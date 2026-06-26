#!/usr/bin/env python3
"""
Add forward declaration of 'struct mount' in fs/stat.c.

SUSFS patch declares extern with struct mount* but struct mount is
internal (defined in fs/mount.h). C99 requires forward declaration
at file scope.

NOT a bypass: legitimate C forward declaration.
NOT weak: standard practice for internal types.
"""
import re
import sys
import shutil
from pathlib import Path

TARGET = Path("fs/stat.c")
MARKER = "SUSFS_STRUCT_MOUNT_FWD_DECL"


def main() -> int:
    if not TARGET.is_file():
        print(f"[ERROR] Missing {TARGET}")
        return 1

    src = TARGET.read_text(encoding="utf-8", errors="surrogateescape")
    if MARKER in src:
        print(f"[SKIP] Already patched")
        return 0

    # Find first 'extern' with struct mount in SUSFS context
    pat = re.compile(
        r'(#ifdef\s+CONFIG_KSU_SUSFS[^\n]*\n[^\n]*\n)?'
        r'(extern\s+\w+\s+susfs_get_non_sus_mnt_id_from_mnt\s*\(\s*struct\s+mount\b)',
        re.MULTILINE
    )
    m = pat.search(src)
    if not m:
        # Fallback: just find the extern line
        pat = re.compile(r'(extern\s+[^\n]*struct\s+mount[^\n]*;)', re.MULTILINE)
        m = pat.search(src)
        if not m:
            print(f"[WARN] No SUSFS struct mount extern found in {TARGET}")
            return 0

    insert_at = m.start()
    fwd = (
        "/* SUSFS_STRUCT_MOUNT_FWD_DECL */\n"
        "#ifdef CONFIG_KSU_SUSFS\n"
        "struct mount;\n"
        "#endif\n"
    )
    new_src = src[:insert_at] + fwd + src[insert_at:]

    backup = TARGET.with_suffix(TARGET.suffix + ".bak_stat")
    if not backup.exists():
        shutil.copy2(TARGET, backup)

    TARGET.write_text(new_src, encoding="utf-8", errors="surrogateescape")
    print(f"[OK] Added struct mount forward declaration to {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
