# v5.13 resolution-aware morphology and candidate decomposition: experimental report

Status: **experimental, uncommitted** (branch `experimental/morphology-v513`, from `d7af64a`). Detection, scoring,
production defaults, the v5.12 module and the viewer are unchanged. Synthetic and phantom data only. **No real-patient
validation. Nothing here is clinical validation.**

## Verdict in five lines

1. **Candidate decomposition (dark core / blooming) improves physical measurements, on held-out phantoms:**
   - median thickness error 0.99 → 0.34 mm; core closer to truth than v5.12 in 149 / 192 cases;
   - Dice with the true structure 0.46 → 0.66; better in 162 / 192;
   - volume overestimate 3.2× → 1.8×.
   
   But the core still contains about 35 % of the blooming voxels, and 33 % of core voxels are unstable.
2. **No morphology approach tested here separates sheet-like from tube-like structures reliably in phantoms with
   blooming.** The surface-normal classifier (A2) abstains almost always ("indeterminate"). v5.12's local classifier is
   biased towards "sheet" (89 % on sheets, 35 % on tubes). Core width, thickness and slice count separate bands from
   veins at chance level (AUC 0.53–0.62, post hoc).
3. The resolvability gate is **weakly calibrated**. Structures thinner than half a slice were declared "not resolvable"
   in only 8 / 38 cases; the rest were "partially resolved".
4. Phase 1 fixes:
   - **B1 (generator) was real** and changes one v5.12 result: the 0.5 × 0.5 × 2 mm cylinder test now fails (tube 0 %).
     The old pass came from the mis-scaled phantom.
   - **B6 (box chord) gives no improvement**; slightly worse on some oblique sheets.
   - **B10 (MST length)** is identical to v5.12 on every test.
5. Recommendation: **keep the decomposition** as a measurement aid, with uncertainty shown. **Do not ship any tube / sheet
   label** (v5.12 or v5.13) as more than exploratory. **Abandon A2** in its current form (criteria in section 9).

## 0. Baseline preserved

- `morph_v513/baseline/`: the v5.12 file hashes, the v5.12 test output, the v5.12 numbers and the v5.12 phantom generator.
- `scripts/css_morph3d.py` is unchanged (its hash is checked in `FREEZE.json`).
- The v5.12 tube / sheet / blob output is labelled **exploratory** in `baseline/BASELINE.md` and in this report.

**Not yet done:** the label inside the viewer. That is a UI change and waits for your image approval.

## 1. Architecture (new files, all uncommitted)

| Path | Role |
|---|---|
| `scripts/css_morph3d_v2.py` | v5.13 experimental module: decompose, thickness (chord), mst_length, inplane (A1), normal_tensor (A2 at 2 / 4 mm = A5), resolvability + stability (Phase 4), context ± 1 voxel (Phase 6). Imports v5.12 for the skeleton and the Hessian (A4, unchanged) |
| `tests/morph_phantoms.py` | B1 fixed: per-axis fine step that divides each voxel exactly; raises on an incompatible voxel size |
| `tests/check_morph3d.py` | one line changed: anisotropy grid built with the voxel size (required by the B1 fix) |
| `morph_v513/bloom_phantoms.py` | blooming phantoms with independent truth (structure labels, blooming region, detector-like candidate) |
| `morph_v513/evaluate_bloom.py` | v5.12 vs v5.13 evaluation; refuses to run held-out cases unless `FREEZE.json` hashes match |
| `morph_v513/phase1_compare.py`, `figures.py`, `posthoc_a1.py` | Phase 1 comparison, decomposition figures, post-hoc A1 check |
| `morph_v513/DESIGN_DECLARED_BEFORE_TESTING.md`, `CHANGES_AFTER_TESTING.md`, `FREEZE.json`, `heldout_spec.json` | pre-registration, disclosed change, freeze record, held-out parameter ranges |
| `morph_v513/results/*` | every number below |

## 2. Mathematical definitions (new features)

Notation: `v` = voxel size (mm); `I` = SWI intensity.

- **Background**:
  - shell 2–5 mm outside the candidate, voxels below median − 2·1.4826·MAD removed once;
  - μ_b = median, σ_b = 1.4826·MAD of the remainder.
- **Darkness**: c(x) = (μ_b − I(x)) / σ_b, in noise units.
- **Local peak**: c_pk(x) = max of c within 2 mm.
- **Dark core**: x in the candidate dilated by one voxel, with c(x) ≥ ½·c_pk(x) (half maximum) and c_pk ≥ 3.
- **Core unstable**: membership differs between 0.4·c_pk and 0.6·c_pk, or |c − ½·c_pk| < 1.
- **Blooming / support**: candidate \ core. **Adjacent**: c ≥ 3 components within 5 mm that touch neither candidate nor core.
- **Thickness (B6)**: 2·EDT − chord(u), with chord(u) = min_i v_i / |u_i|. Plateau correction and nearest-ridge
  assignment as in v5.12.
- **Skeleton length (B10)**: total weight of the minimum spanning tree over 26-neighbour skeleton edges (mm).
- **A1 in-plane** (per acquisition slice, slice axis = largest voxel side):
  - per 2-D piece: area; width = 2·max(2-D EDT) − in-plane chord;
  - length = MST length of the 2-D skeleton.
- **A2 surface-normal tensor**:
  - T(x) = Σ a_f n_f n_fᵀ / Σ a_f over marching-cubes triangles within r of x (r = 2 and 4 mm);
  - eigenvalues e1 ≥ e2 ≥ e3; nearest prototype sheet (1, 0, 0), tube (½, ½, 0), blob (⅓, ⅓, ⅓);
  - "mixed" if d1 ≥ 0.75·d2. **A5** = A2 at both scales agree.
- **Resolvable voxel** (after the disclosed change): not (≤ 1 slice at that voxel AND in-plane width < 2 × slice thickness).
- **Stability**: share of A2 (2 mm) labels unchanged after a one-voxel erosion and after a one-voxel dilation (mean).
- **Level**:
  - resolved: resolvable ≥ 0.8 and stability ≥ 0.7;
  - partially resolved: resolvable ≥ 0.3;
  - otherwise not resolvable.
- **Label**: "not resolvable" if the level is; else the class holding ≥ 60 % of resolvable-and-agreeing voxels; else
  "mixed" if a second class holds ≥ 25 %; else "indeterminate".
- **Context (Phase 6)**: CSF fraction (signed pial distance > 0.5 mm), tissue fraction (< −0.5 mm), within 1 mm, median
  pial distance. Each is also recomputed with the map shifted ± 1 voxel along x, y, z and reported as min–max.

## 3. Phase 1 results (what changed)

- **Original suite with the B1-fixed generator** (`phase1_check_morph3d_B1fixed.txt` vs `baseline/v512_check_morph3d.txt`):
  - the only changes are at 0.5 × 0.5 × 2 mm;
  - cylinder along x: tube-like 0.89 → **0.00 (now FAILS)**, volume 188 → 76 mm³, length 24.0 → 19.0 mm;
  - cylinder along z: volume 152 → 80 mm³;
  - every other result is identical.
- **B6** (`results/phase1_compare.csv`):
  - the 11 original shapes are unchanged;
  - tilted 2.0 mm sheets: 1.86 → 1.70 mm (0.4 mm isotropic, digitised 2.0–2.08) and 1.86 → 1.44 mm (0.8 × 0.8 × 1.2,
    digitised 2.03–2.14), i.e. **worse**;
  - the +0.6 mm overestimate on a tilted 1.2 mm sheet persists. Its cause is the distance to staircase voxel centres,
    not the step term.
- **B10**: MST length is identical to v5.12 on every shape. A 3-D diagonal tube on 0.5 × 0.5 × 2 mm reads 29.0 mm in
  both (true 24.2): the skeleton itself zig-zags.
- **B11 / B12**: reliability is replaced by the resolvability level with reasons; the summary lists numbers only.

## 4. Decomposition results

Before / after figures with the original mask, core and blooming shown separately:
`results/fig_decomposition_dev.png` (development phantoms) and `results/fig_decomposition_ph6.png`.

Held-out phantoms (n = 192 detectable of 200; `results/bloom_heldout.csv`, `heldout_summary.txt`):

| Measure | v5.12 on candidate | v5.13 on candidate | v5.13 on dark core |
|---|---|---|---|
| Thickness \|error\| vs true (median [IQR]) | 0.99 [0.52–1.41] mm | 0.79 [0.40–1.35] mm | **0.34 [0.17–0.61] mm** |
| Signed thickness bias | +0.97 mm | +0.77 mm | +0.07 mm |
| Dice with the true structure | 0.46 | 0.46 | **0.66** |
| Volume / true volume | 3.23 | 3.23 | **1.83** |

- Blooming voxels left in the core: median 35 %. Unstable core voxels: 33 %.
- **PH6 (development, not validation)**:
  - the core helps #2 (Dice 0.58 → 0.82) and the surface vein #10;
  - it **hurts the two-banked cSS #1** (Dice 0.66 → 0.45; thickness 2.4 → 1.13 mm, true 1.2 mm digitised 1.6 mm);
  - it is neutral on #4 and #9.

So decomposition improves measurements on average, but can remove real structure.

## 5. Morphology approaches

Held-out, per true structure (`heldout_summary.txt`). "Correct" requires resolvable and both scales agreeing on the
right class.

| True structure | v5.12 correct (mean) | A2 on candidate | A2 on core | A2 "not resolvable" |
|---|---|---|---|---|
| Sheet (n 115) | 0.89 | 0.03 | 0.06 | 0.08 / 0.19 |
| Tube (n 184) | 0.35 | 0.16 | 0.24 | 0.23 / 0.34 |

Structure-level labels (core):

| Kind | Result |
|---|---|
| bands (n 38) | 1 sheet-compatible, 29 indeterminate |
| single veins (n 36) | 16 tube-compatible, 8 blob-like, 7 indeterminate, 5 not resolvable |

- **v5.12 is not better.** Its sheet "accuracy" reflects a bias: it calls 65 % of tube voxels sheet.
- **A1 post hoc** (single bands vs single veins, AUC): core width 0.53, core thickness 0.59, slices 0.61, width/length
  0.25 (i.e. 0.75 inverted). This is a weak signal, found after the run, not validated.
- **A4 (Hessian)** is unchanged from v5.12 and not re-evaluated here.

## 6. Resolution and reliability

| True thickness / slice thickness | n | Not resolvable | Partially resolved | Resolved |
|---|---|---|---|---|
| < 0.5 | 38 | 8 | 27 | 3 |
| 0.5–1 | 75 | 2 | 69 | 4 |
| 1–2 | 74 | 0 | 68 | 6 |
| ≥ 2 | 5 | 0 | 5 | 0 |

- The gate rarely says "resolved" and rarely says "not resolvable". It does not track the physical ratio well. The
  stability term (erosion / dilation) drives most cases to "partially resolved".
- **Phase 6** (PH6, ± 1 voxel shift): CSF fraction of true cSS #4 is 0.13 with a range of **0.00–0.42**; of #1, 0.13
  with a range of 0.09–0.29; of the vein #6, 0.66 with a range of 0.37–0.82. The ranges overlap. **CSF and pial distance
  are descriptive only and are never used to exclude.**

## 7. Development data and tuning (disclosed)

- **Development data:** the 11 original shapes, the audit's adversarial cases, blooming seeds 0–29, PH6.
- **One rule was changed after testing:** the resolvability definition (`CHANGES_AFTER_TESTING.md` #1), for a definitional
  bug, not to improve a score.
- No threshold was changed after the held-out run. Held-out seeds 1000–1199 were generated and run once, after the
  freeze (`FREEZE.json` hashes are checked by the evaluator).
- The phantom model is simplified (Gaussian blooming, intensity threshold as the "detector"), written by the same agent
  that wrote the method. It is not independent of the method's assumptions.

## 8. Failure analysis

- **Core loses real thin structure** where two thin bands lie close together (tram-track): half-maximum relative to a
  local peak treats the weaker bank as halo.
- **The core keeps about a third of the blooming**: with Gaussian blooming at σ 0.4–1.2 mm the half-maximum contour still
  lies outside thin structures (the stated FWHM limit).
- **A2 cannot see blobs larger than its radius** (a ball's surface is locally flat), and sheet edges disagree between
  scales. Both drive "indeterminate".
- **Stability under ± 1-voxel erosion and dilation is low for every thin structure**: erosion deletes them. This makes
  the stability measure uninformative where it is most needed.
- **B6 analysis in the audit was partly wrong**: the chord is not the dominant oblique error.

## 9. Findings that justify abandoning an approach

| Approach | Abandon if | Status |
|---|---|---|
| A2 surface-normal tensor | held-out per-voxel correctness on sheets < 0.5 at the declared constants | **met (0.03–0.06): abandon in this form** |
| v5.12 local classifier | sheet / tube balanced accuracy < 0.7 or strong class bias | **met (0.89 / 0.35): exploratory only** |
| Dark-core decomposition | no thickness or Dice improvement on held-out data | **not met:** improves both (keep, show uncertainty) |
| Resolvability gate | "not resolvable" < 50 % for true thickness < half a slice | **met (21 %): redesign before use** |
| A1 in-plane width | AUC < 0.65 for band vs vein | **met post hoc (0.53): not a discriminator alone** |
| Context fractions as evidence | ranges under ± 1 voxel overlap between cSS and vein | **met: descriptive only** |

## 10. Validation status, separated

| Level | Status |
|---|---|
| A. Software tests | original suite runs: 1 failure (the cylinder at 0.5 × 0.5 × 2 mm) caused by the B1 fix, kept as a true failure |
| B. Synthetic morphology | development + held-out blooming phantoms (above); thickness and volume improve with the core; tube / sheet classification does not work |
| C. Phantom (PH6) | development only (thresholds of the earlier version were tuned on it); not validation |
| D. Real patients | **not done** |

## 11. Suggested next steps (none started)

1. Show the dark core and blooming as **separate layers** in the 3-D viewer, with core uncertainty, and keep the original
   mask as the reference (needs a mockup and your approval).
2. Report thickness and volume of **both** candidate and core, with the voxel quantum and the unstable fraction.
3. Drop A2. Keep the v5.12 local classes only as an exploratory overlay, clearly labelled.
4. Redesign resolvability from the physical ratio (local thickness / slice thickness, in-plane width / pixel) without the
   erosion-based stability term, pre-register it, and test on a new held-out seed range.
5. Collect expert-outlined real cases (dark core outlines) before any further shape claims.
