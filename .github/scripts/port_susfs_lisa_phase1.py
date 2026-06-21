#!/usr/bin/env python3
"""
Official Phase 1 SUSFS port for ReSukiSU + ShirkNeko SUSFS on lisa 5.4.

Targets only small/contained kernel-side SUSFS integration points:
  - fs/Makefile
  - fs/proc/task_mmu.c
  - fs/notify/fdinfo.c

Rules:
  - No bypass
  - No no-op/stub
  - No --reject / patch -p1
  - Idempotent: safe to run more than once
  - Fails loudly if expected anchors are missing
"""
from pathlib import Path
import sys

ROOT = Path.cwd()

class PortError(RuntimeError):
    pass

def read(rel):
    p = ROOT / rel
    if not p.exists():
        raise PortError(f"missing required file: {rel}")
    return p.read_text(errors="ignore")

def write(rel, text):
    p = ROOT / rel
    p.write_text(text)
    print(f"[OK] updated {rel}")

def require(condition, msg):
    if not condition:
        raise PortError(msg)

def insert_after_once(text, anchor, insertion, marker):
    if marker in text:
        return text, False
    idx = text.find(anchor)
    require(idx != -1, f"anchor not found: {anchor[:120]!r}")
    idx += len(anchor)
    return text[:idx] + insertion + text[idx:], True

def insert_before_once(text, anchor, insertion, marker):
    if marker in text:
        return text, False
    idx = text.find(anchor)
    require(idx != -1, f"anchor not found: {anchor[:120]!r}")
    return text[:idx] + insertion + text[idx:], True

def replace_once(text, old, new, marker):
    if marker in text:
        return text, False
    require(old in text, f"target block not found for marker {marker}")
    return text.replace(old, new, 1), True

# ---------------------------------------------------------------------------
# fs/Makefile
# ---------------------------------------------------------------------------
def patch_fs_makefile():
    rel = "fs/Makefile"
    text = read(rel)
    marker = "obj-$(CONFIG_KSU_SUSFS) += susfs.o"
    if marker in text:
        print(f"[SKIP] {rel}: SUSFS object already present")
        return
    anchor = "\t\tfs_types.o fs_context.o fs_parser.o fsopen.o\n"
    insertion = "\nobj-$(CONFIG_KSU_SUSFS) += susfs.o\n"
    text, changed = insert_after_once(text, anchor, insertion, marker)
    if changed:
        write(rel, text)

# ---------------------------------------------------------------------------
# fs/proc/task_mmu.c
# ---------------------------------------------------------------------------
def patch_task_mmu():
    rel = "fs/proc/task_mmu.c"
    text = read(rel)

    # Add include for INODE_STATE_SUS_KSTAT and SUSFS definitions.
    include_marker = "#include <linux/susfs_def.h>"
    if include_marker not in text:
        # Prefer the ShirkNeko patch anchor. Lisa source has linux/ctype.h before asm includes.
        anchor_candidates = [
            "#include <linux/ctype.h>\n",
            "#include <linux/mm_inline.h>\n",
        ]
        for anchor in anchor_candidates:
            if anchor in text:
                insertion = "#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT\n#include <linux/susfs_def.h>\n#endif\n"
                text, _ = insert_after_once(text, anchor, insertion, include_marker)
                break
        else:
            raise PortError(f"{rel}: no include anchor found")

    # Add extern prototype before show_map_vma().
    proto_marker = "susfs_sus_ino_for_show_map_vma"
    proto = (
        "#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT\n"
        "extern void susfs_sus_ino_for_show_map_vma(unsigned long ino, dev_t *out_dev, unsigned long *out_ino);\n"
        "#endif\n\n"
    )
    if proto_marker not in text:
        text, _ = insert_before_once(text, "static void\nshow_map_vma", proto, proto_marker)

    # Add actual kstat spoof logic inside show_map_vma() file block.
    logic_marker = "SUSFS: spoof map VMA inode/dev for SUS_KSTAT"
    if logic_marker not in text:
        old = (
            "\tif (file) {\n"
            "\t\tstruct inode *inode = file_inode(vma->vm_file);\n"
            "\t\tdev = inode->i_sb->s_dev;\n"
            "\t\tino = inode->i_ino;\n"
            "\t\tpgoff = ((loff_t)vma->vm_pgoff) << PAGE_SHIFT;\n"
            "\t}\n"
        )
        new = (
            "\tif (file) {\n"
            "\t\tstruct inode *inode = file_inode(vma->vm_file);\n"
            "#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT\n"
            "\t\t/* SUSFS: spoof map VMA inode/dev for SUS_KSTAT */\n"
            "\t\tif (unlikely(inode->i_state & INODE_STATE_SUS_KSTAT)) {\n"
            "\t\t\tsusfs_sus_ino_for_show_map_vma(inode->i_ino, &dev, &ino);\n"
            "\t\t\tgoto susfs_skip_orig_map_vma_stat;\n"
            "\t\t}\n"
            "#endif\n"
            "\t\tdev = inode->i_sb->s_dev;\n"
            "\t\tino = inode->i_ino;\n"
            "#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT\n"
            "susfs_skip_orig_map_vma_stat:\n"
            "#endif\n"
            "\t\tpgoff = ((loff_t)vma->vm_pgoff) << PAGE_SHIFT;\n"
            "\t}\n"
        )
        text, _ = replace_once(text, old, new, logic_marker)

    write(rel, text)

# ---------------------------------------------------------------------------
# fs/notify/fdinfo.c
# ---------------------------------------------------------------------------
def patch_fdinfo():
    rel = "fs/notify/fdinfo.c"
    text = read(rel)

    # Add include.
    if "#include <linux/susfs_def.h>" not in text:
        anchor = "#include <linux/exportfs.h>\n"
        insertion = "#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n#include <linux/susfs_def.h>\n#endif\n"
        text, _ = insert_after_once(text, anchor, insertion, "#include <linux/susfs_def.h>")

    # Add extern prototype for helper used by fdinfo logic.
    if "susfs_is_current_non_root_user_app_proc" not in text:
        anchor = "#include \"fsnotify.h\"\n"
        insertion = (
            "#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n"
            "extern bool susfs_is_current_non_root_user_app_proc(void);\n"
            "#endif\n"
        )
        text, _ = insert_after_once(text, anchor, insertion, "susfs_is_current_non_root_user_app_proc")

    # Change show_fdinfo() callback signature and call site.
    old_sig = (
        "static void show_fdinfo(struct seq_file *m, struct file *f,\n"
        "\t\t\tvoid (*show)(struct seq_file *m,\n"
        "\t\t\t\t     struct fsnotify_mark *mark))\n"
    )
    new_sig = (
        "#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n"
        "static void show_fdinfo(struct seq_file *m, struct file *f,\n"
        "\t\t\tvoid (*show)(struct seq_file *m,\n"
        "\t\t\t\t     struct fsnotify_mark *mark,\n"
        "\t\t\t\t     struct file *file))\n"
        "#else\n"
        "static void show_fdinfo(struct seq_file *m, struct file *f,\n"
        "\t\t\tvoid (*show)(struct seq_file *m,\n"
        "\t\t\t\t     struct fsnotify_mark *mark))\n"
        "#endif\n"
    )
    text, _ = replace_once(text, old_sig, new_sig, "struct file *file))")

    old_call = "\t\tshow(m, mark);\n"
    new_call = (
        "#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n"
        "\t\tshow(m, mark, f);\n"
        "#else\n"
        "\t\tshow(m, mark);\n"
        "#endif\n"
    )
    text, _ = replace_once(text, old_call, new_call, "show(m, mark, f)")

    # Change inotify_fdinfo signature.
    old_inotify_sig = "static void inotify_fdinfo(struct seq_file *m, struct fsnotify_mark *mark)\n"
    new_inotify_sig = (
        "#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n"
        "static void inotify_fdinfo(struct seq_file *m, struct fsnotify_mark *mark, struct file *file)\n"
        "#else\n"
        "static void inotify_fdinfo(struct seq_file *m, struct fsnotify_mark *mark)\n"
        "#endif\n"
    )
    text, _ = replace_once(text, old_inotify_sig, new_inotify_sig, "inotify_fdinfo(struct seq_file *m, struct fsnotify_mark *mark, struct file *file)")

    # Insert SUSFS kstat fdinfo logic after inode is grabbed and before original seq_printf.
    logic_marker = "SUSFS: show original inode information for SUS_KSTAT fdinfo"
    if logic_marker not in text:
        anchor = "\tinode = igrab(fsnotify_conn_inode(mark->connector));\n\tif (inode) {\n"
        insertion = (
            "#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n"
            "\t\t/* SUSFS: show original inode information for SUS_KSTAT fdinfo */\n"
            "\t\tif (likely(susfs_is_current_non_root_user_app_proc()) &&\n"
            "\t\t    unlikely(inode->i_state & INODE_STATE_SUS_KSTAT)) {\n"
            "\t\t\tstruct path path;\n"
            "\t\t\tchar *pathname = kmalloc(PAGE_SIZE, GFP_KERNEL);\n"
            "\t\t\tchar *dpath;\n"
            "\t\t\tif (!pathname)\n"
            "\t\t\t\tgoto susfs_orig_seq_printf;\n"
            "\t\t\tdpath = d_path(&file->f_path, pathname, PAGE_SIZE);\n"
            "\t\t\tif (IS_ERR(dpath))\n"
            "\t\t\t\tgoto susfs_free_pathname;\n"
            "\t\t\tif (kern_path(dpath, 0, &path))\n"
            "\t\t\t\tgoto susfs_free_pathname;\n"
            "\t\t\tseq_printf(m, \"inotify wd:%x ino:%lx sdev:%x mask:%x ignored_mask:0 \",\n"
            "\t\t\t\t   inode_mark->wd, path.dentry->d_inode->i_ino,\n"
            "\t\t\t\t   path.dentry->d_inode->i_sb->s_dev,\n"
            "\t\t\t\t   inotify_mark_user_mask(mark));\n"
            "\t\t\tshow_mark_fhandle(m, path.dentry->d_inode);\n"
            "\t\t\tseq_putc(m, '\\n');\n"
            "\t\t\tiput(inode);\n"
            "\t\t\tpath_put(&path);\n"
            "\t\t\tkfree(pathname);\n"
            "\t\t\treturn;\n"
            "susfs_free_pathname:\n"
            "\t\t\tkfree(pathname);\n"
            "\t\t}\n"
            "susfs_orig_seq_printf:\n"
            "#endif\n"
        )
        text, _ = insert_after_once(text, anchor, insertion, logic_marker)

    write(rel, text)


def main():
    try:
        patch_fs_makefile()
        patch_task_mmu()
        patch_fdinfo()
    except PortError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
    print("[OK] Phase 1 SUSFS port completed")

if __name__ == "__main__":
    main()
