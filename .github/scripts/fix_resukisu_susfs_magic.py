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
    define_block = 