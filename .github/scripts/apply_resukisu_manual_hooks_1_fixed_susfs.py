#!/usr/bin/env python3
"""
apply_resukisu_manual_hooks.py  (hardened revision)

CLI compatible with the original:
    python3 apply_resukisu_manual_hooks.py [defconfig]

Drop-in replacement. No change to build-resukisu-manual.yml required.
"""
import os
import re
import sys
import shutil
from pathlib import Path
from datetime import datetime

ROOT = Path(".").resolve()

# ---------- backup ----------
BACKUP_DIR = ROOT / ".resukisu_backup" / datetime.now().strftime("%Y%m%d-%H%M%S")
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

# ---------- small helpers (same names as original) ----------
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
    """marker: idempotency marker (string). If set, used instead of `new in data`."""
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

# ---------- patches ----------
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
        "CONFIG_KALLSYMS=", "CONFIG_KALLSYMS_ALL=",
        "# CONFIG_KALLSYMS_ALL is not set",
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

    # Inline/non-GKI manager compatibility: always force full kallsyms.
    enable_kallsyms_all = True

    lines += [
        "",
        "# ReSukiSU",
        "CONFIG_KSU=y",
        "# CONFIG_KSU_MANUAL_HOOK is not set",
        "CONFIG_KALLSYMS=y",
        # Inline/non-GKI manager compatibility.
        "CONFIG_KALLSYMS_ALL=y",
        "# CONFIG_KSU_KPROBE_HOOKS is not set",
        "# CONFIG_KSU_KPROBES_HOOK is not set",
        "# CONFIG_KSU_KPROBES_HOOKS is not set",
        "# CONFIG_KSU_WITH_KPROBES is not set",
        "",
    ]
    write(path, "\n".join(lines))
    print(f"[OK] enabled ReSukiSU manual hook in {path} "
          f"(KALLSYMS_ALL={'y' if enable_kallsyms_all else 'n'})")

def patch_exec():
    path = "fs/exec.c"
    proto = """#ifdef CONFIG_KSU_MANUAL_HOOK
__attribute__((hot))
extern int ksu_handle_execveat(int *fd, struct filename **filename_ptr,
                               void *argv, void *envp, int *flags);
extern int ksu_handle_execve(const char __user **filename_user,
                             const char __user *const __user **argv,
                             const char __user *const __user **envp);
#endif"""
    insert_before(path, "int do_execve(struct filename *filename,",
                  proto, required=False)

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
    # 🔧 CHANGE (CRITICAL): fail-fast if NEITHER execve variant was hooked.
    if not (hit_a or hit_b) and "ksu_handle_execveat" not in read(path):
        raise RuntimeError(
            "fs/exec.c: NO execveat hook applied — refusing to build a "
            "kernel where execve is unhooked (would bypass su gating)."
        )

    # 🔧 CHANGE (NEW): 32-bit ABI hook — compat_do_execve / compat_do_execveat
    data = read(path)
    if "compat_do_execve" in data and "ksu_handle_execve(&filename" not in data:
        compat_pat = re.compile(
            r"(asmlinkage\s+long\s+compat_do_execve\s*\([^)]*\)\s*\{)"
        )
        m = compat_pat.search(data)
        if m:
            inj = m.group(1) + "\n#ifdef CONFIG_KSU_MANUAL_HOOK\n" \
                  "\tksu_handle_execve(&filename, &argv, &envp);\n#endif"
            write(path, data[:m.start()] + inj + data[m.end():])
            print("[OK] patched compat_do_execve (32-bit)")
        else:
            print("[INFO] compat_do_execve present but signature differs; skipped")

def patch_open():
    path = "fs/open.c"
    data = read(path)
    proto = """#ifdef CONFIG_KSU_MANUAL_HOOK
extern int ksu_handle_faccessat(int *dfd, const char __user **filename_user,
                                int *mode, int *flags);
#endif"""

    # 🔧 CHANGE: support BOTH 3-arg (≤5.7) and 4-arg (≥5.8) do_faccessat
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
        # 🔧 CHANGE: was a silent WARN; faccessat is a primary stat-style
        # bypass vector, so make it loud and fail.
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

    # 🔧 CHANGE (NEW): hook faccessat2 syscall (kernel ≥ 5.8)
    data = read(path)
    if "faccessat2" in data and "ksu_handle_faccessat(&dfd, &filename, &mode, &flags)" not in data:
        f2_pat = re.compile(
            r"SYSCALL_DEFINE4\s*\(\s*faccessat2\s*,[^{]*?\)\s*\{", re.S
        )
        hook2 = ("\n#ifdef CONFIG_KSU_MANUAL_HOOK\n"
                 "\tksu_handle_faccessat(&dfd, &filename, &mode, &flags);\n#endif\n")
        insert_after_declarations(path, f2_pat, hook2, "open.c faccessat2")

def patch_stat():
    path = "fs/stat.c"
    data = read(path)
    proto = """#ifdef CONFIG_KSU_MANUAL_HOOK
__attribute__((hot))
extern int ksu_handle_stat(int *dfd, const char __user **filename_user,
                           int *flags);
extern void ksu_handle_newfstat_ret(unsigned int *fd,
                                    struct stat __user **statbuf_ptr);
#if defined(__ARCH_WANT_STAT64) || defined(__ARCH_WANT_COMPAT_STAT64)
extern void ksu_handle_fstat64_ret(unsigned long *fd,
                                   struct stat64 __user **statbuf_ptr);
#endif
#endif"""
    if "extern int ksu_handle_stat" not in data:
        for marker in ["SYSCALL_DEFINE4(newfstatat",
                       "SYSCALL_DEFINE2(newfstat",
                       "SYSCALL_DEFINE5(statx",     # 🔧 CHANGE: statx fallback
                       "int vfs_statx("]:
            if marker in data:
                insert_before(path, marker, proto, required=False)
                break
        else:
            print("[WARN] cannot find stat marker for prototype")

    # newfstatat
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

    # fstatat64 (32-bit compat)
    # IMPORTANT: check the hook inside the fstatat64 function body only.
    # Do not use a global file-wide check, because newfstatat uses the exact
    # same call text and would otherwise make this compat hook get skipped.
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

    # 🔧 CHANGE (NEW): statx syscall (kernel ≥ 4.11) — modern detection vector
    data = read(path)
    if "SYSCALL_DEFINE5(statx" in data and \
       "ksu_handle_stat(&dfd, &filename, &flags);" not in data:
        sx = re.compile(
            r"SYSCALL_DEFINE5\s*\(\s*statx\s*,[^{]*?\)\s*\{", re.S)
        hook = ("\n#ifdef CONFIG_KSU_MANUAL_HOOK\n"
                "\tksu_handle_stat(&dfd, &filename, &flags);\n#endif\n")
        insert_after_declarations(path, sx, hook, "stat.c statx")

    # newfstat return hook (UNCHANGED — already working per build.log)
    data = read(path)
    if "ksu_handle_newfstat_ret(&fd, &statbuf);" not in data:
        nfs = re.compile(
            r"SYSCALL_DEFINE2\s*\(\s*newfstat\s*,\s*unsigned\s+int\s*,\s*fd\s*,\s*"
            r"struct\s+stat\s+__user\s*\*\s*,\s*statbuf\s*\)\s*\{", re.S)
        span = find_function_span(data, nfs)
        if span:
            s, _, e = span
            body = data[s:e]
            rp = re.compile(r"\n(?P<indent>[ \t]*)return\s+error\s*;")
            m = rp.search(body)
            if m:
                ind = m.group("indent")
                hook = ("\n#ifdef CONFIG_KSU_MANUAL_HOOK\n"
                        f"{ind}ksu_handle_newfstat_ret(&fd, &statbuf);\n#endif")
                body_new = rp.sub(hook + m.group(0), body, count=1)
                write(path, data[:s] + body_new + data[e:])
                print("[OK] patched newfstat return hook")
            else:
                print("[WARN] return error not found in newfstat")
        else:
            print("[WARN] newfstat syscall not found")

    # fstat64 return hook (UNCHANGED)
    data = read(path)
    if "SYSCALL_DEFINE2(fstat64" in data and \
       "ksu_handle_fstat64_ret(&fd, &statbuf);" not in data:
        f64r = re.compile(
            r"SYSCALL_DEFINE2\s*\(\s*fstat64\s*,\s*unsigned\s+long\s*,\s*fd\s*,\s*"
            r"struct\s+stat64\s+__user\s*\*\s*,\s*statbuf\s*\)\s*\{", re.S)
        span = find_function_span(data, f64r)
        if span:
            s, _, e = span
            body = data[s:e]
            rp = re.compile(r"\n(?P<indent>[ \t]*)return\s+error\s*;")
            m = rp.search(body)
            if m:
                ind = m.group("indent")
                hook = ("\n#ifdef CONFIG_KSU_MANUAL_HOOK\n"
                        f"{ind}ksu_handle_fstat64_ret(&fd, &statbuf);\n#endif")
                body_new = rp.sub(hook + m.group(0), body, count=1)
                write(path, data[:s] + body_new + data[e:])
                print("[OK] patched fstat64 return hook")
            else:
                print("[WARN] return error not found in fstat64")

def patch_reboot():
    path = "kernel/reboot.c"
    proto = """#ifdef CONFIG_KSU_MANUAL_HOOK
extern int ksu_handle_sys_reboot(int magic1, int magic2, unsigned int cmd,
                                 void __user **arg);
#endif"""
    data = read(path)
    # cleanup older variants (UNCHANGED logic)
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
    data = re.sub(
        r"#ifdef CONFIG_KSU_MANUAL_HOOK\s*\n\s*ksu_handle_sys_reboot\(magic1, magic2, cmd, arg\);\s*\n#endif\s*\n\s*",
        "", data, flags=re.S)
    data = re.sub(
        r"#ifdef CONFIG_KSU\s*\n\s*ksu_handle_sys_reboot\(magic1, magic2, cmd, arg\);\s*\n#endif\s*\n\s*",
        "", data, flags=re.S)
    write(path, data)

    # 🔧 CHANGE: dual-anchor. First try the historical comment marker (works
    # on stock); fall back to anchoring directly inside SYSCALL_DEFINE4(reboot,…)
    # so forks that stripped the comment are still hooked.
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
            write(path, data); return
        data = (data[:m.end()] +
                "\n\n#ifdef CONFIG_KSU\nEXPORT_SYMBOL_GPL(sel_handle_status_ops);\n#endif\n" +
                data[m.end():])
        print("[OK] exported sel_handle_status_ops in selinuxfs.c")
    else:
        print("[SKIP] sel_handle_status_ops already exported")
    write(path, data)

def patch_selinuxfs_write_op_export():
    path = "security/selinux/selinuxfs.c"
    if not Path(path).exists():
        print("[WARN] selinuxfs.c not found for write_op")
        return
    data = read(path)
    data = ensure_export_header(data)
    data = re.sub(r"\n\s*EXPORT_SYMBOL(?:_GPL)?\s*\(\s*write_op\s*\)\s*;\s*\n",
                  "\n", data)

    # array form (lisa 5.4)
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
            write(path, data); return
        data = (data[:m2.end()] +
                "\n\n#ifdef CONFIG_KSU\nEXPORT_SYMBOL_GPL(write_op);\n#endif\n" +
                data[m2.end():])
        write(path, data)
        print("[OK] exported existing write_op array in selinuxfs.c")
        return

    # pointer form
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

    # 🔧 CHANGE (CRITICAL): the original script had a fallback that *defined*
    # a brand-new write_op symbol when no matching array/pointer was found.
    # That fallback could create a duplicate-symbol link error, OR worse,
    # produce a WRONG type that silently breaks SELinux state spoofing.
    # We REFUSE to fabricate and fail loudly instead.
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


def strip_ksu_manual_hook_guards():
    """Remove only outer CONFIG_KSU_MANUAL_HOOK wrappers from hook sites.
    Keep real ksu_handle_* declarations/calls for SuSFS inline mode.
    """
    targets = [
        "kernel/sys.c", "fs/exec.c", "fs/open.c", "fs/read_write.c",
        "fs/stat.c", "kernel/reboot.c", "drivers/input/input.c",
    ]
    for path in targets:
        p = Path(path)
        if not p.exists():
            continue
        lines = read(p).splitlines(True)
        out = []
        i = 0
        changed = False
        while i < len(lines):
            if lines[i].strip() == "#ifdef CONFIG_KSU_MANUAL_HOOK":
                changed = True
                i += 1
                depth = 1
                while i < len(lines):
                    st = lines[i].strip()
                    if st.startswith("#if"):
                        depth += 1
                        out.append(lines[i])
                    elif st == "#endif":
                        depth -= 1
                        if depth == 0:
                            i += 1
                            break
                        out.append(lines[i])
                    else:
                        out.append(lines[i])
                    i += 1
                continue
            out.append(lines[i])
            i += 1
        if changed:
            write(p, "".join(out))
            print(f"[OK] stripped CONFIG_KSU_MANUAL_HOOK guards from {path}")


def strict_inline_sanity():
    targets = [
        "kernel/sys.c", "fs/exec.c", "fs/open.c", "fs/read_write.c",
        "fs/stat.c", "kernel/reboot.c", "drivers/input/input.c",
    ]
    required = {
        "kernel/sys.c": "ksu_handle_setresuid",
        "fs/exec.c": "ksu_handle_execveat",
        "fs/open.c": "ksu_handle_faccessat",
        "fs/read_write.c": "ksu_handle_sys_read",
        "fs/stat.c": "ksu_handle_stat",
        "kernel/reboot.c": "ksu_handle_sys_reboot",
        "drivers/input/input.c": "ksu_handle_input_handle_event",
    }
    for path in targets:
        p = Path(path)
        if not p.exists():
            continue
        data = read(p)
        if "CONFIG_KSU_MANUAL_HOOK" in data:
            raise RuntimeError(f"{path}: CONFIG_KSU_MANUAL_HOOK guard remains")
        if "ksu_input_hook" in data:
            raise RuntimeError(f"{path}: ksu_input_hook remains")
        if "__weak" in data or re.search(r"(__weak|weak).*ksu_handle_|ksu_handle_.*(__weak|weak)", data):
            raise RuntimeError(f"{path}: weak ksu_handle shim detected")
        if re.search(r"ksu_handle_[A-Za-z0-9_]+\([^;]*\)\s*\{\s*return\s+0;\s*\}", data):
            raise RuntimeError(f"{path}: no-op ksu_handle stub detected")
        if path in required and required[path] not in data:
            raise RuntimeError(f"{path}: missing {required[path]}")
    print("[OK] inline-only sanity passed: no manual guards, no ksu_input_hook, no weak, no no-op stubs")

def main():
    defconfig = sys.argv[1] if len(sys.argv) >= 2 else "lisa_defconfig"
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[INFO] backups -> {BACKUP_DIR}")
    patch_defconfig(defconfig)
    patch_exec()
    patch_open()
    patch_stat()
    patch_reboot()
    patch_selinuxfs_export()
    patch_selinuxfs_write_op_export()
    strip_ksu_manual_hook_guards()
    strict_inline_sanity()
    print("[DONE] ReSukiSU SuSFS inline-only hooks applied.")

if __name__ == "__main__":
    main()