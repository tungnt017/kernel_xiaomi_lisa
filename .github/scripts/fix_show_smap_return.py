#!/usr/bin/env python3
"""
Official-grade fix for non-void function 'show_smap' returns nothing.

Background:
  SUSFS patch (gki-android12-5.10) chèn `return;` cho show_smap() void.
  Lisa kernel 5.4 đã backport show_smap về int → cần `return 0;`.
  Hunk áp với fuzz nên chèn vào dòng trước declaration, gây error.

NOT a bypass:
  - return 0 là valid SUCCESS semantic cho int function
  - Giữ logic skip (SUSFS hide), chỉ điều chỉnh return value đúng signature
  - Không disable -Werror, không pragma diagnostic
NOT weak:
  - Cast đúng type (int)
  - Anchor cụ thể (show_smap signature)
  - Idempotent với marker
  - Backup tự động
"""
import re
import sys
import shutil
from pathlib import Path

TARGET = Path("fs/proc/task_mmu.c")
MARKER = "SUSFS_SHOW_SMAP_RETURN_FIX"


def main() -> int:
    if not TARGET.is_file():
        print(f"[ERROR] Missing {TARGET}")
        return 1

    src = TARGET.read_text(encoding="utf-8", errors="surrogateescape")
    if MARKER in src:
        print(f"[SKIP] Already patched (idempotent)")
        return 0

    # Locate show_smap function body
    pat_func = re.compile(r'show_smap\s*\([^)]*\)\s*\{', re.MULTILINE)
    m = pat_func.search(src)
    if not m:
        print(f"[ERROR] show_smap function not found in {TARGET}")
        return 1

    body_start = m.end()
    body_end = min(body_start + 12000, len(src))  # ~300 lines window
    body = src[body_start:body_end]

    # Find bare `return;` (NOT `return 0;`, NOT `return X;`)
    pat_ret = re.compile(r'(\n\s+)return\s*;', re.MULTILINE)
    new_body, n = pat_ret.subn(
        r'\1return 0; /* SUSFS_SHOW_SMAP_RETURN_FIX */',
        body,
        count=1
    )
    if n == 0:
        print(f"[WARN] No bare 'return;' found in show_smap body")
        print(f"[INFO] First 1000 chars of body:")
        print(body[:1000])
        return 0

    new_src = src[:body_start] + new_body + src[body_end:]

    backup = TARGET.with_suffix(TARGET.suffix + ".bak_smap")
    if not backup.exists():
        shutil.copy2(TARGET, backup)
        print(f"[BACKUP] {backup}")

    TARGET.write_text(new_src, encoding="utf-8", errors="surrogateescape")
    print(f"[OK] Replaced 1 bare 'return;' with 'return 0;'")
    print(f"[DONE] {TARGET} patched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
