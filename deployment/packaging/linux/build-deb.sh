#!/usr/bin/env bash
set -Eeuo pipefail
CLI="$1"; GUI="$2"; CHANNEL="$3"; VERSION="$4"; IMAGE="$5"; ROOT="$6"
mkdir -p "$ROOT/DEBIAN" "$ROOT/usr/bin" "$ROOT/usr/share/applications" "$ROOT/usr/share/icons/hicolor/112x71/apps" "$ROOT/usr/share/weave-cbt/assets" dist
install -m 0755 "$CLI" "$ROOT/usr/bin/weave"
install -m 0755 "$GUI" "$ROOT/usr/bin/weave-cbt-desktop"
cp deployment/compose.yaml "$ROOT/usr/share/weave-cbt/assets/compose.yaml"
cp -a deployment/nginx deployment/bootstrap "$ROOT/usr/share/weave-cbt/assets/"
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
Depends: libc6, libstdc++6
Description: WEAVE CBT desktop interface and CLI manager
 GUI for the WEAVE CBT local server runtime.
EOF
dpkg-deb --build --root-owner-group "$ROOT" "dist/weave-cbt-desktop-$CHANNEL-linux-amd64.deb"
