#!/usr/bin/env python3
from pathlib import Path
import re

ROOT = Path('.').resolve()
path = ROOT / 'fs' / 'proc' / 'fd.c'

if not path.exists():
    print('[WARN] fs/proc/fd.c not found')
    raise SystemExit(0)

data = path.read_text(errors='ignore')

# The SUSFS 5.4 patch may apply the declaration hunk but reject the usage hunk,
# leaving an unused local variable under CONFIG_KSU_SUSFS_SUS_MOUNT:
#   struct mount *mnt = NULL;
# Kernel builds with -Werror, so this becomes fatal.
if 'struct mount *mnt = NULL;' in data:
    # If the actual SUSFS usage hunk was not applied, remove the orphan declaration.
    usage_count = data.count('mnt->') + data.count('mnt = real_mount')
    if usage_count == 0:
        data = re.sub(
            r'\n#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\s*\n\s*struct mount \*mnt = NULL;\s*\n#endif\s*\n',
            '\n',
            data,
            flags=re.S,
        )
        path.write_text(data)
        print('[OK] removed orphan unused mnt declaration from fs/proc/fd.c')
    else:
        print('[SKIP] fs/proc/fd.c uses mnt; leaving declaration intact')
else:
    print('[SKIP] no orphan mnt declaration found in fs/proc/fd.c')
