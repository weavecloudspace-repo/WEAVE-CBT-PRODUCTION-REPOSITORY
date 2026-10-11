#!/usr/bin/env bash
set -Eeuo pipefail

BLUE=$(printf '\033[1;34m')
GREEN=$(printf '\033[1;32m')
RED=$(printf '\033[1;31m')
RESET=$(printf '\033[0m')
if [ ! -t 1 ] || [ "${NO_COLOR+x}" = x ]; then
    BLUE=''; GREEN=''; RED=''; RESET=''
fi

printf '%s\n' "${BLUE}WEAVE CBT CLI MANAGER SETUP${RESET}"

if [ "$(id -u)" -ne 0 ]; then
    printf '%s\n' "${RED}[ERROR] Run sudo ./install.sh${RESET}" >&2
    exit 1
fi

HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [ ! -f "$HERE/weave" ] || [ ! -f "$HERE/assets/compose.yaml" ] || [ ! -f "$HERE/assets/release-manifest.json" ]; then
    printf '%s\n' "${RED}[ERROR] Release package is incomplete.${RESET}" >&2
    exit 1
fi

manifest_channel() {
    awk -F '"' '/^[[:space:]]*"channel"[[:space:]]*:/ {print $4; exit}' "$1"
}

incoming_channel=$(manifest_channel "$HERE/assets/release-manifest.json")
if [ "$incoming_channel" != production ] && [ "$incoming_channel" != staging ]; then
    echo "[ERROR] Release package contains an invalid channel." >&2
    exit 1
fi

# The DEB owns /usr/bin/weave and /usr/share/weave-cbt. The standalone
# archive owns /usr/local/bin/weave and /usr/local/share/weave-cbt.
# A mixed install could silently dispatch the wrong CLI or release image.
if command -v dpkg-query >/dev/null 2>&1 &&
   [ "$(dpkg-query -W -f='${Status}' weave-cbt-desktop 2>/dev/null || true)" = 'install ok installed' ]; then
    echo '[ERROR] Refusing to mix Linux DEB and standalone CBT manager installations. Remove the DEB manager explicitly before installing the standalone CLI. Existing CBT exam data is not touched.' >&2
    exit 1
fi
if [ -e /usr/bin/weave ] || [ -e /usr/share/weave-cbt/assets/release-manifest.json ]; then
    echo '[ERROR] A system-level WEAVE CLI/package was detected. Refusing standalone installation until an administrator resolves the mixed package ownership.' >&2
    exit 1
fi

destination=/usr/local/share/weave-cbt/assets
if [ -f "$destination/release-manifest.json" ]; then
    existing_channel=$(manifest_channel "$destination/release-manifest.json")
    if [ "$existing_channel" != production ] && [ "$existing_channel" != staging ]; then
        echo '[ERROR] Existing manager manifest has an invalid release channel; refusing replacement.' >&2
        exit 1
    fi
    if [ "$incoming_channel" != "$existing_channel" ]; then
        printf '%s\n' "${RED}[ERROR] Installed manager channel is $existing_channel; refusing a $incoming_channel override.${RESET}" >&2
        exit 1
    fi
fi

# Reject a broken executable before modifying the installed manager.
"$HERE/weave" --help >/dev/null

install -d -m 0755 /usr/local/bin "$destination"
# A running Linux executable cannot safely be overwritten in place.
# Stage in the same filesystem and then rename atomically.
staged=/usr/local/bin/.weave-setup-$$
trap 'rm -f -- "$staged"' EXIT
install -m 0755 "$HERE/weave" "$staged"
mv -f -- "$staged" /usr/local/bin/weave
cp -a "$HERE/assets/." "$destination/"
chmod -R a+rX "$destination"
/usr/local/bin/weave --help >/dev/null

printf '%s\n' "${GREEN}[OK] WEAVE Manager installed and available globally.${RESET}"
printf '%s\n' "NEXT STEP: Run the following command from any directory:"
printf '%s\n' "    sudo weave install"
