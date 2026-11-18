"""Object inventory for the reference-standard audit (read-only on production outputs).
usage: python reference_audit/inventory.py M02 M03 ...
For each study it collects EVERY object production produced, at every stage that is recorded:
  shown     review/ID_candidates.{csv,nii.gz}            (reached the reader)
  excluded  review/ID_excluded.{csv,nii.gz}              (rule exclusions incl. the confidence cut E30) - reason verbatim
  dropped   work/ID_dropped.{csv,nii.gz}                 (generation gates G1 volume / G2 slices / G3 elongation / G4 cortex)
Lesions that never became an object ("not generated") cannot be listed - they are found only by the whole-scan review.
Writes to $CSS_BASE/reference_audit/inventory/ (never to review/ or work/):
  ID_objects_public.csv     uid, stage-free location fields (safe to show a blinded reviewer AFTER sampling: no stage, no reason, no score)
  ID_objects_concealed.csv  uid, stage, exact reason, mechanism category, gate measured/threshold, score_v4, confidence, measurements
  ID_audit_objects.nii.gz   one label map, value = stage code x 100000 + production id (1 shown, 2 excluded, 3 dropped)
  inventory_manifest.json   sha256 of every production file read"""
import sys, os, json, time, numpy as np, pandas as pd, nibabel as nib
from scipy import ndimage as ndi
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ra_common as R

KEEP = ["score_v4", "score", "confidence_pct", "volume_mm3", "extent_mm", "n_slices", "elongation", "darkness_z", "edge_contrast", "cortex_frac",
        "pial_dist_mm", "tube_ratio", "struct_cls", "css_evidence", "vein_evidence", "skull_frac", "skullbase_frac", "midline_frac", "rel_height"]

def run(sid):
    out = os.path.join(R.OUT, "inventory"); os.makedirs(out, exist_ok=True)
    f = dict(cand=f"{R.B}/review/{sid}_candidates.csv", candm=f"{R.B}/review/{sid}_candidates.nii.gz", excl=f"{R.B}/review/{sid}_excluded.csv",
             exclm=f"{R.B}/review/{sid}_excluded.nii.gz", drop=f"{R.B}/work/{sid}_dropped.csv", dropm=f"{R.B}/work/{sid}_dropped.nii.gz",
             seg=f"{R.B}/work/{sid}_seg_swispace.nii.gz", swi=f"{R.B}/data/{sid}_swi.nii")
    miss = [k for k in ("cand", "candm", "excl", "exclm", "swi") if not os.path.exists(f[k])]
    if miss: sys.exit(f"{sid}: missing {[f[k] for k in miss]}")
    img = nib.load(f["swi"]); vox = img.header.get_zooms()[:3]; aff = img.affine
    seg = np.asarray(nib.load(f["seg"]).dataobj).astype(np.int32) if os.path.exists(f["seg"]) else None
    L = np.zeros(img.shape[:3], np.int32); pub, con = [], []
    for stage, cf, mf, idc in (("shown", f["cand"], f["candm"], "cand_id"), ("excluded", f["excl"], f["exclm"], "excl_id"), ("dropped", f["drop"], f["dropm"], "drop_id")):
        if not os.path.exists(cf) or not os.path.exists(mf): continue
        t = pd.read_csv(cf); M = np.asarray(nib.load(mf).dataobj).astype(np.int32)
        if not len(t): continue
        boxes = ndi.find_objects(M)                         # bounding boxes: thousands of dropped components stay fast
        for r in t.itertuples(index=False):
            r = r._asdict(); oid = int(r[idc])
            if oid < 1 or oid > len(boxes) or boxes[oid - 1] is None: continue
            sl = boxes[oid - 1]; m = M[sl] == oid
            L[sl][m] = R.label_value(stage, oid); c = np.argwhere(m).mean(0) + [s_.start for s_ in sl]; ci = np.round(c).astype(int)
            mm = aff @ np.r_[c, 1]
            lab = r.get("label")
            if (lab is None or pd.isna(lab) or not (1000 <= int(lab) < 3000)) and seg is not None:
                lab = R.nearest_cortex_label(seg, ci, 10.0, vox)
            region, lobe = R.region_lobe(lab)
            vol = float(m.sum() * np.prod(vox))
            u = R.uid(sid, stage, oid)
            pub.append(dict(uid=u, study_id=sid, vox_i=int(ci[0]), vox_j=int(ci[1]), vox_k=int(ci[2]), x_mm=round(mm[0], 1), y_mm=round(mm[1], 1),
                            z_mm=round(mm[2], 1), hemi=r.get("hemi", ""), lobe=lobe, region=region, size_bin=R.size_bin([vol])[0], n_vox=int(m.sum())))
            reason = "shown" if stage == "shown" else str(r.get("reason", ""))
            gate = r.get("gate_id", "") if stage == "dropped" else ""
            d = dict(uid=u, study_id=sid, stage=stage, production_id=oid, label_value=R.label_value(stage, oid), reason=reason,
                     mechanism="shown" if stage == "shown" else R.category(f"{gate} {reason}"), gate_id=gate,
                     gate_measured=r.get("measured", ""), gate_threshold=r.get("threshold", ""), volume_mask_mm3=round(vol, 1))
            for k in KEEP:
                if k in r: d[k] = r[k]
            con.append(d)
    nib.save(nib.Nifti1Image(L, aff), f"{out}/{sid}_audit_objects.nii.gz")
    P, C = pd.DataFrame(pub), pd.DataFrame(con)
    P.to_csv(f"{out}/{sid}_objects_public.csv", index=False); C.to_csv(f"{out}/{sid}_objects_concealed.csv", index=False)
    man = dict(study_id=sid, created_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), inputs={k: dict(path=v, sha256=R.sha(v)) for k, v in f.items() if os.path.exists(v)},
               counts=C.stage.value_counts().to_dict() if len(C) else {}, note="read-only inventory; production files are not modified")
    json.dump(man, open(f"{out}/{sid}_inventory_manifest.json", "w"), indent=1)
    print(f"{sid}: {len(C)} objects inventoried {man['counts']}")
    return C

if __name__ == "__main__":
    if len(sys.argv) < 2: sys.exit(__doc__)
    for s in sys.argv[1:]: run(s)
