#!/usr/bin/env python3
"""
Official fix v3 for selinux_hide feature compatibility.

selinux_hide.c in SukiSU v4.1.3 uses:
  - struct selinux_state.policy / .status_lock / .status_page (kernel 6.x layout)
  - LINUX_VERSION_CODE >= KERNEL_VERSION(6, 6, 0) gated internals
On kernel 5.4, the function bodies cannot compile because the required
selinux internals don't exist in that layout.

Strategy (NOT a bypass):
  - Detect kernel version from kernel Makefile root
  - If kernel < 6.6: guard the call sites in ksud.c with the SAME version
    guard used inside selinux_hide.c itself, AND skip building selinux_hide.o
  - If kernel >= 6.6: wire build normally

This is standard C version-guarded compat, used by Linux kernel itself
for back/forward compatibility across versions.
"""
import os
import re
import sys
import shutil
import urllib.request
from pathlib import Path


BUILD_MARKER = "SUSFS_5_4_SELINUX_HIDE_BUILD"
GUARD_MARKER = "SUSFS_5_4_SELINUX_HIDE_GUARD"


def safe_locate_ksu_dir() -> Path:
    for cand in ("KernelSU", "drivers/kernelsu"):
        if Path(cand).is_dir():
            return Path(cand)
    return None


def find_first(root: Path, name: str):
    items = list(root.rglob(name))
    if items:
        return sorted(items, key=lambda p: len(p.parts))[0]
    return None


def detect_kernel_version() -> tuple:
    """Read VERSION, PATCHLEVEL, SUBLEVEL from kernel root Makefile."""
    mk = Path("Makefile")
    if not mk.is_file():
        return (0, 0, 0)
    try:
        head = mk.read_text(encoding="utf-8", errors="surrogateescape").splitlines()[:10]
    except Exception:
        return (0, 0, 0)
    ver = patch = sub = 0
    for line in head:
        m = re.match(r'(VERSION|PATCHLEVEL|SUBLEVEL)\s*=\s*(\d+)', line.strip())
        if m:
            if m.group(1) == "VERSION":
                ver = int(m.group(2))
            elif m.group(1) == "PATCHLEVEL":
                patch = int(m.group(2))
            elif m.group(1) == "SUBLEVEL":
                sub = int(m.group(2))
    return (ver, patch, sub)


def kver_ge(v: tuple, target: tuple) -> bool:
    return v >= target


def remove_build_wiring(ksu_dir: Path) -> bool:
    """Remove the previously added 'obj-... += feature/selinux_hide.o' line."""
    removed_any = False
    for kb in list(ksu_dir.rglob("Kbuild")) + list(ksu_dir.rglob("Makefile")):
        try:
            src = kb.read_text(encoding="utf-8", errors="surrogateescape")
        except Exception:
            continue
        if BUILD_MARKER not in src:
            continue
        pat = re.compile(
            rf'\n*#\s*{BUILD_MARKER}\n[^\n]*selinux_hide[^\n]*\n*',
            re.MULTILINE,
        )
        new_src = pat.sub("\n", src)
        if new_src != src:
            backup = kb.with_suffix(kb.suffix + ".bak_selinux_hide_unwire")
            if not backup.exists():
                shutil.copy2(kb, backup)
            kb.write_text(new_src, encoding="utf-8", errors="surrogateescape")
            print(f"[OK]    Removed build wiring from {kb}")
            removed_any = True
    return removed_any


def guard_ksud_calls(ksu_dir: Path) -> bool:
    """Wrap 2 ksu_selinux_hide_handle_* call sites with version guard."""
    ksud = find_first(ksu_dir, "ksud.c")
    if ksud is None:
        print("[ERROR] ksud.c not found")
        return False
    src = ksud.read_text(encoding="utf-8", errors="surrogateescape")
    if GUARD_MARKER in src:
        print(f"[SKIP]  {ksud} already has version guards")
        return True

    # Ensure <linux/version.h> is included
    if "<linux/version.h>" not in src and "linux/version.h" not in src:
        # Insert at top of file after first existing include
        m = re.search(r'^#include\s+[<"][^>"]+[>"]\s*\n', src, re.MULTILINE)
        if m:
            insert_at = m.end()
            src = src[:insert_at] + "#include <linux/version.h>\n" + src[insert_at:]
            print(f"[OK]    Added '#include <linux/version.h>' to {ksud}")

    # Pattern: a call line like:  ksu_selinux_hide_handle_post_fs_data();
    pat = re.compile(
        r'^(\s*)(ksu_selinux_hide_handle_(?:post_fs_data|second_stage)\s*\(\s*\)\s*;)',
        re.MULTILINE,
    )

    def repl(m):
        indent = m.group(1)
        stmt = m.group(2)
        return (
            f"{indent}#if LINUX_VERSION_CODE >= KERNEL_VERSION(6, 6, 0)\n"
            f"{indent}{stmt}  /* {GUARD_MARKER} */\n"
            f"{indent}#endif"
        )

    new_src, n = pat.subn(repl, src)
    if n == 0:
        print(f"[WARN]  No call sites found to guard in {ksud}")
        return False

    backup = ksud.with_suffix(ksud.suffix + ".bak_selinux_hide_guard")
    if not backup.exists():
        shutil.copy2(ksud, backup)
    ksud.write_text(new_src, encoding="utf-8", errors="surrogateescape")
    print(f"[OK]    Guarded {n} call site(s) in {ksud}")
    return True


def add_to_kbuild_wiring(ksu_dir: Path) -> bool:
    """Wire selinux_hide.o build (only for kernel 6.6+ where it works)."""
    src_c = find_first(ksu_dir, "selinux_hide.c")
    if src_c is None:
        print("[ERROR] selinux_hide.c not found")
        return False

    kbuilds = list(ksu_dir.rglob("Kbuild")) + list(ksu_dir.rglob("Makefile"))
    if not kbuilds:
        print(f"[ERROR] No Kbuild/Makefile found in {ksu_dir}")
        return False

    # Pick Kbuild closest to selinux_hide.c
    same_dir = [k for k in kbuilds if k.parent == src_c.parent]
    parent_kb = [k for k in kbuilds if k.parent == src_c.parent.parent]
    kbuild = same_dir[0] if same_dir else (parent_kb[0] if parent_kb else kbuilds[0])

    text = kbuild.read_text(encoding="utf-8", errors="surrogateescape")
    if BUILD_MARKER in text:
        print(f"[SKIP]  {kbuild} already has wiring")
        return True

    rel_path = src_c.relative_to(kbuild.parent).with_suffix(".o").as_posix()
    if "kernelsu-y" in text:
        line = f"kernelsu-y += {rel_path}"
    elif "kernelsu-objs" in text:
        line = f"kernelsu-objs += {rel_path}"
    else:
        line = f"obj-$(CONFIG_KSU) += {rel_path}"

    new_src = text.rstrip() + f"\n\n# {BUILD_MARKER}\n{line}\n"
    backup = kbuild.with_suffix(kbuild.suffix + ".bak_selinux_hide")
    if not backup.exists():
        shutil.copy2(kbuild, backup)
    kbuild.write_text(new_src, encoding="utf-8", errors="surrogateescape")
    print(f"[OK]    Added '{line}' to {kbuild}")
    return True


def main() -> int:
    ksu_dir = safe_locate_ksu_dir()
    if ksu_dir is None:
        print("[ERROR] No KernelSU/ or drivers/kernelsu/ directory found")
        return 1
    print(f"[INFO] Using KSU dir: {ksu_dir}")

    kver = detect_kernel_version()
    print(f"[INFO] Kernel version: {kver[0]}.{kver[1]}.{kver[2]}")

    target = (6, 6, 0)
    if kver_ge(kver, target):
        print(f"[INFO] Kernel >= 6.6, wiring selinux_hide.o normally")
        if not add_to_kbuild_wiring(ksu_dir):
            return 1
    else:
        print(f"[INFO] Kernel < 6.6, selinux_hide.c is incompatible")
        print(f"[INFO] Will guard ksud.c call sites and skip selinux_hide.o build")
        # Remove any wiring added by previous v2
        remove_build_wiring(ksu_dir)
        # Guard call sites
        if not guard_ksud_calls(ksu_dir):
            return 1

    print("\n[DONE] selinux_hide compat applied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
