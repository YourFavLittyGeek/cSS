"""css_morph3d.py - 3-D morphology of ONE candidate (viewer / research tool; never used by detection or scoring).

Measures the candidate mask itself (not a regrown dark structure), in millimetres, on a candidate-local crop:
  components, principal axes (coordinate PCA), volume, mesh surface area, sphericity, local thickness (distance
  transform), skeleton (only when it is reliable), cross-sections along the first principal axis, per-voxel local
  shape (neighbourhood PCA: linear / planar / scattered), per-voxel image Hessian (intensity curvature, kept separate),
  pial-surface relation, vessel-map connection, and a descriptive summary. Nothing here is a probability.

Inputs are crops on the canonical (RAS+) grid with voxel size `vox` (mm). All outputs are copies: the caller's mask
and image are never modified.

usage (self-test on a phantom):  python css_morph3d.py --selftest
"""
import sys
import numpy as np
from scipy import ndimage as ndi
from scipy.spatial import cKDTree

S26 = ndi.generate_binary_structure(3, 3)
HESS_SIGMAS_MM = (0.8, 1.6)          # same scales as detect_css.py (HESS_SIGMAS_MM)
CLASS_NAMES = ["tube", "sheet", "blob", "uncertain", "unresolved", "acquisition_limited"]
# v5.14-gui resolution confidence (docs/INVESTIGATION_morph3d_cylinder.md): a shape class is only claimed when every direction it
# depends on is sampled by MORE than two voxels across the structure (two samples cannot tell a width <= w from one up to 2w).
K_RESOLVED = 2.2      # samples spanned along a direction; > 2, with 0.2 margin for the discretisation of round cross-sections
ANISO_LIMITED = 1.5   # an unresolved direction sampled >= 1.5 x more coarsely than the finest voxel side = limited by acquisition
FLAT_FACTOR = 2.0     # a sheet with an unresolved thickness must be >= 2 x wider than the thickness that sampling could hide


# ---------------------------------------------------------------- basic geometry
def pca(P):
    """coordinate PCA (mm): eigenvalues (descending) of the covariance, unit axes as columns, sd along each axis"""
    if len(P) < 4: return np.zeros(3), np.eye(3), np.zeros(3)
    w, v = np.linalg.eigh(np.cov((P - P.mean(0)).T)); o = np.argsort(w)[::-1]
    w = np.clip(w[o], 0, None); v = v[:, o]
    return w, v, np.sqrt(w)


def extent_along(P, axes, vox):
    """physical extent along each axis: range of voxel centres + one voxel measured along that axis"""
    pr = (P - P.mean(0)) @ axes
    return np.ptp(pr, axis=0) + np.abs(axes).T @ np.asarray(vox, float)


def mesh(mask, vox, smooth_iter=0):
    """marching cubes on a padded copy (level 0.5, physical spacing). smooth_iter > 0: Taubin smoothing of a copy
    (lambda 0.5 / mu -0.53: low-pass without the shrinkage of plain Laplacian smoothing)"""
    from skimage.measure import marching_cubes, mesh_surface_area
    m = np.pad(mask.astype(np.float32), 1)
    if m.sum() < 1: return np.zeros((0, 3)), np.zeros((0, 3), int), 0.0
    v, f, _, _ = marching_cubes(m, 0.5, spacing=tuple(float(x) for x in vox))
    v = v - np.asarray(vox, float)                     # undo the pad: vertex coordinates in crop mm (voxel centre = index x vox)
    area_raw = float(mesh_surface_area(v, f))
    if smooth_iter:
        nb = [set() for _ in range(len(v))]
        for a, b, c in f: nb[a].update((b, c)); nb[b].update((a, c)); nb[c].update((a, b))
        idx = [np.fromiter(s, int) for s in nb]
        for k in range(2 * smooth_iter):
            lam = 0.5 if k % 2 == 0 else -0.53
            avg = np.array([v[i].mean(0) if len(i) else v[j] for j, i in enumerate(idx)])
            v = v + lam * (avg - v)
    return v, f, area_raw


def mesh_volume(v, f):
    if len(f) == 0: return 0.0
    a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    return float(abs(np.einsum("ij,ij->i", a, np.cross(b, c)).sum()) / 6.0)


def vertex_normals(v, f):
    n = np.zeros_like(v)
    if len(f):
        fn = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
        for k in range(3): np.add.at(n, f[:, k], fn)
    return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)


# ---------------------------------------------------------------- thickness, skeleton
def local_thickness(mask, vox):
    """per-voxel thickness (mm) = 2 x distance to the nearest background voxel centre minus one voxel measured along
    that direction (a one-voxel layer measures one voxel, not two). Value at each voxel = the thickness of the
    nearest point of the medial ridge (largest inscribed sphere), so the edges of a sheet report the sheet's thickness"""
    vox = np.asarray(vox, float)
    pad = np.pad(mask, 1)
    dt, ind = ndi.distance_transform_edt(pad, sampling=vox, return_indices=True)
    grid = np.indices(pad.shape)
    d = (ind - grid) * vox[:, None, None, None]                       # vector to the nearest background voxel (mm)
    n = np.linalg.norm(d, axis=0) + 1e-9
    step = 1.0 / np.sqrt(((d / n) ** 2 / vox[:, None, None, None] ** 2).sum(0) + 1e-12)   # one voxel along that direction
    t = np.clip(2 * dt - step, vox.min() * 0.5, None) * pad
    # ridge = local maxima of the distance (the medial set); every voxel takes its nearest ridge value
    ridge = pad & (dt >= ndi.maximum_filter(dt, footprint=S26) - 1e-6)
    # an object an EVEN number of voxels across has a two-voxel plateau on its ridge: add the missing voxel there
    R = np.argwhere(ridge)
    if len(R):
        u = -(d[:, R[:, 0], R[:, 1], R[:, 2]] / n[R[:, 0], R[:, 1], R[:, 2]]).T          # away from the nearest background
        stepv = np.where(np.abs(u) > 0.38, np.sign(u), 0).astype(int); q = np.clip(R + stepv, 0, np.array(pad.shape) - 1)
        plateau = pad[tuple(q.T)] & (dt[tuple(q.T)] >= dt[tuple(R.T)] - 1e-6) & (stepv != 0).any(1)
        t[tuple(R[plateau].T)] += step[tuple(R[plateau].T)]
    if ridge.any():
        _, ri = ndi.distance_transform_edt(~ridge, sampling=vox, return_indices=True)
        t = np.where(pad, t[tuple(ri)], 0)
    return t[1:-1, 1:-1, 1:-1], dt[1:-1, 1:-1, 1:-1]


def skeleton(mask):
    """curve skeleton (Lee thinning); objects of even thickness can vanish, then a copy thickened by one voxel is used"""
    from skimage.morphology import skeletonize
    s = skeletonize(mask); note = ""
    if s.sum() < 3 and mask.sum() >= 3:
        s = skeletonize(ndi.binary_dilation(mask, structure=np.ones((2, 2, 2), bool))) & ndi.binary_dilation(mask, S26)
        note = "computed on a copy thickened by one voxel (even-thickness object)"
    return s, note


def skeleton_graph(sk, vox):
    """length (mm, each 26-neighbour pair counted once), end points, branch points, path points ordered along PC1"""
    vox = np.asarray(vox, float); P = np.argwhere(sk)
    if len(P) == 0: return dict(length_mm=0.0, n_end=0, n_branch=0, points=[], branch_pts=[])
    nb = ndi.convolve(sk.astype(np.uint8), S26.astype(np.uint8), mode="constant") - 1
    deg = nb[sk]
    L = 0.0
    for off in np.argwhere(S26) - 1:
        if tuple(off) <= (0, 0, 0): continue                 # half of the 26 offsets: every pair once
        a = sk[max(0, -off[0]):sk.shape[0] - max(0, off[0]), max(0, -off[1]):sk.shape[1] - max(0, off[1]), max(0, -off[2]):sk.shape[2] - max(0, off[2])]
        b = sk[max(0, off[0]):sk.shape[0] + min(0, off[0]) or None, max(0, off[1]):sk.shape[1] + min(0, off[1]) or None, max(0, off[2]):sk.shape[2] + min(0, off[2]) or None]
        L += float((a & b).sum()) * float(np.linalg.norm(off * vox))
    # an orthogonal step plus a diagonal across the same corner double-counts; scale by the ratio of a pure chain
    n = len(P); L = min(L, (n - 1) * float(np.linalg.norm(vox)) if n > 1 else 0.0) if n > 1 else 0.0
    return dict(length_mm=round(L, 1), n_end=int((deg == 1).sum()), n_branch=int((deg >= 3).sum()),
                points=P, branch_pts=P[deg >= 3])


# ---------------------------------------------------------------- local shape (geometry) and Hessian (image)
def sampling_width(u, vox):
    """sampling interval (mm) of the voxel grid along unit direction u = width of one voxel box projected on u
    (sum |u_i| v_i): exactly the voxel side for axis-aligned u, and continuous under small rotations of u."""
    return float(np.sum(np.abs(np.asarray(u)) * np.asarray(vox)))


def axis_extent_mm(proj_mm, w_mm):
    """physical extent of the structure along a direction, from the voxel-centre projections: span + min(largest gap between
    consecutive projected centres, w). Axis-aligned (also slightly rotated) axes: the centres form clusters one voxel apart, the
    largest gap is ~w, so extent = span + w. Oblique axes: the lattice projects densely, the centres reach the boundary, the
    largest gap is small, so extent ~ span (adding a whole w there double-counts - found by the oblique cases of
    check_morph3d_resolution). Span-based, so it does not depend on the profile shape (an sd-based count called a 2.4 mm tube at
    1 mm voxels unresolved)."""
    p = np.sort(np.asarray(proj_mm, float))
    if len(p) < 2: return float(w_mm)
    return float(np.ptp(p) + min(float(np.max(np.diff(p))), w_mm))


def samples_across(proj_mm, w_mm):
    """samples across = extent / sampling interval along that direction (axis-aligned: span / w + 1)."""
    return axis_extent_mm(proj_mm, w_mm) / max(w_mm, 1e-9)


def local_shape(P_mm, radius, thick, vmax, comp=None, vox=None):
    """neighbourhood PCA of the mask coordinates around every voxel (radius mm): spreads s1 >= s2 >= s3 (sd, mm), axes e1-e3.
    Geometric candidate (unchanged rules):
    blob   : s3 / s1 >= 0.5 (spread in all three directions) AND local thickness >= 3 x s3 (solid: a folded or
             two-layer sheet, e.g. both banks of a sulcus, spreads in 3-D too but is thin everywhere -> sheet)
    tube   : s2 <= 0.45 x local thickness + 0.25 x largest voxel AND s2 <= 1.8 x s3 (+0.15 voxel): thin and round across
             (a ribbon is thin in one direction only, s2 >> s3)
    sheet  : otherwise (thin in one direction only)
    Resolution confidence (v5.14-gui): the candidate class is kept only if the directions it DEPENDS ON are resolved, i.e. the
    structure spans k > 2 grid samples (k >= K_RESOLVED; k = span of the neighbourhood along the axis / sampling interval + 1)
    along them, with the sampling interval taken along that direction for
    anisotropic voxels (sampling_width) - so oblique structures are judged on their own axes:
      tube needs e2 and e3 (the cross-section shape), sheet needs e1 and e2 (the in-plane extent) - its thickness e3 may be
      below resolution only if the width along e2 is >= FLAT_FACTOR x the thickness the sampling along e3 could hide
      (k3 x w3); blob needs all three.
    Otherwise: acquisition_limited when an unresolved direction is sampled >= ANISO_LIMITED x more coarsely than the finest
    voxel side (the slice geometry, not the structure, prevents the decision), else unresolved (too small for the grid).
    uncertain: fewer than 8 neighbours. Returns spreads, class, neighbour count, samples spanned (k1, k2, k3)."""
    vox = np.full(3, vmax) if vox is None else np.asarray(vox, float); vmin = float(vox.min())
    tree = cKDTree(P_mm); out = np.zeros((len(P_mm), 3)); cls = np.full(len(P_mm), 3, int); nn = np.zeros(len(P_mm), int)
    kk = np.zeros((len(P_mm), 3))
    for i, nbrs in enumerate(tree.query_ball_point(P_mm, radius)):
        if comp is not None: nbrs = [j for j in nbrs if comp[j] == comp[i]]       # never mix separate pieces
        nn[i] = len(nbrs)
        if len(nbrs) < 8: continue
        Q = P_mm[nbrs]; ev, V = np.linalg.eigh(np.cov((Q - Q.mean(0)).T)); o = np.argsort(ev)[::-1]
        s = np.sqrt(np.clip(ev[o], 0, None)); E = V[:, o]
        out[i] = s
        if s[0] <= 0: continue
        w = np.array([sampling_width(E[:, a], vox) for a in range(3)]); Qc = Q - Q.mean(0)
        k = np.array([samples_across(Qc @ E[:, a], w[a]) for a in range(3)]); kk[i] = k
        tube = s[1] <= 0.45 * thick[i] + 0.25 * vmax and s[1] <= 1.8 * s[2] + 0.15 * vmax and s[0] >= 2 * s[1]   # thin, round across, elongated
        solid = thick[i] >= 3.0 * s[2]            # a ball is thick where it spreads; two thin sheets a few mm apart are not
        cand, need = (2, (0, 1, 2)) if (s[2] / s[0] >= 0.5 and solid) else ((0, (1, 2)) if tube else (1, (0, 1)))
        bad = [a for a in need if k[a] < K_RESOLVED]
        if cand == 1 and not bad and k[2] < K_RESOLVED:
            # a sheet may be thin below resolution, but only if it is clearly WIDER than the thickness the sampling could hide:
            # otherwise a tube (round cross-section) seen in one coarse slice would be called a sheet
            if axis_extent_mm(Qc @ E[:, 1], w[1]) < FLAT_FACTOR * max(k[2], 1.0) * w[2]: bad = [2]
        if not bad: cls[i] = cand
        else: cls[i] = 5 if any(w[a] >= ANISO_LIMITED * vmin for a in bad) else 4
    return out, cls, nn, kk


def hessian_features(img, mask, vox, sigmas_mm=HESS_SIGMAS_MM):
    """image-intensity Hessian at the mask voxels, repository convention (detect_css.py): scale-normalised (x sigma^2),
    eigenvalues sorted by |lambda| ascending (l1 smallest); a DARK line / sheet is an intensity minimum -> the large
    curvatures are POSITIVE. Per voxel, the scale with the largest l3 wins. tube_h = |l2|/l3 when l3 > 0 and
    |l1|/l3 < 0.5 (detect_css's TUBE); sheet_h = 1 - |l2|/l3 when l3 > 0; blob_h = |l1|/l3 when l3 > 0."""
    vox = np.asarray(vox, float); idx = np.nonzero(mask); n = len(idx[0])
    best = np.full(n, -np.inf, np.float32); eig = np.zeros((n, 3), np.float32); vec = np.zeros((n, 3), np.float32); sig = np.zeros(n, np.float32)
    If = img.astype(np.float32)
    for s_mm in sigmas_mm:
        sg = s_mm / vox; H = np.zeros((n, 3, 3), np.float32)
        for a in range(3):
            for b in range(a, 3):
                order = [0, 0, 0]; order[a] += 1; order[b] += 1
                h = ndi.gaussian_filter(If, sg, order=order)[idx] / (vox[a] * vox[b]) * s_mm ** 2
                H[:, a, b] = h; H[:, b, a] = h
        w, V = np.linalg.eigh(H); o = np.argsort(np.abs(w), axis=1)
        w = np.take_along_axis(w, o, 1); V = np.take_along_axis(V, o[:, None, :], 2)
        upd = w[:, 2] > best; best[upd] = w[upd, 2]; eig[upd] = w[upd]; vec[upd] = V[upd][:, :, 0]; sig[upd] = s_mm
    l3 = np.maximum(eig[:, 2], 1e-9); pos = eig[:, 2] > 0
    tube = np.where(pos & (np.abs(eig[:, 0]) / l3 < 0.5), np.abs(eig[:, 1]) / l3, 0.0)
    sheet = np.where(pos, 1 - np.abs(eig[:, 1]) / l3, 0.0)
    blob = np.where(pos, np.abs(eig[:, 0]) / l3, 0.0)
    cls = np.where(~pos, 3, np.argmax(np.stack([tube, sheet, blob], 1), 1))
    return dict(eig=eig, axis=vec, sigma=sig, tube=tube, sheet=sheet, blob=blob, cls=cls)


# ---------------------------------------------------------------- cross-sections
def cross_sections(P_mm, axes, vox, n=12):
    """slabs perpendicular to the first principal axis; per slab: area (voxel volume / slab width), equivalent diameter,
    major / minor axis (2-D extents in the slab), eccentricity. Limitation: for a strongly curved object the PC1 slabs cut
    obliquely - the local-shape overlay is the curvature-independent measure."""
    t = (P_mm - P_mm.mean(0)) @ axes[:, 0]; lo, hi = t.min(), t.max()
    if hi - lo < 1e-6: return []
    vv = float(np.prod(vox)); w = (hi - lo) / n; out = []
    for k in range(n):
        a, b = lo + k * w, lo + (k + 1) * w
        sel = (t >= a) & ((t < b) if k < n - 1 else (t <= b))
        if sel.sum() < 2: out.append(dict(i=k, pos_mm=round(float((a + b) / 2), 1), n=int(sel.sum()))); continue
        Q = (P_mm[sel] - P_mm[sel].mean(0)) @ axes[:, 1:]
        e = np.ptp(Q, axis=0) + np.abs(axes[:, 1:]).T @ np.asarray(vox, float)
        ev = np.sort(np.linalg.eigvalsh(np.cov(Q.T)))[::-1] if sel.sum() > 2 else np.array([0, 0])
        area = sel.sum() * vv / max(w, 1e-6)
        out.append(dict(i=k, pos_mm=round(float((a + b) / 2), 1), n=int(sel.sum()), area_mm2=round(float(area), 1),
                        eq_diam_mm=round(float(2 * np.sqrt(area / np.pi)), 2), major_mm=round(float(e.max()), 2), minor_mm=round(float(e.min()), 2),
                        ecc=round(float(np.sqrt(max(0.0, 1 - ev[1] / ev[0]))) if ev[0] > 0 else 0.0, 2)))
    return out


# ---------------------------------------------------------------- the analysis
def analyse(mask, vox, img=None, psd=None, cortex=None, vessel=None, radius_mm=None):
    """mask: bool crop (candidate only). Returns measurements + per-voxel arrays for the viewer."""
    mask = np.asarray(mask, bool).copy(); vox = np.asarray(vox, float)
    P_idx = np.argwhere(mask); P = P_idx * vox; n = len(P)
    if n == 0: return dict(error="empty mask"), {}
    vmax, vmin = float(vox.max()), float(vox.min()); vv = float(np.prod(vox))
    lab, nc = ndi.label(mask, S26)
    comps = sorted([dict(id=k, n_vox=int((lab == k).sum()), volume_mm3=round(float((lab == k).sum() * vv), 1)) for k in range(1, nc + 1)],
                   key=lambda c: -c["n_vox"])
    w, ax, sd = pca(P); ext = extent_along(P, ax, vox)
    volume = n * vv
    v_raw, f_raw, area = mesh(mask, vox)
    v_s, f_s, _ = mesh(mask, vox, smooth_iter=8)
    vol_mesh_raw, vol_mesh_s = mesh_volume(v_raw, f_raw), mesh_volume(v_s, f_s)
    sph = float(np.pi ** (1 / 3) * (6 * volume) ** (2 / 3) / area) if area > 0 else np.nan
    th, dt = local_thickness(mask, vox); tv = th[mask]
    # per-voxel neighbourhood: 3 x the local thickness (4-7 mm; at least 3 voxels) so a sheet's edge still sees the sheet's
    # width while a thin tube next to a sheet is judged on itself
    Rv = np.clip(3.0 * tv, max(4.0, 3.0 * vmax), max(7.0, 3.0 * vmax)) if radius_mm is None else np.full(n, float(radius_mm))
    R = float(np.median(Rv))
    desc, gcls, nn, kk = local_shape(P, Rv, tv, vmax, comp=lab[mask], vox=vox)
    share = {CLASS_NAMES[k]: round(float((gcls == k).mean()), 3) for k in range(len(CLASS_NAMES))}
    sk, sk_note = skeleton(mask); sg = skeleton_graph(sk, vox)
    tube_share = share["tube"]
    # v5.14-gui: a curve skeleton (length along a line) is meaningful for any clearly ELONGATED object whose cross-section is
    # tube-like OR not resolvable - it does not require a confident tube class; never for sheets
    line_like = (tube_share + share["unresolved"] + share["acquisition_limited"]) >= 0.4 and sd[0] > 0 and sd[1] / sd[0] <= 0.5
    sk_ok = line_like and len(sg["points"]) >= 3
    if not sk_ok: sk_note = (sk_note + "; " if sk_note else "") + ("not shown: the object is not curve-like (the medial set of a sheet is a surface)" if not line_like else "too few skeleton voxels")
    xs = cross_sections(P, ax, vox)
    xs_ok = [c for c in xs if "area_mm2" in c]
    cv = float(np.std([c["eq_diam_mm"] for c in xs_ok]) / max(np.mean([c["eq_diam_mm"] for c in xs_ok]), 1e-6)) if len(xs_ok) >= 3 else np.nan
    res = dict(n_vox=n, vox=[round(float(x), 3) for x in vox], components=comps,
               pca_eigen_mm2=[round(float(x), 2) for x in w], pca_sd_mm=[round(float(x), 2) for x in sd], pca_axes=ax.T.round(3).tolist(),
               pca_ratio=[1.0, round(float(sd[1] / sd[0]), 2) if sd[0] else 0, round(float(sd[2] / sd[0]), 2) if sd[0] else 0],
               extent_mm=[round(float(x), 1) for x in ext], bbox_mm=[round(float(x), 1) for x in (np.ptp(P_idx, 0) + 1) * vox],
               volume_mm3=round(volume, 1), surface_mm2=round(area, 1), sa_to_vol=round(area / volume, 2) if volume else None,
               sphericity=round(sph, 2), mesh_volume_raw_mm3=round(vol_mesh_raw, 1), mesh_volume_smoothed_mm3=round(vol_mesh_s, 1),
               smoothing_volume_change_pct=round(100 * (vol_mesh_s - vol_mesh_raw) / vol_mesh_raw, 1) if vol_mesh_raw else None,
               thickness_mm=dict(mean=round(float(tv.mean()), 2), median=round(float(np.median(tv)), 2), min=round(float(tv.min()), 2), max=round(float(tv.max()), 2),
                                 p10=round(float(np.percentile(tv, 10)), 2), p90=round(float(np.percentile(tv, 90)), 2)),
               local_radius_mm=round(R, 2), local_share=share,
               resolution=dict(rule=f"a class is claimed only when the structure spans >= {K_RESOLVED} samples along every direction it depends on",
                               resolved_share=round(float(np.isin(gcls, (0, 1, 2)).mean()), 3),
                               indeterminate_share=round(float(np.isin(gcls, (4, 5)).mean()), 3),
                               samples_median=[round(float(x), 2) for x in np.median(kk[nn >= 8], 0)] if (nn >= 8).any() else None), xsections=xs, xsection_cv=round(cv, 2) if np.isfinite(cv) else None,
               skeleton=dict(ok=bool(sk_ok), note=sk_note, length_mm=sg["length_mm"], n_end=sg["n_end"], n_branch=sg["n_branch"]))
    arr = dict(P_idx=P_idx, gcls=gcls, desc=desc, thick=tv, sk=sg["points"] if sk_ok else np.zeros((0, 3), int),
               sk_branch=sg["branch_pts"] if sk_ok else np.zeros((0, 3), int), mesh_raw=(v_raw, f_raw), mesh=(v_s, f_s))
    # thickness along the skeleton (ordered along PC1)
    if sk_ok:
        sp = sg["points"]; order = np.argsort((sp * vox - P.mean(0)) @ ax[:, 0])
        res["skeleton"]["radius_profile"] = [[round(float(((sp[i] * vox - P.mean(0)) @ ax[:, 0])), 1), round(float(th[tuple(sp[i])] / 2), 2)] for i in order]
    # image Hessian (separate from geometry)
    if img is not None:
        h = hessian_features(img, mask, vox); arr["hess"] = h
        hs = {CLASS_NAMES[k]: round(float((h["cls"] == k).mean()), 3) for k in range(4)}   # image Hessian: no resolution classes
        res["hessian"] = dict(convention="eigenvalues sorted by |l| ascending, scale-normalised, dark structure -> positive l3 (detect_css.py)",
                              sigmas_mm=list(HESS_SIGMAS_MM), share=hs, tube_med=round(float(np.median(h["tube"])), 2),
                              sheet_med=round(float(np.median(h["sheet"])), 2), blob_med=round(float(np.median(h["blob"])), 2),
                              agree_with_geometry=round(float((h["cls"] == gcls)[gcls < 3].mean()), 2) if (gcls < 3).any() else None)
    # pial surface relation
    if psd is not None:
        d = psd[mask]; res["surface"] = dict(within_1mm=round(float((np.abs(d) <= 1).mean()), 2), median_pial_mm=round(float(np.median(d)), 2),
                                             in_csf=round(float((d > 0.5).mean()), 2), in_tissue=round(float((d < -0.5).mean()), 2))
    if cortex is not None:
        edge = cortex & ~ndi.binary_erosion(cortex, S26)
        near = edge & (ndi.distance_transform_edt(~mask, sampling=vox) <= 1.5)
        res.setdefault("surface", {})["footprint_mm2"] = round(float(near.sum() * vv ** (2 / 3)), 1); arr["footprint"] = np.argwhere(near)
    # vessel map context
    if vessel is not None and vessel.any():
        vl, nv = ndi.label(vessel, S26); touch = np.unique(vl[ndi.binary_dilation(mask, S26, iterations=1) & (vl > 0)])
        conn = np.isin(vl, touch[touch > 0]); contact = mask & ndi.binary_dilation(vessel, S26)
        res["vessel"] = dict(present=True, connected=bool(len(touch[touch > 0])), n_connected_segments=int((touch > 0).sum()),
                             connected_length_mm=round(float(conn.sum() * vv ** (1 / 3)), 1), contact_vox=int(contact.sum()),
                             note="a connection is evidence of vascular anatomy nearby, not proof that the candidate is a vein")
        arr["vessel"] = vessel; arr["vessel_conn"] = conn; arr["contact"] = np.argwhere(contact)
    else: res["vessel"] = dict(present=vessel is not None, connected=False)
    res["reliability"], res["reliability_notes"] = reliability(res, vox)
    res["summary"] = summary(res)
    return res, arr


def reliability(r, vox):
    vmax, vmin = float(np.max(vox)), float(np.min(vox)); notes = []
    if r["n_vox"] < 30: notes.append(f"only {r['n_vox']} voxels")
    if r["thickness_mm"]["median"] < 1.5 * vmax: notes.append(f"median thickness {r['thickness_mm']['median']} mm is close to the largest voxel side ({vmax:g} mm)")
    if vmax / vmin > 2: notes.append(f"anisotropic voxels ({vmax / vmin:.1f}:1): shapes along the slice direction are coarse")
    if len(r["components"]) > 1: notes.append(f"{len(r['components'])} separate pieces")
    ind = r.get("resolution", {}).get("indeterminate_share", 0) or 0
    if ind >= 0.2: notes.append(f"{round(100 * ind)} % of voxels: shape not resolvable at this voxel size (unresolved / acquisition-limited)")
    lvl = "low" if (r["n_vox"] < 30 or len(notes) >= 3 or ind >= 0.5) else ("moderate" if notes else "good")
    return lvl, notes


def summary(r):
    s = r["local_share"]; ranked = sorted([(s[k], k) for k in ("sheet", "tube", "blob")], reverse=True)
    main, second = ranked[0], ranked[1]
    word = {"sheet": "sheet-like", "tube": "tube-like", "blob": "blob-like"}
    ind = s.get("unresolved", 0) + s.get("acquisition_limited", 0)
    if ind >= 0.4:
        why = "the slice geometry (acquisition-limited)" if s.get("acquisition_limited", 0) >= s.get("unresolved", 0) else "the structure being small for the voxel grid"
        txt = f"local shape NOT resolvable for {round(100 * ind)} % of voxels because of {why}; no tube / sheet / blob claim"
    elif main[0] < 0.4: txt = "mixed / indeterminate local geometry"
    elif second[0] >= 0.2: txt = f"predominantly {word[main[1]]} geometry with a {word[second[1]]} part ({round(100 * second[0])} %) - mixed"
    else: txt = f"predominantly {word[main[1]]} geometry"
    if r.get("surface", {}).get("within_1mm") is not None:
        w1 = r["surface"]["within_1mm"]; txt += "; follows the pial surface" if w1 >= 0.6 else ("; partly on the pial surface" if w1 >= 0.3 else "; mostly away from the pial surface")
    if r.get("vessel", {}).get("connected"): txt += "; touches the vessel map"
    return txt + f". Measurement reliability: {r['reliability']}. Descriptive, not a diagnosis."


if __name__ == "__main__" and "--selftest" in sys.argv:
    vox = (0.8, 0.8, 1.2); g = np.indices((60, 60, 40)).astype(float) * np.array(vox)[:, None, None, None]
    tube = ((g[1] - 24) ** 2 + (g[2] - 24) ** 2 <= 1.2 ** 2) & (g[0] > 6) & (g[0] < 40)
    sheet = (np.abs(g[2] - 20) <= 0.7) & (g[0] > 6) & (g[0] < 30) & (g[1] > 6) & (g[1] < 26)
    for name, m in (("tube", tube), ("sheet", sheet)):
        r, _ = analyse(m, vox); print(name, r["local_share"], r["thickness_mm"]["median"], r["summary"])
