#!/usr/bin/env python3
"""Patch apply_resukisu_susfs_full_impl.py to dry-run KSU integration patch first.

The original full script may try `patch -pN` directly. If a strip level applies
some hunks and then fails, the tree becomes dirty before the next strip level is
tried. This helper replaces try_apply_ksu_integration_patch() with a safer flow:

1. Test each candidate path/strip level with `patch --dry-run`.
2. Apply for real only if dry-run succeeds.
3. Stop immediately if real apply fails after a successful dry-run.
"""
from pathlib import Path
import py_compile
import re

TARGET = Path('.github/scripts/apply_resukisu_susfs_full_impl.py')

if not TARGET.exists():
    raise SystemExit(f'[ERROR] target not found: {TARGET}')

text = TARGET.read_text(errors='ignore')

new_func = """def try_apply_ksu_integration_patch() -> bool:\n    patch_file = SUSFS_DIR / \"kernel_patches\" / \"KernelSU\" / \"10_enable_susfs_for_ksu.patch\"\n    if not patch_file.exists():\n        raise FileNotFoundError(f\"KernelSU integration patch missing: {patch_file}\")\n\n    candidates = [ROOT / \"drivers\" / \"kernelsu\", ROOT / \"KernelSU\", ROOT]\n    attempts: list[str] = []\n\n    print(\"[INFO] dry-running KernelSU SUSFS integration patch before applying\")\n    for cwd in candidates:\n        if not cwd.exists():\n            continue\n        for strip in (2, 1, 0):\n            label = f\"{cwd} -p{strip}\"\n            attempts.append(label)\n            print(f\"[INFO] dry-run KernelSU SUSFS integration patch in {cwd} with -p{strip}\")\n            dry_rc = run(\n                f\"patch -p{strip} --dry-run --forward --batch < '{patch_file.resolve()}'\",\n                cwd=cwd,\n                check=False,\n            )\n            if dry_rc != 0:\n                print(f\"[SKIP] dry-run failed for {label}\")\n                continue\n\n            print(f\"[OK] dry-run passed for {label}; applying for real\")\n            apply_rc = run(\n                f\"patch -p{strip} --forward --batch < '{patch_file.resolve()}'\",\n                cwd=cwd,\n                check=False,\n            )\n            if apply_rc == 0:\n                print(f\"[OK] applied KernelSU SUSFS integration patch in {cwd} with -p{strip}\")\n                return True\n\n            raise RuntimeError(f\"dry-run passed but real patch failed for {label}; inspect tree/rejects\")\n\n    message = \"failed to dry-run KernelSU SUSFS integration patch cleanly. Tried: \" + \", \".join(attempts)\n    if ALLOW_KSU_PATCH_REJECTS:\n        print(\"[WARN] \" + message)\n        return False\n    raise RuntimeError(message + \"; pin compatible ReSukiSU/SUSFS commits or backport patch for this layout\")\n"""

patterns = [
    re.compile(r'def try_apply_ksu_integration_patch\(\) -> bool:\n.*?\n\ndef symbol_has_real_definition', re.S),
    re.compile(r'def try_apply_ksu_integration_patch\(\).*?\n\ndef symbol_has_real_definition', re.S),
]

for pattern in patterns:
    if pattern.search(text):
        text2 = pattern.sub(new_func + '\n\ndef symbol_has_real_definition', text, count=1)
        break
else:
    raise SystemExit('[ERROR] Could not locate try_apply_ksu_integration_patch() block')

TARGET.write_text(text2)
py_compile.compile(str(TARGET), doraise=True)
print('[OK] Patched apply_resukisu_susfs_full_impl.py: uses --dry-run before real KSU integration patch apply')
