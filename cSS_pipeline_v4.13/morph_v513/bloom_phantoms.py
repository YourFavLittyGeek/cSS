"""Blooming phantoms with independent ground truth for (1) each underlying structure, (2) the blooming region, (3) the
detector-like candidate. Simplified signal model (NOT a dipole simulation): partial-volume occupancy o of each structure,
blurred by a Gaussian of sigma_b mm (blooming / PSF), saturating signal loss, Gaussian noise.
  I = 100 * (1 - a * min(1, 1.5 * blur(o))) + N(0, noise)
truth structure (per label) = voxels with occupancy >= 0.5; candidate = connected voxels with (100 - I)/noise >= 2.5
touching a structure (a stand-in for the detector's darkness gate); blooming = candidate minus all structures.
make_case(spec) -> dict(img, vox, labels (0 bg, 1.. structures), kinds, candidate, bloom, spec)"""
import sys, os, math
H = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(H), "tests"))
import numpy as np
from scipy import ndimage as ndi
import morph_phantoms as mp

BOX = (28.0, 28.0, 28.0)


def rot(angles):
    a, b, c = angles
    Rx = np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])
    Ry = np.array([[math.cos(b), 0, math.sin(b)], [0, 1, 0], [-math.sin(b), 0, math.cos(b)]])
    Rz = np.array([[math.cos(c), -math.sin(c), 0], [math.sin(c), math.cos(c), 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def local(g, R):
    c = np.array(BOX) / 2; X = g - c[:, None, None, None]
    return np.einsum("ji,j...->i...", R, X)                      # coordinates in the structure's own frame (R^T x)


def capsule(L, pts, r, ell=1.0):
    """union of capsules along a polyline in local coords; ell < 1 flattens the cross-section along local z (compressed vein)"""
    m = np.zeros(L.shape[1:], bool)
    for a, b in zip(pts[:-1], pts[1:]):
        a, b = np.asarray(a, float), np.asarray(b, float); ab = b - a
        t = np.clip(np.tensordot(ab, L - a[:, None, None, None], 1) / (ab @ ab), 0, 1)
        q = a[:, None, None, None] + ab[:, None, None, None] * t; d = L - q
        m |= (d[0] ** 2 + d[1] ** 2 + (d[2] / ell) ** 2) <= r * r
    return m


def band(L, width, thick, length, curv_r):
    """curved sheet (cSS-like band): surface z = s(x) with radius of curvature curv_r, |y| <= width/2, |x| <= length/2"""
    x, y, z = L; s = (x ** 2) / (2 * curv_r) if curv_r < 1e3 else 0 * x
    return (np.abs(z - s) <= thick / 2) & (np.abs(y) <= width / 2) & (np.abs(x) <= length / 2)


def arc(L0, r_curv, n=8):
    th = np.linspace(-L0 / (2 * r_curv), L0 / (2 * r_curv), n) if r_curv < 1e3 else None
    if th is None: return [(-L0 / 2, 0, 0), (L0 / 2, 0, 0)]
    return [(r_curv * math.sin(t), 0, r_curv * (1 - math.cos(t))) for t in th]


def make_case(sp):
    """sp keys: kind, vox, angles, sigma_b, a, noise, seed, + shape parameters"""
    vox = tuple(sp["vox"]); g, n = mp._grid(BOX, vox); L = local(g, rot(sp["angles"])); k = sp["kind"]; parts = []
    if k == "band": parts = [("sheet", band(L, sp["width"], sp["thick"], sp["length"], sp["curv"]))]
    elif k == "vein": parts = [("tube", capsule(L, arc(sp["length"], sp["curv"]), sp["r"], sp.get("ell", 1.0)))]
    elif k == "paired_veins":
        off = sp["r"] + sp["gap"] / 2; P = arc(sp["length"], sp["curv"])
        parts = [("tube", capsule(L, [(p[0], p[1] - off, p[2]) for p in P], sp["r"])), ("tube", capsule(L, [(p[0], p[1] + off, p[2]) for p in P], sp["r"]))]
    elif k == "vein_on_band":
        parts = [("sheet", band(L, sp["width"], sp["thick"], sp["length"], 1e9)),
                 ("tube", capsule(L, [(sp["length"] / 2 - 1, 0, 0), (sp["length"] / 2 + 9, 2, sp["rise"])], sp["r"]))]
    elif k == "band_vein_adjacent":
        parts = [("sheet", band(L, sp["width"], sp["thick"], sp["length"], 1e9)),
                 ("tube", capsule(L, [(-sp["length"] / 2, sp["width"] / 2 + sp["gap"] + sp["r"], 0), (sp["length"] / 2, sp["width"] / 2 + sp["gap"] + sp["r"], 0)], sp["r"]))]
    else: raise ValueError(k)
    f = [int(round(v / d)) for v, d in zip(vox, n[1])]; sh = [ni // fi for ni, fi in zip(n[0], f)]
    occ = []
    for _, pm in parts:
        o = pm[:sh[0] * f[0], :sh[1] * f[1], :sh[2] * f[2]].reshape(sh[0], f[0], sh[1], f[1], sh[2], f[2]).mean((1, 3, 5)); occ.append(o)
    otot = np.clip(np.sum(occ, 0), 0, 1)
    rng = np.random.default_rng(sp["seed"])
    loss = np.minimum(1.0, 1.5 * ndi.gaussian_filter(otot, [sp["sigma_b"] / v for v in vox]))
    img = 100 * (1 - sp["a"] * loss) + rng.normal(0, sp["noise"], otot.shape)
    labels = np.zeros(otot.shape, np.int16)
    for j, o in enumerate(occ, 1): labels[(o >= 0.5) & (labels == 0)] = j
    c = (100 - img) / sp["noise"]; dk = c >= 2.5
    dl, _ = ndi.label(dk, ndi.generate_binary_structure(3, 3))
    ids = np.unique(dl[ndi.binary_dilation(labels > 0) & (dl > 0)]); cand = np.isin(dl, ids[ids > 0])
    bloom = cand & (labels == 0)
    return dict(img=img.astype(np.float32), vox=vox, labels=labels, kinds=[p[0] for p in parts], candidate=cand, bloom=bloom, spec=sp,
                true_thick=sp.get("thick", 2 * sp.get("r", 0) * (sp.get("ell", 1.0) if k == "vein" else 1)), occ=otot)


VOXES = [(0.8, 0.8, 1.2), (0.5, 0.5, 2.0), (1.0, 1.0, 1.0), (0.6, 0.6, 3.0)]
KINDS = ["band", "vein", "paired_veins", "vein_on_band", "band_vein_adjacent"]


def random_spec(seed):
    """parameter ranges (also written to heldout_spec.json before the held-out set is generated)"""
    r = np.random.default_rng(seed); k = KINDS[seed % len(KINDS)]
    sp = dict(kind=k, seed=seed, vox=VOXES[r.integers(len(VOXES))], angles=[float(x) for x in r.uniform(-math.pi, math.pi, 3)],
              sigma_b=float(r.uniform(0.4, 1.2)), a=float(r.uniform(0.3, 0.7)), noise=float(r.uniform(2, 5)))
    if k in ("band", "vein_on_band", "band_vein_adjacent"):
        sp.update(width=float(r.uniform(3, 12)), thick=float(r.uniform(0.5, 2.0)), length=float(r.uniform(10, 18)), curv=float(r.choice([1e9, r.uniform(5, 30)])))
    if k in ("vein", "paired_veins", "vein_on_band", "band_vein_adjacent"):
        sp.update(r=float(r.uniform(0.4, 1.3)), length=sp.get("length", float(r.uniform(10, 18))), curv=sp.get("curv", float(r.choice([1e9, r.uniform(6, 30)]))))
    if k == "vein": sp["ell"] = float(r.choice([1.0, r.uniform(0.35, 0.6)]))           # compressed against a wall sometimes
    if k == "paired_veins": sp["gap"] = float(r.uniform(0.3, 3.0))
    if k == "vein_on_band": sp["rise"] = float(r.uniform(0, 6))
    if k == "band_vein_adjacent": sp["gap"] = float(r.uniform(0.3, 3.0))
    return sp
