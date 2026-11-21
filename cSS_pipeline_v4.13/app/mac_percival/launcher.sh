#!/bin/bash
# Percival DEVELOPMENT build launcher (branch feature/unified-score-ml-integration; v5.16-v5.18: identification, lineage, setup wizard, one import pathway, study library, export).
# Kept SEPARATE from both the production app and the Percival RC app:
#   project folder  ~/Percival_project  (PERCIVAL_BASE overrides; ~/css_project and ~/cSS_experimental are refused and write-protected)
#   port 8830 (production 8800, RC 8810), bundle id research.css.pipeline.percival-dev
# On start it installs the pipeline, Unified Score package and Unified engine shipped in this bundle into the project when the bundle's
# build differs (old scripts backed up; engine outputs in the project are never deleted), copies the app code, finds conda env "css" and
# FreeSurfer, starts the app server and opens its window. No network access is needed.
CSS_BASE="${PERCIVAL_BASE:-$HOME/Percival_project}"
RES="$(cd "$(dirname "$0")/../Resources" && pwd)"
PORT="${PERCIVAL_PORT:-8830}"
say_err() { /usr/bin/osascript -e "display dialog \"$1\" with title \"Percival (development build)\" buttons {\"OK\"} default button 1 with icon caution" >/dev/null 2>&1; echo "$1" >&2; }
canon() { local p="$1" rest=""; case "$p" in "~"*) p="$HOME${p#\~}";; /*) ;; *) p="$PWD/$p";; esac
  while [ ! -d "$p" ]; do rest="/$(basename "$p")$rest"; p="$(dirname "$p")"; done; echo "$(cd "$p" && pwd -P)$rest"; }
BASE_C="$(canon "$CSS_BASE")"
PROT="$HOME/css_project:$HOME/cSS_experimental${CSS_PROTECTED_PATHS:+:$CSS_PROTECTED_PATHS}"
for R in $(echo "$PROT" | tr ':' ' '); do
  R="$(canon "$R")"
  case "$BASE_C/" in "$R/"*) say_err "Refused: the project folder ($CSS_BASE) is a protected project (production or RC) or inside one ($R). Set PERCIVAL_BASE to a separate folder."; exit 1;; esac
  case "$R/" in "$BASE_C/"*) say_err "Refused: the project folder ($CSS_BASE) contains a protected project ($R). Choose a separate folder."; exit 1;; esac
done
case "$BASE_C/" in *"/Library/Mobile Documents/"*|*"/Library/CloudStorage/"*|*"/Dropbox"*|*"/Google Drive"*|*"/OneDrive"*|*"/iCloud"*|"$HOME/Desktop/"*|"$HOME/Documents/"*)
  say_err "Refused: the project folder is inside a cloud-synced folder (iCloud Desktop & Documents, Dropbox, Google Drive, OneDrive)."; exit 1;; esac
export CSS_BASE="$BASE_C" CSS_EXPERIMENTAL=1 CSS_PROTECTED_PATHS="$PROT"
mkdir -p "$CSS_BASE/app" "$CSS_BASE/app_data/logs" "$CSS_BASE/scripts" "$CSS_BASE/data" "$CSS_BASE/work" "$CSS_BASE/review" "$CSS_BASE/results" "$CSS_BASE/unified_engine"
LOG="$CSS_BASE/app_data/logs/launcher.log"; echo "=== $(date) build $(cat "$RES/pipeline/scripts/BUILD" 2>/dev/null)" >> "$LOG"
if ! cmp -s "$RES/pipeline/scripts/BUILD" "$CSS_BASE/scripts/BUILD"; then
  if ls "$CSS_BASE/scripts/"*.py >/dev/null 2>&1; then BK="$CSS_BASE/scripts/backup_$(date +%Y%m%d_%H%M%S)"; mkdir -p "$BK"; cp "$CSS_BASE/scripts/"*.* "$BK/" 2>/dev/null; fi
  for f in "$RES/pipeline/scripts/"*; do t="$CSS_BASE/scripts/.$(basename "$f").new"; cp "$f" "$t" && chmod +x "$t" && mv -f "$t" "$CSS_BASE/scripts/$(basename "$f")" || { say_err "Pipeline install failed at $(basename "$f")"; exit 1; }; done
  rm -rf "$CSS_BASE/unified_score.new" && cp -R "$RES/pipeline/unified_score" "$CSS_BASE/unified_score.new" && { [ -d "$CSS_BASE/unified_score" ] && mv "$CSS_BASE/unified_score" "$CSS_BASE/unified_score.old_$(date +%Y%m%d_%H%M%S)"; mv "$CSS_BASE/unified_score.new" "$CSS_BASE/unified_score"; }
  # engine code + model files only; the project's own engine outputs (shadow/, image_ml/, SYNTHETIC_BASE, ...) are left untouched (no --delete)
  rsync -a --exclude __pycache__ "$RES/pipeline/unified_engine/" "$CSS_BASE/unified_engine/" >> "$LOG" 2>&1 || { say_err "Engine install failed"; exit 1; }
  mkdir -p "$CSS_BASE/tests" && cp "$RES/pipeline/tests/"* "$CSS_BASE/tests/" 2>/dev/null
  echo "pipeline installed: $(cat "$CSS_BASE/scripts/BUILD")" >> "$LOG"
fi
rsync -a --delete --exclude __pycache__ "$RES/app/" "$CSS_BASE/app/" >> "$LOG" 2>&1 || cp -R "$RES/app/." "$CSS_BASE/app/"
for c in "$HOME/miniforge3" "$HOME/mambaforge" "$HOME/miniconda3" "$HOME/anaconda3" "/opt/homebrew/Caskroom/miniforge/base" "/opt/miniconda3" "/opt/anaconda3"; do
  if [ -f "$c/etc/profile.d/conda.sh" ]; then source "$c/etc/profile.d/conda.sh"; break; fi
done
command -v conda >/dev/null 2>&1 || { say_err "Conda (Miniforge) was not found. See INSTALL.md step 1."; exit 1; }
conda activate css >> "$LOG" 2>&1 || { say_err "The conda environment 'css' was not found. See INSTALL.md step 2."; exit 1; }
python -c "import cryptography, openpyxl" 2>/dev/null || { say_err "The 'css' environment is missing cryptography / openpyxl. Run: conda env update -n css -f environment.yml"; exit 1; }
FSH=$(python -c "import json;print(json.load(open('$CSS_BASE/app_data/settings.json')).get('freesurfer_home',''))" 2>/dev/null)
FSH="${FSH%/}"     # never guessed: set in the setup wizard (or FREESURFER_HOME already in the environment)
[ -z "$FSH" ] && FSH="${FREESURFER_HOME%/}"
if [ -n "$FSH" ] && [ -f "$FSH/SetUpFreeSurfer.sh" ]; then export FREESURFER_HOME="$FSH"; source "$FSH/SetUpFreeSurfer.sh" >> "$LOG" 2>&1; fi
export SUBJECTS_DIR="$CSS_BASE/subjects" CSS_SUBJECTS_DIR="$CSS_BASE/subjects"
export PYTHONPATH="$CSS_BASE/app/guard${PYTHONPATH:+:$PYTHONPATH}"
nohup python "$CSS_BASE/app/css_app.py" --port "$PORT" ${PERCIVAL_NO_WINDOW:+--no-window} >> "$LOG" 2>&1 &
exit 0
