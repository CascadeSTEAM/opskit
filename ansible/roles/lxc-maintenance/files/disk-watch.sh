#!/bin/bash
# Disk-space watchdog for LXC guests (ansible lxc-maintenance role).
# Checks the root filesystem and logs state; exits 2 on critical (%), 1 on
# warning threshold. Failures surface in journald/journalctl + e-mail if the
# deployment configures Unattended-Upgrade mail.

set -u

TARGET="${1:-/}"
WARN="${DISK_WATCH_WARN:-80}"
CRIT="${DISK_WATCH_CRIT:-90}"

# Get used% for the target mount: parse "Use%" column from df -P output line.
read -r used_pct avail avail_k <<<"$(df -P "$TARGET" | awk 'NR==2 {gsub("%","",$5); print $5, $4, $4}')"

logger -t disk-watch "filesystem $TARGET used ${used_pct}% (warn=${WARN} crit=${CRIT}) avail=${avail_k}k"

if [ "${used_pct:-100}" -ge "$CRIT" ]; then
    logger -t disk-watch -p user.err "CRITICAL: $TARGET at ${used_pct}% (>=${CRIT}%) — drive space low"
    exit 2
fi

if [ "${used_pct:-100}" -ge "$WARN" ]; then
    logger -t disk-watch -p user.warn "WARNING: $TARGET at ${used_pct}% (>=${WARN}%)"
    exit 1
fi

exit 0