# 3-D morphology features (scripts/css_morph3d.py)

All measurements are on the **candidate mask itself** (not the regrown dark structure the old card used), in mm,
on the canonical grid with the true voxel size. None is a probability; the summary is descriptive, not a diagnosis.

## Two separate sources

1. **Mask geometry**: the shape of the segmented candidate (coordinates of its voxels).
2. **Image Hessian**: the local curvature of the SWI intensity around those voxels.

They are computed, stored and displayed separately. Coordinate-PCA eigenvalues (spread of voxel positions) are not
Hessian eigenvalues (curvature of the signal).

## Feature table

| Feature | Units | Definition | Reliability / limits |
|---|---|---|---|
| components | – | 26-connected pieces of the mask, with volume; none discarded | small pieces may be fragments of one lesion |
| volume_mm3 | mm³ | voxel count × voxel volume | partial volume: thin objects on thick slices are over-estimated (2 mm slices: up to ~2×) |
| surface_mm2 | mm² | area of the marching-cubes surface of the exact mask (unsmoothed) | the staircase inflates it slightly |
| sa_to_vol | 1/mm | surface / volume | high for thin sheets and tubes |
| sphericity | – | π^(1/3) (6V)^(2/3) / A | 1 = ball; phantoms: blob 0.97, cylinder 0.63, sheets 0.39–0.60 |
| pca_eigen_mm2, pca_sd_mm | mm², mm | eigenvalues of the covariance of voxel positions (descending) and their square roots | describes the overall distribution, **not** the local cross-section: a curved sheet has a large third value from its bend |
| pca_ratio | – | 1 : sd2/sd1 : sd3/sd1 | elongated ≈ 1:small:small, flat ≈ 1:large:small, compact ≈ 1:1:1 |
| pca_axes | unit vectors | principal directions (canonical x/y/z) | shown as red / green / blue lines (± 2 sd) |
| extent_mm | mm | range of voxel centres along each principal axis + one voxel measured along it | ± 1 voxel |
| bbox_mm | mm | axis-aligned bounding box | |
| thickness_mm | mm | local thickness = 2 × EDT to the nearest outside voxel − one voxel measured along that direction (+ one voxel on a two-voxel ridge plateau), read at the nearest medial-ridge voxel; mean / median / min / max / p10 / p90 | quantised to the voxel size; "low reliability" when the median is < 1.5 × the largest voxel side |
| local_share | fraction | per voxel, spreads s1 ≥ s2 ≥ s3 of the mask within 3 × its local thickness (4–7 mm, ≥ 3 voxels, same piece only): **blob** s3/s1 ≥ 0.5 and thickness ≥ 3 s3; **tube** s2 ≤ 0.45 × thickness + 0.25 voxel and s2 ≤ 1.8 s3 and s1 ≥ 2 s2; **sheet** otherwise; **uncertain** < 8 neighbours | edges of a sheet stay sheet (absolute width, not ratios); a two-layer structure (both sulcal banks) stays sheet (not solid); one-voxel-thin lines are borderline tube / sheet |
| xsections | mm, mm² | 12 slabs perpendicular to the first principal axis: area (voxel volume / slab width), equivalent diameter, major / minor extent, eccentricity | oblique for strongly curved objects (local shape is the curvature-independent measure) |
| xsection_cv | – | coefficient of variation of the slab equivalent diameters | small = stable radius |
| skeleton | mm, count | Lee curve skeleton (scikit-image) — length (26-neighbour steps, physical), end points, branch points (≥ 3 neighbours), radius along it (ordered along PC1) | **shown only when ≥ 40 % of voxels are tube-like**: the medial set of a sheet is a surface; even-thickness objects use a one-voxel-thickened copy (noted) |
| hessian | fraction, per voxel | scale-normalised Hessian of the SWI at 0.8 / 1.6 mm (detect_css.py `HESS_SIGMAS_MM`), eigenvalues sorted by \|λ\| ascending, scale with the largest λ3 kept; dark structure → λ3 > 0. tube = \|λ2\|/λ3 if \|λ1\|/λ3 < 0.5 (detect_css TUBE); sheet = 1 − \|λ2\|/λ3; blob = \|λ1\|/λ3; eigenvector of λ1 stored | convention verified in `detect_css.py` lines ~547–556; on compact blobs the Hessian reads "tube" near the rim (phantom blob: 0.81), which is why it is a separate overlay, not the classifier |
| surface | fraction, mm, mm² | within 1 mm of the pial surface (\|signed distance\| ≤ 1), median pial distance (− tissue, + CSF), share in CSF (> 0.5 mm) / tissue (< −0.5 mm), cortical footprint (cortex-surface voxels within 1.5 mm × face area) | needs `work/ID_pial_sd` (T1 labels); proximity alone is not evidence of cSS |
| vessel | flag, count, mm | detector vessel map (`work/ID_vessels`) segments touching the dilated candidate; connected length; contact voxels | a connection is evidence of vascular anatomy nearby, not proof that the candidate is a vein; no connection is not evidence of cSS |
| reliability | good / moderate / low | notes: < 30 voxels, thickness near the voxel size, voxels > 2:1 anisotropic, several pieces | |
| summary | text | "predominantly X-like geometry [with a Y-like part (N %) – mixed]; follows / partly on / away from the pial surface; touches the vessel map. Measurement reliability: …" | descriptive only |

## Mixed structures

Every voxel keeps its own local class, so a candidate that is part vein and part cSS shows two coloured regions (the PH6
phantom's surface-vein candidates #7 / #8 show tube and sheet parts). Nothing is excluded; uncertain voxels stay grey.
