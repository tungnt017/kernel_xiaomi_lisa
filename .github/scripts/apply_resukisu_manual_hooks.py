#!/usr/bin/env python3
import sys
import re
from pathlib import Path

ROOT = Path(".").resolve()


def read(path):
    return Path(path).read_text(errors="ignore")


def write(path, data):
    Path(path).write_text(data)


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


def insert_after_declarations(path, func_pattern, hook, label):
    data = read(path)
    span = find_function_span(data, func_pattern)

    if not span:
        print(f"[WARN] {label} function not found")
        return False

    start, brace_start, end = span
    body = data[brace_start + 1:end - 1]

    if hook.strip() in body:
        print(f"[SKIP] {label} already patched")
        return True

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

    lines.insert(insert_index, hook)
    new_body = "".join(lines)

    write(path, data[:brace_start + 1] + new_body + data[end - 1:])
    print(f"[OK] patched {label} after declarations")
    return True


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

    remove_prefixes = [
        "CONFIG_KSU=",
        "CONFIG_KSU_MANUAL_HOOK=",
        "CONFIG_KSU_KPROBE_HOOKS=",
        "CONFIG_KSU_KPROBES_HOOK=",
        "CONFIG_KSU_KPROBES_HOOKS=",
        "CONFIG_KSU_WITH_KPROBES=",
        "CONFIG_KALLSYMS=",
        "CONFIG_KALLSYMS_ALL=",
        "# CONFIG_KSU is not set",
        "# CONFIG_KSU_MANUAL_HOOK is not set",
        "# CONFIG_KSU_KPROBE_HOOKS is not set",
        "# CONFIG_KSU_KPROBES_HOOK is not set",
        "# CONFIG_KSU_KPROBES_HOOKS is not set",
        "# CONFIG_KSU_WITH_KPROBES is not set",
        "# CONFIG_KALLSYMS is not set",
        "# CONFIG_KALLSYMS_ALL is not set",
    ]

    lines = []
    for line in read(path).splitlines():
        if any(line.startswith(prefix) for prefix in remove_prefixes):
            continue
        lines.append(line)

    lines += [
        "",
        "# ReSukiSU",
        "CONFIG_KSU=y",
        "CONFIG_KSU_MANUAL_HOOK=y",
        "CONFIG_KALLSYMS=y",
        "CONFIG_KALLSYMS_ALL=y",
        "# CONFIG_KSU_KPROBE_HOOKS is not set",
        "# CONFIG_KSU_KPROBES_HOOK is not set",
        "# CONFIG_KSU_KPROBES_HOOKS is not set",
        "# CONFIG_KSU_WITH_KPROBES is not set",
        "",
    ]

    write(path, "\n".join(lines))
    print(f"[OK] enabled ReSukiSU manual hook in {path}")


def patch_exec():
    path = "fs/exec.c"

    proto = """#ifdef CONFIG_KSU_MANUAL_HOOK
__attribute__((hot))
extern int ksu_handle_execveat(int *fd, struct filename **filename_ptr,
                               void *argv, void *envp, int *flags);
#endif"""

    insert_before(path, "int do_execve(struct filename *filename,", proto, required=False)

    replace_once(
        path,
        """\treturn do_execveat_common(AT_FDCWD, filename, argv, envp, 0);""",
        """#ifdef CONFIG_KSU_MANUAL_HOOK
	ksu_handle_execveat((int *)AT_FDCWD, &filename, &argv, &envp, 0);
#endif
	return do_execveat_common(AT_FDCWD, filename, argv, envp, 0);""",
        required=False,
    )

    replace_once(
        path,
        """\treturn do_execveat_common(fd, filename, argv, envp, flags);""",
        """#ifdef CONFIG_KSU_MANUAL_HOOK
	ksu_handle_execveat(&fd, &filename, &argv, &envp, &flags);
#endif
	return do_execveat_common(fd, filename, argv, envp, flags);""",
        required=False,
    )


def patch_open():
    path = "fs/open.c"
    data = read(path)

    proto = """#ifdef CONFIG_KSU_MANUAL_HOOK
extern int ksu_handle_faccessat(int *dfd, const char __user **filename_user,
                                int *mode, int *flags);
#endif"""

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

    if "extern int ksu_handle_faccessat" not in data:
        data = data[:start] + proto + "\n\n" + data[start:]
        write(path, data)
        print("[OK] inserted faccessat prototype")

    hook = (
        "\n#ifdef CONFIG_KSU_MANUAL_HOOK\n"
        "\tksu_handle_faccessat(&dfd, &filename, &mode, NULL);\n"
        "#endif\n"
    )

    insert_after_declarations(path, func_pattern, hook, "open.c faccessat")


def patch_stat():
    path = "fs/stat.c"
    data = read(path)

    proto = """#ifdef CONFIG_KSU_MANUAL_HOOK
__attribute__((hot))
extern int ksu_handle_stat(int *dfd, const char __user **filename_user,
                           int *flags);
extern void ksu_handle_newfstat_ret(unsigned int *fd,
                                    struct stat __user **statbuf_ptr);
#if defined(__ARCH_WANT_STAT64) || defined(__ARCH_WANT_COMPAT_STAT64)
extern void ksu_handle_fstat64_ret(unsigned long *fd,
                                   struct stat64 __user **statbuf_ptr);
#endif
#endif"""

    if "extern int ksu_handle_stat" not in data:
        markers = [
            "SYSCALL_DEFINE4(newfstatat",
            "SYSCALL_DEFINE2(newfstat",
            "int vfs_statx(",
        ]
        inserted = False
        for marker in markers:
            if marker in data:
                insert_before(path, marker, proto, required=False)
                inserted = True
                break
        if not inserted:
            print("[WARN] cannot find stat marker for prototype")

    data = read(path)

    if "ksu_handle_stat(&dfd, &filename, &flag);" not in data:
        newfstatat_pattern = re.compile(
            r"SYSCALL_DEFINE4\s*\(\s*newfstatat\s*,\s*int\s*,\s*dfd\s*,\s*"
            r"const\s+char\s+__user\s*\*\s*,\s*filename\s*,\s*"
            r"struct\s+stat\s+__user\s*\*\s*,\s*statbuf\s*,\s*"
            r"int\s*,\s*flag\s*\)\s*\{",
            re.S,
        )

        hook = (
            "\n#ifdef CONFIG_KSU_MANUAL_HOOK\n"
            "\tksu_handle_stat(&dfd, &filename, &flag);\n"
            "#endif\n"
        )

        if find_function_span(data, newfstatat_pattern):
            insert_after_declarations(path, newfstatat_pattern, hook, "stat.c newfstatat")
        else:
            print("[WARN] newfstatat not found, trying vfs_statx fallback")
            vfs_statx_pattern = re.compile(
                r"int\s+vfs_statx\s*\(\s*int\s+dfd\s*,\s*"
                r"const\s+char\s+__user\s+\*filename\s*,\s*"
                r"int\s+flags\s*,.*?\)\s*\{",
                re.S,
            )
            hook_vfs = (
                "\n#ifdef CONFIG_KSU_MANUAL_HOOK\n"
                "\tksu_handle_stat(&dfd, &filename, &flags);\n"
                "#endif\n"
            )
            insert_after_declarations(path, vfs_statx_pattern, hook_vfs, "stat.c vfs_statx")

    data = read(path)

    if "SYSCALL_DEFINE4(fstatat64" in data and "ksu_handle_stat(&dfd, &filename, &flag);" not in data:
        fstatat64_pattern = re.compile(
            r"SYSCALL_DEFINE4\s*\(\s*fstatat64\s*,\s*int\s*,\s*dfd\s*,\s*"
            r"const\s+char\s+__user\s*\*\s*,\s*filename\s*,.*?"
            r"int\s*,\s*flag\s*\)\s*\{",
            re.S,
        )
        hook = (
            "\n#ifdef CONFIG_KSU_MANUAL_HOOK\n"
            "\tksu_handle_stat(&dfd, &filename, &flag);\n"
            "#endif\n"
        )
        insert_after_declarations(path, fstatat64_pattern, hook, "stat.c fstatat64")

    data = read(path)

    if "ksu_handle_newfstat_ret(&fd, &statbuf);" not in data:
        newfstat_pattern = re.compile(
            r"SYSCALL_DEFINE2\s*\(\s*newfstat\s*,\s*unsigned\s+int\s*,\s*fd\s*,\s*"
            r"struct\s+stat\s+__user\s*\*\s*,\s*statbuf\s*\)\s*\{",
            re.S,
        )
        span = find_function_span(data, newfstat_pattern)

        if span:
            start, brace_start, end = span
            body = data[start:end]
            ret_pattern = re.compile(r"\n(?P<indent>[ \t]*)return\s+error\s*;")
            m = ret_pattern.search(body)
            if m:
                indent = m.group("indent")
                hook = (
                    "\n#ifdef CONFIG_KSU_MANUAL_HOOK\n"
                    f"{indent}ksu_handle_newfstat_ret(&fd, &statbuf);\n"
                    "#endif"
                )
                body_new = ret_pattern.sub(hook + m.group(0), body, count=1)
                write(path, data[:start] + body_new + data[end:])
                print("[OK] patched newfstat return hook")
            else:
                print("[WARN] return error not found in newfstat")
        else:
            print("[WARN] newfstat syscall not found")

    data = read(path)

    if "SYSCALL_DEFINE2(fstat64" in data and "ksu_handle_fstat64_ret(&fd, &statbuf);" not in data:
        fstat64_pattern = re.compile(
            r"SYSCALL_DEFINE2\s*\(\s*fstat64\s*,\s*unsigned\s+long\s*,\s*fd\s*,\s*"
            r"struct\s+stat64\s+__user\s*\*\s*,\s*statbuf\s*\)\s*\{",
            re.S,
        )
        span = find_function_span(data, fstat64_pattern)

        if span:
            start, brace_start, end = span
            body = data[start:end]
            ret_pattern = re.compile(r"\n(?P<indent>[ \t]*)return\s+error\s*;")
            m = ret_pattern.search(body)
            if m:
                indent = m.group("indent")
                hook = (
                    "\n#ifdef CONFIG_KSU_MANUAL_HOOK\n"
                    f"{indent}ksu_handle_fstat64_ret(&fd, &statbuf);\n"
                    "#endif"
                )
                body_new = ret_pattern.sub(hook + m.group(0), body, count=1)
                write(path, data[:start] + body_new + data[end:])
                print("[OK] patched fstat64 return hook")
            else:
                print("[WARN] return error not found in fstat64")
        else:
            print("[WARN] fstat64 syscall not found")


def patch_reboot():
    path = "kernel/reboot.c"

    proto = """#ifdef CONFIG_KSU_MANUAL_HOOK
extern int ksu_handle_sys_reboot(int magic1, int magic2, unsigned int cmd,
                                 void __user *arg);
#endif"""

    insert_before(path, "SYSCALL_DEFINE4(reboot,", proto, required=False)

    replace_once(
        path,
        """\t/* For safety, we require "magic" arguments. */""",
        """#ifdef CONFIG_KSU_MANUAL_HOOK
	ksu_handle_sys_reboot(magic1, magic2, cmd, arg);
#endif

	/* For safety, we require "magic" arguments. */""",
        required=False,
    )


def ensure_export_header(data):
    if "#include <linux/export.h>" in data:
        return data

    if "#include <linux/kernel.h>" in data:
        return data.replace(
            "#include <linux/kernel.h>",
            "#include <linux/kernel.h>\n#include <linux/export.h>",
            1,
        )

    return "#include <linux/export.h>\n" + data


def patch_selinuxfs_export():
    path = "security/selinux/selinuxfs.c"

    if not Path(path).exists():
        print("[WARN] selinuxfs.c not found")
        return

    data = read(path)

    if "sel_handle_status_ops" not in data:
        print("[WARN] sel_handle_status_ops not found in selinuxfs.c")
        return

    data = ensure_export_header(data)

    # Make symbol globally visible if it is static.
    data = data.replace(
        "static const struct file_operations sel_handle_status_ops",
        "const struct file_operations sel_handle_status_ops",
    )
    data = data.replace(
        "static struct file_operations sel_handle_status_ops",
        "struct file_operations sel_handle_status_ops",
    )

    if "EXPORT_SYMBOL_GPL(sel_handle_status_ops);" not in data and "EXPORT_SYMBOL(sel_handle_status_ops);" not in data:
        pattern = re.compile(
            r"((?:const\s+)?struct\s+file_operations\s+sel_handle_status_ops\s*=\s*\{.*?\};)",
            re.S,
        )
        m = pattern.search(data)

        if not m:
            print("[WARN] sel_handle_status_ops definition block not matched")
            write(path, data)
            return

        export_block = """

#ifdef CONFIG_KSU
EXPORT_SYMBOL_GPL(sel_handle_status_ops);
#endif
"""
        data = data[:m.end()] + export_block + data[m.end():]
        print("[OK] exported sel_handle_status_ops in selinuxfs.c")
    else:
        print("[SKIP] sel_handle_status_ops already exported")

    write(path, data)


def patch_selinuxfs_write_op_export():
    path = "security/selinux/selinuxfs.c"

    if not Path(path).exists():
        print("[WARN] selinuxfs.c not found for write_op")
        return

    data = read(path)
    data = ensure_export_header(data)

    # Remove dangling write_op export lines that may be present without a real definition.
    data = re.sub(
        r"\n\s*EXPORT_SYMBOL(?:_GPL)?\s*\(\s*write_op\s*\)\s*;\s*\n",
        "\n",
        data,
    )

    # If write_op is already defined as a variable/pointer, only export it.
    write_op_defined = (
        re.search(r"\bwrite_op\s*=", data) is not None
        or re.search(r"\(\s*\*\s*write_op\s*\)", data) is not None
    )

    if write_op_defined:
        if "EXPORT_SYMBOL_GPL(write_op);" not in data and "EXPORT_SYMBOL(write_op);" not in data:
            data += """

#ifdef CONFIG_KSU
EXPORT_SYMBOL_GPL(write_op);
#endif
"""
            print("[OK] exported existing write_op")
        else:
            print("[SKIP] write_op already defined/exported")
        write(path, data)
        return

    # ReSukiSU references write_op from selinux_hide. Define it here so vmlinux links.
    # On this kernel, sel_write_load should exist in selinuxfs.c. If it does not, keep
    # a NULL-initialized pointer so the symbol still resolves; ReSukiSU can handle export checks.
    if "sel_write_load" in data:
        define_block = """

#ifdef CONFIG_KSU
ssize_t (*write_op)(struct file *file, const char __user *buf,
		    size_t count, loff_t *ppos) = sel_write_load;
EXPORT_SYMBOL_GPL(write_op);
#endif
"""
    else:
        define_block = """

#ifdef CONFIG_KSU
ssize_t (*write_op)(struct file *file, const char __user *buf,
		    size_t count, loff_t *ppos);
EXPORT_SYMBOL_GPL(write_op);
#endif
"""

    data += define_block
    write(path, data)
    print("[OK] defined and exported write_op in selinuxfs.c")


def main():
    defconfig = sys.argv[1] if len(sys.argv) >= 2 else "lisa_defconfig"

    patch_defconfig(defconfig)
    patch_exec()
    patch_open()
    patch_stat()
    patch_reboot()
    patch_selinuxfs_export()
    patch_selinuxfs_write_op_export()

    print("[DONE] ReSukiSU manual hooks applied.")


if __name__ == "__main__":
    main()
