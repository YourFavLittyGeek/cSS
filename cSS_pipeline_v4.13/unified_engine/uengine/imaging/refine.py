"""ALBUS outline refinement (2026-11-28, audit 2026-11-27 Doc 4 / Milestone 3): a deterministic, interpretable extent for every candidate.

Why: the detector's candidate mask (and the outline the reviewer sees) is the RIDGE CORE - voxels that are dark (z < -2) AND among the top
20 % of a 2-D Sato ridge response. Blooming margins and the flat centre of wide bands drop out, so the outline is narrower and more
fragmented than the visible lesion. The full extent already existed only for ACCEPTED candidates at scoring (score_css.py: grown into the
detector's dark map, <= 5 mm), and was never shown.

What (one rule, the same as score_css's grading mask, applied to EVERY candidate):
  extent_i = 6-connected propagation from candidate i's core through the detector's dark map work/ID_dark.nii.gz (= detector search zone AND
             darkness z < -1.5: pial band, minus white matter / deep nuclei / the skull-strip rim), limited to GROW_MM (5 mm) from the core;
             a voxel reachable from two candidates goes to the nearer core (no overlapping outlines);
  measures   core / extent volume, growth ratio, slices, extent (mm), thickness (2 x median inscribed radius, mm), inside / outside contrast
             (median SWI inside vs a 1-2 mm ring), and 'cap_frac' = share of the extent at the 5 mm limit (a leak warning: the growth was
             stopped by the limit, not by the image).
It never decides that something is cSS: it outlines, it measures. Outputs (derived, versioned): review/ID_candidates_extent.nii.gz (int16,
candidate ids, SWI grid) + review/ID_extent.csv + review/ID_extent.json (version, inputs sha256)."""
import hashlib, json, os
import numpy as np
from scipy import ndimage as ndi

VERSION = "albus-extent/1.0"
GROW_MM = 5.0                       # = score_css.GROW_MM (the grading mask)
CAP_WARN = 0.2


def _sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()[:16]


def refine(lab, dark, swi, vox, grow_mm=GROW_MM):
    """lab: int candidate label map (core), dark: bool dark map, swi: float image, vox: voxel size mm -> (extent label map, {id: measures})"""
    lab = np.asarray(lab).astype(np.int32); dark = np.asarray(dark, bool); vox = np.asarray(vox, float)[:3]
    cores = lab > 0
    if not cores.any(): return np.zeros(lab.shape, np.int16), {}
    dist, (ii, jj, kk) = ndi.distance_transform_edt(~cores, sampling=vox, return_indices=True)
    nearest = lab[ii, jj, kk]                                            # id of the nearest core (Voronoi in mm)
    allowed = (dark & (dist <= grow_mm)) | cores
    grown = ndi.binary_propagation(cores, structure=ndi.generate_binary_structure(3, 1), mask=allowed)
    ext = np.where(grown, nearest, 0).astype(np.int16)
    # a voxel assigned to a core it is not connected to (through the Voronoi split) is dropped
    out = np.zeros(lab.shape, np.int16); M = {}
    objs = ndi.find_objects(ext); mg = np.ceil(3.0 / vox).astype(int) + 1             # margin for the 1-2 mm contrast ring
    for i, sl in enumerate(objs, start=1):
        if sl is None: continue
        pad = tuple(slice(max(s.start - m_, 0), min(s.stop + m_, n)) for s, m_, n in zip(sl, mg, lab.shape))
        e = ext[pad] == i; c = lab[pad] == i
        if not c.any(): continue
        L_, _ = ndi.label(e, structure=ndi.generate_binary_structure(3, 1)); keep = np.isin(L_, np.unique(L_[c & e])[np.unique(L_[c & e]) > 0]) | c
        out[pad][keep] = i
        sub = keep; v3 = float(np.prod(vox)); cz = np.argwhere(sub)
        ins = ndi.distance_transform_edt(np.pad(sub, 1), sampling=vox)[1:-1, 1:-1, 1:-1][sub]
        ring = (ndi.distance_transform_edt(~sub, sampling=vox) <= 2.0) & (ndi.distance_transform_edt(~sub, sampling=vox) > 1.0)
        si = np.asarray(swi[pad], float)
        med_in = float(np.median(si[sub])) if sub.any() else None; med_out = float(np.median(si[ring])) if ring.any() else None
        dcore = dist[pad][sub]
        M[i] = dict(core_vox=int(c.sum()), extent_vox=int(sub.sum()), core_mm3=round(float(c.sum() * v3), 1), extent_mm3=round(float(sub.sum() * v3), 1),
                    growth_ratio=round(float(sub.sum() / max(c.sum(), 1)), 2), core_slices=int(len(np.unique(np.argwhere(c)[:, 2]))),
                    extent_slices=int(len(np.unique(cz[:, 2]))), extent_mm=round(float(np.linalg.norm(np.ptp(cz, axis=0) * vox)), 1),
                    thickness_mm=round(float(2 * np.median(ins)), 2) if len(ins) else None,
                    contrast_in_out=round(med_in / med_out, 3) if med_in is not None and med_out else None,
                    cap_frac=round(float((dcore > grow_mm - max(vox)).mean()), 3) if len(dcore) else 0.0)
        M[i]["leak_warning"] = bool(M[i]["cap_frac"] > CAP_WARN)
    return out, M


def run(base, sid, write=True):
    """-> dict(version, inputs, measures {id: ...}, path) for one study; reads data/ID_swi.nii, review/ID_candidates.nii.gz, work/ID_dark.nii.gz"""
    import nibabel as nib
    p = dict(swi=os.path.join(base, "data", f"{sid}_swi.nii"), cand=os.path.join(base, "review", f"{sid}_candidates.nii.gz"),
             dark=os.path.join(base, "work", f"{sid}_dark.nii.gz"))
    miss = [k for k, v in p.items() if not os.path.exists(v)]
    if miss: raise FileNotFoundError(f"{sid}: missing {', '.join(miss)} - the extent needs the detector's outputs")
    S = nib.load(p["swi"]); C = nib.load(p["cand"]); D = nib.load(p["dark"])
    if C.shape[:3] != S.shape[:3] or D.shape[:3] != S.shape[:3]: raise ValueError(f"{sid}: candidate / dark map not on the SWI grid")
    ext, M = refine(np.asarray(C.dataobj), np.asarray(D.dataobj) > 0, np.asarray(S.dataobj, np.float32), S.header.get_zooms()[:3])
    rec = dict(version=VERSION, study=sid, grow_mm=GROW_MM, inputs={k: _sha(v) for k, v in p.items()},
               rule="6-connected growth of each candidate core through the detector dark map (zone AND z < -1.5) within 5 mm; nearest core wins",
               note="derived outline for display and measurement; never a label and never a decision", measures={str(k): v for k, v in M.items()})
    if write:
        rd = os.path.join(base, "review"); out = os.path.join(rd, f"{sid}_candidates_extent.nii.gz")
        nib.save(nib.Nifti1Image(ext, S.affine), out + ".tmp.nii.gz"); os.replace(out + ".tmp.nii.gz", out)
        import csv
        cols = ["cand_id"] + list(next(iter(M.values())).keys()) if M else ["cand_id"]
        with open(os.path.join(rd, f"{sid}_extent.csv.tmp"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); [w.writerow(dict(cand_id=k, **v)) for k, v in sorted(M.items())]
        os.replace(os.path.join(rd, f"{sid}_extent.csv.tmp"), os.path.join(rd, f"{sid}_extent.csv"))
        with open(os.path.join(rd, f"{sid}_extent.json.tmp"), "w") as f: json.dump(rec, f, indent=1)
        os.replace(os.path.join(rd, f"{sid}_extent.json.tmp"), os.path.join(rd, f"{sid}_extent.json")); rec["path"] = out
    return rec


def current(base, sid):
    """the stored extent when its inputs are unchanged, else None (stale outputs are never shown)"""
    jp = os.path.join(base, "review", f"{sid}_extent.json"); xp = os.path.join(base, "review", f"{sid}_candidates_extent.nii.gz")
    if not (os.path.exists(jp) and os.path.exists(xp)): return None
    try:
        rec = json.load(open(jp))
        if rec.get("version") != VERSION: return None
        for k, rel in (("swi", f"data/{sid}_swi.nii"), ("cand", f"review/{sid}_candidates.nii.gz"), ("dark", f"work/{sid}_dark.nii.gz")):
            if _sha(os.path.join(base, rel)) != rec["inputs"].get(k): return None
        return dict(rec, path=xp)
    except Exception: return None
