"""registration.py - registration provenance and checks for the channels resampled onto the SWI grid (Stage 2 P1).

lta_record(path, ...)       one LTA (work/ID_swi2t1.lta, work/ID_flair2swi.lta): sha256, type, RAS->RAS matrix through css_surface.read_lta
                            (pinned, verbatim), rigidity, rotation / translation, volume-info check against the image it claims to
                            belong to, freshness against the SWI.  status: ok / missing / stale / invalid
reg_json(path)              work/ID_reg.json written by prep_anat.sh: method + cost; cost above css_qc.REG_COST_LOW_CONF -> flag
residual_shift(ref, mov)    image-based check of a channel ALREADY on the SWI grid: integer + parabolic sub-voxel shift that maximises
                            normalised mutual information inside the SWI brain (contrast-agnostic, so SWI vs FLAIR works).
                            status: ok / low_confidence / misregistered / unmeasurable
Thresholds marked PROVISIONAL were set on synthetic misregistration tests only."""
import gc, json, os, warnings
import numpy as np
from scipy import ndimage as ndi
from .. import provenance as pv
from . import CSS_QC

REG_COST_LOW_CONF = pv.module_constants(CSS_QC, names=["REG_COST_LOW_CONF"])["REG_COST_LOW_CONF"]
RIGID_SCALE_TOL = 0.02      # |singular value - 1| above this: not a rigid transform (all prep_anat.sh routes are rigid, dof 6)
VOLINFO_TOL_MM = 0.01       # LTA volume info vs the image it names
SHIFT_OK_MM = 1.0           # PROVISIONAL residual shift: <= ok
SHIFT_REFUSE_MM = 2.0       # PROVISIONAL residual shift: > misregistered (channel not used); between: low_confidence
SHIFT_SEARCH_MM = 4.0
NMI_PEAK_MIN = 0.002        # PROVISIONAL: peak NMI above the median of the search: below = unmeasurable (flat landscape)


def _read_lta(path):
    """css_surface.read_lta (pinned, verbatim). It opens the file without a context manager; the warning is contained here."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ResourceWarning)
        M = pv.load_legacy("css_surface").read_lta(path)
        gc.collect()
    return M


def _volinfo(lines, tag):
    k = [j for j, ln in enumerate(lines) if ln.strip().startswith(tag)]
    if not k: return None
    info = {}
    for ln in lines[k[0] + 1:k[0] + 10]:
        if "=" in ln:
            key, val = ln.split("=", 1); info[key.strip()] = val.split()
    if info.get("valid", ["0"])[0] != "1" or "volume" not in info: return None
    dims = np.array([float(x) for x in info["volume"][:3]]); vs = np.array([float(x) for x in info["voxelsize"][:3]])
    R = np.c_[[float(x) for x in info["xras"]], [float(x) for x in info["yras"]], [float(x) for x in info["zras"]]] * vs
    c = np.array([float(x) for x in info.get("cras", info.get("c_ras"))])
    A = np.eye(4); A[:3, :3] = R; A[:3, 3] = c - R @ (dims / 2.0)       # the same convention as css_surface.read_lta
    return dict(shape=[int(x) for x in dims], affine=A)


def rigid_params(M):
    R = np.asarray(M, float)[:3, :3]; s = np.linalg.svd(R, compute_uv=False)
    U, _, Vt = np.linalg.svd(R); Q = U @ Vt
    ang = float(np.degrees(np.arccos(np.clip((np.trace(Q) - 1) / 2, -1, 1))))
    return dict(scale_dev=round(float(np.abs(s - 1).max()), 6), det=round(float(np.linalg.det(R)), 6), rotation_deg=round(ang, 4),
                translation_mm=round(float(np.linalg.norm(np.asarray(M, float)[:3, 3])), 4))


def lta_record(path, base, swi_desc, swi_path, role):
    """role 'src' = the SWI is the LTA's source volume (swi2t1); 'dst' = the SWI is its destination (flair2swi)"""
    rel = os.path.relpath(path, base)
    if not os.path.exists(path): return dict(file=rel, status="missing", reasons=["file not found"])
    r = dict(file=rel, sha256=pv.sha256_file(path), mtime=os.path.getmtime(path), reasons=[])
    try:
        with open(path) as f: lines = f.read().splitlines()
        r["type"] = int(next(ln for ln in lines if ln.strip().startswith("type")).split("=")[1].split()[0])
        M = np.asarray(_read_lta(path), float)
        if M.shape != (4, 4) or not np.isfinite(M).all(): raise ValueError("matrix is not a finite 4 x 4")
    except Exception as e:
        r.update(status="invalid", reasons=[f"unreadable LTA: {type(e).__name__}: {e}"]); return r
    r["ras2ras"] = np.round(M, 6).tolist(); r.update(rigid_params(M))
    if r["scale_dev"] > RIGID_SCALE_TOL or r["det"] <= 0:
        r["reasons"].append(f"not a rigid transform (scale deviation {r['scale_dev']}, det {r['det']})")
    vi = _volinfo(lines, f"{role} volume info")
    if vi is None: r["volinfo_check"] = "absent (not verifiable)"
    else:
        same = vi["shape"] == swi_desc["shape"][:3] and float(np.abs(vi["affine"] - np.array(swi_desc["affine"])).max()) <= VOLINFO_TOL_MM
        r["volinfo_check"] = "matches the SWI" if same else "MISMATCH"
        if not same: r["reasons"].append(f"the LTA's {role} volume is not this SWI (made for another image or before a re-import)")
    if r["reasons"]: r["status"] = "invalid"
    elif os.path.getmtime(path) < os.path.getmtime(swi_path): r.update(status="stale", reasons=["older than the SWI"])
    else: r["status"] = "ok"
    return r


def reg_json(path, base):
    rel = os.path.relpath(path, base)
    if not os.path.exists(path): return dict(file=rel, status="missing")
    try:
        with open(path) as f: j = json.load(f)
    except Exception as e: return dict(file=rel, status="invalid", reasons=[f"{type(e).__name__}"])
    cost = j.get("cost"); method = j.get("method")
    out = dict(file=rel, status="ok", method=method if isinstance(method, str) else None,
               cost=float(cost) if isinstance(cost, (int, float)) else None, cost_threshold=REG_COST_LOW_CONF)
    out["cost_above_threshold"] = bool(out["cost"] is not None and out["cost"] > REG_COST_LOW_CONF)
    return out


def _nmi(a, b, ra, rb, bins=32):
    h, _, _ = np.histogram2d(a, b, bins=bins, range=[ra, rb]); p = h / max(h.sum(), 1)
    px, py = p.sum(1), p.sum(0)
    H = lambda q: -float((q[q > 0] * np.log(q[q > 0])).sum())
    hxy = H(p)
    return (H(px) + H(py)) / hxy if hxy > 0 else 0.0


def residual_shift(ref, mov, vox, A, n_samples=60000, seed=0):
    """shift (world mm) that best aligns mov to ref on the same grid; ref = SWI (brain = ref > 0)"""
    ref = np.asarray(ref, np.float64); mov = np.asarray(mov, np.float64); vox = np.asarray(vox, float)
    R = np.ceil(SHIFT_SEARCH_MM / vox).astype(int)
    brain = ndi.binary_erosion(ref > 0, iterations=1)
    m = np.zeros(ref.shape, bool); sl = tuple(slice(r + 1, s - r - 1) for r, s in zip(R, ref.shape)); m[sl] = True
    idx = np.argwhere(brain & m)
    if len(idx) < 500: return dict(status="unmeasurable", reasons=[f"only {len(idx)} brain voxels inside the search margin"])
    rng = np.random.default_rng(seed); idx = idx[rng.choice(len(idx), size=min(n_samples, len(idx)), replace=False)]
    a = ref[tuple(idx.T)]
    fin = np.isfinite(mov)
    if not fin.all(): mov = np.where(fin, mov, 0.0)
    ra = tuple(np.percentile(a, [0.5, 99.5])); rb = tuple(np.percentile(mov[ref > 0], [0.5, 99.5]))
    if not ra[1] > ra[0] or not rb[1] > rb[0]: return dict(status="unmeasurable", reasons=["a channel is constant inside the brain"])
    cache = {}

    def f(d):
        d = tuple(int(x) for x in d)
        if d not in cache: cache[d] = _nmi(a, mov[tuple((idx + np.array(d)).T)], ra, rb)
        return cache[d]
    coarse = [np.arange(-r, r + 1, 2) for r in R]
    for i in coarse[0]:
        for j in coarse[1]:
            for k in coarse[2]: f((i, j, k))
    best = max(cache, key=cache.get)
    while True:                                                    # hill climb on the full 1-voxel grid
        nb = [tuple(np.clip(np.array(best) + np.array((i, j, k)), -R, R)) for i in (-1, 0, 1) for j in (-1, 0, 1) for k in (-1, 0, 1)]
        nxt = max(nb, key=f)
        if f(nxt) <= f(best) + 1e-12: break
        best = nxt
    peak = f(best) - float(np.median(list(cache.values())))
    if peak < NMI_PEAK_MIN:
        return dict(status="unmeasurable", reasons=[f"no distinct alignment optimum (NMI peak {peak:.4f} < {NMI_PEAK_MIN})"],
                    nmi_peak=round(peak, 5))
    sub = np.array(best, float)
    for ax in range(3):                                            # parabolic refinement per axis
        if abs(best[ax]) >= R[ax]: continue
        e = np.zeros(3, int); e[ax] = 1
        y0, ym, yp = f(best), f(tuple(np.array(best) - e)), f(tuple(np.array(best) + e))
        den = ym - 2 * y0 + yp
        if den < 0: sub[ax] += float(np.clip(0.5 * (ym - yp) / den, -0.5, 0.5))
    world = np.asarray(A, float)[:3, :3] @ sub
    mm = float(np.linalg.norm(world))
    at_edge = any(abs(best[ax]) >= R[ax] for ax in range(3))
    st = "ok" if mm <= SHIFT_OK_MM else ("low_confidence" if mm <= SHIFT_REFUSE_MM else "misregistered")
    reasons = [] if st == "ok" else [f"residual shift {mm:.2f} mm against the SWI"]
    if at_edge: st, reasons = "misregistered", reasons + [f"optimum at the edge of the +-{SHIFT_SEARCH_MM} mm search"]
    return dict(status=st, reasons=reasons, shift_vox=np.round(sub, 3).tolist(), shift_world_mm=np.round(world, 3).tolist(),
                shift_mm=round(mm, 3), nmi_peak=round(peak, 5), nmi_at_zero=round(f((0, 0, 0)), 5), nmi_best=round(f(best), 5),
                thresholds=dict(ok_mm=SHIFT_OK_MM, refuse_mm=SHIFT_REFUSE_MM, search_mm=SHIFT_SEARCH_MM, nmi_peak_min=NMI_PEAK_MIN))


def read_acquisition(base, sid):
    """css_qc.read_acq (pinned, verbatim): its output is already a whitelist of acquisition fields (no names, no dates)"""
    qc = pv.load_legacy("css_qc")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ResourceWarning)          # read_acq opens the JSON without a context manager
        out = qc.read_acq(base, sid)
        gc.collect()
    return out


__all__ = ["lta_record", "reg_json", "residual_shift", "read_acquisition", "rigid_params"]
