#!/usr/bin/env python3
"""Render case images for the visual review (READ-ONLY; run on the Mac where the patient images are).
usage: python3 render_cases.py CASES_CSV OUT_DIR        (CSS_BASE = the project, default ~/css_project)
CASES_CSV columns: study_id, object_id, case [, volume_mm3, vox_i, vox_j, vox_k]  (object_id = cand_id of the CURRENT review/ID_candidates list; fingerprint columns
vox_i/vox_j/vox_k/volume_mm3 are checked when present, so a re-detected list is reported instead of drawn on the wrong object).
For each case: SWI axial / coronal / sagittal 40 mm crops through the object's centre, object outline (red), other candidates (yellow),
labelled cortex boundary (cyan, = the voxel 'pial' surface the detector uses), plus an 8 mm axial minIP. Writes OUT_DIR/<study>_<id>.png."""
import sys, os, numpy as np, pandas as pd, nibabel as nib
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from scipy import ndimage as ndi
B = os.environ.get("CSS_BASE", os.path.expanduser("~/css_project")); LD = os.environ.get("LIST_DIR", f"{B}/review")   # LIST_DIR: folder holding the ID_candidates.* the ids refer to (e.g. review/backup_<date>)
cases = pd.read_csv(sys.argv[1]); OUT = sys.argv[2]; os.makedirs(OUT, exist_ok=True)
for (sid), g in cases.groupby("study_id"):
    try:
        im = nib.load(f"{B}/data/{sid}_swi.nii"); I = im.get_fdata().astype(np.float32); vox = np.array(im.header.get_zooms()[:3], float)
        L = np.asanyarray(nib.load(f"{LD}/{sid}_candidates.nii.gz").dataobj).astype(int); c = pd.read_csv(f"{LD}/{sid}_candidates.csv")
        seg = np.asanyarray(nib.load(f"{B}/work/{sid}_seg_swispace.nii.gz").dataobj).astype(int)
    except Exception as e: print(f"{sid}: cannot load ({e})"); continue
    tissue = (seg > 0) & ~np.isin(seg, [4, 5, 14, 15, 24, 43, 44]); edge = tissue & ~ndi.binary_erosion(tissue)
    lo, hi = np.percentile(I[I > 0], [1, 99])
    for _, r in g.iterrows():
        oid = int(r.object_id); row = c[c.cand_id == oid]
        if not len(row): print(f"{sid} #{oid}: not in the current list"); continue
        row = row.iloc[0]
        if "vox_i" in r and pd.notna(r.get("vox_i")) and (abs(row.vox_i - r.vox_i) > 2 or abs(row.vox_j - r.vox_j) > 2 or abs(row.vox_k - r.vox_k) > 2):
            print(f"{sid} #{oid}: fingerprint differs (list re-detected) - skipped"); continue
        if pd.notna(r.get("volume_mm3", np.nan)) and abs(row.volume_mm3 - r.volume_mm3) > 0.15 * max(r.volume_mm3, 1):
            print(f"{sid} #{oid}: volume {row.volume_mm3:.0f} vs expected {r.volume_mm3:.0f} mm3 - wrong list, skipped (set LIST_DIR)"); continue
        m = L == oid
        if not m.any(): print(f"{sid} #{oid}: empty mask"); continue
        cen = np.round(np.argwhere(m).mean(0)).astype(int); h = np.ceil(20 / vox).astype(int)
        fig, axs = plt.subplots(1, 4, figsize=(16, 4.4))
        def crop(a, ax_):
            sl = [slice(max(cen[i] - h[i], 0), cen[i] + h[i]) for i in range(3)]; sl[ax_] = cen[ax_]; return a[tuple(sl)]
        for k, (ax_, nm) in enumerate(((2, "axial"), (1, "coronal"), (0, "sagittal"))):
            a = axs[k]; asp = {2: vox[1] / vox[0], 1: vox[2] / vox[0], 0: vox[2] / vox[1]}[ax_]
            a.imshow(crop(I, ax_).T, cmap="gray", vmin=lo, vmax=hi, origin="lower", aspect=asp)
            a.contour(crop(m, ax_).T.astype(float), [0.5], colors="r", linewidths=1, origin="lower")
            a.contour(crop((L > 0) & ~m, ax_).T.astype(float), [0.5], colors="y", linewidths=.6, origin="lower")
            a.contour(crop(edge, ax_).T.astype(float), [0.5], colors="c", linewidths=.4, origin="lower"); a.set_title(nm); a.axis("off")
        k0 = max(cen[2] - int(round(4 / vox[2])), 0); k1 = cen[2] + int(round(4 / vox[2])) + 1
        sl = (slice(max(cen[0] - h[0], 0), cen[0] + h[0]), slice(max(cen[1] - h[1], 0), cen[1] + h[1]))
        axs[3].imshow(I[sl[0], sl[1], k0:k1].min(2).T, cmap="gray", vmin=lo, vmax=hi, origin="lower"); axs[3].contour(m[sl[0], sl[1], k0:k1].any(2).T.astype(float), [0.5], colors="r", linewidths=1, origin="lower")
        axs[3].set_title("axial minIP 8 mm"); axs[3].axis("off")
        fig.suptitle(f"{sid} #{oid} {row.region} {row.volume_mm3:.0f} mm3 | tube_ratio {row.get('tube_ratio', np.nan)} | {r.get('case', '')}", fontsize=9)
        fig.tight_layout(); fig.savefig(f"{OUT}/{sid}_{oid}.png", dpi=110); plt.close(fig); print(f"{sid} #{oid}: written")
