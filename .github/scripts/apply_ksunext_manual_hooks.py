#!/usr/bin/env python3
import sys
import re
from pathlib import Path

ROOT = Path(".").resolve()

def replace_regex_once(path, pattern, repl, required=True, flags=0):
    p = Path(path)
    data = read(p)

    if isinstance(repl, str) and repl.strip() in data:
        print(f"[SKIP] regex block already exists: {path}")
        return

    new_data, count = re.subn(pattern, repl, data, count=1, flags=flags)

    if count == 0:
        msg = f"[MISS] regex context not found in {path}: {pattern}"
        if required:
            raise RuntimeError(msg)
        print(msg)
        return

    write(p, new_data)
    print(f"[OK] regex patched: {path}")

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

    data = read(path)

    if "extern int ksu_handle_openat" not in data:
        if "long do_sys_openat2(" in data:
            insert_before(path, "long do_sys_openat2(", proto)
        elif "long do_sys_open(" in data:
            insert_before(path, "long do_sys_open(", proto)
        elif "SYSCALL_DEFINE3(openat" in data:
            insert_before(path, "SYSCALL_DEFINE3(openat", proto)
        else:
            print("[WARN] cannot find open function marker for prototype")

    data = read(path)

    if "ksu_handle_openat(&dfd" in data:
        print("[SKIP] open.c already patched")
        return

    # Case 1: kernel có do_sys_openat2()
    if "long do_sys_openat2(" in data:
        print("[INFO] patching open.c using do_sys_openat2")

        replace_regex_once(
            path,
            r"(?P<indent>\s*)int\s+(?P<var>err|fd)\s*=\s*build_open_flags\(\s*how\s*,\s*&op\s*\);",
            r"""\g<indent>int \g<var>;

#ifdef CONFIG_KSU
\g<indent>ksu_handle_openat(&dfd, &filename, &how->flags);
#endif
\g<indent>\g<var> = build_open_flags(how, &op);""",
            required=False,
        )
        return

    # Case 2: lisa dùng do_sys_open()
    if "long do_sys_open(" in data:
        print("[INFO] patching open.c using do_sys_open")

        replace_regex_once(
            path,
            r"(?P<indent>\s*)int\s+(?P<var>err|fd)\s*=\s*build_open_flags\(\s*flags\s*,\s*mode\s*,\s*&op\s*\);",
            r"""\g<indent>int \g<var>;

#ifdef CONFIG_KSU
\g<indent>ksu_handle_openat(&dfd, &filename, &flags);
#endif
\g<indent>\g<var> = build_open_flags(flags, mode, &op);""",
            required=False,
        )
        return

    print("[WARN] open hook not applied: no supported open function found")


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

    data = read(path)

    if "extern int ksu_handle_stat" not in data:
        if "int vfs_statx(" in data:
            insert_before(path, "int vfs_statx(", proto)
        elif "int vfs_fstatat(" in data:
            insert_before(path, "int vfs_fstatat(", proto)
        else:
            print("[WARN] cannot find stat function marker for prototype")

    data = read(path)

    if "ksu_handle_stat(&dfd, &filename, &flags);" in data:
        print("[SKIP] stat.c already patched")
        return

    # Preferred: hook vfs_statx()
    if "int vfs_statx(" in data:
        print("[INFO] patching stat.c using vfs_statx")

        pattern = (
            r"(int\s+vfs_statx\s*\(\s*int\s+dfd\s*,\s*"
            r"const\s+char\s+__user\s+\*filename\s*,\s*"
            r"int\s+flags\s*,.*?\)\s*\{)"
        )

        replace_regex_once(
            path,
            pattern,
            r"""\1

#ifdef CONFIG_KSU
    ksu_handle_stat(&dfd, &filename, &flags);
#endif""",
            required=True,
            flags=re.S,
        )
        return

    # Fallback: hook vfs_fstatat()
    if "int vfs_fstatat(" in data:
        print("[INFO] patching stat.c using vfs_fstatat fallback")

        pattern = (
            r"(int\s+vfs_fstatat\s*\(\s*int\s+dfd\s*,\s*"
            r"const\s+char\s+__user\s+\*filename\s*,.*?"
            r"int\s+flags\s*\)\s*\{)"
        )

        replace_regex_once(
            path,
            pattern,
            r"""\1

#ifdef CONFIG_KSU
    ksu_handle_stat(&dfd, &filename, &flags);
#endif""",
            required=False,
            flags=re.S,
        )
        return

    print("[WARN] stat hook not applied: no supported stat function found")


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
