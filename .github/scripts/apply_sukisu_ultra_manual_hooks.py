#!/usr/bin/env python3
"""
apply_sukisu_ultra_manual_hooks.py

Adapted from apply_resukisu_manual_hooks_1_fixed.py (tungnt017/kernel_xiaomi_lisa)
for SukiSU-Ultra builtin branch.

Key differences from the ReSukiSU version:
  - Removed ksu_handle_newfstat_ret hook (not present in SukiSU-Ultra builtin)
  - Removed ksu_handle_fstat64_ret hook  (not present in SukiSU-Ultra builtin)
  - Prototype guard changed: CONFIG_KSU_MANUAL_HOOK (same — required by both)
  - setup command changed: bash -s builtin (not ReSukiSU setup.sh)
  - Comment label changed throughout for clarity

CLI:
    python3 apply_sukisu_ultra_manual_hooks.py [defconfig]

Environment:
    SUKISU_KALLSYMS_ALL=1   Force CONFIG_KALLSYMS_ALL=y (default: n)
"""

import os
import re
import sys
import shutil
from pathlib import Path
from datetime import datetime

ROOT = Path(".").resolve()

# ---------- backup ----------
BACKUP_DIR = ROOT / ".sukisu_backup" / datetime.now().strftime("%Y%m%d-%H%M%S")
_backed_up: set[Path] = set()


def _backup(path: Path):
    if path in _backed_up or not path.exists():
        return
    try:
        rel = path.resolve().relative_to(ROOT)
    except ValueError:
        rel = Path(path.name)
    dst = BACKUP_DIR / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dst)
    _backed_up.add(path)


# ---------- io ----------
def read(path):
    return Path(path).read_text(errors="ignore")


def write(path, data):
    p = Path(path)
    _backup(p)
    p.write_text(data)


# ---------- helpers ----------
def insert_before(path, marker, block, required=True):
    p = Path(path)
    data = read(p)
    if block.strip() in data:
        print(f"[SKIP] block already exists: {path}")
        return True
    if marker not in data:
        msg = f"[MISS] marker not found in {path}: {marker}"
        if required:
            raise RuntimeError(msg)
        print(msg)
        return False
    data = data.replace(marker, block + "\n\n" + marker, 1)
    write(p, data)
    print(f"[OK] inserted block: {path}")
    return True


def replace_once(path, old, new, required=True, marker=None):
    """marker: idempotency sentinel string. If set, used instead of `new in data`."""
    p = Path(path)
    data = read(p)
    sentinel = marker if marker is not None else new
    if sentinel in data:
        print(f"[SKIP] already patched: {path}")
        return True
    if old not in data:
        msg = f"[MISS] context not found in {path}"
        if required:
            raise RuntimeError(msg + f":\n{old}")
        print(msg)
        return False
    data = data.replace(old, new, 1)
    write(p, data)
    print(f"[OK] patched: {path}")
    return True


def find_function_span(data, pattern):
    m = pattern.search(data)
    if not m:
        return None
    brace_start = data.find("{", m.start())
    if brace_start < 0:
        return None
    depth = 0
    for i in range(brace_start, len(data)):
        c = data[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return m.start(), brace_start, i + 1
    return None


def insert_after_declarations(path, func_pattern, hook, label):
    data = read(path)
    span = find_function_span(data, func_pattern)
    if not span:
        print(f"[WARN] {label} function not found")
        return False
    start, brace_start, end = span
    body = data[brace_start + 1:end - 1]
    if hook.strip() in body:
        print(f"[SKIP] {label} already patched")
        return True
    lines = body.splitlines(True)
    insert_index = 0
    decl_re = re.compile(
        r"^\s*(?:const\s+)?(?:"
        r"struct|unsigned|signed|int|long|short|char|bool|umode_t|"
        r"uid_t|gid_t|kuid_t|kgid_t|loff_t|size_t|ssize_t|u8|u16|u32|u64|"
        r"s8|s16|s32|s64|enum"
        r")\b.*;\s*(?:/\*.*\*/)?\s*$"
    )
    blank_re = re.compile(r"^\s*$|^\s*/\*.*\*/\s*$|^\s*//.*$")
    for idx, line in enumerate(lines):
        if blank_re.match(line):
            insert_index = idx + 1
            continue
        if decl_re.match(line):
            insert_index = idx + 1
            continue
        break
    lines.insert(insert_index, hook)
    write(path, data[:brace_start + 1] + "".join(lines) + data[end - 1:])
    print(f"[OK] patched {label} after declarations")
    return True


# ============================================================
# patches
# ============================================================

def patch_defconfig(defconfig):
    candidates = [
        ROOT / "arch" / "arm64" / "configs" / defconfig,
        ROOT / "arch" / "arm64" / "configs" / "vendor" / defconfig,
    ]
    path = next((c for c in candidates if c.exists()), None)
    if path is None:
        print("[ERROR] defconfig not found.")
        print("Available defconfigs:")
        for f in sorted((ROOT / "arch" / "arm64" / "configs").rglob("*defconfig")):
            print(f"  - {f}")
        sys.exit(1)

    remove_prefixes = [
        "CONFIG_KSU=", "CONFIG_KSU_MANUAL_HOOK=",
        "CONFIG_KSU_KPROBE_HOOKS=", "CONFIG_KSU_KPROBES_HOOK=",
        "CONFIG_KSU_KPROBES_HOOKS=", "CONFIG_KSU_WITH_KPROBES=",
        "CONFIG_KALLSYMS=",
        "# CONFIG_KSU is not set",
        "# CONFIG_KSU_MANUAL_HOOK is not set",
        "# CONFIG_KSU_KPROBE_HOOKS is not set",
        "# CONFIG_KSU_KPROBES_HOOK is not set",
        "# CONFIG_KSU_KPROBES_HOOKS is not set",
        "# CONFIG_KSU_WITH_KPROBES is not set",
        "# CONFIG_KALLSYMS is not set",
    ]
    lines = [l for l in read(path).splitlines()
             if not any(l.startswith(p) for p in remove_prefixes)]

    enable_kallsyms_all = os.environ.get("SUKISU_KALLSYMS_ALL", "0") == "1"

    lines += [
        "",
        "# SukiSU-Ultra builtin",
        "CONFIG_KSU=y",
        "CONFIG_KSU_MANUAL_HOOK=y",
        "CONFIG_KALLSYMS=y",
        f"CONFIG_KALLSYMS_ALL={'y' if enable_kallsyms_all else 'n'}",
        "# CONFIG_KSU_KPROBE_HOOKS is not set",
        "# CONFIG_KSU_KPROBES_HOOK is not set",
        "# CONFIG_KSU_KPROBES_HOOKS is not set",
        "# CONFIG_KSU_WITH_KPROBES is not set",
        "",
    ]
    write(path, "\n".join(lines))
    print(f"[OK] enabled SukiSU-Ultra manual hook in {path} "
          f"(KALLSYMS_ALL={'y' if enable_kallsyms_all else 'n'})")


# ------------------------------------------------------------------
# fs/exec.c
# Hooks: ksu_handle_execveat (3.14+), ksu_handle_execve_sucompat (3.14-)
# Both present in SukiSU-Ultra builtin feature/sucompat.c
# ------------------------------------------------------------------
def patch_exec():
    path = "fs/exec.c"

    # Prototype block — declares both variants under one guard
    proto = """#ifdef CONFIG_KSU_MANUAL_HOOK
__attribute__((hot))
extern int ksu_handle_execveat(int *fd, struct filename **filename_ptr,
                               void *argv, void *envp, int *flags);
extern int ksu_handle_execve_sucompat(int *fd, const char __user **filename_user,
                                      void *argv, void *envp, int *flags);
#endif"""
    insert_before(path, "int do_execve(struct filename *filename,",
                  proto, required=False)

    # do_execve: AT_FDCWD (non-fd) path — kernel 3.14+
    hit_a = replace_once(
        path,
        """\treturn do_execveat_common(AT_FDCWD, filename, argv, envp, 0);""",
        """#ifdef CONFIG_KSU_MANUAL_HOOK
    ksu_handle_execveat((int *)AT_FDCWD, &filename, &argv, &envp, 0);
#endif
    return do_execveat_common(AT_FDCWD, filename, argv, envp, 0);""",
        required=False,
        marker="ksu_handle_execveat((int *)AT_FDCWD",
    )

    # do_execveat_common: fd path (when do_execveat is present)
    hit_b = replace_once(
        path,
        """\treturn do_execveat_common(fd, filename, argv, envp, flags);""",
        """#ifdef CONFIG_KSU_MANUAL_HOOK
    ksu_handle_execveat(&fd, &filename, &argv, &envp, &flags);
#endif
    return do_execveat_common(fd, filename, argv, envp, flags);""",
        required=False,
        marker="ksu_handle_execveat(&fd, &filename, &argv, &envp, &flags);",
    )

    # Fail loudly if neither do_execve variant was hooked
    if not (hit_a or hit_b) and "ksu_handle_execveat" not in read(path):
        raise RuntimeError(
            "fs/exec.c: NO execveat hook applied — refusing to build a "
            "kernel where execve is unhooked (would bypass su gating)."
        )

    # compat_do_execve: 32-bit ABI / 32-on-64 (kernel 3.14+, struct filename path)
    # SukiSU-Ultra uses ksu_handle_execveat for the compat path too
    data = read(path)
    if "compat_do_execve" in data and "ksu_handle_execveat((int *)AT_FDCWD, &filename" not in data:
        # Try struct filename ** signature first (3.14+)
        compat_pat = re.compile(
            r"(static\s+int\s+compat_do_execve\s*\(\s*struct\s+filename\s*\*[^)]*\)\s*\{)"
        )
        m = compat_pat.search(data)
        if m:
            inj = (m.group(1) +
                   "\n#ifdef CONFIG_KSU_MANUAL_HOOK\n"
                   "\tksu_handle_execveat((int *)AT_FDCWD, &filename, &argv, &envp, 0);\n#endif")
            write(path, data[:m.start()] + inj + data[m.end():])
            print("[OK] patched compat_do_execve (32-bit, struct filename)")
        else:
            # Older form: const char __user * — use ksu_handle_execve_sucompat
            compat_old = re.compile(
                r"((?:asmlinkage\s+)?(?:int|long)\s+compat_do_execve\s*\(\s*"
                r"(?:struct\s+filename\s*\*|const\s+char\s+__user\s*\*)[^)]*\)\s*\{)"
            )
            m2 = compat_old.search(data)
            if m2 and "ksu_handle_execve_sucompat" not in data:
                inj2 = (m2.group(1) +
                        "\n#ifdef CONFIG_KSU_MANUAL_HOOK\n"
                        "\tksu_handle_execve_sucompat((int *)AT_FDCWD, &filename, &argv, &envp, 0);\n#endif")
                write(path, data[:m2.start()] + inj2 + data[m2.end():])
                print("[OK] patched compat_do_execve (32-bit, sucompat path)")
            else:
                print("[INFO] compat_do_execve present but signature differs; skipped")


# ------------------------------------------------------------------
# fs/open.c
# Hook: ksu_handle_faccessat
# Present in SukiSU-Ultra builtin feature/sucompat.c
# ------------------------------------------------------------------
def patch_open():
    path = "fs/open.c"
    data = read(path)
    proto = """#ifdef CONFIG_KSU_MANUAL_HOOK
extern int ksu_handle_faccessat(int *dfd, const char __user **filename_user,
                                int *mode, int *flags);
#endif"""

    # Support both 4-arg (≥5.8) and 3-arg (≤5.7) do_faccessat
    patterns = [
        re.compile(
            r"(?:static\s+)?(?:long|int)\s+do_faccessat\s*\(\s*"
            r"int\s+dfd\s*,\s*const\s+char\s+__user\s+\*filename\s*,\s*"
            r"int\s+mode\s*,\s*int\s+flags\s*\)\s*\{",
            re.S),
        re.compile(
            r"(?:static\s+)?(?:long|int)\s+do_faccessat\s*\(\s*"
            r"int\s+dfd\s*,\s*const\s+char\s+__user\s+\*filename\s*,\s*"
            r"int\s+mode\s*\)\s*\{",
            re.S),
    ]
    span = None
    chosen = None
    for fp in patterns:
        span = find_function_span(data, fp)
        if span:
            chosen = fp
            break

    if not span:
        raise RuntimeError("fs/open.c: do_faccessat() not found in any "
                           "known signature — refusing to build.")

    start, _, _ = span
    if "extern int ksu_handle_faccessat" not in data:
        data = data[:start] + proto + "\n\n" + data[start:]
        write(path, data)
        print("[OK] inserted faccessat prototype")

    hook = ("\n#ifdef CONFIG_KSU_MANUAL_HOOK\n"
            "\tksu_handle_faccessat(&dfd, &filename, &mode, NULL);\n#endif\n")
    insert_after_declarations(path, chosen, hook, "open.c faccessat")

    # faccessat2 syscall (kernel ≥ 5.8)
    data = read(path)
    if "faccessat2" in data and "ksu_handle_faccessat(&dfd, &filename, &mode, &flags)" not in data:
        f2_pat = re.compile(
            r"SYSCALL_DEFINE4\s*\(\s*faccessat2\s*,[^{]*?\)\s*\{", re.S
        )
        hook2 = ("\n#ifdef CONFIG_KSU_MANUAL_HOOK\n"
                 "\tksu_handle_faccessat(&dfd, &filename, &mode, &flags);\n#endif\n")
        insert_after_declarations(path, f2_pat, hook2, "open.c faccessat2")


# ------------------------------------------------------------------
# fs/stat.c
# Hooks: ksu_handle_stat (newfstatat, fstatat64, statx)
#
# NOTE: ksu_handle_newfstat_ret and ksu_handle_fstat64_ret are
# intentionally OMITTED — these are ReSukiSU-specific return-value
# hooks not present in SukiSU-Ultra builtin. Including them would
# cause linker errors (undefined reference).
# ------------------------------------------------------------------
def patch_stat():
    path = "fs/stat.c"
    data = read(path)

    # Prototype block — only ksu_handle_stat, no ret hooks
    proto = """#ifdef CONFIG_KSU_MANUAL_HOOK
__attribute__((hot))
extern int ksu_handle_stat(int *dfd, const char __user **filename_user,
                           int *flags);
#endif"""

    if "extern int ksu_handle_stat" not in data:
        for marker in ["SYSCALL_DEFINE4(newfstatat",
                       "SYSCALL_DEFINE2(newfstat",
                       "SYSCALL_DEFINE5(statx",
                       "int vfs_statx("]:
            if marker in data:
                insert_before(path, marker, proto, required=False)
                break
        else:
            print("[WARN] cannot find stat marker for prototype")

    # newfstatat — primary stat detection vector
    data = read(path)
    if "ksu_handle_stat(&dfd, &filename, &flag);" not in data:
        nfa = re.compile(
            r"SYSCALL_DEFINE4\s*\(\s*newfstatat\s*,\s*int\s*,\s*dfd\s*,\s*"
            r"const\s+char\s+__user\s*\*\s*,\s*filename\s*,\s*"
            r"struct\s+stat\s+__user\s*\*\s*,\s*statbuf\s*,\s*int\s*,\s*flag\s*\)\s*\{",
            re.S)
        hook = ("\n#ifdef CONFIG_KSU_MANUAL_HOOK\n"
                "\tksu_handle_stat(&dfd, &filename, &flag);\n#endif\n")
        if find_function_span(data, nfa):
            insert_after_declarations(path, nfa, hook, "stat.c newfstatat")
        else:
            print("[WARN] newfstatat not found, trying vfs_statx fallback")
            vfs = re.compile(
                r"int\s+vfs_statx\s*\(\s*int\s+dfd\s*,\s*const\s+char\s+"
                r"__user\s+\*filename\s*,\s*int\s+flags\s*,.*?\)\s*\{", re.S)
            hook_vfs = ("\n#ifdef CONFIG_KSU_MANUAL_HOOK\n"
                        "\tksu_handle_stat(&dfd, &filename, &flags);\n#endif\n")
            insert_after_declarations(path, vfs, hook_vfs, "stat.c vfs_statx")

    # fstatat64 — 32-bit compat stat
    # Check per-function body to avoid false-positive from newfstatat's identical call text
    data = read(path)
    if "SYSCALL_DEFINE4(fstatat64" in data:
        f64 = re.compile(
            r"SYSCALL_DEFINE4\s*\(\s*fstatat64\s*,\s*int\s*,\s*dfd\s*,\s*"
            r"const\s+char\s+__user\s*\*\s*,\s*filename\s*,.*?int\s*,\s*flag\s*\)\s*\{",
            re.S)
        span = find_function_span(data, f64)
        if span:
            _, brace_start, end = span
            body = data[brace_start + 1:end - 1]
            if "ksu_handle_stat(&dfd, &filename, &flag);" not in body:
                hook = ("\n#ifdef CONFIG_KSU_MANUAL_HOOK\n"
                        "\tksu_handle_stat(&dfd, &filename, &flag);\n#endif\n")
                insert_after_declarations(path, f64, hook, "stat.c fstatat64")
            else:
                print("[SKIP] stat.c fstatat64 already patched")
        else:
            print("[WARN] fstatat64 syscall exists but function pattern not matched")

    # statx — modern stat syscall (kernel ≥ 4.11), additional detection vector
    data = read(path)
    if "SYSCALL_DEFINE5(statx" in data and \
       "ksu_handle_stat(&dfd, &filename, &flags);" not in data:
        sx = re.compile(
            r"SYSCALL_DEFINE5\s*\(\s*statx\s*,[^{]*?\)\s*\{", re.S)
        hook = ("\n#ifdef CONFIG_KSU_MANUAL_HOOK\n"
                "\tksu_handle_stat(&dfd, &filename, &flags);\n#endif\n")
        insert_after_declarations(path, sx, hook, "stat.c statx")


# ------------------------------------------------------------------
# kernel/reboot.c
# Hook: ksu_handle_sys_reboot
# Present in SukiSU-Ultra builtin supercall/dispatch.c
# ------------------------------------------------------------------
def patch_reboot():
    path = "kernel/reboot.c"
    proto = """#ifdef CONFIG_KSU_MANUAL_HOOK
extern int ksu_handle_sys_reboot(int magic1, int magic2, unsigned int cmd,
                                 void __user **arg);
#endif"""
    data = read(path)

    # Clean up any older/malformed variants from previous patch attempts
    data = re.sub(
        r"#ifdef CONFIG_KSU_MANUAL_HOOK\s*\n"
        r"extern int ksu_handle_sys_reboot\(int magic1, int magic2, unsigned int cmd,\s*\n"
        r"\s*void __user \*arg\);\s*\n#endif\s*\n\s*",
        "", data, flags=re.S)
    data = re.sub(
        r"#ifdef CONFIG_KSU\s*\n"
        r"extern int ksu_handle_sys_reboot\(int magic1, int magic2, unsigned int cmd,\s*void __user \*arg\);\s*\n"
        r"#endif\s*\n\s*",
        "", data, flags=re.S)
    write(path, data)

    insert_before(path, "SYSCALL_DEFINE4(reboot,", proto, required=False)

    data = read(path)
    # Clean up old call variants (wrong &arg vs arg)
    data = re.sub(
        r"#ifdef CONFIG_KSU_MANUAL_HOOK\s*\n\s*ksu_handle_sys_reboot\(magic1, magic2, cmd, arg\);\s*\n#endif\s*\n\s*",
        "", data, flags=re.S)
    data = re.sub(
        r"#ifdef CONFIG_KSU\s*\n\s*ksu_handle_sys_reboot\(magic1, magic2, cmd, arg\);\s*\n#endif\s*\n\s*",
        "", data, flags=re.S)
    write(path, data)

    # Primary anchor: historical comment marker (present in stock lahaina/lisa)
    ok = replace_once(
        path,
        """\t/* For safety, we require "magic" arguments. */""",
        """#ifdef CONFIG_KSU_MANUAL_HOOK
    ksu_handle_sys_reboot(magic1, magic2, cmd, &arg);
#endif
    /* For safety, we require "magic" arguments. */""",
        required=False,
        marker="ksu_handle_sys_reboot(magic1, magic2, cmd, &arg);",
    )
    # Fallback anchor: inject directly after SYSCALL_DEFINE4(reboot,...){
    if not ok:
        data = read(path)
        if "ksu_handle_sys_reboot(magic1, magic2, cmd, &arg);" not in data:
            sd_pat = re.compile(
                r"(SYSCALL_DEFINE4\s*\(\s*reboot\s*,[^{]*?\)\s*\{)", re.S)
            m = sd_pat.search(data)
            if not m:
                raise RuntimeError("kernel/reboot.c: SYSCALL_DEFINE4(reboot,...) "
                                   "not found — refusing to build.")
            inj = m.group(1) + ("\n#ifdef CONFIG_KSU_MANUAL_HOOK\n"
                                 "\tksu_handle_sys_reboot(magic1, magic2, cmd, &arg);\n#endif")
            write(path, data[:m.start()] + inj + data[m.end():])
            print("[OK] patched sys_reboot via SYSCALL_DEFINE4 anchor (fallback)")


# ------------------------------------------------------------------
# security/selinux/selinuxfs.c
# Export: sel_handle_status_ops (static -> non-static + EXPORT_SYMBOL_GPL)
# ------------------------------------------------------------------
def ensure_export_header(data):
    if "#include <linux/export.h>" in data:
        return data
    if "#include <linux/kernel.h>" in data:
        return data.replace("#include <linux/kernel.h>",
                            "#include <linux/kernel.h>\n#include <linux/export.h>", 1)
    return "#include <linux/export.h>\n" + data


def patch_selinuxfs_export():
    path = "security/selinux/selinuxfs.c"
    if not Path(path).exists():
        print("[WARN] selinuxfs.c not found")
        return
    data = read(path)
    if "sel_handle_status_ops" not in data:
        print("[WARN] sel_handle_status_ops not found in selinuxfs.c")
        return
    data = ensure_export_header(data)
    data = data.replace("static const struct file_operations sel_handle_status_ops",
                        "const struct file_operations sel_handle_status_ops")
    data = data.replace("static struct file_operations sel_handle_status_ops",
                        "struct file_operations sel_handle_status_ops")
    if "EXPORT_SYMBOL_GPL(sel_handle_status_ops);" not in data and \
       "EXPORT_SYMBOL(sel_handle_status_ops);" not in data:
        pat = re.compile(
            r"((?:const\s+)?struct\s+file_operations\s+sel_handle_status_ops\s*=\s*\{.*?\};)",
            re.S)
        m = pat.search(data)
        if not m:
            print("[WARN] sel_handle_status_ops definition block not matched")
            write(path, data)
            return
        data = (data[:m.end()] +
                "\n\n#ifdef CONFIG_KSU\nEXPORT_SYMBOL_GPL(sel_handle_status_ops);\n#endif\n" +
                data[m.end():])
        print("[OK] exported sel_handle_status_ops in selinuxfs.c")
    else:
        print("[SKIP] sel_handle_status_ops already exported")
    write(path, data)


# ------------------------------------------------------------------
# security/selinux/selinuxfs.c
# Export: write_op (static -> non-static + EXPORT_SYMBOL_GPL)
# Handles both array form (lisa 5.4) and pointer form
# ------------------------------------------------------------------
def patch_selinuxfs_write_op_export():
    path = "security/selinux/selinuxfs.c"
    if not Path(path).exists():
        print("[WARN] selinuxfs.c not found for write_op")
        return
    data = read(path)
    data = ensure_export_header(data)
    # Remove any pre-existing EXPORT for write_op to avoid duplicates
    data = re.sub(r"\n\s*EXPORT_SYMBOL(?:_GPL)?\s*\(\s*write_op\s*\)\s*;\s*\n",
                  "\n", data)

    # Array form: ssize_t (* const write_op[])(...) = {...};   — lisa 5.4 layout
    array_pat = re.compile(
        r"(?P<prefix>static\s+)?(?P<decl>ssize_t\s*\(\s*\*\s*const\s+write_op\s*\[\s*\]\s*\)\s*"
        r"\(\s*struct\s+file\s*\*\s*,\s*char\s*\*\s*,\s*size_t\s*\)\s*=\s*\{.*?\};)",
        re.S)
    m = array_pat.search(data)
    if m:
        s, e = m.span()
        data = data[:s] + m.group("decl") + data[e:]
        m2 = re.search(
            r"ssize_t\s*\(\s*\*\s*const\s+write_op\s*\[\s*\]\s*\)\s*"
            r"\(\s*struct\s+file\s*\*\s*,\s*char\s*\*\s*,\s*size_t\s*\)\s*=\s*\{.*?\};",
            data, re.S)
        if not m2:
            print("[WARN] write_op array became unmatchable after static removal")
            write(path, data)
            return
        data = (data[:m2.end()] +
                "\n\n#ifdef CONFIG_KSU\nEXPORT_SYMBOL_GPL(write_op);\n#endif\n" +
                data[m2.end():])
        write(path, data)
        print("[OK] exported existing write_op array in selinuxfs.c")
        return

    # Pointer form: ssize_t (*write_op)(struct file *, ...) = ...;
    ptr_pat = re.compile(
        r"(?P<prefix>static\s+)?(?P<decl>ssize_t\s*\(\s*\*\s*write_op\s*\)\s*"
        r"\(\s*struct\s+file\s*\*\s*file\s*,\s*const\s+char\s+__user\s*\*\s*buf\s*,\s*"
        r"size_t\s+count\s*,\s*loff_t\s*\*\s*ppos\s*\)\s*(?:=\s*[^;]+)?;)",
        re.S)
    m = ptr_pat.search(data)
    if m:
        s, e = m.span()
        data = data[:s] + m.group("decl") + data[e:]
        m2 = ptr_pat.search(data)
        pos = m2.end() if m2 else s + len(m.group("decl"))
        data = (data[:pos] +
                "\n\n#ifdef CONFIG_KSU\nEXPORT_SYMBOL_GPL(write_op);\n#endif\n" +
                data[pos:])
        write(path, data)
        print("[OK] exported existing write_op pointer in selinuxfs.c")
        return

    # Refuse to fabricate — avoids duplicate symbol / wrong ABI
    if "write_op" in data:
        raise RuntimeError(
            "selinuxfs.c: write_op symbol exists but neither array nor "
            "pointer pattern matched — kernel layout is unexpected. "
            "Refusing to fabricate a duplicate symbol."
        )
    raise RuntimeError(
        "selinuxfs.c: no write_op definition found at all. "
        "Refusing to inject a fake one (would mismatch SELinux ABI)."
    )


# ============================================================
# entry point
# ============================================================

def main():
    defconfig = sys.argv[1] if len(sys.argv) >= 2 else "lisa_defconfig"
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[INFO] backups -> {BACKUP_DIR}")
    print(f"[INFO] defconfig: {defconfig}")
    print(f"[INFO] kernel root: {ROOT}")
    print()

    patch_defconfig(defconfig)
    patch_exec()
    patch_open()
    patch_stat()
    patch_reboot()
    patch_selinuxfs_export()
    patch_selinuxfs_write_op_export()

    print()
    print("[DONE] SukiSU-Ultra builtin manual hooks applied.")
    print()
    print("Next steps:")
    print("  1. curl -LSs https://raw.githubusercontent.com/SukiSU-Ultra/SukiSU-Ultra/main/kernel/setup.sh | bash -s builtin")
    print("  2. Apply susfs patches if needed (JackA1ltman/NonGKI_Kernel_Patches)")
    print("  3. make O=out ARCH=arm64 <defconfig> && make O=out ARCH=arm64 -j$(nproc)")


if __name__ == "__main__":
    main()
