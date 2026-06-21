#!/usr/bin/env python3
"""Additional anchor-based ReSukiSU non-GKI hooks not covered by the user's existing manual hook script."""
from pathlib import Path
import sys
ROOT = Path.cwd()
FAIL = []

def fail(msg):
    print(f"[ERROR] {msg}")
    FAIL.append(msg)

def read(rel):
    p = ROOT / rel
    if not p.exists():
        raise SystemExit(f"[ERROR] missing {rel}")
    return p.read_text(errors="ignore")

def write(rel, text):
    (ROOT / rel).write_text(text)
    print(f"[OK] updated {rel}")

def patch_setresuid():
    rel = "kernel/sys.c"
    text = read(rel)
    proto = "#ifdef CONFIG_KSU_MANUAL_HOOK\n__attribute__((hot))\nextern int ksu_handle_setresuid(uid_t ruid, uid_t euid, uid_t suid);\n#endif\n\n"
    call = "#ifdef CONFIG_KSU_MANUAL_HOOK\n\tksu_handle_setresuid(ruid, euid, suid);\n#endif\n"
    if "ksu_handle_setresuid" not in text:
        marker = "SYSCALL_DEFINE3(setresuid"
        pos = text.find(marker)
        if pos < 0:
            fail(f"{rel}: setresuid syscall not found")
            return
        text = text[:pos] + proto + text[pos:]
        pos = text.find(marker)
        body = text.find("{", pos)
        insert_at = -1
        for anchor in ["\tkruid = make_kuid(ns, ruid);", "\tkeuid = make_kuid(ns, euid);", "\told = current_cred();"]:
            insert_at = text.find(anchor, body)
            if insert_at >= 0:
                break
        if insert_at < 0:
            fail(f"{rel}: setresuid insertion anchor not found")
            return
        text = text[:insert_at] + call + text[insert_at:]
    write(rel, text)

def patch_sys_read():
    rel = "fs/read_write.c"
    text = read(rel)
    proto = "#ifdef CONFIG_KSU_MANUAL_HOOK\n__attribute__((hot))\nextern int ksu_handle_sys_read(unsigned int fd, char __user **buf_ptr, size_t *count_ptr);\n#endif\n\n"
    call = "#ifdef CONFIG_KSU_MANUAL_HOOK\n\tksu_handle_sys_read(fd, &buf, &count);\n#endif\n"
    if "ksu_handle_sys_read" not in text:
        marker = "SYSCALL_DEFINE3(read"
        pos = text.find(marker)
        if pos < 0:
            fail(f"{rel}: read syscall not found")
            return
        text = text[:pos] + proto + text[pos:]
        pos = text.find(marker)
        body = text.find("{", pos)
        insert_at = -1
        for anchor in ["\tstruct fd f = fdget_pos(fd);", "\tstruct fd f = fdget(fd);", "\tssize_t ret = -EBADF;"]:
            insert_at = text.find(anchor, body)
            if insert_at >= 0:
                break
        if insert_at < 0:
            fail(f"{rel}: sys_read insertion anchor not found")
            return
        text = text[:insert_at] + call + text[insert_at:]
    write(rel, text)

def patch_input_event():
    rel = "drivers/input/input.c"
    text = read(rel)
    proto = "#ifdef CONFIG_KSU_MANUAL_HOOK\nextern bool ksu_input_hook __read_mostly;\nextern int ksu_handle_input_handle_event(unsigned int *type, unsigned int *code, int *value);\n#endif\n\n"
    call = "#ifdef CONFIG_KSU_MANUAL_HOOK\n\tif (unlikely(ksu_input_hook))\n\t\tksu_handle_input_handle_event(&type, &code, &value);\n#endif\n"
    if "ksu_handle_input_handle_event" not in text:
        marker = "void input_handle_event("
        pos = text.find(marker)
        if pos < 0:
            fail(f"{rel}: input_handle_event not found")
            return
        text = text[:pos] + proto + text[pos:]
        pos = text.find(marker)
        body = text.find("{", pos)
        insert_at = -1
        for anchor in ["\tdisposition = input_get_disposition(dev, type, code, &value);", "\tlockdep_assert_held(&dev->event_lock);", "\tint disposition;"]:
            insert_at = text.find(anchor, body)
            if insert_at >= 0:
                if anchor == "\tint disposition;":
                    nl = text.find("\n", insert_at)
                    insert_at = nl + 1
                break
        if insert_at < 0:
            fail(f"{rel}: input_handle_event insertion anchor not found")
            return
        text = text[:insert_at] + call + text[insert_at:]
    write(rel, text)

def main():
    patch_setresuid()
    patch_sys_read()
    patch_input_event()
    if FAIL:
        print("\n[FAIL] missing ReSukiSU hook backport incomplete")
        raise SystemExit(1)
    print("[OK] missing ReSukiSU hooks backported by anchors")

if __name__ == "__main__":
    main()
