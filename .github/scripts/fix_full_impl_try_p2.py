#!/usr/bin/env python3
"""Patch apply_resukisu_susfs_full_impl.py to try patch -p2.

Why:
SUSFS KernelSU integration patch may contain paths like:
    a/kernel/allowlist.c
    a/kernel/ksu.c
    a/kernel/selinux/rules.c

When ReSukiSU is checked out as KernelSU/ and files are directly under that
folder, applying from KernelSU/ needs strip level -p2 so:
    a/kernel/allowlist.c -> allowlist.c

This script changes the full SUSFS apply script from trying only -p1/-p0 to
trying -p2/-p1/-p0.
"""
from pathlib import Path
import py_compile

TARGET = Path('.github/scripts/apply_resukisu_susfs_full_impl.py')

if not TARGET.exists():
    raise SystemExit(f'[ERROR] target not found: {TARGET}')

text = TARGET.read_text(errors='ignore')
original = text

# Common exact pattern used by the current script.
text = text.replace('for strip in (1, 0):', 'for strip in (2, 1, 0):', 1)

# Fallback for whitespace variants.
if text == original:
    text = text.replace('for strip in [1, 0]:', 'for strip in [2, 1, 0]:', 1)

# Improve error text if present.
text = text.replace(
    'failed to apply KernelSU SUSFS integration patch cleanly. Tried: ',
    'failed to apply KernelSU SUSFS integration patch cleanly even with -p2/-p1/-p0. Tried: ',
    1,
)

if text == original:
    print('[SKIP] No matching strip loop found; script may already be patched or layout changed.')
else:
    TARGET.write_text(text)
    py_compile.compile(str(TARGET), doraise=True)
    print('[OK] Patched apply_resukisu_susfs_full_impl.py to try patch strip levels: -p2, -p1, -p0')
