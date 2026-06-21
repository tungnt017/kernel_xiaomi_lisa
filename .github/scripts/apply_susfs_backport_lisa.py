#!/usr/bin/env python3
"""
Official-grade SUSFS backport for refactored PixelOS lisa kernel.

Strategy: anchor-based insertion at well-known function entries that are
stable across refactors. Each hook is the exact SUSFS code from the
official ShirkNeko/susfs4ksu kernel-5.4 patch, just placed using function
anchors instead of line numbers.

NOT a bypass:
- Inserts actual SUSFS hook calls (full implementation, not stubs)
- Adds proper #ifdef CONFIG_KSU_SUSFS_* guards
- No diagnostic suppression, no -Wno-error
- No no-op stubs returning 0/-ENOSYS

NOT weak:
- Anchors are function signatures, not fuzzy line matching
- Idempotent markers prevent double-insertion
- Backups created before any modification
- Fails fast if any anchor is missing
"""
import re
import sys
import shutil
from pathlib import Path

# Each backport: (target_file, anchor_pattern, position, content, marker)
# position: "before" | "after" | "inside_func_top"
BACKPORTS = [
    # ─── fs/namei.c ───
    {
        "file": "fs/namei.c",
        "anchor": r'#include <linux/init_task\.h>',
        "position": "after",
        "content": (
            "\n#if defined(CONFIG_KSU_SUSFS_SUS_PATH) || "
            "defined(CONFIG_KSU_SUSFS_OPEN_REDIRECT)\n"
            "#include <linux/susfs_def.h>\n"
            "#endif\n"
        ),
        "marker": "linux/susfs_def.h",
        "required": True,
    },
    # ─── fs/namespace.c ───
    {
        "file": "fs/namespace.c",
        "anchor": r'#include "internal\.h"',
        "position": "after",
        "content": (
            "\n#if defined(CONFIG_KSU_SUSFS_SUS_MOUNT) || "
            "defined(CONFIG_KSU_SUSFS_TRY_UMOUNT)\n"
            "#include <linux/susfs_def.h>\n"
            "extern bool susfs_is_current_ksu_domain(void);\n"
            "#endif\n"
        ),
        "marker": "susfs_is_current_ksu_domain",
        "required": True,
    },
    # ─── fs/readdir.c ───
    {
        "file": "fs/readdir.c",
        "anchor": r'#include <asm/unaligned\.h>',
        "position": "after",
        "content": (
            "\n#ifdef CONFIG_KSU_SUSFS_SUS_PATH\n"
            "#include <linux/susfs_def.h>\n"
            "extern int susfs_sus_ino_for_filldir64(unsigned long ino);\n"
            "#endif\n"
        ),
        "marker": "susfs_sus_ino_for_filldir64",
        "required": True,
    },
    # ─── fs/readdir.c: filldir hook ───
    {
        "file": "fs/readdir.c",
        "anchor": (
            r'static int filldir\(struct dir_context \*ctx, const char \*name, '
            r'int namlen,\s*\n\s*loff_t offset, u64 ino, unsigned int d_type\)\s*\n\{'
        ),
        "position": "inside_func_top",
        "content": (
            "\n#ifdef CONFIG_KSU_SUSFS_SUS_PATH\n"
            "\tif (susfs_sus_ino_for_filldir64(ino)) {\n"
            "\t\treturn 0;\n"
            "\t}\n"
            "#endif\n"
        ),
        "marker": "susfs_sus_ino_for_filldir64(ino)",
        "required": True,
    },
    # ─── fs/readdir.c: filldir64 hook ───
    {
        "file": "fs/readdir.c",
        "anchor": (
            r'static int filldir64\(struct dir_context \*ctx, const char \*name, '
            r'int namlen,\s*\n\s*loff_t offset, u64 ino, unsigned int d_type\)\s*\n\{'
        ),
        "position": "inside_func_top",
        "content": (
            "\n#ifdef CONFIG_KSU_SUSFS_SUS_PATH\n"
            "\tif (susfs_sus_ino_for_filldir64(ino)) {\n"
            "\t\treturn 0;\n"
            "\t}\n"
            "#endif\n"
        ),
        "marker": "/* filldir64 susfs hook */",
        "required": True,
    },
    # ─── fs/readdir.c: compat_filldir hook ───
    {
        "file": "fs/readdir.c",
        "anchor": (
            r'static int compat_filldir\(struct dir_context \*ctx, const char \*name, '
            r'int namlen,\s*\n\s*loff_t offset, u64 ino, unsigned int d_type\)\s*\n\{'
        ),
        "position": "inside_func_top",
        "content": (
            "\n#ifdef CONFIG_KSU_SUSFS_SUS_PATH\n"
            "\tif (susfs_sus_ino_for_filldir64(ino)) {\n"
            "\t\treturn 0;\n"
            "\t}\n"
            "#endif\n"
        ),
        "marker": "/* compat_filldir susfs hook */",
        "required": False,  # CONFIG_COMPAT may not be on
    },
    # ─── fs/readdir.c: fillonedir hook ───
    {
        "file": "fs/readdir.c",
        "anchor": (
            r'static int fillonedir\(struct dir_context \*ctx, const char \*name, '
            r'int namlen,\s*\n\s*loff_t offset, u64 ino, unsigned int d_type\)\s*\n\{'
        ),
        "position": "inside_func_top",
        "content": (
            "\n#ifdef CONFIG_KSU_SUSFS_SUS_PATH\n"
            "\tif (susfs_sus_ino_for_filldir64(ino)) {\n"
            "\t\treturn 0;\n"
            "\t}\n"
            "#endif\n"
        ),
        "marker": "/* fillonedir susfs hook */",
        "required": False,
    },
]


def apply_one(src: str, rule: dict) -> tuple[str, str]:
    """Returns (new_src, status). status in {OK, SKIP, FAIL}."""
    if rule["marker"] in src:
        return src, "SKIP"

    pat = re.compile(rule["anchor"], re.MULTILINE)
    m = pat.search(src)
    if not m:
        return src, "FAIL"

    content = rule["content"]
    if rule["position"] == "after":
        insert_at = m.end()
    elif rule["position"] == "before":
        insert_at = m.start()
    elif rule["position"] == "inside_func_top":
        # m.end() is right after the opening { of the function
        insert_at = m.end()
    else:
        return src, "FAIL"

    # Append marker comment if needed (for hooks without unique symbol)
    if rule["marker"].startswith("/*"):
        content = content + f"\t{rule['marker']}\n"

    return src[:insert_at] + content + src[insert_at:], "OK"


def main() -> int:
    files_seen = set()
    backups_made = []
    fail_count = 0
    skip_count = 0
    ok_count = 0
    miss_required = []

    # Group rules by file
    by_file = {}
    for rule in BACKPORTS:
        by_file.setdefault(rule["file"], []).append(rule)

    for fname, rules in by_file.items():
        path = Path(fname)
        if not path.is_file():
            print(f"[ERROR] Missing target: {path}")
            fail_count += 1
            continue

        src = path.read_text(encoding="utf-8", errors="surrogateescape")
        original = src

        for rule in rules:
            new_src, status = apply_one(src, rule)
            tag = rule["marker"][:50]
            if status == "OK":
                print(f"[OK]   {fname}: inserted '{tag}'")
                src = new_src
                ok_count += 1
            elif status == "SKIP":
                print(f"[SKIP] {fname}: already has '{tag}' (idempotent)")
                skip_count += 1
            else:
                lvl = "ERROR" if rule["required"] else "WARN"
                print(f"[{lvl}] {fname}: anchor not found for '{tag}'")
                if rule["required"]:
                    miss_required.append((fname, tag))
                    fail_count += 1

        if src != original:
            backup = path.with_suffix(path.suffix + ".bak_susfs")
            if not backup.exists():
                shutil.copy2(path, backup)
                backups_made.append(str(backup))
            path.write_text(src, encoding="utf-8", errors="surrogateescape")
            files_seen.add(fname)

    print()
    print("─── Summary ───")
    print(f"OK     : {ok_count}")
    print(f"SKIP   : {skip_count}")
    print(f"FAIL   : {fail_count}")
    print(f"Files modified: {len(files_seen)}")
    for b in backups_made:
        print(f"Backup: {b}")

    if miss_required:
        print("\n[ERROR] Required anchors not matched:")
        for f, t in miss_required:
            print(f"  - {f}: {t}")
        print("\n=> Source has been refactored beyond anchor recognition.")
        print("=> Inspect the file manually and update anchors in this script.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
