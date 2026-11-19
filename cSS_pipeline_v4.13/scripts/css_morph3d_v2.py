"""css_morph3d_v2.py - v5.13 EXPERIMENTAL resolution-aware morphology of one candidate (research tool; never used by
detection or scoring). The v5.12 module css_morph3d.py is kept unchanged for comparison.

Rules and constants: morph_v513/DESIGN_DECLARED_BEFORE_TESTING.md (declared before any test was run).
  decompose()     candidate -> dark core / blooming-support / adjacent dark structures (needs the SWI crop)
  thickness()     local thickness with the box-chord correction (B6)
  mst_length()    skeleton length = minimum-spanning-tree edge length (B10)
  inplane()       A1 per-slice 2-D description
  normal_tensor() A2 surface-normal tensor classes at 2 and 4 mm (A5 = agreement)
  resolvability() Phase 4 gate and level
  analyse()       everything above on one mask, each approach reported separately
Outputs are descriptive measurements, not probabilities and not diagnoses."""
import numpy as np
from scipy import ndimage as ndi
from scipy.spatial import cKDTree
import css_morph3d as v512

S26 = ndi.generate_binary_structure(3, 3)
PROTO = {"sheet": np.array([1, 0, 0.]), "tube": np.array([.5, .5, 0.]), "blob": np.array([1 / 3, 1 / 3, 1 / 3])}


# ------------------------------------------------------------------ B6 thickness with the box chord
def chord(u, vox):
    """length of one voxel crossed along unit direction u: min_i v_i / |u_i|"""
    a = np.abs(u); v = np.asarray(vox, float).reshape((3,) + (1,) * (a.ndim - 1))
    with np.errstate(divide="ignore"): r = np.where(a > 1e-9, v / np.maximum(a, 1e-12), np.inf)
    return r.min(0)


def thickness(mask, vox):
    """as v5.12 local_thickness but the subtracted voxel is the box chord along the direction to the nearest background"""
    vox = np.asarray(vox, float); pad = np.pad(mask, 1)
    dt, ind = ndi.distance_transform_edt(pad, sampling=vox, return_indices=True)
    d = (ind - np.indices(pad.shape)) * vox[:, None, None, None]; n = np.linalg.norm(d, axis=0) + 1e-9
    step = chord(d / n, vox)
    t = np.clip(2 * dt - step, vox.min() * 0.5, None) * pad
    ridge = pad & (dt >= ndi.maximum_filter(dt, footprint=S26) - 1e-6)
    R = np.argwhere(ridge)
    if len(R):
        u = -(d[:, R[:, 0], R[:, 1], R[:, 2]] / n[R[:, 0], R[:, 1], R[:, 2]]).T
        sv = np.where(np.abs(u) > 0.38, np.sign(u), 0).astype(int); q = np.clip(R + sv, 0, np.array(pad.shape) - 1)
        pl = pad[tuple(q.T)] & (dt[tuple(q.T)] >= dt[tuple(R.T)] - 1e-6) & (sv != 0).any(1)
        t[tuple(R[pl].T)] += step[tuple(R[pl].T)]
        _, ri = ndi.distance_transform_edt(~ridge, sampling=vox, return_indices=True); t = np.where(pad, t[tuple(ri)], 0)
    return t[1:-1, 1:-1, 1:-1]


# ------------------------------------------------------------------ B10 skeleton length
def mst_length(points, vox):
    """total length (mm) of the minimum spanning tree over 26-neighbour edges of the skeleton voxels"""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import minimum_spanning_tree
    P = np.asarray(points); n = len(P)
    if n < 2: return 0.0
    tree = cKDTree(P); pairs = tree.query_pairs(np.sqrt(3) + 1e-6, output_type="ndarray")
    if not len(pairs): return 0.0
    w = np.linalg.norm((P[pairs[:, 0]] - P[pairs[:, 1]]) * np.asarray(vox, float), axis=1)
    return float(minimum_spanning_tree(coo_matrix((w, (pairs[:, 0], pairs[:, 1])), shape=(n, n))).sum())


# ------------------------------------------------------------------ Phase 2 decomposition
def decompose(cand, img, vox, shell=(2.0, 5.0), r_peak=2.0):
    vox = np.asarray(vox, float); cand = np.asarray(cand, bool)
    dist = ndi.distance_transform_edt(~cand, sampling=vox)
    S = (dist >= shell[0]) & (dist <= shell[1])
    if S.sum() < 20: return dict(error="background shell too small")
    s = img[S]; med = np.median(s); mad = 1.4826 * np.median(np.abs(s - med)) + 1e-6
    s2 = s[s >= med - 2 * mad]; mu = float(np.median(s2)); sd = float(1.4826 * np.median(np.abs(s2 - np.median(s2))) + 1e-6)
    c = (mu - img) / sd
    fp = np.ones([max(1, int(np.ceil(r_peak / v))) * 2 + 1 for v in vox], bool)
    gg = np.indices(fp.shape).astype(float); ctr = (np.array(fp.shape) - 1) / 2
    fp = (((gg - ctr[:, None, None, None]) * vox[:, None, None, None]) ** 2).sum(0) <= r_peak ** 2
    cpk = ndi.maximum_filter(c, footprint=fp)
    zone = ndi.binary_dilation(cand, S26)
    ok = zone & (cpk >= 3)
    core = ok & (c >= 0.5 * cpk)
    unstable = ok & (((c >= 0.4 * cpk) != (c >= 0.6 * cpk)) | (np.abs(c - 0.5 * cpk) < 1))
    lowc = zone & (cpk < 3)
    support = cand & ~core
    dark = (c >= 3) & (dist <= shell[1]) & ~cand
    dl, nd = ndi.label(dark, S26); touch = np.unique(dl[ndi.binary_dilation(cand | core, S26) & (dl > 0)])
    adjacent = (dl > 0) & ~np.isin(dl, touch)
    return dict(core=core, support=support, adjacent=adjacent, unstable=unstable, lowc=lowc, c=c, mu=mu, sd=sd,
                core_unstable_frac=float(unstable[core].mean()) if core.any() else None,
                lowc_frac=float(lowc[cand].mean()) if cand.any() else None)


# ------------------------------------------------------------------ Phase 3 approaches
def slice_axis(vox): return int(np.argmax(vox)) if np.ptp(vox) > 1e-6 else 2


def inplane(mask, vox):
    """A1: per acquisition slice, 2-D pieces: area (mm2), width (mm) = 2 x max 2-D EDT - in-plane chord, length (mm) of the
    2-D skeleton (MST). Returns a per-slice list and the number of slices occupied."""
    from skimage.morphology import skeletonize
    ax = slice_axis(vox); ip = [v for i, v in enumerate(vox) if i != ax]; out = []
    for k in range(mask.shape[ax]):
        sl = np.take(mask, k, axis=ax)
        if not sl.any(): continue
        lab, n = ndi.label(sl, np.ones((3, 3), bool))
        for j in range(1, n + 1):
            m = lab == j; e, ind = ndi.distance_transform_edt(np.pad(m, 1), sampling=ip, return_indices=True)
            p = np.unravel_index(np.argmax(e), e.shape); dvec = (np.array([ind[0][p], ind[1][p]]) - np.array(p)) * np.array(ip)
            u = dvec / (np.linalg.norm(dvec) + 1e-9); ch = min(ip[i] / abs(u[i]) for i in range(2) if abs(u[i]) > 1e-9)
            sk = skeletonize(m); L = mst_length(np.c_[np.argwhere(sk), np.zeros(sk.sum())], list(ip) + [1.0])
            out.append(dict(slice=k, area_mm2=round(float(m.sum() * np.prod(ip)), 2), width_mm=round(float(max(2 * e.max() - ch, min(ip))), 2), length_mm=round(L, 2)))
    return out, len({o["slice"] for o in out})


def normal_tensor(mask, vox, radii=(2.0, 4.0)):
    """A2: area-weighted mean n n^T of marching-cubes triangles within r of each mask voxel; eigenvalues sorted; nearest
    prototype (sheet / tube / blob) or 'mixed' if d1 >= 0.75 d2. Returns {r: (labels, eigenvalues)} per voxel."""
    from skimage.measure import marching_cubes
    vox = np.asarray(vox, float); P = np.argwhere(mask) * vox; out = {}
    if mask.sum() < 2: return {r: (np.array(["mixed"] * len(P)), np.zeros((len(P), 3))) for r in radii}
    v, f, _, _ = marching_cubes(np.pad(mask.astype(np.float32), 1), 0.5, spacing=tuple(vox)); v -= vox
    a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]; cr = np.cross(b - a, c - a); area = np.linalg.norm(cr, axis=1) / 2
    nrm = cr / np.maximum(2 * area[:, None], 1e-12); cen = (a + b + c) / 3; T = np.einsum("ni,nj->nij", nrm, nrm) * area[:, None, None]
    tree = cKDTree(cen)
    for r in radii:
        labs = []; eigs = np.zeros((len(P), 3))
        for i, nb in enumerate(tree.query_ball_point(P, r)):
            if not nb: labs.append("mixed"); continue
            M = T[nb].sum(0) / max(area[nb].sum(), 1e-12); e = np.sort(np.linalg.eigvalsh(M))[::-1]; eigs[i] = e
            d = sorted((float(np.linalg.norm(e - p)), k) for k, p in PROTO.items())
            labs.append(d[0][1] if d[0][0] < 0.75 * d[1][0] else "mixed")
        out[r] = (np.array(labs), eigs)
    return out


# ------------------------------------------------------------------ Phase 4 resolvability
def run_lengths(mask):
    """per voxel, length (in voxels) of the mask run through it along each axis"""
    out = np.zeros((3,) + mask.shape, np.int32)
    for ax in range(3):
        m = np.moveaxis(mask, ax, -1); r = np.zeros(m.shape, np.int32)
        lab = np.zeros(m.shape, np.int32); flat = m.reshape(-1, m.shape[-1]); R = r.reshape(-1, m.shape[-1])
        for i, row in enumerate(flat):
            if not row.any(): continue
            d = np.diff(np.r_[0, row.astype(np.int8), 0]); st, en = np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]
            for s_, e_ in zip(st, en): R[i, s_:e_] = e_ - s_
        out[ax] = np.moveaxis(r, -1, ax)
    return out


def resolvable_voxels(mask, vox):
    """CHANGED AFTER TESTING (CHANGES_AFTER_TESTING.md #1; the declared run-length rule counted runs ALONG the structure,
    so one-slice structures passed). A voxel is NOT resolvable (3-D) when the structure occupies <= 1 slice there AND its
    in-plane width there (A1) is < 2 x slice thickness: through-plane extent is then unknown and a tube lying in-plane
    cannot be told from a ribbon. A one-slice patch wider than 2 slice thicknesses is resolvable as a flat (sheet-compatible,
    thickness unknown) structure."""
    vox = np.asarray(vox, float); rl = run_lengths(mask); ax = slice_axis(vox); dz = vox[ax]
    ip = [v for i, v in enumerate(vox) if i != ax]; wmap = np.zeros(mask.shape, np.float32)
    for k in range(mask.shape[ax]):
        sl = np.take(mask, k, axis=ax)
        if not sl.any(): continue
        lab, n = ndi.label(sl, np.ones((3, 3), bool)); W = np.zeros(sl.shape, np.float32)
        for j in range(1, n + 1):
            m = lab == j; e = ndi.distance_transform_edt(np.pad(m, 1), sampling=ip)[1:-1, 1:-1]; W[m] = max(2 * e.max() - min(ip), min(ip))
        idx = [slice(None)] * 3; idx[ax] = k; wmap[tuple(idx)] = W
    bad = (rl[ax] <= 1) & (wmap < 2 * dz)
    return mask & ~bad, rl


def stability(mask, vox, labels_ref, radius=2.0):
    """A2 label agreement on the original voxels after a 1-voxel erosion and after a 1-voxel dilation (mean of both)"""
    P = np.argwhere(mask); agree = []
    for m2 in (ndi.binary_erosion(mask, S26) if ndi.binary_erosion(mask, S26).sum() >= 4 else mask, ndi.binary_dilation(mask, S26)):
        L2, _ = normal_tensor(m2, vox, (radius,))[radius]; P2 = np.argwhere(m2)
        if not len(P2): continue
        _, nn = cKDTree(P2).query(P); agree.append(float((L2[nn] == labels_ref).mean()))
    return float(np.mean(agree)) if agree else 0.0


# ------------------------------------------------------------------ the analysis
def analyse(cand, vox, img=None, psd=None, vessel=None):
    vox = np.asarray(vox, float); cand = np.asarray(cand, bool).copy(); out = dict(version="v5.13-exp", vox=vox.tolist())
    reps = {"candidate": cand}
    if img is not None:
        D = decompose(cand, img, vox)
        if "error" not in D:
            reps["core"] = D["core"]; out["decomposition"] = dict(background=round(D["mu"], 2), noise=round(D["sd"], 3),
                n_candidate=int(cand.sum()), n_core=int(D["core"].sum()), n_support=int(D["support"].sum()), n_adjacent=int(D["adjacent"].sum()),
                core_inside_candidate=round(float((D["core"] & cand).sum() / max(D["core"].sum(), 1)), 2),
                core_unstable_frac=None if D["core_unstable_frac"] is None else round(D["core_unstable_frac"], 2),
                low_contrast_frac=None if D["lowc_frac"] is None else round(D["lowc_frac"], 2))
            out["_D"] = D
        else: out["decomposition"] = D
    for nm, m in reps.items(): out[nm] = describe(m, vox)
    if psd is not None: out["context"] = context(cand, psd, vox)
    return out


def describe(m, vox):
    vox = np.asarray(vox, float)
    if m.sum() < 2: return dict(n_vox=int(m.sum()), level="not resolvable", reasons=["fewer than 2 voxels"])
    P = np.argwhere(m); th = thickness(m, vox)[m]
    lab, npc = ndi.label(m, S26)
    res, rl = resolvable_voxels(m, vox); rf = float(res[m].mean())
    nt = normal_tensor(m, vox); l2, e2 = nt[2.0]; l4, e4 = nt[4.0]
    rv = res[tuple(P.T)]; agree = (l2 == l4)
    stab = stability(m, vox, l2) if m.sum() <= 20000 else None
    ax = slice_axis(vox); ip, nsl = inplane(m, vox)
    # orientation: dominant A2 normal (largest eigenvector at 4 mm, whole object) vs slice axis
    from skimage.measure import marching_cubes
    lvl = "resolved" if (rf >= 0.8 and (stab or 0) >= 0.7) else ("partially resolved" if rf >= 0.3 else "not resolvable")
    reasons = []
    if nsl <= 1: reasons.append(f"occupies {nsl} slice: through-plane shape unknown")
    if np.median([o["width_mm"] for o in ip]) < 2 * min(vox[[i for i in range(3) if i != ax]]): reasons.append("in-plane width under 2 voxels")
    if rf < 0.8: reasons.append(f"only {round(100 * rf)} % of voxels have >= 2 voxels across in two directions")
    if stab is not None and stab < 0.7: reasons.append(f"shape labels change under a 1-voxel erosion / dilation ({round(100 * stab)} % stable)")
    if npc > 1: reasons.append(f"{npc} separate pieces")
    if max(vox) / min(vox) > 2: reasons.append(f"voxels {max(vox) / min(vox):.1f}:1 anisotropic")
    share = {k: round(float(((l2 == k) & agree & rv).sum() / max(rv.sum(), 1)), 3) for k in ("sheet", "tube", "blob")}
    share["mixed_or_scale_disagree"] = round(float((rv & ~(agree & np.isin(l2, ["sheet", "tube", "blob"]))).sum() / max(rv.sum(), 1)), 3)
    share["not_resolvable"] = round(1 - rf, 3)
    if lvl == "not resolvable": label = "not resolvable"
    else:
        top = sorted(((share[k], k) for k in ("sheet", "tube", "blob")), reverse=True)
        res_share = {k: share[k] / max(1 - share["not_resolvable"], 1e-9) for k in ("sheet", "tube", "blob")}
        rs = sorted(((v, k) for k, v in res_share.items()), reverse=True)
        label = (f"{rs[0][1]}-compatible" if rs[0][1] != "blob" else "blob-like") if rs[0][0] >= 0.6 else ("mixed" if rs[1][0] >= 0.25 else "indeterminate")
    sk, _ = v512.skeleton(m); skl = mst_length(np.argwhere(sk), vox) if lvl != "not resolvable" else None
    return dict(n_vox=int(m.sum()), volume_mm3=round(float(m.sum() * np.prod(vox)), 1), pieces=int(npc),
                thickness_mm=dict(median=round(float(np.median(th)), 2), p10=round(float(np.percentile(th, 10)), 2), p90=round(float(np.percentile(th, 90)), 2),
                                  quantum_mm=round(float(min(vox)), 2)),
                slices_occupied=nsl, inplane_width_median_mm=round(float(np.median([o["width_mm"] for o in ip])), 2), inplane_length_max_mm=round(float(max(o["length_mm"] for o in ip)), 1),
                resolvable_frac=round(rf, 3), stability=None if stab is None else round(stab, 3), level=lvl, reasons=reasons,
                a2_share=share, label=label, skeleton_mst_mm=None if skl is None else round(skl, 1),
                _labels2=l2, _labels4=l4, _res=rv)


def context(cand, psd, vox):
    """pial distance / CSF / tissue fractions with the pial-distance map shifted +-1 voxel along each axis (min-max)"""
    def f(p): d = p[cand]; return float((d > 0.5).mean()), float((d < -0.5).mean()), float((np.abs(d) <= 1).mean()), float(np.median(d))
    base = f(psd); runs = [f(np.roll(psd, k, axis=a)) for a in range(3) for k in (-1, 1)]
    rng = lambda i: [round(min(r[i] for r in runs + [base]), 2), round(max(r[i] for r in runs + [base]), 2)]
    return dict(csf_frac=round(base[0], 2), csf_range=rng(0), tissue_frac=round(base[1], 2), tissue_range=rng(1),
                within_1mm=round(base[2], 2), within_1mm_range=rng(2), median_pial_mm=round(base[3], 2), median_pial_range=rng(3),
                note="descriptive; shifted by +-1 voxel per axis; never an exclusion criterion")
