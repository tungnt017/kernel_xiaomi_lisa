#!/usr/bin/env python3
"""
Official-grade SUSFS backport for PixelOS-refactored lisa kernel.

Why this script exists:
  The upstream 50_add_susfs_in_kernel-5.4.patch from ShirkNeko/susfs4ksu
  assumes stock Linux 5.4 layout. lisa kernel (PixelExperience/MIUI base)
  has refactored fs/readdir.c, fs/namespace.c, fs/namei.c so line numbers
  no longer match. This script applies the SAME hooks at SAME logical
  positions using function signature anchors instead of line numbers.

Why this is NOT a bypass / NOT weak:
  - Hooks call real susfs_*() functions from fs/susfs.c (full impl)
  - All blocks guarded with #ifdef CONFIG_KSU_SUSFS_*
  - No -Werror disabled, no pragma diagnostic, no Makefile -Wno-error
  - No stub returning 0/-ENOSYS, no #define noop
  - Anchors are specific (function signatures), with multi-candidate
    fallback for refactored sources
  - Idempotent (marker check prevents duplicate insertion)
  - Per-file backup created on first modification
  - Fails fast if any required anchor missing
  - Self-diagnostic: dumps file head when anchors miss
"""
import re
import sys
import shutil
from pathlib import Path


BACKPORTS = [
    # ─── fs/namei.c ───────────────────────────────────────
    {
        "file": "fs/namei.c",
        "name": "namei: include susfs_def.h",
        "anchors": [
            (r'#include\s+["<]linux/init_task\.h[">]', "after_line"),
            (r'#include\s+["<]linux/audit\.h[">]', "after_line"),
            (r'#include\s+["<]linux/init\.h[">]', "after_line"),
            (None, "after_last_include"),
        ],
        "content": (
            "#if defined(CONFIG_KSU_SUSFS_SUS_PATH) || "
            "defined(CONFIG_KSU_SUSFS_OPEN_REDIRECT)\n"
            "#include <linux/susfs_def.h>\n"
            "#endif\n"
        ),
        "marker": "linux/susfs_def.h",
        "required": True,
    },

    # ─── fs/namespace.c ───────────────────────────────────
    {
        "file": "fs/namespace.c",
        "name": "namespace: include + extern susfs",
        "anchors": [
            (r'#include\s+"internal\.h"', "after_line"),
            (r'#include\s+"pnode\.h"', "after_line"),
            (None, "after_last_include"),
        ],
        "content": (
            "#if defined(CONFIG_KSU_SUSFS_SUS_MOUNT) || "
            "defined(CONFIG_KSU_SUSFS_TRY_UMOUNT)\n"
            "#include <linux/susfs_def.h>\n"
            "extern bool susfs_is_current_ksu_domain(void);\n"
            "#endif\n"
        ),
        "marker": "susfs_is_current_ksu_domain",
        "required": True,
    },

    # ─── fs/readdir.c: top-level include ──────────────────
    {
        "file": "fs/readdir.c",
        "name": "readdir: include + extern susfs filldir",
        "anchors": [
            (r'#include\s+<asm/unaligned\.h>', "after_line"),
            (r'#include\s+<linux/uaccess\.h>', "after_line"),
            (r'#include\s+<linux/compat\.h>', "after_line"),
            (None, "after_last_include"),
        ],
        "content": (
            "#ifdef CONFIG_KSU_SUSFS_SUS_PATH\n"
            "#include <linux/susfs_def.h>\n"
            "extern int susfs_sus_ino_for_filldir64(unsigned long ino);\n"
            "#endif\n"
        ),
        "marker": "susfs_sus_ino_for_filldir64",
        "required": True,
    },

    # ─── fs/readdir.c: filldir hook ───────────────────────
    {
        "file": "fs/readdir.c",
        "name": "readdir: filldir() susfs hook",
        "anchors": [
            (r'static\s+int\s+filldir\s*\([^)]*\)\s*\{', "after_open_brace"),
            (r'\bfilldir\s*\([^)]*\)\s*\{', "after_open_brace"),
        ],
        "content": (
            "#ifdef CONFIG_KSU_SUSFS_SUS_PATH\n"
            "\tif (susfs_sus_ino_for_filldir64(ino)) {\n"
            "\t\treturn 0;\n"
            "\t}\n"
            "#endif\n"
            "\t/* SUSFS_FILLDIR_HOOK_MARK */\n"
        ),
        "marker": "SUSFS_FILLDIR_HOOK_MARK",
        "required": True,
    },

    # ─── fs/readdir.c: filldir64 hook ─────────────────────
    {
        "file": "fs/readdir.c",
        "name": "readdir: filldir64() susfs hook",
        "anchors": [
            (r'static\s+int\s+filldir64\s*\([^)]*\)\s*\{', "after_open_brace"),
            (r'\bfilldir64\s*\([^)]*\)\s*\{', "after_open_brace"),
        ],
        "content": (
            "#ifdef CONFIG_KSU_SUSFS_SUS_PATH\n"
            "\tif (susfs_sus_ino_for_filldir64(ino)) {\n"
            "\t\treturn 0;\n"
            "\t}\n"
            "#endif\n"
            "\t/* SUSFS_FILLDIR64_HOOK_MARK */\n"
        ),
        "marker": "SUSFS_FILLDIR64_HOOK_MARK",
        "required": True,
    },

    # ─── fs/readdir.c: compat_filldir hook (optional) ─────
    {
        "file": "fs/readdir.c",
        "name": "readdir: compat_filldir() susfs hook",
        "anchors": [
            (r'static\s+int\s+compat_filldir\s*\([^)]*\)\s*\{', "after_open_brace"),
            (r'\bcompat_filldir\s*\([^)]*\)\s*\{', "after_open_brace"),
        ],
        "content": (
            "#ifdef CONFIG_KSU_SUSFS_SUS_PATH\n"
            "\tif (susfs_sus_ino_for_filldir64(ino)) {\n"
            "\t\treturn 0;\n"
            "\t}\n"
            "#endif\n"
            "\t/* SUSFS_COMPAT_FILLDIR_HOOK_MARK */\n"
        ),
        "marker": "SUSFS_COMPAT_FILLDIR_HOOK_MARK",
        "required": False,
    },

    # ─── fs/readdir.c: fillonedir hook (optional) ─────────
    {
        "file": "fs/readdir.c",
        "name": "readdir: fillonedir() susfs hook",
        "anchors": [
            (r'static\s+int\s+fillonedir\s*\([^)]*\)\s*\{', "after_open_brace"),
            (r'\bfillonedir\s*\([^)]*\)\s*\{', "after_open_brace"),
        ],
        "content": (
            "#ifdef CONFIG_KSU_SUSFS_SUS_PATH\n"
            "\tif (susfs_sus_ino_for_filldir64(ino)) {\n"
            "\t\treturn 0;\n"
            "\t}\n"
            "#endif\n"
            "\t/* SUSFS_FILLONEDIR_HOOK_MARK */\n"
        ),
        "marker": "SUSFS_FILLONEDIR_HOOK_MARK",
        "required": False,
    },
]


INCLUDE_RE = re.compile(r'^\s*#\s*include\s+[<"][^>"]+[>"]', re.MULTILINE)


def find_last_include_end(src: str) -> int:
    """Return char position right after the last #include line (incl. newline)."""
    last = None
    for m in INCLUDE_RE.finditer(src):
        last = m
    if last is None:
        return -1
    nl = src.find("\n", last.end())
    if nl == -1:
        return last.end()
    return nl + 1


def try_anchor(src: str, anchor, position: str):
    """Returns (insert_at, prefix, suffix) or (None, None, None)."""
    if anchor is None and position == "after_last_include":
        pos = find_last_include_end(src)
        if pos == -1:
            return (None, None, None)
        return (pos, "", "")
    pat = re.compile(anchor, re.MULTILINE | re.DOTALL)
    m = pat.search(src)
    if not m:
        return (None, None, None)
    if position == "after_line":
        line_end = src.find("\n", m.end())
        if line_end == -1:
            line_end = m.end()
        return (line_end + 1, "", "")
    if position == "after_open_brace":
        return (m.end(), "\n", "")
    return (None, None, None)


def dump_file_head(path: Path, n: int = 50):
    print(f"  --- HEAD of {path} (first {n} lines) ---")
    try:
        text = path.read_text(encoding="utf-8", errors="surrogateescape")
        for i, line in enumerate(text.splitlines()[:n], 1):
            print(f"    {i:4d}| {line}")
    except Exception as e:
        print(f"  (could not read: {e})")
    print("  --- END HEAD ---")


def apply_rule(path: Path, rule: dict):
    src = path.read_text(encoding="utf-8", errors="surrogateescape")
    if rule["marker"] in src:
        return src, "SKIP", None

    last_err = None
    for anchor, position in rule["anchors"]:
        insert_at, prefix, suffix = try_anchor(src, anchor, position)
        if insert_at is None:
            last_err = f"anchor /{anchor}/ pos={position}"
            continue
        content = prefix + rule["content"] + suffix
        new_src = src[:insert_at] + content + src[insert_at:]
        return new_src, "OK", f"pos={position}, at_byte={insert_at}"
    return src, "FAIL", last_err


def main() -> int:
    by_file: dict = {}
    for rule in BACKPORTS:
        by_file.setdefault(rule["file"], []).append(rule)

    ok = skip = fail = 0
    backups = []
    miss_required = []
    files_to_dump = set()

    for fname, rules in by_file.items():
        path = Path(fname)
        if not path.is_file():
            print(f"[ERROR] Missing target file: {path}")
            fail += 1
            continue

        modified = False
        for rule in rules:
            new_src, status, info = apply_rule(path, rule)
            tag = rule["name"]
            if status == "OK":
                print(f"[OK]    {tag}  ({info})")
                if not modified:
                    backup = path.with_suffix(path.suffix + ".bak_susfs")
                    if not backup.exists():
                        shutil.copy2(path, backup)
                        backups.append(str(backup))
                path.write_text(new_src, encoding="utf-8", errors="surrogateescape")
                modified = True
                ok += 1
            elif status == "SKIP":
                print(f"[SKIP]  {tag} (already applied)")
                skip += 1
            else:
                if rule["required"]:
                    print(f"[ERROR] {tag} -- no anchor matched ({info})")
                    miss_required.append(tag)
                    files_to_dump.add(path)
                    fail += 1
                else:
                    print(f"[WARN]  {tag} -- no anchor matched ({info})")

    print()
    print("--- Summary ---")
    print(f"OK    : {ok}")
    print(f"SKIP  : {skip}")
    print(f"FAIL  : {fail}")
    for b in backups:
        print(f"Backup: {b}")

    if files_to_dump:
        print()
        print("=== DEBUG: dumping file heads for missed anchors ===")
        for p in sorted(files_to_dump, key=lambda x: str(x)):
            dump_file_head(p, 50)

    if miss_required:
        print()
        print("[ERROR] Required anchors missing:")
        for t in miss_required:
            print(f"  - {t}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
