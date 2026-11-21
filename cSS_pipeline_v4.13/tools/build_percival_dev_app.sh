#!/bin/bash
# Build the Percival DEVELOPMENT app (branch feature/unified-score-ml-integration) as a self-contained zip:
#   Percival Dev.app (app + pipeline scripts + Unified Score package + Unified engine + image model) + INSTALL.md + user guide + environment.yml
# Builds from COMMITTED files only (git archive of HEAD) and leaves out every clinical-derived data file (cohort manifests, reconciliation
# tables, adjudication tables, test outputs). Separate from tools/build_experimental_app.sh (the RC build), which is unchanged.
# usage: bash tools/build_percival_dev_app.sh [OUT_DIR]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; OUT="${1:-$ROOT/../dist}"; mkdir -p "$OUT"; OUT="$(cd "$OUT" && pwd)"
COMMIT="$(git -C "$ROOT" rev-parse HEAD)"; SHORT="${COMMIT:0:7}"; BR="$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)"
DIRTY=""; git -C "$ROOT" diff --quiet HEAD -- app scripts unified_score unified_engine tests tools || DIRTY=" (working tree has uncommitted changes - NOT included)"
VER="v5.18-dev"; NAME="Percival_${VER}_${SHORT}"; STAGE="$(mktemp -d)"; SRC="$STAGE/src"; PKG="$STAGE/$NAME"; APP="$PKG/Percival Dev.app"
mkdir -p "$SRC" && git -C "$ROOT" archive HEAD . | tar -x -C "$SRC"          # committed files of the package root only
R="$APP/Contents/Resources"; mkdir -p "$APP/Contents/MacOS" "$R/app/guard" "$R/pipeline/scripts" "$R/pipeline/tests"
cp "$SRC/app/mac_percival/launcher.sh" "$APP/Contents/MacOS/Percival Dev"; chmod +x "$APP/Contents/MacOS/Percival Dev"
cp "$SRC/app/mac_experimental/AppIcon.icns" "$R/AppIcon.icns"
cat > "$APP/Contents/Info.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
 <key>CFBundleName</key><string>Percival Dev</string><key>CFBundleDisplayName</key><string>Percival Dev</string>
 <key>CFBundleIdentifier</key><string>research.css.pipeline.percival-dev</string>
 <key>CFBundleVersion</key><string>${VER#v}</string><key>CFBundleShortVersionString</key><string>${VER#v}</string>
 <key>CFBundleExecutable</key><string>Percival Dev</string><key>CFBundlePackageType</key><string>APPL</string>
 <key>LSMinimumSystemVersion</key><string>12.0</string><key>NSHighResolutionCapable</key><true/><key>CFBundleIconFile</key><string>AppIcon</string>
 <key>LSArchitecturePriority</key><array><string>arm64</string></array>
</dict></plist>
PL
for f in "$SRC"/app/*.py "$SRC"/app/*.html "$SRC"/app/*.js "$SRC"/app/*.png "$SRC"/app/*.json "$SRC"/app/README.md; do [ -f "$f" ] && cp "$f" "$R/app/"; done
cp "$SRC"/app/guard/*.py "$R/app/guard/"
[ -f "$R/app/guard/css_writeguard.py" ] && [ -f "$R/app/guard/sitecustomize.py" ] || { echo "BUILD FAILED: write guard missing"; exit 1; }
for f in "$SRC"/scripts/*.py "$SRC"/scripts/*.sh "$SRC"/scripts/*.html "$SRC"/scripts/*.js "$SRC"/scripts/VERSION; do cp "$f" "$R/pipeline/scripts/"; done
echo "$COMMIT $(git -C "$ROOT" log -1 --format=%cs) $BR (Percival development build $VER)" > "$R/pipeline/scripts/BUILD"
# Unified Score: code only - no cohort manifests (study codes + split roles), no reconciliation tables, no test outputs
mkdir -p "$R/pipeline/unified_score"; cp -R "$SRC/unified_score/uscore" "$SRC/unified_score/run_unified.py" "$R/pipeline/unified_score/"
mkdir -p "$R/pipeline/unified_engine"; ( cd "$SRC/unified_engine" && tar cf - --exclude __pycache__ uengine models tools run_engine.py run_imaging.py ) | ( cd "$R/pipeline/unified_engine" && tar xf - )
cp "$SRC/tests/uscore_synth.py" "$SRC/tests/uscore_synth_columns.json" "$SRC/tests/check_uscore_seeds.py" "$R/pipeline/tests/"
cp "$SRC/docs/percival_app/INSTALL_AND_USER_GUIDE.md" "$PKG/USER_GUIDE.md"; cp "$SRC/environment.yml" "$PKG/"
cp "$SRC/app/mac_percival/INSTALL.md" "$PKG/INSTALL.md"; cp "$SRC/app/mac_percival/uninstall_percival_dev.sh" "$PKG/"; chmod +x "$PKG/uninstall_percival_dev.sh"
find "$PKG" -name __pycache__ -prune -exec rm -rf {} + ; find "$PKG" -name .DS_Store -delete
# leak check: no clinical-derived data files, no images, no licence
BAD="$(find "$PKG" \( -name 'cohort_manifest*' -o -name 'reconciliation*.csv' -o -name 'adjudication*' -o -name 'scoreability_from_records*' -o -name '*.nii' -o -name '*.nii.gz' -o -name '*.mgz' -o -name '*.dcm' -o -name 'license.txt' -o -name 'names.csv' -o -name 'identity_vault*' \) -print)"
[ -z "$BAD" ] || { echo "BUILD FAILED: data files in the package:"; echo "$BAD"; exit 1; }
ZIP="$OUT/$NAME.zip"; rm -f "$ZIP"; ( cd "$STAGE" && ditto -c -k --keepParent "$NAME" "$ZIP" )
{ echo "package:  $NAME.zip  (Percival Dev.app, $VER)"; echo "source:   $COMMIT  branch $BR$DIRTY"
  echo "built:    $(date '+%Y-%m-%d %H:%M %Z') on $(uname -sm)"; echo "zip sha256: $(shasum -a 256 "$ZIP" | awk '{print $1}')"
  echo "files:    $(find "$PKG" -type f | wc -l | tr -d ' ')"; echo "contains: app, pipeline scripts, Unified Score code, Unified engine + synthetic image model; NO clinical data"; } > "$OUT/${NAME}_BUILD_INFO.txt"
rm -rf "$STAGE"; cat "$OUT/${NAME}_BUILD_INFO.txt"
