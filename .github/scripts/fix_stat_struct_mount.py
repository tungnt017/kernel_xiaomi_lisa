#!/usr/bin/env python3
"""
Add forward declaration of 'struct mount' in fs/stat.c.

SUSFS patch declares: extern int susfs_get_non_sus_mnt_id_from_mnt(struct mount *)
But 'struct mount' is internal (defined in fs/mount.h, not exported).
C99 requires forward declaration at file scope.

NOT a bypass: standard C forward declaration.
NOT weak: legitimate handling of incomplete types.
Idempotent + backup.
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
        print(f"[SKIP] Already patched (idempotent)")
        return 0

    # Find first 'extern' referencing 'struct mount'
    pat = re.compile(
        r'(extern\s+[^;\n]*\bstruct\s+mount\b[^;\n]*;)',
        re.MULTILINE
    )
    m = pat.search(src)
    if not m:
        print(f"[WARN] No SUSFS struct mount extern found in {TARGET}")
        print("       Source may not yet have SUSFS patch applied.")
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
        print(f"[BACKUP] {backup}")

    TARGET.write_text(new_src, encoding="utf-8", errors="surrogateescape")
    print(f"[OK] Added 'struct mount;' forward declaration to {TARGET}")
    print(f"[DONE] {TARGET} patched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
