#!/usr/bin/env python3
"""
Apply SUSFS as a FULL implementation for ReSukiSU/KernelSU-style trees.

This script intentionally does NOT create weak/no-op fallback symbols.  If the
selected ReSukiSU + susfs4ksu revisions do not contain real implementations for
required SUSFS helpers, it fails loudly and asks you to pin compatible commits.

Expected repo layout in CI:
  - kernel source at current working directory
  - susfs4ksu cloned to SUSFS_DIR, default: susfs-src
  - ReSukiSU already integrated under drivers/kernelsu or KernelSU
"""
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys

ROOT = Path('.').resolve()
SUSFS_DIR = Path(os.environ.get('SUSFS_DIR', 'susfs-src')).resolve()
DEFCONFIG = os.environ.get('DEFCONFIG', 'lisa_defconfig')
SUSFS_KERNEL_PATCH = os.environ.get('SUSFS_KERNEL_PATCH', '').strip()

FULL_CONFIGS_ON = [
    'CONFIG_KSU=y',
    'CONFIG_KSU_SUSFS=y',
    'CONFIG_KSU_SUSFS_HAS_MAGIC_MOUNT=y',
    'CONFIG_KSU_SUSFS_SUS_PATH=y',
    'CONFIG_KSU_SUSFS_SUS_MOUNT=y',
    'CONFIG_KSU_SUSFS_AUTO_ADD_SUS_KSU_DEFAULT_MOUNT=y',
    'CONFIG_KSU_SUSFS_AUTO_ADD_SUS_BIND_MOUNT=y',
    'CONFIG_KSU_SUSFS_SUS_KSTAT=y',
    'CONFIG_KSU_SUSFS_SUS_MAP=y',
    'CONFIG_KSU_SUSFS_TRY_UMOUNT=y',
    'CONFIG_KSU_SUSFS_AUTO_ADD_TRY_UMOUNT_FOR_BIND_MOUNT=y',
    'CONFIG_KSU_SUSFS_SPOOF_UNAME=y',
    'CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG=y',
    'CONFIG_KSU_SUSFS_OPEN_REDIRECT=y',
    'CONFIG_KSU_SUSFS_ENABLE_LOG=y',
    'CONFIG_KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS=y',
]

# Full implementation should come from upstream.  Avoid SUS_SU unless you know
# this ReSukiSU revision supports that mode for your kernel.
FULL_CONFIGS_OFF = [
    '# CONFIG_KSU_SUSFS_SUS_SU is not set',
]

REQUIRED_REAL_SYMBOLS = [
    'susfs_extra_works',
    'susfs_enable_log',
    'susfs_show_version',
    'susfs_get_enabled_features',
    'susfs_show_variant',
    'susfs_start_sdcard_monitor_fn',
    'susfs_is_current_proc_umounted',
]


def read(path):
    return Path(path).read_text(errors='ignore')


def write(path, data):
    Path(path).write_text(data)


def run(cmd, cwd=None, check=True):
    print(f'[RUN] {cmd} cwd={cwd or ROOT}')
    p = subprocess.run(cmd, shell=True, cwd=cwd or ROOT, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f'command failed: {cmd}')
    return p.returncode


def find_defconfig():
    candidates = [
        ROOT / 'arch' / 'arm64' / 'configs' / DEFCONFIG,
        ROOT / 'arch' / 'arm64' / 'configs' / 'vendor' / DEFCONFIG,
    ]
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError(f'defconfig not found: {DEFCONFIG}')


def patch_defconfig_full():
    path = find_defconfig()
    data = read(path)
    remove = []
    for line in FULL_CONFIGS_ON:
        key = line.split('=')[0]
        remove += [key + '=', '# ' + key + ' is not set']
    for line in FULL_CONFIGS_OFF:
        m = re.match(r'# (CONFIG_[A-Za-z0-9_]+) is not set', line)
        if m:
            key = m.group(1)
            remove += [key + '=', '# ' + key + ' is not set']

    lines = [ln for ln in data.splitlines() if not any(ln.startswith(prefix) for prefix in remove)]
    lines += ['', '# ReSukiSU SUSFS full implementation'] + FULL_CONFIGS_ON + FULL_CONFIGS_OFF + ['']
    write(path, '\n'.join(lines) + '\n')
    print(f'[OK] enabled full SUSFS config set in {path}')


def copy_tree_files(src_dir, dst_dir):
    src = Path(src_dir)
    dst = Path(dst_dir)
    if not src.exists():
        print(f'[WARN] missing {src}')
        return
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.is_file():
            target = dst / item.name
            shutil.copy2(item, target)
            print(f'[OK] copied {item} -> {target}')


def find_kernel_patch():
    kp = SUSFS_DIR / 'kernel_patches'
    if SUSFS_KERNEL_PATCH:
        for p in (kp / SUSFS_KERNEL_PATCH, SUSFS_DIR / SUSFS_KERNEL_PATCH, Path(SUSFS_KERNEL_PATCH)):
            if p.exists():
                return p.resolve()
        raise FileNotFoundError(f'SUSFS_KERNEL_PATCH not found: {SUSFS_KERNEL_PATCH}')
    for pat in ['50_add_susfs_in_kernel-5.4*.patch', '50_add_susfs_in_kernel*.patch', '*5.4*.patch']:
        matches = sorted(kp.glob(pat))
        if matches:
            print(f'[OK] selected kernel patch: {matches[0]}')
            return matches[0].resolve()
    raise FileNotFoundError('cannot find SUSFS kernel patch under susfs-src/kernel_patches')


def apply_patch_strict(patch_file, cwd, strip=1):
    patch_file = Path(patch_file).resolve()
    rc = run(f"patch -p{strip} --forward --batch < '{patch_file}'", cwd=cwd, check=False)
    if rc != 0:
        raise RuntimeError(f'patch failed: {patch_file} cwd={cwd} - full implementation requires clean or manually resolved patch')
    print(f'[OK] applied patch {patch_file} in {cwd}')


def try_apply_ksu_integration_patch():
    patch_file = SUSFS_DIR / 'kernel_patches' / 'KernelSU' / '10_enable_susfs_for_ksu.patch'
    if not patch_file.exists():
        raise FileNotFoundError(f'KernelSU integration patch missing: {patch_file}')

    # ReSukiSU may be embedded under drivers/kernelsu; classic KernelSU may be KernelSU/.
    candidates = [ROOT / 'drivers' / 'kernelsu', ROOT / 'KernelSU', ROOT]
    errors = []
    for cwd in candidates:
        if not cwd.exists():
            continue
        for strip in (1, 0):
            print(f'[INFO] trying KernelSU/SUSFS integration patch in {cwd} with -p{strip}')
            rc = run(f"patch -p{strip} --forward --batch < '{patch_file.resolve()}'", cwd=cwd, check=False)
            if rc == 0:
                print(f'[OK] applied KernelSU SUSFS integration patch in {cwd} with -p{strip}')
                return
            errors.append(f'{cwd} -p{strip}')
    raise RuntimeError('failed to apply KernelSU SUSFS integration patch cleanly. Tried: ' + ', '.join(errors))


def remove_weak_fallbacks():
    # Full implementation must not use the old compat weak stubs.
    compat = ROOT / 'fs' / 'susfs_resukisu_compat.c'
    if compat.exists():
        compat.unlink()
        print('[OK] removed weak fallback file fs/susfs_resukisu_compat.c')
    mf = ROOT / 'fs' / 'Makefile'
    if mf.exists():
        data = read(mf)
        data2 = re.sub(r'^obj-\$\(CONFIG_KSU_SUSFS\) \+= susfs_resukisu_compat\.o\s*\n?', '', data, flags=re.M)
        if data2 != data:
            write(mf, data2)
            print('[OK] removed susfs_resukisu_compat.o from fs/Makefile')


def symbol_has_real_definition(symbol):
    # Heuristic: look for a function definition in C files, excluding extern declarations,
    # comments are not fully parsed but this catches normal SUSFS implementations.
    definition_re = re.compile(r'(^|\n)\s*(?!extern\b)(?:[A-Za-z_][\w\s\*]*\s+)?' + re.escape(symbol) + r'\s*\([^;{]*\)\s*\{', re.M)
    for c in list((ROOT / 'fs').glob('*.c')) + list((ROOT / 'drivers' / 'kernelsu').rglob('*.c')):
        try:
            if definition_re.search(read(c)):
                print(f'[OK] real definition found for {symbol} in {c}')
                return True
        except Exception:
            pass
    return False


def verify_real_symbols():
    missing = [s for s in REQUIRED_REAL_SYMBOLS if not symbol_has_real_definition(s)]
    if missing:
        print('[ERROR] Missing real SUSFS implementations:')
        for s in missing:
            print(' - ' + s)
        print('')
        print('This means ReSukiSU and susfs4ksu are out of sync for this kernel tree.')
        print('Pin compatible commits or use a ReSukiSU branch that already carries the matching SUSFS integration.')
        raise SystemExit(2)
    print('[OK] all required ReSukiSU SUSFS helper symbols have real implementations')


def main():
    if not SUSFS_DIR.exists():
        raise FileNotFoundError(f'SUSFS_DIR not found: {SUSFS_DIR}')

    remove_weak_fallbacks()
    patch_defconfig_full()

    # Copy kernel-side SUSFS sources/headers.
    copy_tree_files(SUSFS_DIR / 'kernel_patches' / 'fs', ROOT / 'fs')
    copy_tree_files(SUSFS_DIR / 'kernel_patches' / 'include' / 'linux', ROOT / 'include' / 'linux')

    # Full mode: apply both kernel and KernelSU integration patches strictly.
    apply_patch_strict(find_kernel_patch(), ROOT, strip=1)
    try_apply_ksu_integration_patch()

    verify_real_symbols()
    print('[DONE] full SUSFS implementation patch completed')


if __name__ == '__main__':
    main()
