#!/usr/bin/env python3
"""
Pre-build compatibility check between SukiSU-Ultra (module side) and
ShirkNeko/susfs4ksu (kernel side).

Goal: catch version skew BEFORE running 1-2h kernel build.

Strategy:
  - Read SukiSU-Ultra module's source files (after setup.sh)
  - Read susfs4ksu's headers (after clone)
  - Find symbols that SukiSU calls but susfs4ksu does NOT export
  - Find CMD_* / struct names that SukiSU references but headers lack

This is NOT a bypass: it only INSPECTS, does not patch anything.
Fails fast with exact missing symbol list so user can pin correct versions.
"""
import re
import sys
from pathlib import Path

# Pairs of (callee_pattern_in_sukisu, expected_decl_in_susfs_headers)
EXPECTED_SYMBOLS = [
    # SukiSU calls these → susfs headers must declare them
    ("susfs_handle_sus_path",         r'\bsusfs_handle_sus_path\b'),
    ("susfs_sus_ino_for_filldir64",   r'\bsusfs_sus_ino_for_filldir64\b'),
    ("susfs_is_current_ksu_domain",   r'\bsusfs_is_current_ksu_domain\b'),
    ("SUSFS_MAGIC",                   r'\bSUSFS_MAGIC\b'),
    ("susfs_get_enabled_features",    r'\bsusfs_get_enabled_features\b'),
    ("CMD_SUSFS_ADD_SUS_PATH",        r'\bCMD_SUSFS_ADD_SUS_PATH\b'),
    ("CMD_SUSFS_ADD_SUS_MOUNT",       r'\bCMD_SUSFS_ADD_SUS_MOUNT\b'),
]


def find_susfs_files(susfs_root: Path):
    candidates = []
    for sub in ("include/linux", "fs"):
        d = susfs_root / "kernel_patches" / sub
        if d.exists():
            candidates += list(d.glob("susfs*.h")) + list(d.glob("susfs*.c"))
    return candidates


def find_sukisu_files(ksu_root: Path):
    return list(ksu_root.rglob("*.c")) + list(ksu_root.rglob("*.h"))


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: verify_sukisu_susfs_compat.py <KSU_DIR> <SUSFS_REPO_DIR>")
        return 2

    ksu_dir = Path(sys.argv[1])
    susfs_dir = Path(sys.argv[2])

    if not ksu_dir.is_dir():
        print(f"[ERROR] KSU_DIR not found: {ksu_dir}")
        return 1
    if not susfs_dir.is_dir():
        print(f"[ERROR] SUSFS_REPO_DIR not found: {susfs_dir}")
        return 1

    # Concatenate all susfs header/source content
    susfs_files = find_susfs_files(susfs_dir)
    if not susfs_files:
        print(f"[ERROR] No susfs*.h/c in {susfs_dir}")
        return 1
    susfs_text = "\n".join(
        f.read_text(encoding="utf-8", errors="surrogateescape")
        for f in susfs_files
    )
    print(f"==> SUSFS source bundle: {len(susfs_files)} files, "
          f"{len(susfs_text)} bytes")

    # Concatenate all SukiSU module sources
    sukisu_files = find_sukisu_files(ksu_dir)
    sukisu_text = "\n".join(
        f.read_text(encoding="utf-8", errors="surrogateescape")
        for f in sukisu_files
    )
    print(f"==> SukiSU source bundle: {len(sukisu_files)} files, "
          f"{len(sukisu_text)} bytes")

    print()
    print("=== Compatibility checks ===")
    missing = []
    for sym, pat in EXPECTED_SYMBOLS:
        sukisu_calls = re.search(pat, sukisu_text) is not None
        susfs_decls  = re.search(pat, susfs_text) is not None

        if sukisu_calls and not susfs_decls:
            print(f"[MISMATCH] '{sym}' is CALLED by SukiSU but NOT declared in SUSFS headers")
            missing.append(sym)
        elif sukisu_calls and susfs_decls:
            print(f"[OK]       '{sym}' present in both")
        elif susfs_decls and not sukisu_calls:
            print(f"[note]     '{sym}' in SUSFS but unused by SukiSU (fine)")
        else:
            print(f"[note]     '{sym}' not present in either (feature may be off)")

    print()
    print("--- Summary ---")
    print(f"Mismatches: {len(missing)}")
    if missing:
        print()
        print("[ERROR] SukiSU-Ultra and SUSFS versions are INCOMPATIBLE.")
        print("        Missing symbols in SUSFS headers:")
        for m in missing:
            print(f"  - {m}")
        print()
        print("  => Action: pin SukiSU-Ultra to an older version that matches")
        print("     SUSFS branch you cloned, OR pick newer SUSFS branch/tag.")
        return 1

    print("[OK] No mismatches detected. Safe to proceed with build.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
