#!/bin/bash
# Percival DEVELOPMENT build launcher (branch feature/unified-score-ml-integration; v5.16-v5.25). Double-click start - no Terminal needed.
# Kept SEPARATE from both the production app and the Percival RC app:
#   project folder  chosen on first start (default ~/Percival_project; remembered in ~/Library/Application Support/Percival Dev/);
#                   ~/css_project and ~/cSS_experimental are refused and write-protected; PERCIVAL_BASE still overrides
#   port 8830 (production 8800, RC 8810); the bundled "Percival Demo" app (MODE=demo) uses ~/Percival_demo and port 8831
# On start it: finds a Python environment ("percival", else a complete "css"; offers a one-time automatic installation when neither
# exists), installs the pipeline / Unified Score / Unified engine shipped in this bundle into the project when the build differs (old
# scripts backed up; engine outputs never deleted), copies the app code, finds FreeSurfer, starts the app server and opens its window.
# When the app is already running it only opens the window. After installation no network access is needed.
RES="$(cd "$(dirname "$0")/../Resources" && pwd)"
MODE="$(cat "$RES/MODE" 2>/dev/null || echo dev)"
TITLE="Percival (development build)"; [ "$MODE" = demo ] && TITLE="Percival Demo (synthetic data)"
CFGDIR="$HOME/Library/Application Support/Percival Dev"; mkdir -p "$CFGDIR"; SLOG="$CFGDIR/setup.log"
say_err() { /usr/bin/osascript -e "display dialog \"$1\" with title \"$TITLE\" buttons {\"OK\"} default button 1 with icon caution" >/dev/null 2>&1; echo "$1" >&2; }
ask() {   # ask "text" "button A" "button B (default)" -> prints the button pressed ("" when cancelled)
  /usr/bin/osascript -e "button returned of (display dialog \"$1\" with title \"$TITLE\" buttons {\"$2\", \"$3\"} default button \"$3\")" 2>/dev/null; }
canon() { local p="$1" rest=""; case "$p" in "~"*) p="$HOME${p#\~}";; /*) ;; *) p="$PWD/$p";; esac
  while [ ! -d "$p" ]; do rest="/$(basename "$p")$rest"; p="$(dirname "$p")"; done; echo "$(cd "$p" && pwd -P)$rest"; }

# ------------------------------------------------------------------ project folder and port
if [ "$MODE" = demo ]; then CSS_BASE="${PERCIVAL_BASE:-$HOME/Percival_demo}"; PORT="${PERCIVAL_PORT:-8831}"
else
  PORT="${PERCIVAL_PORT:-8830}"; CFG="$CFGDIR/project_path"
  if [ -n "${PERCIVAL_BASE:-}" ]; then CSS_BASE="$PERCIVAL_BASE"
  elif [ -s "$CFG" ]; then CSS_BASE="$(cat "$CFG")"
  elif [ -d "$HOME/Percival_project" ]; then CSS_BASE="$HOME/Percival_project"; echo "$CSS_BASE" > "$CFG"      # earlier Percival Dev install: keep it
  else
    b="$(ask "Welcome to Percival.\n\nPercival keeps your studies, reviews, results and its locally trained models in one project folder on this Mac.\n\nUse the folder Percival_project in your home folder, or choose another one (not on the Desktop, in Documents or in a cloud-synced folder)." "Choose folder…" "Use Percival_project")"
    [ -z "$b" ] && exit 0
    if [ "$b" = "Choose folder…" ]; then
      CSS_BASE="$(/usr/bin/osascript -e 'POSIX path of (choose folder with prompt "Choose or create the Percival project folder")' 2>/dev/null)"; [ -z "$CSS_BASE" ] && exit 0
      CSS_BASE="${CSS_BASE%/}"
    else CSS_BASE="$HOME/Percival_project"; fi
    SAVE_CFG=1
  fi
fi
BASE_C="$(canon "$CSS_BASE")"
PROT="$HOME/css_project:$HOME/cSS_experimental${CSS_PROTECTED_PATHS:+:$CSS_PROTECTED_PATHS}"
for R in $(echo "$PROT" | tr ':' ' '); do
  R="$(canon "$R")"
  case "$BASE_C/" in "$R/"*) say_err "Refused: the project folder ($CSS_BASE) is a protected project (production or RC) or inside one ($R). Open Percival again and choose a separate folder."; rm -f "$CFGDIR/project_path"; exit 1;; esac
  case "$R/" in "$BASE_C/"*) say_err "Refused: the project folder ($CSS_BASE) contains a protected project ($R). Open Percival again and choose a separate folder."; rm -f "$CFGDIR/project_path"; exit 1;; esac
done
case "$BASE_C/" in *"/Library/Mobile Documents/"*|*"/Library/CloudStorage/"*|*"/Dropbox"*|*"/Google Drive"*|*"/OneDrive"*|*"/iCloud"*|"$HOME/Desktop/"*|"$HOME/Documents/"*)
  say_err "Refused: the project folder is on the Desktop, in Documents or in a cloud-synced folder. Open Percival again and choose another folder."; rm -f "$CFGDIR/project_path"; exit 1;; esac
[ "${SAVE_CFG:-}" = 1 ] && echo "$BASE_C" > "$CFGDIR/project_path"

# ------------------------------------------------------------------ already running: just open the window
if /usr/bin/nc -z 127.0.0.1 "$PORT" >/dev/null 2>&1; then
  if /usr/bin/pgrep -f "$BASE_C/app/css_app.py" >/dev/null 2>&1; then /usr/bin/open "http://127.0.0.1:$PORT/"; exit 0; fi
  say_err "Port $PORT is used by another program, so Percival cannot start. Quit that program (or the other Percival) and open Percival again."; exit 1
fi

# ------------------------------------------------------------------ Python environment (one-time automatic installation)
find_conda() { for c in "$HOME/miniforge3" "$HOME/mambaforge" "$HOME/miniconda3" "$HOME/anaconda3" "/opt/homebrew/Caskroom/miniforge/base" "/opt/miniconda3" "/opt/anaconda3"; do
  [ -f "$c/etc/profile.d/conda.sh" ] && { source "$c/etc/profile.d/conda.sh"; return 0; }; done; return 1; }
ENVOK=""
if find_conda; then
  for e in percival css; do
    if conda activate "$e" >/dev/null 2>&1 && python -c "import numpy, scipy, nibabel, pandas, skimage, cryptography, openpyxl" >/dev/null 2>&1; then ENVOK="$e"; break; fi
  done
fi
if [ -z "$ENVOK" ]; then
  b="$(ask "Percival needs a one-time installation of its Python components (open-source packages from conda-forge, about 2 GB, 5-15 minutes, internet needed once).\n\nNothing from your projects is sent anywhere. After this, Percival works offline.\n\nInstall now? You will get a message when it is finished." "Not now" "Install")"
  [ "$b" = "Install" ] || exit 0
  /bin/bash "$RES/first_run_setup.sh" "$RES/percival_environment.yml" "$SLOG" || exit 1
  find_conda && conda activate percival >/dev/null 2>&1 && ENVOK=percival || { say_err "The installation did not finish. Details: $SLOG"; exit 1; }
fi

# ------------------------------------------------------------------ demo project (synthetic MRI phantoms, no clinical data)
if [ "$MODE" = demo ]; then
  ls "$BASE_C/review/"*_candidates.csv >/dev/null 2>&1 || /usr/bin/osascript -e "display notification \"Creating synthetic demo studies...\" with title \"$TITLE\"" >/dev/null 2>&1
  python "$RES/make_demo.py" "$BASE_C" "$RES/pipeline/unified_engine/run_imaging.py" >> "$SLOG" 2>&1 || { say_err "The demo studies could not be prepared. Details: $SLOG"; exit 1; }
fi

# ------------------------------------------------------------------ install the bundled pipeline into the project
export CSS_BASE="$BASE_C" CSS_EXPERIMENTAL=1 CSS_PROTECTED_PATHS="$PROT" PERCIVAL_APP_BUNDLE="$(cd "$RES/../.." && pwd)"   # bundle path: the app can restart itself (new project folder chosen in setup)
mkdir -p "$CSS_BASE/app" "$CSS_BASE/app_data/logs" "$CSS_BASE/scripts" "$CSS_BASE/data" "$CSS_BASE/work" "$CSS_BASE/review" "$CSS_BASE/results" "$CSS_BASE/unified_engine"
LOG="$CSS_BASE/app_data/logs/launcher.log"; echo "=== $(date) build $(cat "$RES/pipeline/scripts/BUILD" 2>/dev/null) env $ENVOK" >> "$LOG"
if ! cmp -s "$RES/pipeline/scripts/BUILD" "$CSS_BASE/scripts/BUILD"; then
  if ls "$CSS_BASE/scripts/"*.py >/dev/null 2>&1; then BK="$CSS_BASE/scripts/backup_$(date +%Y%m%d_%H%M%S)"; mkdir -p "$BK"; cp "$CSS_BASE/scripts/"*.* "$BK/" 2>/dev/null; fi
  for f in "$RES/pipeline/scripts/"*; do t="$CSS_BASE/scripts/.$(basename "$f").new"; cp "$f" "$t" && chmod +x "$t" && mv -f "$t" "$CSS_BASE/scripts/$(basename "$f")" || { say_err "Pipeline install failed at $(basename "$f")"; exit 1; }; done
  rm -rf "$CSS_BASE/unified_score.new" && cp -R "$RES/pipeline/unified_score" "$CSS_BASE/unified_score.new" && { [ -d "$CSS_BASE/unified_score" ] && mv "$CSS_BASE/unified_score" "$CSS_BASE/unified_score.old_$(date +%Y%m%d_%H%M%S)"; mv "$CSS_BASE/unified_score.new" "$CSS_BASE/unified_score"; }
  # engine code + model files only; the project's own engine outputs (percival/, shadow/, image_ml/, ...) are left untouched (no --delete)
  rsync -a --exclude __pycache__ "$RES/pipeline/unified_engine/" "$CSS_BASE/unified_engine/" >> "$LOG" 2>&1 || { say_err "Engine install failed"; exit 1; }
  mkdir -p "$CSS_BASE/tests" && cp "$RES/pipeline/tests/"* "$CSS_BASE/tests/" 2>/dev/null
  echo "pipeline installed: $(cat "$CSS_BASE/scripts/BUILD")" >> "$LOG"
fi
rsync -a --delete --exclude __pycache__ "$RES/app/" "$CSS_BASE/app/" >> "$LOG" 2>&1 || cp -R "$RES/app/." "$CSS_BASE/app/"
FSH=$(python -c "import json;print(json.load(open('$CSS_BASE/app_data/settings.json')).get('freesurfer_home',''))" 2>/dev/null)
FSH="${FSH%/}"     # never guessed: set in the setup wizard (or FREESURFER_HOME already in the environment)
[ -z "$FSH" ] && FSH="${FREESURFER_HOME%/}"
if [ -n "$FSH" ] && [ -f "$FSH/SetUpFreeSurfer.sh" ]; then export FREESURFER_HOME="$FSH"; source "$FSH/SetUpFreeSurfer.sh" >> "$LOG" 2>&1; fi
export SUBJECTS_DIR="$CSS_BASE/subjects" CSS_SUBJECTS_DIR="$CSS_BASE/subjects"
export PYTHONPATH="$CSS_BASE/app/guard${PYTHONPATH:+:$PYTHONPATH}"
nohup python "$CSS_BASE/app/css_app.py" --port "$PORT" ${PERCIVAL_NO_WINDOW:+--no-window} >> "$LOG" 2>&1 &
exit 0
