"""check_morph3d.py - validation of scripts/css_morph3d.py on synthetic masks with known geometry (tests/morph_phantoms.py).
Writes reports/morph3d_phantoms.csv and reports/img/morph3d_phantoms.png when --report is given. Exit 1 on a failed check.
usage: python tests/check_morph3d.py [--report]"""
import sys, os, json, csv
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts")); sys.path.insert(0, HERE)
import numpy as np
from scipy import ndimage as ndi
import css_morph3d as cm, morph_phantoms as mp

fails = []; rows = []
def check(ok, msg):
    print(("ok    " if ok else "FAIL  ") + msg)
    if not ok: fails.append(msg)

def dark_image(mask, vox, contrast=60.0):
    """synthetic SWI-like crop: background 100, the structure darker, smoothed by the voxel PSF"""
    return ndi.gaussian_filter(100.0 - contrast * mask.astype(np.float32), 0.6)

res = {}
for nm in mp.NAMES:
    m, t = mp.make(nm); before = m.copy()
    r, a = cm.analyse(m, t["vox"], img=dark_image(m, t["vox"]))
    check(np.array_equal(m, before), f"{nm}: the input mask is not modified")
    res[nm] = (r, a, t)
    s = r["local_share"]; h = r["hessian"]["share"]
    rows.append(dict(shape=nm, vox="x".join(f"{v:g}" for v in t["vox"]), n_vox=r["n_vox"], components=len(r["components"]),
                     volume_mm3=r["volume_mm3"], surface_mm2=r["surface_mm2"], sphericity=r["sphericity"],
                     thick_median_mm=r["thickness_mm"]["median"], pca_ratio=f"1:{r['pca_ratio'][1]}:{r['pca_ratio'][2]}",
                     geo_tube=s["tube"], geo_sheet=s["sheet"], geo_blob=s["blob"], geo_uncertain=s["uncertain"],
                     hess_tube=h["tube"], hess_sheet=h["sheet"], hess_blob=h["blob"], skeleton=r["skeleton"]["ok"],
                     skel_len_mm=r["skeleton"]["length_mm"], xs_cv=r["xsection_cv"], reliability=r["reliability"],
                     smooth_vol_change_pct=r["smoothing_volume_change_pct"], summary=r["summary"]))

g = lambda nm: res[nm][0]
# 1-3 tubes
for nm in ("cylinder", "curved_cylinder"):
    check(g(nm)["local_share"]["tube"] >= 0.8, f"{nm}: tube-like share {g(nm)['local_share']['tube']} >= 0.8")
    check(g(nm)["skeleton"]["ok"], f"{nm}: skeleton shown (curve-like object)")
    check(abs(g(nm)["thickness_mm"]["median"] - 2.0) <= 0.8, f"{nm}: thickness {g(nm)['thickness_mm']['median']} mm ~ diameter 2.0 mm (+-1 voxel)")
check(abs(g("cylinder")["skeleton"]["length_mm"] - 18) <= 4, f"cylinder: skeleton length {g('cylinder')['skeleton']['length_mm']} mm ~ 18 mm")
check(g("cylinder")["xsection_cv"] is not None and g("cylinder")["xsection_cv"] <= 0.35, f"cylinder: cross-section diameter CV {g('cylinder')['xsection_cv']} <= 0.35 (stable radius)")
check(g("curved_cylinder")["skeleton"]["length_mm"] > g("curved_cylinder")["extent_mm"][0] * 0.9, "curved cylinder: skeleton length follows the curve (>= 0.9 x first principal extent)")
check(g("branching_tube")["local_share"]["tube"] >= 0.6, f"branching tube: tube-like share {g('branching_tube')['local_share']['tube']} >= 0.6")
# 4-6 sheets
for nm in ("sheet", "curved_sheet", "irregular_patch"):
    check(g(nm)["local_share"]["sheet"] >= 0.8, f"{nm}: sheet-like share {g(nm)['local_share']['sheet']} >= 0.8")
    check(g(nm)["local_share"]["tube"] <= 0.1, f"{nm}: edges not called tube ({g(nm)['local_share']['tube']} <= 0.1)")
    check(not g(nm)["skeleton"]["ok"], f"{nm}: no curve skeleton forced on a sheet")
check(g("sheet")["thickness_mm"]["median"] <= 2.4 + 1e-6, f"sheet: thickness {g('sheet')['thickness_mm']['median']} mm <= 2 voxels (1.2 mm sheet straddling two slices)")
check(g("curved_sheet")["thickness_mm"]["median"] <= 1.2 * 1.5, f"curved sheet: thickness {g('curved_sheet')['thickness_mm']['median']} mm ~ 1 slice")
# 7 blob
check(g("blob")["local_share"]["blob"] >= 0.8 and g("blob")["local_share"]["tube"] <= 0.05, f"blob: blob-like {g('blob')['local_share']['blob']}, not tube")
check(g("blob")["sphericity"] >= 0.6, f"blob: sphericity {g('blob')['sphericity']} >= 0.6 (sheet {g('sheet')['sphericity']}, tube {g('cylinder')['sphericity']})")
check(g("blob")["sphericity"] > g("sheet")["sphericity"] and g("blob")["sphericity"] > g("cylinder")["sphericity"], "sphericity orders blob > sheet, tube")
# 8 mixed: the tube part is found where it is
r, a, t = res["sheet_plus_tube"]; P = a["P_idx"] * np.array(t["vox"]); far = P[:, 0] > 15; near = P[:, 0] < 9
check((a["gcls"][far] == 0).mean() >= 0.8, f"sheet + tube: voxels of the tube part (x > 15 mm) called tube-like ({(a['gcls'][far] == 0).mean():.2f})")
check((a["gcls"][near] == 1).mean() >= 0.8, f"sheet + tube: voxels of the sheet part (x < 9 mm) called sheet-like ({(a['gcls'][near] == 1).mean():.2f})")
check("tube" in r["summary"] or r["local_share"]["tube"] > 0, "sheet + tube: the tube part is reported")
# 9 two pieces
r, a, t = res["two_pieces"]
check(len(r["components"]) == 2, f"two pieces: {len(r['components'])} components")
lab, _ = ndi.label(mp.make("two_pieces")[0], cm.S26); comp = lab[tuple(a["P_idx"].T)]
big = [c["id"] for c in r["components"]]
per = {k: np.bincount(a["gcls"][comp == k], minlength=4) for k in big}
check(any(v[0] / v.sum() >= 0.8 for v in per.values()) and any(v[1] / v.sum() >= 0.8 for v in per.values()), f"two pieces: one piece tube-like, the other sheet-like ({ {k: v.tolist() for k, v in per.items()} })")
# 10 fragmented sheet: small pieces kept, judged as sheet
check(len(g("fragmented_sheet")["components"]) >= 3, f"fragmented sheet: {len(g('fragmented_sheet')['components'])} pieces kept (none discarded)")
check(g("fragmented_sheet")["local_share"]["sheet"] >= 0.6, f"fragmented sheet: sheet-like share {g('fragmented_sheet')['local_share']['sheet']}")
# 11 thin anisotropic
r = g("thin_aniso")
check(r["reliability"] != "good" and any("anisotropic" in n for n in r["reliability_notes"]), f"thin anisotropic sheet: reliability '{r['reliability']}' with the anisotropy note")
check(r["local_share"]["sheet"] >= 0.8, f"thin anisotropic sheet: still sheet-like ({r['local_share']['sheet']})")
# Hessian (image) is separate and sensible on the clean shapes
check(g("cylinder")["hessian"]["share"]["tube"] >= 0.5, f"Hessian: cylinder tube-like share {g('cylinder')['hessian']['share']['tube']} >= 0.5")
check(g("curved_sheet")["hessian"]["share"]["sheet"] >= 0.5, f"Hessian: curved sheet sheet-like share {g('curved_sheet')['hessian']['share']['sheet']} >= 0.5")
# geometry: smoothing must not change the volume much; volumes physical
for nm in mp.NAMES:
    ch = g(nm)["smoothing_volume_change_pct"]
    check(ch is not None and abs(ch) <= 12, f"{nm}: display smoothing changes the mesh volume by {ch} % (<= 12 %)")
# anisotropy / orientation: same cylinder along x and along z, and at three voxel sizes
for vox in ((0.5, 0.5, 2.0), (0.8, 0.8, 1.2), (1.0, 1.0, 1.0)):
    g_, n_ = mp._grid(mp.BOX); x, y, z = g_; c = 12.0
    for axis, pts in (("x", [(3, c, c), (21, c, c)]), ("z", [(c, c, 3), (c, c, 21)])):
        m = mp._down(mp._tube(g_, pts, 1.2), n_, vox); r, _ = cm.analyse(m, vox)
        true_v = np.pi * 1.2 ** 2 * 18 + 4 / 3 * np.pi * 1.2 ** 3
        check(r["local_share"]["tube"] >= 0.7, f"cylinder r 1.2 along {axis}, voxels {vox}: tube-like {r['local_share']['tube']}")
        tol = 0.45 if max(vox) <= 1.2 else 1.3          # thick slices: a 2.4 mm tube spans 2 slices -> volume up to ~2x (documented)
        check(abs(r["volume_mm3"] - true_v) / true_v <= tol, f"   volume {r['volume_mm3']} mm3 vs true {true_v:.0f} (partial volume, <= {round(100 * tol)} %)")
        check(abs(r["extent_mm"][0] - 20.4) <= 1.5 + 2 * max(vox), f"   length (first principal extent) {r['extent_mm'][0]} mm vs true 20.4 mm (+- 1.5 mm + 2 voxels)")
        rows.append(dict(shape=f"cylinder_r1.2_along_{axis}", vox="x".join(f"{v:g}" for v in vox), n_vox=r["n_vox"], volume_mm3=r["volume_mm3"],
                         thick_median_mm=r["thickness_mm"]["median"], geo_tube=r["local_share"]["tube"], geo_sheet=r["local_share"]["sheet"], reliability=r["reliability"],
                         summary=f"true volume {true_v:.0f} mm3, true length 20.4 mm, measured length {r['extent_mm'][0]} mm"))

if "--report" in sys.argv:
    os.makedirs(f"{ROOT}/reports/img", exist_ok=True)
    with open(f"{ROOT}/reports/morph3d_phantoms.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), restval=""); w.writeheader(); w.writerows(rows)
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    col = np.array(["#f0a040", "#4aa3ff", "#c77dff", "#8a8f98"])
    fig = plt.figure(figsize=(16, 9), facecolor="#111418")
    for k, nm in enumerate(mp.NAMES):
        r, a, t = res[nm]; P = a["P_idx"] * np.array(t["vox"]); ax = fig.add_subplot(3, 4, k + 1, projection="3d"); ax.set_facecolor("#111418")
        # local class of the geometry: sheet orange, tube blue, blob purple, uncertain grey
        ax.scatter(P[:, 0], P[:, 1], P[:, 2], c=col[np.array([1, 0, 2, 3])[a["gcls"]]], s=6, depthshade=False)
        s = r["local_share"]; ax.set_title(f"{nm}\ntube {s['tube']:.2f} sheet {s['sheet']:.2f} blob {s['blob']:.2f}", color="w", fontsize=8)
        ax.set_box_aspect(np.ptp(P, 0) + 1); ax.set_axis_off(); ax.view_init(25, -60)
    fig.text(0.5, 0.02, "local geometry per voxel: blue = tube-like, orange = sheet-like, purple = blob-like, grey = uncertain", color="w", ha="center")
    fig.savefig(f"{ROOT}/reports/img/morph3d_phantoms.png", dpi=110, facecolor="#111418"); print("report written")

print(f"RESULT morph3d {'OK' if not fails else 'FAILED: ' + str(len(fails))}")
sys.exit(1 if fails else 0)
