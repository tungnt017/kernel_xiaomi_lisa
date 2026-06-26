def patch_kernel_includes(ksu_dir: Path) -> bool:
    # Target kernel_compat.h (where __strncpy_from_user_nofault is defined)
    target = find_first(ksu_dir, "kernel_compat.h")
    if target is None:
        print(f"[ERROR] kernel_compat.h not found in {ksu_dir}")
        return False
    print(f"[INFO] Found {target}")

    marker = "SUSFS_5_4_STRNCPY_COMPAT"
    src = target.read_text(encoding="utf-8", errors="surrogateescape")
    if marker in src:
        print(f"[SKIP] {target} already has strncpy compat shim")
        return True

    # Also remove leftover from kernel_includes.h if it was added there
    incl_h = find_first(ksu_dir, "kernel_includes.h")
    if incl_h is not None:
        incl_src = incl_h.read_text(encoding="utf-8", errors="surrogateescape")
        if marker in incl_src:
            # Strip the wrong-place shim
            pat = re.compile(
                r'\n*/\* SUSFS_5_4_STRNCPY_COMPAT \*/.*?#endif\n',
                re.DOTALL
            )
            incl_src_new = pat.sub("", incl_src)
            if incl_src_new != incl_src:
                incl_h.write_text(incl_src_new, encoding="utf-8", errors="surrogateescape")
                print(f"[OK] Removed misplaced shim from {incl_h}")

    # Walk to end of __strncpy_from_user_nofault function body
    pat = re.compile(
        r'static\s+inline\s+long\s+__strncpy_from_user_nofault\s*\([^)]*\)\s*\{',
        re.MULTILINE | re.DOTALL,
    )
    m = pat.search(src)
    if not m:
        print(f"[WARN] __strncpy_from_user_nofault not found, appending shim at end")
        insert_at = len(src)
    else:
        depth = 1
        i = m.end()
        while i < len(src) and depth > 0:
            c = src[i]
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
            i += 1
        insert_at = i

    shim = (
        "\n\n/* SUSFS_5_4_STRNCPY_COMPAT */\n"
        "#include <linux/version.h>\n"
        "#if LINUX_VERSION_CODE < KERNEL_VERSION(5, 10, 0)\n"
        "static inline long strncpy_from_user_nofault(char *dst,\n"
        "\t\tconst void __user *unsafe_addr, long count)\n"
        "{\n"
        "\treturn __strncpy_from_user_nofault(dst, unsafe_addr, count);\n"
        "}\n"
        "#endif\n"
    )
    new_src = src[:insert_at] + shim + src[insert_at:]

    backup = target.with_suffix(target.suffix + ".bak_compat")
    if not backup.exists():
        shutil.copy2(target, backup)
    target.write_text(new_src, encoding="utf-8", errors="surrogateescape")
    print(f"[OK] {target}: shim inserted after __strncpy_from_user_nofault body")
    return True
