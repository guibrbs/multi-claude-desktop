#!/bin/bash -p
PATH=/usr/bin:/bin:/usr/sbin:/sbin
export PATH
# Opt-in content checkpoints. Never restores, migrates or launches an account.
set -uo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/claude-instances-common.sh"
ci_load_config || exit 1
case "${1:-}" in
    create) [ "$#" -eq 2 ] || { ci_error 'usage: claude-profile-checkpoint.sh create NAME'; exit 1; } ;;
    verify) [ "$#" -eq 3 ] || { ci_error 'usage: claude-profile-checkpoint.sh verify NAME UUID'; exit 1; } ;;
    *) ci_error 'use create NAME or verify NAME UUID; restore is deliberately unavailable'; exit 1 ;;
esac
umask 077
ci_prepare_private_directory "$CI_ICONS" || exit 1
[ ! -e "$CI_ICONS/.refresh-lock" ] && [ ! -L "$CI_ICONS/.refresh-lock" ] || { ci_error 'legacy refresh lock exists; inspect it first'; exit 1; }
compile_dir="$(mktemp -d "$CI_ICONS/.checkpoint-native.XXXXXXXX")" || exit 1
trap 'rm -rf "$compile_dir"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
ci_compile_integrity "$compile_dir" || exit 1
bin_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)" || exit 1
for native in claude-transaction claude-checkpoint; do
    [ -f "$bin_dir/$native.c" ] && [ ! -L "$bin_dir/$native.c" ] || { ci_error 'install the complete bin/claude-* set'; exit 1; }
    /usr/bin/clang -std=c11 -Wall -Wextra -Werror -O2 -mmacosx-version-min=12.0 "$bin_dir/$native.c" -o "$compile_dir/$native" || { ci_error 'native helper compilation failed; Xcode Command Line Tools are required'; exit 1; }
done
"$compile_dir/claude-transaction" run "$CI_APPS" "$bin_dir/claude-checkpoint-worker.sh" "$compile_dir/claude-checkpoint" "$@"
exit $?
