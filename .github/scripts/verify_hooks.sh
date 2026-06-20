#!/usr/bin/env bash
# verify_hooks.sh — ReSukiSU manual-hook verification suite
#
# Usage:
#   ./verify_hooks.sh                    # run all checks, exit non-zero on any failure
#   ./verify_hooks.sh --strict           # also fail on warnings (recommended for CI)
#   ./verify_hooks.sh --quiet            # only print summary
#   ./verify_hooks.sh --json out.json    # also emit machine-readable report
#
# Exit codes:
#   0  - all required hooks present
#   1  - one or more REQUIRED hooks missing  (build is UNSAFE to flash)
#   2  - WARNINGS only (with --strict)
#   3  - script usage error

set -u   # no -e: we want to keep going and collect all failures

# ─────────── CLI ───────────
STRICT=0
QUIET=0
JSON_OUT=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --strict)  STRICT=1; shift ;;
        --quiet)   QUIET=1;  shift ;;
        --json)    JSON_OUT="${2:-}"; shift 2 ;;
        -h|--help)
            sed -n '2,15p' "$0"; exit 0 ;;
        *) echo "Unknown arg: $1" >&2; exit 3 ;;
    esac
done

# ─────────── colors ───────────
if [[ -t 1 ]] && [[ -z "${NO_COLOR:-}" ]]; then
    R=$'\e[31m'; G=$'\e[32m'; Y=$'\e[33m'; B=$'\e[34m'; C=$'\e[36m'; D=$'\e[2m'; X=$'\e[0m'
else
    R=""; G=""; Y=""; B=""; C=""; D=""; X=""
fi

# ─────────── counters & JSON state ───────────
PASS=0; FAIL=0; WARN=0; SKIP=0
declare -a RESULTS   # "STATUS|CATEGORY|NAME|DETAIL"

log()  { [[ $QUIET -eq 0 ]] && echo "$@"; }
hdr()  { [[ $QUIET -eq 0 ]] && printf "\n${B}═══ %s ═══${X}\n" "$1"; }

record() {
    local status="$1" cat="$2" name="$3" detail="${4:-}"
    RESULTS+=("${status}|${cat}|${name}|${detail}")
    case "$status" in
        PASS) PASS=$((PASS+1));
              [[ $QUIET -eq 0 ]] && printf "  ${G}✔${X} %-45s ${D}%s${X}\n" "$name" "$detail" ;;
        FAIL) FAIL=$((FAIL+1));
              printf "  ${R}✘ %-45s %s${X}\n" "$name" "$detail" ;;
        WARN) WARN=$((WARN+1));
              [[ $QUIET -eq 0 ]] && printf "  ${Y}⚠ %-45s %s${X}\n" "$name" "$detail" ;;
        SKIP) SKIP=$((SKIP+1));
              [[ $QUIET -eq 0 ]] && printf "  ${D}○ %-45s %s${X}\n" "$name" "$detail" ;;
    esac
}

# count occurrences of regex in file. echoes number; 0 if file missing.
count_in() {
    local file="$1" regex="$2"
    [[ -f "$file" ]] || { echo 0; return; }
    grep -cE "$regex" "$file" 2>/dev/null || echo 0
}

# require: count >= min, status PASS/FAIL
require() {
    local cat="$1" name="$2" file="$3" regex="$4" min="${5:-1}" hint="${6:-}"
    if [[ ! -f "$file" ]]; then
        record FAIL "$cat" "$name" "file missing: $file"
        return
    fi
    local n; n=$(count_in "$file" "$regex")
    if [[ "$n" -ge "$min" ]]; then
        record PASS "$cat" "$name" "$n match(es) in $file"
    else
        record FAIL "$cat" "$name" "found=$n, need≥$min in $file ${hint:+— $hint}"
    fi
}

# expect: count >= min, status PASS/WARN (non-blocking)
expect() {
    local cat="$1" name="$2" file="$3" regex="$4" min="${5:-1}" hint="${6:-}"
    if [[ ! -f "$file" ]]; then
        record SKIP "$cat" "$name" "n/a (file missing)"
        return
    fi
    local n; n=$(count_in "$file" "$regex")
    if [[ "$n" -ge "$min" ]]; then
        record PASS "$cat" "$name" "$n match(es) in $file"
    else
        record WARN "$cat" "$name" "found=$n, expected≥$min ${hint:+— $hint}"
    fi
}

# forbid: regex must NOT match (used to catch leftover unstubbed `static`)
forbid() {
    local cat="$1" name="$2" file="$3" regex="$4" hint="${5:-}"
    if [[ ! -f "$file" ]]; then
        record SKIP "$cat" "$name" "n/a (file missing)"
        return
    fi
    local n; n=$(count_in "$file" "$regex")
    if [[ "$n" -eq 0 ]]; then
        record PASS "$cat" "$name" "no forbidden pattern in $file"
    else
        record FAIL "$cat" "$name" "found $n forbidden match(es) in $file ${hint:+— $hint}"
    fi
}

# ─────────── pre-flight ───────────
log "${C}ReSukiSU hook verification — $(date -u +%Y-%m-%dT%H:%M:%SZ)${X}"
log "${D}srctree: $(pwd)${X}"

if [[ ! -f "Makefile" ]] || ! grep -q "KERNELRELEASE" Makefile 2>/dev/null; then
    echo "${R}ERROR: current directory does not look like a kernel source tree${X}" >&2
    exit 3
fi

KVER=$(make kernelversion 2>/dev/null || echo "unknown")
log "${D}kernel version: ${KVER}${X}"

# ═══════════════════════════════════════════════════════════════
hdr "1. defconfig"
# ═══════════════════════════════════════════════════════════════
DEFCONFIG_GLOB=(arch/arm64/configs/*defconfig)
DEFCONFIG_HIT=0
for dc in "${DEFCONFIG_GLOB[@]}"; do
    [[ -f "$dc" ]] || continue
    if grep -q "^CONFIG_KSU=y" "$dc" && grep -q "^CONFIG_KSU_MANUAL_HOOK=y" "$dc"; then
        record PASS "defconfig" "KSU manual hook enabled" "$(basename "$dc")"
        DEFCONFIG_HIT=1
        # KPROBES should be off (manual hook conflicts with kprobes mode)
        if grep -qE "^CONFIG_KSU_(KPROBE_HOOKS|KPROBES_HOOK|KPROBES_HOOKS|WITH_KPROBES)=y" "$dc"; then
            record FAIL "defconfig" "KPROBES mode disabled" "$(basename "$dc"): kprobes still =y (conflicts with manual)"
        else
            record PASS "defconfig" "KPROBES mode disabled" "$(basename "$dc")"
        fi
        # KALLSYMS_ALL fingerprint check
        if grep -q "^CONFIG_KALLSYMS_ALL=y" "$dc"; then
            record WARN "defconfig" "KALLSYMS_ALL leak" "$(basename "$dc"): =y leaks kernel pointers"
        else
            record PASS "defconfig" "KALLSYMS_ALL fingerprint" "$(basename "$dc"): not =y"
        fi
    fi
done
[[ $DEFCONFIG_HIT -eq 0 ]] && record FAIL "defconfig" "any KSU-enabled defconfig" "none of arch/arm64/configs/*defconfig has CONFIG_KSU=y"

# ═══════════════════════════════════════════════════════════════
hdr "2. fs/exec.c — execve family"
# ═══════════════════════════════════════════════════════════════
require "exec" "ksu_handle_execveat call" \
        "fs/exec.c" "ksu_handle_execveat" 1 \
        "primary 64-bit syscall entry must be gated"

expect  "exec" "execveat prototype present" \
        "fs/exec.c" "extern int ksu_handle_execveat" 1

# 32-bit ABI: either compat hook is patched, OR compat routes through do_execveat_common
if [[ -f fs/exec.c ]]; then
    compat_direct=$(grep -cE "ksu_handle_execve\(&filename" fs/exec.c || echo 0)
    compat_routed=$(grep -cE "do_execveat_common\b" fs/exec.c || echo 0)
    if   [[ $compat_direct -gt 0 ]]; then
        record PASS "exec" "32-bit execve hooked" "direct compat hook present"
    elif [[ $compat_routed -gt 0 ]]; then
        record PASS "exec" "32-bit execve hooked" "routed via do_execveat_common (already hooked)"
    else
        record FAIL "exec" "32-bit execve hooked" "no compat hook AND no do_execveat_common routing"
    fi
fi

# ═══════════════════════════════════════════════════════════════
hdr "3. fs/open.c — faccessat family"
# ═══════════════════════════════════════════════════════════════
require "open" "ksu_handle_faccessat call" \
        "fs/open.c" "ksu_handle_faccessat" 1

expect  "open" "faccessat prototype present" \
        "fs/open.c" "extern int ksu_handle_faccessat" 1

# faccessat2 only on kernel >= 5.8 — non-blocking
if grep -q "faccessat2" fs/open.c 2>/dev/null; then
    expect "open" "faccessat2 hooked (kernel ≥5.8)" \
           "fs/open.c" "ksu_handle_faccessat\(&dfd, &filename, &mode, &flags\)" 1 \
           "kernel exposes faccessat2 but hook missing — modern detectors leak"
else
    record SKIP "open" "faccessat2 hooked" "syscall not present in this kernel (pre-5.8)"
fi

# ═══════════════════════════════════════════════════════════════
hdr "4. fs/stat.c — stat family"
# ═══════════════════════════════════════════════════════════════
require "stat" "ksu_handle_stat call (newfstatat/statx)" \
        "fs/stat.c" "ksu_handle_stat" 1

expect  "stat" "stat prototype present" \
        "fs/stat.c" "extern int ksu_handle_stat" 1

require "stat" "newfstat return hook" \
        "fs/stat.c" "ksu_handle_newfstat_ret" 1 \
        "needed to spoof fstat() results on su-managed fds"

# fstat64 only on archs with __ARCH_WANT_STAT64
if grep -q "SYSCALL_DEFINE2(fstat64" fs/stat.c 2>/dev/null; then
    require "stat" "fstat64 return hook (32-bit compat)" \
            "fs/stat.c" "ksu_handle_fstat64_ret" 1
else
    record SKIP "stat" "fstat64 return hook" "fstat64 not present"
fi

# statx — modern detection vector
if grep -q "SYSCALL_DEFINE5(statx" fs/stat.c 2>/dev/null; then
    expect "stat" "statx syscall hooked" \
           "fs/stat.c" "ksu_handle_stat\(&dfd, &filename, &flags\)" 1 \
           "Play Integrity 2024+ uses statx — strongly recommended"
else
    record SKIP "stat" "statx syscall hooked" "syscall not present (pre-4.11)"
fi

# ═══════════════════════════════════════════════════════════════
hdr "5. kernel/reboot.c — sys_reboot"
# ═══════════════════════════════════════════════════════════════
require "reboot" "ksu_handle_sys_reboot call" \
        "kernel/reboot.c" "ksu_handle_sys_reboot" 1

expect  "reboot" "sys_reboot prototype present" \
        "kernel/reboot.c" "extern int ksu_handle_sys_reboot" 1

# ═══════════════════════════════════════════════════════════════
hdr "6. SELinux exports"
# ═══════════════════════════════════════════════════════════════
require "selinux" "sel_handle_status_ops exported" \
        "security/selinux/selinuxfs.c" "EXPORT_SYMBOL_GPL\(sel_handle_status_ops\)" 1

require "selinux" "write_op exported" \
        "security/selinux/selinuxfs.c" "EXPORT_SYMBOL_GPL\(write_op\)" 1

# Static keyword must be GONE from these symbols (otherwise export is a no-op)
forbid "selinux" "sel_handle_status_ops not static" \
       "security/selinux/selinuxfs.c" \
       "static[[:space:]]+(const[[:space:]]+)?struct[[:space:]]+file_operations[[:space:]]+sel_handle_status_ops" \
       "leftover 'static' will silently mask the EXPORT"

forbid "selinux" "write_op not static" \
       "security/selinux/selinuxfs.c" \
       "static[[:space:]]+ssize_t[[:space:]]*\\([[:space:]]*\\*[[:space:]]*(const[[:space:]]+)?write_op" \
       "leftover 'static' will silently mask the EXPORT"

# Anti-fabrication check: must NOT have a fake write_op definition
forbid "selinux" "no fabricated write_op" \
       "security/selinux/selinuxfs.c" \
       "ssize_t[[:space:]]*\\([[:space:]]*\\*[[:space:]]*write_op[[:space:]]*\\)[[:space:]]*\\([^)]*\\)[[:space:]]*=[[:space:]]*sel_write_load" \
       "fabricated single-pointer write_op breaks SELinux state spoofing"

# 6.6+ specific symbols
if [[ $(echo "$KVER" | cut -d. -f1) -ge 6 && $(echo "$KVER" | cut -d. -f2) -ge 6 ]]; then
    require "selinux" "security_dump_masked_av exported (6.6+)" \
            "security/selinux/ss/services.c" \
            "EXPORT_SYMBOL_GPL\(security_dump_masked_av\)" 1
    require "selinux" "context_struct_compute_av exported (6.6+)" \
            "security/selinux/ss/services.c" \
            "EXPORT_SYMBOL_GPL\(context_struct_compute_av\)" 1
fi

# ═══════════════════════════════════════════════════════════════
hdr "7. ReSukiSU tree integrity"
# ═══════════════════════════════════════════════════════════════
if [[ -d KernelSU ]] || [[ -d drivers/kernelsu ]] || [[ -d drivers/ksu ]]; then
    record PASS "tree" "ReSukiSU source tree present" "$(ls -d KernelSU drivers/kernelsu drivers/ksu 2>/dev/null | head -1)"
else
    record FAIL "tree" "ReSukiSU source tree present" "setup.sh not run? no KernelSU/ dir found"
fi

# linux/ksu.h must exist in include paths
KSU_H=$(find . -path ./out -prune -o -name "ksu.h" -print 2>/dev/null | head -1)
if [[ -n "$KSU_H" ]]; then
    record PASS "tree" "ksu.h header reachable" "$KSU_H"
else
    record WARN "tree" "ksu.h header reachable" "not found — may rely on inline extern declarations"
fi

# ═══════════════════════════════════════════════════════════════
hdr "8. Header inclusion sanity"
# ═══════════════════════════════════════════════════════════════
for f in fs/exec.c fs/open.c fs/stat.c kernel/reboot.c; do
    if [[ ! -f "$f" ]]; then
        record SKIP "headers" "$f export.h" "file missing"
        continue
    fi
    # files that EXPORT_SYMBOL need linux/export.h (or via linux/module.h)
    :
done

# Files we added EXPORT_SYMBOL to MUST include export.h
for f in security/selinux/selinuxfs.c; do
    if grep -qE "EXPORT_SYMBOL(_GPL)?\(" "$f" 2>/dev/null; then
        if grep -qE "#include[[:space:]]*<linux/(export|module)\.h>" "$f"; then
            record PASS "headers" "$f has export header" ""
        else
            record FAIL "headers" "$f has export header" "EXPORT_SYMBOL used but no <linux/export.h>"
        fi
    fi
done

# ═══════════════════════════════════════════════════════════════
hdr "9. CONFIG_KSU_MANUAL_HOOK guard hygiene"
# ═══════════════════════════════════════════════════════════════
# Every ksu_handle_* call we injected must be under #ifdef CONFIG_KSU_MANUAL_HOOK
for f in fs/exec.c fs/open.c fs/stat.c kernel/reboot.c; do
    [[ -f "$f" ]] || continue
    # quick heuristic: count ksu_handle_ calls vs CONFIG_KSU_MANUAL_HOOK ifdef blocks
    calls=$(grep -cE "ksu_handle_" "$f")
    guards=$(grep -cE "#ifdef CONFIG_KSU_MANUAL_HOOK|#if defined\(CONFIG_KSU_MANUAL_HOOK\)" "$f")
    if [[ $calls -gt 0 && $guards -eq 0 ]]; then
        record FAIL "guards" "$f hooks guarded" "calls=$calls guards=0 (unguarded → build fails without manual hook)"
    elif [[ $calls -gt $((guards * 3)) ]]; then
        record WARN "guards" "$f hooks guarded" "calls=$calls guards=$guards (ratio suspicious — review)"
    else
        record PASS "guards" "$f hooks guarded" "calls=$calls guards=$guards"
    fi
done

# ═══════════════════════════════════════════════════════════════
hdr "10. Backup presence (audit trail)"
# ═══════════════════════════════════════════════════════════════
BACKUP_LATEST=$(ls -td .resukisu_backup/*/ 2>/dev/null | head -1)
if [[ -n "$BACKUP_LATEST" ]]; then
    nfiles=$(find "$BACKUP_LATEST" -type f | wc -l)
    record PASS "audit" "backup snapshot present" "$BACKUP_LATEST ($nfiles files)"
else
    record WARN "audit" "backup snapshot present" "no .resukisu_backup/ — rollback not available"
fi

# ═══════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════
TOTAL=$((PASS + FAIL + WARN + SKIP))
log ""
log "${B}════════════════ Summary ════════════════${X}"
printf "  ${G}PASS${X}: %-3d  ${R}FAIL${X}: %-3d  ${Y}WARN${X}: %-3d  ${D}SKIP${X}: %-3d  (total %d)\n" \
       "$PASS" "$FAIL" "$WARN" "$SKIP" "$TOTAL"
log ""

# JSON report
if [[ -n "$JSON_OUT" ]]; then
    {
        echo "{"
        echo "  \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\","
        echo "  \"kernel_version\": \"$KVER\","
        echo "  \"summary\": { \"pass\": $PASS, \"fail\": $FAIL, \"warn\": $WARN, \"skip\": $SKIP, \"total\": $TOTAL },"
        echo "  \"results\": ["
        for i in "${!RESULTS[@]}"; do
            IFS='|' read -r st cat name det <<< "${RESULTS[$i]}"
            comma=","; [[ $i -eq $((${#RESULTS[@]} - 1)) ]] && comma=""
            det_esc=${det//\\/\\\\}; det_esc=${det_esc//\"/\\\"}
            printf '    {"status":"%s","category":"%s","name":"%s","detail":"%s"}%s\n' \
                   "$st" "$cat" "$name" "$det_esc" "$comma"
        done
        echo "  ]"
        echo "}"
    } > "$JSON_OUT"
    log "${C}JSON report → $JSON_OUT${X}"
fi

# Verdict
if [[ $FAIL -gt 0 ]]; then
    echo "${R}✘ VERDICT: UNSAFE — $FAIL required hook(s) missing. Do NOT flash.${X}" >&2
    exit 1
elif [[ $WARN -gt 0 && $STRICT -eq 1 ]]; then
    echo "${Y}⚠ VERDICT: WARNINGS in --strict mode — review before flashing.${X}" >&2
    exit 2
elif [[ $WARN -gt 0 ]]; then
    echo "${Y}⚠ VERDICT: OK with warnings — review recommended.${X}"
    exit 0
else
    echo "${G}✔ VERDICT: All required hooks present. Safe to build & flash.${X}"
    exit 0
fi
