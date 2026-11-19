# 3-D morphology viewer: technical design (v5.12, branch `experimental/3d-morphology-viewer`)

Read-only research tool. It never changes the candidate list, the detector output, the reader's calls or the score.
Detection logic (`detect_css.py`, `score_css.py`, rules, thresholds) is **not modified**.

## Files

| Path | Status | Role |
|---|---|---|
| `scripts/css_morph3d.py` | new | morphology module: measurements on one candidate mask (+ optional SWI, pial distance, cortex, vessel map) |
| `scripts/morph3d_view.js` | new | WebGL 1 viewer (no libraries), served at `/morph3d.js` |
| `scripts/review_web.py` | modified | `Study.morph3d()` (candidate-local crop, cache) + `GET /api/morph3d`, `GET /morph3d.js` |
| `scripts/review_web.html` | modified | "Open 3-D analysis ▸" (3-D card), View › 3-D analysis…, the analysis window (controls, measurements, cross-section strip), MRI ↔ 3-D sync |
| `tests/morph_phantoms.py` | new | 11 synthetic shapes drawn at 0.2 mm and averaged onto the voxel grid (partial volume) |
| `tests/check_morph3d.py` | new | validation of the module on the phantoms (`--report` writes the CSV + figure) |
| `tests/check_morph3d_api.py` | new | the server endpoint on the PH6 phantom: truth-matched candidates, files unchanged |
| `tests/run_tests.sh` | modified | runs both checks |
| `reports/*.md`, `reports/img/*`, `reports/morph3d_phantoms.csv` | new | the four reports, figures, feature table, numbers |

## Data flow

1. The reviewer asks `GET /api/morph3d?study=ID&cand=N&margin=8`.
2. `Study.morph3d` takes `Study.lab == N` (the **original** candidate label on the canonical RAS+ grid, exactly what the
   detector wrote), crops its bounding box + margin (mm → voxels per axis), and copies the crops of the SWI,
   `work/ID_pial_sd`, `work/ID_seg_swispace` (cortex), `work/ID_vessels` and `work/ID_dark`. The full volumes are loaded
   once per study; every later call works on the crop only. Results are cached per (candidate, margin).
3. `css_morph3d.analyse()` measures the candidate (see `3D_MORPHOLOGY_FEATURES.md`).
4. The JSON carries **every** candidate voxel (no subsampling): canonical index, mm position relative to the centroid,
   piece id, local class, thickness, spreads, Hessian eigenvalues / class, cross-section index; the display mesh; vessel,
   cortex and nearby-dark meshes; skeleton / branch points; footprint and contact points; three orthogonal MRI planes
   through the centroid (8-bit, window p1–p99 of the crop).

## Geometry and coordinates

- Canonical RAS+ grid (`nib.as_closest_canonical`), physical voxel size per axis; every position is index × voxel size, so
  anisotropic voxels are drawn and measured at their true size (voxel boxes are 0.8 × 0.8 × 1.2 mm, not cubes).
- Origin of the 3-D scene = candidate centroid; axes x = right, y = anterior, z = superior; camera presets R L A P S I.
- 3-D → MRI: a click picks the nearest candidate voxel on screen and sets the reviewer's cursor (`cur`, canonical index) –
  the three planes jump there. MRI → 3-D: every reviewer redraw moves a yellow cross to `cur` in the 3-D scene.

## Surface reconstruction

- Marching cubes (scikit-image, level 0.5, `spacing = voxel size`) on a padded **copy** of the mask.
- Display mesh: Taubin smoothing (λ 0.5 / μ −0.53, 8 iterations) — low-pass without the shrinkage of Laplacian smoothing.
  Fidelity is checked on every candidate: `smoothing_volume_change_pct` (mesh volume after vs before smoothing). Phantoms:
  |change| ≤ 12 % in the tests, typically 1–6 %.
- The **original voxels** are always available ("Voxels" / "Both"): one box per voxel at the true voxel size.
- Measurements use the voxel mask and the unsmoothed surface, never the smoothed display mesh.

## Viewer

- Modes: **Isolated** (candidate only, centred and fitted; first view along the thinnest principal axis so a sheet is face-on
  and a tube side-on) and **Anatomical context** (vessel map, cortical surface (8 % opacity), MRI axial plane).
- Context layers are translucent and drawn last with depth writes off: they never hide the candidate.
- Colour by local shape (tube blue, sheet orange, blob purple, uncertain grey), image Hessian (same palette, separate source),
  thickness (p10–p90 ramp), piece, plain.
- Layers (independent): vessel map, other dark structures, cortical surface, MRI axial / coronal / sagittal planes, contact
  with vessels, cortical footprint, skeleton (only when reliable), principal axes. Pieces can be shown individually.
- Cross-section strip: equivalent diameter per slab along the first principal axis (bars) and thickness along the skeleton
  (line); a click highlights that slab's voxels in white and lists area, diameter, major / minor axis, eccentricity.
- Validation (blind) read: the interpretation (local-shape colours, shares, summary) is hidden; measurements stay.

## Performance

Candidate-local crops only (PH6: 0.2–0.7 s per candidate, 0.7–1.2 MB JSON, cached). The full SWI is read once per study.
