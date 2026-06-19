#!/usr/bin/env python3
"""Resolve known SUSFS kernel-5.4 rejects for Xiaomi lisa tree.

Expected rejects from susfs4ksu kernel-5.4 patch:
  - include/linux/mount.h.rej
  - fs/proc/task_mmu.c.rej
  - fs/proc/fd.c.rej

This script safely resolves the deterministic rejects:
  1. include/linux/mount.h: add susfs_mnt_id_backup to Android KABI slot 4.
  2. fs/proc/task_mmu.c: include <linux/susfs_def.h> when SUS_KSTAT is enabled.

The fd.c reject is context-sensitive and mainly affects /proc fdinfo mount-id
masking. The script keeps it as a warning unless you manually backport that hunk.
"""
from pathlib import Path

ROOT = Path.cwd()

def log(msg: str):
    print(msg, flush=True)

def replace_once(path: Path, old: str, new: str, desc: str) -> bool:
    if not path.exists():
        log(f"[WARN] {desc}: missing {path}")
        return False
    s = path.read_text(errors="ignore")
    if new in s:
        log(f"[OK] {desc}: already present")
        return True
    if old not in s:
        log(f"[WARN] {desc}: pattern not found in {path}")
        return False
    path.write_text(s.replace(old, new, 1))
    log(f"[OK] {desc}: patched {path}")
    return True

def insert_after(path: Path, marker: str, block: str, desc: str) -> bool:
    if not path.exists():
        log(f"[WARN] {desc}: missing {path}")
        return False
    s = path.read_text(errors="ignore")
    if block in s:
        log(f"[OK] {desc}: already present")
        return True
    if marker not in s:
        log(f"[WARN] {desc}: marker not found in {path}")
        return False
    path.write_text(s.replace(marker, marker + block, 1))
    log(f"[OK] {desc}: patched {path}")
    return True

# 1) include/linux/mount.h reject
mount_path = ROOT / "include/linux/mount.h"
mount_old = "ANDROID_KABI_RESERVE(4);"
mount_new = "#ifdef CONFIG_KSU_SUSFS\n\tANDROID_KABI_USE(4, u64 susfs_mnt_id_backup);\n#else\n\tANDROID_KABI_RESERVE(4);\n#endif"
mount_ok = replace_once(
    mount_path,
    mount_old,
    mount_new,
    "resolve include/linux/mount.h susfs_mnt_id_backup",
)
if mount_ok:
    rej = ROOT / "include/linux/mount.h.rej"
    if rej.exists():
        rej.unlink()
        log("[OK] removed include/linux/mount.h.rej")

# 2) fs/proc/task_mmu.c reject
task_path = ROOT / "fs/proc/task_mmu.c"
task_marker = "#include <linux/pkeys.h>\n"
task_block = "#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT\n#include <linux/susfs_def.h>\n#endif\n"
task_ok = insert_after(
    task_path,
    task_marker,
    task_block,
    "resolve fs/proc/task_mmu.c susfs_def include",
)
if task_ok:
    rej = ROOT / "fs/proc/task_mmu.c.rej"
    if rej.exists():
        rej.unlink()
        log("[OK] removed fs/proc/task_mmu.c.rej")

# 3) fs/proc/fd.c reject is optional/context-sensitive.
fd_rej = ROOT / "fs/proc/fd.c.rej"
if fd_rej.exists():
    log("[WARN] fs/proc/fd.c.rej remains: optional fdinfo mnt_id masking hunk not auto-merged")
    log("[WARN] Build can continue; inspect fd.c manually if full fdinfo hiding is required")

remaining = sorted(ROOT.rglob("*.rej"))
if remaining:
    log("[WARN] remaining reject files:")
    for p in remaining:
        log(f"  - {p.relative_to(ROOT)}")
else:
    log("[OK] no reject files remain")
