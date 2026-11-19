"""Independent audit of scripts/css_morph3d.py (v5.12). Read-only: imports the module, never edits it.
Writes audit_3d/results/*.csv|json|png.  usage: CSS_BASE=<base with PH6 detected> python audit_3d/run_audit.py"""
import sys, os, json, csv, math
H = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(H)
sys.path.insert(0, os.path.join(ROOT, "scripts")); sys.path.insert(0, os.path.join(ROOT, "tests"))
import numpy as np
from scipy import ndimage as ndi
import css_morph3d as cm, morph_phantoms as mp
OUT = os.path.join(H, "results"); os.makedirs(OUT, exist_ok=True)
def save(name, rows):
    with open(f"{OUT}/{name}.csv", "w", newline="") as f:
        keys = list(dict.fromkeys(k for r in rows for k in r)); w = csv.DictWriter(f, fieldnames=keys, restval=""); w.writeheader(); w.writerows(rows)
    print(f"-- {name}: {len(rows)} rows")
FINE = mp.FINE

def grid(box=(24, 24, 24)): return mp._grid(box)
def down(m, n, vox): return mp._down(m, n, vox)
def down_labels(L, n, vox, k):
    """majority ground-truth label per voxel among labels 1..k (fine grid), restricted to voxels the union mask keeps"""
    f = [max(1, int(round(v / FINE))) for v in vox]; s = [ni // fi for ni, fi in zip(n, f)]
    L = L[:s[0] * f[0], :s[1] * f[1], :s[2] * f[2]]
    cnt = np.stack([(L == j).reshape(s[0], f[0], s[1], f[1], s[2], f[2]).mean((1, 3, 5)) for j in range(1, k + 1)])
    return np.argmax(cnt, 0) + 1

def med_thick(m, vox):
    t, _ = cm.local_thickness(m, vox); return float(np.median(t[m])) if m.any() else float("nan")

def tube_pts(g, pts, r): return mp._tube(g, pts, r)
ADV = []
def adv(name, vox, parts, expect, note=""):
    """parts: list of (label_name, fine_mask). Ground truth per structure; union = candidate"""
    gg, nn = grid()
    L = np.zeros(gg.shape[1:], np.uint8)
    for j, (_, pm) in enumerate(parts, 1): L[pm & (L == 0)] = j
    union = down(L > 0, nn, vox); lab = down_labels(L, nn, vox, len(parts)) * union
    r, a = cm.analyse(union, vox)
    if "error" in r: ADV.append(dict(case=name, error=r["error"])); return
    P = a["P_idx"]; gl = lab[tuple(P.T)]; out = dict(case=name, vox="x".join(map(str, vox)), n_vox=int(union.sum()), components=len(r["components"]),
                                                       expected_components=expect.get("components", ""), summary=r["summary"], note=note)
    ok_all = True
    for j, (nm, _) in enumerate(parts, 1):
        sel = gl == j
        if not sel.any(): out[f"{nm}_vox"] = 0; continue
        want = {"tube": 0, "sheet": 1, "blob": 2}[nm.split("_")[0]]
        acc = float((a["gcls"][sel] == want).mean()); out[f"{nm}_vox"] = int(sel.sum()); out[f"{nm}_correct"] = round(acc, 2)
        out[f"{nm}_tube/sheet/blob/unc"] = "/".join(str(round(float((a['gcls'][sel] == k).mean()), 2)) for k in range(4))
        ok_all &= acc >= 0.7
    if expect.get("components"): ok_all &= len(r["components"]) == expect["components"]
    out["pass_0.7"] = ok_all; ADV.append(out)

g, n = grid(); x, y, z = g; c = 12.0; V = (0.8, 0.8, 1.2)
ell = (((y - c) / 1.6) ** 2 + ((z - c) / 0.9) ** 2 <= 1) & (x >= 3) & (x <= 21)
adv("04b_compressed_vein_3.2x1.8mm", V, [("tube", ell)], {"components": 1}, "flattened vessel")
sheet10 = (np.abs(z - c) <= 0.6) & (np.abs(x - c) <= 9) & (y >= c - 8) & (y <= c + 2)
adv("10c_tube_r0.8_beside_sheet_gap1mm", V, [("sheet", sheet10), ("tube", tube_pts(g, [(3, c + 3.8, c), (21, c + 3.8, c)], 0.8))], {"components": 2})
adv("10d_tube_r0.8_touching_sheet", V, [("sheet", sheet10), ("tube", tube_pts(g, [(3, c + 2.8, c), (21, c + 2.8, c)], 0.8))], {"components": 1})
adv("03b_vein_r1.2_parallel_to_surface", V, [("tube", tube_pts(g, [(3, c, c), (21, c + 2, c)], 1.2))], {"components": 1})
for w in (2, 3, 4, 6, 8):           # narrow sheet strip (ribbon) 1.2 mm thick: where does "sheet" become "tube"?
    adv(f"ribbon_width_{w}mm", V, [("sheet", (np.abs(z - c) <= 0.6) & (np.abs(x - c) <= 9) & (np.abs(y - c) <= w / 2))], {"components": 1})
save("3b_adversarial_extra", ADV)
