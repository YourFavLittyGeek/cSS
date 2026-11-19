"""Figures: original candidate / dark core / blooming-support shown separately, with ground truth, for development blooming
cases and PH6 candidates (CSS_BASE with PH6). Writes results/fig_decomposition_dev.png, results/fig_decomposition_ph6.png"""
import sys, os
H = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(H)
sys.path.insert(0, os.path.join(ROOT, "scripts")); sys.path.insert(0, H)
import numpy as np, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt
import css_morph3d_v2 as v2, bloom_phantoms as bp

def panel(ax, img, masks, k, axis, title):
    sl = lambda a: np.take(a, k, axis=axis).T
    ax.imshow(sl(img), cmap="gray", origin="lower", interpolation="nearest")
    for m, col in masks:
        if m is not None and sl(m).any(): ax.contour(sl(m).astype(float), [0.5], colors=col, linewidths=1.1)
    ax.set_title(title, fontsize=7, color="w"); ax.axis("off")

def case_fig(items, out):
    fig, axs = plt.subplots(len(items), 4, figsize=(12, 3 * len(items)), facecolor="#111")
    for i, (name, img, cand, core, sup, truth, txt) in enumerate(items):
        P = np.argwhere(cand); c = np.round(P.mean(0)).astype(int); ax_ = int(np.argmax(np.ptp(P, 0) * 0 + 1)) if False else 2
        k = c[2]
        panel(axs[i, 0], img, [(truth, "#3aff6a")], k, 2, f"{name}\nSWI + truth (green)")
        panel(axs[i, 1], img, [(cand, "#ffd23f")], k, 2, "A original candidate (yellow)")
        panel(axs[i, 2], img, [(core, "#ff4b4b")], k, 2, "B dark core (red)")
        panel(axs[i, 3], img, [(sup, "#4aa3ff")], k, 2, "C blooming / support (blue)")
        axs[i, 3].text(1.02, 0.5, txt, transform=axs[i, 3].transAxes, color="w", fontsize=7, va="center")
    fig.subplots_adjust(right=0.78); fig.savefig(out, dpi=110, facecolor="#111"); plt.close(fig)

items = []
for sd in (0, 4, 7, 13, 23):
    sp = bp.random_spec(sd); C = bp.make_case(sp); o = v2.analyse(C["candidate"], C["vox"], img=C["img"]); D = o["_D"]
    t = (f"{sp['kind']}, {C['vox']}\ntrue thickness {C['true_thick']:.2f} mm\ncandidate {o['candidate']['thickness_mm']['median']} mm,"
         f" core {o['core']['thickness_mm']['median']} mm\ncandidate label: {o['candidate']['label']}\ncore label: {o['core']['label']}\ncore unstable {o['decomposition']['core_unstable_frac']}")
    items.append((f"dev seed {sd}", C["img"], C["candidate"], D["core"], D["support"], C["labels"] > 0, t))
case_fig(items, f"{H}/results/fig_decomposition_dev.png")

B = os.environ.get("CSS_BASE", "")
if B and os.path.exists(f"{B}/review/PH6_candidates.csv"):
    sys.argv = sys.argv[:1]; import review_web as rw; from scipy import ndimage as ndi
    rw.IDS[:] = ["PH6"]; s = rw.study("PH6"); I = s.can.get_fdata(dtype=np.float32); tr = s._grid(f"{B}/work/PH6_truth.nii.gz", 0) > 0
    ve = (s._grid(f"{B}/work/PH6_veins.nii.gz", 0) > 0) | (s._grid(f"{B}/work/PH6_surfvein.nii.gz", 0) > 0)
    psd = s._grid(f"{B}/work/PH6_pial_sd.nii.gz", 1); items = []; rows = []
    for cid in (1, 2, 4, 6, 9, 10):
        full = s.lab == cid; P0 = np.argwhere(full); mg = np.ceil(8 / np.array(s.vox)).astype(int)
        lo = np.maximum(P0.min(0) - mg, 0); hi = np.minimum(P0.max(0) + mg + 1, s.shape); sl = tuple(slice(a, b) for a, b in zip(lo, hi))
        o = v2.analyse(full[sl], s.vox, img=I[sl], psd=psd[sl]); D = o["_D"]; truth = (tr | ve)[sl]
        t = (f"PH6 #{cid}\ncandidate {o['candidate']['thickness_mm']['median']} mm, {o['candidate']['volume_mm3']} mm3\n"
             f"core {o['core']['thickness_mm']['median']} mm, {o['core']['volume_mm3']} mm3\ncandidate: {o['candidate']['label']} ({o['candidate']['level']})\n"
             f"core: {o['core']['label']} ({o['core']['level']})\nCSF {o['context']['csf_frac']} range {o['context']['csf_range']}")
        items.append((f"PH6 #{cid}", I[sl], full[sl], D["core"], D["support"], truth, t))
        tm = truth & full[sl]; rows.append(dict(cand=cid, cand_vol=o["candidate"]["volume_mm3"], core_vol=o["core"]["volume_mm3"], truth_in_crop=int(truth.sum()),
            cand_dice=round(2 * (full[sl] & truth).sum() / (full[sl].sum() + truth.sum()), 2), core_dice=round(2 * (D["core"] & truth).sum() / (D["core"].sum() + truth.sum()), 2),
            cand_thick=o["candidate"]["thickness_mm"]["median"], core_thick=o["core"]["thickness_mm"]["median"], cand_label=o["candidate"]["label"], core_label=o["core"]["label"],
            cand_level=o["candidate"]["level"], csf=o["context"]["csf_frac"], csf_range=o["context"]["csf_range"], within1=o["context"]["within_1mm"], within1_range=o["context"]["within_1mm_range"]))
    case_fig(items, f"{H}/results/fig_decomposition_ph6.png")
    import csv
    with open(f"{H}/results/ph6_v513_development.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    for r in rows: print(r)
print("figures written")
