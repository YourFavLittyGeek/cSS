"""Phase 1: what changes between v5.12 and the v5.13 fixes (B6 thickness chord, B10 MST skeleton length) on the original
11 shapes (with the B1-fixed generator) and on tilted / curved sheets. Writes results/phase1_compare.csv"""
import sys, os, csv, math
H = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(H)
sys.path.insert(0, os.path.join(ROOT, "scripts")); sys.path.insert(0, os.path.join(ROOT, "tests"))
import numpy as np
import css_morph3d as v512, css_morph3d_v2 as v2, morph_phantoms as mp
rows = []
for nm in mp.NAMES:
    m, t = mp.make(nm); vox = t["vox"]; th1, _ = v512.local_thickness(m, vox); th2 = v2.thickness(m, vox)
    sk, _ = v512.skeleton(m); L1 = v512.skeleton_graph(sk, vox)["length_mm"]; L2 = v2.mst_length(np.argwhere(sk), vox)
    rows.append(dict(case=nm, vox="x".join(map(str, vox)), v512_thick=round(float(np.median(th1[m])), 2), v513_thick=round(float(np.median(th2[m])), 2),
                     v512_skel_mm=L1, v513_skel_mst_mm=round(L2, 1)))
g_cache = {}
for vox in ((0.8, 0.8, 1.2), (0.4, 0.4, 0.4), (0.5, 0.5, 2.0)):
    g, n = mp._grid((24, 24, 24), vox); x, y, z = g; c = 12.0
    for ang in (0, 30, 45, 60):
        a = math.radians(ang); dist = (x - c) * math.sin(a) + (z - c) * math.cos(a); along = (x - c) * math.cos(a) - (z - c) * math.sin(a)
        for T in (1.2, 2.0):
            m = mp._down((np.abs(dist) <= T / 2) & (np.abs(along) <= 8) & (np.abs(y - c) <= 6), n, vox)
            if not m.any(): continue
            dig = m.sum() * np.prod(vox) / (16 * 12); th1, _ = v512.local_thickness(m, vox); th2 = v2.thickness(m, vox)
            rows.append(dict(case=f"tilted_{ang}deg_T{T}", vox="x".join(map(str, vox)), digitised=round(dig, 2), v512_thick=round(float(np.median(th1[m])), 2), v513_thick=round(float(np.median(th2[m])), 2)))
    # straight / diagonal cylinders: skeleton length truth = 18 mm (+ caps)
    for nm, pts in (("cyl_axis", [(3, c, c), (21, c, c)]), ("cyl_diag", [(4, 4, c), (20, 20, c)]), ("cyl_3d_diag", [(5, 5, 5), (19, 19, 19)])):
        m = mp._down(mp._tube(g, pts, 1.0), n, vox); sk, _ = v512.skeleton(m)
        Ltrue = float(np.linalg.norm(np.subtract(pts[1], pts[0])))
        rows.append(dict(case=f"{nm}_skeleton", vox="x".join(map(str, vox)), true_len=round(Ltrue, 1), v512_skel_mm=v512.skeleton_graph(sk, vox)["length_mm"], v513_skel_mst_mm=round(v2.mst_length(np.argwhere(sk), vox), 1)))
os.makedirs(f"{H}/results", exist_ok=True)
keys = list(dict.fromkeys(k for r in rows for k in r))
with open(f"{H}/results/phase1_compare.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=keys, restval=""); w.writeheader(); w.writerows(rows)
for r in rows: print(r)
