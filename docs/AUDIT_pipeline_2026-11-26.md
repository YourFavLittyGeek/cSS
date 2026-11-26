# Pipeline audit — read from the code (2026-11-26)

Scope: the scripts themselves (`scripts/`, `unified_engine/uengine/`, `unified_score/uscore/`, `app/`), not the existing reports.
Method: read the code paths end to end; ran the phantom suite (`tests/run_tests.sh`) and `check_percival`, `check_percival_learning`,
`check_ranker`, `check_heldout_protection` on a copy in an isolated venv (no patient data, nothing in the repo was changed);
reproduced one suspected bug with a probe script. Line numbers are in the `cSS_pipeline_v4.13/` tree.

---------------------------------------------------------------------------------------------------------------------

## 1. What the pipeline actually is (as executed)

```
SWI (+T1/FLAIR/phase)
  └─ run_css.sh / processing_manager STAGES = anatomy → registration → align → detect → unified
       anatomy  : prep_anat.sh (T1 SynthSeg or recon-all, bbregister) ; SWI masked with T1 labels (swi_mask_from_t1.py)
       detect   : scripts/detect_css.py   ← "ALBUS" in the architecture docs
       after    : surface_features.py (recon-all only), rank_candidates.py (dev split only, if a ranker exists), ai_score
  └─ review/ID_candidates.csv  (~60-100 candidates/scan, ranked by score_v4)
  └─ reader reviews in review_web.py → ID_calls_<reviewer>.csv → call_ledger.py (policy: designated experts, quorum)
  └─ score_css.py → patient-level 0-4 multifocality (STRIVE-2 / Charidimou, Destrieux sulci adjacency)
Learning side (app, runs in the background on the user's Mac):
  call_ledger → eligibility.py → datasets.py (manifest, hash) → percival/meta.py train_cycle()
       NOX  (30 detector measurements → logistic / GBT / forest, chosen by patient-grouped CV)
       LUMOS (3 surface-aligned patch maps 49×25 → pixel-logistic / SmallCNN (1,425 params) / 3-seed CNN ensemble)
       ALBUS (score_v4 → 2-parameter Platt recalibration)          → PERCIVAL meta-model (1-SE rule over 6 candidates)
       → Platt calibration → bootstrap-stable red/yellow/green cuts → locked-test evaluation → human approval in Model Center
```

### How each component works and how (whether) it learns

| Component | What it does (from the code) | Does it learn? |
|---|---|---|
| **ALBUS = `detect_css.py`** (1,413 lines) | Signed pial distance from labels → local-cortex-referenced darkness z (2-pass, MAD) → per-slice Sato ridge → hysteresis seeds per hemisphere → piece merging (≤3 mm, ≤40 mm) → ~20 features/candidate → hard exclusion rules E1–E30 → `score_v4 = √darkness × on-surface × sheet × alignment × tram`. | **No.** Thresholds and E-rules are hand-set and frozen (comment block at `detect_css.py:121-128`). "Learning" = a human reads `ALBUS evaluation` (`albus_detection.py`), then edits code and runs `redetect.py`. Everything downstream can only re-rank what ALBUS generated. |
| **NOX** (`percival/meta.py` `CHAR`, `learners.py`) | 30 columns the detector already wrote (9 core + 18 added + 3 uScore predictors). Family chosen by patient-grouped CV (logistic < gbt < forest, 1-SE rule). | **Yes** — retrained each cycle on expert labels; a new version is adopted only if CV log-loss improves (`module_report`). |
| **LUMOS** (`percival/cnn.py`) | min-IP / mean / footprint maps of the surface-aligned patch → small CNN, flip+rotation+bias-field+resolution augmentation, early stopping on a held-out patient split; test-time-augmentation spread = uncertainty. Expert "missed cSS" marks are added as extra positives only if they do not worsen CV log-loss. | **Yes**, same loop. |
| **PERCIVAL** (`meta.py`) | Stacks ALBUS/NOX/LUMOS log-odds with missing indicators, disagreement and reliability terms; Platt; thresholds; OOD (Mahalanobis, 99th pct); ensemble spread; abstention. Nested patient-level cross-fitting of the *whole* procedure (`nested.py`) plus a hash-locked test cohort. | **Yes**, but a trained model is only a *candidate* until a human approves it. |
| **uScore** (`unified_score/`) | Five-predictor ridge LR. | **Retired** (`legacy_guard.RETIRED`); x1/x2/x5 live on as NOX inputs. |
| **Legacy ranker / confidence** (`train_ranker.py`, `css_confidence.py`) | Separate L2-LR on detector columns; `E30` exclusion with `CSS_CONF=1`. | Yes, separately, **outside** the Percival loop. |

### How they integrate

Strengths (verified in code): one label source (`call_ledger` → `eligibility.py`), content-hashed dataset manifests, patient-level
leakage audit (`split.py:leakage_audit`), nested cross-fitting, immutable prediction ledger, no automatic promotion, held-out guards
(`check_heldout_protection`: 0 FAIL). This is unusually careful for a research pipeline.

---------------------------------------------------------------------------------------------------------------------

## 2. What is not working / defects found

### A. Real defects (code-level, reproduced or directly read)

1. **Patient grade from Percival uses an arbitrary cut, not the model's own thresholds.**
   `app/percival_gui.py:1198` → `ids = [... if s["percival_score"] >= 50]` feeds `score_css.py --accept-ids`. The model carries
   calibrated `red_below` / `green_from` (sensitivity ≥0.95 / specificity ≥0.90 cuts) that are never used here. 50 was never validated, and the
   candidate-level model was never evaluated against the 0–4 grade. A scan with no candidate ≥50 gets grade 0 ("negative"), a
   miss-prone reading for a sensitivity-first design.
2. **Three different "AI opinions" are shown to the reader and none of them is the learned one for the patient grade.**
   - `review_web.ai_opinion()` (`review_web.py:125`): rule meter `css_evidence/(css+vein)` with ×0.4–0.9 hand multipliers, or `score_model`
     from the legacy ranker; drives `ID_score_ai.json` (`ai_score()`, `ai_score_cli.py`).
   - Percival score (`percival/scores/ID.json`), different candidates "green".
   - Legacy confidence `E30`.
   The study-level "AI score" in the reviewer top bar and the automatic-mode score therefore come from the *unvalidated hand rule*, not
   from the trained engine. Reader sees ≥2 numbers that can disagree.
3. **`albus.py` adaptive learning is wrong (retired, but still shipped and documented as active).** Reproduced with a probe:
   - `threshold_before` is read *after* `update_adaptive_threshold()` (`albus.py:206`), so before == after in every logged event.
   - The "normalisation by patient" is inverted: 12 misses in **one** patient → threshold 0.50 → **0.26** (multiplier 2.0, clipped);
     12 misses spread over 12 patients → 0.45. One scan distorts sensitivity most — the exact thing the docstring says it prevents.
   - Lowering a *score* threshold cannot recover lesions lost at generation gates or exclusion rules E1–E30 (the usual cause).
4. **`percival_core.py` is a second, hand-weighted Percival.** Default weights (`w_albus 0.25 … bias -0.8`, `geom_score` formula) are
   invented; `fit()` can overwrite them but nothing calls it. It is gated off by default and labelled "comparison only", but it ships in
   the app and in `docs` as "Percival Core". ~4,000 lines (`albus.py`, `nox.py`, `lumos.py`, `percival_core.py`, `pensieve.py`,
   `vault.py`, `shadow_lab.py`, `governance.py`, `unified_fusion.py`) are retired/comparison code that look live.
5. **Dead / misleading references:** `meta.test_assignment` is imported in `percival_gui.py:528,648,690` but the authoritative split is
   `split.partition_of`; two split rules exist (`study_meta.csv test`, uscore held-out, Percival split) and only a leakage *audit* reconciles them.

### B. Statistical / methodological limits that cap what "learning" can do today

1. **Label quality.** The development cohort M02–M11 was read by *one non-expert reader* (kappa 0.65 AI-visible, 0.87 hidden; Normal↔Vessel
   drift). E12–E25 and the confidence thresholds were fitted to those same calls. The new ledger refuses non-expert/non-blind labels as
   primary ground truth (good), but that means **the current training set that satisfies `READINESS` may be very small or empty**; the model
   gates (`MIN_STUDIES=30`, `MIN_CANDIDATES=100`, `MIN_PER_CLASS=10`, `MIN_TEST_PATIENTS_PER_CLASS=5`) need ≥~50 studies to ever pass acceptance
   (test = hash-random 20 %, so ≥10 test patients with *both* classes).
2. **Candidate-level target ≠ clinical endpoint.** Everything is trained for P(candidate is cSS); the product is a patient 0–4 grade. No
   patient-level loss, no evaluation of *grade* agreement for Percival (only compare_grades vs radiologist for the detector+reader route).
3. **Verification/selection bias in ALBUS evaluation.** `albus_detection.evaluate()` sensitivity = detected / (detected + *expert-marked
   missed*): lesions nobody found are not counted, and exclusion rules E1–E30 remove objects before anyone sees them (audit sample is 20 % of
   excluded objects and only in validation reads). Detector recall is therefore unmeasured; Percival cannot improve it.
4. **Per-scan relative thresholds always produce candidates.** Ridge cut = 85th percentile of the shell *in that scan*
   (`detect_css.py:r_pct`) → every scan yields ~6–100 objects, incl. healthy LEMON (6–16) and negatives (P011: 8). The detector cannot say
   "no cSS here"; all negative-scan specificity must come from the downstream model, which has the fewest negative patients.
5. **Capacity vs data.** 30 NOX features + a CNN on a handful of positive *patients*; `Stumps`/GBT/forest are in the search space even
   though the 1-SE rule penalises them. Mahalanobis OOD (30-d, training 99th pct) flags 1 % of *training* by construction and is
   in-sample; it will flag new scanners/1.5 T heavily.
6. **Optimistic selection.** `component_oof` chooses families on the same folds that `meta.discover` then re-uses and the "development
   thresholds" are fitted on the same OOF scores (the code says so: `th["dev_basis"]`). Honest numbers are only `model["nested"]` and the
   locked test; the app shows both.
7. **2-D Sato seeds.** Candidate generation is per axial slice (orientation/slice-thickness dependent), 3-D seeds are "recorded only"
   (`CSS_3D_SEEDS`), and `G2` gate / merge rules depend on slice geometry; 3 mm 1.5 T SWI (M01/05/11/12/13) is a different regime than 3 T.
8. **Opt-in rules vs production.** E12–E29, `MIXED_REVIEW`, `STRUCT`, `ZONE2`, `CONF` are env-var switches; the manifest records them but
   a project can silently run mixed rule sets across studies; no single "production rule-set" is enforced at score time.

### C. Not tested here / limits of this audit

- Phantom suite: **first ~60 % passed** (PH1–PH6, check_v4/v418/v51/v511 …) with no FAIL lines; it was still running when this was
  written — see the final line of `scratchpad/run_tests.log` for the final status.
- `check_percival` (34 PASS), `check_percival_learning` (ALL PASS, 57), `check_ranker` (OK; noise labels AUC 0.506), `check_heldout_protection` (0 FAIL).
- I could not run FreeSurfer, the Mac app, the browser-driven checks, or anything on real patient data. Findings about real-cohort
  behaviour (kappa, FP/scan) are taken from numbers the code/commentary itself records, not re-measured.

---------------------------------------------------------------------------------------------------------------------

## 3. Recommendations (ordered by payoff / risk)

**Do first (small, safe)**
1. Replace `percival_score >= 50` with the model's own cut (`green_from`, or `red_below` for a sensitivity-first read) and record which
   cut produced each grade; show the patient-level number as "Percival-assisted", never as the study grade.
2. One "AI opinion" in the UI: make the reviewer meter, `ai_score` and the automatic-mode score read the *active Percival model* when one
   exists, and fall back (labelled) to the rule meter only when none does. Remove the ×0.4–0.9 hand multipliers from the learned path.
3. Delete (or move to `legacy/`) `albus.py`, `nox.py`, `lumos.py`, `percival_core.py`, `unified_fusion.py`, `shadow_lab.py`,
   `governance.py`, legacy `pensieve.py`/`vault.py`; keep one adapter for the comparison tile if still wanted. At minimum fix `albus.py:206`
   and the inverted per-patient normalisation, and stop calling it "active learning" in docstrings.
4. Remove the dead `test_assignment` imports; keep `split.py` as the only authority and make `study_meta.csv`, uscore held-out and Percival
   read the same file.

**Next (moderate)**
5. **Patient-level objective.** Add a patient-grade evaluation of the whole chain (Percival → `score_css --accept-ids` → 0–4) on the nested
   folds, reported as weighted kappa vs expert. Optimise cuts for *grade* agreement and for false-negative patients, not only candidate log-loss.
6. **Close the generation gap.** Use expert missed-cSS marks to *tune and test ALBUS* (generation + E-rules) by ablation on a frozen
   development set; promote only when every previously detected cSS is retained (the `compare()` rule already exists — wire it to
   `redetect.py` with a CI-gated pipeline). Turn the per-scan percentile ridge cut into an absolute (calibrated) cut plus a scan-level
   "no-cSS" decision so negative scans can return zero.
7. Stratify the locked test cohort by cSS status (hash-random 20 % can contain no positive patient) and report the test only when it has ≥N
   positive patients; with <50 studies prefer repeated nested CV and treat the locked test as confirmatory only.
8. Collapse to **one rule set** per release: freeze production switches into a versioned `rules.json`, refuse to score/learn from studies
   whose `ID_manifest.json` rule hash differs (or label them separately in the dataset manifest).

**Later**
9. Move candidate generation toward a 3-D plate-ness filter (the `CSS_3D_SEEDS` branch already records overlap) once the overlap statistics are
   judged; add a 1.5 T/3 mm-specific validation stratum.
10. Recompute OOD on out-of-fold data (not training distances) and report the per-scanner flag rate; switch to a robust distance
    (MCD / per-protocol medians).
11. Treat NOX feature count honestly: report feature-ablation at the *patient* level and prefer the logistic family until ≥10 positive
    patients per fold.

**Evidence that should be gathered before trusting any score:** a blind, expert, two-reader consensus on ≥~30 scans (≥10 cSS-positive),
with whole-study missed-lesion search, so ALBUS sensitivity and the Percival grade can finally be measured against something other than the
developers' own calls.
