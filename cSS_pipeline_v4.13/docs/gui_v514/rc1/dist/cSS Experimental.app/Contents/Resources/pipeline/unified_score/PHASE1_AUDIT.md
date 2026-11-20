# Phase 1 audit: unified cSS candidate score (read-only; no code changed)

- Repository state: branch `experimental/morphology-v513` (from `d7af64a`), with the v5.13 morphology work uncommitted.
- Detection, scoring and candidate generation were only read, not changed.
- The detector writes 157 columns per candidate (`review/ID_candidates.csv`); excluded objects go to `ID_excluded.csv`.

## 1. What already exists that overlaps this brief (important)

| Component | File | What it is | Status |
|---|---|---|---|
| Confidence model | `css_confidence.py`, `fit_confidence.py`, `eval_confidence.py` | v5.10: one class-balanced L2 logistic regression over 7 evidence domains (location, form, surface, course, minIP, darkness, size); `confidence_pct` column; per-object explanation | fitted on the user's M02–M11 calls **on the Mac** (not in this container); the cut uses `lopo_min`; refuses evaluation studies |
| Exclusion by confidence | `detect_css.py` rule **E30** | excludes objects below the confidence cut | **opt-in only** (`CSS_CONF=1`); the app runs with `CSS_CONF=1` (`PIPE_ENV`), so it is active in the app if a model file exists |
| Ranker | `train_ranker.py`, `rank_candidates.py`, `css_model.py` | L2 LR, nested leave-one-patient-out, PR-AUC / Brier / sens@FP, model card, refuses test studies | needs `labels/` (expert labels) |
| Review tiers | `css_tiers.py` | reading order 1–5 | placeholders fitted to phantoms |
| Labels | `expert_sheet.py`, `expert_import.py`, `consensus.py`, `study_meta.py`, `label_missed.py` | fine codes (C, V/VS/VC/VT/VX, A, N, MB, …), confidence 1–5, dev/test split, two-reader consensus with kappa | infrastructure exists; **real labels exist only on the user's Mac** (M02–M11 reader calls, 287 read candidates) |
| Evaluation | `evaluate.py` | patient-grouped, FROC, top-k, patient bootstrap CIs, default split = test | ready |

**Consequence:** the brief should **extend and re-validate** the v5.10 confidence model, not build a parallel one.
Two concerns need an answer before Phase 4:

1. E30 is a single-threshold exclusion on a cSS score. That is exactly what the brief forbids ("do not suppress on
   low cSS probability alone").
2. E30 may already be active in the app.

## 2. Labels and data available

| Data | Where | Usable for | Leakage status |
|---|---|---|---|
| M02–M11 reader calls (287 read; 61 cSS, 78 artifact, 114 normal, rest vessel / other) | user's Mac, `review/*_calls*.csv` | development | **used to set v5.3 rules E12–E24 and the v5.10 model**: development only |
| M12–M15, M01 | user's Mac | held-out test (declared untouched in v5.3) | status must be checked: were they read, and did any rule see them? |
| M16–M26 (new batch) | user's Mac; radiologist grades per patient, no candidate labels yet | a genuinely new held-out cohort once candidates are expert-labelled | clean |
| P006 (6 known cSS), P010 / P011 (negatives), LEMON P201–P204 (presumed negative) | user's Mac | development / negative controls | used throughout development |
| PH1–PH7, PH6, synthetic shapes, v5.13 blooming phantoms | this container | software and mechanism tests | **not independent validation** (they shaped features and rules) |
| Expert (radiologist) candidate-level labels | not available yet | required for the model and for any suppression threshold | – |

**No candidate-level expert labels exist in this container.** A learned model, calibration and a safe exclusion threshold
can only be produced on the user's Mac with the labelled cohorts. Here the code can be built and tested mechanically
on synthetic labels; the numbers must not be reported as performance.

## 3. Feature inventory (brief groups A–I)

Reliability: **H** = physically well defined, stable in tests; **M** = defined but sensitive to resolution or registration;
**L** = known failures (audit / v5.13).

| Group | Feature (existing columns) | New implementation needed | Reliability | Limitations |
|---|---|---|---|---|
| A Location | `cortex_frac`, `cortex_dist_mm`, `pial_dist_mm`, `pial_sd_p10/p90`, `rel_height`, `infra_frac`, `basal_frac`, `midline_frac`, `skullbase_frac`, `sylvian_frac`, `zone2_frac`, `vent_frac`, `out_frac`, `region` (aparc), `hemi` | lobe from aparc; sulcal bank / fundus / crown position from `sulcal_depth_mm` + Destrieux (recon-all only); context ± 1-voxel ranges (v5.13) | M | depends on registration (± 1 voxel moved CSF 0 → 42 % in v5.13); SWI-only route coarse; E-rules already hard-exclude some zones (E1–E24) |
| B Signal | `darkness_z`, `darkness_z_p10`, `dark_frac_z2/3/4`, `edge_contrast`, `region_z`, `region_dark_frac`, `dark_cv`, `dark_gap_frac`, `minip_len_mm`, `minip_cont`, `mirror_*` | dark core / blooming decomposition (v5.13: `core_*` volume, thickness, unstable fraction); cross-slice continuity; multi-scale contrast | M | darkness is a weak discriminator on real data (v3 AUC 0.37–0.53); region_z overlaps cSS / normal (v4.19.2); the core keeps ~35 % of blooming |
| C Vessel | `vessel_wm_mm`, `vessel_run_mm`, `vessel_ext_mm`, `axis_normal`, `local_cont_*`, `cand_geodesic_mm`, `terminal_ends`, `local_branch_*`, `end_type_*`, `vein_like`, `vein_evidence`, `piece_vein_frac`, `mixed_object`, `net_radius_*`, struct `struct_cont` | explicit split into proximity (distance), contact (touching voxels), overlap (% in vessel map), continuity (vessel passes through: enters + exits), alignment (axis · vessel direction) | M | the vessel map is a Hessian product (tubes only); vein_tree merges brain-wide (deprecated); a cSS next to a vein reads "runs on" (v4.18, untested on real data) |
| D Morphology | `elongation`, `extent_mm`, `n_slices`, `single_slice`, `elongation_3d`, `flatness_3d`, `sphericity`, `compactness_3d`, `path_length_mm`, `tortuosity`, `struct_s1/s2/s3`, `struct_thick_mm`, `struct_cls`, `sheet3d_*`, `piece_sheet`, `cand_radius_*`, `n_pieces`, `cmb_like` | resolvability status (v5.13, needs redesign); thickness / volume of the core; morphology as "unresolved" rather than missing | **L** | audit + v5.13: no tube / sheet method works on blooming phantoms; struct_* uses the 20 mm regrown structure (audit B8) |
| E Sulcal / cortical | `bank_frac`, `tram_frac`, `surface_alignment`, `surface_contact*`, `csf_adjacent_frac`, `sulcal_depth_mm`, `dual_contact_frac`, `struct_surf_cos`, surface_features.py `surf_*` (recon-all) | "runs along a sulcus" vs "near a sulcus": trajectory tangent vs local sulcal direction (pial-distance gradient) along the skeleton | M | recon-all features only on that route; tram_frac relies on both banks being visible |
| F Hessian | `tube_ratio`, `surface_alignment`; v5.12 per-voxel Hessian (viewer only) | per-candidate Hessian summary from the SWI (median / IQR of tube, sheet, blob responses per scale) | M | convention verified (\|λ1\| ≤ \|λ2\| ≤ \|λ3\|, dark → λ3 > 0); support up to 5 mm includes neighbours; reads blobs as tubes on the phantom |
| G Skull / artifact | `skull_frac`, `mask_edge_mm`, `skullbase_frac`, `artifact_zone`, `out_frac`, `soft_gate_fail`, `plane_dist_mm` / `cos_plane` (midline sheet), `mimic_*` (phase, FLAIR) | "dark band continues outside the brain mask" (extracranial continuation length); air–bone zone map | M | the brain mask is T1 labels + 5 mm (v5.2.5); no extracranial image is kept after masking, so outside continuation can only be measured on the unmasked SWI (`raw/`) |
| H Size | `volume_mm3`, `extent_mm`, `n_slices`, `path_length_mm`, `n_pieces`, `esd` | core vs candidate size | H (mask) / M (true size) | blooming inflates volume (~3×); slice thickness quantises |
| I Context | `ich_dist_mm`, `near_ich_suggest`, `ich_contact_frac`, `local_net_mm`, nearby candidates (not a column) | count / distance of other candidates and dark objects within N mm; segmentation-gap vs signal-gap fragmentation | L | not yet a column |

## 4. Checks of the brief's warnings against the code

- **PCA ≠ Hessian.** Confirmed separate: `elongation_3d` / `struct_*` / v5.12 local shape are coordinate geometry;
  `tube_ratio` and the v5.12 Hessian are image curvature.
- **Vessel proximity ≠ continuity.** The existing columns mix them. `vein_like` / `vein_evidence` combine reach,
  alignment and Hessian. They must be split before any vessel term can give strong negative evidence.
- **Mask ≠ deposit (blooming).** Confirmed (audit B8, v5.13): the candidate is about 2–3× the structure.
- **Pial / CSF instability.** Confirmed (v5.13 Phase 6).
- **Unresolved morphology.** The current model imputes the median when a feature is missing; it has no "unresolved"
  state. That would treat unresolved morphology as average evidence, not as absent evidence.

## 5. Decisions needed from the user before Phase 2

1. Extend the existing v5.10 confidence model (recommended) or build a separate model?
2. Is E30 (`CSS_CONF=1`) active in the app at the moment (is there a `review/confidence_model.json` on the Mac)? The
   brief's suppression design would replace E30's single-threshold exclusion with the two-outcome design, in shadow
   mode first.
3. Which cohorts are development and which are held-out? Proposed: M02–M11 + P006 development; M12–M15, M01 and the new
   M16–M26 held-out, only once they have candidate-level expert labels.
4. The rest of the brief (Phase 6 onward) did not arrive.
