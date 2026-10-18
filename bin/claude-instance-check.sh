#!/bin/bash -p
PATH=/usr/bin:/bin:/usr/sbin:/sbin
export PATH
# Exit 0=observed healthy, 1=collision, 2=cannot determine state.
set -uo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/claude-instances-common.sh"
snapshot="$(ps -Aww -o pid=,comm=)" || { ci_error 'cannot enumerate processes'; exit 2; }
pids=(); apps=(); profiles=()
while IFS= read -r line; do
    read -r pid executable <<<"$line"
    case "$executable" in */Contents/MacOS/Claude) ;; *) continue ;; esac
    profile="$(ci_profile_of_pid "$pid")" || { ci_error 'cannot determine a running profile'; exit 2; }
    app="${executable%/Contents/MacOS/Claude}"; app="${app##*/}"
    pids+=("$pid"); apps+=("$app"); profiles+=("$profile")
done <<<"$snapshot"
if [ "${#pids[@]}" -eq 0 ]; then printf 'No Claude instances are running (process enumeration succeeded).\n'; exit 0; fi
rc=0
printf '%-8s %-24s %s\n' PID APP PROFILE
for i in "${!pids[@]}"; do
    mark=""
    for j in "${!pids[@]}"; do
        if [ "$i" != "$j" ] && [ "${profiles[$i]}" = "${profiles[$j]}" ]; then mark=' <-- COLLISION'; rc=1; fi
    done
    printf '%-8s %-24s %s%s\n' "${pids[$i]}" "${apps[$i]}" "${profiles[$i]}" "$mark"
done
if [ "$rc" -eq 0 ]; then printf 'OK: observed profiles are distinct.\n'; else ci_error 'shared profile: quit all but one of each colliding instance'; fi
exit "$rc"
