# v5.13 morphology: rules and constants declared BEFORE any test was run

Written before `css_morph3d_v2.py` was run on any shape. Any later change is listed in `CHANGES_AFTER_TESTING.md` with its
reason. Constants come from physics or sampling arguments, or are round defaults; none was fitted to data.

## Phase 1 fixes
- B6: the voxel length subtracted from 2·EDT is the **box chord** along the direction u to the nearest background voxel:
  chord = min_i v_i / |u_i| (the length of a voxel crossed along u).
- B10: skeleton length = total edge length (mm) of the minimum spanning tree of the 26-connected skeleton voxel graph
  (edge weight = physical distance). No caps.
- B11: reliability is replaced by a resolvability assessment (Phase 4).
- B12: no adjectives such as "follows / partly on the surface"; the summary lists the measured numbers.

## Phase 2: candidate decomposition (dark core / blooming-support / adjacent)
- Background: shell 2–5 mm outside the candidate. Voxels darker than median − 2·MAD·1.4826 are removed once (other dark
  structures). Background level μ_b = median, spread σ_b = 1.4826·MAD.
- Darkness in noise units: c(v) = (μ_b − I(v)) / σ_b.
- Local peak: c_peak(v) = maximum of c within 2 mm of v.
- **Dark core** = voxels of the candidate dilated by 1 voxel where c(v) ≥ 0.5·c_peak(v) (half maximum: the FWHM width of a
  blurred profile), and c_peak ≥ 3 (else the voxel is "low contrast, undetermined").
- Uncertainty per voxel: unstable if membership differs at fractions 0.4 and 0.6 of c_peak, or if |c − 0.5·c_peak| < 1
  noise unit. Reported as the unstable fraction.
- **Blooming / support** = candidate voxels not in the core. Never treated as structure.
- **Adjacent dark structures** = c ≥ 3 components within the margin that touch neither candidate nor core.
- Known physical limit (stated before testing): FWHM of a blurred thin structure is ≥ ~2.355·σ_PSF, so the core cannot be
  thinner than the blur.

## Phase 3: separate morphology approaches (none combined into a score)
- A1 in-plane: per acquisition slice (slice axis = the axis with the largest voxel size; z if isotropic), 2-D components:
  area, width = 2·max 2-D EDT − in-plane chord, length = MST length of the 2-D skeleton. Descriptive only.
- A2 surface-normal tensor: marching-cubes mesh of the mask; for every voxel, the area-weighted mean of n·nᵀ of the mesh
  triangles within radius r; eigenvalues e1 ≥ e2 ≥ e3 (sum 1). Prototypes: sheet (1, 0, 0), tube (½, ½, 0),
  blob (⅓, ⅓, ⅓). Nearest prototype by Euclidean distance d1; "mixed" when d1 ≥ 0.75·d2 (d2 = second nearest).
  Scales r = 2 mm and 4 mm (A5 multi-scale = agreement of the two).
- A3 medial axis: MST skeleton (length, end points, branch points); reported only when the core is resolvable.
- A4 Hessian: the v5.12 function, unchanged, reported separately.

## Phase 4: resolvability (the gate, before any 3-D class)
- Per voxel of the analysed mask: thickness counted in voxels along each axis through the voxel (run length of the mask
  along x, y, z). A 3-D tube vs sheet decision needs ≥ 2 voxels in at least two axes OR ≥ 2 slices along the slice
  axis plus ≥ 2 voxels in-plane. Otherwise the voxel is **not resolvable (3-D)**; only in-plane (A1) description is given.
- Structure level: resolvable fraction; slices occupied; in-plane voxels across (median); anisotropy ratio; orientation
  (angle of the A2 dominant normal to the slice axis); pieces; merged (more than one core piece joined only through
  support voxels); stability = A2 label agreement after a 1-voxel erosion and dilation of the mask (fraction).
- Levels: **resolved** (resolvable ≥ 0.8 and stability ≥ 0.7), **partially resolved** (resolvable ≥ 0.3),
  **not resolvable** (otherwise). Reasons listed.
- Final descriptive label per structure: sheet- / tube-compatible / blob-like only when A2 at both scales agrees on
  ≥ 60 % of resolvable voxels and the level is not "not resolvable"; "mixed" when two classes each hold ≥ 25 %;
  otherwise "indeterminate". Never a diagnosis.

## Phase 6: context sensitivity
- Pial distance, CSF and cortex fractions are recomputed with the pial-distance map shifted by ±1 voxel along each axis;
  reported as min–max. Never used to exclude.

## Phase 5: evaluation protocol
- Development set: the 11 original shapes, the audit's adversarial cases, and blooming phantoms with seeds 0–29.
- Held-out set: blooming phantoms with seeds 1000–1199, parameter ranges written in `heldout_spec.json` BEFORE
  generation. The module and generator are frozen (sha256 in `FREEZE.json`) before the held-out set is generated or run.
