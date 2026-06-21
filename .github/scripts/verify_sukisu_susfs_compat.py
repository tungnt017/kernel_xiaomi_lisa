#!/usr/bin/env python3
"""
Pre-build compatibility check (v2).

Symbol categorization:
  - kernel_required: MUST be in SUSFS kernel headers
    (e.g. function decls SukiSU module calls into kernel-side susfs.c)
  - either_ok: defined either in SUSFS headers OR in SukiSU module itself
    (e.g. SUSFS_MAGIC is typically self-defined in SukiSU module)
  - cmd_required: CMD_* constants used in IOCTL switch
"""
import re
import sys
from pathlib import Path


KERNEL_REQUIRED = [
    "susfs_is_current_ksu_domain",
    "susfs_sus_ino_for_filldir64",
]

CMD_REQUIRED = [
    "CMD_SUSFS_ADD_SUS_PATH",
]

# These can be defined in SukiSU's own headers OR SUSFS headers
EITHER_OK = [
    "SUSFS_MAGIC",
    "susfs_get_enabled_features",
    "susfs_handle_sus_path",
]


def collect_text(root: Path, patterns):
    out = ""
    for p in patterns:
        for f in root.rglob(p):
            try:
                out += "\n" + f.read_text(encoding="utf-8", errors="surrogateescape")
            except Exception:
                pass
    return out


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

    # Concatenate SUSFS upstream headers/source
    susfs_text = collect_text(susfs_dir / "kernel_patches", ["susfs*.h", "susfs*.c"])
    print(f"==> SUSFS source bundle bytes: {len(susfs_text)}")

    # Concatenate SukiSU module
    sukisu_text = collect_text(ksu_dir, ["*.c", "*.h"])
    print(f"==> SukiSU source bundle bytes: {len(sukisu_text)}")

    print()
    print("=== Compatibility checks ===")
    fail = 0

    # KERNEL_REQUIRED: must be in SUSFS upstream + called by SukiSU
    for sym in KERNEL_REQUIRED:
        in_susfs = re.search(rf'\b{re.escape(sym)}\b', susfs_text) is not None
        called_by_sukisu = re.search(rf'\b{re.escape(sym)}\b', sukisu_text) is not None
        if called_by_sukisu and not in_susfs:
            print(f"[MISMATCH] '{sym}' is CALLED by SukiSU but NOT in SUSFS upstream")
            fail += 1
        elif called_by_sukisu and in_susfs:
            print(f"[OK]       '{sym}' in both (kernel-required)")
        elif in_susfs and not called_by_sukisu:
            print(f"[note]     '{sym}' in SUSFS upstream but unused by SukiSU (fine)")
        else:
            print(f"[note]     '{sym}' not present in either (feature may be off)")

    # CMD_REQUIRED: must be in SUSFS upstream if called by SukiSU
    for sym in CMD_REQUIRED:
        in_susfs = re.search(rf'\b{re.escape(sym)}\b', susfs_text) is not None
        called_by_sukisu = re.search(rf'\b{re.escape(sym)}\b', sukisu_text) is not None
        if called_by_sukisu and not in_susfs:
            print(f"[MISMATCH] CMD '{sym}' used by SukiSU but NOT in SUSFS upstream")
            fail += 1
        elif called_by_sukisu and in_susfs:
            print(f"[OK]       CMD '{sym}' in both")
        else:
            print(f"[note]     CMD '{sym}' not present (optional)")

    # EITHER_OK: needs to exist somewhere (SUSFS OR SukiSU module)
    for sym in EITHER_OK:
        in_susfs = re.search(rf'\b{re.escape(sym)}\b', susfs_text) is not None
        in_sukisu = re.search(rf'\b{re.escape(sym)}\b', sukisu_text) is not None
        # Detect if SukiSU defines it (not just uses)
        defined_in_sukisu = re.search(
            rf'#\s*define\s+{re.escape(sym)}\b', sukisu_text
        ) is not None or re.search(
            rf'\b(int|long|bool|void|u32|u64|s32|s64|static|extern)[^;]*\b{re.escape(sym)}\s*\(', sukisu_text
        ) is not None

        if defined_in_sukisu:
            print(f"[OK]       '{sym}' self-defined by SukiSU (either-ok)")
        elif in_susfs:
            print(f"[OK]       '{sym}' provided by SUSFS upstream (either-ok)")
        elif in_sukisu and not in_susfs:
            print(f"[MISMATCH] '{sym}' referenced by SukiSU but not defined anywhere")
            fail += 1
        else:
            print(f"[note]     '{sym}' not present anywhere (feature may be off)")

    print()
    print(f"--- Summary --- Failures: {fail}")
    if fail:
        print("[ERROR] Compatibility check failed.")
        return 1
    print("[OK] No real mismatches. Safe to proceed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
