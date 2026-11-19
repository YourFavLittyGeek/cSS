"""Lists incomplete blind-read marks and, only with the options given, repairs them. A backup is written first.
usage: python reference_audit/blind_read/fix_incomplete.py PACKET READER                       (list only)
       python reference_audit/blind_read/fix_incomplete.py PACKET READER --drop-uncategorised --fill-hemisphere
--drop-uncategorised  removes marks that never got a category (placed but not classified)
--fill-hemisphere     fills an empty hemisphere from the mark's position (midline = centre of the brain in that axial slice,
                      the same rule the viewer uses). Categories, confidence and positions are never changed."""
import sys, os, time, shutil, numpy as np, pandas as pd, nibabel as nib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); import ra_common as R
a = sys.argv[1:]
if len(a) < 2: sys.exit(__doc__)
D = os.path.join(R.OUT, "whole_scan", a[0]); F = f"{D}/lesion_annotations_{a[1]}.csv"
d = pd.read_csv(F, dtype=str).fillna("")
nocat = d.final_category == ""; nohemi = (d.hemisphere == "") & ~nocat
print(f"{len(d)} marks: {int(nocat.sum())} without a category, {int(nohemi.sum())} with a category but no hemisphere")
for _, r in d[nocat | nohemi].iterrows():
    print(f"  {r.patient_id} #{r.lesion_id}  voxel {r.vox_i},{r.vox_j},{r.vox_k}  category '{r.final_category}'  hemisphere '{r.hemisphere}'")
if "--drop-uncategorised" not in a and "--fill-hemisphere" not in a: sys.exit(0)
os.makedirs(f"{D}/backups", exist_ok=True); bk = f"{D}/backups/" + os.path.basename(F).replace(".csv", f"_backup_{time.strftime('%Y%m%dT%H%M%S')}.csv"); shutil.copy2(F, bk); print("backup:", bk)
if "--drop-uncategorised" in a: d = d[~nocat].copy()
if "--fill-hemisphere" in a:
    cache = {}
    for i, r in d[(d.hemisphere == "") & (d.vox_i != "")].iterrows():
        c = r.patient_id
        if c not in cache:
            p = f"{D}/cases/{c}/" + ("SWI.nii" if os.path.exists(f"{D}/cases/{c}/SWI.nii") else "SWI.nii.gz"); img = nib.load(p)
            cache[c] = (np.asarray(img.dataobj, np.float32), img.affine[0, 0] > 0)
        I, i_to_right = cache[c]; k = int(r.vox_k); cols = np.nonzero((I[:, ::2, k] > np.percentile(I[I > 0], 5)).any(1))[0]
        if not len(cols): continue
        mid = (cols.min() + cols.max()) / 2; d.loc[i, "hemisphere"] = "R" if (int(r.vox_i) > mid) == i_to_right else "L"
        print(f"  {c} #{r.lesion_id}: hemisphere set to {d.loc[i, 'hemisphere']}")
d.to_csv(F, index=False); print(f"saved {len(d)} marks -> {F}")
