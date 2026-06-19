#!/usr/bin/env python3
from pathlib import Path
import re

ROOT = Path('.').resolve()
path = ROOT / 'drivers' / 'kernelsu' / 'supercall' / 'dispatch.c'

MISSING_CMDS = [
    'CMD_SUSFS_ADD_SUS_PATH_LOOP',
    'CMD_SUSFS_HIDE_SUS_MNTS_FOR_NON_SU_PROCS',
    'CMD_SUSFS_ADD_SUS_MAP',
    'CMD_SUSFS_ENABLE_AVC_LOG_SPOOFING',
]

if not path.exists():
    print('[WARN] drivers/kernelsu/supercall/dispatch.c not found')
    raise SystemExit(0)

data = path.read_text(errors='ignore')
orig = data

for cmd in MISSING_CMDS:
    if f'#ifdef {cmd}' in data or f'#if defined({cmd})' in data:
        print(f'[SKIP] {cmd} already guarded')
        continue

    # Guard exactly one switch-case block. This keeps ABI values unchanged when
    # the command exists, and compiles the block out when ReSukiSU/SUSFS headers
    # do not provide that command for this version.
    pattern = re.compile(
        r'(?P<indent>\s*)case\s+' + re.escape(cmd) + r'\s*:\s*\{(?P<body>.*?)\n(?P=indent)\}\s*\n(?=\s*(?:case\s+CMD_|default\s*:|\}))',
        re.S,
    )

    def repl(m):
        block = m.group(0)
        return f'\n#ifdef {cmd}\n{block}#endif /* {cmd} */\n'

    data, n = pattern.subn(repl, data, count=1)
    if n:
        print(f'[OK] guarded optional SUSFS dispatch case {cmd}')
    else:
        print(f'[WARN] could not find switch case for {cmd}')

if data != orig:
    path.write_text(data)
    print('[DONE] patched optional SUSFS dispatch command guards')
else:
    print('[DONE] no changes needed')
