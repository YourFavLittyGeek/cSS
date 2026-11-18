"""Figures for the structural upgrade report (phantom data only). Usage: python make_figures.py REPO_EXPERIMENTAL_DIR PHANTOM_BASE OUT"""
import sys, json, numpy as np, pandas as pd, nibabel as nib, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt
EXP, PB, OUT = sys.argv[1:4]; sys.path.insert(0, EXP); R = "/home/user/cSS_structural_upgrade"
from structural_detection import phantoms as P, hessian_fingerprint as A, candidate_decomposition as F, multiview_seeding as D
C1, C2, C3, C4, INK, INK2 = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#0b0b0b", "#52514e"
plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": INK2, "axes.labelcolor": INK,
                     "xtick.color": INK2, "ytick.color": INK2, "axes.grid": True, "grid.color": "#e6e5e1", "grid.linewidth": 0.6, "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb"})
V = (0.5, 0.5, 0.5)
# Fig 1: class fractions per synthetic shape
shapes = dict(plate=P.plate(), curved_sheet=P.curved_sheet(), tram_track=P.tram_track(), fragmented=P.fragmented_sheet()[:2],
              tube=P.tube(), oblique_tube=P.tube(direction=(1, 1, 1)), blob=P.blob())
cls_names = ["plate", "tube", "blob", "saddle", "mixed"]; cols = [C1, C2, C4, C3, "#c3c2b7"]
fr = {}; tr = {}
for k, (im, m) in shapes.items():
    mp = A.voxel_maps(im, V, m); f = A.object_features(mp, np.ones(int(m.sum()), bool), V)
    fr[k] = [f[f"hf_{c}_frac"] for c in cls_names]; tr[k] = (f["tube_ratio_prod_med"], f["tube_ratio_signed_med"])
fig, ax = plt.subplots(figsize=(7.5, 3.2)); left = np.zeros(len(fr))
for i, c in enumerate(cls_names):
    v = np.array([fr[k][i] for k in fr]); ax.barh(list(fr), v, left=left, color=cols[i], edgecolor="#fcfcfb", linewidth=2, label=c); left += v
ax.invert_yaxis(); ax.set_xlabel("share of object voxels (best scale)"); ax.set_xlim(0, 1); ax.grid(axis="y", visible=False)
ax.legend(ncol=5, frameon=False, loc="lower center", bbox_to_anchor=(0.5, 1.0)); ax.set_title("Module A voxel classes on synthetic shapes (phantom only)", loc="left", pad=22)
fig.tight_layout(); fig.savefig(f"{OUT}/fig1_hessian_classes_synthetic.png", dpi=200); plt.close(fig)
# Fig 2: production |l2|/l3 vs signed on PH3/PH6 objects, coloured by phantom truth
rows = []
for s in ("PH3", "PH6"):
    d = pd.read_csv(f"{R}/test_results/structural_{s}/features.csv")
    tru = np.asarray(nib.load(f"{PB}/work/{s}_truth.nii.gz").dataobj) > 0
    for src, fn in (("candidate", f"{PB}/review/{s}_candidates.nii.gz"), ("excluded", f"{PB}/review/{s}_excluded.nii.gz")):
        L = np.asarray(nib.load(fn).dataobj).astype(int)
        for r in d[d.source == src].itertuples():
            m = L == r.obj_id; rows.append(dict(study=s, source=src, obj_id=r.obj_id, is_lesion=bool((m & tru).sum() / max(m.sum(), 1) > 0.3),
                                                prod=r.tube_ratio_prod_med, signed=r.tube_ratio_signed_med, saddle=r.hf_saddle_frac, cat=r.fusion_category))
df = pd.DataFrame(rows); df.to_csv(f"{R}/test_results/phantom_objects_truth.csv", index=False)
fig, ax = plt.subplots(figsize=(4.8, 4.2))
for les, c, lab in ((True, C1, "phantom cSS lesion"), (False, C2, "phantom vessel / other")):
    s = df[df.is_lesion == les]; ax.scatter(s["prod"], s["signed"], s=46, color=c, edgecolor="#fcfcfb", linewidth=1.5, label=f"{lab} (n={len(s)})", zorder=3)
ax.plot([0, 1], [0, 1], color=INK2, lw=0.8, ls="--"); ax.set_xlim(0, 0.7); ax.set_ylim(-0.02, 0.7)
ax.set_xlabel("production tube_ratio  |λ2| / λ3  (median)"); ax.set_ylabel("signed variant  max(λ2,0) / λ3  (median)")
ax.legend(frameon=False, loc="upper left"); ax.set_title("Saddle voxels inflate the production value", loc="left")
fig.tight_layout(); fig.savefig(f"{OUT}/fig2_tube_ratio_prod_vs_signed_PH3_PH6.png", dpi=200); plt.close(fig)
# Fig 3: volume gate sweep
for nm, fn in (("offmidline", "volume_gate"), ("anysite", "volume_gate_anysite")):
    d = pd.read_csv(f"{R}/stage0/{fn}/volume_gate_sweep.csv"); d["f"] = d.fate.str.replace(" (generation gate)", "")
    fig, ax = plt.subplots(figsize=(6.5, 3.0)); cmap = {"shown": C1, "dropped": C2, "excluded": C4, "not generated": INK2}
    yy = {k: i for i, k in enumerate(cmap)}
    for k, c in cmap.items():
        s = d[d.f == k]; ax.scatter(s.true_vol_mm3, [yy[k]] * len(s) + np.random.default_rng(1).uniform(-0.15, 0.15, len(s)), s=40, color=c, edgecolor="#fcfcfb", linewidth=1.2, zorder=3)
    ax.axvline(25, color=INK2, lw=0.8, ls="--"); ax.text(26.5, 2.55, "25 mm³ gate\n(on the MEASURED component)", color=INK2, fontsize=8)
    ax.set_xscale("log"); ax.set_yticks(range(4)); ax.set_yticklabels(list(cmap)); ax.set_xlabel("inserted (true) lesion volume, mm³"); ax.grid(axis="y", visible=False)
    ax.set_title(f"Fate of 36 inserted subpial lesions in PH3 copies ({'sites >= 12 mm off midline' if nm == 'offmidline' else 'sites anywhere'})", loc="left", fontsize=9)
    fig.tight_layout(); fig.savefig(f"{OUT}/fig3_volume_gate_{nm}.png", dpi=200); plt.close(fig)
# Fig 4: decomposition of a merged plate + tube
im, pl, tb = P.sheet_plus_tube(); m = pl | tb; mp = A.voxel_maps(im, V, m); cls = np.full(m.shape, -1, np.int8); cls[mp["idx"]] = mp["cls"]
comp, crow = F.decompose(m, cls, V); k = m.shape[2] // 2
fig, axs = plt.subplots(1, 2, figsize=(6.5, 3.2))
axs[0].imshow(im[:, :, k].T, cmap="gray", origin="lower"); axs[0].set_title("synthetic merged object (axial)", fontsize=9)
cm = np.ma.masked_where(comp[:, :, k] == 0, comp[:, :, k]); axs[1].imshow(im[:, :, k].T, cmap="gray", origin="lower", alpha=0.5)
from matplotlib.colors import ListedColormap
axs[1].imshow(cm.T, cmap=ListedColormap([C1, C2, C3, C4][:max(1, comp.max())]), origin="lower", interpolation="nearest")
axs[1].set_title(" / ".join(f"{r['comp_kind']} {r['comp_vol_mm3']:.0f} mm³" for r in crow), fontsize=9)
for a in axs: a.axis("off")
fig.tight_layout(); fig.savefig(f"{OUT}/fig4_candidate_splitting.png", dpi=200); plt.close(fig)
# Fig 5: surface-width resolution (15b)
t = [r for r in json.load(open(f"{R}/test_results/phantom_tests.json")) if r["category"] == "15b_surface_width_resolution"]
fig, ax = plt.subplots(figsize=(4.6, 3.0)); x = [1, 2, 4, 8]; ax.plot(x, [r["sc_tan_width_mm"] for r in t], color=C1, lw=2, marker="o", ms=8, label="tangential width")
ax.plot(x, [r["sc_width_mm"] for r in t], color=C2, lw=2, marker="o", ms=8, label="footprint / length"); ax.plot(x, [1.2 * n for n in x], color=INK2, lw=0.8, ls="--", label="true band height")
ax.set_xticks(x); ax.set_xlabel("band height in 1.2 mm slices"); ax.set_ylabel("mm"); ax.legend(frameon=False); ax.set_title("Surface width tracks slice coverage", loc="left")
fig.tight_layout(); fig.savefig(f"{OUT}/fig5_surface_width_resolution.png", dpi=200); plt.close(fig)
# Fig 6: multiview on an in-plane sheet
from scipy import ndimage as ndi
im, m = P.plate(shape=(48, 48, 32), normal_axis=2, size_mm=(12, 12), noise=0.02, seed=4); mask = ndi.binary_dilation(m, iterations=8)
Vt, per, vv = D.votes(im, mask, V); kz = int(np.argwhere(m)[:, 2].mean()); jy = 24
fig, axs = plt.subplots(1, 3, figsize=(7.5, 2.8))
axs[0].imshow(im[:, :, kz].T, cmap="gray", origin="lower"); axs[0].set_title("axial: filled area", fontsize=9)
axs[1].imshow(per[2][:, :, kz].T, cmap="Blues", origin="lower"); axs[1].set_title("axial ridge seeds", fontsize=9)
axs[2].imshow(per[1][:, jy, :].T, cmap="Blues", origin="lower", aspect="auto"); axs[2].set_title("coronal ridge seeds (line)", fontsize=9)
for a in axs: a.axis("off")
fig.tight_layout(); fig.savefig(f"{OUT}/fig6_multiview_inplane_sheet.png", dpi=200); plt.close(fig)
print(df.to_string(index=False))
