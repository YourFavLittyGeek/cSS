# Independent audit of the v5.12 3-D morphology analysis

Scope: `scripts/css_morph3d.py`, the `/api/morph3d` endpoint and the tests, as committed in `d7af64a` on
`experimental/3d-morphology-viewer`. That commit was made and pushed **before** this audit was requested, at the user's
earlier "commit and push".

During the audit:
- no code was changed;
- nothing was committed or pushed;
- detection, scoring and production defaults are untouched.

Audit code and outputs:
- `audit_3d/run_audit.py` and `audit_3d/run_audit_extra.py`: the audit code; they import the module and never edit it;
- `audit_3d/results/*.csv`: every number quoted below.

Bottom line: the **measurements of the mask** (volume, extents, thickness of the digitised mask) are arithmetically sound
within ±1 voxel. The **tube / sheet / blob classification is not robust** in the size range where real cSS and cortical
veins live:
- structures narrower than about 5 mm, or only one slice thick, are misclassified;
- several of its thresholds were tuned on the very data (11 synthetic shapes, PH6) later reported as validation.

It should be shown only as exploratory until corrected and re-validated on held-out data.

---

## 1. Thickness mathematics (`local_thickness`)

**Definition used.** Let `dt(p)` be the Euclidean distance (scipy EDT with per-axis voxel size) from voxel centre `p` to
the nearest background voxel **centre**. Let `u` be the unit vector to that background voxel. Then:

- step(p) = 1 / sqrt(Σ_i u_i² / v_i²), with `v` the voxel size;
- t(p) = 2·dt(p) − step(p), clipped at ≥ 0.5·min(v).

Ridge voxels are local maxima of `dt` in the 26-neighbourhood. If the neighbour one step further from the background
(along sign(u), components > 0.38) has an equal `dt`, the voxel is on a 2-voxel plateau and receives `+step`. Finally,
every mask voxel takes the `t` of its nearest ridge voxel (Euclidean, in mm).

- **Radius or thickness?** `dt` is a radius-like distance from a voxel centre. `2·dt − step` converts it to a full
  thickness counted in whole voxels: a one-voxel layer gives `2·v − v = v`.
- **Odd and even voxel counts.** An odd count N has a single ridge voxel with dt = (N+1)/2·v, so t = N·v. An even count
  has a two-voxel plateau with dt = N/2·v, so t = (N−1)·v, and the plateau rule adds the missing voxel. Verified
  exactly on flat sheets: measured = digitised to 0.00 mm at 0.4 mm isotropic and at 1 mm isotropic.
- **Perpendicular to the sheet?** Only approximately. `u` points to the nearest background voxel centre. That is close
  to the local normal for a smooth sheet, but it is quantised to the voxel lattice.
- **The `step` term is not the voxel chord along `u`.** It is the length used in the formula, not the box chord:
  - along an axis both agree;
  - along a diagonal of 1 mm voxels the formula gives 1.0 mm but the box chord is 1.41 mm (`1_thickness.csv`, rows
    `step_term`).
  
  Consequence: thickness measured along oblique directions is mis-corrected by up to about 0.4 voxel.
- **Curved sheets.** The nearest-ridge assignment works for curvature radius ≥ 2.5 mm:
  - 1.2 mm sheet, curvature radius 2.5 / 4 / 6 / 12 mm → 1.2 / 1.39 / 1.2 / 1.2 mm at 0.4 mm isotropic voxels;
  - 1.2 mm at 0.8 × 0.8 × 1.2 mm voxels;
  - against a digitised thickness of 1.14–1.41 mm.
- **Anisotropy and partial volume dominate** (`1_thickness.csv`). Thickness is quantised to whole voxels along the
  normal, and the digitisation decides the answer.

  Flat sheets at 0.8 × 0.8 × 1.2 mm:

  | True sheet | Centred in a slice | Straddling two slices |
  |---|---|---|
  | 0.6 mm | 1.2 mm | disappears |
  | 1.2 mm | 1.2 mm | 2.4 mm |
  | 2.0 mm | 1.2 mm | 2.4 mm |
  | 2.4 mm | 3.6 mm | 2.4 mm |

  At 0.4 × 0.4 × 3 mm, every sheet of 2.0–3.6 mm reads 3.0 mm, and a 3.6 mm sheet straddling two slices reads 6.0 mm.

  Tilted 1.2 mm sheet at 0.8 × 0.8 × 1.2 mm, tilted 45–75°: 1.6 mm against a digitised 1.01–1.15 mm, an
  overestimate of +0.45 to +0.59 mm caused by the `step` term.
- **Systematic bias.** Thickness is unbiased against the *digitised mask* to within ±0.25 mm on isotropic data, with
  +0.45–0.6 mm on oblique anisotropic sheets. Against the *true structure* the error is ±1 voxel along the normal and is
  set by partial volume, not by the algorithm.
- **PH6 cSS.** The true bands are 1.2 mm thick and measure 1.6 mm as digitised truth masks. The detector candidates
  measure 1.46–2.4 mm. The candidate masks are about twice the lesion volume (section 4), so the reported thickness
  describes the detector's blooming mask, not the deposit.

## 2. Local morphology classification (`local_shape`): exact definitions

For voxel `i` with local thickness T_i:

- neighbourhood radius R_i = clip(3·T_i, max(4, 3·v_max), max(7, 3·v_max)) mm, using only voxels of the same
  26-connected piece;
- s1 ≥ s2 ≥ s3 = square roots of the eigenvalues of the covariance of neighbour voxel-centre coordinates (mm). These
  are spreads (standard deviations) of the mask, not image curvatures.

| Class | Equation | Units | Threshold | When chosen |
|---|---|---|---|---|
| blob | s3/s1 ≥ 0.5 **and** T_i ≥ 3·s3 | ratio; mm | 0.5; factor 3 | 0.5 after the first run on the 11 synthetic shapes; the "solid" T ≥ 3·s3 condition **after seeing PH6 cSS candidates read "blob"** |
| tube | s2 ≤ 0.45·T_i + 0.25·v_max **and** s2 ≤ 1.8·s3 + 0.15·v_max **and** s1 ≥ 2·s2 | mm | 0.45, 0.25, 1.8, 0.15, 2 | iteratively, after failures on the same 11 synthetic test shapes (sheet edges, fragmented sheet) |
| sheet | otherwise | – | – | – |
| uncertain | fewer than 8 neighbours | count | 8 | first version |

- **Source data.** Voxel-centre coordinates of the candidate mask only (no image), plus `T_i` from section 1.
- **Sensitivity to voxel spacing.** Strong:
  - `s3` of a one-slice-thick structure is about 0, so "round across" (s2 ≤ 1.8·s3 + 0.15·v_max) fails for any tube
    that occupies a single slice. Such tubes become "sheet".
  - The radius floor of 4 mm (3 × 1.2 mm) makes every structure narrower than about 4–5 mm look elongated within the
    neighbourhood, so narrow bands become "tube".
- **Genuinely local?** Partly:
  - separate pieces never mix (same-component rule), which works: two-pieces phantom, adversarial 10c;
  - within one connected piece, the 4–7 mm neighbourhood mixes structures across junctions. On a sheet with an
    attached branching vessel, only 30 % of the vessel voxels are called tube; the rest are absorbed into "sheet".
- **Image Hessian** (separate source). Gaussian derivatives of the SWI crop at σ 0.8 and 1.6 mm. The convention matches
  `detect_css.py` (|λ1| ≤ |λ2| ≤ |λ3|, dark structure → λ3 > 0). Its support (~3σ, up to about 5 mm) includes adjacent
  structures, so image contamination is inherent. On a compact blob it reads "tube" for 81 % of voxels (rim curvature).

## 3. Adversarial synthetic validation

Ground truth per structure (`3_adversarial.csv`, `3b_adversarial_extra.csv`). Voxels 0.8 × 0.8 × 1.2 mm unless noted.
Pass = ≥ 70 % of each true structure's voxels in its correct class, and the expected number of pieces.

| # | Case | Result | Pass |
|---|---|---|---|
| 1 | thin curved sheet, 0.6 → 1.8 mm | sheet 95 %; the thin end breaks into 3 pieces (partial volume) | class yes; pieces no |
| 2 | sheet with interruptions (1 mm gaps every 4 mm) | **tube 100 %**: the 3 mm-wide strips read as tubes | no |
| 3 | vein r 0.8 mm parallel to the surface | tube 48 % / sheet 52 % (one-slice-thick tube) | no |
| 3b | same vein, r 1.2 mm | tube 100 % | yes |
| 4 | compressed vein, 3.0 × 1.0 mm | **vanished** (thinner than half a slice) | n/a |
| 4b | compressed vein, 3.2 × 1.8 mm | tube 100 % | yes |
| 5 | vein partly merged with a sheet | sheet part 100 % correct; vein part 52 % tube | no |
| 6 | two adjacent veins 2.2 mm apart | **sheet 100 %** (two tubes side by side = a ribbon) | no |
| 7 | sheet with an attached branching vessel | sheet 100 %; vessel 30 % tube | no |
| 8 | sharp U-fold sheet (radius 2.1 mm) | sheet 100 % | yes |
| 9 | oblique sheet on 0.4 × 0.4 × 3 mm | sheet 82 %; 4 pieces | yes |
| 10a, 10b | tube r 0.5 mm beside / touching a sheet | **the tube vanished** at this resolution | n/a |
| 10c, 10d | tube r 0.8 mm beside / touching a sheet | separate piece, but **tube read as sheet 100 %** | no |
| – | 1.2 mm ribbon, 2 / 3 / 4 mm wide | **tube 100 %** | no |
| – | 1.2 mm ribbon, 6 / 8 mm wide | sheet 100 % | yes |

Interpretation: the classifier separates tube from sheet only when two conditions hold. A tube has to be at least about
2 slices thick, and a sheet at least about 5–6 mm wide. Narrow cSS bands, thin in-plane veins, flattened or paired
veins, and vessels attached to a sheet are exactly the cases it gets wrong.

## 4. PH6 audit (`4_ph6.csv`)

Matching. Each candidate was assigned to the independent truth masks `PH6_truth` (lesions), `PH6_veins` and
`PH6_surfvein` by the share of its voxels inside them; ≥ 0.3 counts as a match. That 0.3 threshold is my choice.

| Cand | Identity | In truth | Truth lesion covered | Tube / sheet / blob / unc | Thick (mm) | Volume (mm³) | Reliability | CSF / tissue | Pieces |
|---|---|---|---|---|---|---|---|---|---|
| 1 | cSS lesion 1 | 0.50 | 1.00 | 0 / 1.00 / 0 / 0 | 2.4 | 1396 | moderate | 0.13 / 0.87 | 7 |
| 2 | cSS lesion 3 | 0.49 | 1.00 | 0 / 1.00 / 0 / 0 | 1.46 | 757 | moderate | 0.13 / 0.87 | 1 |
| 3 | cSS lesion 2 | 0.49 | 1.00 | 0 / 0.995 / 0 / 0.005 | 2.4 | 718 | moderate | 0.08 / 0.92 | 5 |
| 4 | cSS lesion 5 | 0.51 | 1.00 | 0 / 1.00 / 0 / 0 | 1.86 | 584 | good | 0.13 / 0.87 | 1 |
| 5 | cSS lesion 6 | 0.45 | 1.00 | 0 / 0.99 / 0 / 0.01 | 2.4 | 363 | moderate | 0.15 / 0.85 | 5 |
| 6 | vein (PH6_veins) | 0.66 | – | 0.82 / 0 / 0 / 0.18 | 0.8 | 58 | moderate | 0.66 / 0.34 | 10 |
| 7 | surface vein (PH6_surfvein) | 1.00 | – | 0.52 / 0.40 / 0 / 0.08 | 0.8 | 37 | moderate | 1.00 / 0 | 1 |
| 8 | surface vein (PH6_surfvein) | 0.91 | – | 0.47 / 0.43 / 0 / 0.09 | 0.8 | 41 | moderate | 0.92 / 0.08 | 1 |
| 9 | vein (PH6_veins) | 0.93 | – | 0 / 1.00 / 0 / 0 | 1.46 | 81 | moderate | 0.93 / 0.07 | 1 |
| 10 | surface vein (PH6_surfvein) | 0.99 | – | 1.00 / 0 / 0 / 0 | 1.6 | 71 | moderate | 0.99 / 0.01 | 1 |
| 11 | surface vein (PH6_surfvein) | 0.99 | – | 1.00 / 0 / 0 / 0 | 1.6 | 71 | moderate | 0.99 / 0.01 | 1 |

- Every candidate matches exactly one truth structure. **Correction to the validation report:** #7, #8, #10 and #11
  were called "other"; they are surface veins in `PH6_surfvein`.
- **Mismatches:**
  - #9 is a 1.4 mm-diameter sulcal vein, but its *candidate mask* is a 40 × 5.7 × 2.4 mm ribbon. It reads sheet-like
    because the detector's mask is not the vessel's shape.
  - #7 and #8 (one-voxel-thin surface veins) are about 50/50 tube / sheet.
- **cSS candidates are about twice the lesion.** Only 45–51 % of their voxels lie inside the true band; the rest is
  blooming or the adjacent dark rim. Each candidate covers its lesion completely.
- Truth lesion 4 (convexity) is matched by no candidate in this list. That is a detection matter, outside this audit.
- **Data leakage, disclosed explicitly:**
  1. The "solid" condition for blob (T ≥ 3·s3) was added **after** the first PH6 run showed cSS #1–#5 as "blob-like".
     The PH6 cSS results are therefore **not independent validation**.
  2. Every tube / sheet threshold, the per-voxel radius rule and the same-piece rule were adjusted after failures on
     the **same 11 synthetic shapes** that `check_morph3d.py` then reports as passing.
  3. The thickness plateau correction was added after the synthetic cylinder measured 0.8 mm.
  4. The pass thresholds of both tests (for example "sheet ≥ 0.8" for PH6 cSS) and the loosened volume tolerance on
     thick slices were set after seeing the outputs.
  5. The `thin_aniso` phantom was moved to sit centred in a slice after it vanished.

  None of these numbers is a held-out result.

## 5. Surface (`5_surface.csv`; the original mask is authoritative)

- **Marching cubes vs voxel volume:** the raw mesh is 1–15 % smaller (level 0.5 cuts the voxel corners). Taubin display
  smoothing changes it a further +1 to −7 % (largest on thin cylinders).
- **Partial volume dominates the voxel volume itself.** Cylinder r 1.2 mm (true 89 mm³):
  - 0.8 × 0.8 × 1.2 mm along z: 49 mm³ (−45 %); along x: 74 mm³;
  - 1 mm isotropic: 80 mm³;
  - 0.4 × 0.4 × 2 mm along x: 120 mm³ (+36 %).
  
  So volume depends on orientation and slice thickness by ±40 % for thin structures.
- **Surface area:** the raw mesh is 0–30 % below the true area for thin cylinders at coarse resolution, and up to +36 %
  on thick-slice anisotropic grids.
- **Thickness before and after smoothing:** thickness is computed on the mask only, so smoothing has no effect on any
  reported measurement. It affects only the display (a thin cylinder shrinks visibly by about 7 %).
- **Conclusion:** no clinically meaningful distortion is added by meshing or smoothing beyond what the digitisation
  already contains. The mask is, and must remain, the authority. Volume and area of thin structures are uncertain by
  tens of percent.

## 6. Anatomical context (`6_context_shift.csv`)

CSF and pial-contact fractions come from the signed pial distance of the registered T1 labels. Shifting the labels by
0.8–1.6 mm (one or two voxels, still within the pipeline's 1.5 mm registration gate):

- moved the true-cSS candidate #4 from 13 % CSF to **0–72 %** depending on the direction;
- moved #1 from 13 % to 9–49 %;
- moved the vein #6 from 66 % to 5–84 %.

Other ways a genuine cSS candidate can appear "in CSF":
- partial volume at the pial boundary;
- SynthSeg cortex boundaries that differ from the SWI's pial edge;
- tight sulci where both banks and the CSF between them share voxels;
- detector blooming (half of each PH6 cSS candidate lies outside the true band).

**The CSF fraction must not be used as an exclusion criterion.** It is unstable at registration errors the pipeline
accepts.

## 7. Bugs and weaknesses (verified)

| ID | Item | Evidence |
|---|---|---|
| B1 | **Phantom generator scale bug** (`tests/morph_phantoms._down`): a voxel spans round(v / 0.2) fine samples, so a "0.5 mm" voxel is really 0.4 mm (+25 % error per affected axis). Affects the `thin_aniso` phantom and the 0.5 × 0.5 × 2 mm anisotropy tests (their volumes and thicknesses are mis-scaled). Production code is unaffected. | `0_generator_scale.csv` |
| B2 | Tube criterion fails for single-slice structures (s3 ≈ 0): thin in-plane tubes → sheet | adv. 3, 10c, 10d; PH6 #7–#8 |
| B3 | Ribbons ≤ 4 mm wide → tube; narrow cSS bands will often be called tube | ribbon sweep, adv. 2 |
| B4 | Paired or adjacent veins merge into a ribbon → sheet | adv. 6 |
| B5 | A vessel attached to a sheet is absorbed near the junction (4–7 mm neighbourhood) | adv. 7 (30 %) |
| B6 | `step` term ≠ voxel chord along oblique directions: thickness bias up to +0.6 mm on oblique anisotropic sheets | `1_thickness` step / tilted rows |
| B7 | Thickness quantised to whole voxels along the normal; on 3 mm slices every sheet ≤ 3 mm reads 3.0 mm | flat rows |
| B8 | Candidate mask ≠ anatomical structure (blooming): morphology describes the detector's mask; PH6 cSS candidates about 2× the lesion; sulcal vein #9 becomes a ribbon | section 4 |
| B9 | The image Hessian reads compact blobs as tube (81 %) and its 3σ support includes neighbours | synthetic table |
| B10 | Skeleton length is capped at (n − 1)·‖v‖, an approximation | code |
| B11 | Reliability is almost always "moderate" (the rule rarely says "low"); it does not flag the B2–B5 regimes | sections 3–4 |
| B12 | Summary wording thresholds ("follows / partly on the pial surface" at 0.6 / 0.3) are arbitrary | code |

## 8. Recommended corrections, ranked by importance

1. **Label the tube / sheet / blob class as exploratory, and return "not resolvable" instead of a class when:**
   - the structure is ≤ 1 slice thick, or narrower than about 5 mm (the neighbourhood floor);
   - or two structures merge.
   
   Do not use it for any decision or rule.
2. **Freeze the current thresholds and validate on held-out data:** new adversarial shapes generated by someone or
   something other than the tuning loop, and PH-series phantoms not used here. Then real-patient expert labels.
3. **Fix B1** (assert the voxel size is a multiple of the fine grid, or resample exactly), then re-run every
   synthetic test and the anisotropy table.
4. **Fix B2:** judge roundness in-plane when the slice thickness exceeds the structure, or mark it unresolved.
5. **Fix B6:** use the voxel chord min_i v_i / |u_i| (or measure thickness along an estimated surface normal).
6. **Report thickness and volume with their quantisation:** for example "1.2 mm (one slice; true 0.6–2.4 mm)",
   with voxel volume and mesh volume side by side, and a thin-structure warning.
7. **Show the CSF / pial fractions with the registration uncertainty:** the QC label shift, and a range across ±1-voxel
   label shifts. Never use them as exclusion.
8. **Separate the candidate's dark core from its blooming halo** (for example a darkness-weighted core) before
   measuring shape.
9. **Hessian:** compute on an image masked to the candidate's neighbourhood, or state the contamination. Do not show
   it as a class on compact objects.
10. **Correct the validation report:** #7–#11 are surface veins; the PH6 cSS results are not independent (leakage
    item 1).

## 9. Validation status, separated

| Level | What was done | Status |
|---|---|---|
| A. Software tests | `check_morph3d.py` (11 shapes), `check_morph3d_api.py` (PH6), reviewer browser tests, `review_web` tests, shell tests | pass; **but their thresholds were tuned on the same data**, so they are regression tests, not validation |
| B. Synthetic morphology validation | 10 new adversarial cases + variants and a ribbon-width sweep with independent ground truth (this audit) | **mixed:** 6 of 16 variants pass; systematic failures for narrow, one-slice-thin, paired and attached structures |
| C. Phantom validation | PH6 (5 cSS, 2 veins, 4 surface veins) matched to independent truth masks | all 5 cSS read sheet, but **after a rule change made on these candidates (leakage)**; veins: 3 of 6 clearly tube, 2 mixed, 1 ribbon |
| D. Real-patient validation | none | **not done.** Nothing here is clinical validation. |

## 10. Explicit limitations of this audit

- Phantoms and synthetic shapes only. Their contrast, blooming and anatomy are simplified.
- The adversarial cases were designed by the same agent that wrote the implementation (not fully independent).
- One acquisition geometry dominates (0.8 × 0.8 × 1.2 mm), plus 0.4 mm isotropic, 1 mm isotropic and 3 mm slices.
- Registration error was simulated as a rigid shift of the pial-distance map, not by real misregistration.
- The audit did not test the WebGL rendering beyond what the existing browser test covers.
