#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(".").resolve()


def read(path):
    return Path(path).read_text(errors="ignore")


def write(path, data):
    Path(path).write_text(data)


def ensure_contains(path, needle, append_text):
    p = Path(path)
    data = read(p)
    if needle not in data:
        data += append_text
        write(p, data)


def replace_once(path, old, new, required=True):
    p = Path(path)
    data = read(p)
    if new in data:
        print(f"[SKIP] already patched: {path}")
        return

    if old not in data:
        msg = f"[MISS] context not found in {path}:\n{old}"
        if required:
            raise RuntimeError(msg)
        print(msg)
        return

    data = data.replace(old, new, 1)
    write(p, data)
    print(f"[OK] patched: {path}")


def insert_before(path, marker, block):
    p = Path(path)
    data = read(p)

    if block.strip() in data:
        print(f"[SKIP] block already exists: {path}")
        return

    if marker not in data:
        raise RuntimeError(f"[MISS] marker not found in {path}: {marker}")

    data = data.replace(marker, block + "\n\n" + marker, 1)
    write(p, data)
    print(f"[OK] inserted block: {path}")


def patch_defconfig(defconfig):
    candidates = [
        ROOT / "arch" / "arm64" / "configs" / defconfig,
        ROOT / "arch" / "arm64" / "configs" / "vendor" / defconfig,
    ]

    path = None
    for c in candidates:
        if c.exists():
            path = c
            break

    if path is None:
        print("[ERROR] defconfig not found.")
        print("Available defconfigs:")
        for f in sorted((ROOT / "arch" / "arm64" / "configs").rglob("*defconfig")):
            print(f" - {f}")
        sys.exit(1)

    data = read(path)
    lines = []
    for line in data.splitlines():
        if line.startswith("CONFIG_KSU="):
            continue
        if line.startswith("CONFIG_KSU_KPROBE_HOOKS="):
            continue
        if line.startswith("# CONFIG_KSU is not set"):
            continue
        if line.startswith("# CONFIG_KSU_KPROBE_HOOKS is not set"):
            continue
        lines.append(line)

    lines += [
        "",
        "# KernelSU Next",
        "CONFIG_KSU=y",
        "# CONFIG_KSU_KPROBE_HOOKS is not set",
        "",
    ]

    write(path, "\n".join(lines))
    print(f"[OK] enabled CONFIG_KSU in {path}")


def patch_exec():
    path = "fs/exec.c"

    proto = """#ifdef CONFIG_KSU
__attribute__((hot))
extern int ksu_handle_execveat(int *fd, struct filename **filename_ptr,
                   void *argv, void *envp, int *flags);
#endif"""

    insert_before(path, "int do_execve(struct filename *filename,", proto)

    replace_once(
        path,
        """\treturn do_execveat_common(AT_FDCWD, filename, argv, envp, 0);""",
        """#ifdef CONFIG_KSU
    {
        int fd = AT_FDCWD;
        int flags = 0;
        ksu_handle_execveat(&fd, &filename, &argv, &envp, &flags);
        return do_execveat_common(fd, filename, argv, envp, flags);
    }
#else
    return do_execveat_common(AT_FDCWD, filename, argv, envp, 0);
#endif""",
        required=False,
    )

    replace_once(
        path,
        """\treturn do_execveat_common(fd, filename, argv, envp, flags);""",
        """#ifdef CONFIG_KSU
    ksu_handle_execveat(&fd, &filename, &argv, &envp, &flags);
#endif
    return do_execveat_common(fd, filename, argv, envp, flags);""",
        required=False,
    )


def patch_open():
    path = "fs/open.c"

    proto = """#ifdef CONFIG_KSU
extern int ksu_handle_openat(int *dfd, const char __user **filename_user,
                             int *flags);
#endif"""

    insert_before(path, "long do_sys_openat2(", proto)

    # insert đúng SAU khi biến đã tồn tại
    replace_once(
        path,
        "struct open_flags op;",
        """struct open_flags op;

#ifdef CONFIG_KSU
    ksu_handle_openat(&dfd, &filename, &how->flags);
#endif""",
        required=False,
    )

    # fallback cho kernel không có openat2
    replace_once(
        path,
        "SYSCALL_DEFINE3(openat,",
        """SYSCALL_DEFINE3(openat,
#ifdef CONFIG_KSU
    ksu_handle_openat(&dfd, &filename, &flags);
#endif""",
        required=False,
    )


def patch_read_write():
    path = "fs/read_write.c"

    proto = """#ifdef CONFIG_KSU
extern int ksu_handle_vfs_read(struct file **file_ptr, char __user **buf_ptr,
                   size_t *count_ptr, loff_t **pos);
extern int ksu_handle_vfs_write(struct file **file_ptr,
                const char __user **buf_ptr,
                size_t *count_ptr, loff_t **pos);
#endif"""

    insert_before(path, "ssize_t vfs_read(", proto)

    replace_once(
        path,
        """\tif (!(file->f_mode & FMODE_READ))""",
        """#ifdef CONFIG_KSU
    ksu_handle_vfs_read(&file, &buf, &count, &pos);
#endif
    if (!(file->f_mode & FMODE_READ))""",
        required=False,
    )

    replace_once(
        path,
        """\tif (!(file->f_mode & FMODE_WRITE))""",
        """#ifdef CONFIG_KSU
    ksu_handle_vfs_write(&file, &buf, &count, &pos);
#endif
    if (!(file->f_mode & FMODE_WRITE))""",
        required=False,
    )


def patch_stat():
    path = "fs/stat.c"

    proto = """#ifdef CONFIG_KSU
extern int ksu_handle_stat(int *dfd, const char __user **filename_user,
                           int *flags);
#endif"""

    insert_before(path, "SYSCALL_DEFINE4(statx,", proto)

    # hook ngay sau dấu {
    data = read(path)

    if "ksu_handle_stat" in data:
        print("[SKIP] stat already patched")
        return

    new_data = data.replace(
        "{",
        """{
#ifdef CONFIG_KSU
    ksu_handle_stat(&dfd, &filename, &flags);
#endif
""",
        1
    )

    write(path, new_data)
    print("[OK] patched stat.c (safe mode)")
``


def patch_reboot():
    path = "kernel/reboot.c"

    proto = """#ifdef CONFIG_KSU
extern int ksu_handle_sys_reboot(int magic1, int magic2, unsigned int cmd,
                 void __user *arg);
#endif"""

    insert_before(path, "SYSCALL_DEFINE4(reboot,", proto)

    replace_once(
        path,
        """\t/* For safety, we require "magic" arguments. */""",
        """#ifdef CONFIG_KSU
    ksu_handle_sys_reboot(magic1, magic2, cmd, arg);
#endif

    /* For safety, we require "magic" arguments. */""",
        required=False,
    )


def main():
    if len(sys.argv) < 2:
        defconfig = "lisa_defconfig"
    else:
        defconfig = sys.argv[1]

    patch_defconfig(defconfig)

    patch_exec()
    patch_open()
    patch_read_write()
    patch_stat()
    patch_reboot()

    print("[DONE] KernelSU Next manual hooks applied.")


if __name__ == "__main__":
    main()
