"""Experimental structural analysis runner (opt-in). Usage:  python -m structural_detection.run_structural ID [--out DIR] [--include-excluded]
Reads (never writes) $CSS_BASE/data/ID_swi.nii, work/ID_pial_sd.nii.gz, work/ID_seg_swispace.nii.gz,
review/ID_candidates.{csv,nii.gz} (+ excluded / dropped masks if present). Writes ONLY to a new folder
$CSS_BASE/experimental/structural/ID_<UTC time>/ (or --out): features.csv, components.nii.gz, seeds.csv, config.json.
With every CSS_* experimental flag off it prints that and writes nothing (production behaviour untouched)."""
import sys, os, json, hashlib, time, numpy as np, pandas as pd, nibabel as nib
from scipy import ndimage as ndi
from . import flags as FL, hessian_fingerprint as A, candidate_decomposition as F, surface_coordinates as B
from . import vessel_graph as C, multiview_seeding as D, sulcus_reference as E, fusion as FU, __version__

MARGIN_MM = 15.0   # >= 4 x largest sigma (2.4 mm), >= reference radius (10 mm), = vessel ROI: same crop for every configuration

def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()

def load(p, dt=np.float32):
    return np.asarray(nib.load(p).dataobj).astype(dt) if os.path.exists(p) else None

def prep_image(I, brain):
    """Like production If: clip at the brain 99.5th percentile, fill outside the brain with the brain median."""
    hi = np.percentile(I[brain], 99.5); J = np.clip(I, 0, hi); J[~brain] = np.median(J[brain]); return J.astype(np.float32)

def crop(sl_obj, shape, vox, margin_mm):
    return tuple(slice(max(s.start - int(np.ceil(margin_mm / v)), 0), min(s.stop + int(np.ceil(margin_mm / v)), n))
                 for s, v, n in zip(sl_obj, vox, shape))

def analyse(sid, base, fl, out=None, include_excluded=False):
    if not FL.any_on(fl):
        print(f"{sid}: all experimental flags off - nothing computed, nothing written"); return None
    # modules that need module A's voxel classes switch it on (C: tube class for the vessel map; F: plate/tube split)
    if fl["CSS_CANDIDATE_SPLITTING"] or fl["CSS_EXPERIMENTAL_FUSION"] or fl["CSS_VESSEL_GRAPH"]: fl = dict(fl, CSS_HESSIAN_FINGERPRINT=True)
    p = dict(swi=f"{base}/data/{sid}_swi.nii", psd=f"{base}/work/{sid}_pial_sd.nii.gz", seg=f"{base}/work/{sid}_seg_swispace.nii.gz",
             cand=f"{base}/review/{sid}_candidates.nii.gz", candcsv=f"{base}/review/{sid}_candidates.csv",
             excl=f"{base}/review/{sid}_excluded.nii.gz", drop=f"{base}/work/{sid}_dropped.nii.gz")
    for k in ("swi", "cand", "candcsv"):
        if not os.path.exists(p[k]): sys.exit(f"{sid}: missing {p[k]}")
    img = nib.load(p["swi"]); vox = tuple(float(v) for v in img.header.get_zooms()[:3])
    I = np.asarray(img.dataobj, np.float32); seg = load(p["seg"], np.int32); psd = load(p["psd"])
    brain = seg > 0 if seg is not None else I > np.percentile(I, 5)
    J = prep_image(I, brain); cand = load(p["cand"], np.int32); csv = pd.read_csv(p["candcsv"])
    prod_any = cand > 0
    for k in ("excl", "drop"):
        m = load(p[k], np.int32)
        if m is not None: prod_any |= m > 0
    nrm = B.normals(psd, vox) if (psd is not None and fl["CSS_SURFACE_COORDINATES"]) else None
    out = out or f"{base}/experimental/structural/{sid}_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    os.makedirs(out, exist_ok=False)
    COMP = np.zeros(cand.shape, np.int32); rows = []
    sources = [("candidate", cand)]
    if include_excluded and os.path.exists(p["excl"]): sources.append(("excluded", load(p["excl"], np.int32)))
    from .common import objects
    for src, L_ in sources:
      for cid, sl_o, _ in objects(L_):
          sl = crop(sl_o, cand.shape, vox, MARGIN_MM)
          obj = L_[sl] == cid; Jc = J[sl]; r = dict(study_id=sid, source=src, obj_id=cid, vol_mm3=round(float(obj.sum() * np.prod(vox)), 1))
          cls_full = np.full(obj.shape, -1, np.int8)
          if fl["CSS_HESSIAN_FINGERPRINT"]:
              need = (brain[sl] | obj) if fl["CSS_VESSEL_GRAPH"] else obj      # vessel graph needs classes around the object
              mp = A.voxel_maps(Jc, vox, need)
              cls_full[mp["idx"]] = mp["cls"]
              sel = obj[mp["idx"]]
              nn = None
              if nrm is not None: nn = nrm[sl][mp["idx"]]
              r.update(A.object_features(mp, sel, vox, nn))
          if fl["CSS_CANDIDATE_SPLITTING"]:
              comp, crow = F.decompose(obj, cls_full, vox); r.update(F.summary(crow))
              if src == "candidate": off = COMP.max(); COMP[sl][obj] = comp[obj] + off
          if fl["CSS_SURFACE_COORDINATES"] and psd is not None: r.update(B.object_features(obj, psd[sl], nrm[sl], vox))
          if fl["CSS_VESSEL_GRAPH"]:
              vm = C.vessel_map(Jc, cls_full, brain[sl]) & ~(prod_any[sl] & ~obj & (L_[sl] != cid))
              sk, deg, L = C.skeleton_graph(vm | (obj & (cls_full == 1)), vox); r.update(C.object_features(obj, sk, deg, L, vox))
          if fl["CSS_SULCUS_REFERENCE"] and psd is not None:
              r.update(E.object_features(Jc, obj, psd[sl], vox, others=(prod_any[sl] & ~obj), brain=brain[sl]))
          if fl["CSS_EXPERIMENTAL_FUSION"]:
              cat, why = FU.categorise(r); r.update(fusion_category=cat, fusion_signals=why)
          rows.append(r)
    pd.DataFrame(rows).to_csv(f"{out}/features.csv", index=False)
    if fl["CSS_CANDIDATE_SPLITTING"]: nib.save(nib.Nifti1Image(COMP, img.affine), f"{out}/components.nii.gz")
    if fl["CSS_MULTIVIEW_SEEDING"]:
        zone = brain & (psd > -3.5) & (psd < 4.0) if psd is not None else brain
        V, per, vv = D.votes(J, zone, vox); _, srows = D.seed_components(V, per, vox, prod_any)
        pd.DataFrame(srows, columns=["seed_id", "vol_mm3", "views", "axial_seen", "status", "vox_i", "vox_j", "vox_k"]).to_csv(f"{out}/seeds.csv", index=False)
    cfg = dict(study_id=sid, module_version=__version__, flags=fl, voxel_mm=vox, created_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               inputs={k: dict(path=v, sha256=sha(v)) for k, v in p.items() if os.path.exists(v)},
               params=dict(scales_mm=A.SCALES_MM, t_low=A.T_LOW, t_high=A.T_HIGH, min_comp_mm3=F.MIN_COMP_MM3, roi_mm=C.ROI_MM,
                           cont_mm=C.CONT_MM, dark_z=C.DARK_Z, mv_pct=D.PCT, mv_aniso=D.VIEW_ANISO, ref_radius=E.REF_RADIUS_MM),
               note="experimental, recorded only; no candidate removed, re-ranked or relabelled")
    json.dump(cfg, open(f"{out}/config.json", "w"), indent=1, default=str)
    print(f"{sid}: experimental structural analysis of {len(rows)} candidates -> {out}"); return out

if __name__ == "__main__":
    a = sys.argv[1:]
    if not a: sys.exit(__doc__)
    o = a[a.index("--out") + 1] if "--out" in a else None
    analyse(a[0], os.environ.get("CSS_BASE", os.path.expanduser("~/css_project")), FL.read(), o, "--include-excluded" in a)
