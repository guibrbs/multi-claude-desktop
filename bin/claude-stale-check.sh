#!/bin/bash -p
PATH=/usr/bin:/bin:/usr/sbin:/sbin
export PATH
# Read-only app checks; local log and notification. Never rebuilds or quits apps.
set -uo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/claude-instances-common.sh"
LOG_DIR="$HOME/Library/Logs/claude-instances"
LOG="$LOG_DIR/watchdog.log"
DELAY="${CLAUDE_STALE_CHECK_DELAY:-45}"
case "$DELAY" in ''|*[!0-9]*) ci_error 'invalid watchdog delay'; exit 2 ;; esac
ci_load_config || exit 1
[ "$DELAY" -eq 0 ] || sleep "$DELAY"
umask 077
ci_prepare_private_directory "$LOG_DIR" || exit 1
if [ -e "$LOG" ] || [ -L "$LOG" ]; then
    [ -f "$LOG" ] && [ ! -L "$LOG" ] && [ -O "$LOG" ] && [ "$(/usr/bin/stat -f '%l' "$LOG")" = 1 ] && ci_no_allow_acl "$LOG" || { ci_error 'watchdog log is not a private regular file'; exit 1; }
fi
: >> "$LOG" || exit 1
/bin/chmod 600 "$LOG" || exit 1
ci_prepare_private_directory "$CI_ICONS" || exit 1
compile_dir="$(mktemp -d "$CI_ICONS/.watch-native.XXXXXXXX")" || exit 1
trap 'rm -rf "$compile_dir"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
ci_compile_integrity "$compile_dir" || exit 1
source_version="$(ci_version "$CI_SRC")" || { ci_error 'source version unavailable'; exit 1; }
rc=0; problems=""
for i in "${!names[@]}"; do
    if [ "$#" -gt 0 ]; then
        selected=no
        for arg in "$@"; do [ "$(ci_lower "$arg")" != "$(ci_lower "${names[$i]}")" ] || selected=yes; done
        [ "$selected" = yes ] || continue
    fi
    app="$(ci_app_path "${names[$i]}")"; state=ok
    if ! ci_verify_one "$app" "$i" >/dev/null 2>&1; then
        state=BROKEN
    elif ! version="$(ci_version "$app")"; then
        state=BROKEN
    elif [ "$version" != "$source_version" ]; then
        state=STALE
    fi
    printf '%s %s: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "${names[$i]}" "$state" >> "$LOG" || exit 1
    if [ "$state" != ok ]; then problems="$problems ${names[$i]}:$state"; rc=1; fi
done
if [ "$rc" -ne 0 ]; then
    # argv avoids AppleScript interpolation of configuration-derived strings.
    /usr/bin/osascript - 'Claude instances need attention' "$problems" <<'APPLESCRIPT'
on run argv
    display notification (item 2 of argv) with title (item 1 of argv)
end run
APPLESCRIPT
fi
exit "$rc"
