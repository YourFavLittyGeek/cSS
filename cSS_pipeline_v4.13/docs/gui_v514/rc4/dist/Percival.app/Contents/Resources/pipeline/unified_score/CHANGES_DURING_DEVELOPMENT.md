# Changes made during development (all driven by SYNTHETIC scenes; no patient data was used)

Every definition or threshold that changed after it was first written, and why. No real M study, label or reader call was read.
Synthetic scenes shaped these changes, so the adversarial results are **not independent evidence**. The scenes added after the
changes (section B) are the only partial check.

## A. Changes

| # | Component | First version | Problem seen (synthetic) | Change |
|---|---|---|---|---|
| 1 | test thresholds `check_core_decompose` | contrast k = 2–3 SD, blur 0.8 mm | 7 FAIL: recall 0.39–0.65; a sweep showed recall depends on deposit contrast (≥ ~5 noise units needed) | mechanical tests at a stated high-contrast condition; the low-contrast regime is MEASURED and printed, not asserted |
| 2 | vein detector status logic | any unresolved input → "unresolved" | fired for every candidate (even with no vessel contact), so its protective flag blocked every decision | decisive contrary evidence (no contact / no traverse) → "not_confirmed"; stability and cross-section required only when the support criteria are met |
| 3 | x4 sulcal alignment | 1 − \|PC1·n\| only | undefined for square sheets (elongation < 1.5), so most convexity cSS were "unreliable" | line: 1 − \|PC1·n\|; sheet: \|PC3·n\|; otherwise unreliable |
| 4 | protective "morphology unresolved" | tube cross-section test (both minor axes resolved) | every thin cSS sheet was flagged (sheets are thin by nature) | `shape_resolvable`: ≥ 8 voxels and the second axis ≥ 2 voxels; the tube test stays in the vein detector only |
| 5 | x1 vessel continuity zone | 1-voxel dilation, full vessel mask | vessel voxels alongside a narrower dark candidate joined both ends into one piece → no traverse | zone = within max(1.5 mm, 1 voxel); topology on the vessel CENTRELINE (distance ridge) |
| 6 | vein centreline | skimage 3-D skeletonize | returned EMPTY for even-thickness tubes (known bug in this environment) | distance-transform ridge |
| 7 | censoring (x1, x5) | censored → unreliable | a long vein reaching the 20 mm crop edge became "unreliable" | censoring is a note: the length is a lower bound |
| 8 | **dark core on masked SWI (important)** | verbatim `decompose()` on the detector's brain-masked SWI | zeros outside the mask read as maximal darkness: **623 masked voxels in the core, deposit recall 0.03** (test 10) | wrapper fills masked voxels with the valid-shell median BEFORE the verbatim function and removes them from the outputs (input preparation; the algorithm is unchanged) |
| 9 | skull-interface detector | void proximity + parallel + pial distance > 1 mm | confirmed a surface VEIN in CSF under the skull | added: band-shaped (planar, not a tube) and vessel-map overlap ≤ 0.2 |
| 10 | **skull-interface cortical criterion (critical)** | pial distance > 1.0 mm | **CRITICAL: a subarachnoid cSS band 1.3 mm off the pial surface was confirmed as an artefact and proposed for suppression** | pial distance > 3.0 mm (beyond the subarachnoid layer; consistent with production v5.3's E15 inner-skull band). The synthetic brain mask was made labels + 5 mm, as in production |
| 11 | synthetic scenes | candidate = the whole vein; extracranial band through a bone void | the scenes, not the method, prevented measurement | vein candidates bounded in y (like detector objects); a soft-tissue window through the skull for the extracranial scene. **x5 does not follow continuation ACROSS a bone void**: documented limit |

## B. Scenes added AFTER the revisions (not used to develop them)
css_subarachnoid_near_skull (found change 10, then passed), css_in_thick_csf_2.4mm, css_directly_under_skull, css_touching_sulcal_vein.
The 5-seed sweep (85 runs) gave 0 critical failures.

## C. Consequences for the v5.13 results
Change 8 matters beyond this project. If the v5.13 dark-core figures were computed on brain-masked images, candidates within ~2 mm
of the mask edge were biased. v5.13's phantoms were unmasked, so its reported numbers are probably unaffected, but it is unverified.
