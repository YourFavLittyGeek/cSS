# Percival v5.24: implementation report (2026-11-21)

Scope: review-to-learning rebuild, the ML architecture investigation (five tabs), and Milestone 2, **the unified learning engine**.
Companion documents:
- `ARCHITECTURE_AUDIT_v5.24.md`: root causes of the "cSS 1 / not cSS 33" failure and of studies missing from training.
- `ML_TABS_AUDIT_v5.24.md`: the five tabs, the dependency matrix and the 10 questions.
- `ML_ARCHITECTURE_INVESTIGATION_v5.24.md`: the executed single-candidate trace, the diagrams and the status of every component.

**All results below are on synthetic data. Nothing here measures clinical accuracy.**

## 1. One learning engine, not another training system

| Requirement | Implementation (file) |
|---|---|
| Expert-review record | `percival_gui.snapshot_study`, `percival/reviews/ID/<reviewer>__<saved>.json`, schema `percival-review-snapshot/1.1`, immutable. Contents:<br>• study and candidate ids, calls, reviewer, save time<br>• annotations (comments) and missed-lesion marks<br>• image references (SWI, candidate mask, voxel, patch hash + cache reference) and candidate measurements (MATH, characteristics, predictors)<br>• the Percival prediction shown at review time<br>• processing run + manifest / candidate-list hashes<br>• engine, code hash, active model, eligibility rules<br>A revised review is a **new** record (`revision`, `revises`); none is ever rewritten. Call history itself also lives in the reviewer's append-only `ID_review_log.csv` (call ledger). |
| Central eligibility | `uengine/percival/eligibility.py`, rules `percival-eligibility/1.1`. Components: Characteristic ML, Image ML, Fusion, meta-model, **Unified Score predictors**, **Shadow evaluation**. Per candidate it gives status, reason codes, missing requirements in words, partition, rules version and evaluation time. A candidate can be eligible for one component and not for another (no MRI patch → no Image ML / Fusion; no reliable predictor → no predictor component). Unknown call values get status `unrecognised` and are listed, never dropped. Persisted per evaluation in `percival/eligibility/current.json`, including dataset membership; earlier records are kept. |
| Datasets | `uengine/percival/datasets.py`, manifest `percival-dataset/1.1`, content-hashed. Contents: candidate, study, patient, label, call, label source, reviewer, eligibility per component, reasons, **split** (train / test), **patient-level validation fold** (the CV folds used for model selection), feature schema, image preprocessing (`percival-patch/1.0`), creation time, settings. Before writing, the dataset is refused on **patient leakage** (a patient in both development and test) or **duplicate candidates**; the same examination twice is excluded as `DUPLICATE_STUDY`. `reproduce()` rebuilds a dataset from today's reviews and reports what changed: label, partition, input availability or reasons. |
| Central orchestration | `percival_gui._train` → `meta.train_cycle`: one cycle trains Characteristic ML, Image ML and Fusion (each with its own families and configuration), then the meta-model and calibration, on one dataset version and one patient split. Every run is recorded in `percival/runs/runNNN.json`: started, finished, failed with its error, or interrupted (a run still marked running at the next start). Each record has settings, code version, dataset, model and log. The Unified Score model and the Stage-1 shadow engine stay prototypes (section 4). |
| Model registry | `percival_gui.registry()` + `registry/vNNN/model.json` + `registry/status.json`. Each entry: identity `percival-score/vNNN`, component architectures (chosen and compared), dataset and hash, eligibility rules, feature schema, patch specification, code version, configuration (seed, epochs, minimum data, reason), metrics (locked test + development), validation report (acceptance), artifact path, training run, and status (experimental / candidate / active / retired / rejected, with its history). |
| Promotion | **No model becomes active by itself** (v5.24 change: before, a version passing acceptance was activated automatically). A new version is *candidate* (passed acceptance) or *experimental*. Acceptance compares it with MATH and with the active model on the locked test cohort. Activation needs your explicit approval in Model Center. A version that did not pass needs an override **with a reason**. A rejected version cannot be activated until restored. The replaced version becomes *retired*. Rollback is available, and promotions and status changes are logged. Shadow mode evaluates a version apart and can never activate it. The test hook `CSS_PERCIVAL_FIRST_ACTIVE=1` is for synthetic tests only. |
| GUI | **Training Center:**<br>• pipeline tiles (studies → processed → candidates → called → eligible)<br>• settings and datasets per component (all six)<br>• eligibility record with *Evaluate and record now* and a *reproducible?* check<br>• training runs<br>• study table with reasons, and candidate drill-down (per component, missing requirements)<br>**Model Center:** versions with status, *Make active* / *Reject* / *Restore*, registry details, promotion log, rollback, shadow mode.<br>**Data integrity:** store schema, migrations, backups, compatibility of every study, unrecognised calls. |
| Backward compatibility | Store schema 4 (`uengine/percival/store.py`). The migration 3 → 4 first makes a **verified backup**, then derives the status register and the training-run records from existing files. No existing file is rewritten. Chains from schema 1 / 2 (v5.22 / v5.23) are supported; a newer schema is refused untouched. Old study ids, candidate ids, reviews (shared file, `Vein`, per-reviewer files, earlier-project reviews) and old models / predictions are preserved and used. |

## 2. Tests that were run (synthetic only)

| Test | What it proves |
|---|---|
| `tests/trace_candidate.py` | One candidate through every component with the real code paths: synthetic MRI + candidates → MATH → Unified predictors (real extraction) → the prototypes → review → eligibility → dataset → training → score + provenance → shadow mode → registry status → explicit promotion → rollback → run records. 0 broken steps. |
| `tests/check_percival_learning.py` A–K | Legacy reviews, re-detection (fingerprints), conflicts, Unsure / Near ICH, revised and withdrawn calls, historical reviews from an earlier project, orphan studies, content-hashed datasets, store migration with backup, newer-schema refusal, clear training message. Section K adds:<br>• status register<br>• override with a reason; reject / restore / retire / rollback<br>• failed and interrupted runs<br>• persisted eligibility record with dataset membership<br>• the six components and missing requirements<br>• patient-level split and validation folds<br>• leakage and duplicate refusal<br>• reproducibility (a revised review is reported as such)<br>• unrecognised calls<br>• restart persistence |
| `tests/check_percival.py` | Engine: components, meta-model discovery, thresholds, locked test, explicit promotion (never automatic), ledger, review snapshot, offline inference. |
| `tests/check_app_percival.py` | The whole app in a temporary HOME with a headless browser:<br>• switch on, training, status *experimental* / *candidate* (not active)<br>• explicit approval with override<br>• reviewer receives the score<br>• Training Center (runs, eligibility record, reproducibility), Model Center (status, registry details), Data integrity<br>• second cycle, rollback<br>• shadow mode changes nothing reviewers see |
| `tests/check_local_only.py` | The above with every non-loopback connection blocked. |
| `tests/run_uscore_tests.sh`, `unified_engine/run_tests.sh`, `tests/run_tests.sh` | Full suites (results in the final report). |
| Packaged update test | v5.23 package → v5.24 package on the same scratch project, then a restart (section 5). |

## 3. Problems found and fixed in Milestone 2
- Automatic promotion of a passing model: removed (explicit approval).
- Concurrent writes: re-scoring after a promotion and a score request could write the same `.tmp` file at the same moment (found by the trace). Temp names are now unique per writer.
- The integrity report (reviewer conflicts, duplicate examinations) only looked at studies with an eligible label. A study whose only labels were in conflict was not reported. It now covers every labelled study.
- An unknown call value was treated like "no call". It is now `unrecognised`: reported and listed, never silently ignored.
- A dataset can change without any review change: the app's Unified Score step re-extracts predictors after switch-on. The reproducibility check reports such changes by kind instead of only "different".

## 4. What stays outside the engine, and why
- **Unified Score model ("Predictor model")**: its own held-out-protected cohort (M01–M26) and label reader. Training it on app projects fails by design (shown by the trace). Percival uses its five predictors; the eligibility engine reports, per candidate, whether a reliable predictor exists. Merging its training into the engine would remove the held-out protection; that is a scientific decision, not made here.
- **Stage-1 engine ("Shadow ML")** and the **synthetic image model**: prototypes on synthetic data, hidden by default. Real shadow evaluation is part of the Model Center.

## 5. Limitations
- Synthetic data cannot show clinical accuracy, calibration on real cases, or generalisation across scanners. Clinical validation needs expert-labelled studies, with the locked test cohort evaluated once.
- Unified predictors need FreeSurfer anatomy and registration. Without them every predictor is unreliable and Percival treats the input as missing (shown in the Overview).
- The meta-model's validation folds are recorded in the manifest. The Image / Characteristic family comparison uses the same patient-grouped folds (`meta.folds`, same seed).

## 6. Release verification (v5.24 final)

### 6.1 The main learning system, component by component (verified by execution; synthetic data)
| Component | Code | Input | Output | Stored | Consumed by | Version |
|---|---|---|---|---|---|---|
| Expert-review ingestion | `scripts/call_ledger.py` (all reviewer files, legacy shared file, `Vein`→Vessel, fingerprint matching incl. earlier-version reviews via `match_one`), `percival_gui.label_summary` | `review/ID_calls*.csv`, `ID_final_*.json`, `historical/ID/review/` | per-candidate label, source, reviewer, conflict | `percival/reviews/` (immutable snapshots), dataset manifests | eligibility → datasets → training | rules `percival-eligibility/1.1` |
| Characteristic ML | `percival/learners.py`, `meta.Components` | the 9 detector measurements | logit (logistic / boosted trees / forest, chosen by patient-grouped CV) | `registry/vNNN/model.json` → `components.char`; predictions in the ledger | Fusion, meta-model, Intelligence | model version |
| Image ML | `learners.PixelLogistic`, `cnn.py`, `imaging/patches.py`, `cnn.patch_maps` | the candidate's MRI patch (3×49×25 maps) | logit + TTA spread; **v5.24: image out-of-distribution distance** | `components.image`; ledger | Fusion, meta-model, Intelligence | model version |
| Fusion | `meta.Components` (late / feature / hybrid) | characteristic logit + image logit | logit | `components.fusion`; ledger | meta-model | model version |
| Meta-model ("Predictor") | `meta.discover`, `Meta` | MATH, Unified (5 reliable predictors), Fusion logits (never Fusion with its own parts) | combined logit | `meta`, `meta_ensemble` | calibration | model version |
| Calibration | ridge-Platt in `meta.train_cycle` | meta logit (development out-of-fold) | calibrated probability ×100 | `calibration`, `thresholds` | Percival Score, bands | model version |
| Reliability / uncertainty | `intelligence.py`, `meta.score_rows` | ensemble spread, component disagreement, OOD (measurements **and image patches**), TTA spread, QC, missing sources | status (reliable / uncertain / insufficient / review) + reasons | ledger + current score | reviewer ("Why this score"), Model Center | model version |
| Final Percival Score | `meta.score_rows`, `percival_gui.score_study` | all of the above | score 0–100, band, status, reasons, every component value, provenance | `percival/scores/ID.json` (current), `percival/ledger/ID/vNNN__run.json` (immutable) | reviewer, Studies list | model + dataset + code hash + run |
| Historical predictions | `percival_gui.history_of` | ledger | current / historical / earlier processing | never rewritten | Explorer, review snapshots | — |

**Image ML learns from expert-reviewed patches** (`tests/check_image_ml_integration.py`, 24 synthetic studies, calls in the reviewer's file format):
- out-of-fold AUC 0.961 for the pixel baseline vs **0.516 with the labels shuffled**, on the same pipeline;
- every candidate with a patch was used (88 = 88);
- altering one patch changes its Image ML value, its Fusion value and its Percival Score, while MATH, Unified and Characteristic stay unchanged;
- a missing patch is reported as "missing: image".

The CNN learns more slowly: out-of-fold AUC 0.52 at 10 epochs, 0.67 at 30 (the default) and 0.76 at 60, on 84 development candidates. The pixel baseline is chosen because the CNN must beat it; on small datasets the CNN adds nothing yet.

**Found and fixed:** a patch unlike any training patch got an extreme Image ML value marked "reliable", because out-of-distribution detection only looked at measurements. An image OOD check (Mahalanobis distance on per-channel intensity, contrast and structure statistics, 99th-percentile limit) now marks such candidates "uncertain" with the reason. Real patches are not flagged. Models trained before this simply have no image OOD.

### 6.2 Unified predictors and FreeSurfer (`tests/check_unified_prerequisites.py`)
Every predictor is computed by `uscore.pipeline.extract_study` from:
- the SWI;
- the candidate mask;
- `work/ID_vessels.nii.gz` (detector);
- `work/ID_pial_sd.nii.gz` (detector, from the anatomical labels, i.e. FreeSurfer / SynthSeg);
- the unmasked SWI in `raw/`;
- the registration state from `review/ID_qc.json`.

The synthetic image cohort used for Percival tests has none of the detector or anatomy outputs, so all anatomy-dependent predictors were "unavailable" or "unreliable" (registration "unverified"). x2 was unreliable there for its own reason: no contrast core.

Results by scenario, with Percival's own extraction path:

| Scenario | Registration | Predictors |
|---|---|---|
| full prerequisites | ok | reliable (18 reliable values), used by Percival |
| no QC | unverified | x1, x3, x4, x5 unreliable with the reason, **never passed to Percival**; x2 is image-only by design |
| failed registration | unreliable | same |
| SWI-only anatomy | swi_only | same |
| no pial map (no anatomy) | — | x3 and x4 unavailable ("no pial distance map (no anatomy)") |
| no vessel map | — | x1 unavailable |
| no raw SWI | — | x5 unavailable |
| SWI missing | — | extraction refused and logged |

In Percival, an unreliable or unavailable predictor is never a value: the source is flagged "missing: unified", the score does not change whatever unreliable value was measured, and the candidate is not eligible for the predictor component ("a reliable Unified Score predictor (FreeSurfer anatomy + registration)").

### 6.3 Older prototype tabs
They are hidden by default and their back ends still answer (`/api/u/state`, `/api/se/state`, `/api/im/state`, `/api/train/overview`). Their stored outputs, history and tests are unchanged.

Planting an old Unified Score model and report does not change any Percival Score (`tests/check_app_percival.py`). Percival reads only the five predictors.

The held-out protection of the Unified Score model holds (`tests/check_heldout_protection.py`). Fingerprint matching of earlier-version reviews moved into the call ledger (`call_ledger.match_one`), the boundary that rule enforces.

### 6.4 Shadow ML
- **Operational runner:** Percival shadow mode scores every study with a non-active version into `percival/shadow/vNNN/`. On 24 studies, 49 active score and ledger files stayed byte-identical; the version stayed experimental and only *Make active* can deploy it.
- **Comparison with expert reviews:**
  - "unseen" metrics use calls the shadow version never learned from;
  - **head-to-head** metrics use only calls that *neither* model learned from.

  Fixed in v5.24: the head-to-head first compared against the active model on calls it had been trained on, which is in-sample.
- **Traceability:** each run summary names both versions; each version names its dataset.
- **The older Stage-1 "Shadow ML" runner** is operational but its only model is synthetic. It is a shadow runner, not a scientifically useful trained model.

### 6.5 Two further fixes from the full regression run
- Earlier-version reviews were matched in app code with the call matcher, which the held-out-protection rule forbids. This was moved into the call ledger.
- An intermittent "partially initialized module openpyxl" error appeared when two server threads first imported openpyxl at once (the Excel template). openpyxl is now imported at app start-up.
