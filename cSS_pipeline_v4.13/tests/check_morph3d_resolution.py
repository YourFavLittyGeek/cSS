"""check_morph3d_resolution.py - resolution-confidence matrix for css_morph3d.local_shape (v5.14-gui).

Tubes, sheets and blobs at several orientations (x, y, z, oblique in-plane / through-plane, 3-D oblique) and voxel spacings
(0.5 iso, 0.5x0.5x1, 0.5x0.5x2, 0.5x0.5x3, 1 iso). The EXPECTED outcome of each case is computed from physics, independently
of the classifier: nominal samples k = decisive width / w, w = the worst sampling interval in the directions that decide the
class. No edge-loss model is used (it differs between axis-aligned and oblique sampling); instead only clear cases are asserted:
  resolved   (k >= 3.5): the correct class must dominate (>= 0.7) and the wrong confident classes stay <= 0.1
  unresolved (k <= 2.0, the two-sample limit): confident classes together <= 0.2 - the shape must NOT be claimed
  grey zone  (2 < k < 3.5, or the sampling breaks the structure into several pieces - e.g. a 1 mm sheet tilted 45 deg through
             3 mm slices becomes one strip per slice, each judged alone): only "never the wrong class" (<= 0.2) is asserted
  not representable: the structure vanishes under sampling (< 8 voxels) - reported, counted neither as pass nor fail
Never acceptable at any resolution: a tube called sheet / blob, a sheet called tube, a blob called tube.
Synthetic geometry only. usage: python tests/check_morph3d_resolution.py   (exit 1 on any FAIL)"""
import os, sys, itertools
H = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(H), "scripts"))
import numpy as np
from scipy import ndimage as ndi
import css_morph3d as cm

FAILS = []; ROWS = []
def check(n, ok, info=""):
    print(f"{'PASS' if ok else 'FAIL'}  {n}  {info}"); (None if ok else FAILS.append(n))

FINE = 0.1; BOX = 32.0


def render(fn, vox):
    """supersample a signed-membership function on a 0.1 mm grid, then partial-volume downsample (>= 50 % of a voxel)."""
    f = np.round(np.array(vox) / FINE).astype(int); n = (np.round(BOX / np.array(vox))).astype(int)
    out = np.zeros(n, bool)
    for zi in range(n[2]):                                     # slice by slice keeps memory small
        zs = (zi * f[2] + np.arange(f[2]) + 0.5) * FINE
        xs = (np.arange(n[0] * f[0]) + 0.5) * FINE; ys = (np.arange(n[1] * f[1]) + 0.5) * FINE
        X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
        m = fn(X, Y, Z)
        frac = m.reshape(n[0], f[0], n[1], f[1], f[2]).mean((1, 3, 4))
        out[:, :, zi] = frac >= 0.5
    return out


def unit(v): v = np.asarray(v, float); return v / np.linalg.norm(v)


def tube_fn(axis, r, length=22.0):
    a = unit(axis); c = np.full(3, BOX / 2)
    def f(X, Y, Z):
        P = np.stack([X - c[0], Y - c[1], Z - c[2]], -1); t = P @ a
        d = np.linalg.norm(P - t[..., None] * a, axis=-1)
        return (d <= r) & (np.abs(t) <= length / 2)
    return f


def sheet_fn(normal, thick, rad=8.0):
    n = unit(normal); c = np.full(3, BOX / 2)
    def f(X, Y, Z):
        P = np.stack([X - c[0], Y - c[1], Z - c[2]], -1); t = P @ n
        inpl = np.linalg.norm(P - t[..., None] * n, axis=-1)
        return (np.abs(t) <= thick / 2) & (inpl <= rad)
    return f


def ball_fn(r):
    c = np.full(3, BOX / 2)
    return lambda X, Y, Z: (X - c[0]) ** 2 + (Y - c[1]) ** 2 + (Z - c[2]) ** 2 <= r * r


def worst_w(dirs, vox):
    return max(cm.sampling_width(unit(d), vox) for d in dirs)


def perp_dirs(a, n=24):
    a = unit(a); b = unit(np.cross(a, [1, 0, 0] if abs(a[0]) < 0.9 else [0, 1, 0])); c = np.cross(a, b)
    return [np.cos(t) * b + np.sin(t) * c for t in np.linspace(0, np.pi, n, endpoint=False)]


def inplane_dirs(nrm, n=24): return perp_dirs(nrm, n)


VOX = [(0.5, 0.5, 0.5), (0.5, 0.5, 1.0), (0.5, 0.5, 2.0), (0.5, 0.5, 3.0), (1.0, 1.0, 1.0)]
ORIENT = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1), "oblique_xy": (1, 1, 0), "oblique_xz": (1, 0, 1), "oblique_xyz": (1, 1, 1)}
CASES = []
for o, a in ORIENT.items():
    CASES += [("tube_r2.0", "tube", a, o, tube_fn(a, 2.0), 4.0), ("tube_r0.6", "tube", a, o, tube_fn(a, 0.6), 1.2)]
    CASES += [("sheet_t1.0", "sheet", a, o, sheet_fn(a, 1.0), 16.0)]          # sheet NORMAL along the orientation
CASES += [("blob_r3.0", "blob", None, "-", ball_fn(3.0), 6.0), ("blob_r1.0", "blob", None, "-", ball_fn(1.0), 2.0)]

for (name, kind, a, o, fn, decisive), vox in itertools.product(CASES, VOX):
    vox = np.array(vox); m = render(fn, vox)
    if m.sum() < 8:
        print(f"NOT-REPRESENTABLE  {name} {o} vox {'x'.join(f'{v:g}' for v in vox)}: {int(m.sum())} voxels after sampling (structure lost)")
        ROWS.append(dict(case=name, orientation=o, vox="x".join(f"{v:g}" for v in vox), k_physics=None, pieces=0, expected="not representable",
                         tube=None, sheet=None, blob=None, unresolved=None, acquisition_limited=None, indeterminate=None)); continue
    r, _ = cm.analyse(m, vox); s = r["local_share"]
    if kind == "tube": dirs = perp_dirs(a)
    elif kind == "sheet": dirs = inplane_dirs(a)
    else: dirs = [(1, 0, 0), (0, 1, 0), (0, 0, 1)]
    wv = worst_w(dirs, vox); k_phys = decisive / wv               # nominal samples across the decisive width, worst direction
    pieces = int(ndi.label(m, cm.S26)[1])
    state = "grey" if pieces > 1 else ("resolved" if k_phys >= 3.5 else ("unresolved" if k_phys <= 2.0 else "grey"))
    wrong = {"tube": s["sheet"] + s["blob"], "sheet": s["tube"], "blob": s["tube"] + s["sheet"]}[kind]
    conf = s["tube"] + s["sheet"] + s["blob"]; ind = s.get("unresolved", 0) + s.get("acquisition_limited", 0)
    tag = f"{name} {o} vox {'x'.join(f'{v:g}' for v in vox)} (k={k_phys:.1f}, {pieces} piece(s), {state})"
    info = f"tube {s['tube']:.2f} sheet {s['sheet']:.2f} blob {s['blob']:.2f} unres {s.get('unresolved', 0):.2f} acq {s.get('acquisition_limited', 0):.2f}"
    if state == "resolved":
        check(f"{tag}: correct class dominates", s[kind] >= 0.7, info)
        check(f"{tag}: wrong confident class <= 0.1", wrong <= 0.1, info)
    elif state == "unresolved":
        check(f"{tag}: no confident shape claim (<= 0.2)", conf <= 0.2, info)
    else:
        check(f"{tag}: never the wrong class (<= 0.2)", wrong <= 0.2, info)
    ROWS.append(dict(case=name, orientation=o, vox="x".join(f"{v:g}" for v in vox), k_physics=round(k_phys, 2), pieces=pieces, expected=state,
                     tube=s["tube"], sheet=s["sheet"], blob=s["blob"], unresolved=s.get("unresolved", 0), acquisition_limited=s.get("acquisition_limited", 0),
                     indeterminate=round(ind, 3)))

try:
    import csv
    out = os.path.join(os.path.dirname(H), "docs", "gui_v514", "morph3d_resolution_matrix.csv")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(ROWS[0])); w.writeheader(); w.writerows(ROWS)
except Exception as e: print("matrix csv not written:", e)
nr = sum(r["expected"] == "not representable" for r in ROWS)
print(f"\nRESULT morph3d_resolution {'OK' if not FAILS else 'FAILED: ' + str(len(FAILS))}  ({len(ROWS)} cases, {nr} not representable)")
sys.exit(1 if FAILS else 0)
