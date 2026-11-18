"""sha256 of every production file the validation reads (proves they are unchanged). Usage: hash_inputs.py OUT.csv IDS..."""
import sys, os, glob, hashlib, pandas as pd
B = os.environ["CSS_BASE"]; rows = []
for sid in sys.argv[2:]:
    pats = [f"data/{sid}_swi.nii*", f"work/{sid}_pial_sd.nii.gz", f"work/{sid}_seg_swispace.nii.gz", f"work/{sid}_dropped.nii.gz",
            f"review/{sid}_candidates.*", f"review/{sid}_excluded.*", f"review/{sid}_calls*.csv", f"review/{sid}_excluded_audit_*.csv", f"review/{sid}_missed.csv"]
    for p in pats:
        for f in sorted(glob.glob(os.path.join(B, p))):
            h = hashlib.sha256(open(f, "rb").read()).hexdigest(); rows.append(dict(study_id=sid, file=os.path.relpath(f, B), sha256=h))
for f in ("review/radiologist_grades.csv", "review/adjudication.csv", "review/evaluation_studies.txt"):
    if os.path.exists(os.path.join(B, f)): rows.append(dict(study_id="all", file=f, sha256=hashlib.sha256(open(os.path.join(B, f), "rb").read()).hexdigest()))
pd.DataFrame(rows).to_csv(sys.argv[1], index=False); print(f"hashed {len(rows)} production files -> {sys.argv[1]}")
