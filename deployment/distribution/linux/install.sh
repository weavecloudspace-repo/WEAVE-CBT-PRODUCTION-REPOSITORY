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

destination=/usr/local/share/weave-cbt/assets
if [ -f "$destination/release-manifest.json" ]; then
    existing_channel=$(manifest_channel "$destination/release-manifest.json")
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
