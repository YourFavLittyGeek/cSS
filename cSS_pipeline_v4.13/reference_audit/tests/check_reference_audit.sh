#!/usr/bin/env bash
# End-to-end test of reference_audit/ on the PH3 / PH6 phantoms with SYNTHETIC reads (plumbing only; no patient data, no results).
# Also proves the production outputs are untouched (sha256 of review/ and work/ before = after).
# usage (from cSS_pipeline_v4.13): bash reference_audit/tests/check_reference_audit.sh
set -euo pipefail
cd "$(dirname "$0")/../.."; ROOT=$PWD; RA=$ROOT/reference_audit; T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
export CSS_BASE=$T FREESURFER_HOME=$T/fs CSS_REVIEW_TEST=1; eval "$(sed -n 8,10p tests/run_tests.sh)"; S=$T/scripts
python tests/phantom_v4.py PH3 1 > /dev/null; python $S/align_seg.py PH3 > /dev/null; cp $T/work/PH3_seg_swispace.nii.gz $T/work/PH3_t1seg_swispace.nii.gz
python tests/phantom_surfvein.py > /dev/null; python $S/align_seg.py PH6 > /dev/null
for ID in PH3 PH6; do CSS_V53=1 CSS_ZONE2=1 python $S/detect_css.py $ID > /dev/null; done
H() { (cd $T && find review work data -type f | sort | xargs sha256sum); }; H > $T/before.sha
fail() { echo "FAIL: $*"; exit 1; }
python $RA/inventory.py PH3 PH6
python $RA/sample.py B01 --studies PH3,PH6 --plan $RA/EXCLUDED_OBJECT_SAMPLING.csv --include-shown 2
python $RA/sample.py B02 --studies PH3,PH6 --per-stratum 3
python $RA/sample.py B01 --studies PH3 > /dev/null 2>&1 && fail "batch overwrite allowed" || echo "PASS batch names never overwritten"
python $RA/sample.py B03 --studies PH3 --max-per-study 3 > /dev/null 2>&1 && fail "--max-per-study accepted" || echo "PASS unequal-probability cap refused"
python - "$T" <<'PY'
import sys, pandas as pd
T = sys.argv[1]; L = pd.read_csv(f"{T}/reference_audit/batches/ledger.csv")
assert not L.uid.duplicated().any(), "duplicate object across batches"
for b in ("B01", "B02"):
    c = pd.read_csv(f"{T}/reference_audit/batches/{b}/cases_blinded.csv")
    assert set(c.columns) == {"case_id", "study_id", "vox_i", "vox_j", "vox_k", "x_mm", "y_mm", "z_mm"}, f"blinded file leaks {set(c.columns)}"
print(f"PASS no duplicates across batches ({len(L)} objects); blinded files contain ids and coordinates only")
PY
python $RA/render_batch.py B01 --masks; python $RA/render_batch.py B02
python - "$T" "$RA" <<'PY'
import sys, pandas as pd; sys.path.insert(0, sys.argv[2]); from annotation_schema import OBJECT_COLUMNS
d = pd.read_csv(f"{sys.argv[1]}/reference_audit/batches/B01/review/annotation_sheet.csv", dtype=str).fillna("")
assert list(d.columns) == OBJECT_COLUMNS, "unexpected columns"
filled = [c for c in d.columns if c not in ("case_id", "patient_id") and (d[c] != "").any()]
assert not filled, f"pre-filled fields {filled}"
print("PASS annotation sheet: schema columns only, nothing pre-filled except case id and study code")
PY
python $RA/ws_prepare.py W1 --studies PH3,PH6 --readers R1,R2
ls $T/reference_audit/whole_scan/W1/cases/*/ | grep -q -i -E "cand|excl|drop" && fail "whole-scan packet contains detector output" || echo "PASS whole-scan packet holds images only"
python $RA/tests/make_synthetic_reads.py $T W1 B01,B02
for f in $T/reference_audit/whole_scan/W1/lesion_annotations_*.csv; do python $RA/validate_annotations.py $f lesion; done
python $RA/agreement.py whole_scan W1; python $RA/agreement.py objects B01; python $RA/agreement.py objects B02
python - "$T" <<'PY'
import sys, pandas as pd
T = sys.argv[1]; W = f"{T}/reference_audit/whole_scan/W1"
a = pd.read_csv(f"{W}/agreement_summary.csv"); assert {"kappa_ci_low", "kappa_ci_high"} <= set(a.columns), "no kappa CI"
t = pd.read_csv(f"{W}/adjudication_TEMPLATE.csv", dtype=str).fillna("")
t["adjudicated_category"] = ["non_cSS" if "non_cSS" in (a_ + b_) else ("indeterminate" if "not_marked" in (a_ + b_) else "definite_cSS") for a_, b_ in zip(t.R1_category, t.R2_category)]
t["adjudicator"] = "TEST"; t.to_csv(f"{W}/adjudication.csv", index=False)
print("PASS kappa CIs present:", a[["measure", "kappa", "kappa_ci_low", "kappa_ci_high"]].head(3).to_string(index=False))
PY
python $RA/evaluate.py T1 --packet W1 --batches B01,B02 > $T/eval.txt; cat $T/eval.txt
python - "$T" <<'PY'
import sys, pandas as pd
T = sys.argv[1]; R = f"{T}/reference_audit/results/T1"
f = pd.read_csv(f"{R}/reference_lesions_with_production_fate.csv"); fates = set(f.fate)
assert "retained (shown)" in fates and "never generated" in fates, fates
e = pd.read_csv(f"{R}/rejected_objects_css_estimate.csv"); assert {"p_ci_low", "p_ci_high", "population_N"} <= set(e.columns)
p = pd.read_csv(f"{R}/production_performance.csv"); assert p.measure.str.contains("lesion-level sensitivity").any()
print("PASS evaluation: fates", sorted(fates), "; strata", len(e), "; pooled batches")
PY
H > $T/after.sha; cmp -s $T/before.sha $T/after.sha && echo "PASS production files (review/, work/, data/) unchanged: $(wc -l < $T/before.sha) files" || fail "production files changed"
echo "ALL REFERENCE-AUDIT CHECKS PASSED"
