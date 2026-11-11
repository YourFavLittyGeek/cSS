#!/bin/bash
# Re-runs ONLY steps 4 (pial_compare) and 6 (compare_pipelines) of run_all_v57E.sh with the fixed scripts, using the experiments already made. A few minutes.
# usage: conda activate css ; bash ~/Downloads/rerun_failed_v57E.sh      -> bundle: ~/css_project/review/results_v57E_fix.zip
BASE=${CSS_BASE:-$HOME/css_project}; cd "$BASE" || exit 1
STUDIES=${STUDIES:-M02,M03,M04,M05,M06,M07,M08,M09,M10,M11}; EXP_STUDIES=${EXP_STUDIES:-M02,M03,M04,M05,M06}; READS=${READS:-Redo_v53,Blind_v57}
S=$BASE/scripts; LOG=$BASE/review/rerun_failed_v57E.log; : > "$LOG"; FAILED=()
run() { local n="$1"; shift; echo "=== $n ($(date '+%H:%M:%S'))" | tee -a "$LOG"; if "$@" >> "$LOG" 2>&1; then echo "    ok" | tee -a "$LOG"; else echo "    FAILED (see the log)" | tee -a "$LOG"; FAILED+=("$n"); fi; }
[ -d "$BASE/experiments/base" ] && [ -d "$BASE/experiments/soft" ] && [ -d "$BASE/experiments/seeds3d" ] || { echo "the experiments base / soft / seeds3d are missing: run run_all_v57E.sh first" | tee -a "$LOG"; exit 1; }
run "pial_compare" python "$S/pial_compare.py" "$STUDIES" --reads "$READS"
run "compare base vs soft" python "$S/compare_pipelines.py" base soft "$EXP_STUDIES" --reads "$READS"
run "compare base vs seeds3d" python "$S/compare_pipelines.py" base seeds3d "$EXP_STUDIES" --reads "$READS"
OUT=$BASE/review/results_v57E_fix.zip; rm -f "$OUT"
zip -q -j "$OUT" review/rerun_failed_v57E.log review/pial_compare.csv review/pial_compare_summary.txt review/compare_pipelines_base_vs_soft.csv review/compare_pipelines_base_vs_soft_summary.txt \
  review/compare_pipelines_base_vs_seeds3d.csv review/compare_pipelines_base_vs_seeds3d_summary.txt 2>/dev/null
echo "DONE. Send: $OUT"; echo "failed: ${#FAILED[@]}"; for f in "${FAILED[@]}"; do echo "  - $f"; done
