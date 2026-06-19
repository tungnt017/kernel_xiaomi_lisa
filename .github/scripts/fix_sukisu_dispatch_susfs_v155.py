#!/usr/bin/env python3
from pathlib import Path
import re

ROOT = Path.cwd()
DISPATCH = ROOT / "drivers/kernelsu/supercall/dispatch.c"
FD_C = ROOT / "fs/proc/fd.c"
DEFCONFIG = ROOT / "arch/arm64/configs/lisa_defconfig"

def log(msg: str):
    print(msg, flush=True)

def replace_block(text: str, start_pat: str, end_pat: str, replacement: str) -> str:
    start = text.find(start_pat)
    if start < 0:
        raise SystemExit(f"[ERROR] start pattern not found: {start_pat}")
    end = text.find(end_pat, start)
    if end < 0:
        raise SystemExit(f"[ERROR] end pattern not found after start: {end_pat}")
    return text[:start] + replacement + text[end:]

if not DISPATCH.exists():
    raise SystemExit(f"[ERROR] missing {DISPATCH}")

text = DISPATCH.read_text(errors="ignore")

include_block = "#ifdef CONFIG_KSU_SUSFS\n#include <linux/susfs.h>\n#ifndef SUSFS_MAGIC\n#define SUSFS_MAGIC 0x55555\n#endif\n#endif\n\n"
if "#include <linux/susfs.h>" not in text:
    text = include_block + text
    log("[OK] inserted SUSFS include/compat magic block into dispatch.c")
else:
    log("[OK] dispatch.c already includes linux/susfs.h")

new_dispatch = """#ifdef CONFIG_KSU_SUSFS
int ksu_handle_sys_reboot(int magic1, int magic2, unsigned int cmd, void __user **arg)
{
    void __user *uarg = (void __user *)arg;

    if (magic1 != KSU_INSTALL_MAGIC1) {
        return -EINVAL;
    }

    if (magic2 == SUSFS_MAGIC && current_uid().val == 0) {
        switch (cmd) {
#ifdef CONFIG_KSU_SUSFS_SUS_PATH
        case CMD_SUSFS_ADD_SUS_PATH:
            return susfs_add_sus_path((struct st_susfs_sus_path __user *)uarg);
#endif

#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT
        case CMD_SUSFS_ADD_SUS_MOUNT:
            return susfs_add_sus_mount((struct st_susfs_sus_mount __user *)uarg);
#endif

#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT
        case CMD_SUSFS_ADD_SUS_KSTAT:
            return susfs_add_sus_kstat((struct st_susfs_sus_kstat __user *)uarg);
        case CMD_SUSFS_UPDATE_SUS_KSTAT:
            return susfs_update_sus_kstat((struct st_susfs_sus_kstat __user *)uarg);
        case CMD_SUSFS_ADD_SUS_KSTAT_STATICALLY:
            return susfs_add_sus_kstat((struct st_susfs_sus_kstat __user *)uarg);
#endif

#ifdef CONFIG_KSU_SUSFS_TRY_UMOUNT
        case CMD_SUSFS_ADD_TRY_UMOUNT:
            return susfs_add_try_umount((struct st_susfs_try_umount __user *)uarg);
        case CMD_SUSFS_RUN_UMOUNT_FOR_CURRENT_MNT_NS:
            susfs_try_umount(current_uid().val);
            return 0;
#endif

#ifdef CONFIG_KSU_SUSFS_SPOOF_UNAME
        case CMD_SUSFS_SET_UNAME:
            return susfs_set_uname((struct st_susfs_uname __user *)uarg);
#endif

#ifdef CONFIG_KSU_SUSFS_ENABLE_LOG
        case CMD_SUSFS_ENABLE_LOG: {
            int enabled = 0;
            if (copy_from_user(&enabled, uarg, sizeof(enabled)))
                return -EFAULT;
            susfs_set_log(enabled != 0);
            return 0;
        }
#endif

#ifdef CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG
        case CMD_SUSFS_SET_CMDLINE_OR_BOOTCONFIG:
            return susfs_set_cmdline_or_bootconfig((char __user *)uarg);
#endif

#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT
        case CMD_SUSFS_ADD_OPEN_REDIRECT:
            return susfs_add_open_redirect((struct st_susfs_open_redirect __user *)uarg);
#endif

#ifdef CONFIG_KSU_SUSFS_SUS_SU
        case CMD_SUSFS_SUS_SU:
            return susfs_sus_su((struct st_sus_su __user *)uarg);
        case CMD_SUSFS_SHOW_SUS_SU_WORKING_MODE: {
            int mode = susfs_get_sus_su_working_mode();
            if (copy_to_user(uarg, &mode, sizeof(mode)))
                return -EFAULT;
            return 0;
        }
        case CMD_SUSFS_IS_SUS_SU_READY: {
            int ready = 1;
            if (copy_to_user(uarg, &ready, sizeof(ready)))
                return -EFAULT;
            return 0;
        }
#endif

        case CMD_SUSFS_SHOW_VERSION:
            if (copy_to_user(uarg, SUSFS_VERSION, sizeof(SUSFS_VERSION)))
                return -EFAULT;
            return 0;

        case CMD_SUSFS_SHOW_VARIANT:
            if (copy_to_user(uarg, SUSFS_VARIANT, sizeof(SUSFS_VARIANT)))
                return -EFAULT;
            return 0;

        case CMD_SUSFS_SHOW_ENABLED_FEATURES: {
            unsigned long features = 0;
#ifdef CONFIG_KSU_SUSFS_SUS_PATH
            features |= 1UL << 0;
#endif
#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT
            features |= 1UL << 1;
#endif
#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT
            features |= 1UL << 2;
#endif
#ifdef CONFIG_KSU_SUSFS_SPOOF_UNAME
            features |= 1UL << 3;
#endif
#ifdef CONFIG_KSU_SUSFS_ENABLE_LOG
            features |= 1UL << 4;
#endif
#ifdef CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG
            features |= 1UL << 5;
#endif
#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT
            features |= 1UL << 6;
#endif
            if (copy_to_user(uarg, &features, sizeof(features)))
                return -EFAULT;
            return 0;
        }

        default:
            return -EINVAL;
        }
    }

    if (magic2 == KSU_INSTALL_MAGIC2)
        return ksu_supercall_reboot_handler(arg);

    return -EINVAL;
}
#endif
"""

text = replace_block(
    text,
    "#ifdef CONFIG_KSU_SUSFS\nint ksu_handle_sys_reboot",
    "static int do_nuke_ext4_sysfs",
    new_dispatch + "\n",
)
DISPATCH.write_text(text)
log("[OK] replaced ksu_handle_sys_reboot() with SUSFS v1.5.5-compatible dispatch")

if FD_C.exists():
    fd = FD_C.read_text(errors="ignore")
    if "struct mount *mnt;" in fd:
        fd = fd.replace("struct mount *mnt;", "struct mount __maybe_unused *mnt;", 1)
        FD_C.write_text(fd)
        log("[OK] marked fs/proc/fd.c mnt as __maybe_unused")
    elif "struct mount __maybe_unused *mnt;" in fd:
        log("[OK] fs/proc/fd.c mnt already marked __maybe_unused")
    else:
        log("[INFO] no plain 'struct mount *mnt;' found in fs/proc/fd.c")
else:
    log("[WARN] fs/proc/fd.c missing")

if DEFCONFIG.exists():
    cfg = DEFCONFIG.read_text(errors="ignore")
    cfg2 = re.sub(r"^CONFIG_KSU_SUSFS_SUS_MAP=y\n", "# CONFIG_KSU_SUSFS_SUS_MAP is not set\n", cfg, flags=re.M)
    if cfg2 != cfg:
        DEFCONFIG.write_text(cfg2)
        log("[OK] disabled CONFIG_KSU_SUSFS_SUS_MAP for v1.5.5 API compatibility")
    else:
        log("[INFO] CONFIG_KSU_SUSFS_SUS_MAP=y not present or already disabled")
else:
    log("[WARN] defconfig missing; skipped SUS_MAP disable")

log("[DONE] SukiSU dispatch/SUSFS v1.5.5 compatibility fixes applied")
