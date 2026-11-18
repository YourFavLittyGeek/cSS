"""Synthetic test volumes (dark structures on a bright background, SWI-like). Phantom results never show clinical validity."""
import numpy as np
from scipy import ndimage as ndi

BG = 1000.0

def grid(shape, vox):
    ii, jj, kk = np.meshgrid(*[np.arange(n) * v for n, v in zip(shape, vox)], indexing="ij")
    return ii, jj, kk

def _finish(dist_or_mask, vox, depth=0.6, blur_mm=0.4, noise=0.0, seed=0, soft=None):
    """Turn a [0,1] occupancy into an image: BG * (1 - depth * occ), Gaussian partial-volume blur, optional noise."""
    occ = dist_or_mask.astype(float)
    if blur_mm: occ = ndi.gaussian_filter(occ, [blur_mm / v for v in vox])
    img = BG * (1 - depth * occ)
    if noise: img = img + np.random.default_rng(seed).normal(0, noise * BG, img.shape)
    return img.astype(np.float32)

def plate(shape=(48, 48, 48), vox=(0.5, 0.5, 0.5), thick_mm=1.0, size_mm=(14, 14), normal_axis=0, **kw):
    g = grid(shape, vox); c = [n * v / 2 for n, v in zip(shape, vox)]
    ax = [a for a in range(3) if a != normal_axis]
    m = (np.abs(g[normal_axis] - c[normal_axis]) <= thick_mm / 2) & (np.abs(g[ax[0]] - c[ax[0]]) <= size_mm[0] / 2) \
        & (np.abs(g[ax[1]] - c[ax[1]]) <= size_mm[1] / 2)
    return _finish(m, vox, **kw), m

def oblique_plate(shape=(56, 56, 56), vox=(0.5, 0.5, 0.5), thick_mm=1.0, size_mm=14, n=(1, 1, 1), **kw):
    g = grid(shape, vox); c = [s * v / 2 for s, v in zip(shape, vox)]; n = np.asarray(n, float); n /= np.linalg.norm(n)
    d = [g[a] - c[a] for a in range(3)]; dn = sum(n[a] * d[a] for a in range(3))
    r2 = sum(d[a] ** 2 for a in range(3)) - dn ** 2
    m = (np.abs(dn) <= thick_mm / 2) & (r2 <= (size_mm / 2) ** 2)
    return _finish(m, vox, **kw), m

def tube(shape=(48, 48, 48), vox=(0.5, 0.5, 0.5), radius_mm=0.6, length_mm=20, axis=2, direction=None, **kw):
    g = grid(shape, vox); c = [n * v / 2 for n, v in zip(shape, vox)]
    u = np.zeros(3); u[axis] = 1.0
    if direction is not None: u = np.asarray(direction, float) / np.linalg.norm(direction)
    d = [g[a] - c[a] for a in range(3)]; t = sum(u[a] * d[a] for a in range(3))
    r2 = sum(d[a] ** 2 for a in range(3)) - t ** 2
    m = (r2 <= radius_mm ** 2) & (np.abs(t) <= length_mm / 2)
    return _finish(m, vox, **kw), m

def blob(shape=(40, 40, 40), vox=(0.5, 0.5, 0.5), radius_mm=1.5, **kw):
    g = grid(shape, vox); c = [n * v / 2 for n, v in zip(shape, vox)]
    m = sum((g[a] - c[a]) ** 2 for a in range(3)) <= radius_mm ** 2
    return _finish(m, vox, **kw), m

def curved_sheet(shape=(64, 64, 48), vox=(0.5, 0.5, 0.5), radius_mm=10.0, thick_mm=1.0, arc_deg=90, height_mm=10, **kw):
    """Band following a cylindrical 'cortical surface' of radius R (axis = z): cSS along a curved gyrus."""
    g = grid(shape, vox); c = [n * v / 2 for n, v in zip(shape, vox)]
    x, y, z = g[0] - c[0], g[1] - c[1] + radius_mm * 0.5, g[2] - c[2]
    r = np.hypot(x, y); th = np.degrees(np.arctan2(y, x))
    m = (np.abs(r - radius_mm) <= thick_mm / 2) & (np.abs(th - 90) <= arc_deg / 2) & (np.abs(z) <= height_mm / 2)
    return _finish(m, vox, **kw), m

def tram_track(shape=(48, 48, 48), vox=(0.5, 0.5, 0.5), gap_mm=2.0, thick_mm=0.8, size_mm=(14, 12), **kw):
    """Two parallel plates (both banks of a sulcus)."""
    g = grid(shape, vox); c = [n * v / 2 for n, v in zip(shape, vox)]
    inside = (np.abs(g[1] - c[1]) <= size_mm[0] / 2) & (np.abs(g[2] - c[2]) <= size_mm[1] / 2)
    m = inside & ((np.abs(g[0] - c[0] - gap_mm / 2) <= thick_mm / 2) | (np.abs(g[0] - c[0] + gap_mm / 2) <= thick_mm / 2))
    return _finish(m, vox, **kw), m

def fragmented_sheet(shape=(48, 48, 48), vox=(0.5, 0.5, 0.5), thick_mm=1.0, size_mm=16, n_holes=12, hole_mm=2.0, seed=3, **kw):
    img, m = plate(shape, vox, thick_mm, (size_mm, size_mm), **kw)
    g = grid(shape, vox); rng = np.random.default_rng(seed); c = [n * v / 2 for n, v in zip(shape, vox)]
    m = m.copy()
    for _ in range(n_holes):
        p = [c[0], c[1] + rng.uniform(-size_mm / 2, size_mm / 2), c[2] + rng.uniform(-size_mm / 2, size_mm / 2)]
        m &= ~((np.abs(g[1] - p[1]) <= hole_mm / 2) & (np.abs(g[2] - p[2]) <= hole_mm / 2))
    return _finish(m, vox, **{k: v for k, v in kw.items()}), m

def sheet_plus_tube(shape=(64, 64, 48), vox=(0.5, 0.5, 0.5), touching=True, **kw):
    """A plate and a tube in one connected object (merged cSS + vessel): the splitting test."""
    g = grid(shape, vox); c = [n * v / 2 for n, v in zip(shape, vox)]
    pl = (np.abs(g[0] - c[0]) <= 0.5) & (np.abs(g[1] - (c[1] - 6)) <= 6) & (np.abs(g[2] - c[2]) <= 6)
    off = 0.0 if touching else 3.0
    d1, d2 = g[0] - c[0], g[2] - c[2]
    tb = (d1 ** 2 + d2 ** 2 <= 0.6 ** 2) & (g[1] >= c[1] + off) & (g[1] <= c[1] + 14)
    return _finish(pl | tb, vox, **kw), pl, tb

def branching_vessel(shape=(64, 64, 48), vox=(0.5, 0.5, 0.5), radius_mm=0.6, **kw):
    """Y-shaped vessel: trunk + two branches."""
    _, t0 = tube(shape, vox, radius_mm, 14, direction=(0, 1, 0))
    g = grid(shape, vox); c = np.array([n * v / 2 for n, v in zip(shape, vox)])
    m = t0.copy()
    for dr in ((1, 1, 0), (-1, 1, 0)):
        u = np.array(dr, float); u /= np.linalg.norm(u); st = c + np.array([0, 7, 0])
        d = [g[a] - st[a] for a in range(3)]; t = sum(u[a] * d[a] for a in range(3)); r2 = sum(x ** 2 for x in d) - t ** 2
        m |= (r2 <= radius_mm ** 2) & (t >= 0) & (t <= 10)
    return _finish(m, vox, **kw), m

def resample_z(img, mask, factor, thr=0.5):
    """Thick slices: average `factor` consecutive slices (anisotropic voxels, partial volume)."""
    n = img.shape[2] // factor
    im = img[:, :, :n * factor].reshape(img.shape[0], img.shape[1], n, factor).mean(3)
    mk = mask[:, :, :n * factor].reshape(mask.shape[0], mask.shape[1], n, factor).mean(3) >= thr
    return im.astype(np.float32), mk
