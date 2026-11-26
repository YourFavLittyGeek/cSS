# IMAGE_PIPELINE_DESIGN.md - from SWI volume to candidate tensor (design, not implemented)

## 1. Stages

```
ImageRecord index -> geometry gate -> channel alignment check -> patch extraction (surface frame + native stack)
   -> intensity normalisation -> validity / quality flags -> (training only) augmentation -> tensor + metadata
```
Every stage is a pure function of (files, their sha256, parameters) and writes only into
`$CSS_BASE/unified_engine/` (image_index/, patches/ ; never review/, labels/, work/, data/).

## 2. Geometry gate (refuse, never guess)

| check | rule | on failure |
|---|---|---|
| header | qform or sform code > 0; affine finite, determinant != 0 | `geometry_refused` |
| slice axis | the detector's rule: array axis 2 is the S-I axis and the thickest | `geometry_refused` (the detector stops anyway) |
| voxel size | in-plane <= 1.0 mm, slice <= 3.0 mm (2026-11-26 user decision, was 2.5; tolerance 0.01 mm for header rounding) | `quality_refused`, reported |
| channel grid | FLAIR / labels / phase on the SWI grid (shape + affine within 1e-4 mm) | channel absent, not resampled silently |
| freshness | channel not older than the SWI | channel absent (existing `stale_against`) |
| registration | `bbregister` cost from the LTA chain below a threshold (to be set on synthetic misregistration tests; css_qc already records it) | channel absent + `low_confidence_review` |
| normal | pial normal sign checked against the labels (tissue on -n), flipped and recorded | recorded |

World coordinates are RAS mm through the image's own affine; the surface frame and all sampling use the affine (as
`surface_aligned_patch.extract_patch` already does), so oblique and LAS/RAS storage give the same physical patch.
A synthetic test rotates / flips / reorients the same phantom and requires identical patches (tolerance 1e-4).

## 3. Surface-aligned patch (existing `css-patch/1.0`, kept)

24 (u, along) x 12 (v, across) x 8 (n, normal) mm at 0.5 mm, centred on the object, channels swi / phase / flair /
labels, linear interpolation (nearest for labels), NaN + invalid outside image or brain. Rationale: cSS is a band
following the cortex; veins are tubes in CSF or crossing the cortex. The frame turns that into a fixed axis (n) and
makes left/right, orientation and slice direction irrelevant.

## 4. Native 2.5D stack (NEW in css-patch/2.0)

The 0.5 mm surface frame interpolates through 1.2-2 mm slices. To expose what was actually acquired, add a native
stack: the candidate's axial slices (centre slice +-2, so 5 slices) cropped 32 x 32 mm at native in-plane spacing,
then resampled in-plane only to 0.5 mm. No through-plane interpolation. Both representations are produced; the
model card states which one a model used.

## 5. Intensity normalisation

SWI magnitude is not quantitative and varies by vendor / TE. Per study: robust z relative to the local cortex, exactly
as the detector's darkness z (local cortex mean, sigma 10 mm, cortical MAD) so the image stream and MATH share a
scale but the image stream sees the spatial pattern instead of a summary. Phase: homodyne high-pass (`make_swi.py`
filter), sign convention recorded (paramagnetic negative / positive per vendor; unknown -> phase channel absent).
FLAIR: robust z within brain. No statistics are pooled across studies at inference.

## 6. Image-derived features for option A (extends `classify_surface_patches.py features`)

Per channel: validity fraction; robust-z quantiles inside the object and in shells; profiles along n (subpial vs
CSF position), along v (band width: sheet vs tube), along u (continuity); gradient means; NEW: tram-track symmetry
(both banks dark), extent across the surface at n = 0, tubularity in the native stack (Hessian eigenvalue ratio per
slice), slice-to-slice persistence, blooming estimate, phase sign agreement (paramagnetic), FLAIR brightness of the
sulcus (cSAH mimic). Each feature has a `<ch>_missing` indicator. Features that duplicate MATH inputs (darkness_z,
tube_ratio, pial_dist_mm, tram_frac, elongation) are flagged `overlap_with_math`; redundancy is handled by the offset
fusion and tested by ablation (MODEL_EVALUATION_PLAN section 4).

## 7. Option B tensor (only if the gate in ARCHITECTURE_DESIGN section 3 opens)

Input [C, 16, 48, 24] surface patch or [C x 5, 64, 64] native stack, validity channels concatenated, invalid voxels
set to 0 AFTER normalisation with the mask channel present. Network: 3-4 conv blocks, <= 100k parameters, global
pooling, dropout; 5-seed ensemble; output one logit used as the image increment. Augmentation (training only,
physically plausible): rotation about n, flips along u (cSS and veins are symmetric along the band), +-15 %
intensity scale, Gaussian noise matched to the study's MAD, simulated slice thickness 1.0-2.0 mm, simulated
misregistration of FLAIR 0-2 mm. Never: flips along n (would swap tissue and CSF).

## 8. Synthetic data for development (allowed now)

Generators: `tests/phantom_v4.py` (truth cSS tram-track / convexity / single bank; sulcal, surface and transcortical
veins), `phantom_surfvein.py` (surface vein with branch into a sinus), `morph_phantoms.py` (partial volume). Planned
extension (Stage 2 implementation, after approval): a parametric generator with acquisition variability (voxel size,
noise, bias field, blooming by TE, vendor phase sign), each object's truth class and subtype, plus label noise
(reader error matrix), indeterminate and insufficient-quality cases. `scripts/make_synthetic.py` is NOT used: it
needs a real host image.

## 9. Failure behaviour

Any refusal makes the image stream `available = false` for that candidate or study; the fusion then uses M + C only
and the category rules apply (uncertain when the image stream is the only one disagreeing). The pipeline never
substitutes zeros for missing channels and never resamples a channel silently.
