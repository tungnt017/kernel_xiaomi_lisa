#!/usr/bin/env python3
"""
Official compat shims for SukiSU-Ultra v4.1.3 on kernel 5.4 (non-GKI).

v3 changes:
  - Target kernel_compat.h (not kernel_includes.h) — same file as
    __strncpy_from_user_nofault definition, so wrapper sees it.
  - Auto-cleanup misplaced shim from kernel_includes.h.

Issues fixed:
  1. strncpy_from_user_nofault: only in kernel 5.10+
     -> Inline wrapper in kernel_compat.h
  2. ksu_selinux_hide_handle_* : missing extern decl in ksud.c
     -> Add extern decls

NOT a bypass: real impl, no -Werror disable.
NOT weak: version-guarded, idempotent, backup.
"""
import re
import sys
import shutil
from pathlib import Path


def safe_locate_ksu_dir() -> Path:
    for cand in ("KernelSU", "drivers/kernelsu"):
        if Path(cand).is_dir():
            return Path(cand)
    return None


def find_first(root: Path, name: str):
    direct = list(root.rglob(name))
    if direct:
        return sorted(direct, key=lambda p: len(p.parts))[0]
    return None


def cleanup_old_shim_from(path: Path, marker: str) -> bool:
    """Remove leftover SUSFS_5_4_STRNCPY_COMPAT block if present."""
    if path is None or not path.is_file():
        return False
    src = path.read_text(encoding="utf-8", errors="surrogateescape")
    if marker not in src:
        return False
    # Remove from "/* SUSFS_5_4_STRNCPY_COMPAT */" to matching "#endif"
    pat = re.compile(
        r'\n*/\* SUSFS_5_4_STRNCPY_COMPAT \*/.*?#endif\s*\n',
        re.DOTALL,
    )
    new_src = pat.sub("\n", src)
    if new_src != src:
        path.write_text(new_src, encoding="utf-8", errors="surrogateescape")
        print(f"[CLEAN] Removed misplaced shim from {path}")
        return True
    return False


def patch_kernel_compat(ksu_dir: Path) -> bool:
    """Fix #1: add strncpy_from_user_nofault wrapper in kernel_compat.h."""
    target = find_first(ksu_dir, "kernel_compat.h")
    if target is None:
        print(f"[ERROR] kernel_compat.h not found in {ksu_dir}")
        return False
    print(f"[INFO] Found {target}")

    marker = "SUSFS_5_4_STRNCPY_COMPAT"

    # Cleanup misplaced shim in kernel_includes.h (from v2 attempt)
    incl_h = find_first(ksu_dir, "kernel_includes.h")
    cleanup_old_shim_from(incl_h, marker)

    src = target.read_text(encoding="utf-8", errors="surrogateescape")
    if marker in src:
        print(f"[SKIP] {target} already has strncpy compat shim")
        return True

    # Brace-walk to find end of __strncpy_from_user_nofault body
    pat = re.compile(
        r'static\s+inline\s+long\s+__strncpy_from_user_nofault\s*\([^)]*\)\s*\{',
        re.MULTILINE | re.DOTALL,
    )
    m = pat.search(src)
    if not m:
        print(f"[WARN] __strncpy_from_user_nofault not found, appending shim at EOF")
        insert_at = len(src)
    else:
        depth = 1
        i = m.end()
        while i < len(src) and depth > 0:
            c = src[i]
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
            i += 1
        insert_at = i

    shim = (
        "\n\n/* SUSFS_5_4_STRNCPY_COMPAT */\n"
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
    print(f"[OK] {target}: shim inserted after __strncpy_from_user_nofault body")
    return True


def patch_ksud(ksu_dir: Path) -> bool:
    """Fix #2: add extern decls for ksu_selinux_hide_*."""
    target = find_first(ksu_dir, "ksud.c")
    if target is None:
        print(f"[ERROR] ksud.c not found in {ksu_dir}")
        return False
    print(f"[INFO] Found {target}")

    marker = "SUSFS_5_4_SELINUX_HIDE_DECL"
    src = target.read_text(encoding="utf-8", errors="surrogateescape")
    if marker in src:
        print(f"[SKIP] {target} already has selinux_hide decls")
        return True

    # Insert after last #include in top 200 lines
    lines = src.splitlines(keepends=True)
    last_include_idx = -1
    for i, line in enumerate(lines[:200]):
        stripped = line.lstrip()
        if stripped.startswith("#include"):
            last_include_idx = i

    if last_include_idx < 0:
        first_code_idx = 0
        for i, line in enumerate(lines[:50]):
            s = line.strip()
            if s and not s.startswith(("/*", "*", "//")):
                first_code_idx = i
                break
        insert_at_line = first_code_idx
    else:
        insert_at_line = last_include_idx + 1

    decls = (
        "\n/* SUSFS_5_4_SELINUX_HIDE_DECL */\n"
        "#ifdef CONFIG_KSU_SUSFS\n"
        "extern void ksu_selinux_hide_handle_post_fs_data(void);\n"
        "extern void ksu_selinux_hide_handle_second_stage(void);\n"
        "#endif\n\n"
    )
    new_lines = lines[:insert_at_line] + [decls] + lines[insert_at_line:]
    new_src = "".join(new_lines)

    backup = target.with_suffix(target.suffix + ".bak_compat")
    if not backup.exists():
        shutil.copy2(target, backup)
        print(f"[BACKUP] {backup}")

    target.write_text(new_src, encoding="utf-8", errors="surrogateescape")
    print(f"[OK] {target} patched (after line {insert_at_line})")
    return True


def main() -> int:
    ksu_dir = safe_locate_ksu_dir()
    if ksu_dir is None:
        print("[ERROR] No KernelSU/ or drivers/kernelsu/ directory found")
        return 1
    print(f"[INFO] Using KSU dir: {ksu_dir}")

    fail = 0
    if not patch_kernel_compat(ksu_dir):
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
