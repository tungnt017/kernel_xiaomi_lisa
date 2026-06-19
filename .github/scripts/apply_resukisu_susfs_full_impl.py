#!/usr/bin/env python3
"""
Full SUSFS implementation helper for ReSukiSU on Xiaomi lisa / kernel 5.4.

Purpose:
- Apply SUSFS kernel-side files and 5.4 kernel patch.
- Allow known lisa/QGKI 5.4 rejects and resolve the build-critical ones.
- Apply the upstream SUSFS KernelSU integration patch when it matches the current
  ReSukiSU/KernelSU layout.
- Do NOT create weak/no-op fallback symbols. Full mode must use real SUSFS
  implementations from a compatible ReSukiSU + SUSFS patch set.

Expected CI layout:
- Run from kernel source root.
- SUSFS repo cloned to SUSFS_DIR, default: susfs-src.
- ReSukiSU already integrated before this script runs.
"""

from pathlib import Path
import os
import re
import shutil
import subprocess
import sys

ROOT = Path(".").resolve()
SUSFS_DIR = Path(os.environ.get("SUSFS_DIR", "susfs-src")).resolve()
DEFCONFIG = os.environ.get("DEFCONFIG", "lisa_defconfig")
SUSFS_KERNEL_PATCH = os.environ.get("SUSFS_KERNEL_PATCH", "").strip()
ALLOW_KERNEL_REJECTS = os.environ.get("ALLOW_SUSFS_KERNEL_REJECTS", "true").strip().lower() in ("1", "true", "yes", "y", "on")
ALLOW_KSU_PATCH_REJECTS = os.environ.get("ALLOW_SUSFS_KSU_PATCH_REJECTS", "false").strip().lower() in ("1", "true", "yes", "y", "on")

FULL_CONFIGS_ON = [
    "CONFIG_KSU=y",
    "CONFIG_KSU_SUSFS=y",
    "CONFIG_KSU_SUSFS_HAS_MAGIC_MOUNT=y",
    "CONFIG_KSU_SUSFS_SUS_PATH=y",
    "CONFIG_KSU_SUSFS_SUS_MOUNT=y",
    "CONFIG_KSU_SUSFS_AUTO_ADD_SUS_KSU_DEFAULT_MOUNT=y",
    "CONFIG_KSU_SUSFS_AUTO_ADD_SUS_BIND_MOUNT=y",
    "CONFIG_KSU_SUSFS_SUS_KSTAT=y",
    "CONFIG_KSU_SUSFS_SUS_MAP=y",
    "CONFIG_KSU_SUSFS_TRY_UMOUNT=y",
    "CONFIG_KSU_SUSFS_AUTO_ADD_TRY_UMOUNT_FOR_BIND_MOUNT=y",
    "CONFIG_KSU_SUSFS_SPOOF_UNAME=y",
    "CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG=y",
    "CONFIG_KSU_SUSFS_OPEN_REDIRECT=y",
    "CONFIG_KSU_SUSFS_ENABLE_LOG=y",
    "CONFIG_KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS=y",
]

# Keep SUS_SU disabled for lisa manual-hook/non-kprobe path unless you have a
# known-compatible SUS_SU integration for this exact ReSukiSU revision.
FULL_CONFIGS_OFF = [
    "# CONFIG_KSU_SUSFS_SUS_SU is not set",
]

REQUIRED_REAL_SYMBOLS = [
    "susfs_extra_works",
    "susfs_enable_log",
    "susfs_show_version",
    "susfs_get_enabled_features",
    "susfs_show_variant",
    "susfs_start_sdcard_monitor_fn",
    "susfs_is_current_proc_umounted",
]


def read(path: Path) -> str:
    return Path(path).read_text(errors="ignore")


def write(path: Path, data: str) -> None:
    Path(path).write_text(data)


def run(cmd: str, cwd: Path | None = None, check: bool = False) -> int:
    print(f"[RUN] {cmd} cwd={cwd or ROOT}")
    proc = subprocess.run(cmd, shell=True, cwd=cwd or ROOT, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"command failed: {cmd}")
    return proc.returncode


def find_defconfig() -> Path:
    candidates = [
        ROOT / "arch" / "arm64" / "configs" / DEFCONFIG,
        ROOT / "arch" / "arm64" / "configs" / "vendor" / DEFCONFIG,
    ]
    for path in candidates:
        if path.exists():
            return path
    print(f"[ERROR] defconfig not found: {DEFCONFIG}")
    for path in sorted((ROOT / "arch" / "arm64" / "configs").rglob("*defconfig")):
        print(f" - {path}")
    raise SystemExit(1)


def patch_defconfig_full() -> None:
    path = find_defconfig()
    data = read(path)

    remove_prefixes: list[str] = []
    for line in FULL_CONFIGS_ON:
        key = line.split("=", 1)[0]
        remove_prefixes.extend([key + "=", "# " + key + " is not set"])
    for line in FULL_CONFIGS_OFF:
        match = re.match(r"# (CONFIG_[A-Za-z0-9_]+) is not set", line)
        if match:
            key = match.group(1)
            remove_prefixes.extend([key + "=", "# " + key + " is not set"])

    lines = [line for line in data.splitlines() if not any(line.startswith(prefix) for prefix in remove_prefixes)]
    lines += ["", "# ReSukiSU SUSFS full implementation"] + FULL_CONFIGS_ON + FULL_CONFIGS_OFF + [""]
    write(path, "\n".join(lines) + "\n")
    print(f"[OK] enabled full SUSFS config set in {path}")


def copy_tree_files(src_dir: Path, dst_dir: Path) -> None:
    if not src_dir.exists():
        print(f"[WARN] missing {src_dir}")
        return
    dst_dir.mkdir(parents=True, exist_ok=True)
    for item in src_dir.iterdir():
        if item.is_file():
            target = dst_dir / item.name
            shutil.copy2(item, target)
            print(f"[OK] copied {item} -> {target}")


def find_kernel_patch() -> Path:
    patch_root = SUSFS_DIR / "kernel_patches"
    if SUSFS_KERNEL_PATCH:
        candidates = [
            patch_root / SUSFS_KERNEL_PATCH,
            SUSFS_DIR / SUSFS_KERNEL_PATCH,
            Path(SUSFS_KERNEL_PATCH),
        ]
        for path in candidates:
            if path.exists():
                print(f"[OK] selected requested kernel patch: {path}")
                return path.resolve()
        raise FileNotFoundError(f"SUSFS_KERNEL_PATCH not found: {SUSFS_KERNEL_PATCH}")

    patterns = [
        "50_add_susfs_in_kernel-5.4*.patch",
        "50_add_susfs_in_kernel*.patch",
        "*5.4*.patch",
    ]
    for pattern in patterns:
        matches = sorted(patch_root.glob(pattern))
        if matches:
            print(f"[OK] selected kernel patch: {matches[0]}")
            return matches[0].resolve()
    raise FileNotFoundError("cannot find SUSFS kernel patch under susfs-src/kernel_patches")


def remove_weak_fallbacks() -> None:
    compat = ROOT / "fs" / "susfs_resukisu_compat.c"
    if compat.exists():
        compat.unlink()
        print("[OK] removed weak fallback file fs/susfs_resukisu_compat.c")

    makefile = ROOT / "fs" / "Makefile"
    if makefile.exists():
        data = read(makefile)
        data2 = re.sub(
            r"^obj-\$\(CONFIG_KSU_SUSFS\) \+= susfs_resukisu_compat\.o\s*\n?",
            "",
            data,
            flags=re.M,
        )
        if data2 != data:
            write(makefile, data2)
            print("[OK] removed susfs_resukisu_compat.o from fs/Makefile")


def ensure_include_after(data: str, anchor: str, block: str) -> str:
    if block in data:
        return data
    if anchor in data:
        return data.replace(anchor, anchor + "\n" + block, 1)
    return block + "\n" + data


def patch_mount_h() -> None:
    path = ROOT / "include" / "linux" / "mount.h"
    if not path.exists():
        print("[WARN] include/linux/mount.h not found")
        return
    data = read(path)
    if "susfs_mnt_id_backup" in data:
        print("[SKIP] include/linux/mount.h already has susfs_mnt_id_backup")
        return

    replacement = (
        "#ifdef CONFIG_KSU_SUSFS\n"
        "\tANDROID_KABI_USE(4, u64 susfs_mnt_id_backup);\n"
        "#else\n"
        "\tANDROID_KABI_RESERVE(4);\n"
        "#endif"
    )
    data2 = data.replace("\tANDROID_KABI_RESERVE(4);", replacement, 1)
    if data2 == data:
        print("[WARN] mount.h: ANDROID_KABI_RESERVE(4) not found")
        return
    write(path, data2)
    print("[OK] fixed reject: include/linux/mount.h susfs_mnt_id_backup")


def patch_task_mmu_include() -> None:
    path = ROOT / "fs" / "proc" / "task_mmu.c"
    if not path.exists():
        print("[WARN] fs/proc/task_mmu.c not found")
        return
    data = read(path)
    if "<linux/susfs_def.h>" in data:
        print("[SKIP] fs/proc/task_mmu.c already includes susfs_def.h")
        return
    block = "#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT\n#include <linux/susfs_def.h>\n#endif"
    data = ensure_include_after(data, "#include <linux/pkeys.h>", block)
    write(path, data)
    print("[OK] fixed reject: fs/proc/task_mmu.c susfs_def include")


def patch_proc_fd_known_reject() -> None:
    """Keep fs/proc/fd.c build-clean when SUS_MOUNT hunk rejects.

    The complete fdinfo mnt_id spoof block is highly layout-sensitive. If the
    upstream hunk failed, we remove only the orphan `mnt` declaration to avoid
    -Wunused-variable. Real full feature quality still requires a matching patch
    set or a manual fd.c backport.
    """
    path = ROOT / "fs" / "proc" / "fd.c"
    if not path.exists():
        print("[WARN] fs/proc/fd.c not found")
        return
    data = read(path)
    if "bypass_orig_flow" in data:
        print("[SKIP] fs/proc/fd.c SUS_MOUNT block appears present")
        return

    data2 = re.sub(
        r"\n#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\s*\n"
        r"\s*struct mount \*mnt = NULL;\s*\n"
        r"#endif\s*\n",
        "\n",
        data,
        flags=re.S,
    )
    if data2 != data:
        write(path, data2)
        print("[OK] fixed reject: removed orphan mnt declaration from fs/proc/fd.c")
    else:
        print("[SKIP] fs/proc/fd.c has no orphan mnt declaration")


def patch_known_kernel_rejects_for_lisa() -> None:
    patch_mount_h()
    patch_task_mmu_include()
    patch_proc_fd_known_reject()
    print("[INFO] fs/open.c SUS_SU reject ignored because CONFIG_KSU_SUSFS_SUS_SU is disabled")


def apply_kernel_patch_with_known_rejects() -> None:
    patch_file = find_kernel_patch()
    rc = run(f"patch -p1 --forward --batch < '{patch_file}'", cwd=ROOT, check=False)
    if rc != 0:
        if not ALLOW_KERNEL_REJECTS:
            raise RuntimeError(f"SUSFS kernel patch failed and ALLOW_SUSFS_KERNEL_REJECTS=false: {patch_file}")
        print("[WARN] SUSFS kernel patch had rejects; applying known lisa 5.4 resolutions")
    else:
        print("[OK] SUSFS kernel patch applied cleanly")
    patch_known_kernel_rejects_for_lisa()


def try_apply_ksu_integration_patch() -> bool:
    patch_file = SUSFS_DIR / "kernel_patches" / "KernelSU" / "10_enable_susfs_for_ksu.patch"
    if not patch_file.exists():
        raise FileNotFoundError(f"KernelSU integration patch missing: {patch_file}")

    candidates = [ROOT / "drivers" / "kernelsu", ROOT / "KernelSU", ROOT]
    attempts: list[str] = []
    for cwd in candidates:
        if not cwd.exists():
            continue
        for strip in (1, 0):
            attempts.append(f"{cwd} -p{strip}")
            print(f"[INFO] trying KernelSU SUSFS integration patch in {cwd} with -p{strip}")
            rc = run(f"patch -p{strip} --forward --batch < '{patch_file.resolve()}'", cwd=cwd, check=False)
            if rc == 0:
                print(f"[OK] applied KernelSU SUSFS integration patch in {cwd} with -p{strip}")
                return True

    message = "failed to apply KernelSU SUSFS integration patch cleanly. Tried: " + ", ".join(attempts)
    if ALLOW_KSU_PATCH_REJECTS:
        print("[WARN] " + message)
        return False
    raise RuntimeError(message + "; pin compatible ReSukiSU/SUSFS commits")


def symbol_has_real_definition(symbol: str) -> bool:
    definition_re = re.compile(
        r"(^|\n)\s*(?!extern\b)(?:[A-Za-z_][\w\s\*]*\s+)?" + re.escape(symbol) + r"\s*\([^;{]*\)\s*\{",
        re.M,
    )
    search_roots = [ROOT / "fs", ROOT / "drivers" / "kernelsu", ROOT / "KernelSU"]
    for search_root in search_roots:
        if not search_root.exists():
            continue
        for c_file in search_root.rglob("*.c"):
            if c_file.name == "susfs_resukisu_compat.c":
                continue
            try:
                if definition_re.search(read(c_file)):
                    print(f"[OK] real definition found for {symbol} in {c_file}")
                    return True
            except Exception:
                pass
    return False


def verify_real_symbols() -> None:
    missing = [symbol for symbol in REQUIRED_REAL_SYMBOLS if not symbol_has_real_definition(symbol)]
    if missing:
        print("[ERROR] Missing real SUSFS implementations after integration patch:")
        for symbol in missing:
            print(" - " + symbol)
        print("")
        print("Full implementation cannot use weak/no-op fallbacks.")
        print("Pin compatible ReSukiSU + susfs4ksu commits, or manually backport the KernelSU integration patch.")
        raise SystemExit(2)
    print("[OK] all required ReSukiSU SUSFS helper symbols have real implementations")


def print_rejects_for_audit() -> None:
    rejects = sorted(ROOT.rglob("*.rej"))
    if not rejects:
        print("[OK] no .rej files found")
        return
    print("[INFO] .rej files remain for audit/backport:")
    for reject in rejects:
        print(f" - {reject}")


def main() -> None:
    if not SUSFS_DIR.exists():
        raise FileNotFoundError(f"SUSFS_DIR not found: {SUSFS_DIR}")

    remove_weak_fallbacks()
    patch_defconfig_full()

    copy_tree_files(SUSFS_DIR / "kernel_patches" / "fs", ROOT / "fs")
    copy_tree_files(SUSFS_DIR / "kernel_patches" / "include" / "linux", ROOT / "include" / "linux")

    apply_kernel_patch_with_known_rejects()
    try_apply_ksu_integration_patch()
    verify_real_symbols()
    print_rejects_for_audit()
    print("[DONE] full SUSFS implementation patch completed")


if __name__ == "__main__":
    main()
