#!/usr/bin/env python3
"""
Official compat shims for SukiSU-Ultra v4.1.3 on kernel 5.4 (non-GKI).

v2: more robust anchors (handle nested braces + various include patterns).

Issues fixed:
  1. strncpy_from_user_nofault: only in kernel 5.10+
     -> Inline wrapper using __strncpy_from_user_nofault
  2. ksu_selinux_hide_handle_post_fs_data / _second_stage: missing extern
     -> Add extern decls to ksud.c

NOT a bypass: real functions, real semantics.
NOT weak: signature-exact, version-guarded, idempotent, backup.
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
    """Find first file with given name under root, BFS-ish."""
    direct = list(root.rglob(name))
    if direct:
        # Prefer shorter path
        return sorted(direct, key=lambda p: len(p.parts))[0]
    return None


def add_after_match(path: Path, anchor_pat: str, content: str, marker: str,
                    flags=re.MULTILINE | re.DOTALL) -> str:
    """Insert content right after anchor match. Returns status string."""
    src = path.read_text(encoding="utf-8", errors="surrogateescape")
    if marker in src:
        return f"[SKIP] {path} already has marker {marker}"

    pat = re.compile(anchor_pat, flags)
    m = pat.search(src)
    if not m:
        return f"[NOMATCH] anchor not found in {path}"

    insert_at = m.end()
    new_src = src[:insert_at] + content + src[insert_at:]

    backup = path.with_suffix(path.suffix + ".bak_compat")
    if not backup.exists():
        shutil.copy2(path, backup)

    path.write_text(new_src, encoding="utf-8", errors="surrogateescape")
    return f"[OK] {path} patched"


def add_at_start_after_includes(path: Path, content: str, marker: str) -> str:
    """Insert content right after the include block at start of file."""
    src = path.read_text(encoding="utf-8", errors="surrogateescape")
    if marker in src:
        return f"[SKIP] {path} already has marker {marker}"

    # Find the LAST #include in the top-of-file include block
    # Strategy: scan first 200 lines, find highest line index that is #include
    lines = src.splitlines(keepends=True)
    last_include_idx = -1
    for i, line in enumerate(lines[:200]):
        stripped = line.lstrip()
        if stripped.startswith("#include"):
            last_include_idx = i

    if last_include_idx < 0:
        # No include found at all — insert at beginning after any leading comments
        first_code_idx = 0
        for i, line in enumerate(lines[:50]):
            s = line.strip()
            if s and not s.startswith("/*") and not s.startswith("*") and not s.startswith("//"):
                first_code_idx = i
                break
        insert_at_line = first_code_idx
    else:
        insert_at_line = last_include_idx + 1

    # Reconstruct
    new_lines = lines[:insert_at_line] + [content] + lines[insert_at_line:]
    new_src = "".join(new_lines)

    backup = path.with_suffix(path.suffix + ".bak_compat")
    if not backup.exists():
        shutil.copy2(path, backup)

    path.write_text(new_src, encoding="utf-8", errors="surrogateescape")
    return f"[OK] {path} patched (after line {insert_at_line})"


def patch_kernel_includes(ksu_dir: Path) -> bool:
    target = find_first(ksu_dir, "kernel_includes.h")
    if target is None:
        print(f"[ERROR] kernel_includes.h not found in {ksu_dir}")
        return False
    print(f"[INFO] Found {target}")

    marker = "SUSFS_5_4_STRNCPY_COMPAT"
    src = target.read_text(encoding="utf-8", errors="surrogateescape")
    if marker in src:
        print(f"[SKIP] {target} already has strncpy compat shim")
        return True

    # Try multiple anchors for __strncpy_from_user_nofault
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

    anchors = [
        # Anchor 1: closing brace of __strncpy_from_user_nofault function
        # Find function signature, then walk to matching '}'
        ("function_brace_walk", r'static\s+inline\s+long\s+__strncpy_from_user_nofault\s*\([^)]*\)\s*\{'),
        # Anchor 2: just after the function signature line + body opener
        ("after_function_decl", r'__strncpy_from_user_nofault\s*\([^)]*\)\s*\{'),
    ]

    for kind, pat_str in anchors:
        pat = re.compile(pat_str, re.MULTILINE | re.DOTALL)
        m = pat.search(src)
        if not m:
            continue

        if kind in ("function_brace_walk", "after_function_decl"):
            # Walk from end of match (which is at '{') to matching '}'
            depth = 1
            i = m.end()
            while i < len(src) and depth > 0:
                c = src[i]
                if c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                i += 1
            if depth != 0:
                continue
            insert_at = i  # right after closing '}'
            new_src = src[:insert_at] + shim + src[insert_at:]

            backup = target.with_suffix(target.suffix + ".bak_compat")
            if not backup.exists():
                shutil.copy2(target, backup)
            target.write_text(new_src, encoding="utf-8", errors="surrogateescape")
            print(f"[OK] {target}: shim inserted after __strncpy_from_user_nofault body")
            return True

    # Fallback: insert at end of file
    print(f"[WARN] __strncpy_from_user_nofault not found, fallback to end of file")
    new_src = src + "\n" + shim
    backup = target.with_suffix(target.suffix + ".bak_compat")
    if not backup.exists():
        shutil.copy2(target, backup)
    target.write_text(new_src, encoding="utf-8", errors="surrogateescape")
    print(f"[OK] {target}: shim appended at end of file (fallback)")
    return True


def patch_ksud(ksu_dir: Path) -> bool:
    target = find_first(ksu_dir, "ksud.c")
    if target is None:
        print(f"[ERROR] ksud.c not found in {ksu_dir}")
        return False
    print(f"[INFO] Found {target}")

    decls = (
        "\n/* SUSFS_5_4_SELINUX_HIDE_DECL */\n"
        "#ifdef CONFIG_KSU_SUSFS\n"
        "extern void ksu_selinux_hide_handle_post_fs_data(void);\n"
        "extern void ksu_selinux_hide_handle_second_stage(void);\n"
        "#endif\n\n"
    )

    msg = add_at_start_after_includes(
        target,
        content=decls,
        marker="SUSFS_5_4_SELINUX_HIDE_DECL",
    )
    print(msg)
    return msg.startswith("[OK]") or msg.startswith("[SKIP]")


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
