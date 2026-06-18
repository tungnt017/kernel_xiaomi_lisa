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
        "CONFIG_KSU_SUSFS=",
        "CONFIG_KSU_SUSFS_HAS_MAGIC_MOUNT=",
        "CONFIG_KSU_SUSFS_SUS_PATH=",
        "CONFIG_KSU_SUSFS_SUS_MOUNT=",
        "CONFIG_KSU_SUSFS_AUTO_ADD_SUS_KSU_DEFAULT_MOUNT=",
        "CONFIG_KSU_SUSFS_AUTO_ADD_SUS_BIND_MOUNT=",
        "CONFIG_KSU_SUSFS_SUS_KSTAT=",
        "CONFIG_KSU_SUSFS_TRY_UMOUNT=",
        "CONFIG_KSU_SUSFS_AUTO_ADD_TRY_UMOUNT_FOR_BIND_MOUNT=",
        "CONFIG_KSU_SUSFS_SPOOF_UNAME=",
        "CONFIG_KSU_SUSFS_ENABLE_LOG=",
        "CONFIG_KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS=",
        "CONFIG_KSU_SUSFS_SUS_SU=",
        "# CONFIG_KSU_SUSFS is not set",
        "# CONFIG_KSU_SUSFS_HAS_MAGIC_MOUNT is not set",
        "# CONFIG_KSU_SUSFS_SUS_PATH is not set",
        "# CONFIG_KSU_SUSFS_SUS_MOUNT is not set",
        "# CONFIG_KSU_SUSFS_AUTO_ADD_SUS_KSU_DEFAULT_MOUNT is not set",
        "# CONFIG_KSU_SUSFS_AUTO_ADD_SUS_BIND_MOUNT is not set",
        "# CONFIG_KSU_SUSFS_SUS_KSTAT is not set",
        "# CONFIG_KSU_SUSFS_TRY_UMOUNT is not set",
        "# CONFIG_KSU_SUSFS_AUTO_ADD_TRY_UMOUNT_FOR_BIND_MOUNT is not set",
        "# CONFIG_KSU_SUSFS_SPOOF_UNAME is not set",
        "# CONFIG_KSU_SUSFS_ENABLE_LOG is not set",
        "# CONFIG_KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS is not set",
        "# CONFIG_KSU_SUSFS_SUS_SU is not set",
    ]

    lines = []
    for line in data.splitlines():
        if any(line.startswith(prefix) for prefix in remove_prefixes):
            continue
        lines.append(line)

    lines += [
        "",
        "# ReSukiSU SUSFS experimental",
        "CONFIG_KSU=y",
        "CONFIG_KSU_SUSFS=y",
        "CONFIG_KSU_SUSFS_HAS_MAGIC_MOUNT=y",
        "CONFIG_KSU_SUSFS_SUS_PATH=y",
        "CONFIG_KSU_SUSFS_SUS_MOUNT=y",
        "CONFIG_KSU_SUSFS_AUTO_ADD_SUS_KSU_DEFAULT_MOUNT=y",
        "CONFIG_KSU_SUSFS_AUTO_ADD_SUS_BIND_MOUNT=y",
        "CONFIG_KSU_SUSFS_SUS_KSTAT=y",
        "CONFIG_KSU_SUSFS_TRY_UMOUNT=y",
        "CONFIG_KSU_SUSFS_AUTO_ADD_TRY_UMOUNT_FOR_BIND_MOUNT=y",
        "CONFIG_KSU_SUSFS_SPOOF_UNAME=y",
        "CONFIG_KSU_SUSFS_ENABLE_LOG=y",
        "CONFIG_KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS=y",
        "# CONFIG_KSU_SUSFS_SUS_SU is not set",
        "",
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
        requested_path = kp / requested
        if requested_path.exists():
            return requested_path
        requested_path = Path(susfs_dir) / requested
        if requested_path.exists():
            return requested_path
        raise FileNotFoundError(f"requested SUSFS kernel patch not found: {requested}")

    patterns = [
        "50_add_susfs_in_kernel-5.4*.patch",
        "50_add_susfs_in_kernel*.patch",
        "*5.4*.patch",
    ]
    for pat in patterns:
        matches = sorted(kp.glob(pat))
        if matches:
            print(f"[OK] auto selected SUSFS kernel patch: {matches[0]}")
            return matches[0]
    raise FileNotFoundError("cannot auto-find SUSFS kernel patch under kernel_patches")


def patch_setresuid_hook():
    path = ROOT / "kernel" / "sys.c"
    if not path.exists():
        print("[WARN] kernel/sys.c not found, cannot patch setresuid hook")
        return

    data = read(path)

    # Remove previous wrong wrapper-only hook if present.
    data = re.sub(
        r"\n#if defined\(CONFIG_KSU\)\s*\n"
        r"extern int ksu_handle_setresuid\(uid_t ruid, uid_t euid, uid_t suid\);\s*\n"
        r"#endif\s*\n\s*(?=SYSCALL_DEFINE3\s*\(\s*setresuid)",
        "\n",
        data,
        flags=re.S,
    )
    data = re.sub(
        r"\n\s*#if defined\(CONFIG_KSU\)\s*\n"
        r"\s*ksu_handle_setresuid\(ruid, euid, suid\);\s*\n"
        r"\s*#endif\s*\n",
        "\n",
        data,
        flags=re.S,
    )

    proto = """#ifdef CONFIG_KSU_SUSFS
extern int ksu_handle_setresuid(uid_t ruid, uid_t euid, uid_t suid);
#endif"""

    if "extern int ksu_handle_setresuid(uid_t ruid, uid_t euid, uid_t suid);" not in data:
        for marker in ["long __sys_setresuid(uid_t ruid, uid_t euid, uid_t suid)", "SYSCALL_DEFINE3(setresuid"]:
            if marker in data:
                data = data.replace(marker, proto + "\n\n" + marker, 1)
                print("[OK] inserted ksu_handle_setresuid prototype in kernel/sys.c")
                break
        else:
            print("[WARN] cannot find marker for setresuid prototype")

    hook = """
#ifdef CONFIG_KSU_SUSFS
	(void)ksu_handle_setresuid(ruid, euid, suid);
#endif
"""

    if "ksu_handle_setresuid(ruid, euid, suid);" in data:
        print("[SKIP] setresuid hook call already exists")
        write(path, data)
        return

    pat = re.compile(
        r"(long\s+__sys_setresuid\s*\(\s*uid_t\s+ruid\s*,\s*uid_t\s+euid\s*,\s*uid_t\s+suid\s*\)\s*\{\s*)",
        re.S,
    )
    m = pat.search(data)
    if m:
        data = data[:m.end()] + hook + data[m.end():]
        write(path, data)
        print("[OK] inserted ksu_handle_setresuid call inside __sys_setresuid")
        return

    pat = re.compile(r"(SYSCALL_DEFINE3\s*\(\s*setresuid\s*,.*?\)\s*\{\s*)", re.S)
    m = pat.search(data)
    if m:
        data = data[:m.end()] + hook + data[m.end():]
        write(path, data)
        print("[OK] inserted ksu_handle_setresuid call inside SYSCALL_DEFINE3(setresuid) fallback")
        return

    write(path, data)
    print("[WARN] failed to patch setresuid hook call")


def patch_sys_read_hook():
    path = ROOT / "fs" / "read_write.c"
    if not path.exists():
        print("[WARN] fs/read_write.c not found, cannot patch sys_read hook")
        return

    data = read(path)

    # Remove wrong multi-argument sys_read hook variants if present.
    data = re.sub(
        r"\n\s*#ifdef\s+CONFIG_KSU(?:_SUSFS)?\s*\n"
        r"\s*extern\s+int\s+ksu_handle_sys_read\s*\([^;]+;\s*\n"
        r"\s*#endif\s*\n",
        "\n",
        data,
        flags=re.S,
    )
    data = re.sub(
        r"\n\s*#ifdef\s+CONFIG_KSU(?:_SUSFS)?\s*\n"
        r"\s*ksu_handle_sys_read\s*\(\s*fd\s*,\s*&buf\s*,\s*&count\s*\)\s*;\s*\n"
        r"\s*#endif\s*\n",
        "\n",
        data,
        flags=re.S,
    )

    proto = """#ifdef CONFIG_KSU_SUSFS
extern __attribute__((cold)) void ksu_handle_sys_read(unsigned int fd);
#endif"""

    if "ksu_handle_sys_read(unsigned int fd)" not in data:
        for marker in ["ssize_t ksys_read(unsigned int fd, char __user *buf, size_t count)", "SYSCALL_DEFINE3(read,"]:
            if marker in data:
                data = data.replace(marker, proto + "\n\n" + marker, 1)
                print("[OK] inserted ksu_handle_sys_read prototype in fs/read_write.c")
                break
        else:
            print("[WARN] cannot find marker for sys_read prototype")

    hook = """
#ifdef CONFIG_KSU_SUSFS
	ksu_handle_sys_read(fd);
#endif
"""

    if "ksu_handle_sys_read(fd);" in data:
        print("[SKIP] sys_read hook call already exists")
        write(path, data)
        return

    # Preferred target on Linux 5.4.
    pat = re.compile(
        r"(ssize_t\s+ksys_read\s*\(\s*unsigned\s+int\s+fd\s*,\s*char\s+__user\s*\*\s*buf\s*,\s*size_t\s+count\s*\)\s*\{\s*)",
        re.S,
    )
    m = pat.search(data)
    if m:
        data = data[:m.end()] + hook + data[m.end():]
        write(path, data)
        print("[OK] inserted ksu_handle_sys_read call inside ksys_read")
        return

    pat = re.compile(r"(SYSCALL_DEFINE3\s*\(\s*read\s*,.*?\)\s*\{\s*)", re.S)
    m = pat.search(data)
    if m:
        data = data[:m.end()] + hook + data[m.end():]
        write(path, data)
        print("[OK] inserted ksu_handle_sys_read call inside SYSCALL_DEFINE3(read) fallback")
        return

    write(path, data)
    print("[WARN] failed to patch sys_read hook call")


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

    # ReSukiSU SUSFS inline mode currently fails checks one missing hook at a time.
    patch_setresuid_hook()
    patch_sys_read_hook()

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
