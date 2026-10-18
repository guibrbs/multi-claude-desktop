#!/bin/bash -p
PATH=/usr/bin:/bin:/usr/sbin:/sbin
export PATH
# Internal worker; caller retains the same lock as application publication.
set -uo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/claude-instances-common.sh"
ci_load_config || exit 1
[ "$#" -ge 4 ] || { ci_error 'checkpoint worker requires native helpers'; exit 1; }
CI_TX_HELPER="$1"; checkpoint_helper="$2"; operation="$3"; selected="$4"
shift 4
for helper in "$CI_TX_HELPER" "$checkpoint_helper"; do
    [ -f "$helper" ] && [ -x "$helper" ] && [ ! -L "$helper" ] && [ -O "$helper" ] || { ci_error 'invalid checkpoint helper'; exit 1; }
done
"$CI_TX_HELPER" locked "$CI_APPS" || exit 1
case "$operation:$#" in create:0|verify:1) ;; *) ci_error 'invalid checkpoint worker operation'; exit 1 ;; esac
idx=""
for i in "${!names[@]}"; do
    [ "$(ci_lower "${names[$i]}")" != "$(ci_lower "$selected")" ] || idx="$i"
done
[ -n "$idx" ] || { ci_error 'unknown instance'; exit 1; }
app="$(ci_app_path "${names[$idx]}")"
ci_verify_one "$app" "$idx" || exit 1
version="$(ci_version "$app")" && [ -n "$version" ] || { ci_error 'cannot determine app version'; exit 1; }
# Hash a NUL-delimited tuple, never shell-parse app metadata or a manifest.
# Bind to the actual app's critical bytes as well as config identity and paths.
app_hashes="$(/usr/bin/shasum -a 256 "$app/Contents/Info.plist" "$app/Contents/MacOS/Claude" "$app/Contents/MacOS/launcher" "$app/Contents/_CodeSignature/CodeResources")" || exit 1
binding="$(printf '%s\0' "MCD_BINDING_1" "${names[$idx]}" "${ids[$idx]}" "${dirs[$idx]}" "${code_dirs[$idx]}" "$version" "$app_hashes" | /usr/bin/shasum -a 256)" || exit 1
binding="${binding%% *}"
[[ "$binding" =~ ^[0-9a-f]{64}$ ]] || { ci_error 'invalid profile binding'; exit 1; }
checkpoint_root="$HOME/Library/Application Support/Multi Claude Desktop/Checkpoints"
umask 077
ci_prepare_private_directory "$checkpoint_root" || exit 1
if [ "$operation" = verify ]; then
    "$checkpoint_helper" verify "$checkpoint_root" "$1" "$binding"
    exit $?
fi
desktop="${dirs[$idx]}"; code="${code_dirs[$idx]}"
for kind in desktop code; do
    if [ "$kind" = desktop ]; then path="$desktop"; else path="$code"; fi
    [ -d "$path" ] && [ ! -L "$path" ] && [ "$(ci_canonical_dir "$path")" = "$path" ] && ci_safe_data_dir "$path" "$kind" || { ci_error 'both existing profile directories must be safe; no empty substitute is created'; exit 1; }
done
checkpoint_id="$(/usr/bin/uuidgen | LC_ALL=C tr '[:upper:]' '[:lower:]')" || exit 1
[[ "$checkpoint_id" =~ ^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$ ]] || exit 1
observation="$(mktemp -d "$checkpoint_root/.observation.XXXXXXXX")" || exit 1
trap 'rm -rf "$observation"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
idle() {
    local path rc probe expected_probe
    # Quit all configured apps and stock Claude. The source may be shared by a
    # stock/default instance. A process inspection error is never "stopped".
    ci_require_stopped "$CI_SRC" || return 1
    for i in "${!names[@]}"; do ci_require_stopped "$(ci_app_path "${names[$i]}")" || return 1; done
    ci_require_desktop_idle || return 1
    # A sandbox/permission failure may look exactly like "no matches". First
    # require visibility of a file held open by this very shell (no account data).
    printf 'observation capability probe\n' >"$observation/probe" || return 1
    exec 8<"$observation/probe" || return 1
    /usr/sbin/lsof -nP -a -p "$$" -F p -- "$observation/probe" >"$observation/open" 2>"$observation/errors"; rc=$?
    exec 8<&-
    probe="$(/bin/cat "$observation/open")" || return 1
    # Darwin emits the matching file descriptor even when only -F p was asked
    # for. Require both our PID and the specific descriptor we held open.
    expected_probe="$(printf 'p%s\nf8' "$$")"
    [ "$rc" -eq 0 ] && [ "$probe" = "$expected_probe" ] && [ ! -s "$observation/errors" ] || { ci_error 'open-file observer could not see its own probe; refusing an uncertain backup'; return 1; }
    # lsof includes CLI/editor/background users of both roots, not only Claude
    # Desktop. Empty output + exit 1 + no diagnostics is its no-match result.
    # Never print captured file paths/process details to a log.
    for path in "$desktop" "$code"; do
        /usr/sbin/lsof -nP -F p +D "$path" >"$observation/open" 2>"$observation/errors"; rc=$?
        [ "$rc" -eq 1 ] && [ ! -s "$observation/open" ] && [ ! -s "$observation/errors" ] || { ci_error 'profile has open handles or open-file observation is uncertain; close Claude, CLI and editors first'; return 1; }
    done
}
idle || exit 1
printf 'Preparing checkpoint %s; pending directories are never accepted as published checkpoints.\n' "$checkpoint_id"
"$checkpoint_helper" prepare "$checkpoint_root" "$checkpoint_id" "$binding" "$desktop" "$code" || exit 1
idle || exit 1
# Recheck the app binding under the cooperating rebuild lock. A changed source
# is rejected by the native commit's full content and metadata observations.
ci_verify_one "$app" "$idx" || exit 1
current_hashes="$(/usr/bin/shasum -a 256 "$app/Contents/Info.plist" "$app/Contents/MacOS/Claude" "$app/Contents/MacOS/launcher" "$app/Contents/_CodeSignature/CodeResources")" || exit 1
[ "$current_hashes" = "$app_hashes" ] || { ci_error 'app changed during checkpoint preparation'; exit 1; }
"$checkpoint_helper" commit "$checkpoint_root" "$checkpoint_id" "$binding" "$desktop" "$code"
exit $?
