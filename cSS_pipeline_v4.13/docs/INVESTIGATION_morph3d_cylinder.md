# Investigation: `check_morph3d` cylinder failure (0.5 × 0.5 × 2 mm voxels)

Status: **real defect in the v5.12 3-D viewer's local-shape classifier - FIXED in cycle 2 by a resolution-confidence assessment (section "Implemented resolution-confidence design").**
Detector, rules, 0–4 score and the unified score are not affected (see the end).

## Failing check
`tests/check_morph3d.py`: `FAIL cylinder r 1.2 along x, voxels (0.5, 0.5, 2.0): tube-like 0.0`. The check requires a tube-like share ≥ 0.7.

## Reproduction (same phantom generator, `morph_phantoms._tube`, radius 1.2 mm, length 18 mm)
| voxels (mm) | tube axis | voxels | slices occupied | local share (tube / sheet) | median local thickness |
|---|---|---|---|---|---|
| 0.5 × 0.5 × **2.0** | **x (in-plane)** | 152 | **2** | **0.00 / 1.00** | 1.0 mm |
| 0.5 × 0.5 × 2.0 | z (through-plane) | 160 | 10 | 1.00 / 0.00 | 2.0 mm |
| 0.5 × 0.5 × 1.5 | x | 312 | 2 | 1.00 / 0.00 | 2.0 mm |
| 0.5 × 0.5 × 1.0 | x | 320 | 2 | 1.00 / 0.00 | 2.0 mm |
| 0.8 × 0.8 × 1.2 | x | 96 | 2 | 1.00 / 0.00 | 1.6 mm |

## Cause
1. A 2.4 mm-diameter tube lying in the slice plane is sampled by **two 2-mm slices**. Its voxelised cross-section is about 2.4 mm wide (in-plane, ~5 voxels) by 4 mm tall (2 × 2 mm). The round cross-section cannot be represented at this slice thickness.
2. The local thickness, read across the two slices, is 1.0 mm. That is thinner than the 2.4 mm in-plane width, so the shortest direction of the sampled object is no longer its true cross-section.
3. The classifier labels a voxel "sheet" when the neighbourhood is thin in one direction and wide in the other two. Here it is thin along y/z (two slices) and long along x, but the 2-slice stack is read as one thin direction plus two wide ones. Result: 100 % sheet.
4. **The classifier has no "cannot resolve" outcome for structures spanning ≤ 2 voxels of the coarsest axis.** It returns a confident label where the data cannot support one. This matches the earlier v5.12 audit (bias towards "sheet"; weak resolvability gate).

## Why it passed before
Before the v5.13 phantom-scale fix (B1), the generator produced 0.4 mm voxels when asked for 0.5 mm. The phantom was effectively sampled more finely, so the tube was resolved. The earlier PASS was an artefact of the generator bug, not evidence that the classifier works at 2 mm slices.

## Impact
| Component | Affected? |
|---|---|
| detect_css / rules / score_css / 0–4 score | **no**: css_morph3d is not used by detection |
| unified score (x1–x5, detectors) | **no**: it uses its own coordinate-PCA definitions. For this geometry, x4 sees an elongated object (axis ratio ≫ 2.25, "line") |
| 3-D viewer "Local shape" colouring and percentages | **yes**: on thick-slice scans (≥ 2 mm, e.g. the 1.5 T 3 mm cohort M01/05/11/12/13) in-plane tubes (veins) can be shown as "sheet" with false confidence |

## Implemented resolution-confidence design (cycle 2)
**Status:** implemented in `scripts/css_morph3d.py` (`local_shape`, `sampling_width`, `axis_extent_mm`, `samples_across`). The 3-D viewer only; detection is unaffected.

### Principle
A local shape class is claimed only when every direction it depends on is sampled by **more than two grid samples across the structure**. Two samples cannot tell a width ≤ w from one up to 2w, so round and flat can't be distinguished.

### Steps, for every voxel neighbourhood
1. **Principal axes.** PCA of the neighbourhood coordinates (mm) gives spreads s1 ≥ s2 ≥ s3 and axes e1, e2, e3.
2. **Sampling interval along each axis.** w(e) = Σ|eᵢ|·vᵢ, the voxel box projected on that axis.
   - It uses the actual anisotropic voxel, so oblique structures are judged on their own axes.
   - It is continuous under small rotations.
3. **Physical extent along each axis.** Span of the voxel-centre projections plus min(largest gap between consecutive projections, w).
   - Axis-aligned: span + w.
   - Oblique: about the span, because the lattice projects densely and the centres already reach the boundary.
   - Physical dimensions are used, not voxel counts, and not the sd (an sd-based count under-states centre-heavy disc profiles).
4. **Samples across.** k = extent / w.
5. **Geometric candidate.** The original v5.12 rules give tube, sheet or blob.
6. **Gate.** The directions each class depends on must reach k ≥ 2.2 (more than two samples, with 0.2 margin for discretisation):
   - tube needs e2 and e3 (the cross-section shape);
   - blob needs e1, e2 and e3;
   - sheet needs e1 and e2 (in-plane extent).

   **Genuine sheet versus unresolved tube:** a sheet's thickness e3 may be below resolution, but only if its width along e2 is at least 2× the thickness the sampling along e3 could hide (k3·w3). A tube seen in one coarse slice fails this, a real sheet passes.
7. **When the gate fails, the result is indeterminate, never a confident class:**
   - **acquisition-limited** when an unresolved direction is sampled ≥ 1.5× more coarsely than the finest voxel side (the slice geometry prevents the decision);
   - otherwise **unresolved** (the structure is too small for the grid).

### Display and summary
- The viewer shows the two new classes in their own colours, in the voxel readout and in the share bars, and prints the rule.
- The summary says "local shape NOT resolvable for N % of voxels because of …; no tube / sheet / blob claim".
- The reliability level drops (≥ 20 % indeterminate gives a note; ≥ 50 % gives "low").
- The curve skeleton is shown for clearly elongated objects whose cross-section is tube-like or indeterminate, never for sheets.

### Iterations, all on synthetic geometry (documented, not hidden)
1. **sd-based sample count:** called a 2.4 mm tube at 1 mm voxels "unresolved", because a disc profile is centre-heavy. Replaced by a span-based count.
2. **Projected-gap extent:** unstable under tiny rotations of nearly aligned axes. Replaced by a box-projection interval.
3. **Box-union extent:** double-counted on oblique axes (oblique 4 mm tubes at 2–3 mm slices were called "tube"). Replaced by span + min(largest gap, w).
4. **Sheet rule:** a 4 mm tube lying flat in one 3 mm slice was called "sheet". This led to the flatness requirement.

The thresholds were not tuned to the cylinder test. The 2.2-sample limit follows from the two-sample argument, and the factors 1.5 and 2.0 are stated design choices.

### Results
- **New matrix** (`tests/check_morph3d_resolution.py`):
  - shapes: tubes r = 2.0 / 0.6 mm, sheets 1 mm thick, blobs r = 3.0 / 1.0 mm;
  - orientations: x, y, z, oblique xy / xz, 3-D oblique;
  - voxels: 0.5 iso, 0.5×0.5×1, 0.5×0.5×2, 0.5×0.5×3, 1 iso.

  The expected outcome comes from physics, independently of the classifier: nominal samples k = width / worst sampling interval.

  | Physics expectation | Cases | Required | Result |
  |---|---|---|---|
  | resolved (k ≥ 3.5) | 41 | correct class ≥ 0.7, wrong ≤ 0.1 | all pass |
  | unresolved (k ≤ 2) | 29 | confident classes ≤ 0.2 | all pass |
  | grey zone, including structures fragmented by sampling | 15 | never the wrong class | all pass |
  | not representable (the structure vanishes under sampling) | 15 | reported, counted neither as pass nor fail | — |

  Per-case values are in `docs/gui_v514/morph3d_resolution_matrix.csv`.
- **`tests/check_morph3d.py`:** all pass.
  - The original failing check now requires "NOT sheet, acquisition-limited ≥ 0.7" for the 2.4 mm in-plane tube at 0.5 × 0.5 × 2 mm. It is now acquisition-limited (before: 100 % sheet).
  - The default phantom tubes (2.0 mm at 0.8 × 0.8 × 1.2 mm) render about two voxels across (e.g. a 2 × 2 cross-section). Their checks now require "tube OR indeterminate, never sheet / blob", stated in the file.
  - New resolved versions (r = 2.0 mm) must still be tube ≥ 0.7.
- **`tests/check_morph3d_api.py` (PH6 phantom, inside run_tests.sh):**
  - It **FAILED on the first full run** of this cycle: vein #6 "tube 0.0". The detected vein object is 0.8 mm thick and spans about 1.8 × 1.2 samples (0.8 × 0.8 × 1.2 mm voxels), below the two-sample limit, so it is 82 % "unresolved".
  - Expectation changed in the file to "tube or not resolvable ≥ 0.6, never sheet". The cSS sheets in PH6 still pass as confident sheets.
  - The failing log is kept: `docs/gui_v514/cycle2/TEST_run_tests_attempt1_FAILED_morph3d_api.txt`.
  - The branching tube's junction reads partly sheet-like because a Y-shaped neighbourhood is genuinely planar. This is not a resolution issue; it is checked as "no worse than before" (≤ 0.33, the previous classifier's value) and listed as a known limitation.

### Consequence for real data
- Thin veins and cSS (≤ about 2 voxels across), and in-plane structures on thick-slice scans (the 1.5 T 3 mm cohort), will now often read **unresolved / acquisition-limited** in the 3-D viewer instead of a confident tube / sheet label. That is the intended, honest behaviour.
- The unified score's predictors do not use this classifier.
