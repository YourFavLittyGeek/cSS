#!/usr/bin/env python3
"""Mesh-based vs mask-based pial distance (audit finding F1). Research software; expert review required.
usage: pial_compare.py M02,M03,...  [--reads Redo_v53,Blind_v57]
READ-ONLY. For every object (shown + excluded) it puts side by side
  mask distance   pial_dist_mm  (detect_css.py: signed distance to the LABELLED tissue mask, voxel resolution; - tissue, + CSF)
  mesh distance   surf_normal_dist_mm  (surface_features.py: signed distance to the FreeSurfer pial MESH along the vertex normal; same sign)
and reports, over the objects that have both:
  - agreement: Pearson r, bias (median mesh - mask), spread (MAD), 90th percentile of |difference|, objects whose two distances lie on
    DIFFERENT sides of the surface (one in tissue, one in CSF, both beyond 0.3 mm)
  - dependence on sulcal depth (surf_sulc > 0 sulcus / < 0 crown): is the difference larger in sulci?
  - which one separates cSS from not-cSS better: AUC of -distance for the objects you called (review/adjudication.csv replaces the reads),
    with the AUC difference and a bootstrap interval over objects
Reading it: if the median |difference| is below about half a voxel and the AUCs do not differ, the voxel-based distance is not what limits
the detector (F1 is not supported on these cases); a clear AUC gain for the mesh distance would justify a mesh-based zone.
Needs review/ID_surface_features.csv (run surface_features.py; recon-all cases only). Writes review/pial_compare.csv and pial_compare_summary.txt."""
import sys, os, numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from css_common import base as _base
import probe_common as pc

B = _base(); a = sys.argv[1:]
if not a or a[0].startswith("-"): sys.exit(__doc__)
ids = [s for s in a[0].split(",") if s]
reads = (a[a.index("--reads") + 1] if "--reads" in a else "Redo_v53,Blind_v57").split(",")


def auc(pos, neg):
    """Mann-Whitney AUC of 'larger score = positive'"""
    pos, neg = np.asarray(pos, float), np.asarray(neg, float)
    if not len(pos) or not len(neg): return np.nan
    allv = np.concatenate([pos, neg]); r = pd.Series(allv).rank().to_numpy()
    return float((r[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


rows, notes = [], []
for sid in ids:
    cp, sp = f"{B}/review/{sid}_candidates.csv", f"{B}/review/{sid}_surface_features.csv"
    if not (os.path.exists(cp) and os.path.exists(sp)): notes.append(f"{sid}: no candidates or no surface_features.csv (recon-all surfaces needed) - skipped"); continue
    cand = pd.read_csv(cp); sf = pd.read_csv(sp)
    xp = f"{B}/review/{sid}_excluded.csv"; xd = pd.read_csv(xp) if os.path.exists(xp) else pd.DataFrame()
    for fate, tab, key in (("shown", cand, "cand_id"), ("excluded", xd, "excl_id")):
        if not len(tab) or key not in tab.columns: continue
        s_ = sf[sf["list"] == ("candidate" if fate == "shown" else "excluded")].set_index("obj_id") if "list" in sf.columns else sf.set_index("obj_id")
        L = np.zeros(1, np.int32)
        cl = pc.object_calls(B, sid, fate, L, reads, cand) if fate == "shown" else pc.object_calls(B, sid, fate, L, reads)
        for _, r in tab.iterrows():
            oid = int(r[key]); srow = s_.loc[oid] if oid in s_.index else None
            row = dict(study_id=sid, fate=fate, obj_id=oid, region=str(r.get("region", "")), mask_dist_mm=r.get("pial_dist_mm", np.nan),
                       mesh_dist_mm=np.nan if srow is None else srow.get("surf_normal_dist_mm", np.nan),
                       surf_valid=np.nan if srow is None else srow.get("surf_valid", np.nan), surf_sulc=np.nan if srow is None else srow.get("surf_sulc", np.nan),
                       volume_mm3=r.get("volume_mm3", np.nan), **pc.summarize(cl.get(oid, [])))
            rows.append(row)
    print(f"{sid}: {sum(1 for r in rows if r['study_id'] == sid)} objects", flush=True)
if not rows: sys.exit("\n".join(notes) + "\nnothing to compare")
d = pc.apply_adjudication(pd.DataFrame(rows), B)
d["group"] = np.where(d.css_any == 1, "cSS (final)", np.where(d.non_css == 1, "not cSS (read)", "not read"))
d.to_csv(f"{B}/review/pial_compare.csv", index=False)
v = d[(d.surf_valid == 1) & d.mask_dist_mm.notna() & d.mesh_dist_mm.notna()].copy(); v["diff"] = v.mesh_dist_mm - v.mask_dist_mm
out = ["Mesh vs mask pial distance (research software; expert review required)", f"studies: {', '.join(ids)}", *notes, "",
       f"objects with both distances: {len(v)} of {len(d)} (shown {int((v.fate == 'shown').sum())}, excluded {int((v.fate == 'excluded').sum())})"]
if len(v) >= 5:
    ad = v["diff"].abs(); sign = ((v.mesh_dist_mm > 0.3) & (v.mask_dist_mm < -0.3)) | ((v.mesh_dist_mm < -0.3) & (v.mask_dist_mm > 0.3))
    out += [f"Pearson r {np.corrcoef(v.mesh_dist_mm, v.mask_dist_mm)[0, 1]:.2f}", f"bias (median mesh - mask) {v['diff'].median():+.2f} mm",
            f"spread (MAD) {1.4826 * (v['diff'] - v['diff'].median()).abs().median():.2f} mm", f"|difference| median {ad.median():.2f} mm, 90th percentile {ad.quantile(.9):.2f} mm",
            f"objects on different sides of the surface: {int(sign.sum())} of {len(v)} ({100 * sign.mean():.0f} %)", ""]
    if v.surf_sulc.notna().any():
        out.append("difference by sulcal depth (surf_sulc > 0 = in a sulcus):")
        for nm, g in (("sulcus", v[v.surf_sulc > 0]), ("crown", v[v.surf_sulc <= 0])):
            out.append(f"   {nm:<7} n={len(g):<4} median |diff| {g['diff'].abs().median():.2f} mm" if len(g) else f"   {nm}: none")
        out.append("")
    g = v[v.group != "not read"]; p, n_ = g[g.css_any == 1], g[g.css_any == 0]
    out.append(f"objects with a final call: cSS {len(p)}, not cSS {len(n_)}")
    if len(p) >= 5 and len(n_) >= 5:
        am, ae = auc(-p.mask_dist_mm, -n_.mask_dist_mm), auc(-p.mesh_dist_mm, -n_.mesh_dist_mm)
        rng = np.random.default_rng(1); dd = []
        for _ in range(500):
            ps, ns = p.sample(len(p), replace=True, random_state=int(rng.integers(1e9))), n_.sample(len(n_), replace=True, random_state=int(rng.integers(1e9)))
            dd.append(auc(-ps.mesh_dist_mm, -ns.mesh_dist_mm) - auc(-ps.mask_dist_mm, -ns.mask_dist_mm))
        lo, hi = np.percentile(dd, [2.5, 97.5])
        out += [f"AUC of -distance, cSS vs not cSS:  mask {am:.2f}   mesh {ae:.2f}   difference {ae - am:+.2f}  (bootstrap 95 % interval {lo:+.2f} .. {hi:+.2f})",
                "verdict: " + ("the mesh distance separates better - a mesh-based zone is worth testing" if lo > 0.02 else
                               "no clear gain from the mesh distance on these cases - the voxel-based distance is not what limits the detector (F1 not supported)")]
    else: out.append("too few called objects with both distances for an AUC")
else: out.append("too few objects with both distances (surface features missing or invalid)")
out.append("\nNothing was changed. Send review/pial_compare.csv and pial_compare_summary.txt.")
open(f"{B}/review/pial_compare_summary.txt", "w").write("\n".join(out) + "\n"); print("\n".join(out))
print(f"\nwrote {B}/review/pial_compare.csv and pial_compare_summary.txt")
