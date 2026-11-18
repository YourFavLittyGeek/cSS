#!/usr/bin/env bash
# Experimental structural modules: phantom tests + proof that production output is unchanged.
# Usage: bash experimental/run_all_checks.sh [OUT_DIR]   (from cSS_pipeline_v4.13; needs no FreeSurfer, no patient data)
set -euo pipefail
cd "$(dirname "$0")/.."; ROOT=$PWD; OUT=${1:-$ROOT/experimental/test_results}; mkdir -p "$OUT"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
export CSS_BASE=$T FREESURFER_HOME=$T/fs CSS_REVIEW_TEST=1
eval "$(sed -n 8,10p tests/run_tests.sh)"; S=$T/scripts
for ID in PH3 PH6; do
  # same preparation as the baseline hashes: PH3 with T1-style labels, PH6 as in tests/run_tests.sh (SWI-only labels)
  if [ $ID = PH3 ]; then python tests/phantom_v4.py PH3 1 > /dev/null; python $S/align_seg.py PH3 > /dev/null; cp $T/work/PH3_seg_swispace.nii.gz $T/work/PH3_t1seg_swispace.nii.gz
  else python tests/phantom_surfvein.py > /dev/null; python $S/align_seg.py PH6 > /dev/null; fi
  env -u CSS_HESSIAN_FINGERPRINT -u CSS_SURFACE_COORDINATES -u CSS_VESSEL_GRAPH -u CSS_MULTIVIEW_SEEDING -u CSS_SULCUS_REFERENCE \
      -u CSS_CANDIDATE_SPLITTING -u CSS_EXPERIMENTAL_FUSION CSS_V53=1 CSS_ZONE2=1 python $S/detect_css.py $ID > $OUT/${ID}_detect.log
done
( cd $T/review && md5sum PH3_candidates.csv PH3_candidates.nii.gz PH6_candidates.csv ) > $OUT/production_hashes_now.txt
# the same detection with every experimental flag ON must give identical production files (flags are not read by scripts/)
cp $T/review/PH3_candidates.csv $T/ph3_before.csv
CSS_HESSIAN_FINGERPRINT=1 CSS_SURFACE_COORDINATES=1 CSS_VESSEL_GRAPH=1 CSS_MULTIVIEW_SEEDING=1 CSS_SULCUS_REFERENCE=1 CSS_CANDIDATE_SPLITTING=1 \
  CSS_EXPERIMENTAL_FUSION=1 CSS_V53=1 CSS_ZONE2=1 python $S/detect_css.py PH3 > /dev/null
python - "$T" <<'PY'
import sys, pandas as pd
T = sys.argv[1]; a = pd.read_csv(f"{T}/ph3_before.csv"); b = pd.read_csv(f"{T}/review/PH3_candidates.csv")
assert a.equals(b), "production candidates changed when experimental flags were on"
print("production PH3 candidates identical with experimental flags on")
PY
grep -rl "structural_detection\|CSS_HESSIAN_FINGERPRINT" scripts/ && { echo "FAIL: production code references the experimental package"; exit 1; } || echo "production scripts do not reference the experimental package"
cd experimental && CSS_STRUCT_TEST_BASE=$T python -m structural_detection.tests.test_structural "$OUT"
for ID in PH3 PH6; do CSS_HESSIAN_FINGERPRINT=1 CSS_SURFACE_COORDINATES=1 CSS_VESSEL_GRAPH=1 CSS_MULTIVIEW_SEEDING=1 CSS_SULCUS_REFERENCE=1 \
  CSS_CANDIDATE_SPLITTING=1 CSS_EXPERIMENTAL_FUSION=1 python -m structural_detection.run_structural $ID --include-excluded --out "$OUT/structural_$ID"; done
echo "all experimental checks done -> $OUT"
