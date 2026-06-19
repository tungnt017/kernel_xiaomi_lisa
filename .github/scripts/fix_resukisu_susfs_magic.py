#!/usr/bin/env python3
from pathlib import Path
import re

ROOT = Path('.').resolve()
path = ROOT / 'drivers' / 'kernelsu' / 'supercall' / 'supercall.c'

if not path.exists():
    print('[WARN] drivers/kernelsu/supercall/supercall.c not found')
    raise SystemExit(0)

data = path.read_text(errors='ignore')
orig = data

# ReSukiSU supercall.c may use SUSFS_MAGIC while the SUSFS header set being
# used by this experimental kernel does not export the macro to this file.
# SUSFS userspace tools conventionally use 0xFAFAFAFA for SUSFS_MAGIC.
if 'SUSFS_MAGIC' in data and '#define SUSFS_MAGIC' not in data:
    define_block = """
#ifndef SUSFS_MAGIC
#define SUSFS_MAGIC 0xFAFAFAFA
#endif
"""

    # Prefer placing after local includes, before code. If include section is
    # hard to detect, place at top; guarded define is safe either way.
    include_matches = list(re.finditer(r'^#include\s+[<"].*[>"]\s*$', data, re.M))
    if include_matches:
        pos = include_matches[-1].end()
        data = data[:pos] + define_block + data[pos:]
    else:
        data = define_block + data

    print('[OK] added guarded SUSFS_MAGIC fallback define to drivers/kernelsu/supercall/supercall.c')
else:
    print('[SKIP] SUSFS_MAGIC fallback not needed or already defined')

if data != orig:
    path.write_text(data)
    print('[DONE] patched supercall.c SUSFS_MAGIC fallback')
else:
    print('[DONE] no changes needed')
