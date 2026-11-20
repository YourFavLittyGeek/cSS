#!/bin/bash
# Build the experimental cSS app bundle (test release candidate) from this source tree. Works on macOS and Linux (bash, cp, zip/ditto).
# usage: bash tools/build_experimental_app.sh [OUT_DIR]      -> OUT_DIR/Percival.app + OUT_DIR/Percival_<version>.zip + BUILD_INFO.txt
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; OUT="${1:-$ROOT/dist}"; APP="$OUT/Percival.app"
VER="$(head -1 "$ROOT/scripts/VERSION")"; SHORT="$(echo "$VER" | awk '{print $1}')"
COMMIT="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"; BR="$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
DIRTY=""; git -C "$ROOT" diff --quiet HEAD -- . 2>/dev/null || DIRTY=" +uncommitted changes"
[ -n "$(git -C "$ROOT" ls-files --others --exclude-standard -- app scripts unified_score tests tools 2>/dev/null)" ] && DIRTY=" +uncommitted changes"
rm -rf "$APP"; mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/app" "$APP/Contents/Resources/pipeline/scripts" "$APP/Contents/Resources/pipeline/tests"
cp "$ROOT/app/mac_experimental/launcher.sh" "$APP/Contents/MacOS/Percival"; chmod +x "$APP/Contents/MacOS/Percival"
cp "$ROOT/app/mac_experimental/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"     # Percival P (dark); the Dock icon follows the theme at run time
cat > "$APP/Contents/Info.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
 <key>CFBundleName</key><string>Percival</string><key>CFBundleDisplayName</key><string>Percival</string>
 <key>CFBundleIdentifier</key><string>research.css.pipeline.experimental</string>
 <key>CFBundleVersion</key><string>$SHORT</string><key>CFBundleShortVersionString</key><string>$SHORT</string>
 <key>CFBundleExecutable</key><string>Percival</string><key>CFBundlePackageType</key><string>APPL</string>
 <key>LSMinimumSystemVersion</key><string>12.0</string><key>NSHighResolutionCapable</key><true/><key>CFBundleIconFile</key><string>AppIcon</string>
 <key>LSArchitecturePriority</key><array><string>arm64</string></array>
</dict></plist>
PL
for f in "$ROOT"/app/*.py "$ROOT"/app/*.html "$ROOT"/app/*.js "$ROOT"/app/*.png "$ROOT"/app/*.json "$ROOT"/app/README.md; do [ -f "$f" ] && cp "$f" "$APP/Contents/Resources/app/"; done
mkdir -p "$APP/Contents/Resources/app/guard" && cp "$ROOT"/app/guard/*.py "$APP/Contents/Resources/app/guard/"     # rc2: production write guard (required)
[ -f "$APP/Contents/Resources/app/guard/css_writeguard.py" ] && [ -f "$APP/Contents/Resources/app/guard/sitecustomize.py" ] || { echo "BUILD FAILED: write guard missing"; exit 1; }
for f in "$ROOT"/scripts/*.py "$ROOT"/scripts/*.sh "$ROOT"/scripts/*.html "$ROOT"/scripts/*.js "$ROOT"/scripts/VERSION; do cp "$f" "$APP/Contents/Resources/pipeline/scripts/"; done
echo "$COMMIT $(date +%Y-%m-%d) $BR$DIRTY (experimental app build $SHORT)" > "$APP/Contents/Resources/pipeline/scripts/BUILD"
( cd "$ROOT" && tar cf - --exclude output --exclude __pycache__ unified_score ) | ( cd "$APP/Contents/Resources/pipeline" && tar xf - )
cp "$ROOT/tests/uscore_synth.py" "$ROOT/tests/uscore_synth_columns.json" "$ROOT/tests/check_uscore_seeds.py" "$APP/Contents/Resources/pipeline/tests/"
for g in "$ROOT"/docs/gui_v514/rc5/INSTALL_AND_USER_GUIDE_RC5.md "$ROOT"/docs/gui_v514/rc4/TEST_REPORT_RC4.md "$ROOT"/docs/gui_v514/rc3/PRODUCTION_PARITY_RC3.md; do [ -f "$g" ] && cp "$g" "$OUT/"; done
cp "$ROOT/app/mac_experimental/uninstall_experimental.sh" "$OUT/" 2>/dev/null || true
find "$APP" -name __pycache__ -prune -exec rm -rf {} +
ZIP="$OUT/Percival_${SHORT}.zip"; rm -f "$ZIP"
if command -v ditto >/dev/null 2>&1; then ( cd "$OUT" && ditto -c -k --keepParent "Percival.app" "$(basename "$ZIP")" ); else ( cd "$OUT" && zip -qr "$(basename "$ZIP")" "Percival.app" ); fi
{ echo "app:      Percival.app  ($VER)"; echo "source:   $COMMIT  branch $BR$DIRTY"; echo "built:    $(date '+%Y-%m-%d %H:%M %Z') on $(uname -sm)"
  echo "zip sha256: $( (shasum -a 256 "$ZIP" 2>/dev/null || sha256sum "$ZIP") | awk '{print $1}')"
  echo "files:    $(find "$APP" -type f | wc -l | tr -d ' ')"; } > "$OUT/BUILD_INFO.txt"
cat "$OUT/BUILD_INFO.txt"
