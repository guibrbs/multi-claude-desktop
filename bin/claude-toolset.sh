#!/bin/bash -p
PATH=/usr/bin:/bin:/usr/sbin:/sbin
export PATH
# Reviewed installer entry. No downloads, account access or legacy ~/bin writes.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/claude-instances-common.sh"
umask 077
[ "$(/usr/bin/id -u)" != 0 ] || { ci_error 'do not run with sudo'; exit 1; }
ci_prepare_private_directory "$CI_ICONS"
compile_dir="$(mktemp -d "$CI_ICONS/.toolset-native.XXXXXXXX")"
trap 'rm -rf "$compile_dir"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
bin_dir="$(cd -- "${BASH_SOURCE[0]%/*}" && pwd -P)"
native="$bin_dir/claude-toolset.c"
[ -f "$native" ] && [ ! -L "$native" ] && [ -O "$native" ] || { ci_error 'reviewed installer source required'; exit 1; }
/bin/cp "$native" "$compile_dir/source.c"
/bin/chmod 600 "$compile_dir/source.c"
source_sha="$(/usr/bin/shasum -a 256 "$compile_dir/source.c")"
source_sha="${source_sha%% *}"
[[ "$source_sha" =~ ^[a-f0-9]{64}$ ]] || exit 1
/usr/bin/env -i HOME="$HOME" PATH="$PATH" LANG=C TMPDIR="$compile_dir" /usr/bin/clang -std=c11 -Wall -Wextra -Werror -O2 -mmacosx-version-min=12.0 \
    "-DMCD_TOOLSET_SOURCE_SHA=\"$source_sha\"" "$compile_dir/source.c" -o "$compile_dir/helper"
"$compile_dir/helper" "$@"
