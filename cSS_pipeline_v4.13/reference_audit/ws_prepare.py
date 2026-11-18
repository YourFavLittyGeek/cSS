"""Whole-scan blinded review packet (pathway A). Experts read complete examinations with NO detector output.
usage: python reference_audit/ws_prepare.py PACKET --studies M02,...,M15 --readers R1,R2 [--seed 20261119] [--link]
writes reference_audit/whole_scan/<PACKET>/:
  cases/<CODE>/  SWI (+ FLAIR, T1, GRE / phase if present) copied (or hard-linked with --link) under a blinded case code -
                 no candidate masks, no lists, no scores, no study code in file names
  reading_order_<reader>.csv   independent random order per reader
  lesion_annotations_<reader>.csv, patient_annotations_<reader>.csv   empty templates (EXPERT_ANNOTATION_TEMPLATE columns)
  key_CONCEALED.csv            CODE -> study_id (for the analyst only)
Readers mark each lesion's centre (x/y/z mm from the viewer, or voxel i/j/k) and may save a mask per case (ITK-SNAP / freeview) named
<CODE>_<reader>_lesions.nii.gz with one integer per lesion_id."""
import sys, os, shutil, json, time, numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ra_common as R
from annotation_schema import LESION_COLUMNS, PATIENT_COLUMNS

a = sys.argv[1:]
if not a or a[0].startswith("-"): sys.exit(__doc__)
arg = lambda k, d=None: a[a.index(k) + 1] if k in a else d
NAME = a[0]; studies = arg("--studies").split(","); readers = arg("--readers").split(","); rng = np.random.default_rng(int(arg("--seed", 20261119)))
out = os.path.join(R.OUT, "whole_scan", NAME)
if os.path.exists(out): sys.exit(f"packet {NAME} exists (never overwritten)")
os.makedirs(f"{out}/cases")
codes = [f"C{i + 1:03d}" for i in rng.permutation(len(studies))]
key = []
for sid, code in zip(studies, codes):
    d = f"{out}/cases/{code}"; os.makedirs(d); got = []
    for src, dst in ((f"data/{sid}_swi.nii", "SWI.nii"), (f"data/{sid}_swi.nii.gz", "SWI.nii.gz"), (f"data/{sid}_flair.nii.gz", "FLAIR.nii.gz"),
                     (f"work/{sid}_flair_swispace.nii.gz", "FLAIR_on_SWI.nii.gz"), (f"data/{sid}_t1.nii.gz", "T1.nii.gz"),
                     (f"data/{sid}_phase.nii.gz", "PHASE.nii.gz"), (f"data/{sid}_gre.nii.gz", "GRE.nii.gz")):
        p = os.path.join(R.B, src)
        if os.path.exists(p):
            (os.link if "--link" in a else shutil.copy2)(p, f"{d}/{dst}"); got.append(dst)
    key.append(dict(case_code=code, study_id=sid, files=";".join(got)))
pd.DataFrame(key).to_csv(f"{out}/key_CONCEALED.csv", index=False)
for rd in readers:
    order = [codes[i] for i in rng.permutation(len(codes))]
    pd.DataFrame(dict(order=range(1, len(order) + 1), case_code=order)).to_csv(f"{out}/reading_order_{rd}.csv", index=False)
    pd.DataFrame(columns=LESION_COLUMNS).to_csv(f"{out}/lesion_annotations_{rd}.csv", index=False)
    pd.DataFrame(columns=PATIENT_COLUMNS).to_csv(f"{out}/patient_annotations_{rd}.csv", index=False)
json.dump(dict(packet=NAME, studies=studies, readers=readers, created_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())), open(f"{out}/packet.json", "w"), indent=1)
print(f"{NAME}: {len(studies)} blinded cases for readers {readers} -> {out}")
