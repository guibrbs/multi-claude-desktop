#!/bin/bash -p
PATH=/usr/bin:/bin:/usr/sbin:/sbin
export PATH
# claude-recolor-icon.sh <hue-degrees> <output.icns>
#
#   blue 212 · green 142 · red 0 · orange 30 · yellow 55
#   teal 175 · purple 275 · pink 320
#
# Regenerates a coloured Claude icon master from the stock icon.
#
# Depends only on macOS system tooling: iconutil, sips, and swift (Xcode command
# line tools). The previous version needed python3 + PIL + numpy, which broke
# twice -- once when Homebrew moved to python 3.14 and once when the OS upgrade
# left miniconda without them -- silently disabling icon generation. Nothing
# here comes from Homebrew or pip.

set -euo pipefail

HUE="${1:-}"; OUT="${2:-}"
if [ -z "$HUE" ] || [ -z "$OUT" ]; then
    printf 'usage: claude-recolor-icon.sh HUE OUTPUT.icns\n' >&2
    exit 2
fi
[[ "$HUE" =~ ^[0-9]{1,3}$ ]] && [ "$((10#$HUE))" -le 359 ] || {
    echo 'error: hue must be an integer from 0 to 359' >&2
    exit 2
}
umask 077

SRC="/Applications/Claude.app/Contents/Resources/electron.icns"
SWIFT_SRC="$(dirname "$0")/claude-recolor-icon.swift"

[ -f "$SRC" ]       || { echo "error: $SRC not found" >&2; exit 1; }
[ -f "$SWIFT_SRC" ] || { echo "error: $SWIFT_SRC not found" >&2; exit 1; }
command -v swift    >/dev/null || { echo "error: swift not found (install Xcode command line tools: xcode-select --install)" >&2; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

iconutil --convert iconset --output "$TMP/src.iconset" "$SRC"

MASTER="$TMP/src.iconset/icon_512x512@2x.png"
[ -f "$MASTER" ] || MASTER="$TMP/src.iconset/icon_512x512.png"
[ -f "$MASTER" ] || { echo "error: no large icon found in $SRC" >&2; exit 1; }

swift "$SWIFT_SRC" "$MASTER" "$TMP/recoloured.png" "$HUE"

mkdir -p "$TMP/out.iconset"
# sips for the downscales: also system tooling, no third-party imaging stack.
for spec in "16 icon_16x16" "32 icon_16x16@2x" "32 icon_32x32" "64 icon_32x32@2x" \
            "128 icon_128x128" "256 icon_128x128@2x" "256 icon_256x256" \
            "512 icon_256x256@2x" "512 icon_512x512" "1024 icon_512x512@2x"; do
    size="${spec%% *}"; name="${spec#* }"
    sips -z "$size" "$size" "$TMP/recoloured.png" --out "$TMP/out.iconset/$name.png" >/dev/null 2>&1
done

mkdir -p "$(dirname "$OUT")"
iconutil --convert icns --output "$OUT" "$TMP/out.iconset"
echo "  wrote $OUT ($(du -h "$OUT" | cut -f1))"
echo "  install it, then rebuild:  claude-apps-refresh.sh"
