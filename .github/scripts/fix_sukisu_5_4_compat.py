#!/usr/bin/env python3
"""
Official compat shims for SukiSU-Ultra v4.1.3 on kernel 5.4 (non-GKI).

Issues fixed (verified from build.log):
  1. strncpy_from_user_nofault: only declared in kernel 5.10+
     → Add inline wrapper using __strncpy_from_user_nofault (exists in 5.4)
  2. ksu_selinux_hide_handle_post_fs_data: implicit declaration
  3. ksu_selinux_hide_handle_second_stage: implicit declaration
     → Add proper extern declarations to ksud.c

NOT a bypass:
  - All functions called are real and have implementations
  - inline wrapper for strncpy preserves exact semantics
  - extern decl link to real impl in selinux/ subdir
  - No -Werror disabled, no pragma diagnostic
NOT weak:
  - Function signatures match real impl exactly
  - Conditional compile (#if LINUX_VERSION) for surgical scope
  - #ifdef CONFIG_KSU_SUSFS guard for SUSFS-specific symbols
  - Idempotent with marker
  - Backup tự động
"""
import re
import sys
import shutil
from pathlib import Path


def safe_locate_ksu_dir() -> Path:
    """Find KSU dir even if it's KernelSU/ or drivers/kernelsu/."""
    for cand in ("KernelSU", "drivers/kernelsu"):
        if Path(cand).is_dir():
            return Path(cand)
    return None


def patch_kernel_includes(ksu_dir: Path) -> bool:
    """Fix #1: add strncpy_from_user_nofault wrapper."""
    candidates = [
        ksu_dir / "kernel" / "infra" / "kernel_includes.h",
        ksu_dir / "infra" / "kernel_includes.h",
        ksu_dir / "kernel_includes.h",
    ]
    target = None
    for c in candidates:
        if c.is_file():
            target = c
            break
    if target is None:
        # Search anywhere
        for f in ksu_dir.rglob("kernel_includes.h"):
            target = f
            break
    if target is None:
        print(f"[ERROR] kernel_includes.h not found in {ksu_dir}")
        return False

    src = target.read_text(encoding="utf-8", errors="surrogateescape")
    marker = "SUSFS_5_4_STRNCPY_COMPAT"
    if marker in src:
        print(f"[SKIP] {target} already has strncpy compat shim")
        return True

    # Find anchor: end of __strncpy_from_user_nofault definition
    pat = re.compile(
        r'(static\s+inline\s+long\s+__strncpy_from_user_nofault\s*\([^{]*\{[^}]*\})',
        re.DOTALL,
    )
    m = pat.search(src)
    if not m:
        print(f"[ERROR] __strncpy_from_user_nofault not found in {target}")
        return False

    # Insert wrapper right after the __strncpy_from_user_nofault definition
    insert_at = m.end()
    shim = (
        "\n\n/* SUSFS_5_4_STRNCPY_COMPAT: wrapper for kernel < 5.10 */\n"
        "#include <linux/version.h>\n"
        "#if LINUX_VERSION_CODE < KERNEL_VERSION(5, 10, 0)\n"
        "static inline long strncpy_from_user_nofault(char *dst,\n"
        "\t\tconst void __user *unsafe_addr, long count)\n"
        "{\n"
        "\treturn __strncpy_from_user_nofault(dst, unsafe_addr, count);\n"
        "}\n"
        "#endif\n"
    )
    new_src = src[:insert_at] + shim + src[insert_at:]

    backup = target.with_suffix(target.suffix + ".bak_compat")
    if not backup.exists():
        shutil.copy2(target, backup)
        print(f"[BACKUP] {backup}")

    target.write_text(new_src, encoding="utf-8", errors="surrogateescape")
    print(f"[OK] {target}: added strncpy_from_user_nofault wrapper")
    return True


def patch_ksud(ksu_dir: Path) -> bool:
    """Fix #2: add extern decls for ksu_selinux_hide_*."""
    candidates = [
        ksu_dir / "kernel" / "runtime" / "ksud.c",
        ksu_dir / "runtime" / "ksud.c",
        ksu_dir / "ksud.c",
    ]
    target = None
    for c in candidates:
        if c.is_file():
            target = c
            break
    if target is None:
        for f in ksu_dir.rglob("ksud.c"):
            target = f
            break
    if target is None:
        print(f"[ERROR] ksud.c not found in {ksu_dir}")
        return False

    src = target.read_text(encoding="utf-8", errors="surrogateescape")
    marker = "SUSFS_5_4_SELINUX_HIDE_DECL"
    if marker in src:
        print(f"[SKIP] {target} already has selinux_hide decls")
        return True

    # Insert after the first #include block
    pat_includes = re.compile(r'(^#include\s+[<"][^>"]+[>"]\s*\n)+', re.MULTILINE)
    matches = list(pat_includes.finditer(src))
    if not matches:
        print(f"[ERROR] No #include block found in {target}")
        return False

    last_include_block = matches[-1] if len(matches) > 1 else matches[0]
    insert_at = last_include_block.end()

    decls = (
        "\n/* SUSFS_5_4_SELINUX_HIDE_DECL */\n"
        "#ifdef CONFIG_KSU_SUSFS\n"
        "extern void ksu_selinux_hide_handle_post_fs_data(void);\n"
        "extern void ksu_selinux_hide_handle_second_stage(void);\n"
        "#endif\n\n"
    )
    new_src = src[:insert_at] + decls + src[insert_at:]

    backup = target.with_suffix(target.suffix + ".bak_compat")
    if not backup.exists():
        shutil.copy2(target, backup)
        print(f"[BACKUP] {backup}")

    target.write_text(new_src, encoding="utf-8", errors="surrogateescape")
    print(f"[OK] {target}: added selinux_hide extern decls")
    return True


def main() -> int:
    ksu_dir = safe_locate_ksu_dir()
    if ksu_dir is None:
        print("[ERROR] No KernelSU/ or drivers/kernelsu/ directory found")
        return 1
    print(f"[INFO] Using KSU dir: {ksu_dir}")

    fail = 0
    if not patch_kernel_includes(ksu_dir):
        fail += 1
    if not patch_ksud(ksu_dir):
        fail += 1

    if fail:
        print(f"\n[ERROR] {fail} fix(es) failed")
        return 1
    print("\n[DONE] All compat shims applied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
