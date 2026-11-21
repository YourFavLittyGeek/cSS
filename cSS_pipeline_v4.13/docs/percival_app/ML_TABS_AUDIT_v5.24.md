# The five ML tabs: audit and consolidation (v5.24, 2026-11-21)

Every statement below comes from following the code: the app module, the view, the subprocess command line and the engine functions it
calls. The tab names describe what the menu said before v5.24.

## 1. What each tab actually does

| | **Training** | **Predictor model** | **Image ML** | **Shadow ML** | **Percival Intelligence** |
|---|---|---|---|---|---|
| Code (app → engine) | `training_gui.py` / `training_view.js` → `run_imaging.py models / evaluate-synthetic`, `label_schema.build`, `unified_gui.validation`, `shadow_engine_gui.models`, `review_calls_gui.policy` | `unified_gui.py` / `unified_view.js` → `unified_score/run_unified.py` (`uscore/pipeline.py`: extract, train, freeze, score, heldout) | `image_ml_gui.py` / `image_ml_view.js` → `unified_engine/run_imaging.py` (`uengine/imaging/*`) | `shadow_engine_gui.py` / `shadow_view.js` → `unified_engine/run_engine.py shadow` (`uengine/shadow.py`, `math_component`, `characteristics_component`, `ml_component`, `unified_fusion`) | `percival_gui.py` / `percival_view.js` → `uengine/percival/{meta,learners,cnn,intelligence,eligibility,datasets,store}.py` |
| What it really is | **A dashboard.** It shows the other engines' model cards, the label table and evaluation panels, and can re-run a SYNTHETIC image-model evaluation. It trains nothing | The **Unified Score's own model**: one ridge logistic regression on 5 predictors, nested leave-one-patient-out, freeze with the typed word FREEZE, held-out evaluation via an authorization file. **Not a meta-model** | An image-model **prototype for synthetic phantoms only**. It refuses any project without the `SYNTHETIC_BASE` marker | The **Stage-1 engine in shadow mode**: recomputes MATH and the characteristics and applies a model from `unified_engine/models/`. The only model there is `synthetic_demo_offset` (trained on synthetic demo data) | The **Percival Score**: characteristic ML, image ML, fusion, meta-model discovery, calibration, thresholds, locked test, registry, ledger and Intelligence analyses |
| Reads | `unified_engine/models/image/*.json`, `app_data/eval/`, `review/*_calls*.csv`, `labels/` | `uscore/features/`, `unified_score/cohort_manifest_RECONCILED.csv` (**fixed list M01–M26**), `review/ID_calls.csv` through `LabelAccess` | synthetic `image_truth/`, the study MRI | `review/ID_candidates.csv`, `excluded.csv`, `qc.json`, `score.json`, `unified_engine/models/` | `review/` candidates, the call ledger (all reviewer files), `historical/`, `uscore/features/`, MRI patches |
| Writes | `app_data/eval/image_eval_*.json`, `labels/candidate_labels_v2.csv` (derived) | `uscore/model_*.json`, `development_report.json`, `reports/ID.json`; study columns `unified_*` | `unified_engine/image_ml/ID.json` | `unified_engine/shadow/ID.json` | `percival/` (registry, ledger, scores, reviews, datasets, shadow) |
| Trains / infers / evaluates | evaluates (synthetic only) | trains, freezes, infers, evaluates | infers (synthetic), trains on the synthetic generator | infers only | trains, infers, evaluates, deploys |
| Own dataset? | — | **yes**: its own cohort manifest and label reader (shared file only) | **yes**: synthetic generator truth, no expert reviews | none (no training on project data) | yes. Since v5.24 it is the one shared label source (call ledger plus earlier-version reviews), with eligibility and manifests |
| Gets expert reviews | displays them | through `LabelAccess` (shared `ID_calls.csv`, development roles of the fixed manifest) | **never** | **never** | call ledger (all reviewers, fingerprint-matched) plus earlier-version reviews |
| Consumed by | nothing | the reviewer's old "Unified score" card (hidden whenever a Percival assessment exists); **Percival uses the 5 predictors, not this model** | nothing | nothing | the reviewer (the one score) and the Studies list |
| Status | functional dashboard; partly duplicates the Training Center | functional for the M-cohort; **disconnected from Percival-era projects** (study keys outside the manifest have no role) | experimental; **disconnected** (synthetic only) | functional shadow runner, **but no real model**; duplicates MATH and characteristics; disconnected | functional; central |

## 2. Dependency matrix (row depends on column)

| depends on → | studies / candidates | call ledger (reviews) | uscore predictors | detector measurements | MRI patches | Unified model | Stage-1 engine | image prototype | Percival registry |
|---|---|---|---|---|---|---|---|---|---|
| Training (dashboard) | ✓ | ✓ (label table) | | | | ✓ (card) | ✓ (card) | ✓ (card, eval) | |
| Predictor model | ✓ | ✓ (shared file only) | ✓ | | | — | | | |
| Image ML | ✓ (synthetic) | | | | ✓ | | | — | |
| Shadow ML | ✓ | | | ✓ | | | — | | |
| Percival | ✓ | ✓ | ✓ | ✓ | ✓ | | | | — |
| Reviewer score | ✓ | | | | | (fallback card) | | | ✓ |

No component depends on Training, Image ML, Shadow ML or the Predictor model except their own screens. Percival depends only on shared
inputs.

## 3. Answers

1. **Single training orchestration: yes.** Percival's training cycle is now the one orchestration for every component that learns from
   expert reviews: characteristic ML, image ML, fusion and the meta-model. They share the eligibility engine, the dataset manifest and the
   patient-level split. The old Training tab never trained, and has been replaced by the Training Center.
2. **Separate configuration and evaluation, one infrastructure: yes, as built.** Each family is compared in the same cycle:
   characteristic ML (logistic / boosted trees / forest), image ML (pixel baseline / CNN), fusion (late / feature / hybrid). Each has its own
   evaluation (*Evidence & reliability*: family comparison, ablation, calibration) on one dataset version.
3. **Predictor model is not a meta-model.** It is the Unified Score's single logistic model on 5 predictors. Percival already uses those 5
   predictors as the "Unified Score" input of its meta-model. The separate model is redundant for the Percival Score and cannot train on
   projects whose study keys are not in its fixed manifest.
4. **Shadow ML** was a legitimate shadow *runner* (subprocess, time limit, never changes outputs) with no legitimate model: only a
   synthetic demo model exists. Its deterministic block recomputes MATH and the characteristics that Percival reads directly. v5.24 adds the
   valuable part to Percival as **shadow mode**: a trained candidate version scores every study apart (`percival/shadow/`), never shown and
   never used. It is compared with the active model and, prospectively, with expert calls it never learned from. Only *Make active*
   deploys it.
5. **Intelligence vs Fusion.** Intelligence adds no evidence twice:
   - No meta-model combines Fusion with the Characteristic or Image source it already contains (enforced in `meta.discover`).
   - Intelligence contributes reliability information that Fusion lacks: out-of-distribution distance, the disagreement pattern and its
     observed cSS rate, image TTA spread, study QC and missing sources.
   - Ablation reports whether each source adds information.
6. **Origin of the final Percival Score.** `meta.score_rows` takes the component logits, applies the chosen meta-model (picked by
   patient-grouped CV with the 1-SE rule), then ridge-Platt calibration × 100, then the bootstrap-stable thresholds. That gives the band
   and the status/reasons from Intelligence. The study score is computed with the reader's own `score_css.py` on the candidates scoring
   ≥ 50.
7. **Prediction provenance: yes for Percival.** Every prediction stores all component values and the model version. Since v5.24 it also
   stores the dataset id, the feature schema, the engine code hash and the processing run, in an immutable ledger file per model and run.
   Shadow predictions are stored apart. The prototypes store their own JSON with engine versions.
8. **Historical results across versions.**
   - The ledger is never rewritten. Each entry is marked current, historical or earlier processing.
   - v5.22/v5.23 stores are migrated with a backup.
   - Models without a manifest are shown as "before v5.24".
   - Prototype outputs stay where they are.
9. **Expert reviews for every component.** Since v5.24 there is one source: the call ledger plus earlier-version reviews. The eligibility
   engine reports per component (e.g. no MRI patch → not for Image ML or Fusion, still for Characteristic ML and the meta-model). The
   Predictor model keeps its own held-out-protected reader by design (its held-out audit). It is a prototype.
10. **Understandable without five tabs: yes.** The main menu shows one ML entry, Percival Intelligence:
    - Overview: how the parts fit together, with live input status.
    - Training Center: studies → reviews → eligibility → datasets.
    - Model Center: versions, dataset, acceptance, make active / roll back, shadow mode.
    - Data integrity.
    - Advanced: components, evidence, meta-model, explorer.

## 4. What was changed and what was kept

| Tab | Decision | Proof of safety |
|---|---|---|
| Training | Replaced in the workflow by the **Training Center**, which uses the same labels as training. Kept as the prototype "Labels & image evaluation" (hidden by default) | It trained nothing. Its label table now reads the same legacy files (`label_schema.build` reads the shared file and *Vein*). Its synthetic image evaluation is unchanged |
| Predictor model | Kept as the prototype "Unified Score model" (hidden). Percival keeps using its 5 predictors | Its model was never an input to the Percival Score. Reviewer fallback card unchanged |
| Image ML | Kept as the prototype "Synthetic image model" (hidden). Percival's own Image ML is the one trained on project reviews | It refuses non-synthetic projects, so no project result depends on it |
| Shadow ML | Kept as the prototype "Stage-1 engine" (hidden). **Shadow mode moved into Percival's Model Center** with a real candidate model | Its only model is synthetic. Its outputs (`unified_engine/shadow/`) are untouched |
| Percival Intelligence | **Central system**: shared records, eligibility, datasets, orchestration, registry, provenance, evaluation, shadow, migration | `tests/check_percival_learning.py`, `tests/check_app_percival.py` |

Nothing was deleted. Settings › *Show the older research prototypes* puts the four screens back in the menu. Their back ends, tests and
stored outputs are unchanged.
