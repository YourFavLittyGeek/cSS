#!/bin/bash
# Runs every v5.7-E check on the Mac in one go and bundles the results. Research software; expert review required.
# usage:  conda activate css ; caffeinate -i bash ~/css_project/tools/run_all_v57E.sh
# Nothing here changes the project's candidate lists, calls or scores (read-only probes + experiments on COPIES). No redetect.
# Takes about 2 hours for M02-M11; one study at a time (about 3 GB). Close other heavy programs. A failing step is logged and the next one runs.
# Env overrides: CSS_BASE (project), STUDIES (all studies), EXP_STUDIES (studies for the experiments), READS.
BASE=${CSS_BASE:-$HOME/css_project}; cd "$BASE" || exit 1
STUDIES=${STUDIES:-M02,M03,M04,M05,M06,M07,M08,M09,M10,M11}
EXP_STUDIES=${EXP_STUDIES:-M02,M03,M04,M05,M06}
READS=${READS:-Redo_v53,Blind_v57}
LOG=$BASE/review/run_all_v57E.log; mkdir -p "$BASE/review"; : > "$LOG"
S=$BASE/scripts
FAILED=()
step() { local name="$1"; echo "" | tee -a "$LOG"; echo "=== $name  ($(date '+%H:%M:%S'))" | tee -a "$LOG"; shift
         if "$@" >> "$LOG" 2>&1; then echo "    ok" | tee -a "$LOG"; else echo "    STEP FAILED (see the log)" | tee -a "$LOG"; FAILED+=("$name"); fi; }
echo "version: $(cat $S/VERSION 2>/dev/null)   base: $BASE   studies: $STUDIES   experiments: $EXP_STUDIES" | tee -a "$LOG"
for f in probe_common.py css_shape.py shape_probe.py zone_probe.py css_sheet3d.py pial_compare.py run_experiment.py compare_pipelines.py; do
  [ -f "$S/$f" ] || { echo "MISSING $S/$f - install the cumulative zip first" | tee -a "$LOG"; exit 1; }
done
# the reader's final decisions, if the file was not copied yet
[ -f "$BASE/review/adjudication.csv" ] || echo "note: review/adjudication.csv not found - probes use the individual reads only" | tee -a "$LOG"

step "1/7 acceptance test of the new rules on copies (v53_compare)"  python "$S/v53_compare.py" "$STUDIES"
step "2/7 shape probe (blob / straight-in-sulcus measures, axis angle)" python "$S/shape_probe.py" "$STUDIES" --reads "$READS"
step "3/7 zone probe"                                                  python "$S/zone_probe.py" "$STUDIES" --reads "$READS"
step "4/7 mesh vs mask pial distance (needs surface features)"         python "$S/pial_compare.py" "$STUDIES" --reads "$READS"
step "5/7 experiments: base / soft gates / 3-D seeds on copies"        bash -c "python '$S/run_experiment.py' $EXP_STUDIES --name base --flags CSS_V53=1 && python '$S/run_experiment.py' $EXP_STUDIES --name soft --flags CSS_V53=1,CSS_SOFT_GATES=1 && python '$S/run_experiment.py' $EXP_STUDIES --name seeds3d --flags CSS_V53=1,CSS_3D_SEEDS=1"
step "6/7 comparisons"                                                  bash -c "python '$S/compare_pipelines.py' base soft $EXP_STUDIES --reads $READS && python '$S/compare_pipelines.py' base seeds3d $EXP_STUDIES --reads $READS"
step "7/7 3-D seed statistics from the manifests"                       bash -c "python - <<'PY' > '$BASE/review/seeds3d_stats.txt'
import json, glob
for p in sorted(glob.glob('$BASE/experiments/seeds3d/review/*_manifest.json')):
    print(p.split('/')[-1].split('_')[0], json.load(open(p))['detect']['parameters'].get('seeds3d'))
PY
cat '$BASE/review/seeds3d_stats.txt'"

# bundle the results
OUT=$BASE/review/results_v57E.zip; rm -f "$OUT"
cd "$BASE" && zip -q -j "$OUT" review/run_all_v57E.log review/seeds3d_stats.txt review/v53_compare.csv review/v53_compare_summary.txt review/v53_objects.csv \
  review/shape_probe.csv review/shape_probe_summary.txt review/zone_probe.csv review/zone_probe_summary.txt review/pial_compare.csv review/pial_compare_summary.txt \
  review/compare_pipelines_base_vs_soft.csv review/compare_pipelines_base_vs_soft_summary.txt review/compare_pipelines_base_vs_seeds3d.csv review/compare_pipelines_base_vs_seeds3d_summary.txt \
  experiments/*/work/*_3d_only.csv experiments/*/work/*_soft_gate.csv experiments/base/review/*_rule_audit.csv experiments/base/review/*_manifest.json 2>/dev/null
echo "" | tee -a "$LOG"
echo "DONE. Send this file: $OUT   ($(du -h "$OUT" | cut -f1))" | tee -a "$LOG"
echo "Steps that failed: ${#FAILED[@]}"; for f in "${FAILED[@]}"; do echo "  - $f"; done
echo "(step 4 fails when a study has no review/<ID>_surface_features.csv: that study has no recon-all surface features; the other steps do not depend on it)"
