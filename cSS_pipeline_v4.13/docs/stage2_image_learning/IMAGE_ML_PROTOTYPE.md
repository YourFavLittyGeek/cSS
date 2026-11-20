# IMAGE_ML_PROTOTYPE.md - Percival Image ML prototype (SYNTHETIC DATA ONLY), 2026-11-20

**Research prototype. The image model was trained and evaluated on invented phantom images only. Nothing here is a clinical result,
a validated measurement or a performance claim for cSS.** No clinical MRI, label or table was opened, copied, processed or transmitted.

## 1. What it is
A new **Image ML** screen in the experimental Percival GUI (Research group) that loads a SYNTHETIC study, runs a local image model on every
candidate and shows, per candidate: coordinates (stored voxel fingerprint and world centre), predicted class (cSS or a mimic subtype), class
probabilities, p(cSS) with a 5-95 % patient-bootstrap interval, confidence, a reading-aid category, quality flags, three patch views
(surface-aligned u x v and v x n, native acquired slice) with the object mask, the 30 features used, and full model provenance.
Image ML, Characteristic ML (Stage 1) and deterministic MATH are shown as three separate panels; for the synthetic image studies the latter
two say "not available" (these phantoms carry no detector measurements), they are never filled in or mixed.

## 2. Components (all local; numpy / scipy / nibabel; no network, no external AI service)
| layer | file | role |
|---|---|---|
| P1 index + geometry gate | `unified_engine/uengine/imaging/{geometry,registration,index}.py` | refuses bad geometry, records provenance |
| P2 patches | `uengine/imaging/patches.py` | css-patch/2.0 (production `surface_aligned_patch.extract_patch`, pinned, + native 2.5D stack) |
| P3 synthetic cohort | `uengine/imaging/synthetic_cohort.py` | acquisition variability, 7 mimic subtypes, simulated readers, negative control |
| image model | `uengine/imaging/image_model.py` | 30 patch features + L2 multinomial logistic regression (D1 option A), bootstrap ensemble, hash-protected file |
| training | `uengine/imaging/train_image_model.py` | synthetic train / independent test / two negative-control cohorts |
| inference | `uengine/imaging/image_infer.py` | per-study inference, writes only `unified_engine/image_ml/ID.json` (+ patches) |
| CLI | `unified_engine/run_imaging.py` | `cohort`, `models`, `infer`, `train-synthetic`, `index`, `patches`, `verify` |
| model weights | `unified_engine/models/image/synthetic_image_softmax_v1.0.0.json` (112 KB) | bundled, synthetic |
| GUI back end | `app/image_ml_gui.py` | subprocess runner (never imports the engine), synthetic-base-only listing |
| GUI screen | `app/image_ml_view.js` | the Image ML screen |
| app wiring | `app/css_app.py` (+20 lines: `/image_ml_view.js`, `GET/POST /api/im/*`), `app/css_app.html` (nav entry, title, guarded render branch, script tag) | |

Safety properties (each tested): synthetic base marker AND SYN code required before any file is opened; a synthetic-trained model is applied
to synthetic studies only; inputs (images, detector tables) hashed before and after every run; the engine runs in a subprocess with a time
limit; a failing run writes nothing and the previous result stays; corrupt / edited / incompatible models are listed and never selected;
on a non-synthetic base the screen lists and reads nothing; no network connection is attempted (verified with the repository's netguard).

## 3. Model card - synthetic_image_softmax v1.0.0
| field | value |
|---|---|
| hash | `8d223b29d1c538afc99589a32e89c934a1934d984bdfadf62b6ef56aa808af9c` (parameters AND card; verified on every load) |
| data kind | synthetic (card and hash-protected training record) |
| classes | css, artifact_airbone, calcification, microbleed, normal_iron_cortex, vein_sulcal, vein_surface, vein_transcortical |
| training | generator `uengine-synthetic-cohort/1.0`, seed 500, 48 studies, 237 objects, 101 training rows = objects on which the two simulated readers agreed on a definite class (7 of them wrong vs truth: label noise) |
| method | 30 image-derived features from css-patch/2.0, balanced L2 multinomial logistic regression (l2 0.05), 20 patient-bootstrap refits |

Synthetic evaluation (against the generator's truth; these numbers describe the invented generator, not cSS):
| evaluation | n objects (cSS) | within-patient AUC | pooled AUC [95 % CI] | kind accuracy | cal. slope |
|---|---|---|---|---|---|
| 5-fold patient-grouped CV, training cohort | 101 (23) | 1.000 | 0.991 | 0.842 | 1.91 |
| independent synthetic test cohort (16 studies, every scorable object) | 74 (13) | 0.981 | 0.986 [0.967-1.000] | 0.811 | 3.15 |
| **negative control** (images carry no label information; trained on one null cohort, tested on another) | 116 (21) | 0.489 | **0.505 [0.378-0.629]** | 0.069 | 0.03 |
| negative control, 5-fold CV (reported, unstable) | 44 (13) | 0.263 | 0.335 | 0.091 | - |

Reading: the generator is easy (near-perfect separation), so high synthetic AUCs say nothing about real SWI. The negative control behaves as
required (CI contains 0.5). Calibration slopes > 1 mean the model is UNDER-confident on this separable synthetic data. The K-fold CV of the
null cohort is far from 0.5 on small samples (fold prevalence artefact, the Stage 1 finding); the independent-cohort null is the decision value.

## 4. Launch instructions (synthetic demonstration; works offline)
```zsh
cd /Users/tarabeah.selim/Projects/cSS-unified-score-ml/cSS_pipeline_v4.13
conda activate css
# 1. a SYNTHETIC cohort in a scratch folder (never ~/css_project); 8 studies with varied acquisitions
python unified_engine/run_imaging.py cohort /tmp/percival_imageml_demo --n 8 --seed 42
# 2. start Percival on it (write guard on; port of your choice)
CSS_BASE=/tmp/percival_imageml_demo CSS_EXPERIMENTAL=1 PYTHONPATH=app/guard python app/css_app.py --port 8830
```
Then open **http://127.0.0.1:8830/#imageml** (or click **Research > Image ML**). Press **Run inference** on a study, then **Open**; click a
candidate row to see its patches, class probabilities, features and provenance. Direct links: `#imageml:SYN001`, `#imageml:SYN001:c1`.
In this seed SYN002 and SYN004 have 3 mm slices and show the "not scorable" path; SYN003 (2.5 mm slices) shows quality-flagged "uncertain".
Stop the app with Ctrl-C. Optional: `python unified_engine/run_imaging.py infer SYN001 --base /tmp/percival_imageml_demo --write` (CLI).
Requirements: the existing `css` environment (numpy, scipy, nibabel, pandas); no internet, no GPU, no PyTorch; the model weights are in the
repository. Retrain (synthetic, ~4 min, never overwrites): `python unified_engine/run_imaging.py train-synthetic /tmp/my_model.json`, then copy
it into `/tmp/percival_imageml_demo/unified_engine/models/image/` to have it listed.

## 5. Tests
```zsh
bash unified_engine/run_tests.sh /tmp/uengine_tests.log            # 7 stages: Stage 1 + imaging + Image ML + both app/browser checks
python tests/check_app_image_ml.py --shots /tmp/imageml_shots       # Image ML through the real app + headless Chrome only
```
Results (2026-11-20): runner 0 failing stages - Stage 1 119 / 119 unit tests, Shadow ML app 35 / 35, imaging + Image ML 78 / 78 unit tests,
Image ML app + browser 42 / 42 (43 / 43 with `--shots`). New test files: `test_synthetic_cohort.py` (15: physics, truth, readers, negative
control, threshold re-check), `test_image_ml.py` (14: model health / tamper / incompatibility, signal and null, inference record, truth
tracking, invalid images, missing patches, missing model, model failure, synthetic-only, bundled model, offline), `tests/check_app_image_ml.py`
(GUI integration incl. failure, corrupt model, non-synthetic base, browser DOM). Screenshots: `docs/stage2_image_learning/screenshots/`.

## 6. Known limitations
1. Synthetic only: geometry, contrasts, blooming, mimic shapes and reader error rates are invented; nothing transfers to real SWI.
2. No detector run on the phantoms: MATH and Characteristic ML are "not available" for image studies (shown, not faked).
3. Phase-sign handling assumes most dark objects in a study are paramagnetic (study-level sign); flagged when it cannot be established.
4. Option A only (hand-crafted features). The 2.5D CNN (option B, P9) is not built; PyTorch is not installed.
5. The P4 label converter (css-labels/1.0 -> 2.0) is not built; the simulated readers write 2.0-shaped rows directly.
6. No tram-track (two-bank) cSS and no out-of-scope objects in the generator yet.
7. Inference runs per study on demand; no cohort-level Image ML report.
