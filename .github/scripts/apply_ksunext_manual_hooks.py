#!/usr/bin/env python3
import sys
import re
from pathlib import Path

ROOT = Path(".").resolve()


def read(path):
    return Path(path).read_text(errors="ignore")


def write(path, data):
    Path(path).write_text(data)


def replace_once(path, old, new, required=True):
    p = Path(path)
    data = read(p)
    if new in data:
        print(f"[SKIP] already patched: {path}")
        return True
    if old not in data:
        msg = f"[MISS] context not found in {path}:\n{old}"
        if required:
            raise RuntimeError(msg)
        print(msg)
        return False
    data = data.replace(old, new, 1)
    write(p, data)
    print(f"[OK] patched: {path}")
    return True


def insert_before(path, marker, block, required=True):
    p = Path(path)
    data = read(p)
    if block.strip() in data:
        print(f"[SKIP] block already exists: {path}")
        return True
    if marker not in data:
        msg = f"[MISS] marker not found in {path}: {marker}"
        if required:
            raise RuntimeError(msg)
        print(msg)
        return False
    data = data.replace(marker, block + "\n\n" + marker, 1)
    write(p, data)
    print(f"[OK] inserted block: {path}")
    return True


def find_function_span(data, pattern):
    m = pattern.search(data)
    if not m:
        return None
    brace_start = data.find("{", m.start())
    if brace_start < 0:
        return None
    depth = 0
    for i in range(brace_start, len(data)):
        if data[i] == "{":
            depth += 1
        elif data[i] == "}":
            depth -= 1
            if depth == 0:
                return m.start(), brace_start, i + 1
    return None


def patch_defconfig(defconfig):
    candidates = [
        ROOT / "arch" / "arm64" / "configs" / defconfig,
        ROOT / "arch" / "arm64" / "configs" / "vendor" / defconfig,
    ]
    path = next((c for c in candidates if c.exists()), None)

    if path is None:
        print("[ERROR] defconfig not found.")
        print("Available defconfigs:")
        for f in sorted((ROOT / "arch" / "arm64" / "configs").rglob("*defconfig")):
            print(f" - {f}")
        sys.exit(1)

    lines = []
    for line in read(path).splitlines():
        if line.startswith("CONFIG_KSU="):
            continue
        if line.startswith("CONFIG_KSU_MANUAL_HOOK="):
            continue
        if line.startswith("CONFIG_KSU_KPROBE_HOOKS="):
            continue
        if line.startswith("CONFIG_KSU_KPROBES_HOOK="):
            continue
        if line.startswith("CONFIG_KSU_KPROBES_HOOKS="):
            continue
        if line.startswith("CONFIG_KSU_WITH_KPROBES="):
            continue

        if line.startswith("# CONFIG_KSU is not set"):
            continue
        if line.startswith("# CONFIG_KSU_MANUAL_HOOK is not set"):
            continue
        if line.startswith("# CONFIG_KSU_KPROBE_HOOKS is not set"):
            continue
        if line.startswith("# CONFIG_KSU_KPROBES_HOOK is not set"):
            continue
        if line.startswith("# CONFIG_KSU_KPROBES_HOOKS is not set"):
            continue
        if line.startswith("# CONFIG_KSU_WITH_KPROBES is not set"):
            continue

        lines.append(line)

    lines += [
        "",
        "# KernelSU Next",
        "CONFIG_KSU=y",
        "CONFIG_KSU_MANUAL_HOOK=y",		
		"CONFIG_KSU_SUSFS=y",
		"CONFIG_KSU_SUSFS_SUS_PATH=y",
		"CONFIG_KSU_SUSFS_SUS_MAP=y",
		"CONFIG_KSU_SUSFS_OPEN_REDIRECT=y",
		"CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG=y",
		"CONFIG_KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS=y",

        "# CONFIG_KSU_KPROBE_HOOKS is not set",
        "# CONFIG_KSU_KPROBES_HOOK is not set",
        "# CONFIG_KSU_KPROBES_HOOKS is not set",
        "# CONFIG_KSU_WITH_KPROBES is not set",
        "",
    ]

    write(path, "\n".join(lines))
    print(f"[OK] enabled CONFIG_KSU manual hook in {path}")


def patch_exec():
    path = "fs/exec.c"
    proto = """#ifdef CONFIG_KSU
__attribute__((hot))
extern int ksu_handle_execveat(int *fd, struct filename **filename_ptr,
                               void *argv, void *envp, int *flags);
#endif"""
    insert_before(path, "int do_execve(struct filename *filename,", proto, required=False)

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
    data = read(path)

    proto = """#ifdef CONFIG_KSU
extern int ksu_handle_faccessat(int *dfd, const char __user **filename_user,
                                int *mode, int *flags);
#endif"""

    # Locate do_faccessat()
    func_pattern = re.compile(
        r"(?:static\s+)?(?:long|int)\s+do_faccessat\s*\(\s*"
        r"int\s+dfd\s*,\s*"
        r"const\s+char\s+__user\s+\*filename\s*,\s*"
        r"int\s+mode\s*\)\s*\{",
        re.S,
    )

    span = find_function_span(data, func_pattern)

    if not span:
        print("[WARN] do_faccessat() not found in fs/open.c, faccessat hook not applied")
        return

    start, brace_start, end = span

    # Insert prototype before do_faccessat()
    if "extern int ksu_handle_faccessat" not in data:
        data = data[:start] + proto + "\n\n" + data[start:]
        write(path, data)
        print("[OK] inserted faccessat prototype")

        data = read(path)
        span = find_function_span(data, func_pattern)

        if not span:
            print("[WARN] do_faccessat() disappeared after prototype insert")
            return

        start, brace_start, end = span

    body = data[brace_start + 1:end - 1]

    if "ksu_handle_faccessat(&dfd, &filename, &mode" in body:
        print("[SKIP] open.c faccessat already patched")
        return

    lines = body.splitlines(True)
    insert_index = 0

    declaration_regex = re.compile(
        r"^\s*(?:const\s+)?(?:"
        r"struct|unsigned|signed|int|long|short|char|bool|umode_t|"
        r"uid_t|gid_t|kuid_t|kgid_t|loff_t|size_t|ssize_t|u8|u16|u32|u64|"
        r"s8|s16|s32|s64|enum"
        r")\b.*;\s*(?:/\*.*\*/)?\s*$"
    )

    blank_or_comment_regex = re.compile(
        r"^\s*$|^\s*/\*.*\*/\s*$|^\s*//.*$"
    )

    for idx, line in enumerate(lines):
        if blank_or_comment_regex.match(line):
            insert_index = idx + 1
            continue

        if declaration_regex.match(line):
            insert_index = idx + 1
            continue

        break

    hook = (
        "\n#ifdef CONFIG_KSU\n"
        "\tksu_handle_faccessat(&dfd, &filename, &mode, NULL);\n"
        "#endif\n"
    )

    lines.insert(insert_index, hook)
    new_body = "".join(lines)

    write(path, data[:brace_start + 1] + new_body + data[end - 1:])
    print("[OK] patched open.c faccessat after declarations")



def patch_read_write():
    path = "fs/read_write.c"

    proto = """#ifdef CONFIG_KSU
extern bool ksu_vfs_read_hook;
extern int ksu_handle_sys_read(unsigned int fd, char __user **buf_ptr,
                               size_t *count_ptr);
#endif"""

    data = read(path)

    if "extern int ksu_handle_sys_read" not in data:
        if "ssize_t ksys_read(" in data:
            insert_before(path, "ssize_t ksys_read(", proto, required=False)
        elif "SYSCALL_DEFINE3(read," in data:
            insert_before(path, "SYSCALL_DEFINE3(read,", proto, required=False)
        else:
            print("[WARN] cannot find read marker for prototype")

    data = read(path)

    # Patch ksys_read only.
    # Do NOT patch ksys_write because KernelSU-Next v3.2.0-legacy may not export
    # ksu_vfs_write_hook / ksu_handle_sys_write.
    if "ksu_handle_sys_read(fd" not in data:
        print("[INFO] patching ksys_read")

        read_pattern = re.compile(
            r"(?P<header>ssize_t\s+ksys_read\s*\(\s*unsigned\s+int\s+fd\s*,\s*"
            r"char\s+__user\s+\*buf\s*,\s*size_t\s+count\s*\)\s*\{\s*)"
            r"(?P<indent>[ \t]*)struct\s+fd\s+f\s*=\s*fdget_pos\s*\(\s*fd\s*\)\s*;\s*\n"
            r"(?P=indent)ssize_t\s+ret\s*=\s*-EBADF\s*;",
            re.S,
        )

        def read_repl(m):
            indent = m.group("indent")
            return (
                m.group("header")
                + f"{indent}struct fd f;\n"
                + f"{indent}ssize_t ret = -EBADF;\n\n"
                + "#ifdef CONFIG_KSU\n"
                + f"{indent}if (unlikely(ksu_vfs_read_hook))\n"
                + f"{indent}\tksu_handle_sys_read(fd, &buf, &count);\n"
                + "#endif\n\n"
                + f"{indent}f = fdget_pos(fd);"
            )

        data, count = read_pattern.subn(read_repl, data, count=1)

        if count:
            print("[OK] patched ksys_read")
        else:
            print("[WARN] ksys_read pattern not found")
    else:
        print("[SKIP] ksys_read already patched")

    write(path, data)


def patch_stat():
    path = "fs/stat.c"
    data = read(path)

    proto = """#ifdef CONFIG_KSU
extern int ksu_handle_stat(int *dfd, const char __user **filename_user,
                           int *flags);
#endif"""

    if "extern int ksu_handle_stat" not in data:
        if "int vfs_statx(" in data:
            insert_before(path, "int vfs_statx(", proto, required=False)
        elif "int vfs_fstatat(" in data:
            insert_before(path, "int vfs_fstatat(", proto, required=False)
        else:
            print("[WARN] cannot find stat function marker for prototype")

    data = read(path)
    func_pattern = re.compile(
        r"int\s+vfs_statx\s*\(\s*int\s+dfd\s*,\s*"
        r"const\s+char\s+__user\s+\*filename\s*,\s*"
        r"int\s+flags\s*,.*?\)\s*\{",
        re.S,
    )
    span = find_function_span(data, func_pattern)
    if not span:
        print("[WARN] vfs_statx function not found, stat hook not applied")
        return

    start, brace_start, end = span
    body = data[brace_start + 1:end - 1]
    if "ksu_handle_stat(&dfd, &filename, &flags);" in body:
        print("[SKIP] stat.c already patched")
        return

    lines = body.splitlines(True)
    insert_index = 0
    declaration_regex = re.compile(
        r"^\s*(?:const\s+)?(?:struct|unsigned|signed|int|long|short|char|bool|umode_t|"
        r"uid_t|gid_t|loff_t|size_t|ssize_t|u8|u16|u32|u64|s8|s16|s32|s64|enum)\b.*;\s*(?:/\*.*\*/)?\s*$"
    )
    blank_or_comment_regex = re.compile(r"^\s*$|^\s*/\*.*\*/\s*$|^\s*//.*$")

    for idx, line in enumerate(lines):
        if blank_or_comment_regex.match(line):
            insert_index = idx + 1
            continue
        if declaration_regex.match(line):
            insert_index = idx + 1
            continue
        break

    hook = "\n#ifdef CONFIG_KSU\n\tksu_handle_stat(&dfd, &filename, &flags);\n#endif\n"
    lines.insert(insert_index, hook)
    new_body = "".join(lines)
    write(path, data[:brace_start + 1] + new_body + data[end - 1:])
    print("[OK] patched stat.c after declarations")


def patch_reboot():
    path = "kernel/reboot.c"
    proto = """#ifdef CONFIG_KSU
extern int ksu_handle_sys_reboot(int magic1, int magic2, unsigned int cmd,
                                 void __user *arg);
#endif"""
    insert_before(path, "SYSCALL_DEFINE4(reboot,", proto, required=False)
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
    defconfig = sys.argv[1] if len(sys.argv) >= 2 else "lisa_defconfig"
    patch_defconfig(defconfig)
    patch_exec()
    patch_open()
    patch_read_write()
    patch_stat()
    patch_reboot()
    print("[DONE] KernelSU Next manual hooks applied.")


if __name__ == "__main__":
    main()
