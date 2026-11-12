#!/bin/bash
# Phase 1 (safety fixes) - MEASUREMENT ONLY on the development studies. Research software; expert review required.
# usage: conda activate css ; caffeinate -i bash ~/css_project/tools/phase1_measure.sh       (about 25 min; one study at a time)
# Nothing in the project's lists, calls, scores or model is changed: detections run on COPIES (experiments/), the fit is a dry run.
BASE=${CSS_BASE:-$HOME/css_project}; cd "$BASE" || exit 1; S=$BASE/scripts; R=$BASE/review
DEV=${DEV:-M02,M03,M04,M05,M06,M07,M08,M09,M10,M11}; THICK=${THICK:-M05,M11}; READS=${READS:-ST,ML,Redo_v53,Blind_v57}
echo "version: $(cat $S/VERSION)"; LOG=$R/phase1_measure.log; : > "$LOG"
# 0. evaluation studies are named once; fit_confidence.py refuses them from now on
E=$R/evaluation_studies.txt
[ -f "$E" ] || printf '# evaluation studies: never used to fit or calibrate. Note = what has already been looked at.\nM12,examined 2026-11 (blind ST read; effect of the 24.2 %% cut was inspected)\nM13,examined 2026-11 (blind ST read; effect of the 24.2 %% cut was inspected)\nM14,examined 2026-11 (blind ST read; effect of the 24.2 %% cut was inspected)\nM15,examined 2026-11 (blind ST read; effect of the 24.2 %% cut was inspected)\n' > "$E"
echo "=== 1/3 registration check of every study (from the existing QC files)" | tee -a "$LOG"
python - "$R" <<'PY' | tee -a "$LOG"
import sys, json, glob, os
R = sys.argv[1]; bad = 0
for f in sorted(glob.glob(f"{R}/M*_qc.json")):
    q = json.load(open(f)); s, b = q.get("label_shift_mm"), q.get("edge_bias_mm")
    v = "not measured" if s is None else ("FAIL" if s > 1.5 or (b is not None and abs(b) > 1.5) else "ok")
    bad += v == "FAIL"; print(f"   {os.path.basename(f)[:3]}: label shift {s} mm, edge bias {b} mm, anatomy {q.get('anatomy')} -> {v}")
print(f"   studies the registration gate would stop: {bad}")
PY
echo "=== 2/3 slice gate on the 3 mm development studies ($THICK): legacy vs mm gate, on copies  $(date '+%H:%M')" | tee -a "$LOG"
python "$S/run_experiment.py" "$THICK" --name p1_legacy --flags CSS_V53=1,CSS_ZONE2=1,CSS_SLICE_GATE=legacy >> "$LOG" 2>&1 \
 && python "$S/run_experiment.py" "$THICK" --name p1_mm --flags CSS_V53=1,CSS_ZONE2=1 >> "$LOG" 2>&1 \
 && python "$S/compare_pipelines.py" p1_legacy p1_mm "$THICK" --reads "$READS" >> "$LOG" 2>&1 || echo "    step 2 FAILED (see the log)" | tee -a "$LOG"
grep -E "LOST|GAINED|B-only|shown objects:|^   M[0-9]+:" "$R/compare_pipelines_p1_legacy_vs_p1_mm_summary.txt" 2>/dev/null | tee -a "$LOG"
python - "$BASE" "$THICK" <<'PY' | tee -a "$LOG"
import sys, pandas as pd, os
B, ids = sys.argv[1], sys.argv[2].split(",")
for s in ids:
    for n in ("p1_legacy", "p1_mm"):
        p = f"{B}/experiments/{n}/review/{s}_candidates.csv"
        if os.path.exists(p):
            c = pd.read_csv(p); x = pd.read_csv(p.replace("candidates", "excluded"))
            print(f"   {s} {n}: shown {len(c)} (single-slice {int(c.get('single_slice', pd.Series([0])).sum())}), excluded {len(x)} (single-slice {int(x.get('single_slice', pd.Series([0])).sum())})")
PY
echo "=== 3/3 confidence model with the leave-one-patient-out cut - DRY RUN, no model written  $(date '+%H:%M')" | tee -a "$LOG"
if head -1 "$R/M02_candidates.csv" | grep -q "minip_cont" && [ "$(cat $R/M*_excluded.csv | grep -c 'low confidence')" = "0" ]; then
  python "$S/fit_confidence.py" "$DEV" --reads "$READS" --dry-run > "$R/phase1_fit_dryrun.txt" 2>&1; grep -E "objects:|leave-one-patient-out AUC|lowest protected|at this cut|HONEST" "$R/phase1_fit_dryrun.txt" | tee -a "$LOG"
else
  echo "    skipped: the current lists already carry low-confidence exclusions, so a fit on them would be meaningless. (Earlier fit on the full lists: LOPO cut about 8 %, about 5 non-cSS removed.)" | tee -a "$LOG"
fi
cd "$R" && rm -f results_phase1.zip && zip -q results_phase1.zip phase1_measure.log phase1_fit_dryrun.txt evaluation_studies.txt compare_pipelines_p1_legacy_vs_p1_mm.csv compare_pipelines_p1_legacy_vs_p1_mm_summary.txt 2>/dev/null
echo "DONE. Nothing in the project was changed. Send: $R/results_phase1.zip"
