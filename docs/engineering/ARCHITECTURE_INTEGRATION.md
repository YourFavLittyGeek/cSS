# PERCIVAL architecture integration (development tree, uncommitted)

Builds the intended architecture on the working implementation (see ARCHITECTURE_RECONCILIATION.md). No second detector, CNN, scoring
engine or annotation system was added. Synthetic data only; nothing installed, trained on real data, promoted or committed.

## Terminology (user-facing ↔ implementation)

| User-facing name | Meaning | Implementation |
|---|---|---|
| PERCIVAL | integrated cSS AI system | the whole application |
| ALBUS · Mathematical Detection | candidate generation, rules E1–E30, score_v4 | `scripts/detect_css.py`; engine input `math`; framework `uengine/albus_detection.py` |
| NOX · Quantitative MRI Analysis | detector measurements + uScore x1–x5 | engine inputs `char` (9 measurements) and `unified` (x1–x5) |
| LUMOS · Visual Intelligence | image network on MRI patches | the engine's `image` component (SmallCNN); `uengine/lumos.py` loads the SAME registry weights |
| PERCIVAL Decision Engine / PERCIVAL score | trainable decision and its 0–100 output | `uengine/percival/meta.py` (meta-model + calibration + OOD + thresholds) |
| CORE · Fixed-Weight Baseline | comparison only | `uengine/percival_core.py`, off by default, output only under `experimental_core` |
| PENSIEVE · AI Memory and History | per-project memory rebuilt from authoritative records | `uengine/pensieve_index.py` |
| SHADOW · Experimental Discovery Lab | governed hypothesis → discovery → PERCIVAL confirmation → human approval | `uengine/shadow_governed.py` + `uengine/percival/component_registry.py` |
| uScore scorer (prototype) | separate older scorer | `unified_score/uscore` model: training disabled; its x1–x5 extractors feed NOX |
| Stage-1 prototype | older shadow-mode engine | `uengine/shadow.py` (not SHADOW) |

Internal identifiers (`math`, `char`, `unified`, `image`, `fusion`, `percival_score`, file names, API paths) are unchanged: they are data
contracts of saved models, ledgers and tests.

## What was implemented
- **Candidate contract** (`uengine/percival/architecture.py`, `GET /api/percival/contracts?code=`): identity + fingerprint, ALBUS / NOX /
  LUMOS evidence each with an explicit state (`valid | missing | untrained | uncalibrated | failed`), the PERCIVAL decision, pairwise
  disagreement of every available component pair with the cSS rate of that pattern in expert-reviewed development data, component
  versions, provenance. Missing evidence has value `None`, never a negative. No patient id. Blind-gated like the scores.
- **LUMOS**: `LumosImageIntelligence.from_percival_model(model)` uses the registry CNN weights; without them `analyze_patch` returns
  status `untrained` and no probability (previously a random network reported `ok`). The CORE comparison path uses it.
- **Component versions**: every newly trained model records `component_versions` (content hash per component, owner). `component_report()`
  maps the existing out-of-fold metrics, ablation, disagreement, calibration, OOD and split to ALBUS / NOX / LUMOS / PERCIVAL.
- **PENSIEVE**: per-project index `<project>/percival/pensieve/pensieve_index.db`, rebuilt from reviewer journals + call ledger + missed
  marks + prediction ledger; stable candidate UID from the fingerprint; expert calls (with role, read phase, AI visibility, provenance class)
  and predictions in separate tables with CHECK constraints; false positives / missed lesions attributed to the ALBUS detector VERSION;
  atomic rebuild, reproducible digest, idempotent per-study update after every reviewer save; failures returned and written to
  `percival/pensieve/status.json`. The reviewer's old direct writes (duplicates, mismatched ids, lost provenance, swallowed errors) are
  removed. The legacy `pensieve.db` and its local journal are now per project (`$CSS_BASE/app_data/`).
- **SHADOW**: development patients only (locked-test refused), locked discovery / confirmation split, pre-registered hypotheses, label-like
  variables refused, patient-grouped CV on discovery, PERCIVAL-only one-shot confirmation on unseen patients (effect size, CI, failure cases),
  approval only by a named person with the typed phrase `APPROVE COMPONENT CHANGE` and a reason, synthetic evidence refused unless stamped,
  approval → new NOX version, rollback. The old fixed trials remain as labelled synthetic demonstrations and never record "replicated".
- **ALBUS framework**: per detector version (build + rule set + parameter hash): eligible detected cSS, expert-marked missed cSS,
  sensitivity with Wilson CI, FP per study, whole-study search coverage; `compare()` rejects any version that loses sensitivity or an eligible
  lesion whatever its FP gain; approved versions recorded in the component registry, never applied automatically.
- **GUI**: PERCIVAL screen with System (component states from the project), ALBUS, PENSIEVE, SHADOW tabs; architecture names in the
  navigation, component columns, tables, notifications and reviewer; the setup card no longer claims "VERIFIED READY" models.
- **I0**: uScore training gate (`--research-unverified` only, stamped); content-hash cache keys incl. the roles journal.

## Not done / next steps
- The PERCIVAL Decision Engine still trains on its built-in 9 NOX measurements; reading an approved NOX configuration during training
  needs a model-format change (feature list stored in the model) - designed, not implemented.
- SHADOW implements the `nox_measurement` kind only; ALBUS rule and LUMOS pattern hypotheses can be registered but report
  "not implemented".
- Components are still retrained together per cycle (component hashes recorded, not independently promotable).
- No real data: every component state is "awaiting data / untrained" on a new project; no metric here is evidence.

## Defects found and fixed during integration testing
- **Reviewer race (pre-existing since 2026-11-11, `review_web.py Study._excluded`)**: two concurrent requests could see `_aud_xl` set before
  `_aud_xd` → `AttributeError` → "request could not be completed". This was the unexplained intermittent 3A.1 concurrency failure; the
  slightly longer saves (PENSIEVE update) made it more frequent. Fixed by publishing `_aud_xd` before `_aud_xl`; reproducer 15/15 after
  (failed on run 1 before).
- **Tests that asserted untrained LUMOS predictions** (`test_lumos`, `test_master_end_to_end_rebuild`, `test_adversarial_scientific_acceptance`):
  they expected status `ok` and a probability from a randomly initialised network. Updated to test the inference mechanics with explicit,
  labelled weights and to assert `untrained` without weights.

## Consolidation mission (2026-11-24): Stages 1–8
Synthetic data and temporary projects only; nothing installed, no real-data training, no model or rule promoted.

| Stage | What exists now | Where | Tests |
|---|---|---|---|
| 1 Retire | governance promotion refuses; Shadow Lab trials synthetic-only; legacy engines on null memory / null Vault; CORE uses real NOX measurements (missing → unavailable); legacy PENSIEVE routes and in-app uScore freeze / score-all retired; frozen bundles removed | `uengine/legacy_guard.py`, `docs/engineering/DEPRECATIONS.md` | `test_stage1_retirement.py` |
| 2 Interface | `features / version / reliability / train / evaluate` for ALBUS, NOX, LUMOS; the engine reads inputs through it; the NOX feature list is stored in the model (old models load with the built-in 9); training uses the ACTIVE approved NOX version; frozen component families (no re-selection) with the meta-model refitted on top; per-component freeze / rollback (named person, typed phrase) | `uengine/percival/component_api.py`, `meta.py` (`features=`, `frozen=`), `percival_gui.component_freeze` | `test_stage2_components.py` |
| 3 Model | `stack_unc` meta-model candidate (neutral missing fill, missing indicators, ALBUS rule fate, NOX missing fraction, LUMOS TTA spread, |gap| of every component pair; 1-SE rule, inside nested CV); per-candidate pairwise disagreement + top NOX measurements; performance by available inputs; LUMOS augmentation / balanced sampling / seed ensemble (`cnn_ensemble`, via the LUMOS registry); learning curve; subgroup calibration (never applied automatically); abstention policy (two triggers → review required, no score); study-level agreement (kappa, Bland-Altman) vs `labels/expert_grades.csv`; reproducible model hash; second-review priority (blind-gated); NOX stability selection → SHADOW hypotheses only | `meta.py`, `analysis.py`, `cnn.py`, `shadow_governed.suggest_nox` | `test_stage3_model.py` |
| 4 Detection | SHADOW kinds `albus_rule` (sensitivity-gated against the current detector output on the same studies; any lost eligible cSS rejects; approval records a proposal, the detector is never changed), `interaction`, `lumos_pattern`; millimetre matching tolerances when the voxel size is known (voxel fallback unchanged) | `shadow_governed.py`, `css_common.match_one_to_one`, `call_ledger.py` | `test_stage4_detection.py` |
| 5 Authority | one identity service (gathering, split, leakage audit, SHADOW); hash-chained event log (detection runs, training runs, approvals, component changes, rollbacks, configuration) with registry replay / verify / rebuild; one versioned configuration record per training run | `uengine/identity_service.py`, `uengine/event_log.py`, `percival_gui.config_snapshot` | `test_stage5_6_governance.py` |
| 6 Governance | pre-registered evaluation plan + milestones; the locked test cohort supports acceptance once per milestone (every consultation recorded); automatic cycles OFF by default; inter-reader kappa baseline; drift monitoring by field / sequence / anatomy | `percival_gui` (evaluation plan, `test_reuse_gate`, `drift_state`), `pensieve_index.reader_agreement` | `test_stage5_6_governance.py` |
| 7 Engineering | headless-Chrome harness (temporary profile, mock keychain, no background networking, longer first render; unusable browser → SKIPPED, rc 77); K14 / T4 references updated with reasons; fast profile `tests/run_fast.py`; local HMAC signatures on approvals (key outside the project; does NOT authenticate persons - deferred) | `tests/_chrome.py`, `uengine/approval_signing.py` | `test_stage5_6_governance.py`, `check_app_percival.py` |
| 8 GUI | System page: purpose / inputs / outputs / version / status per component, readiness with categorised missing prerequisites, validation governance, small-data honesty, configuration + event-log integrity, retired layers; NOX / LUMOS names in the PERCIVAL screens and the reviewer | `percival_view.js`, `review_web.html` | `check_app_percival.py` |

Not done: the image network does not consume approved LUMOS patterns; approved ALBUS rules are proposals until a reviewed detector release; optional phase / FLAIR patch channels (patch maps are SWI only); self-supervised LUMOS pretraining; per-person authentication of approvals.
