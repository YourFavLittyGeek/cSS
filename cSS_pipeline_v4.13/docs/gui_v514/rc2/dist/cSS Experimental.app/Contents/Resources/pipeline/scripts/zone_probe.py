#!/usr/bin/env python3
"""Anatomical zone probe. Research software; expert review required.
usage: zone_probe.py M02,M03,...  [--reads Redo_v53,Blind_v57]
READ-ONLY. For every object the detector produced (shown candidates + excluded objects) it measures where the object lies in a
compartment map built from the FreeSurfer / SynthSeg labels, next to your calls. Nothing in the project is changed.
Compartments (labels = work/ID_seg_swispace.nii.gz):
  outside_hull_frac    share of the object's voxels OUTSIDE a smooth hull of the cerebrum (closing radius 8 mm): skull, dura, anything
                       outside the brain. hull_out_mm = median distance of those voxels outside the hull.
  cortex_contact_frac  share of voxels within 1 mm of cerebral cortex (cSS lies ON the cortical surface; contact protects it)
  free_csf_frac        share of voxels in non-tissue space inside the hull more than 1 mm from any cortex (free CSF, ventricles, cisterns)
  infra_near_frac      share of voxels whose nearest tissue is cerebellum / brainstem (within 5 mm)
  skullbase_frac       share of voxels whose nearest cortex is orbitofrontal / frontal pole / temporal pole / entorhinal /
                       parahippocampal / fusiform / inferior temporal (the air-bone and tentorial surfaces); rel_z = height of the
                       object in the cerebrum (0 = floor, 1 = vertex)
  fissure_frac         share of voxels in the interhemispheric fissure: non-tissue, inside the hull, left AND right hemisphere tissue
                       both within 15 mm (any fissure width)
  fissure_side_bias    median |dL - dR| / (dL + dR) over the fissure voxels (0 = centred between the hemispheres, 1 = hugging one side; NaN = none)
  dual_contact_frac    share with left cortex AND right cortex both within 3 mm
  cos_plane / plane_dist_mm / ext_major_mm   sheet orientation vs the mid-sagittal plane (as midline_probe.py)
Reads: every name in --reads (default Redo_v53,Blind_v57): calls of shown objects from ID_calls_<name>.csv (fingerprint match; a study
with none of those files falls back to the shared ID_calls.csv of the first read);
calls of excluded objects from ID_excluded_audit_<name>.csv and from the pre-redetect snapshot (review/changes, old calls mapped by
voxel overlap). css_any = any read called it cSS (these are PROTECTED when rules are fitted); css_all = every read of it said cSS;
non_css = read at least once and never called cSS.
review/adjudication.csv (study_id,fate,obj_id,call), if present, holds your FINAL decisions and replaces the reads for those objects.
Writes review/zone_probe.csv and zone_probe_summary.txt: distributions by group, the protected cSS objects closest to each zone, and a grid
per rule: protected cSS flagged / shown non-cSS flagged / margin of the nearest protected cSS."""
import sys, os, re, itertools, numpy as np, pandas as pd, nibabel as nib
from scipy import ndimage as ndi
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from css_common import base as _base, match_calls

B = _base(); a = sys.argv[1:]
if not a or a[0].startswith("-"): sys.exit(__doc__)
ids = [s for s in a[0].split(",") if s]
reads = (a[a.index("--reads") + 1] if "--reads" in a else "Redo_v53,Blind_v57").split(",")
slug = lambda s: re.sub(r"[^A-Za-z0-9]+", "_", s.strip()).strip("_") or "reviewer"
CH = f"{B}/review/changes"
SB_LABELS = {1012, 1014, 1032, 1033, 1006, 1016, 1007, 1009, 1019}       # lateral/medial orbitofrontal, frontal pole, temporal pole, entorhinal, parahippocampal, fusiform, inferior temporal, pars orbitalis
SB_LABELS |= {x + 1000 for x in SB_LABELS}
INFRA = (7, 8, 15, 16, 46, 47)                                           # cerebellum WM / cortex, 4th ventricle, brainstem


def lab(p): return np.asanyarray(nib.load(p).dataobj).astype(np.int32)


def old_calls_onto(sid, new_lab):
    pc, pl, pk = f"{CH}/{sid}_before_candidates.csv", f"{CH}/{sid}_before_candidates.nii.gz", f"{CH}/{sid}_before_calls.csv"
    old_dir = f"{B}/review/old_calls_before_redo/{sid}_calls.csv"
    pk = pk if os.path.exists(pk) else old_dir
    if not (os.path.exists(pc) and os.path.exists(pl) and os.path.exists(pk)): return {}
    oc, calls = pd.read_csv(pc), pd.read_csv(pk); m, _ = match_calls(oc, calls)
    if not m: return {}
    old = lab(pl); out = {}
    for cid, call in m.items():
        if not isinstance(call, str) or not call: continue
        v = new_lab[old == cid]; v = v[v > 0]
        for l in np.unique(v):
            if (v == l).sum() >= max(3, 0.1 * (old == cid).sum()): out.setdefault(int(l), []).append("first:" + call)
    return out


rows = []
for sid in ids:
    need = [f"{B}/data/{sid}_swi.nii", f"{B}/work/{sid}_seg_swispace.nii.gz", f"{B}/review/{sid}_candidates.csv", f"{B}/review/{sid}_candidates.nii.gz"]
    if any(not os.path.exists(p) for p in need): print(f"{sid}: missing input - skipped"); continue
    swi = nib.load(need[0]); vox = np.array(swi.header.get_zooms()[:3], float); seg = lab(need[1])
    Lcx = ((seg >= 1000) & (seg < 2000)) | (seg == 3); Rcx = ((seg >= 2000) & (seg < 3000)) | (seg == 42); cx = Lcx | Rcx
    Lh, Rh = Lcx | (seg == 2), Rcx | (seg == 41)
    infra = np.isin(seg, INFRA); deep = np.isin(seg, (10, 11, 12, 13, 17, 18, 26, 28, 49, 50, 51, 52, 53, 54, 58, 60))
    cerebrum = Lh | Rh | deep
    if Lh.sum() < 1000 or Rh.sum() < 1000: print(f"{sid}: labels have no two hemispheres - skipped"); continue
    edt = lambda m: ndi.distance_transform_edt(~m, sampling=vox).astype(np.float32)
    # hull of the cerebrum: closing with an 8 mm ball done with distance transforms, then holes filled
    grown = edt(cerebrum) <= 8.0
    closed = ndi.distance_transform_edt(grown, sampling=vox) > 8.0
    hull = ndi.binary_fill_holes(closed | cerebrum); del grown, closed
    dHull = ndi.distance_transform_edt(~hull, sampling=vox).astype(np.float32)           # distance outside the hull (0 inside)
    tissue = cerebrum | infra
    dCx, dLc, dRc, dLh, dRh, dInf = edt(cx), edt(Lcx), edt(Rcx), edt(Lh), edt(Rh), edt(infra)
    near_cx_lab = None
    # label of the nearest cortex voxel (for the skull-base zone) - computed lazily per object from the index map
    idx = ndi.distance_transform_edt(~cx, sampling=vox, return_distances=False, return_indices=True)
    hl = dLh <= dRh; bd = hl & ndi.binary_dilation(~hl) & (dLh <= 8) & (dRh <= 8); P0 = np.argwhere(bd) * vox
    pc = P0.mean(0) if len(P0) >= 100 else None
    mvec = np.linalg.svd(P0[:: max(1, len(P0) // 20000)] - pc, full_matrices=False)[2][2] if pc is not None else None
    zc = np.argwhere(cerebrum)[:, 2] if cerebrum.any() else np.array([0, 1]); zlo, zhi = zc.min(), zc.max()
    objs = []
    cand = pd.read_csv(need[2]); L1 = lab(need[3]); objs.append(("shown", cand.set_index("cand_id"), L1))
    xp, xl = f"{B}/review/{sid}_excluded.csv", f"{B}/review/{sid}_excluded.nii.gz"
    if os.path.exists(xp) and os.path.exists(xl):
        xd = pd.read_csv(xp)
        if len(xd) and "excl_id" in xd.columns: objs.append(("excluded", xd.set_index("excl_id"), lab(xl)))
    for fate, tab, L in objs:
        calls_of = {}                                                    # object id -> list of "read:call"
        if fate == "shown":
            have = False
            for rd in reads:
                f = f"{B}/review/{sid}_calls_{slug(rd)}.csv"
                if os.path.exists(f):
                    have = True
                    m, _ = match_calls(cand, pd.read_csv(f))
                    for k, v in (m or {}).items():
                        if isinstance(v, str) and v: calls_of.setdefault(int(k), []).append(f"{rd}:{v}")
            if not have:                      # studies without a named read (e.g. M07-M11): the shared file of the first read
                for f in (f"{B}/review/{sid}_calls.csv", f"{B}/review/old_calls_before_redo/{sid}_calls.csv"):
                    if os.path.exists(f):
                        m, _ = match_calls(cand, pd.read_csv(f))
                        for k, v in (m or {}).items():
                            if isinstance(v, str) and v: calls_of.setdefault(int(k), []).append(f"shared:{v}")
                        break
        else:
            for rd in reads:
                f = f"{B}/review/{sid}_excluded_audit_{slug(rd)}.csv"
                if os.path.exists(f):
                    for _, r in pd.read_csv(f).iterrows():
                        if isinstance(r.call, str) and r.call: calls_of.setdefault(int(r.excl_id), []).append(f"{rd}:{r.call}")
        for k, v in old_calls_onto(sid, L).items(): calls_of.setdefault(k, []).extend(v)
        for oid, r in tab.iterrows():
            idxs = np.argwhere(L == int(oid))
            if len(idxs) < 5: continue
            sel = tuple(idxs.T); P = idxs * vox
            nt = ~tissue[sel]                                            # voxels in non-tissue space
            dc = dCx[sel]
            fis = (nt & hull[sel] & (dLh[sel] <= 15) & (dRh[sel] <= 15))
            dl, dr = dLh[sel], dRh[sel]
            nearest = seg[tuple(idx[:, sel[0], sel[1], sel[2]])]       # label of the nearest cortex voxel
            Q = P - P.mean(0); w, v = np.linalg.eigh(np.cov(Q.T)); ext = np.ptp(Q @ v, axis=0)
            cl = calls_of.get(int(oid), [])
            callnames = [c.split(":", 1)[1] for c in cl]
            reads_css = [c for c in callnames if c == "cSS"]
            rows.append(dict(study_id=sid, fate=fate, obj_id=int(oid), calls=" | ".join(cl), n_calls=len(callnames), n_css=len(reads_css),
                             css_any=int(len(reads_css) > 0), css_all=int(len(callnames) > 0 and len(reads_css) == len(callnames)),
                             non_css=int(len(callnames) > 0 and not reads_css), region=str(r.get("region", "")), hemi=r.get("hemi", ""),
                             volume_mm3=round(len(idxs) * vox.prod(), 1), reason=str(r.get("reason", "")).split(":")[0].split(" (")[0] if fate == "excluded" else "",
                             outside_hull_frac=round(float((dHull[sel] > 0).mean()), 2), hull_out_mm=round(float(np.median(dHull[sel])), 1),
                             cortex_contact_frac=round(float((dc <= 1.0).mean()), 2),
                             free_csf_frac=round(float((nt & hull[sel] & (dc > 1.0)).mean()), 2),
                             infra_near_frac=round(float(((dInf[sel] < dc) & (dInf[sel] <= 5.0)).mean()), 2),
                             skullbase_frac=round(float(np.isin(nearest, list(SB_LABELS)).mean()), 2),
                             rel_z=round(float((np.median(idxs[:, 2]) - zlo) / max(zhi - zlo, 1)), 2),
                             fissure_frac=round(float(fis.mean()), 2),
                             fissure_side_bias=round(float(np.median((np.abs(dl - dr) / np.maximum(dl + dr, 1e-3))[fis])), 2) if fis.any() else np.nan,
                             dual_contact_frac=round(float(((dLc[sel] <= 3) & (dRc[sel] <= 3)).mean()), 2),
                             plane_dist_mm=round(float(np.median(np.abs((P - pc) @ mvec))), 1) if pc is not None else np.nan,
                             cos_plane=round(float(abs(v[:, 0] @ mvec)), 2) if pc is not None else np.nan, ext_major_mm=round(float(ext[2]), 1),
                             detector_midline_frac=r.get("midline_frac", np.nan)))
    print(f"{sid}: {sum(1 for r in rows if r['study_id'] == sid)} objects measured", flush=True)
    del idx, dCx, dLc, dRc, dLh, dRh, dInf, dHull
if not rows: sys.exit("nothing measured")
import probe_common as _pc
d = _pc.apply_adjudication(pd.DataFrame(rows), B); d["group"] = np.where(d.css_any == 1, "cSS (any read)", np.where(d.non_css == 1, "not cSS (read)", "not read"))
d.to_csv(f"{B}/review/zone_probe.csv", index=False)
out = ["Anatomical zone probe (research software; expert review required)", f"studies: {', '.join(ids)}   reads: {', '.join(reads)}", "",
       "Objects by fate and group (cSS (any read) = PROTECTED when rules are fitted):", pd.crosstab(d.group, d.fate, margins=True).to_string(), ""]
FE = ["outside_hull_frac", "cortex_contact_frac", "free_csf_frac", "infra_near_frac", "skullbase_frac", "fissure_frac", "fissure_side_bias", "dual_contact_frac"]
for f in FE:
    out.append(f"{f}: median [10th-90th] by group")
    for g_, g in d.groupby("group"):
        q = g[f].quantile([.1, .5, .9]).round(2).tolist(); out.append(f"   {g_:<16} n={len(g):<4} {q[1]}  [{q[0]} - {q[2]}]")
    out.append("")
prot = d[d.css_any == 1]
for f in ("outside_hull_frac", "free_csf_frac", "infra_near_frac", "skullbase_frac", "fissure_frac", "dual_contact_frac"):
    out.append(f"PROTECTED cSS objects with the highest {f} (a rule on it must stay above these):")
    out.append(prot.sort_values(f, ascending=False).head(5)[["study_id", "fate", "obj_id", "region", "reason", "calls", f, "cortex_contact_frac", "volume_mm3"]].to_string(index=False)); out.append("")
RULES = {
    "OUT  outside the hull":        lambda g, t, c: (g.outside_hull_frac >= t) & (g.cortex_contact_frac < c),
    "INFRA cerebellum/brainstem":   lambda g, t, c: (g.infra_near_frac >= t) & (g.cortex_contact_frac < c),
    "SKULLBASE orbitofrontal etc.": lambda g, t, c: (g.skullbase_frac >= t) & (g.rel_z <= 0.45),
    "FISSURE free in the fissure":  lambda g, t, c: (g.fissure_frac >= t) & (g.fissure_side_bias <= c),
    "CSF free CSF":                 lambda g, t, c: (g.free_csf_frac >= t) & (g.cortex_contact_frac < c),
}
GRID = {"OUT  outside the hull": ([.3, .5, .7, .9], [.2, .4, .6]), "INFRA cerebellum/brainstem": ([.3, .5, .7, .9], [.2, .4, .6]),
        "SKULLBASE orbitofrontal etc.": ([.5, .7, .9], [0]), "FISSURE free in the fissure": ([.3, .5, .7, .9], [.3, .5, .7]),
        "CSF free CSF": ([.3, .5, .7, .9], [.2, .4, .6])}
res = []
for nm, fn in RULES.items():
    ts, cs = GRID[nm]
    for t, c in itertools.product(ts, cs):
        fl = fn(d, t, c); sh = d.fate == "shown"
        res.append(dict(rule=nm, t=t, c=c, protected_cSS_flagged=int((fl & (d.css_any == 1)).sum()), of_protected=int((d.css_any == 1).sum()),
                        shown_nonCSS_flagged=int((fl & sh & (d.non_css == 1)).sum()), shown_unread_flagged=int((fl & sh & (d.group == "not read")).sum()),
                        excluded_flagged=int((fl & ~sh).sum()), excluded_of=int((~sh).sum())))
g = pd.DataFrame(res)
out.append("Rule grid (flag = rule says exclude).  protected_cSS_flagged must be 0.  shown_nonCSS_flagged = gain (objects still shown that the rule would remove).")
out.append("excluded_flagged / excluded_of = how many already-excluded objects the rule would ALSO catch (a check that the zone map agrees with the old rules).")
for nm in RULES:
    s = g[g.rule == nm]; safe = s[s.protected_cSS_flagged == 0].sort_values(["shown_nonCSS_flagged", "excluded_flagged"], ascending=False)
    out.append(f"\n{nm}: safe settings (best first)")
    out.append(safe.head(6)[["t", "c", "protected_cSS_flagged", "shown_nonCSS_flagged", "shown_unread_flagged", "excluded_flagged", "excluded_of"]].to_string(index=False) if len(safe) else "   none: every setting tried flags a protected cSS")
out.append("\nNothing was changed. Send review/zone_probe.csv and zone_probe_summary.txt back to fit the zone rules.")
open(f"{B}/review/zone_probe_summary.txt", "w").write("\n".join(out) + "\n"); print("\n".join(out))
print(f"\nwrote {B}/review/zone_probe.csv and zone_probe_summary.txt")
