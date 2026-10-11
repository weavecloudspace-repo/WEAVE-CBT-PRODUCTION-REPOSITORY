#!/usr/bin/env bash
set -Eeuo pipefail
CLI="$1"; GUI="$2"; CHANNEL="$3"; VERSION="$4"; IMAGE="$5"; ROOT="$6"
case "$CHANNEL" in
  staging|production) ;;
  *) echo "Unsupported CBT release channel: $CHANNEL" >&2; exit 1 ;;
esac
mkdir -p "$ROOT/DEBIAN" "$ROOT/usr/bin" "$ROOT/usr/share/applications" "$ROOT/usr/share/icons/hicolor/112x71/apps" "$ROOT/usr/share/weave-cbt/assets" dist
install -m 0755 "$CLI" "$ROOT/usr/bin/weave"
install -m 0755 "$GUI" "$ROOT/usr/bin/weave-cbt-desktop"
cp deployment/compose.yaml "$ROOT/usr/share/weave-cbt/assets/compose.yaml"
cp -a deployment/nginx deployment/bootstrap deployment/certificates "$ROOT/usr/share/weave-cbt/assets/"
python deployment/distribution/make_manifest.py --channel "$CHANNEL" --image "$IMAGE" --version "$VERSION" --destination "$ROOT/usr/share/weave-cbt/assets/release-manifest.json"
install -m 0644 deployment/gui/resources/weave-logo-blue.png "$ROOT/usr/share/icons/hicolor/112x71/apps/weave-cbt-desktop.png"
cat > "$ROOT/usr/share/applications/weave-cbt-desktop.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=WEAVE CBT Desktop Manager
Comment=Install and manage your school's CBT server
Exec=/usr/bin/weave-cbt-desktop
Icon=weave-cbt-desktop
Terminal=false
Categories=Education;System;
EOF
cat > "$ROOT/DEBIAN/control" <<EOF
Package: weave-cbt-desktop
Version: $VERSION
Section: education
Priority: optional
Architecture: amd64
Maintainer: WEAVE CBT <support@weavecloudspace.com>
Depends: libc6, libstdc++6, libegl1, libgl1, libopengl0, libxkbcommon-x11-0, libxcb-cursor0, libxcb-icccm4, libxcb-keysyms1, libxcb-xinerama0
Description: WEAVE CBT desktop interface and CLI manager
 GUI for the WEAVE CBT local server runtime.
EOF
cat > "$ROOT/DEBIAN/preinst" <<'EOF'
#!/bin/sh
set -eu
# No automatic removal of school-owned CLI managers or runtime data.
# A DEB update must never overwrite a standalone manager's binaries/assets.
if [ -e /usr/local/bin/weave ] || [ -e /usr/local/share/weave-cbt/assets/release-manifest.json ]; then
    echo '[WEAVE CBT] Refusing mixed standalone and DEB manager installation; an administrator must resolve package ownership first.' >&2
    exit 1
fi
installed=/usr/share/weave-cbt/assets/release-manifest.json
if [ -f "$installed" ]; then
    existing=$(awk -F '"' '/^[[:space:]]*"channel"[[:space:]]*:/ {print $4; exit}' "$installed")
    if [ "$existing" != '__INCOMING_CHANNEL__' ]; then
        echo "[WEAVE CBT] Existing DEB channel is '$existing'; refusing an automatic channel change." >&2
        exit 1
    fi
fi
exit 0
EOF
sed -i "s/__INCOMING_CHANNEL__/$CHANNEL/g" "$ROOT/DEBIAN/preinst"
chmod 0755 "$ROOT/DEBIAN/preinst"
dpkg-deb --build --root-owner-group "$ROOT" "dist/weave-cbt-desktop-$CHANNEL-linux-amd64.deb"
