#!/usr/bin/env bash
set -Eeuo pipefail
BLUE=$(printf '\033[1;34m'); GREEN=$(printf '\033[1;32m'); RED=$(printf '\033[1;31m'); RESET=$(printf '\033[0m')
if [ ! -t 1 ] || [ -n "$(printenv NO_COLOR 2>/dev/null || true)" ]; then BLUE=''; GREEN=''; RED=''; RESET=''; fi
echo "$BLUE WEAVE CBT CLI MANAGER SETUP $RESET"
if [ "$(id -u)" -ne 0 ]; then
    echo "$RED [ERROR] Run: sudo ./install.sh $RESET" >&2
    exit 1
fi
HERE=$(cd "$(dirname "$0")" && pwd)
if [ ! -f "$HERE/weave" ] || [ ! -f "$HERE/assets/compose.yaml" ] || [ ! -f "$HERE/assets/release-manifest.json" ]; then
    echo "$RED [ERROR] Incomplete installation archive. $RESET" >&2
    exit 1
fi
install -d -m 0755 /usr/local/bin /usr/local/share/weave-cbt/assets
install -m 0755 "$HERE/weave" /usr/local/bin/weave
cp -a "$HERE/assets/." /usr/local/share/weave-cbt/assets/
chmod -R a+rX /usr/local/share/weave-cbt/assets
/usr/local/bin/weave --help > /dev/null
echo "$GREEN [OK] WEAVE Manager installed and available in PATH. $RESET"
echo "NEXT STEP: Run the following command from any directory:"
echo "    sudo weave install"
