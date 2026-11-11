"""css_shape.py on synthetic shapes with hand-checked values (thin 0.8 mm and 3 mm slices). usage: check_shape.py"""
import os, sys, numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import css_shape as cs
def fail(m): print("FAIL:", m); sys.exit(1)


def grid(vox, mm=(40, 40, 40)):
    sh = tuple(int(round(m / v)) for m, v in zip(mm, vox)); idx = np.indices(sh).astype(float)
    return [(idx[a] - sh[a] / 2) * vox[a] for a in range(3)], sh


def sphere(vox, r):
    (x, y, z), sh = grid(vox); return x ** 2 + y ** 2 + z ** 2 <= r ** 2
def rod(vox, length, r):
    r = max(r, vox[2] * 0.6)                       # with 3 mm slices the rod must reach the slice centres (z = +-1.5 mm)
    (x, y, z), sh = grid(vox); return (np.abs(x) <= length / 2) & (y ** 2 + z ** 2 <= r ** 2)
def arc(vox, radius, ang_deg, thick):
    thick = max(thick, vox[2] * 1.05)
    (x, y, z), sh = grid(vox); rr = np.sqrt(x ** 2 + y ** 2); th = np.degrees(np.arctan2(y, x))
    return (np.abs(rr - radius) <= thick / 2) & (np.abs(th) <= ang_deg / 2) & (np.abs(z) <= thick / 2)
def disc(vox, r, h):
    h = max(h, vox[2] * 1.05)
    (x, y, z), sh = grid(vox); return (x ** 2 + y ** 2 <= r ** 2) & (np.abs(z) <= h / 2)


for vox in ((0.8, 0.8, 0.8), (0.8, 0.8, 3.0)):
    tag = f"{vox[2]:g} mm slices"
    b = sphere(vox, 2.4); m = cs.blob_measures(b, b, vox)                     # 4.8 mm sphere (microbleed-like)
    lim = 1.3 if vox[2] < 1 else 1.6          # on 3 mm slices a round 4.8 mm blob spans 2 slices = 6 mm in z vs 4 mm in plane (measured 1.5): the blob threshold must allow it
    if not (m["l_over_m"] <= lim and m["m_over_s"] <= 1.6 and m["fill"] >= 0.5): fail(f"sphere {tag}: {m}")
    r_ = rod(vox, 20, 0.8); m = cs.blob_measures(r_, r_, vox)                # 20 mm line, 1.6 mm wide
    if not (m["l_over_m"] >= 3.0): fail(f"rod {tag}: {m}")
    a_ = arc(vox, 10, 100, 1.6); m = cs.blob_measures(a_, a_, vox); br = cs.bend(np.argwhere(a_), vox)
    sr = cs.bend(np.argwhere(r_), vox)
    # analytic: 10 mm radius arc over 100 deg, 1.6 mm thick -> rms 1.26 mm (centre line 1.08 + thickness 0.65); straight 1.6 mm rod -> 0.57 mm
    if vox[2] < 1 and not (abs(br[0] - 1.26) <= 0.25 * 1.26): fail(f"arc rms {tag}: {br} (analytic 1.26)")
    if vox[2] < 1 and not (sr[0] <= 0.9 and br[1] >= 1.5 * sr[1] and br[1] >= 0.07): fail(f"bend {tag}: arc {br} vs rod {sr}")
    if vox[2] >= 1 and not (br[1] > sr[1]):                    # on 3 mm slices the slice thickness itself dominates the rms: bend only ranks, it does not separate
        fail(f"bend ranking {tag}: arc {br} vs rod {sr}")
    d_ = disc(vox, 5, 1.6); m = cs.blob_measures(d_, d_, vox)               # 10 mm disc
    if not (m["l_over_m"] <= 1.4 and m["e1"] >= 8): fail(f"disc {tag}: {m}")
    if vox[2] < 1:
        if not (m["m_over_s"] >= 3.0): fail(f"disc m_over_s on thin slices: {m}")
    print(f"shapes ok ({tag}): sphere l/m {cs.blob_measures(b, b, vox)['l_over_m']}, rod l/m {cs.blob_measures(r_, r_, vox)['l_over_m']}, arc bend {br[1]}, rod bend {sr[1]}")

# dark support: the support of a blob inside a bigger dark halo, capped; a disconnected dark island is left out
vox = (0.8, 0.8, 0.8); (x, y, z), sh = grid(vox); obj = (x ** 2 + y ** 2 + z ** 2) <= 1.2 ** 2
halo = (x ** 2 + y ** 2 + z ** 2) <= 3.0 ** 2; island = ((x - 14) ** 2 + y ** 2 + z ** 2) <= 2.0 ** 2
sup = cs.dark_support(halo | island, obj, vox, cap_mm=10, grow=1)
if (sup & island).any() or not sup[halo].all(): fail("dark support must contain the connected halo and not the island")
capd = cs.dark_support(np.ones(sh, bool), obj, vox, cap_mm=5, grow=1)
if (capd & ~(np.sqrt(x ** 2 + y ** 2 + z ** 2) <= 7.0)).any(): fail("dark support must respect the cap")

# depth / touch statistics
depth = np.zeros((10, 10, 10)); depth[:, :, 5:] = 6.0
om = np.zeros((10, 10, 10), bool); om[4:6, 4:6, :] = True          # an object running from the crown (z 0-4, depth 0) into the sulcus (z 5-9, depth 6)
st = cs.depth_stats(depth, np.argwhere(om))
if not (st["depth_range"] == 6.0 and st["crown_frac"] == 0.5 and st["deep_frac"] == 0.5): fail(f"depth stats {st}")
L = np.zeros((20, 20, 20), int); L[:10] = 1012; L[10:] = 1022; o = np.zeros_like(L, bool); o[9:11, 8:12, 8:12] = True
ts = cs.touch_stats(L, o, (1, 1, 1), 1.5)
if ts["n_labels"] != 2 or not (0.3 <= ts["label_spread"] <= 0.7): fail(f"touch stats {ts}")
o2 = np.zeros_like(L, bool); o2[3:5, 8:12, 8:12] = True; ts2 = cs.touch_stats(L, o2, (1, 1, 1), 1.5)
if ts2["n_labels"] != 1: fail(f"touch stats one label {ts2}")
print("dark support, depth and label-touch statistics ok")
print("RESULT shape OK")
