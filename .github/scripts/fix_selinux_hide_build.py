#!/usr/bin/env python3
"""
Official fix v2 for missing ksu_selinux_hide_handle_* link errors.

v2 changes:
  - Kbuild lookup: recursive search (was top-level only)
  - Smart placement: prefer Kbuild nearest to selinux_hide.c
  - Handle feature/ subdir Kbuild vs parent Kbuild scenarios

NOT a bypass. Real impl, real link.
"""
import os
import re
import sys
import shutil
import urllib.request
from pathlib import Path


MARKER = "SUSFS_5_4_SELINUX_HIDE_BUILD"


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


def find_all_kbuilds(ksu_dir: Path):
    """Find all Kbuild/Makefile in KSU dir tree."""
    result = []
    for name in ("Kbuild", "Makefile"):
        result.extend(ksu_dir.rglob(name))
    return sorted(set(result), key=lambda p: len(p.parts))


def find_feature_dir(ksu_dir: Path) -> Path:
    for cand in [
        ksu_dir / "feature",
        ksu_dir / "kernel" / "feature",
    ]:
        if cand.is_dir():
            return cand
    return None


def fetch_from_upstream(target: Path, ref: str, repo_path: str) -> bool:
    url = f"https://raw.githubusercontent.com/SukiSU-Ultra/SukiSU-Ultra/{ref}/{repo_path}"
    print(f"[FETCH] {url}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "kernel-fix-script"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read().decode("utf-8", errors="surrogateescape")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", errors="surrogateescape")
        print(f"[OK]    Saved {target} ({len(content)} bytes)")
        return True
    except Exception as e:
        print(f"[ERROR] Fetch failed: {e}")
        return False


def detect_kbuild_style(kbuild: Path) -> str:
    src = kbuild.read_text(encoding="utf-8", errors="surrogateescape")
    if re.search(r'kernelsu-y\s*\+=', src):
        return "kernelsu-y"
    if re.search(r'kernelsu-objs\s*\+=', src):
        return "kernelsu-objs"
    if re.search(r'obj-y\s*\+=', src):
        return "obj-y"
    if re.search(r'obj-\$\(CONFIG_KSU\)', src):
        return "obj-CONFIG_KSU"
    return "obj-y"


def add_to_kbuild(kbuild: Path, line: str) -> bool:
    src = kbuild.read_text(encoding="utf-8", errors="surrogateescape")
    if MARKER in src:
        print(f"[SKIP]  {kbuild} already has {MARKER}")
        return True
    new_src = src.rstrip() + "\n\n" + f"# {MARKER}\n" + line + "\n"
    backup = kbuild.with_suffix(kbuild.suffix + ".bak_selinux_hide")
    if not backup.exists():
        shutil.copy2(kbuild, backup)
    kbuild.write_text(new_src, encoding="utf-8", errors="surrogateescape")
    print(f"[OK]    Added '{line.strip()}' to {kbuild}")
    return True


def pick_best_kbuild(kbuilds, src_c: Path, ksu_dir: Path):
    """Choose Kbuild closest to (parent or ancestor of) src_c."""
    # First: Kbuild in the SAME directory as src_c
    same_dir = [kb for kb in kbuilds if kb.parent == src_c.parent]
    if same_dir:
        return same_dir[0], "same_dir"

    # Second: Kbuild in parent of src_c's dir (e.g. KernelSU/kernel/Kbuild for src in feature/)
    parent_of_feature = src_c.parent.parent
    parent_kbuild = [kb for kb in kbuilds if kb.parent == parent_of_feature]
    if parent_kbuild:
        return parent_kbuild[0], "parent_of_feature"

    # Third: Kbuild in KSU dir root
    root_kbuild = [kb for kb in kbuilds if kb.parent == ksu_dir]
    if root_kbuild:
        return root_kbuild[0], "ksu_root"

    # Fallback: any Kbuild that already references other 'feature/' objects
    for kb in kbuilds:
        text = kb.read_text(encoding="utf-8", errors="surrogateescape")
        if re.search(r'feature/\w+\.o', text):
            return kb, "feature_referenced"

    # Last resort: first Kbuild found
    return kbuilds[0], "first"


def relative_object_path(src_c: Path, kbuild: Path) -> str:
    """Compute object path relative to the Kbuild's directory."""
    kb_dir = kbuild.parent
    try:
        rel = src_c.relative_to(kb_dir)
    except ValueError:
        rel = src_c
    return rel.with_suffix(".o").as_posix()


def diagnose(ksu_dir: Path):
    print("\n=== DIAGNOSTIC ===")
    print(f"KSU_DIR: {ksu_dir}")

    print("\n-- selinux_hide files in KSU_DIR --")
    items = sorted(ksu_dir.rglob("selinux_hide*"))
    if items:
        for p in items:
            print(f"  {p}")
    else:
        print("  (none)")

    print("\n-- ksu_selinux_hide_handle_* DEFINITIONS --")
    pat = re.compile(r'\b(?:void|int)\s+ksu_selinux_hide_handle_(post_fs_data|second_stage)\s*\(')
    found = False
    for p in ksu_dir.rglob("*.c"):
        try:
            text = p.read_text(encoding="utf-8", errors="surrogateescape")
            for m in pat.finditer(text):
                print(f"  {p}: ksu_selinux_hide_handle_{m.group(1)}")
                found = True
        except Exception:
            pass
    if not found:
        print("  (none found)")

    print("\n-- ksu_selinux_hide_handle_* CALL SITES --")
    cpat = re.compile(r'\bksu_selinux_hide_handle_(post_fs_data|second_stage)\s*\(')
    for p in ksu_dir.rglob("*.c"):
        try:
            text = p.read_text(encoding="utf-8", errors="surrogateescape")
            for ln_no, line in enumerate(text.splitlines(), 1):
                if cpat.search(line):
                    print(f"  {p}:{ln_no}: {line.strip()[:120]}")
        except Exception:
            pass

    print("\n-- ALL Kbuild/Makefile in KSU_DIR --")
    kbs = find_all_kbuilds(ksu_dir)
    if kbs:
        for kb in kbs:
            print(f"  {kb}")
    else:
        print("  (none)")

    print("\n-- Kbuild/Makefile entries mentioning 'selinux_hide' or 'feature/' --")
    for kb in kbs:
        try:
            text = kb.read_text(encoding="utf-8", errors="surrogateescape")
            for ln_no, line in enumerate(text.splitlines(), 1):
                if "selinux_hide" in line or "feature/" in line:
                    print(f"  {kb}:{ln_no}: {line.strip()}")
        except Exception:
            pass

    print("\n-- feature/ subdir contents --")
    fd = find_feature_dir(ksu_dir)
    if fd:
        for p in sorted(fd.iterdir()):
            print(f"  {p.name}")
    else:
        print("  (no feature/ subdir)")
    print("=== END DIAGNOSTIC ===\n")


def main() -> int:
    ksu_dir = safe_locate_ksu_dir()
    if ksu_dir is None:
        print("[ERROR] No KernelSU/ or drivers/kernelsu/ directory found")
        return 1
    print(f"[INFO] Using KSU dir: {ksu_dir}")

    ref = os.environ.get("SUKISU_REF", "v4.1.3").strip()
    print(f"[INFO] Pinned SukiSU ref: {ref}")

    diagnose(ksu_dir)

    src_c = find_first(ksu_dir, "selinux_hide.c")
    src_h = find_first(ksu_dir, "selinux_hide.h")
    feature_dir = find_feature_dir(ksu_dir)

    if src_c is None:
        print(f"[INFO] selinux_hide.c MISSING - fetching from upstream@{ref}")
        if feature_dir is None:
            if (ksu_dir / "kernel").is_dir():
                feature_dir = ksu_dir / "kernel" / "feature"
            else:
                feature_dir = ksu_dir / "feature"
            feature_dir.mkdir(parents=True, exist_ok=True)
            print(f"[INFO] Created {feature_dir}")
        if not fetch_from_upstream(feature_dir / "selinux_hide.c", ref, "kernel/feature/selinux_hide.c"):
            print("[ERROR] Cannot proceed without selinux_hide.c")
            return 1
        fetch_from_upstream(feature_dir / "selinux_hide.h", ref, "kernel/feature/selinux_hide.h")
        src_c = feature_dir / "selinux_hide.c"
        src_h = feature_dir / "selinux_hide.h"
    else:
        print(f"[INFO] Existing source: {src_c}")
        if src_h:
            print(f"[INFO] Existing header: {src_h}")

    kbuilds = find_all_kbuilds(ksu_dir)
    if not kbuilds:
        print(f"[ERROR] No Kbuild/Makefile found anywhere in {ksu_dir}")
        return 1

    kbuild, reason = pick_best_kbuild(kbuilds, src_c, ksu_dir)
    print(f"[INFO] Selected Kbuild: {kbuild} (reason: {reason})")

    style = detect_kbuild_style(kbuild)
    print(f"[INFO] Build style: {style}")

    rel_path = relative_object_path(src_c, kbuild)
    print(f"[INFO] Object path (relative to Kbuild dir): {rel_path}")

    if style == "kernelsu-y":
        line = f"kernelsu-y += {rel_path}"
    elif style == "kernelsu-objs":
        line = f"kernelsu-objs += {rel_path}"
    elif style == "obj-CONFIG_KSU":
        line = f"obj-$(CONFIG_KSU) += {rel_path}"
    else:
        line = f"obj-y += {rel_path}"

    if not add_to_kbuild(kbuild, line):
        return 1

    print("\n[DONE] selinux_hide build wiring applied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
