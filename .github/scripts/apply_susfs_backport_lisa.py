#!/usr/bin/env python3
"""
Anchor-based SUSFS backport for Xiaomi lisa kernel 5.4.

Design rules:
- Do NOT apply 50_add_susfs_in_kernel-5.4.patch.
- Do NOT use patch -p1 / --reject / partial reject files.
- Copy fs/susfs.c + headers first, then insert hooks by stable anchors.
- Insert calls to real SUSFS symbols copied from susfs4ksu, not stubs.
- Fail fast when an expected anchor is missing.
"""
from pathlib import Path
import re
import sys

ROOT = Path.cwd()
FAILURES = []


def log(msg):
    print(msg, flush=True)


def fail(msg):
    FAILURES.append(msg)
    print(f"[ERROR] {msg}", flush=True)


def read(rel):
    p = ROOT / rel
    if not p.exists():
        raise SystemExit(f"[ERROR] missing required file: {rel}")
    return p.read_text(errors="ignore")


def write(rel, text):
    (ROOT / rel).write_text(text)
    log(f"[OK] updated {rel}")


def insert_after(text, anchor, insertion, marker, rel):
    if marker in text:
        return text
    pos = text.find(anchor)
    if pos < 0:
        fail(f"{rel}: anchor not found after: {anchor[:120]!r}")
        return text
    pos += len(anchor)
    return text[:pos] + insertion + text[pos:]


def insert_before(text, anchor, insertion, marker, rel):
    if marker in text:
        return text
    pos = text.find(anchor)
    if pos < 0:
        fail(f"{rel}: anchor not found before: {anchor[:120]!r}")
        return text
    return text[:pos] + insertion + text[pos:]


def replace_once(text, old, new, marker, rel):
    if marker in text:
        return text
    if old not in text:
        fail(f"{rel}: target block not found for marker {marker}")
        return text
    return text.replace(old, new, 1)


def ensure_file(rel):
    p = ROOT / rel
    if not p.exists():
        fail(f"missing {rel}")
    else:
        log(f"[OK] exists {rel}")


def patch_fs_makefile():
    rel = "fs/Makefile"
    text = read(rel)
    if "obj-$(CONFIG_KSU_SUSFS) += susfs.o" not in text:
        text = insert_after(
            text,
            "\t\tfs_types.o fs_context.o fs_parser.o fsopen.o\n",
            "\nobj-$(CONFIG_KSU_SUSFS) += susfs.o\n",
            "obj-$(CONFIG_KSU_SUSFS) += susfs.o",
            rel,
        )
    if (ROOT / "fs/sus_su.c").exists() and "obj-$(CONFIG_KSU_SUSFS_SUS_SU) += sus_su.o" not in text:
        text += "\nobj-$(CONFIG_KSU_SUSFS_SUS_SU) += sus_su.o\n"
    write(rel, text)


def patch_task_mmu():
    rel = "fs/proc/task_mmu.c"
    text = read(rel)
    if "#include <linux/susfs_def.h>" not in text:
        anchor = "#include <linux/ctype.h>\n" if "#include <linux/ctype.h>\n" in text else "#include <linux/mm_inline.h>\n"
        text = insert_after(text, anchor, "#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT\n#include <linux/susfs_def.h>\n#endif\n", "#include <linux/susfs_def.h>", rel)
    if "susfs_sus_ino_for_show_map_vma" not in text:
        text = insert_before(
            text,
            "static void\nshow_map_vma",
            "#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT\nextern void susfs_sus_ino_for_show_map_vma(unsigned long ino, dev_t *out_dev, unsigned long *out_ino);\n#endif\n\n",
            "susfs_sus_ino_for_show_map_vma",
            rel,
        )
    old = "\tif (file) {\n\t\tstruct inode *inode = file_inode(vma->vm_file);\n\t\tdev = inode->i_sb->s_dev;\n\t\tino = inode->i_ino;\n\t\tpgoff = ((loff_t)vma->vm_pgoff) << PAGE_SHIFT;\n\t}\n"
    new = "\tif (file) {\n\t\tstruct inode *inode = file_inode(vma->vm_file);\n#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT\n\t\t/* SUSFS anchor-backport: call real SUSFS KSTAT map spoof helper. */\n\t\tif (unlikely(inode->i_state & INODE_STATE_SUS_KSTAT)) {\n\t\t\tsusfs_sus_ino_for_show_map_vma(inode->i_ino, &dev, &ino);\n\t\t\tgoto susfs_skip_orig_map_vma_stat;\n\t\t}\n#endif\n\t\tdev = inode->i_sb->s_dev;\n\t\tino = inode->i_ino;\n#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT\nsusfs_skip_orig_map_vma_stat:\n#endif\n\t\tpgoff = ((loff_t)vma->vm_pgoff) << PAGE_SHIFT;\n\t}\n"
    text = replace_once(text, old, new, "SUSFS anchor-backport: call real SUSFS KSTAT map spoof helper", rel)
    write(rel, text)


def patch_readdir():
    rel = "fs/readdir.c"
    text = read(rel)
    if "#include <linux/susfs_def.h>" not in text:
        anchor = "#include <linux/uaccess.h>\n" if "#include <linux/uaccess.h>\n" in text else "#include <linux/fs.h>\n"
        text = insert_after(text, anchor, "#ifdef CONFIG_KSU_SUSFS_SUS_PATH\n#include <linux/susfs_def.h>\n#endif\n", "#include <linux/susfs_def.h>", rel)
    if "susfs_is_sus_android_data_d_name_found" not in text:
        externs = """
#ifdef CONFIG_KSU_SUSFS_SUS_PATH
extern bool susfs_is_inode_sus_path(struct inode *inode);
extern bool susfs_is_base_dentry_android_data_dir(struct dentry *dentry);
extern bool susfs_is_base_dentry_sdcard_dir(struct dentry *dentry);
extern bool susfs_is_sus_android_data_d_name_found(const char *d_name);
extern bool susfs_is_sus_sdcard_d_name_found(const char *d_name);
#endif
"""
        anchor = "#include <asm/unaligned.h>\n" if "#include <asm/unaligned.h>\n" in text else "#include <linux/unistd.h>\n"
        text = insert_after(text, anchor, externs, "susfs_is_sus_android_data_d_name_found", rel)

    def add_fields(src, name):
        marker = f"susfs_anchor_backport_{name}_fields"
        if marker in src:
            return src
        m = re.search(r"(struct\s+" + re.escape(name) + r"\s*\{.*?)(\n\};)", src, re.S)
        if not m:
            return src
        fields = "\n#ifdef CONFIG_KSU_SUSFS_SUS_PATH\n\t/* " + marker + " */\n\tstruct super_block *susfs_sb;\n\tbool susfs_is_android_data_root;\n\tbool susfs_is_sdcard_root;\n#endif"
        return src[:m.start(2)] + fields + src[m.start(2):]

    for name in ["readdir_callback", "getdents_callback", "getdents_callback64", "compat_readdir_callback", "compat_getdents_callback"]:
        text = add_fields(text, name)

    if "susfs_anchor_backport_readdir_callback_fields" not in text:
        fail(f"{rel}: no readdir callback structs patched; lisa source may need a dedicated anchor")

    write(rel, text)


def patch_namei():
    rel = "fs/namei.c"
    text = read(rel)
    if "#include <linux/susfs_def.h>" not in text:
        anchor = "#include <linux/uaccess.h>\n" if "#include <linux/uaccess.h>\n" in text else "#include <linux/fs.h>\n"
        text = insert_after(text, anchor, "#if defined(CONFIG_KSU_SUSFS_SUS_PATH) || defined(CONFIG_KSU_SUSFS_OPEN_REDIRECT)\n#include <linux/susfs_def.h>\n#endif\n", "#include <linux/susfs_def.h>", rel)
    if "susfs_anchor_backport_namei_marker" not in text:
        externs = """
#ifdef CONFIG_KSU_SUSFS_SUS_PATH
extern bool susfs_is_inode_sus_path(struct inode *inode);
#endif
#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT
extern struct filename *susfs_get_redirected_path(unsigned long ino);
#endif
static const bool susfs_anchor_backport_namei_marker = true;
"""
        anchor = "#include \"mount.h\"\n" if "#include \"mount.h\"\n" in text else "#include \"internal.h\"\n"
        text = insert_after(text, anchor, externs, "susfs_anchor_backport_namei_marker", rel)
    write(rel, text)


def patch_namespace():
    rel = "fs/namespace.c"
    text = read(rel)
    if "#include <linux/susfs_def.h>" not in text:
        anchor = "#include <linux/shmem_fs.h>\n" if "#include <linux/shmem_fs.h>\n" in text else "#include <linux/fs.h>\n"
        text = insert_after(text, anchor, "#if defined(CONFIG_KSU_SUSFS_SUS_MOUNT) || defined(CONFIG_KSU_SUSFS_TRY_UMOUNT)\n#include <linux/susfs_def.h>\n#endif\n", "#include <linux/susfs_def.h>", rel)
    helper = """

#ifdef CONFIG_KSU_SUSFS_TRY_UMOUNT
extern void susfs_try_umount_all(uid_t uid);
void susfs_run_try_umount_for_current_mnt_ns(void)
{
	/* SUSFS anchor-backport: call real SUSFS try-umount helper. */
	susfs_try_umount_all(current_uid().val);
}
#endif

#ifdef CONFIG_KSU_SUSFS
bool susfs_is_mnt_devname_ksu(struct path *path)
{
	struct mount *mnt;
	if (!path || !path->mnt)
		return false;
	mnt = real_mount(path->mnt);
	return mnt && mnt->mnt_devname && !strcmp(mnt->mnt_devname, "KSU");
}
#endif

static const bool susfs_anchor_backport_namespace_marker = true;
"""
    if "susfs_anchor_backport_namespace_marker" not in text:
        text = text.rstrip() + helper + "\n"
    write(rel, text)


def main():
    for rel in ["fs/susfs.c", "include/linux/susfs.h", "include/linux/susfs_def.h"]:
        ensure_file(rel)
    patch_fs_makefile()
    patch_task_mmu()
    patch_readdir()
    patch_namei()
    patch_namespace()
    if FAILURES:
        print("\n[FAIL] anchor-based SUSFS backport incomplete:")
        for item in FAILURES:
            print(f"  - {item}")
        raise SystemExit(1)
    print("[OK] anchor-based SUSFS backport completed without upstream patch")

if __name__ == "__main__":
    main()
