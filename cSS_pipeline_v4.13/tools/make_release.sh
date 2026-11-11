#!/bin/bash
# Build an installable update zip of the changed files since a git ref.  usage: bash tools/make_release.sh VERSION [SINCE_REF] [OUT_DIR]
# The zip holds cSS_<VERSION>_update/{scripts,tests,docs,tools}/... plus START_HERE.txt; copy its folders over ~/css_project.
set -e
R=$(cd "$(dirname "$0")/.." && pwd); V=${1:?version}; SINCE=${2:-HEAD~1}; OUT=${3:-$R/..}
cd "$R"; python tools/make_all_code.py "$V" > /dev/null
D=$(mktemp -d)/cSS_${V}_update; mkdir -p "$D"
FILES=$(git diff --name-only "$SINCE" -- scripts tests docs tools | sed "s#^$(git rev-parse --show-prefix)##")
for f in $FILES; do [ -f "$f" ] && mkdir -p "$D/$(dirname "$f")" && cp "$f" "$D/$f"; done
printf 'cSS %s update. Copy the folders over your project (scripts -> ~/css_project/scripts, tests and docs optional):\n  cp -R scripts/* ~/css_project/scripts/\nChanged files:\n%s\n' "$V" "$FILES" > "$D/START_HERE.txt"
(cd "$(dirname "$D")" && zip -qr "$OUT/cSS_${V}_update.zip" "$(basename "$D")")
echo "wrote $OUT/cSS_${V}_update.zip ($(echo "$FILES" | wc -w) files)"
