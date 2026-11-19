#!/bin/zsh
# usage (from the package root):  zsh install.sh
B=$HOME/css_project; SRC=$(cd "$(dirname "$0")" && pwd)/scripts
mkdir -p $B/scripts $B/data $B/synthseg $B/work $B/review $B/results
if ls $B/scripts/*.py >/dev/null 2>&1; then
  BK=$B/scripts/backup_$(date +%Y%m%d_%H%M); mkdir -p $BK; cp $B/scripts/*.py $B/scripts/*.sh $BK/ 2>/dev/null
  echo "old scripts backed up to $BK"
fi
# v4.18.3: copy to a temporary name, then rename - a batch that is running keeps reading its old file
# (cp over a running zsh script changes it under the shell's feet)
for f in $SRC/*.py $SRC/*.sh $SRC/*.html $SRC/*.js $SRC/BUILD; do   # BUILD: commit id (v5.1); *.html / *.js: reviewer page + 3-D viewer (v5.14-gui fix: were never installed)
  t=$B/scripts/.$(basename $f).new; cp $f $t && chmod +x $t && mv -f $t $B/scripts/$(basename $f) || { echo "install FAILED at $f"; exit 1; }
done
# v5.14: experimental unified candidate score (package + CLI + manifest) -> $B/unified_score (test outputs not copied)
( cd "$SRC/.." && tar cf - --exclude output --exclude __pycache__ unified_score ) | ( cd $B && tar xf - ) || { echo "install FAILED at unified_score"; exit 1; }
# v5.14-gui: the synthetic robustness suite that the app's Unified tab runs (synthetic scenes only; never part of the cohort)
mkdir -p "$B/tests" && cp "$SRC/../tests/uscore_synth.py" "$SRC/../tests/uscore_synth_columns.json" "$SRC/../tests/check_uscore_seeds.py" "$B/tests/" \
  || { echo "install FAILED at tests/uscore_*"; exit 1; }
# v5.14-gui build stamp: a git archive has BUILD filled in (export-subst). Installed from a source checkout, BUILD still holds the
# placeholder: write the real commit, date and branch so every manifest, report and test record names the actual build.
cp "$SRC/VERSION" "$B/scripts/VERSION" 2>/dev/null || true
if grep -q 'Format' "$B/scripts/BUILD" 2>/dev/null; then
  if git -C "$SRC" rev-parse HEAD >/dev/null 2>&1; then
    D=""; git -C "$SRC" diff --quiet HEAD -- . 2>/dev/null || D=" +uncommitted changes"
    echo "$(git -C "$SRC" rev-parse HEAD) $(git -C "$SRC" log -1 --format=%cs) $(git -C "$SRC" rev-parse --abbrev-ref HEAD)$D (installed from source checkout)" > "$B/scripts/BUILD"
  else
    echo "unknown (installed from a copy without git metadata)" > "$B/scripts/BUILD"
  fi
fi
echo "build: $(cat $B/scripts/BUILD)"
grep -q 'css_project/scripts' ~/.zshrc || echo 'export PATH="$HOME/css_project/scripts:$PATH"' >> ~/.zshrc
echo "installed to $B/scripts  - open a new Terminal window"
