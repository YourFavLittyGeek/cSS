"""Lists every input the validation needs per study and whether it exists. Writes RUN/MISSING_INPUTS.txt and
RUN/inputs_inventory.csv. Exit 1 if a REQUIRED input is missing. Usage: check_inputs.py RUN DEV_IDS... -- HELDOUT_IDS..."""
import sys, os, glob, pandas as pd
run = sys.argv[1]; a = sys.argv[2:]; k = a.index("--") if "--" in a else len(a); dev, held = a[:k], a[k + 1:]
B = os.environ["CSS_BASE"]
REQ = {"SWI image": "data/{id}_swi.nii", "pial signed distance": "work/{id}_pial_sd.nii.gz", "labels on SWI grid": "work/{id}_seg_swispace.nii.gz",
       "candidate list": "review/{id}_candidates.csv", "candidate mask": "review/{id}_candidates.nii.gz", "excluded list": "review/{id}_excluded.csv",
       "excluded mask": "review/{id}_excluded.nii.gz"}
OPT = {"dropped mask": "work/{id}_dropped.nii.gz", "shared calls": "review/{id}_calls.csv", "missed-lesion marks": "review/{id}_missed.csv"}
rows, miss = [], []
for sid in dev + held:
    for kind, d in ((1, REQ), (0, OPT)):
        for nm, p in d.items():
            f = os.path.join(B, p.format(id=sid)); ok = os.path.exists(f) or (f.endswith(".nii") and os.path.exists(f + ".gz"))
            rows.append(dict(study_id=sid, cohort="dev" if sid in dev else "heldout", input=nm, path=p.format(id=sid), required=bool(kind), present=ok))
            if kind and not ok: miss.append(f"{sid}: {nm} ({p.format(id=sid)})")
    rd = sorted(glob.glob(f"{B}/review/{sid}_calls_*.csv"))
    rows.append(dict(study_id=sid, cohort="dev" if sid in dev else "heldout", input="per-reader calls", path=";".join(os.path.basename(x) for x in rd), required=True, present=bool(rd) or os.path.exists(f"{B}/review/{sid}_calls.csv")))
    if not rd and not os.path.exists(f"{B}/review/{sid}_calls.csv"): miss.append(f"{sid}: no reader calls (review/{sid}_calls_<reader>.csv or review/{sid}_calls.csv)")
g = f"{B}/review/radiologist_grades.csv"
rows.append(dict(study_id="all", cohort="", input="radiologist patient-level grades", path="review/radiologist_grades.csv", required=True, present=os.path.exists(g)))
if not os.path.exists(g): miss.append("radiologist grades: review/radiologist_grades.csv (study_id,R,L)")
else:
    gg = pd.read_csv(g); lack = sorted(set(dev + held) - set(gg.study_id.astype(str)))
    if lack: miss.append(f"radiologist grades lack {lack}")
pd.DataFrame(rows).to_csv(f"{run}/inputs_inventory.csv", index=False)
open(f"{run}/MISSING_INPUTS.txt", "w").write("\n".join(miss) + ("\n" if miss else "nothing missing\n"))
print(f"inputs: {sum(r['present'] for r in rows)}/{len(rows)} present; missing required: {len(miss)}")
for m in miss: print("  MISSING", m)
sys.exit(1 if miss else 0)
