#!/bin/bash -p
PATH=/usr/bin:/bin:/usr/sbin:/sbin
export PATH
# Serialize cleanup with rebuilds and profile checkpoints before any mutation.
set -uo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/claude-instances-common.sh"
ci_load_config || exit 1
umask 077
ci_prepare_private_directory "$CI_ICONS" || exit 1
[ ! -e "$CI_ICONS/.refresh-lock" ] && [ ! -L "$CI_ICONS/.refresh-lock" ] || { ci_error 'legacy refresh lock exists; inspect it first'; exit 1; }
compile_dir="$(mktemp -d "$CI_ICONS/.cache-native.XXXXXXXX")" || exit 1
trap 'rm -rf "$compile_dir"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
bin_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)" || exit 1
[ -f "$bin_dir/claude-transaction.c" ] && [ ! -L "$bin_dir/claude-transaction.c" ] || { ci_error 'install the complete bin/claude-* set'; exit 1; }
/usr/bin/clang -std=c11 -Wall -Wextra -Werror -O2 -mmacosx-version-min=12.0 "$bin_dir/claude-transaction.c" -o "$compile_dir/helper" || { ci_error 'native helper compilation failed; Xcode Command Line Tools are required'; exit 1; }
"$compile_dir/helper" run "$CI_APPS" "$bin_dir/claude-cache-worker.sh" "$@"
exit $?
