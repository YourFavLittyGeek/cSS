#!/bin/bash
# cSS Experimental launcher (test release candidate). Kept SEPARATE from the production app:
#   project folder  ~/cSS_experimental  (CSS_EXP_BASE overrides; the production ~/css_project is refused)
#   port 8810 (production uses 8800), bundle id research.css.pipeline.experimental
# On start it installs the pipeline shipped in this bundle into the project when the bundle's build differs (old scripts backed up),
# copies the app code, finds conda env "css" + FreeSurfer, starts the app server and opens its window. No network access is needed.
CSS_BASE="${CSS_EXP_BASE:-$HOME/cSS_experimental}"; export CSS_BASE
RES="$(cd "$(dirname "$0")/../Resources" && pwd)"
say_err() { /usr/bin/osascript -e "display dialog \"$1\" with title \"cSS Experimental\" buttons {\"OK\"} default button 1 with icon caution" >/dev/null 2>&1; }
# v5.14.2-rc2: canonical path of a folder that may not exist yet (deepest existing ancestor resolved with pwd -P, symlinks included)
canon() { local p="$1" rest=""; case "$p" in "~"*) p="$HOME${p#\~}";; /*) ;; *) p="$PWD/$p";; esac
  while [ ! -d "$p" ]; do rest="/$(basename "$p")$rest"; p="$(dirname "$p")"; done; echo "$(cd "$p" && pwd -P)$rest"; }
PROD_C="$(canon "$HOME/css_project")"; BASE_C="$(canon "$CSS_BASE")"
for R in "$PROD_C" "$HOME/css_project" $(echo "${CSS_PROTECTED_PATHS:-}" | tr ':' ' '); do
  R="$(canon "$R")"
  case "$BASE_C/" in "$R/"*) say_err "Refused: the experimental project folder ($CSS_BASE) is the production project or inside it ($R). Unset CSS_EXP_BASE."; exit 1;; esac
  case "$R/" in "$BASE_C/"*) say_err "Refused: the experimental project folder ($CSS_BASE) contains the production project ($R). Choose a separate folder."; exit 1;; esac
done
case "$BASE_C/" in *"/Library/Mobile Documents/"*|*"/Library/CloudStorage/"*|*"/Dropbox"*|*"/Google Drive"*|*"/OneDrive"*|*"/iCloud"*) say_err "Refused: the experimental project folder is inside a cloud-synced folder."; exit 1;; esac
export CSS_BASE="$BASE_C" CSS_EXPERIMENTAL=1
mkdir -p "$CSS_BASE/app" "$CSS_BASE/app_data/logs" "$CSS_BASE/scripts" "$CSS_BASE/data" "$CSS_BASE/work" "$CSS_BASE/review" "$CSS_BASE/results"
LOG="$CSS_BASE/app_data/logs/launcher.log"; echo "=== $(date) build $(cat "$RES/pipeline/scripts/BUILD" 2>/dev/null)" >> "$LOG"
# pipeline: install when the bundle's BUILD differs from the project's (backup of the old scripts kept)
if ! cmp -s "$RES/pipeline/scripts/BUILD" "$CSS_BASE/scripts/BUILD"; then
  if ls "$CSS_BASE/scripts/"*.py >/dev/null 2>&1; then BK="$CSS_BASE/scripts/backup_$(date +%Y%m%d_%H%M%S)"; mkdir -p "$BK"; cp "$CSS_BASE/scripts/"*.* "$BK/" 2>/dev/null; fi
  for f in "$RES/pipeline/scripts/"*; do t="$CSS_BASE/scripts/.$(basename "$f").new"; cp "$f" "$t" && chmod +x "$t" && mv -f "$t" "$CSS_BASE/scripts/$(basename "$f")" || { say_err "Pipeline install failed at $(basename "$f")"; exit 1; }; done
  rm -rf "$CSS_BASE/unified_score.new" && cp -R "$RES/pipeline/unified_score" "$CSS_BASE/unified_score.new" && { [ -d "$CSS_BASE/unified_score" ] && mv "$CSS_BASE/unified_score" "$CSS_BASE/unified_score.old_$(date +%Y%m%d_%H%M%S)"; mv "$CSS_BASE/unified_score.new" "$CSS_BASE/unified_score"; }
  mkdir -p "$CSS_BASE/tests" && cp "$RES/pipeline/tests/"* "$CSS_BASE/tests/" 2>/dev/null
  echo "pipeline installed: $(cat "$CSS_BASE/scripts/BUILD")" >> "$LOG"
fi
rsync -a --delete --exclude __pycache__ "$RES/app/" "$CSS_BASE/app/" >> "$LOG" 2>&1 || cp -R "$RES/app/." "$CSS_BASE/app/"
for c in "$HOME/miniforge3" "$HOME/mambaforge" "$HOME/miniconda3" "$HOME/anaconda3" "/opt/homebrew/Caskroom/miniforge/base" "/opt/miniconda3" "/opt/anaconda3"; do
  if [ -f "$c/etc/profile.d/conda.sh" ]; then source "$c/etc/profile.d/conda.sh"; break; fi
done
command -v conda >/dev/null 2>&1 || { say_err "Conda (Miniforge) was not found."; exit 1; }
conda activate css >> "$LOG" 2>&1 || { say_err "The conda environment 'css' was not found."; exit 1; }
FSH=$(python -c "import json;print(json.load(open('$CSS_BASE/app_data/settings.json')).get('freesurfer_home',''))" 2>/dev/null)
[ -z "$FSH" ] && FSH=$(ls -d /Applications/freesurfer/*/ /Applications/freesurfer 2>/dev/null | sort | tail -1)
FSH="${FSH%/}"
if [ -n "$FSH" ] && [ -f "$FSH/SetUpFreeSurfer.sh" ]; then export FREESURFER_HOME="$FSH"; source "$FSH/SetUpFreeSurfer.sh" >> "$LOG" 2>&1; fi
export SUBJECTS_DIR="$CSS_BASE/subjects" CSS_SUBJECTS_DIR="$CSS_BASE/subjects"
export PYTHONPATH="$CSS_BASE/app/guard${PYTHONPATH:+:$PYTHONPATH}"      # production write guard in every Python process (css_writeguard)
nohup python "$CSS_BASE/app/css_app.py" --port 8810 >> "$LOG" 2>&1 &
exit 0
