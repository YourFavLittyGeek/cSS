#!/usr/bin/env bash
# Real-data validation of the experimental structural modules (read-only on production outputs).
# Usage (from $CSS_BASE = ~/css_project):
#   caffeinate -i bash experimental/validation/run_real_validation.sh                 # dev M02-M11 + held-out M12-M15
#   DEV="M02 M03" HELDOUT="" bash experimental/validation/run_real_validation.sh      # subset
# Runs ONE study at a time. Writes only to $CSS_BASE/experimental/validation_<UTC>/ . Production files are hashed before
# and after; the run stops if any changed. Missing inputs -> MISSING_INPUTS.txt and stop (nothing is guessed).
set -uo pipefail
B=${CSS_BASE:-$HOME/css_project}; export CSS_BASE=$B
DEV=${DEV:-"M02 M03 M04 M05 M06 M07 M08 M09 M10 M11"}; HELDOUT=${HELDOUT-"M12 M13 M14 M15"}
EXP=$B/experimental; KIT=$EXP/validation; PY=${PYTHON:-python}
STAMP=$(date -u +%Y%m%dT%H%M%SZ); RUN=$B/experimental/validation_$STAMP; mkdir -p "$RUN/logs"
exec > >(tee -a "$RUN/logs/run.log") 2>&1
echo "== real-data validation run $STAMP  (CSS_BASE=$B)"
for f in CSS_HESSIAN_FINGERPRINT CSS_SURFACE_COORDINATES CSS_VESSEL_GRAPH CSS_MULTIVIEW_SEEDING CSS_SULCUS_REFERENCE CSS_CANDIDATE_SPLITTING CSS_EXPERIMENTAL_FUSION; do
  if [ "${!f:-0}" != "0" ]; then echo "STOP: $f is set in the shell (must default to 0; the kit sets switches per configuration)"; exit 2; fi; done
# ---- environment record
{ echo "pipeline_version $(cat $B/scripts/VERSION 2>/dev/null || echo unknown)"
  echo "experimental_version $($PY -c 'import sys; sys.path.insert(0,"'$EXP'"); import structural_detection as s; print(s.__version__)' 2>&1)"
  echo "kit_sha256 $(cat $KIT/*.py $KIT/*.sh $EXP/structural_detection/*.py | shasum -a 256 | cut -c1-16)"
  echo "git_commit $(git -C $EXP rev-parse HEAD 2>/dev/null || echo 'not a git checkout (zip install)')"
  echo "python $($PY -V 2>&1)"; $PY -c 'import numpy,scipy,pandas,nibabel,skimage,matplotlib;print("numpy",numpy.__version__,"scipy",scipy.__version__,"pandas",pandas.__version__,"nibabel",nibabel.__version__,"skimage",skimage.__version__,"matplotlib",matplotlib.__version__)'
  echo "host $(uname -mrs)"; echo "dev $DEV"; echo "heldout $HELDOUT"; } > "$RUN/environment.txt"
cat "$RUN/environment.txt"
# ---- input check (exact list of what is needed)
$PY "$KIT/check_inputs.py" "$RUN" $DEV -- $HELDOUT || { echo "STOP: inputs missing - see $RUN/MISSING_INPUTS.txt"; exit 3; }
$PY "$KIT/hash_inputs.py" "$RUN/inputs_before.csv" $DEV $HELDOUT
# ---- configurations: each module alone, then everything + fusion
cfg_flags() { case $1 in   # macOS ships bash 3.2: no associative arrays
  A) echo CSS_HESSIAN_FINGERPRINT;; B) echo CSS_SURFACE_COORDINATES;; C) echo CSS_VESSEL_GRAPH;; D) echo CSS_MULTIVIEW_SEEDING;;
  E) echo CSS_SULCUS_REFERENCE;; F) echo CSS_CANDIDATE_SPLITTING;;
  ALL) echo CSS_HESSIAN_FINGERPRINT CSS_SURFACE_COORDINATES CSS_VESSEL_GRAPH CSS_SULCUS_REFERENCE CSS_CANDIDATE_SPLITTING CSS_EXPERIMENTAL_FUSION;; esac; }
for c in A B C D E F ALL; do
  for ID in $DEV $HELDOUT; do
    env_args=(); for f in $(cfg_flags $c); do env_args+=("$f=1"); done
    t0=$(date +%s)
    ( cd "$EXP" && env "${env_args[@]}" $PY -m structural_detection.run_structural "$ID" --include-excluded --out "$RUN/configs/$c/$ID" ) \
        > "$RUN/logs/${c}_${ID}.log" 2>&1
    rc=$?; echo "$c $ID rc=$rc $(( $(date +%s) - t0 )) s"; echo "$c,$ID,$rc,$(( $(date +%s) - t0 ))" >> "$RUN/logs/timing.csv"
    [ $rc -eq 0 ] || { echo "STOP: $c $ID failed - see $RUN/logs/${c}_${ID}.log"; exit 4; }
  done
done
$PY "$KIT/hash_inputs.py" "$RUN/inputs_after.csv" $DEV $HELDOUT
cmp -s "$RUN/inputs_before.csv" "$RUN/inputs_after.csv" && echo "production inputs/outputs unchanged (sha256 before = after)" \
  || { echo "STOP: a production file changed during the run - see the two inputs_*.csv"; exit 5; }
# ---- analysis (held-out studies are evaluated with every threshold fixed in advance; nothing is tuned)
$PY "$KIT/analyse_real_validation.py" "$RUN" --dev "$DEV" --heldout "$HELDOUT" --scripts "$B/scripts" || { echo "STOP: analysis failed"; exit 6; }
# ---- example images for error cases (candidates only; needs the current lists)
[ -s "$RUN/report/error_cases_for_rendering.csv" ] && $PY "$KIT/render_cases.py" "$RUN/report/error_cases_for_rendering.csv" "$RUN/report/figures/examples" || true
( cd "$RUN" && zip -qr "$B/review/results_real_validation_$STAMP.zip" environment.txt inputs_before.csv inputs_after.csv logs report configs -x "*.nii.gz" )
echo "DONE -> $RUN/report ; send $B/review/results_real_validation_$STAMP.zip"
