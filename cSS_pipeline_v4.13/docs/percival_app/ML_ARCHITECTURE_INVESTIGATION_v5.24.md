# Percival ML architecture: investigation of the five ML tabs as one system (v5.24, 2026-11-21)

**Method.** I read every tab's app module, view, command line and engine functions (`ML_TABS_AUDIT_v5.24.md`). Then I **executed** one
synthetic candidate through every component with `tests/trace_candidate.py`: a temporary project, synthetic phantoms, the real code paths.
A status below is a result of that run, not an assumption based on a tab existing.

Status labels:
- **functional**: runs and its output is used.
- **partial**: runs, but often produces no usable output.
- **experimental**: synthetic only.
- **disconnected**: runs, but nothing consumes its output.
- **not implemented**.

## 1. Trace of one candidate (SYN001 #1, executed)

| # | Step | Code that ran | Result | Status |
|---|---|---|---|---|
| 1–2 | MRI + candidates | `run_imaging.py cohort` + `make_demo.py` (stand-in for import / `detect_css.py`, which `tests/run_tests.sh` covers on phantoms) | 16 studies; candidate #1 with measurements | functional (synthetic stand-in) |
| 3 | MATH | `score_v4` column of `review/ID_candidates.csv` | 1.594 | functional |
| 4 | Unified Score predictors | `uscore.pipeline.extract_study(application=True)`, exactly as Percival calls it | **all 5 predictors unreliable / unavailable on this phantom** (no FreeSurfer anatomy). Percival therefore receives "missing: unified" | **partial** (needs anatomy and registration; now shown in the Overview) |
| 5 | Image ML tab | `run_imaging.py infer --write` | `synthetic_image_softmax` applied; result in `unified_engine/image_ml/ID.json` | **disconnected** (no consumer; synthetic only) |
| 6 | Shadow ML tab | `run_engine.py shadow` | synthetic demo model applied; `unified_engine/shadow/ID.json` | **disconnected** (no consumer; no real model) |
| 8 | Predictor model tab | `run_unified.py train` | **fails**: "features of M.. not extracted". It trains only on its fixed M01–M26 manifest | **disconnected / broken for app projects** |
| 10 | Expert review | `review/ID_calls_<reviewer>.csv` + `ID_final_<reviewer>.json` (the reviewer's format) | 67 calls | functional |
| 11 | Eligibility | `eligibility.evaluate` via `percival_gui.candidates_of` | eligible for char / image / fusion / meta; development partition | functional (v5.24) |
| 13 | Training | `percival_gui._train` → `meta.train_cycle` | v001: char = boosted trees, image = pixel baseline (CNN lost), fusion = late, meta = equal mean; acceptance **not passed** (below minimum data, test cohort too small) | functional |
| 12 | Dataset | `datasets.build` | ds001; candidate present, label source "review", all components | functional (v5.24) |
| 9 | Percival Score | `meta.score_rows` + ledger | 4.2 (red), components MATH 26 / char 31 / image 2.5 / fusion 19 / unified missing; provenance with model, dataset, schema, code hash, run | functional |
| 14 | Shadow | `percival_gui._shadow(v002)` | 67 candidates compared with active v001; 0 prospective calls (all were learned); active unchanged | functional (v5.24) |
| 15 | Acceptance / promotion | `meta.acceptance`, `promote` / `rollback` | not passed (stays a candidate); rollback target kept | functional |

## 2. Architecture diagram (final, v5.24)

```
                         ┌──────────────────────────── project folder (user data) ────────────────────────────┐
 MRI ─► import/identity ─► processing (run_css.sh, FreeSurfer) ─► detect_css.py ─► review/ID_candidates.csv     │
                         │                                              │  MATH (score_v4) + measurements       │
                         │                                              ▼                                       │
                         │   uscore extraction ─► uscore/features/ID.json (5 predictors, reliable/unreliable)   │
                         │   imaging.patches   ─► MRI patch per candidate (cache)                               │
                         │                                              ▼                                       │
                         │  ┌──────────────── PERCIVAL CORE (unified_engine/uengine/percival) ───────────────┐ │
                         │  │ gather ─► Components: Characteristic ML │ Image ML │ Fusion ─► meta-model        │ │
                         │  │          ─► calibration ─► thresholds ─► Intelligence (OOD, disagreement, QC)   │ │
                         │  │ eligibility.py ◄── call ledger + earlier-version reviews ◄── reviewer (review/)   │ │
                         │  │ datasets.py (dsNNN) ─► train_cycle ─► registry vNNN ─► acceptance ─► active.json │ │
                         │  │ ledger/ (immutable predictions) · scores/ (current) · shadow/ (never shown)      │ │
                         │  │ store.py: percival/STORE.json schema 3, migrations, backups/percival/           │ │
                         │  └─────────────────────────────────────────────────────────────────────────────────┘ │
                         │   reviewer shows ONE Percival Score (+ Why this score)                                │
                         │   prototypes (hidden): Unified Score model · Stage-1 engine · synthetic image model   │
                         └────────────────────────────────────────────────────────────────────────────────────────┘
 GUI: Percival Intelligence = Overview · Training Center · Model Center (+ shadow) · Data integrity · Advanced (components, evidence, meta, explorer)
```

## 3. Component responsibility table

| Component | Responsibility | Code | Learns from reviews | Feeds the score | Status |
|---|---|---|---|---|---|
| MATH | deterministic definition rule | `scripts/detect_css.py` (`score_v4`) | no (by design) | yes (input) | functional |
| Unified Score predictors | 5 measured predictors with reliability states | `unified_score/uscore/features.py`, `pipeline.extract_study` | no | yes (input; missing when unreliable) | partial (anatomy-dependent) |
| Characteristic ML | detector measurements → logit (logistic / boosted trees / forest, chosen by CV) | `percival/learners.py`, `meta.Components` | yes | yes | functional |
| Image ML | MRI patch → logit (pixel baseline / CNN, the CNN must win) + TTA uncertainty | `percival/learners.PixelLogistic`, `cnn.py`, `imaging/patches.py` | yes | yes | functional |
| Fusion | characteristic + image (late / feature / hybrid, with a fusion-benefit test) | `meta.Components` | yes | yes | functional |
| Meta-model + calibration | combines MATH, Unified and Fusion (never Fusion together with its own parts) | `meta.discover`, `irls` | yes | yes | functional |
| Percival Intelligence | reliability: OOD, disagreement patterns, ablation, calibration tables, reasons, status | `percival/intelligence.py`, `meta.score_rows` | yes (patterns) | status / reasons (no extra evidence) | functional |
| Eligibility | per-candidate, per-component usability with reason codes | `percival/eligibility.py` | — | — | functional (v5.24) |
| Datasets | versioned manifests | `percival/datasets.py` | — | — | functional (v5.24) |
| Registry / ledger / shadow / store | versions, acceptance, deploy and rollback, immutable predictions, shadow evaluation, schema and migrations | `percival_gui.py`, `percival/store.py` | — | — | functional |
| Unified Score model ("Predictor model") | separate logistic model on the 5 predictors; fixed M-cohort | `unified_score/` + `unified_gui.py` | yes (own reader) | **no** | disconnected (prototype) |
| Stage-1 engine ("Shadow ML") | shadow runner of the Stage-1 engine | `uengine/shadow.py` + `shadow_engine_gui.py` | no | **no** | disconnected (prototype; synthetic model only) |
| Image prototype ("Image ML") | image model on synthetic phantoms | `uengine/imaging/image_infer.py` + `image_ml_gui.py` | no (synthetic truth) | **no** | experimental / disconnected |
| "Training" dashboard | cards of the prototypes, label table, synthetic image evaluation | `training_gui.py` | — | **no** | functional dashboard; superseded by the Training Center |

## 4. Data flow

```
candidates.csv ──► MATH logit ───────────────────────────────────────┐
uscore/features ─► 5 predictors (reliable only; else missing flags) ──┤
measurements ────► Characteristic ML logit ─┐                         ├─► meta-model ─► calibration ─► Percival Score 0-100 ─► band
MRI patch ───────► Image ML logit (+TTA) ───┴─► Fusion logit ─────────┘        │
                                                   Intelligence: OOD, disagreement pattern, QC, missing ─► status + reasons
```

## 5. Expert review → training

```
reviewer key press ─► review/ID_calls_<reviewer>.csv (+ ID_review_log, ID_final_<reviewer>.json)
earlier project review ─(fingerprint, verified copy)─► historical/ID/review/
                 │
call ledger (all reviewers · Vein→Vessel · fingerprint re-attachment · lineage · policy) + earlier-version calls (current call wins)
                 │
eligibility.evaluate ─► per component: char / image / fusion / meta · reason codes · partition (development | locked test)
                 │
datasets.build ─► percival/datasets/dsNNN.json (content hash; unchanged data → same id)
                 │
train_cycle ─► registry/vNNN/model.json (data.dataset = dsNNN) ─► acceptance ─► active (or candidate ─► shadow mode)
```

## 6. Model versions and prediction provenance

```
registry/vNNN/model.json : engine version, dataset dsNNN (+ content hash), eligibility rules, feature schema, patch spec, code hash, seed,
                           families chosen, meta-model, calibration, thresholds, dev/test metrics, acceptance
active.json (+ promotions.json) : which version is active, the rollback target, who / when / why
ledger/ID/vNNN__run.json  (immutable) : every candidate's score, band, status, reasons, ALL component values, provenance
scores/ID.json            (current)   : what the reviewer shows
shadow/vNNN/ID.json       (never shown): shadow predictions + summary (vs active, prospective calls)
reviews/ID/reviewer__time.json (immutable): the expert labels + what Percival showed at review time
Display: current | historical (other model) | earlier processing (other run)
```

## 7. Duplicated, disconnected, incomplete, broken

| Kind | Item | Evidence | Handling |
|---|---|---|---|
| broken (fixed) | Old reviews not used for learning (shared file, `Vein`, partial reviews, re-detection, historical copies, orphans) | user's failure "cSS 1 / not cSS 33"; `check_percival_learning.py` A–F | v5.24 label source + eligibility |
| broken | Predictor model training on app projects | trace step 8: FileNotFoundError for the fixed manifest | kept as a hidden prototype; not part of the score |
| disconnected | Image ML prototype, Stage-1 engine | trace steps 5 and 6: outputs consumed by nothing | hidden prototypes; shadow mode moved into Percival |
| duplicated | Stage-1 MATH / characteristics / fusion / calibration / patient split vs Percival | code | Percival is the one path; prototypes kept |
| duplicated | "Training" label table vs Training Center | code | both read the same files since v5.24; Training Center is the workflow |
| duplicated | Unified Score model vs Percival meta-model | code | Percival uses the predictors, not that model |
| incomplete | Unified predictors unreliable without anatomy | trace step 4 | now visible in the Overview ("candidates with a reliable predictor") |
| incomplete | the Percival app test used hand-made predictors | `check_app_percival.py` fixture | the trace now runs the real extraction (in the suite) |
| conflicting info (fixed) | three label readers (Percival, label table, Unified) | code | Percival and label table now agree; the Unified reader stays separate by design (held-out protection) |
| not implemented | clinical validation | n/a | requires expert-labelled clinical cohorts |

## 8. Recommended final architecture and plan

Recommendation: **one Percival core with shared records, and the prototypes kept but out of the workflow.**

1. The single ML orchestration is Percival's training cycle: one eligibility engine, one dataset version, one registry.
2. Family-specific choice and evaluation stay inside it (*Evidence & reliability*).
3. The shadow experiment is part of the Model Center, so experiments run on real candidate models and can never deploy themselves.
4. Data lives in a versioned store with migrations; reviews from earlier projects are recoverable.

Creative additions that were implemented:
- **prospective shadow evaluation**: AUC on expert calls a model never learned from;
- **content-hashed datasets**: no duplicate snapshots;
- **reliability-aware inputs**: unreliable predictors count as missing and are reported.

Remaining plan, carried out in this session:
1. Full test suites.
2. Build the v5.24 package.
3. Install-and-update test from the packages: v5.23 project with a trained model and old-style reviews → v5.24 → restart.
4. Final report.

Later, outside this session:
- retire the Stage-1 prototypes after a release in which nobody needed them;
- give `patients.json` a schema version;
- clinical validation.
