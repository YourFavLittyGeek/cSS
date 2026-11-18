"""Checks returned annotation files against the schema (allowed values, required fields, ids). Never edits them.
usage: python reference_audit/validate_annotations.py FILE.csv [lesion|object|patient]"""
import sys, os, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from annotation_schema import ALLOWED, LESION_COLUMNS, OBJECT_COLUMNS, PATIENT_COLUMNS
def check(path, kind):
    cols = dict(lesion=LESION_COLUMNS, object=OBJECT_COLUMNS, patient=PATIENT_COLUMNS)[kind]
    d = pd.read_csv(path, dtype=str).fillna(""); err = []
    miss = [c for c in cols if c not in d.columns]
    if miss: err.append(f"missing columns {miss}")
    for c, allowed in ALLOWED.items():
        if c in d.columns:
            bad = d[~d[c].isin(allowed)]
            for i, v in zip(bad.index, bad[c]): err.append(f"row {i + 2}: {c}='{v}' not in {allowed}")
    if kind in ("lesion", "object"):
        for i, r in d.iterrows():
            if r.get("final_category", "") == "": err.append(f"row {i + 2}: final_category empty")
            if r.get("final_category") == "non_cSS" and r.get("noncss_type", "") == "": err.append(f"row {i + 2}: non_cSS needs noncss_type")
            if r.get("final_category") == "indeterminate" and r.get("uncertainty_reason", "") == "": err.append(f"row {i + 2}: indeterminate needs uncertainty_reason")
    if kind == "lesion":
        for i, r in d.iterrows():
            if not ((r.x_mm and r.y_mm and r.z_mm) or (r.vox_i and r.vox_j and r.vox_k) or r.mask_file): err.append(f"row {i + 2}: no location (mm, voxel or mask)")
        dup = d[d.duplicated(["reader_id", "patient_id", "lesion_id"], keep=False)]
        if len(dup): err.append(f"duplicate lesion ids: {dup[['patient_id', 'lesion_id']].values.tolist()}")
    return err
if __name__ == "__main__":
    if len(sys.argv) < 3: sys.exit(__doc__)
    e = check(sys.argv[1], sys.argv[2]); print("\n".join(e) if e else f"{sys.argv[1]}: OK"); sys.exit(1 if e else 0)
