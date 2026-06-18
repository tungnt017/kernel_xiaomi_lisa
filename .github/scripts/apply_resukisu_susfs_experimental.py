#!/usr/bin/env python3
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(".").resolve()

def read(path):
    return Path(path).read_text(errors="ignore")

def write(path, data):
    Path(path).write_text(data)

def run(cmd, cwd=None, check=True):
    print(f"[RUN] {cmd} cwd={cwd or ROOT}")
    p = subprocess.run(cmd, shell=True, cwd=cwd, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"command failed: {cmd}")
    return p.returncode

def bool_env(name, default=False):
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "y", "on")

def find_defconfig(defconfig):
    candidates = [
        ROOT / "arch" / "arm64" / "configs" / defconfig,
        ROOT / "arch" / "arm64" / "configs" / "vendor" / defconfig,
    ]
    for c in candidates:
        if c.exists():
            return c
    print("[ERROR] defconfig not found")
    for f in sorted((ROOT / "arch" / "arm64" / "configs").rglob("*defconfig")):
        print(f" - {f}")
    sys.exit(1)

def patch_defconfig_susfs(defconfig):
    path = find_defconfig(defconfig)
    data = read(path)
    remove_prefixes = [
        "CONFIG_KSU_SUSFS=", "CONFIG_KSU_SUSFS_HAS_MAGIC_MOUNT=", "CONFIG_KSU_SUSFS_SUS_PATH=",
        "CONFIG_KSU_SUSFS_SUS_MOUNT=", "CONFIG_KSU_SUSFS_AUTO_ADD_SUS_KSU_DEFAULT_MOUNT=",
        "CONFIG_KSU_SUSFS_AUTO_ADD_SUS_BIND_MOUNT=", "CONFIG_KSU_SUSFS_SUS_KSTAT=",
        "CONFIG_KSU_SUSFS_TRY_UMOUNT=", "CONFIG_KSU_SUSFS_AUTO_ADD_TRY_UMOUNT_FOR_BIND_MOUNT=",
        "CONFIG_KSU_SUSFS_SPOOF_UNAME=", "CONFIG_KSU_SUSFS_ENABLE_LOG=",
        "CONFIG_KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS=", "CONFIG_KSU_SUSFS_SUS_SU=",
        "# CONFIG_KSU_SUSFS is not set", "# CONFIG_KSU_SUSFS_HAS_MAGIC_MOUNT is not set",
        "# CONFIG_KSU_SUSFS_SUS_PATH is not set", "# CONFIG_KSU_SUSFS_SUS_MOUNT is not set",
        "# CONFIG_KSU_SUSFS_AUTO_ADD_SUS_KSU_DEFAULT_MOUNT is not set",
        "# CONFIG_KSU_SUSFS_AUTO_ADD_SUS_BIND_MOUNT is not set", "# CONFIG_KSU_SUSFS_SUS_KSTAT is not set",
        "# CONFIG_KSU_SUSFS_TRY_UMOUNT is not set", "# CONFIG_KSU_SUSFS_AUTO_ADD_TRY_UMOUNT_FOR_BIND_MOUNT is not set",
        "# CONFIG_KSU_SUSFS_SPOOF_UNAME is not set", "# CONFIG_KSU_SUSFS_ENABLE_LOG is not set",
        "# CONFIG_KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS is not set", "# CONFIG_KSU_SUSFS_SUS_SU is not set",
    ]
    lines = [line for line in data.splitlines() if not any(line.startswith(prefix) for prefix in remove_prefixes)]
    lines += [
        "", "# ReSukiSU SUSFS experimental", "CONFIG_KSU=y", "CONFIG_KSU_SUSFS=y",
        "CONFIG_KSU_SUSFS_HAS_MAGIC_MOUNT=y", "CONFIG_KSU_SUSFS_SUS_PATH=y", "CONFIG_KSU_SUSFS_SUS_MOUNT=y",
        "CONFIG_KSU_SUSFS_AUTO_ADD_SUS_KSU_DEFAULT_MOUNT=y", "CONFIG_KSU_SUSFS_AUTO_ADD_SUS_BIND_MOUNT=y",
        "CONFIG_KSU_SUSFS_SUS_KSTAT=y", "CONFIG_KSU_SUSFS_TRY_UMOUNT=y",
        "CONFIG_KSU_SUSFS_AUTO_ADD_TRY_UMOUNT_FOR_BIND_MOUNT=y", "CONFIG_KSU_SUSFS_SPOOF_UNAME=y",
        "CONFIG_KSU_SUSFS_ENABLE_LOG=y", "CONFIG_KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS=y",
        "# CONFIG_KSU_SUSFS_SUS_SU is not set", "",
    ]
    write(path, "\n".join(lines) + "\n")
    print(f"[OK] enabled SUSFS experimental config in {path}")

def copy_tree_files(src_dir, dst_dir):
    src = Path(src_dir)
    dst = Path(dst_dir)
    if not src.exists():
        print(f"[WARN] missing {src}")
        return
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.is_file():
            target = dst / item.name
            shutil.copy2(item, target)
            print(f"[OK] copied {item} -> {target}")

def apply_patch(patch_file, cwd, continue_on_fail):
    patch_file = Path(patch_file).resolve()
    if not patch_file.exists():
        print(f"[WARN] patch missing: {patch_file}")
        if continue_on_fail:
            return
        raise FileNotFoundError(str(patch_file))
    rc = run(f"patch -p1 --forward --batch < '{patch_file}'", cwd=cwd, check=False)
    if rc != 0:
        msg = f"[WARN] patch failed/rejected: {patch_file}"
        if continue_on_fail:
            print(msg)
            return
        raise RuntimeError(msg)
    print(f"[OK] applied patch {patch_file} in {cwd}")

def find_kernel_patch(susfs_dir, requested):
    kp = Path(susfs_dir) / "kernel_patches"
    if requested:
        for requested_path in (kp / requested, Path(susfs_dir) / requested):
            if requested_path.exists():
                return requested_path
        raise FileNotFoundError(f"requested SUSFS kernel patch not found: {requested}")
    for pat in ["50_add_susfs_in_kernel-5.4*.patch", "50_add_susfs_in_kernel*.patch", "*5.4*.patch"]:
        matches = sorted(kp.glob(pat))
        if matches:
            print(f"[OK] auto selected SUSFS kernel patch: {matches[0]}")
            return matches[0]
    raise FileNotFoundError("cannot auto-find SUSFS kernel patch under kernel_patches")

def insert_after_last_decl_in_function(data, func_regex, hook, label):
    m = re.search(func_regex, data, re.S)
    if not m:
        print(f"[WARN] {label}: function not found")
        return data, False
    brace = data.find("{", m.start())
    depth = 0
    end = None
    for i in range(brace, len(data)):
        if data[i] == "{": depth += 1
        elif data[i] == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end is None:
        print(f"[WARN] {label}: function end not found")
        return data, False
    body = data[brace+1:end]
    if hook.strip() in body:
        print(f"[SKIP] {label}: hook already exists")
        return data, True
    lines = body.splitlines(True)
    decl = re.compile(r"^\s*(?:const\s+)?(?:struct|unsigned|signed|int|long|short|char|bool|kuid_t|kgid_t|uid_t|gid_t|umode_t|loff_t|size_t|ssize_t|u8|u16|u32|u64|s8|s16|s32|s64|enum)\b.*;\s*$")
    blank_comment = re.compile(r"^\s*$|^\s*/\*.*\*/\s*$|^\s*//.*$")
    idx = 0
    for n, line in enumerate(lines):
        if blank_comment.match(line) or decl.match(line):
            idx = n + 1
            continue
        break
    lines.insert(idx, hook)
    print(f"[OK] {label}: inserted after declarations")
    return data[:brace+1] + "".join(lines) + data[end:], True

def patch_setresuid_hook():
    path = ROOT / "kernel" / "sys.c"
    if not path.exists():
        print("[WARN] kernel/sys.c not found")
        return
    data = read(path)
    # Remove wrong hook placed before declarations from previous revisions.
    data = re.sub(r"\n#ifdef CONFIG_KSU_SUSFS\s*\n\s*\(void\)ksu_handle_setresuid\(ruid, euid, suid\);\s*\n#endif\s*\n(?=\s*struct user_namespace \*ns)", "\n", data, flags=re.S)
    data = re.sub(r"\n#if defined\(CONFIG_KSU\)\s*\n\s*ksu_handle_setresuid\(ruid, euid, suid\);\s*\n#endif\s*\n", "\n", data, flags=re.S)
    proto = """#ifdef CONFIG_KSU_SUSFS
extern int ksu_handle_setresuid(uid_t ruid, uid_t euid, uid_t suid);
#endif"""
    if "extern int ksu_handle_setresuid(uid_t ruid, uid_t euid, uid_t suid);" not in data:
        marker = "long __sys_setresuid(uid_t ruid, uid_t euid, uid_t suid)"
        if marker in data:
            data = data.replace(marker, proto + "\n\n" + marker, 1)
            print("[OK] inserted ksu_handle_setresuid prototype in kernel/sys.c")
    hook = """
#ifdef CONFIG_KSU_SUSFS
	(void)ksu_handle_setresuid(ruid, euid, suid);
#endif
"""
    data, _ = insert_after_last_decl_in_function(
        data,
        r"long\s+__sys_setresuid\s*\(\s*uid_t\s+ruid\s*,\s*uid_t\s+euid\s*,\s*uid_t\s+suid\s*\)",
        hook,
        "kernel/sys.c __sys_setresuid",
    )
    write(path, data)

def patch_sys_read_hook():
    path = ROOT / "fs" / "read_write.c"
    if not path.exists():
        print("[WARN] fs/read_write.c not found")
        return
    data = read(path)
    data = re.sub(r"\n\s*#ifdef\s+CONFIG_KSU(?:_SUSFS)?\s*\n\s*extern\s+int\s+ksu_handle_sys_read\s*\([^;]+;\s*\n\s*#endif\s*\n", "\n", data, flags=re.S)
    data = re.sub(r"\n\s*#ifdef\s+CONFIG_KSU(?:_SUSFS)?\s*\n\s*ksu_handle_sys_read\s*\(\s*fd\s*,\s*&buf\s*,\s*&count\s*\)\s*;\s*\n\s*#endif\s*\n", "\n", data, flags=re.S)
    # Remove previous hook before declaration.
    data = re.sub(r"\n#ifdef CONFIG_KSU_SUSFS\s*\n\s*ksu_handle_sys_read\(fd\);\s*\n#endif\s*\n(?=\s*struct fd f)", "\n", data, flags=re.S)
    proto = """#ifdef CONFIG_KSU_SUSFS
extern __attribute__((cold)) void ksu_handle_sys_read(unsigned int fd);
#endif"""
    if "ksu_handle_sys_read(unsigned int fd)" not in data:
        marker = "ssize_t ksys_read(unsigned int fd, char __user *buf, size_t count)"
        if marker in data:
            data = data.replace(marker, proto + "\n\n" + marker, 1)
            print("[OK] inserted ksu_handle_sys_read prototype in fs/read_write.c")
    hook = """
#ifdef CONFIG_KSU_SUSFS
	ksu_handle_sys_read(fd);
#endif
"""
    data, _ = insert_after_last_decl_in_function(
        data,
        r"ssize_t\s+ksys_read\s*\(\s*unsigned\s+int\s+fd\s*,\s*char\s+__user\s*\*\s*buf\s*,\s*size_t\s+count\s*\)",
        hook,
        "fs/read_write.c ksys_read",
    )
    write(path, data)

def patch_input_handle_event_hook():
    path = ROOT / "drivers" / "input" / "input.c"
    if not path.exists():
        print("[WARN] drivers/input/input.c not found")
        return
    data = read(path)
    # Remove old fallback hook that was before local declarations in input_event().
    data = re.sub(r"\n#ifdef CONFIG_KSU_SUSFS\s*\n\s*ksu_handle_input_handle_event\(&type, &code, &value\);\s*\n#endif\s*\n(?=\s*unsigned long flags;)", "\n", data, flags=re.S)
    proto = """#ifdef CONFIG_KSU_SUSFS
extern int ksu_handle_input_handle_event(unsigned int *type, unsigned int *code, int *value);
#endif"""
    if "ksu_handle_input_handle_event(unsigned int *type" not in data:
        marker = "static void input_handle_event(struct input_dev *dev,"
        if marker in data:
            data = data.replace(marker, proto + "\n\n" + marker, 1)
            print("[OK] inserted ksu_handle_input_handle_event prototype in drivers/input/input.c")
    hook = """
#ifdef CONFIG_KSU_SUSFS
	ksu_handle_input_handle_event(&type, &code, &value);
#endif
"""
    if "ksu_handle_input_handle_event(&type, &code, &value);" not in data:
        # Prefer just before input_get_disposition() in input_handle_event(), after declarations.
        m = re.search(r"(static\s+void\s+input_handle_event\s*\([^)]*\)\s*\{.*?)(\n\s*disposition\s*=\s*input_get_disposition\s*\()", data, re.S)
        if m:
            data = data[:m.start(2)] + hook + data[m.start(2):]
            print("[OK] inserted ksu_handle_input_handle_event before input_get_disposition")
        else:
            data, _ = insert_after_last_decl_in_function(
                data,
                r"void\s+input_event\s*\(\s*struct\s+input_dev\s*\*\s*dev\s*,\s*unsigned\s+int\s+type\s*,\s*unsigned\s+int\s+code\s*,\s*int\s+value\s*\)",
                hook,
                "drivers/input/input.c input_event fallback",
            )
    else:
        print("[SKIP] input hook call already exists")
    write(path, data)

def patch_task_mmu_include():
    path = ROOT / "fs" / "proc" / "task_mmu.c"
    if not path.exists():
        return
    data = read(path)
    if "#include <linux/susfs_def.h>" not in data:
        marker = "#include <linux/pkeys.h>"
        block = "#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT\n#include <linux/susfs_def.h>\n#endif"
        if marker in data:
            data = data.replace(marker, marker + "\n" + block, 1)
            write(path, data)
            print("[OK] inserted susfs_def include in fs/proc/task_mmu.c")

def patch_mount_kabi():
    path = ROOT / "include" / "linux" / "mount.h"
    if not path.exists():
        return
    data = read(path)
    if "susfs_mnt_id_backup" in data:
        print("[SKIP] mount.h susfs_mnt_id_backup already exists")
        return
    old = "\tANDROID_KABI_RESERVE(4);"
    new = "#ifdef CONFIG_KSU_SUSFS\n\tANDROID_KABI_USE(4, u64 susfs_mnt_id_backup);\n#else\n\tANDROID_KABI_RESERVE(4);\n#endif"
    if old in data:
        data = data.replace(old, new, 1)
        write(path, data)
        print("[OK] patched include/linux/mount.h susfs_mnt_id_backup")
    else:
        print("[WARN] mount.h ANDROID_KABI_RESERVE(4) not found")

def apply_susfs_patches():
    susfs_dir = Path(os.environ.get("SUSFS_DIR", "susfs-src")).resolve()
    requested_patch = os.environ.get("SUSFS_KERNEL_PATCH", "").strip()
    continue_on_fail = bool_env("CONTINUE_ON_SUSFS_PATCH_FAILURE", False)
    apply_ksu_patch = bool_env("APPLY_SUSFS_KSU_PATCH", False)
    if not susfs_dir.exists():
        raise FileNotFoundError(f"SUSFS_DIR not found: {susfs_dir}")
    copy_tree_files(susfs_dir / "kernel_patches" / "fs", ROOT / "fs")
    copy_tree_files(susfs_dir / "kernel_patches" / "include" / "linux", ROOT / "include" / "linux")
    ksu_patch = susfs_dir / "kernel_patches" / "KernelSU" / "10_enable_susfs_for_ksu.patch"
    if apply_ksu_patch:
        if not (ROOT / "KernelSU").exists():
            raise FileNotFoundError("KernelSU directory not found")
        apply_patch(ksu_patch, ROOT / "KernelSU", continue_on_fail)
    else:
        print("[SKIP] Skipping upstream SUSFS KernelSU patch for ReSukiSU layout. Set apply_susfs_ksu_patch=true only for testing.")
    optional_ksu_kernel = susfs_dir / "kernel_patches" / "KernelSU" / "kernel"
    if optional_ksu_kernel.exists() and (ROOT / "KernelSU" / "kernel").exists():
        copy_tree_files(optional_ksu_kernel, ROOT / "KernelSU" / "kernel")
    kernel_patch = find_kernel_patch(susfs_dir, requested_patch)
    apply_patch(kernel_patch, ROOT, continue_on_fail)
    # Backport/fix-up rejected or checker-required parts.
    patch_setresuid_hook()
    patch_sys_read_hook()
    patch_input_handle_event_hook()
    patch_task_mmu_include()
    patch_mount_kabi()
    print("[INFO] Reject files after SUSFS patch:")
    for rej in sorted(ROOT.rglob("*.rej")):
        print(f"\n===== REJECT: {rej} =====")
        try:
            print(rej.read_text(errors="ignore"))
        except Exception as e:
            print(f"[WARN] cannot read {rej}: {e}")

def main():
    defconfig = sys.argv[1] if len(sys.argv) >= 2 else "lisa_defconfig"
    patch_defconfig_susfs(defconfig)
    apply_susfs_patches()
    print("[DONE] SUSFS experimental patch step completed.")

if __name__ == "__main__":
    main()
