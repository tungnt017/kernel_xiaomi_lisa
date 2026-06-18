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

    # --batch prevents interactive "File to patch:" prompts in CI.
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


def insert_after_declarations_in_function(data, func_pattern, hook, label):
    m = func_pattern.search(data)
    if not m:
        print(f"[WARN] {label}: function not found")
        return data, False

    brace_start = data.find("{", m.start())
    if brace_start < 0:
        print(f"[WARN] {label}: opening brace not found")
        return data, False

    depth = 0
    end = None
    for i in range(brace_start, len(data)):
        if data[i] == "{":
            depth += 1
        elif data[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        print(f"[WARN] {label}: function end not found")
        return data, False

    body = data[brace_start + 1:end - 1]
    if hook.strip() in body:
        print(f"[SKIP] {label}: already patched")
        return data, True

    lines = body.splitlines(True)
    insert_index = 0
    declaration_regex = re.compile(
        r"^\s*(?:const\s+)?(?:struct|unsigned|signed|int|long|short|char|bool|kuid_t|kgid_t|uid_t|gid_t|"
        r"umode_t|loff_t|size_t|ssize_t|u8|u16|u32|u64|s8|s16|s32|s64|enum)\b.*;\s*(?:/\*.*\*/)?\s*$"
    )
    blank_or_comment_regex = re.compile(r"^\s*$|^\s*/\*.*\*/\s*$|^\s*//.*$")

    for idx, line in enumerate(lines):
        if blank_or_comment_regex.match(line):
            insert_index = idx + 1
            continue
        if declaration_regex.match(line):
            insert_index = idx + 1
            continue
        break

    lines.insert(insert_index, hook)
    new_body = "".join(lines)
    data = data[:brace_start + 1] + new_body + data[end - 1:]
    print(f"[OK] {label}: patched after declarations")
    return data, True


def patch_setresuid_hook():
    """Fix ReSukiSU/SUSFS inline hook check: ksu_handle_setresuid must exist in kernel/sys.c."""
    path = ROOT / "kernel" / "sys.c"
    if not path.exists():
        print("[WARN] kernel/sys.c not found, cannot patch setresuid hook")
        return

    data = read(path)

    proto = """#if defined(CONFIG_KSU)
extern int ksu_handle_setresuid(uid_t ruid, uid_t euid, uid_t suid);
#endif"""

    if "ksu_handle_setresuid(uid_t ruid, uid_t euid, uid_t suid)" not in data:
        marker = "SYSCALL_DEFINE3(setresuid"
        if marker in data:
            data = data.replace(marker, proto + "\n\n" + marker, 1)
            print("[OK] inserted ksu_handle_setresuid prototype in kernel/sys.c")
        else:
            print("[WARN] setresuid syscall marker not found for prototype")

    hook = "\n#if defined(CONFIG_KSU)\n\tksu_handle_setresuid(ruid, euid, suid);\n#endif\n"

    if "ksu_handle_setresuid(ruid, euid, suid);" in data:
        print("[SKIP] setresuid hook call already exists")
        write(path, data)
        return

    patterns = [
        re.compile(r"SYSCALL_DEFINE3\s*\(\s*setresuid\s*,\s*uid_t\s*,\s*ruid\s*,\s*uid_t\s*,\s*euid\s*,\s*uid_t\s*,\s*suid\s*\)\s*\{", re.S),
        re.compile(r"SYSCALL_DEFINE3\s*\(\s*setresuid\s*,.*?\)\s*\{", re.S),
    ]
    for pat in patterns:
        data_new, ok = insert_after_declarations_in_function(data, pat, hook, "kernel/sys.c setresuid")
        if ok:
            write(path, data_new)
            return

    write(path, data)
    print("[WARN] failed to patch setresuid hook call")


def apply_susfs_patches():
    susfs_dir = Path(os.environ.get("SUSFS_DIR", "susfs-src")).resolve()
    requested_patch = os.environ.get("SUSFS_KERNEL_PATCH", "").strip()
    continue_on_fail = bool_env("CONTINUE_ON_SUSFS_PATCH_FAILURE", False)
    apply_ksu_patch = bool_env("APPLY_SUSFS_KSU_PATCH", False)

    if not susfs_dir.exists():
        raise FileNotFoundError(f"SUSFS_DIR not found: {susfs_dir}")

    # Copy kernel-side source files.
    copy_tree_files(susfs_dir / "kernel_patches" / "fs", ROOT / "fs")
    copy_tree_files(susfs_dir / "kernel_patches" / "include" / "linux", ROOT / "include" / "linux")

    # ReSukiSU layout differs from official KernelSU; skip upstream KernelSU patch by default.
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

    # Apply main kernel patch to device kernel source.
    kernel_patch = find_kernel_patch(susfs_dir, requested_patch)
    apply_patch(kernel_patch, ROOT, continue_on_fail)

    # ReSukiSU switches to SuSFS Inline hook when CONFIG_KSU_SUSFS=y. Ensure the
    # setresuid hook exists so inline_hook_check.mk does not fail.
    patch_setresuid_hook()


def main():
    defconfig = sys.argv[1] if len(sys.argv) >= 2 else "lisa_defconfig"
    patch_defconfig_susfs(defconfig)
    apply_susfs_patches()
    print("[DONE] SUSFS experimental patch step completed.")


if __name__ == "__main__":
    main()
