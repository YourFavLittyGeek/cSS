#!/usr/bin/env python3
"""Midline / interhemispheric-fissure probe. Research software; expert review required.
usage: midline_probe.py M02,M03,...  [--calls-dir DIR]
READ-ONLY: measures, for every object the detector produced (shown candidates + excluded objects), how much it looks like
the interhemispheric fissure (falx / sagittal sinus / fissure veins between the two hemispheres) rather than a sulcus
inside one hemisphere (calcarine, parieto-occipital, ...), and prints it next to your calls. Nothing in the project is changed.
Measures per object (labels = work/ID_seg_swispace.nii.gz, the same labels the detector uses):
  mid_local_frac  share of the object's voxels that sit in the gap BETWEEN the hemispheres: nearest left and right
                  hemisphere tissue (cortex + white matter) equally far (+-1.5 mm) and both within 4 mm   (local, follows a curved fissure)
  both3_frac      share of voxels with LEFT cortex and RIGHT cortex both within 3 mm (a sulcus has one hemisphere on both banks)
  equi_med_mm     median |distance to left cortex - distance to right cortex|  (small = in the middle of the fissure)
  hug_med_mm      median distance to the NEAREST cortex (cSS hugging the pial surface is ~0-1.5 mm)
  plane_dist_mm   median distance to the fitted mid-sagittal plane (global)
  cos_plane       |cosine| between the object's thin axis and the plane normal (1 = a flat sheet lying in the sagittal plane)
  thin_ratio      thin / middle axis length (small = sheet);  ext_major_mm, ext_mid_mm, ext_thin_mm: extents along its axes
Reader call per object: from review/changes/ID_before_* (snapshot made before redetect --v53: old calls mapped by voxel overlap),
else from ID_calls.csv (also looked up in review/old_calls_before_redo or --calls-dir) matched by fingerprint.
Writes review/midline_probe.csv and review/midline_probe_summary.txt: call-by-call distributions and a grid of candidate rules
with how many of your cSS calls each would remove (the safe ones remove none)."""
import sys, os, itertools, numpy as np, pandas as pd, nibabel as nib
from scipy import ndimage as ndi
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from css_common import base as _base, match_calls

B = _base()
a = sys.argv[1:]
if not a or a[0].startswith("-"): sys.exit(__doc__)
ids = [s for s in a[0].split(",") if s]
cdir = a[a.index("--calls-dir") + 1] if "--calls-dir" in a else None


def lab(p): return np.asanyarray(nib.load(p).dataobj).astype(np.int32)


def old_calls_onto_objects(sid, new_lab):
    """{label in new_lab: set(call)} from the pre-redetect snapshot (old candidate voxels carry the old calls)"""
    ch = f"{B}/review/changes"
    pc, pl, pk = f"{ch}/{sid}_before_candidates.csv", f"{ch}/{sid}_before_candidates.nii.gz", f"{ch}/{sid}_before_calls.csv"
    if not all(os.path.exists(p) for p in (pc, pl, pk)): return None
    oc, calls = pd.read_csv(pc), pd.read_csv(pk); m, _ = match_calls(oc, calls)
    if not m: return None
    old = lab(pl); out = {}
    for cid, call in m.items():
        if not isinstance(call, str) or not call: continue
        v = new_lab[old == cid]; v = v[v > 0]
        for l in np.unique(v):
            if (v == l).sum() >= max(3, 0.1 * (old == cid).sum()): out.setdefault(int(l), set()).add(call)
    return out


def current_calls(sid, cand):
    for d in [x for x in (cdir, f"{B}/review/old_calls_before_redo", f"{B}/review") if x]:
        p = f"{d}/{sid}_calls.csv"
        if os.path.exists(p):
            m, _ = match_calls(cand, pd.read_csv(p))
            if m: return {int(k): {v} for k, v in m.items() if isinstance(v, str) and v}
    return {}


rows = []
for sid in ids:
    need = [f"{B}/data/{sid}_swi.nii", f"{B}/work/{sid}_seg_swispace.nii.gz", f"{B}/review/{sid}_candidates.csv", f"{B}/review/{sid}_candidates.nii.gz"]
    if any(not os.path.exists(p) for p in need): print(f"{sid}: missing input - skipped"); continue
    swi = nib.load(need[0]); vox = np.array(swi.header.get_zooms()[:3], float); seg = lab(need[1])
    Lcx = ((seg >= 1000) & (seg < 2000)) | (seg == 3); Rcx = ((seg >= 2000) & (seg < 3000)) | (seg == 42)
    Lh, Rh = Lcx | (seg == 2), Rcx | (seg == 41)
    if Lh.sum() < 1000 or Rh.sum() < 1000: print(f"{sid}: labels have no two hemispheres - skipped"); continue
    edt = lambda m: ndi.distance_transform_edt(~m, sampling=vox)
    dLc, dRc, dLh, dRh = edt(Lcx), edt(Rcx), edt(Lh), edt(Rh)
    hemiL = dLh <= dRh; bd = hemiL & ndi.binary_dilation(~hemiL) & (dLh <= 8) & (dRh <= 8); P0 = np.argwhere(bd) * vox   # boundary between the two hemisphere territories (as the detector)
    if len(P0) < 100: print(f"{sid}: no hemisphere boundary found - skipped"); continue
    pc = P0.mean(0); mvec = np.linalg.svd(P0[:: max(1, len(P0) // 20000)] - pc, full_matrices=False)[2][2]
    objs = []
    cand = pd.read_csv(need[2]); L1 = lab(need[3]); objs.append(("shown", cand.set_index("cand_id"), L1))
    xp, xl = f"{B}/review/{sid}_excluded.csv", f"{B}/review/{sid}_excluded.nii.gz"
    if os.path.exists(xp) and os.path.exists(xl):
        xd = pd.read_csv(xp)
        if len(xd) and "excl_id" in xd.columns: objs.append(("excluded", xd.set_index("excl_id"), lab(xl)))
    calls_new = None
    for fate, tab, L in objs:
        cmap = old_calls_onto_objects(sid, L) if calls_new is None else None
        if fate == "shown":
            if cmap is None: cmap = {}
            cur = current_calls(sid, cand) if not cmap else {}
            for k, v in cur.items(): cmap.setdefault(k, set()).update(v)
        for oid, r in tab.iterrows():
            idx = np.argwhere(L == int(oid))
            if len(idx) < 5: continue
            P = idx * vox; sel = tuple(idx.T)
            dl, dr, hl, hr = dLc[sel], dRc[sel], dLh[sel], dRh[sel]
            C = np.cov((P - P.mean(0)).T); w, v = np.linalg.eigh(C)
            pr = (P - P.mean(0)) @ v; ext = np.ptp(pr, axis=0)
            rows.append(dict(study_id=sid, fate=fate, obj_id=int(oid), reader_call="+".join(sorted(cmap.get(int(oid), set()))) if cmap else "",
                             hemi=r.get("hemi", ""), region=str(r.get("region", "")), volume_mm3=round(len(idx) * vox.prod(), 1),
                             reason=str(r.get("reason", "")).split(":")[0].split(" (")[0] if fate == "excluded" else "",
                             midline_frac_detector=r.get("midline_frac", np.nan),
                             mid_local_frac=round(float(((np.abs(hl - hr) <= 1.5) & (hl <= 4) & (hr <= 4)).mean()), 2),
                             both3_frac=round(float(((dl <= 3) & (dr <= 3)).mean()), 2),
                             equi_med_mm=round(float(np.median(np.abs(dl - dr))), 1), hug_med_mm=round(float(np.median(np.minimum(dl, dr))), 1),
                             plane_dist_mm=round(float(np.median(np.abs((P - pc) @ mvec))), 1),
                             cos_plane=round(float(abs(v[:, 0] @ mvec)), 2), thin_ratio=round(float(np.sqrt(max(w[0], 0) / max(w[1], 1e-6))), 2),
                             ext_major_mm=round(float(ext[2]), 1), ext_mid_mm=round(float(ext[1]), 1), ext_thin_mm=round(float(ext[0]), 1)))
    calls_new = True
    print(f"{sid}: {sum(1 for r in rows if r['study_id'] == sid)} objects measured", flush=True)
if not rows: sys.exit("nothing measured")
d = pd.DataFrame(rows); d["call"] = d.reader_call.replace("", "(not read)")
d.to_csv(f"{B}/review/midline_probe.csv", index=False)
out = ["Midline probe (research software; expert review required)", f"studies: {', '.join(ids)}", ""]
out.append("Objects by fate and reader call:"); out.append(pd.crosstab(d.call, d.fate, margins=True).to_string()); out.append("")
feats = ["mid_local_frac", "both3_frac", "equi_med_mm", "hug_med_mm", "plane_dist_mm", "cos_plane", "thin_ratio"]
for f in feats:
    out.append(f"{f}: median [10th-90th percentile] by call")
    for c, g in d.groupby("call"):
        q = g[f].quantile([.1, .5, .9]).round(2).tolist(); out.append(f"   {c:<12} n={len(g):<4} {q[1]}  [{q[0]} - {q[2]}]")
    out.append("")
css = d[d.call.str.contains("cSS")]
if len(css):
    out.append("The cSS objects that look most like the fissure (the ones a rule must NOT catch):")
    out.append(css.sort_values("mid_local_frac", ascending=False).head(8)[["study_id", "obj_id", "fate", "region", "mid_local_frac", "both3_frac", "equi_med_mm", "hug_med_mm", "cos_plane", "volume_mm3"]].to_string(index=False)); out.append("")
rd = d[d.call != "(not read)"]
res = []
for a_, b_, c_ in itertools.product([.3, .4, .5, .6, .7], [0, .6, .8], [0, .3, .5]):
    flag = (d.mid_local_frac >= a_) & (d.cos_plane >= b_) & (d.both3_frac >= c_) & (d.fate == "shown")
    fr = flag[rd.index.intersection(d.index)] if False else flag.loc[rd.index]
    res.append(dict(mid_local_ge=a_, cos_plane_ge=b_, both3_ge=c_, cSS_lost=int((fr & rd.call.str.contains("cSS")).sum()),
                    of_cSS=int(rd.call.str.contains("cSS").sum()), non_cSS_removed=int((fr & ~rd.call.str.contains("cSS")).sum()),
                    unread_removed=int((flag & (d.call == "(not read)")).sum())))
g = pd.DataFrame(res); safe = g[g.cSS_lost == 0].sort_values(["non_cSS_removed", "mid_local_ge"], ascending=[False, False])
out.append("Candidate rules applied to the objects still SHOWN (rule = all three conditions): cSS calls lost / other calls removed")
out.append("Rules that lose no cSS call (best first):"); out.append(safe.head(12).to_string(index=False) if len(safe) else "   none: every rule tried loses a cSS call")
out.append(""); out.append("Nothing was changed. Send review/midline_probe.csv and midline_probe_summary.txt back to set the rule.")
open(f"{B}/review/midline_probe_summary.txt", "w").write("\n".join(out) + "\n"); print("\n".join(out))
print(f"\nwrote {B}/review/midline_probe.csv and midline_probe_summary.txt")
