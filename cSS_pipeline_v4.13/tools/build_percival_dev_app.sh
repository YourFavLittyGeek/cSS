#!/bin/bash
# Build the Percival DEVELOPMENT app (branch feature/unified-score-ml-integration) as a self-contained zip:
#   Percival Dev.app (app + pipeline scripts + Unified Score package + Unified engine + image model) + INSTALL.md + user guide + environment.yml
# Builds from COMMITTED files only (git archive of HEAD) and leaves out every clinical-derived data file (cohort manifests, reconciliation
# tables, adjudication tables, test outputs). Separate from tools/build_experimental_app.sh (the RC build), which is unchanged.
# v5.23: + "Percival Demo.app" (same bundle, MODE=demo: synthetic demo project ~/Percival_demo, port 8831), first-run installer of a separate
# conda env "percival" (percival_environment.yml = environment.yml + pywebview + dcm2niix; the "css" env is never changed), ad-hoc signature.
# --worktree builds from the CURRENT WORKING TREE (tracked + untracked, .gitignore respected, nothing committed): the tree object id is
# recorded in BUILD and BUILD_INFO so the exact sources stay identifiable.
# usage: bash tools/build_percival_dev_app.sh [--worktree] [OUT_DIR]
set -euo pipefail
WT=""; [ "${1:-}" = "--worktree" ] && { WT=1; shift; }
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; OUT="${1:-$ROOT/../dist}"; mkdir -p "$OUT"; OUT="$(cd "$OUT" && pwd)"
COMMIT="$(git -C "$ROOT" rev-parse HEAD)"; SHORT="${COMMIT:0:7}"; BR="$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)"
DIRTY=""; git -C "$ROOT" diff --quiet HEAD -- app scripts unified_score unified_engine tests tools || DIRTY=" (working tree has uncommitted changes - NOT included)"
if [ -n "$WT" ]; then                      # snapshot of the working tree as a git tree object (temporary index; real index / branch untouched)
  REPO="$(git -C "$ROOT" rev-parse --show-toplevel)"; SUB="$(git -C "$ROOT" rev-parse --show-prefix)"; SUB="${SUB%/}"; IDX="$(mktemp -u)"
  GIT_INDEX_FILE="$IDX" git -C "$REPO" read-tree HEAD && GIT_INDEX_FILE="$IDX" git -C "$REPO" add -A -- "$SUB" ":!**/.DS_Store" ":!**/__pycache__"
  TREE="$(GIT_INDEX_FILE="$IDX" git -C "$REPO" write-tree)"; rm -f "$IDX"; SHORT="wt${TREE:0:7}"
  DIRTY=" + working tree (uncommitted changes INCLUDED; tree $TREE)"
fi
VER="v5.23-dev"; NAME="Percival_${VER}_${SHORT}"; STAGE="$(mktemp -d)"; SRC="$STAGE/src"; PKG="$STAGE/$NAME"; APP="$PKG/Percival Dev.app"
if [ -n "$WT" ]; then mkdir -p "$SRC" && git -C "$REPO" archive "$TREE:$SUB" | tar -x -C "$SRC"
else mkdir -p "$SRC" && git -C "$ROOT" archive HEAD . | tar -x -C "$SRC"; fi        # committed files of the package root only
R="$APP/Contents/Resources"; mkdir -p "$APP/Contents/MacOS" "$R/app/guard" "$R/pipeline/scripts" "$R/pipeline/tests"
cp "$SRC/app/mac_percival/launcher.sh" "$APP/Contents/MacOS/Percival Dev"; chmod +x "$APP/Contents/MacOS/Percival Dev"
cp "$SRC/app/mac_percival/first_run_setup.sh" "$R/first_run_setup.sh"; chmod +x "$R/first_run_setup.sh"; echo dev > "$R/MODE"; cp "$SRC/app/mac_percival/make_demo.py" "$R/make_demo.py"
{ sed -e 's/^name: css$/name: percival/' "$SRC/environment.yml"; printf '  - dcm2niix           # DICOM import\n  - pip\n  - pip:\n      - pywebview        # the app window\n'; } > "$R/percival_environment.yml"
grep -q "^name: percival$" "$R/percival_environment.yml" || { echo "BUILD FAILED: environment name"; exit 1; }
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
echo "$COMMIT${TREE:+ tree $TREE} $(date +%F) $BR (Percival development build $VER)" > "$R/pipeline/scripts/BUILD"
# Unified Score: code only - no cohort manifests (study codes + split roles), no reconciliation tables, no test outputs
mkdir -p "$R/pipeline/unified_score"; cp -R "$SRC/unified_score/uscore" "$SRC/unified_score/run_unified.py" "$R/pipeline/unified_score/"
mkdir -p "$R/pipeline/unified_engine"; ( cd "$SRC/unified_engine" && tar cf - --exclude __pycache__ uengine models tools run_engine.py run_imaging.py ) | ( cd "$R/pipeline/unified_engine" && tar xf - )
cp "$SRC/tests/uscore_synth.py" "$SRC/tests/uscore_synth_columns.json" "$SRC/tests/check_uscore_seeds.py" "$R/pipeline/tests/"
cp "$SRC/docs/percival_app/INSTALL_AND_USER_GUIDE.md" "$PKG/USER_GUIDE.md"; cp "$SRC/environment.yml" "$PKG/"
cp "$SRC/app/mac_percival/INSTALL.md" "$PKG/READ ME FIRST.md"; cp "$SRC/app/mac_percival/uninstall_percival_dev.sh" "$PKG/"; chmod +x "$PKG/uninstall_percival_dev.sh"
mkdir -p "$PKG/docs"; for d in PERCIVAL_ARCHITECTURE LOCAL_AI_ARCHITECTURE IMPLEMENTATION_REPORT_v5.23 STUDY_ADMINISTRATION; do
  [ -f "$SRC/docs/percival_app/$d.md" ] && cp "$SRC/docs/percival_app/$d.md" "$PKG/docs/"; done
# the demo app: the same bundle with MODE=demo, its own name and bundle id
DEMO="$PKG/Percival Demo.app"; cp -R "$APP" "$DEMO"; echo demo > "$DEMO/Contents/Resources/MODE"
mv "$DEMO/Contents/MacOS/Percival Dev" "$DEMO/Contents/MacOS/Percival Demo"
sed -i '' -e 's/<string>Percival Dev<\/string>/<string>Percival Demo<\/string>/g' -e 's/percival-dev</percival-demo</' "$DEMO/Contents/Info.plist"
find "$PKG" -name __pycache__ -prune -exec rm -rf {} + ; find "$PKG" -name .DS_Store -delete
# leak check: no clinical-derived data files, no images, no licence
BAD="$(find "$PKG" \( -name 'cohort_manifest*' -o -name 'reconciliation*.csv' -o -name 'adjudication*' -o -name 'scoreability_from_records*' -o -name '*.nii' -o -name '*.nii.gz' -o -name '*.mgz' -o -name '*.dcm' -o -name 'license.txt' -o -name 'names.csv' -o -name 'identity_vault*' \) -print)"
[ -z "$BAD" ] || { echo "BUILD FAILED: data files in the package:"; echo "$BAD"; exit 1; }
for a in "$APP" "$DEMO"; do xattr -cr "$a"; codesign --force --deep -s - "$a" >/dev/null 2>&1 || echo "note: ad-hoc signing failed for $a"; done
ZIP="$OUT/$NAME.zip"; rm -f "$ZIP"; ( cd "$STAGE" && ditto -c -k --keepParent "$NAME" "$ZIP" )
{ echo "package:  $NAME.zip  (Percival Dev.app, $VER)"; echo "source:   $COMMIT  branch $BR$DIRTY"
  echo "built:    $(date '+%Y-%m-%d %H:%M %Z') on $(uname -sm)"; echo "zip sha256: $(shasum -a 256 "$ZIP" | awk '{print $1}')"
  echo "files:    $(find "$PKG" -type f | wc -l | tr -d ' ')"; echo "contains: Percival Dev.app + Percival Demo.app (app, pipeline scripts, Unified Score code, Unified engine incl. Percival Score engine, synthetic image model), first-run installer; NO clinical data, NO trained clinical model"; } > "$OUT/${NAME}_BUILD_INFO.txt"
rm -rf "$STAGE"; cat "$OUT/${NAME}_BUILD_INFO.txt"
