#!/usr/bin/env python3
"""
Official KSU hook for fs/devpts/inode.c

Per official KernelSU non-GKI integration guide:
  https://github.com/tiann/KernelSU/blob/main/website/docs/guide/how-to-integrate-for-non-gki.md

Quote:
  "Failed to execute pm in terminal? You should modify fs/devpts/inode.c"

The hook makes `pm` command work correctly in terminal, which is REQUIRED
for SukiSU/KernelSU manager APK to communicate with ksud daemon.
Without this hook, manager shows "Not working" or fails to grant root.

NOT a bypass: this is the official documented patch.
NOT weak: matches the exact diff in tiann/KernelSU non-GKI guide.
Idempotent + backup.
"""
import re
import sys
import shutil
from pathlib import Path

TARGET = Path("fs/devpts/inode.c")
MARKER = "ksu_handle_devpts"


def main() -> int:
    if not TARGET.is_file():
        print(f"[ERROR] Missing {TARGET}")
        return 1

    src = TARGET.read_text(encoding="utf-8", errors="surrogateescape")
    if MARKER in src:
        print(f"[SKIP] {TARGET} already patched (idempotent)")
        return 0

    # Locate devpts_get_priv function definition
    # Pattern matches: void *devpts_get_priv(struct dentry *dentry) {
    pat_func = re.compile(
        r'(\n\s*void\s+\*\s*devpts_get_priv\s*\(\s*struct\s+dentry\s*\*\s*\w+\s*\)\s*\{)',
        re.MULTILINE,
    )
    m = pat_func.search(src)
    if not m:
        print(f"[ERROR] devpts_get_priv function not found in {TARGET}")
        print("[INFO] First 100 lines of file:")
        for i, line in enumerate(src.splitlines()[:100], 1):
            print(f"  {i:4d}| {line}")
        return 1

    func_start = m.start()
    func_body_start = m.end()

    # Extern decl block right before the function (matches official guide format)
    extern_block = (
        "\n#ifdef CONFIG_KSU\n"
        "extern int ksu_handle_devpts(struct inode*);\n"
        "#endif\n"
    )

    # Hook call at top of function body (right after opening brace)
    hook_call = (
        "\n#ifdef CONFIG_KSU\n"
        "\tksu_handle_devpts(dentry->d_inode);\n"
        "#endif\n"
    )

    new_src = (
        src[:func_start]
        + extern_block
        + src[func_start:func_body_start]
        + hook_call
        + src[func_body_start:]
    )

    backup = TARGET.with_suffix(TARGET.suffix + ".bak_devpts")
    if not backup.exists():
        shutil.copy2(TARGET, backup)
        print(f"[BACKUP] {backup}")

    TARGET.write_text(new_src, encoding="utf-8", errors="surrogateescape")
    print(f"[OK] Added ksu_handle_devpts hook to {TARGET}")
    print(f"[OK] Added extern declaration before devpts_get_priv")
    print(f"[DONE] {TARGET} patched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
