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

# ======================================================================= 1. thickness
rows = []
g, n = grid(); x, y, z = g; c = 12.0
for vox in ((0.8, 0.8, 1.2), (0.4, 0.4, 0.4), (1.0, 1.0, 1.0), (0.4, 0.4, 3.0)):
    for T in (0.6, 1.2, 2.0, 2.4, 3.6):
        for place, z0 in (("slice-centred", None), ("straddling", "edge")):
            # put the sheet's centre on a slice centre or on a slice boundary
            k = round(c / vox[2]); zc = (k + 0.5) * vox[2] if z0 is None else k * vox[2]
            m = down((np.abs(z - zc) <= T / 2) & (np.abs(x - c) <= 8) & (np.abs(y - c) <= 6), n, vox)
            if not m.any(): rows.append(dict(test="flat", vox=vox, true_mm=T, place=place, n_vox=0, measured_mm="empty")); continue
            eff = m.sum() * np.prod(vox) / (16 * 12)          # digitised thickness = mask volume / sheet area
            rows.append(dict(test="flat", vox="x".join(map(str, vox)), true_mm=T, place=place, n_vox=int(m.sum()), digitised_mm=round(eff, 2),
                             measured_mm=round(med_thick(m, vox), 2), bias_vs_true=round(med_thick(m, vox) - T, 2), bias_vs_digitised=round(med_thick(m, vox) - eff, 2)))
# tilted sheet: is thickness measured along the normal?
for vox in ((0.4, 0.4, 0.4), (0.8, 0.8, 1.2)):
    for ang in (0, 20, 30, 45, 60, 75):
        a = math.radians(ang); nrm = np.array([math.sin(a), 0, math.cos(a)])
        dist = (x - c) * nrm[0] + (z - c) * nrm[2]; along = (x - c) * math.cos(a) - (z - c) * math.sin(a)
        for T in (1.2, 2.0):
            m = down((np.abs(dist) <= T / 2) & (np.abs(along) <= 8) & (np.abs(y - c) <= 6), n, vox)
            eff = m.sum() * np.prod(vox) / (16 * 12); mt = med_thick(m, vox)
            rows.append(dict(test="tilted", vox="x".join(map(str, vox)), angle_deg=ang, true_mm=T, n_vox=int(m.sum()), digitised_mm=round(eff, 2),
                             measured_mm=round(mt, 2), bias_vs_true=round(mt - T, 2), bias_vs_digitised=round(mt - eff, 2)))
# curved sheet: radius of curvature
for R in (2.5, 4, 6, 12):
    for vox in ((0.4, 0.4, 0.4), (0.8, 0.8, 1.2)):
        r = np.hypot(x - c, z - (c - R + 2)); T = 1.2
        m = down((np.abs(r - R) <= T / 2) & (z >= c - R + 2) & (np.abs(y - c) <= 6), n, vox)
        area = math.pi * R * 12
        rows.append(dict(test="curved", vox="x".join(map(str, vox)), curvature_radius_mm=R, true_mm=T, n_vox=int(m.sum()),
                         digitised_mm=round(m.sum() * np.prod(vox) / area, 2), measured_mm=round(med_thick(m, vox), 2), bias_vs_true=round(med_thick(m, vox) - T, 2)))
# the direction "one voxel" term: the formula vs the box chord along the same direction
for u in ((1, 0, 0), (1, 1, 0), (1, 1, 1), (0, 0, 1)):
    for vox in ((1, 1, 1), (0.8, 0.8, 1.2), (0.5, 0.5, 3.0)):
        u_ = np.array(u, float) / np.linalg.norm(u); v = np.array(vox, float)
        used = 1 / math.sqrt(((u_ / v) ** 2).sum()); chord = min(v[i] / abs(u_[i]) for i in range(3) if u_[i])
        rows.append(dict(test="step_term", vox="x".join(map(str, vox)), direction=str(u), used_mm=round(used, 3), box_chord_mm=round(chord, 3)))
save("1_thickness", rows)

# generator check: _down averages round(vox / 0.2) fine samples, so a 0.5 mm voxel really spans 0.4 mm
rows2 = []
for v in (0.4, 0.5, 0.6, 0.8, 1.0, 1.2, 2.0, 3.0):
    f = max(1, int(round(v / FINE))); rows2.append(dict(labelled_vox_mm=v, fine_samples=f, real_vox_mm=round(f * FINE, 2), scale_error_pct=round(100 * (v / (f * FINE) - 1), 1)))
save("0_generator_scale", rows2)

# ======================================================================= 3. adversarial phantoms (independent ground truth per structure)
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
# 1 thin curved sheet with variable thickness (0.6 -> 1.8 mm)
T = 0.6 + 1.2 * (x - 4) / 16; surf = c - 3 + 0.05 * (x - c) ** 2
adv("01_variable_thickness_curved_sheet", V, [("sheet", (np.abs(z - surf) <= T / 2) & (x >= 4) & (x <= 20) & (np.abs(y - c) <= 6))], {"components": 1})
# 2 sheet with several interruptions (1 mm gaps every 4 mm)
base = (np.abs(z - c) <= 0.6) & (np.abs(x - c) <= 9) & (np.abs(y - c) <= 7)
adv("02_interrupted_sheet", V, [("sheet", base & ~(np.abs(((x - c) % 4) - 2) < 0.5))], {})
# 3 vein running parallel to the cortical surface (tube only; surface plane z = c - 1.5)
adv("03_vein_parallel_to_surface", V, [("tube", tube_pts(g, [(3, c, c), (21, c + 2, c)], 0.8))], {"components": 1})
# 4 vein compressed against a sulcal wall: elliptical cross-section 3.0 x 1.0 mm
ell = (((y - c) / 1.5) ** 2 + ((z - c) / 0.5) ** 2 <= 1) & (x >= 3) & (x <= 21)
adv("04_compressed_vein_elliptic", V, [("tube", ell)], {"components": 1}, "flattened vessel: a ribbon geometrically")
# 5 vein partially merged with a sheet
sheet5 = (np.abs(z - c) <= 0.6) & (x >= 2) & (x <= 14) & (np.abs(y - c) <= 6)
adv("05_vein_merged_with_sheet", V, [("sheet", sheet5), ("tube", tube_pts(g, [(8, c - 3, c + 0.6), (22, c - 3, c + 3)], 0.8))], {"components": 1})
# 6 two adjacent veins that look connected (2.2 mm apart, touching after partial volume)
adv("06_two_adjacent_veins", V, [("tube_a", tube_pts(g, [(3, c - 1.1, c), (21, c - 1.1, c)], 0.8)), ("tube_b", tube_pts(g, [(3, c + 1.1, c), (21, c + 1.1, c)], 0.8))], {}, "may merge into one ribbon")
# 7 sheet with an attached branching vessel
sheet7 = (np.abs(z - c) <= 0.6) & (x >= 2) & (x <= 12) & (np.abs(y - c) <= 6)
br = tube_pts(g, [(12, c, c), (18, c, c + 2), (22, c - 4, c + 3)], 0.8) | tube_pts(g, [(18, c, c + 2), (22, c + 5, c + 4)], 0.8)
adv("07_sheet_with_branching_vessel", V, [("sheet", sheet7), ("tube", br)], {"components": 1})
# 8 sharply curved sheet (U fold, inner radius 1.5 mm - a sulcal fundus)
r8 = np.hypot(x - c, z - c); fold = (np.abs(r8 - 2.1) <= 0.6) & (z <= c) | ((np.abs(np.abs(x - c) - 2.1) <= 0.6) & (z > c) & (z <= c + 8))
adv("08_sharp_U_fold_sheet", V, [("sheet", fold & (np.abs(y - c) <= 6))], {"components": 1})
# 9 oblique sheet crossing thick slices (30 deg, 0.5 x 0.5 x 3 mm)
a9 = math.radians(30); d9 = (x - c) * math.sin(a9) + (z - c) * math.cos(a9)
adv("09_oblique_sheet_thick_slices", (0.4, 0.4, 3.0), [("sheet", (np.abs(d9) <= 0.8) & (np.abs((x - c) * math.cos(a9) - (z - c) * math.sin(a9)) <= 8) & (np.abs(y - c) <= 6))], {})
# 10 very thin tube next to a broad sheet (0.6 mm gap, and touching)
sheet10 = (np.abs(z - c) <= 0.6) & (np.abs(x - c) <= 9) & (y >= c - 8) & (y <= c + 2)
adv("10a_thin_tube_beside_sheet_gap", V, [("sheet", sheet10), ("tube", tube_pts(g, [(3, c + 3.6, c), (21, c + 3.6, c)], 0.5))], {}, "gap 0.6 mm")
adv("10b_thin_tube_touching_sheet", V, [("sheet", sheet10), ("tube", tube_pts(g, [(3, c + 2.6, c), (21, c + 2.6, c)], 0.5))], {"components": 1}, "touching")
save("3_adversarial", ADV)

# ======================================================================= 5. surface / mesh distortion
rows = []
shapes = {"cylinder_r1.2_x": lambda g: mp._tube(g, [(3, 12, 12), (21, 12, 12)], 1.2), "cylinder_r1.2_z": lambda g: mp._tube(g, [(12, 12, 3), (12, 12, 21)], 1.2),
          "sheet_1.2": lambda g: (np.abs(g[2] - 12.3) <= 0.6) & (np.abs(g[0] - 12) <= 8) & (np.abs(g[1] - 12) <= 6),
          "ball_r3.5": lambda g: ((g - 12) ** 2).sum(0) <= 3.5 ** 2}
true_v = {"cylinder_r1.2_x": math.pi * 1.44 * 18 + 4 / 3 * math.pi * 1.2 ** 3, "cylinder_r1.2_z": math.pi * 1.44 * 18 + 4 / 3 * math.pi * 1.2 ** 3, "sheet_1.2": 1.2 * 16 * 12, "ball_r3.5": 4 / 3 * math.pi * 3.5 ** 3}
true_a = {"cylinder_r1.2_x": 2 * math.pi * 1.2 * 18 + 4 * math.pi * 1.44, "cylinder_r1.2_z": 2 * math.pi * 1.2 * 18 + 4 * math.pi * 1.44, "sheet_1.2": 2 * 16 * 12 + 2 * 1.2 * 28, "ball_r3.5": 4 * math.pi * 3.5 ** 2}
for nm, fn in shapes.items():
    g, n = grid()
    for vox in ((0.4, 0.4, 0.4), (0.8, 0.8, 1.2), (1, 1, 1), (0.4, 0.4, 2.0), (0.5, 0.5, 2.0)):
        m = down(fn(g), n, vox); vr, fr, ar = cm.mesh(m, vox); vs, fs, _ = cm.mesh(m, vox, smooth_iter=8)
        from skimage.measure import mesh_surface_area
        rows.append(dict(shape=nm, vox="x".join(map(str, vox)), true_vol=round(true_v[nm], 1), voxel_vol=round(m.sum() * np.prod(vox), 1),
                         mesh_vol_raw=round(cm.mesh_volume(vr, fr), 1), mesh_vol_smoothed=round(cm.mesh_volume(vs, fs), 1),
                         true_area=round(true_a[nm], 1), area_raw=round(ar, 1), area_smoothed=round(float(mesh_surface_area(vs, fs)), 1),
                         thickness_mask_mm=round(med_thick(m, vox), 2)))
save("5_surface", rows)

# ======================================================================= 4 + 6. PH6 through the reviewer
B = os.environ.get("CSS_BASE", "")
if B and os.path.exists(f"{B}/review/PH6_candidates.csv"):
    sys.argv = sys.argv[:1]; import review_web as rw
    rw.IDS[:] = ["PH6"]; s = rw.study("PH6")
    tr = s._grid(f"{B}/work/PH6_truth.nii.gz", 0).astype(int); ve = s._grid(f"{B}/work/PH6_veins.nii.gz", 0) > 0
    sv = s._grid(f"{B}/work/PH6_surfvein.nii.gz", 0) > 0 if os.path.exists(f"{B}/work/PH6_surfvein.nii.gz") else np.zeros_like(ve)
    psd_full = s._grid(f"{B}/work/PH6_pial_sd.nii.gz", 1)
    rows = []; ctx_rows = []
    for cid in range(1, len(s.df) + 1):
        o = s.morph3d(cid); m = o["measures"]; obj = s.lab == cid; nv = int(obj.sum())
        labs, cnt = np.unique(tr[obj], return_counts=True); best = int(labs[np.argmax(np.where(labs > 0, cnt, 0))]) if (labs > 0).any() else 0
        f_les = float((tr[obj] > 0).mean()); f_ves = float(ve[obj].mean()); f_sv = float(sv[obj].mean())
        cover = float((obj & (tr == best)).sum() / max((tr == best).sum(), 1)) if best else 0.0
        ident = f"cSS lesion {best}" if f_les >= 0.3 else ("vein (PH6_veins)" if f_ves >= 0.3 else ("surface vein (PH6_surfvein)" if f_sv >= 0.3 else "no truth structure (other)"))
        sh = m["local_share"]; sf = m.get("surface", {})
        rows.append(dict(cand=cid, identity=ident, frac_in_lesion=round(f_les, 2), frac_in_vein=round(f_ves, 2), frac_in_surfvein=round(f_sv, 2),
                         lesion_covered=round(cover, 2), n_vox=nv, volume_mm3=m["volume_mm3"], thick_median=m["thickness_mm"]["median"],
                         tube=sh["tube"], sheet=sh["sheet"], blob=sh["blob"], uncertain=sh["uncertain"], reliability=m["reliability"],
                         csf=sf.get("in_csf"), tissue=sf.get("in_tissue"), within_1mm=sf.get("within_1mm"), median_pial=sf.get("median_pial_mm"),
                         pieces=len(m["components"]), summary=m["summary"]))
        # 6. sensitivity of the CSF fraction to a label / registration shift (psd shifted by k voxels along each axis)
        if cid <= 6:
            for ax_ in range(3):
                for k in (-2, -1, 1, 2):
                    sh_psd = np.roll(psd_full, k, axis=ax_)[obj]
                    ctx_rows.append(dict(cand=cid, identity=ident, axis="xyz"[ax_], shift_vox=k, shift_mm=round(k * s.vox[ax_], 2),
                                         csf=round(float((sh_psd > 0.5).mean()), 2), within_1mm=round(float((np.abs(sh_psd) <= 1).mean()), 2), csf_unshifted=sf.get("in_csf")))
    save("4_ph6", rows); save("6_context_shift", ctx_rows)
else: print("PH6 not available - section 4/6 skipped")

# figure: adversarial cases coloured by local class, beside their ground truth
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
print("done")
