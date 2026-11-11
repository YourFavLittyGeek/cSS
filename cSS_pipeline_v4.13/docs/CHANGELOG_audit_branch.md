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

## Next
Phase 3 recorded-only 3-D sheetness seeds (CSS_3D_SEEDS=1), Phase 4 compare_pipelines.py + how-to.
