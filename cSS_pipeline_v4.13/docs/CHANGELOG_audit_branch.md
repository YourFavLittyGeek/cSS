# Branch fix/audit-v5.7-priority1 (research software; expert review required)

Plan and verdicts: docs/AUDIT_IMPLEMENTATION_PLAN_v5.7.md. Every default output is unchanged (existing columns identical); all new behaviour is opt-in or read-only.

## Phase 0 - freeze statement + manifest
- detect_css.py: comment block at the rule constants stating that the thresholds fitted on M02-M11 are FROZEN (no tightening, new rules only as opt-in switches,
  judged once on M12-M15 + M01).
- review/ID_manifest.json > detect > parameters now records `frozen_rules` (31 thresholds incl. E12-E25, gates, merge) and `switches` (CSS_V53, CSS_USE_MIMIC,
  CSS_MIXED_REVIEW, CSS_QC_STRICT, CSS_KEEP_ALL, CSS_SATO_LEGACY, CSS_RANK, CSS_ALLOW_ORIENT, CSS_SURFACE_ZONE, CSS_SOFT_GATES, CSS_3D_SEEDS) on every run (test: check_v53).

## Phase 1 - F1 tested, not assumed (read-only)
- scripts/pial_compare.py: mesh-based (surface_features.py, surf_normal_dist_mm) vs mask-based (pial_dist_mm) signed pial distance per object: Pearson r,
  bias, spread, 90th percentile of |difference|, objects on different sides of the surface, difference in sulci vs on crowns, and the AUC of each distance for
  cSS vs not-cSS (adjudication.csv replaces the reads) with a bootstrap interval of the AUC difference and a plain verdict. Test: constructed answer
  (tests/check_pial_compare.py). CSS_SURFACE_ZONE is NOT implemented: replacing the search zone would repeat v5.3.0; it is justified only if this comparison
  shows a clear mesh gain.

## Phase 2 - soft generation gates (F4), CSS_SOFT_GATES=1
- Objects failing G1 volume / G2 slices / G3 elongation are shown as the LAST candidates: column soft_gate_fail (= the gate id; empty otherwise), review
  priority tier 4 with the reason, work/ID_soft_gate.csv (gate, measured value, threshold). Objects under 5 voxels (G0_tiny) and G4 (no cortex label) stay hard drops.
- Deviation from the plan: they are NOT also written to ID_dropped.csv (an object has exactly one fate; the fate invariant would be violated).
- Cost, measured on the PH3 phantom: 4 normal candidates + 30 gate-failing specks = 34 to read. On real cases this is the reader-workload price of the mode.
- review/ID_rule_audit.csv is ALWAYS written: per exclusion rule the number of excluded objects and, when ID_calls.csv exists, how many of them were called cSS
  (fingerprint match).
- Test (check_v53): OFF = unchanged; ON = normal candidates keep order and values, added objects last with tier >= 4, fate invariant holds.

## Phase 3 - orientation (F2): measured, then a recorded-only 3-D path
- Measured first (tests/check_sheet3d.py, synthetic dark sheet 24 x 24 mm, 1.6 mm thick, 0.8 mm voxels): the detector's 2-D axial Sato filter responds 0.000 to a
  sheet PARALLEL to the slices, 0.35 at 45 degrees and 0.27 perpendicular (min/max 0.00); the new 3-D plate-ness filter responds 0.27 / 0.32 / 0.27 (min/max 0.85) and
  recovers the orientation (0 / 45 / 90 degrees). A tube keeps about 0.4 of the sheet response (suppressed ~2x, not removed), a blob 0.05.
- scripts/css_sheet3d.py: scale-normalised dark-sheet measure from the 3-D Hessian (sigmas 0.6 / 1.2 / 1.8 mm) and the sheet orientation.
- detect_css.py, **CSS_3D_SEEDS=1 (default OFF, recorded only)**: same image, same zone, same darkness thresholds, same hysteresis percentiles (85 / 80 of the
  shell) and per-hemisphere hysteresis give work/ID_gen_3d.nii.gz (bits as ID_gen: 8 z<-2, 16 z<-2.5, 32 plate>weak pct, 64 plate>strong pct, 128 kept) and
  work/ID_3d_only.csv (3-D objects >= 25 mm3 and >= 2 slices touching no 2-D object: centroid, hemisphere, nearest cortex label, plate-ness, sheet angle);
  the manifest (detect > parameters > seeds3d) records the overlap statistics. Nothing shown or excluded changes (test: candidates identical on / off).
  A union with the 2-D seeds is NOT implemented: judge the overlap first (PH3 phantom: 488 3-D objects vs 247 2-D, 89 % of the 2-D object voxels covered, 55 3-D-only).
- Always recorded (appended columns, default output otherwise unchanged): axis_angle_deg (long axis vs the axial plane), sheet3d_med and sheet3d_overlap (empty
  unless CSS_3D_SEEDS=1) so later analysis can stratify detection and the reader's calls by orientation. shape_probe.py has the same angle for the real cases.

## Phase 4 - comparison tooling
- scripts/run_experiment.py: runs detect_css.py with chosen switches on COPIES (hard links) of the studies into experiments/<name>/; the project is untouched;
  EXPERIMENT.json records studies, switches, build id.
- scripts/compare_pipelines.py A B IDS: follows every object of A (shown, excluded, gate-dropped) into B by voxel overlap (same / lost / gained / still out / only_B) and
  attaches the reader's calls (the project's reads + adjudication.csv): objects called cSS LOST or GAINED, shown non-cSS removed per B rule, soft-gate objects by gate,
  per-study counts. "main" = the project. Test: tests/check_compare_pipelines.py (A vs A all same; A vs B on the phantom: 4 shown unchanged, 30 gate-dropped objects shown
  as soft-gate objects, 0 cSS lost, project files untouched).
- docs/HOW_TO_audit_experiments.md: how to run the surface / soft-gate / 3-D experiments on the Mac.

## Definition of done (branch)
All new behaviour is opt-in or read-only; with every switch off the existing columns of the candidate and excluded lists keep identical values; thresholds are frozen and
recorded in the manifest; comparison tooling exists; tests/run_tests.sh passes. Merge into a release only after the held-out evaluation (M12-M15 + M01, adjudicated labels).
