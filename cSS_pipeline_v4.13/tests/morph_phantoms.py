"""Synthetic masks with known geometry for css_morph3d (3-D viewer validation). Each shape is drawn on a fine 0.2 mm
grid and then sampled onto the target voxel grid by AVERAGING (partial volume) and thresholding at 0.5, so the masks
carry realistic staircase / partial-volume effects.  make(name, vox=(0.8, 0.8, 1.2)) -> bool mask, truth dict"""
import numpy as np

FINE = 0.2


def _steps(vox):
    """v5.13 (B1 fix): fine step per axis that divides the voxel EXACTLY (vox / ceil(vox / 0.2)); v5.12 used 0.2 mm for
    every axis and averaged round(vox / 0.2) samples, so a '0.5 mm' voxel really spanned 0.4 mm"""
    return [float(v) / max(1, int(np.ceil(float(v) / FINE - 1e-9))) for v in vox]


def _grid(shape_mm, vox=None):
    st = _steps(vox) if vox is not None else [FINE] * 3
    n = [int(round(s / d)) for s, d in zip(shape_mm, st)]
    g = np.stack(np.meshgrid(*[(np.arange(k) + 0.5) * d for k, d in zip(n, st)], indexing="ij"))
    return g, (n, st)


def _tube(g, pts, r):
    """union of capsules along a polyline (mm)"""
    m = np.zeros(g.shape[1:], bool)
    for a, b in zip(pts[:-1], pts[1:]):
        a, b = np.asarray(a, float), np.asarray(b, float); ab = b - a
        t = np.clip(np.tensordot(ab, (g - a[:, None, None, None]), 1) / (ab @ ab), 0, 1)
        q = a[:, None, None, None] + ab[:, None, None, None] * t
        m |= ((g - q) ** 2).sum(0) <= r * r
    return m


def _down(m, n, vox):
    """average the fine mask into vox-sized voxels (partial volume) and keep voxels >= 50 % filled"""
    n, st = n if isinstance(n, tuple) else (n, [FINE] * 3)
    f = [max(1, int(round(v / d))) for v, d in zip(vox, st)]
    bad = [v for v, d, k in zip(vox, st, f) if abs(k * d - v) > 1e-6]
    if bad: raise ValueError(f"voxel size {vox} is not a whole number of fine steps {st} - build the grid with _grid(shape, vox)")
    k = [ni // fi for ni, fi in zip(n, f)]
    m = m[:k[0] * f[0], :k[1] * f[1], :k[2] * f[2]].astype(np.float32)
    return m.reshape(k[0], f[0], k[1], f[1], k[2], f[2]).mean((1, 3, 5)) >= 0.5


BOX = (24.0, 24.0, 24.0)


def make(name, vox=(0.8, 0.8, 1.2), seed=0):
    if name == "thin_aniso": vox = (0.5, 0.5, 3.0)
    g, n = _grid(BOX, vox); x, y, z = g; c = 12.0; rng = np.random.default_rng(seed)
    if name == "cylinder":
        m = _tube(g, [(3, c, c), (21, c, c)], 1.0); t = dict(expect="tube", radius_mm=1.0)
    elif name == "curved_cylinder":
        th = np.linspace(0, np.pi, 12); pts = [(c + 8 * np.cos(a), c + 8 * np.sin(a) - 4, c) for a in th]
        m = _tube(g, pts, 1.0); t = dict(expect="tube", radius_mm=1.0)
    elif name == "branching_tube":
        m = _tube(g, [(3, c, c), (21, c, c)], 0.9) | _tube(g, [(c, c, c), (c + 6, c + 8, c + 4)], 0.9); t = dict(expect="tube", branch=True)
    elif name == "sheet":
        m = (np.abs(z - c) <= 0.6) & (np.abs(x - c) <= 8) & (np.abs(y - c) <= 6); t = dict(expect="sheet", thickness_mm=1.2)
    elif name == "curved_sheet":
        surf = c - 4 + 0.06 * (x - c) ** 2
        m = (np.abs(z - surf) <= 0.6) & (np.abs(x - c) <= 8) & (np.abs(y - c) <= 6); t = dict(expect="sheet", thickness_mm=1.2)
    elif name == "irregular_patch":
        r = 6 + 1.5 * np.sin(3 * np.arctan2(y - c, x - c)) + 0.8 * np.cos(5 * np.arctan2(y - c, x - c))
        m = (np.abs(z - c - 0.5 * np.sin((x - c) / 3)) <= 0.6) & (np.hypot(x - c, y - c) <= r); t = dict(expect="sheet")
    elif name == "blob":
        m = ((x - c) ** 2 + (y - c) ** 2 + ((z - c) / 0.8) ** 2) <= 3.5 ** 2; t = dict(expect="blob")
    elif name == "sheet_plus_tube":
        sheet = (np.abs(z - c) <= 0.6) & (x >= 2) & (x <= 12) & (np.abs(y - c) <= 6)
        m = sheet | _tube(g, [(12, c, c), (22, c, c + 6)], 1.0); t = dict(expect="mixed")
    elif name == "two_pieces":
        m = _tube(g, [(3, 8, c), (21, 8, c)], 1.0) | ((np.abs(z - c) <= 0.6) & (np.abs(x - c) <= 6) & (y >= 13) & (y <= 21)); t = dict(expect="components", n=2)
    elif name == "fragmented_sheet":
        base = (np.abs(z - c) <= 0.6) & (np.abs(x - c) <= 9) & (np.abs(y - c) <= 6)
        m = base & ~((np.abs((x - c) % 6 - 3) < 0.8) | (np.abs(y - c) < 0.8)); t = dict(expect="sheet", fragmented=True)
    elif name == "thin_aniso":
        m = (np.abs(z - c - 1.5) <= 1.0) & (np.abs(x - c) <= 8) & (np.abs(y - c) <= 6); vox = (0.5, 0.5, 3.0)
        t = dict(expect="sheet", note="2 mm sheet on 0.5 x 0.5 x 3 mm voxels: thinner than one slice")
    else: raise ValueError(name)
    return _down(m, n, vox), dict(t, name=name, vox=list(vox))


NAMES = ["cylinder", "curved_cylinder", "branching_tube", "sheet", "curved_sheet", "irregular_patch", "blob",
         "sheet_plus_tube", "two_pieces", "fragmented_sheet", "thin_aniso"]
