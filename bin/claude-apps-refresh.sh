#!/bin/bash -p
PATH=/usr/bin:/bin:/usr/sbin:/sbin
export PATH
# Build verified, separate GUI profiles. The source app is never modified.
set -uo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/claude-instances-common.sh"
ci_load_config || exit 1

list() {
    local i keys pair
    for i in "${!names[@]}"; do
        keys=""; local pairs=()
        IFS=';' read -ra pairs <<<"${envs[$i]}"
        for pair in "${pairs[@]-}"; do [ -z "$pair" ] || keys="${keys}${keys:+, }${pair%%=*}"; done
        printf '%s | %s | %s | hue=%s | env keys: %s\n' "${names[$i]}" "${ids[$i]}" "${dirs[$i]}" "${hues[$i]}" "${keys:--}"
    done
}
verify() {
    local i rc=0
    for i in "${!names[@]}"; do
        if ci_verify_one "$(ci_app_path "${names[$i]}")" "$i"; then
            printf 'Claude %s: launcher/signature/content-record checks passed (ad-hoc copy; user-writable record; account isolation not established)\n' "${names[$i]}"
        else
            printf 'Claude %s: FAILED -- rebuild required\n' "${names[$i]}" >&2; rc=1
        fi
    done
    return "$rc"
}
case "${1:-all}" in
    --status|-s) ci_status; exit $? ;;
    --list|-l) list; exit $? ;;
esac
umask 077
ci_prepare_private_directory "$CI_ICONS" || exit 1
[ ! -e "$CI_ICONS/.refresh-lock" ] && [ ! -L "$CI_ICONS/.refresh-lock" ] || { ci_error 'legacy refresh lock exists; inspect the old rebuild before removing it'; exit 1; }
compile_dir="$(mktemp -d "$CI_ICONS/.native.XXXXXXXX")" || exit 1
trap 'rm -rf "$compile_dir"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
ci_compile_integrity "$compile_dir" || exit 1
case "${1:-all}" in --verify|-v) [ "$#" -eq 1 ] || exit 2; verify; exit $? ;; esac
bin_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)" || exit 1
[ -f "$bin_dir/claude-transaction.c" ] && [ ! -L "$bin_dir/claude-transaction.c" ] || { ci_error 'missing native transaction source; install the complete bin/claude-* set'; exit 1; }
/usr/bin/clang -std=c11 -Wall -Wextra -Werror -O2 -mmacosx-version-min=12.0 "$bin_dir/claude-transaction.c" -o "$compile_dir/helper" || { ci_error 'native helper compilation failed; Xcode Command Line Tools are required'; exit 1; }
"$compile_dir/helper" run "$CI_APPS" "$bin_dir/claude-build-worker.sh" "$@"
exit $?
