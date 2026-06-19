#!/usr/bin/env python3
from pathlib import Path

ROOT = Path('.').resolve()
compat_c = ROOT / 'fs' / 'susfs_resukisu_compat.c'
makefile = ROOT / 'fs' / 'Makefile'

if not makefile.exists():
    print('[WARN] fs/Makefile not found')
    raise SystemExit(0)

compat_src = """// SPDX-License-Identifier: GPL-2.0
/*
 * ReSukiSU <-> SUSFS compatibility fallbacks.
 *
 * This file exists only for experimental partial SUSFS integrations where
 * ReSukiSU references SUSFS helper symbols that are not exported by the
 * selected susfs4ksu kernel patch set. All definitions are weak so a real
 * SUSFS implementation overrides them automatically when present.
 */
#include <linux/types.h>
#include <linux/errno.h>
#include <linux/kernel.h>
#include <linux/compiler.h>

#ifndef __weak
#define __weak __attribute__((weak))
#endif

/* Called from ReSukiSU umount/supercall paths on some SUSFS revisions. */
int __weak susfs_extra_works(void)
{
	return 0;
}

int __weak susfs_enable_log(void *arg)
{
	return 0;
}

int __weak susfs_show_version(void *arg)
{
	return 0;
}

int __weak susfs_get_enabled_features(void *arg)
{
	return 0;
}

int __weak susfs_show_variant(void *arg)
{
	return 0;
}

int __weak susfs_start_sdcard_monitor_fn(void *data)
{
	return 0;
}

bool __weak susfs_is_current_proc_umounted(void)
{
	return false;
}
"""

old = compat_c.read_text(errors='ignore') if compat_c.exists() else ''
if old != compat_src:
    compat_c.write_text(compat_src)
    print('[OK] wrote fs/susfs_resukisu_compat.c weak fallback symbols')
else:
    print('[SKIP] fs/susfs_resukisu_compat.c already up to date')

mf = makefile.read_text(errors='ignore')
line = 'obj-$(CONFIG_KSU_SUSFS) += susfs_resukisu_compat.o'
if line not in mf:
    core = 'obj-$(CONFIG_KSU_SUSFS) += susfs.o'
    if core in mf:
        mf = mf.replace(core, core + '\n' + line, 1)
    else:
        mf = mf.rstrip() + '\n' + line + '\n'
    makefile.write_text(mf)
    print('[OK] added susfs_resukisu_compat.o to fs/Makefile')
else:
    print('[SKIP] fs/Makefile already builds susfs_resukisu_compat.o')

print('[DONE] ReSukiSU SUSFS weak fallback symbol patch complete')
