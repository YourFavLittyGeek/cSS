# Percival - assessment architecture, data flow, training and evaluation (v5.23)

Research software. Everything below runs on the user's computer (see `LOCAL_AI_ARCHITECTURE.md`). Every statement about model
performance in this repository comes from **synthetic data** and says nothing about clinical accuracy (§8).

## 1. Pipeline

```
MRI import (app: Add studies)            import_wizard.py, identity.py, series_detect.py      -> raw/<ID>/SWI|T1|FLAIR (+ study library copy)
MRI processing and preparation           run_css.sh -> prep_anat.sh (recon-all / SynthSeg, bbregister), css_qc.py
                                         -> data/<ID>_swi.nii, work/<ID>_*_swispace.nii.gz, review/<ID>_qc.json (QC status)
Candidate detection                      detect_css.py -> review/<ID>_candidates.csv (+ .nii.gz label map; cand_id = rank,
                                         vox_i/j/k, measurements), excluded.csv, dropped.csv, manifest.json (input hashes)
MATH                                     score_v4 column of the candidates CSV (deterministic, §2.1)
Unified Score                            unified_score/uscore: predictors x1-x5 -> uscore/features/<ID>.json (§2.2)
Image ML / Characteristic ML / Fusion    unified_engine/uengine/percival/{learners,cnn,meta}.py (§3)
Percival Intelligence                    unified_engine/uengine/percival/{meta,intelligence}.py (§4)
Percival Score                           meta.score_rows -> unified_engine/percival/scores/<ID>.json + ledger/<ID>/<model>__<run>.json (§5)
Expert review and controlled learning    scripts/review_web.py (reviewer) -> review/<ID>_calls*.csv, _final_<reviewer>.json
                                         app/percival_gui.py snapshots + controlled training cycles + registry (§6)
```

Traceability: a candidate is identified by (study key, processing run, `cand_id`), has voxel coordinates `vox_i/j/k` in the
SWI grid, a label map in `review/<ID>_candidates.nii.gz`, and its MRI patch is extracted from that label map and the SWI
(`uengine/imaging/patches.py`, surface-aligned u/v/n frame, 0.5 mm). Re-processing keeps lineage (`lineage.py`): earlier calls move
to new candidates only on confident one-to-one matches. Patch arrays are cached per study with the source file mtimes as key.

## 2. Deterministic and structured components (audited, not changed)

### 2.1 MATH (`scripts/detect_css.py`, lines ~1028-1040)
Untrained, deterministic product of definition terms; reproducible for a fixed image and parameter set.

| Input | Measurement |
|---|---|
| `depth` | mean darkness z of the candidate voxels (cortex-referenced, MAD units), clipped at 0 and square-rooted (veins were darker than cSS on real data) |
| `pdist` | median signed distance to the pial surface (mm) -> `on_surf = exp(-((pdist + 0.5)/1.5)^2)` |
| `tub` | median 3-D Hessian tube ratio -> `sheet = 1 - tub` (0.5 if missing) |
| `aln` | median surface alignment (0.5 if missing) |
| `tram` | tram-track fraction (0 if missing) |

`score_v4 = sqrt(max(depth,0)) * (0.25+on_surf) * (0.25+sheet) * (0.5+aln) * (1+tram)`, then x0.5 artifact zone, x0.7 midline,
x0.5 long structure (> 40 mm top-to-bottom), x0.3 infratentorial, and (only with `CSS_USE_MIMIC=1` and a FLAIR mimic class) x0.5.
Missing inputs take the neutral values above. Output: a non-negative ranking score - **not** a probability. Thresholds: none
inside MATH (the review tiers and exclusion rules E1-E30 are separate). Quality limitation: SWI-only anatomy (SynthSeg on SWI)
makes `pdist` / `aln` coarse. Inside Percival, MATH enters as a two-parameter monotone Platt recalibration of `log(score_v4 + eps)`
(`ml_component.MathRecalibration`): MATH's order is never changed.

### 2.2 Unified Score (`unified_score/uscore`, v5.14)
**Hybrid**: deterministic feature extraction + learned combination.
Predictors x1 vessel continuity (mm), x2 core contrast, x3 pial distance (mm), x4 surface conformity (labelled "sulcal alignment";
see FEATURE_DICTIONARY_v514.md - it measures surface conformity), x5 extracranial continuation (mm); each has a state reliable /
unreliable / unavailable, and unreliable values contribute zero. `uscore/model.py`: ridge logistic regression, nested LOPO, inner
Platt scaling; suppression implemented but disabled; held-out labels only through the authorised route.
Percival does **not** modify this engine. Its "Unified" component (§3) re-uses the five **reliable** predictor values with its own
patient-grouped, class-balanced L2 logistic fit, so it can be stacked without leakage.
Overlap with MATH (§4.1): x3 pial distance and x4 surface conformity correspond to MATH's `pdist` and `aln`.

## 3. Learned components (level 0) - model families are compared, not assumed

All components are fitted with **patient weights** (a patient with many candidates counts at most as 20 candidates) and evaluated by
**patient-grouped 5-fold cross-validation** on the development cohort. Selection rule everywhere: the simplest model whose CV log loss
is within one patient-bootstrap standard error of the best (1-SE rule).

| Component | Input | Families compared (simplest first) | Code |
|---|---|---|---|
| Characteristic ML | 9 detector characteristics: darkness_z, edge_contrast, pial_dist_mm, cortex_frac, tram_frac, tube_ratio, elongation_3d, log volume, local_cont_max_mm | L2 logistic (nested penalty) < gradient-boosted depth-2 trees < random forest (patient bootstrap) | `learners.py` |
| Image ML | the candidate's MRI patch pixels: 3 maps (minIP and mean of SWI along the surface normal, normalised to the patch median; candidate footprint), 49 x 25 at 0.5 mm | pixel logistic on 3x7x5 block means < small CNN (conv3x3x8-pool-conv3x3x16-GAP+GMP-dense, Adam, flip augmentation, patient-held-out early stopping) | `learners.py`, `cnn.py` |
| Fusion | Characteristic + Image | late (logistic on the two log-odds) < feature-level (characteristics + image log-odds) < hybrid (both) | `meta.py` |

Image ML is a real image model (it reads patch pixels, never the feature table). The image input is 2.5-D (projections of a 3-D
surface-aligned patch); a full 3-D CNN was not chosen because of the data volume expected per project and CPU-only numpy training.
Image uncertainty: test-time augmentation (patch and its mirror) - the half-gap of the two logits is reported per candidate.
Late / hybrid fusion need out-of-sample Characteristic log-odds for their training rows: an inner patient-grouped 3-fold CV inside
each outer training fold provides them.
**Is fusion worth it?** On the candidates that have both inputs, the paired patient-bootstrap CI of the log-loss difference between
the chosen fusion and the better single model decides the verdict (improves / worse / no demonstrated improvement). Fusion is kept as
a component either way; whether the final score uses it is decided by the meta-model discovery (§5), never by assumption.

## 4. Percival Intelligence (`intelligence.py`, report stored in every model under `intelligence`)

4.1 **Provenance / redundancy**: the measurement concepts of every component, read from the code, and their pairwise Jaccard overlap
(e.g. MATH-Characteristic share darkness, pial distance, tram track, tubularity; Fusion contains all Characteristic inputs).
4.2 **Incremental value (ablation)**: CV log loss / AUC of a logistic stack on all independent components, on all-but-one and on each
alone; Δ log loss when a component is removed with a paired patient-bootstrap 95 % CI -> "adds information" (CI > 0), "redundant"
(CI ≤ 0.002) or "uncertain".
4.3 **Pairwise dependence**: Spearman correlation of log-odds and call agreement (≥ 0.5).
4.4 **Disagreement intelligence**: for each pair, the four patterns (both cSS, both not, A only, B only) with n and the observed cSS rate
among expert-reviewed candidates (Wilson 95 % CI), and who was right when they disagreed. Each scored candidate carries its
Characteristic-vs-Image pattern and that historical rate. The meta-model `stack_reg` additionally has disagreement terms (spread, gap).
Disagreement is never resolved by averaging.
4.5 **Reliability**: patient-bootstrap ensemble spread (20 meta-models), component disagreement, missing inputs, out-of-distribution
distance (Mahalanobis on the standardised characteristics + predictors, shrinkage covariance, limit = 99th percentile of development),
Image ML mirror stability, study image quality (`review/<ID>_qc.json` status).
4.6 **Calibration table** (deciles: mean score vs observed cSS rate) on development out-of-fold scores and on the locked test.

## 5. Percival Score

Meta-model discovery on the out-of-fold component table (development only): MATH alone, equal-weight mean (fixed, NOT learned), Fusion
alone, logistic stacking, regularised stacking on MATH + Unified + Fusion, regularised stacking + disagreement terms, boosted stumps
(only with ≥ 50 candidates per class). No meta-model combines Fusion with Characteristic or Image (double counting). 1-SE selection.
Calibration: Platt scaling of the chosen meta-model's out-of-fold log-odds with a ridge of 1.0 on the slope (without it, separable data
sent every score to 0 or 100). **Percival Score = 100 x calibrated output**, bounded 0-100; deterministic for a fixed model and input.
It is an assessment score calibrated on this project's development data - not a validated probability.

Thresholds: red below the 10th percentile (patient bootstrap) of the highest score that keeps sensitivity ≥ 0.95; green from the 90th
percentile of the lowest score with specificity ≥ 0.90; yellow between = class overlap + cut-point uncertainty. When development data
show no overlap even under bootstrap, the yellow band is empty and this is recorded (`yellow_empty`); it is not widened arbitrarily.

Status per candidate: `insufficient` (no learned source: no score - never a reassuring low value), `review` (study image quality
insufficient: expert review required), `uncertain` (ensemble spread > 15 points, strong disagreement, out-of-distribution, low-confidence
QC, unstable image model), `reliable`. Reasons are listed. Scores of a study whose labels trained the model are marked **in-sample**.

## 6. Expert review and controlled local learning

- Labels: effective reviewer call (policy in `call_ledger.py`); definite cSS = 1, definite mimic = 0; indeterminate / out-of-scope
  calls are kept but not used for training; reviewer conflicts are reported; duplicate studies (same image fingerprint) count once.
- **Review snapshots** (`unified_engine/percival/reviews/<ID>/<reviewer>__<saved>.json`, written once, never rewritten): labels,
  whether the Percival Score was visible to the reviewer, the newest Percival prediction created before the save (model, run,
  per-candidate outputs, thresholds), candidate coordinates, measurements, patch hash and cache reference, processing run, manifest and
  candidates-file hashes, active model at snapshot time.
- **Prediction ledger**: every assessment `ledger/<ID>/<model>__<run>.json` is immutable; a new model writes a new file.
- **Controlled cycles**: never after a single review; automatically after N newly finished studies (default 5, setting) or by the user.
  A cycle = data checks -> component OOF + family comparisons -> discovery -> calibration -> thresholds -> intelligence -> final fit ->
  locked-test evaluation -> acceptance. **Promotion only when acceptance passes** (minimum data; locked-test AUC ≥ MATH alone and ≥ active
  - 0.01; Brier ≤ active + 0.01; calibration slope 0.6-1.6). Every version is kept (`registry/vNNN/model.json`); any version can be made
  active; rollback restores the previous one.
- **Locked test cohort**: a patient is in it iff sha256(salt + patient id) < test fraction (default 0.2) - permanent, patient-level, never
  used for training, selection, calibration or thresholds.

## 7. GUI

- Reviewer: one primary **Percival Score 0-100** with its band; "Why this score" (collapsible): status and reasons, each source alone,
  what moved the final score (linear contributions), the disagreement pattern with its historical cSS rate, uncertainty, OOD distance,
  image stability, model version, in-sample warning. Hidden in a validation (blind) read. With a Percival assessment the old Unified card
  is removed (it appears as a component).
- Research › Percival Intelligence: Overview (learning curve, locked test), Components & agreement, **Evidence & reliability** (families,
  fusion benefit, shared inputs, incremental value, disagreement, calibration, review snapshots), Meta-model (discovery, actual
  calculation, thresholds, subgroups), Candidate explorer (with reasons), Training (selection, cycle settings), Registry (promote,
  rollback). Deep links: `#intel?tab=evidence`.

## 8. Evidence status (never mix these up)

| Claim | Status |
|---|---|
| All components, discovery, calibration, intelligence, ledger, snapshots, registry, GUI | **Implemented** |
| Pipeline integration, reproducibility, no leakage across the locked test, offline operation | **Tested with synthetic data** |
| Any discrimination / calibration number in tests or screenshots | **Synthetic only** - the synthetic cohort is far more separable than real MRI |
| Trained on real clinical data | **No** (this session did not open clinical data) |
| Clinically validated | **No** |

## 9. Known limitations
- Synthetic results are optimistic and make some analyses degenerate (empty yellow band, near-perfect AUCs).
- Small locked test cohorts (few patients) give wide or unavailable test metrics; the acceptance rule then keeps the model as a candidate.
- The CNN lost to the pixel baseline on the synthetic cohorts; whether a CNN earns its place on real patches is an open question that
  the comparison will answer per project.
- Scores on studies used for training are in-sample (flagged).
- The meta-model's linear contributions are associations on this project's data, not causes.
- Characteristic ML uses the detector's measured characteristics; their reliability depends on anatomy quality (T1 vs SWI-only).
