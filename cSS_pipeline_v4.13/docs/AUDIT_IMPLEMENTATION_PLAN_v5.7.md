# Audit implementation plan (branch fix/audit-v5.7-priority1) - research software; expert review required

Source: the independent audit's findings F1-F4 as summarised in the branch plan (F3 = thresholds fitted on the development set; F1 = mask-based pial
distance; F2 = orientation-dependent 2-D detection; F4 = hard generation gates). This file records what was checked against the code and the reads
of M02-M11, what is built on this branch, and what was changed from the plan. Nothing on this branch changes a default output.

## Checked against the code and the data
| Finding | Verdict | Evidence |
|---|---|---|
| F3 thresholds fitted on one reader / 10 patients | **Correct** | E12-E25 set on M02-M11; repeat-read kappa 0.65 (meter visible) / 0.87 (hidden) |
| F1 mask-based pial distance | **Plausible, unquantified** | `pial_sd` = signed EDT of the label mask (voxel resolution). A mesh-based signed distance per object already exists (`surface_features.py`, surf_normal_dist_mm, recorded only). No read shows an error caused by it. Replacing the search zone would repeat v5.3.0 (zone change shifted thresholds, lost 3 cSS) |
| F2 2-D axial ridge | **Correct as a design limit, no evidence of loss** | per-slice `sato` in detect_css.py; 0 missed cSS marked in all five studies of the blind read; `shape_probe.py` now records axis_angle_deg |
| F4 hard generation gates | **Correct, small effect now** | gates cost 3 cSS in v5.3.1; ID_dropped.csv already logs every gate failure; 0 missed marks |

## Changes made to the plan
1. "Bit-identical default output" is read as: every existing column keeps identical values; appended columns and the manifest may grow.
2. Phase 1 is **recorded-only**: no change to the search zone (`CSS_SURFACE_ZONE` is NOT implemented). The question F1 raises is answered first with a read-only
   comparison of the mesh distance with the mask distance (`pial_compare.py`) on the recon-all cases.
3. New rules asked for by the reader (E22, E24, E25, blob, straight-in-sulcus) remain, but are opt-in, are fitted offline with the margin to the nearest called
   cSS reported, and are judged once on M12-M15 + M01.
4. The plan does not address the main false-positive source (cortical-surface objects: microbleed blobs, straight sulcal veins); that is the shape-probe track
   (docs/CHANGELOG_v5.7.md). Soft gates and 3-D seeds ADD candidates (reader workload): both stay optional and recorded-only first.

## Phases
| Phase | Content | Status |
|---|---|---|
| 0 | freeze statement at the top of the rule constants in detect_css.py; manifest records all thresholds + the experimental switches on every run; this document | done |
| 1 | `pial_compare.py` (read-only): mesh vs mask pial distance per object, bias / spread / sign disagreement / sulcal-depth dependence, and which of the two separates cSS from not-cSS better (AUC) | done; run on the Mac (HOW_TO) |
| 2 | soft generation gates, `CSS_SOFT_GATES=1`: gate failures also written to the candidates table with `soft_gate_fail` and lowest priority; per-rule exclusion audit table always written | done |
| 3 | recorded-only 3-D sheetness seeds, `CSS_3D_SEEDS=1` (work/ID_gen_3d.nii.gz, ID_3d_only.csv, overlap statistics in the manifest, axis_angle_deg column) | done |
| 4 | run_experiment.py + compare_pipelines.py (two runs at object level), changelog, how-to (docs/HOW_TO_audit_experiments.md) | done |

## Out of scope on this branch
Re-fitting any threshold on M02-M11; changing the default search zone or default rules; replacing the 2-D detector; a classifier; any claim of better
sensitivity or specificity before the held-out evaluation.
