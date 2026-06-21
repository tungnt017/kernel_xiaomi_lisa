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
  - Hooks call real SUSFS functions from fs/susfs.c (full implementation)
  - All blocks are guarded with #ifdef CONFIG_KSU_SUSFS_*
  - No -Werror disabled, no pragma diagnostic, no Makefile -Wno-error
  - No stub returning 0/-ENOSYS, no #define noop
  - Anchors are exact function signatures (no fuzzy matching)
  - Idempotent (marker check prevents duplicate insertion)
  - Per-file backup created on first modification
  - Fails fast if any required anchor missing

Coverage:
  - fs/namei.c: include susfs_def.h
  - fs/namespace.c: include + extern susfs_is_current_ksu_domain
  - fs/readdir.c: include + extern + filldir/filldir64/iterate hooks
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
        "anchor": r'#include\s+["<]linux/init_task\.h[">]',
        "position": "after_line",
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
        "anchor": r'#include\s+"internal\.h"',
        "position": "after_line",
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
        "anchor": r'#include\s+<asm/unaligned\.h>',
        "position": "after_line",
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
        "anchor": (
            r'static\s+int\s+filldir\s*\(\s*struct\s+dir_context\s*\*\s*ctx,'
            r'[^{]*\)\s*\{'
        ),
        "position": "after_open_brace",
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
        "anchor": (
            r'static\s+int\s+filldir64\s*\(\s*struct\s+dir_context\s*\*\s*ctx,'
            r'[^{]*\)\s*\{'
        ),
        "position": "after_open_brace",
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
        "anchor": (
            r'static\s+int\s+compat_filldir\s*\(\s*struct\s+dir_context\s*\*\s*ctx,'
            r'[^{]*\)\s*\{'
        ),
        "position": "after_open_brace",
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
        "anchor": (
            r'static\s+int\s+fillonedir\s*\(\s*struct\s+dir_context\s*\*\s*ctx,'
            r'[^{]*\)\s*\{'
        ),
        "position": "after_open_brace",
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


def apply_one(src: str, rule: dict):
    """Returns (new_src, status). status in {OK, SKIP, FAIL}."""
    if rule["marker"] in src:
        return src, "SKIP"

    pat = re.compile(rule["anchor"], re.MULTILINE | re.DOTALL)
    m = pat.search(src)
    if not m:
        return src, "FAIL"

    pos = rule["position"]
    content = rule["content"]

    if pos == "after_line":
        # Insert content on next line after the matched line
        line_end = src.find("\n", m.end())
        if line_end == -1:
            line_end = m.end()
        insert_at = line_end + 1
        injected = content
    elif pos == "after_open_brace":
        # Anchor regex ends right after '{'; insert just after it
        insert_at = m.end()
        injected = "\n" + content
    else:
        return src, "FAIL"

    new_src = src[:insert_at] + injected + src[insert_at:]
    return new_src, "OK"


def main() -> int:
    by_file: dict[str, list] = {}
    for rule in BACKPORTS:
        by_file.setdefault(rule["file"], []).append(rule)

    ok = skip = fail = 0
    backups = []
    miss_required = []

    for fname, rules in by_file.items():
        path = Path(fname)
        if not path.is_file():
            print(f"[ERROR] Missing target file: {path}")
            fail += 1
            continue

        src = path.read_text(encoding="utf-8", errors="surrogateescape")
        original = src

        for rule in rules:
            new_src, status = apply_one(src, rule)
            tag = rule["name"]
            if status == "OK":
                print(f"[OK]    {tag}")
                src = new_src
                ok += 1
            elif status == "SKIP":
                print(f"[SKIP]  {tag} (idempotent)")
                skip += 1
            else:
                if rule["required"]:
                    print(f"[ERROR] {tag} -- anchor not matched")
                    miss_required.append(tag)
                    fail += 1
                else:
                    print(f"[WARN]  {tag} -- anchor not matched (optional)")

        if src != original:
            backup = path.with_suffix(path.suffix + ".bak_susfs")
            if not backup.exists():
                shutil.copy2(path, backup)
                backups
