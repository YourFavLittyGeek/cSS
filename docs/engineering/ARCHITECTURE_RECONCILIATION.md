# PERCIVAL — Architecture reconciliation (investigation only)

Status: read-only investigation, 2026-11-24. No code changed, nothing activated, committed or installed; Vault not accessed; no database
opened for writing. Evidence = the code at `106593a` (+ the uncommitted, paused safety-review edits: uScore training gate, content-hash
cache keys), Git history, and call/data-flow tracing. File:line references are to `cSS_pipeline_v4.13/`.

## 0. How the current state came about (Git)

| Date | Commit | Identity | Added |
|---|---|---|---|
| 2025–Nov 2026 | many | Claude / user | MRI pipeline: `run_css.sh` → `prep_anat.sh` → `detect_css.py` (+ `css_vessel`, `css_pieces`, `css_shape`, `css_features`, `mimic_rules`, `css_tiers`) → reviewer → `score_css.py`; detector rules E1–E30, probes (`zone/struct/shape/midline_probe.py`, `v53_compare.py`), ranker (`train_ranker.py`), learned exclusion confidence (`fit_confidence.py`, E30) |
| 19 Nov | `25ba19e` | Claude | uScore (`unified_score/uscore`): predictors x1–x5 + own ridge model, cohort manifest, `LabelAccess` held-out protection |
| 20 Nov | `faea197` | Claude | `uengine` shadow MODE (`shadow.py`, `run_engine.py`), `unified_fusion.py` (gate-locked), synthetic `experiment.py` |
| 21 Nov | `a2637fa`, `5bca173` | Claude | Percival Score engine (`uengine/percival/`: meta-model, CNN, learners, intelligence, eligibility, datasets, store) |
| 22 Nov | `84dafdd` | "Your Name" (Gemini sessions) | ALBUS, LUMOS, NOX, PERCIVAL CORE, PENSIEVE, SHADOW Lab, GOVERNANCE, Vault — one commit ("v5.25"); CORE wired to overwrite the trained score |
| 23 Nov | `73b4ec0` (Phase 0, approved) | Claude | ALBUS/LUMOS/NOX/CORE layer gated by `features.experimental_core` (default off); may no longer overwrite the trained score |
| 23 Nov | `8c2f611` (3A.3, approved) | Claude | Pensieve-only missed lesions no longer become training labels (no provenance) |
| 24 Nov | `106593a` (3B–3D) | Claude | No component file changed; Shadow Lab stops claiming a leakage audit, labels its cohort |

So the named architecture (ALBUS/NOX/LUMOS/CORE/PENSIEVE/SHADOW) was added **after** the working pipeline and the trainable engine, as a
parallel set of modules, and was never wired to their data. Nothing was renamed or removed since.

## A. Component inventory

| Component | Actual implementation | Current responsibility | Inputs | Outputs | Connected status | Learning capability | Missing functionality |
|---|---|---|---|---|---|---|---|
| **ALBUS** (named module) | `unified_engine/uengine/albus.py` | 3 hand formulas over a feature dict (`formula_v4_baseline` restates `score_v4`); adaptive threshold; `learn_from_missed_lesion`, `learn_from_pensieve` | feature dict (when called from the app: **default values** — `gather()` rows carry no `pdist/darkness_z/ci/…`, `percival_gui.py:_gather`) | `AlbusCandidate`; writes `candidates_memory`, "ALBUS false positive" corrections to Pensieve | **Disconnected** (only `percival_gui._experimental_core` / `score_study_unified`, off by default; Shadow Lab) | Methods exist, **no caller** outside tests | Never reads MRI; no access to real features; learning never invoked |
| **ALBUS** (actual detection function today) | `scripts/detect_css.py` + helpers; `score_v4`; rules E1–E30; `RULESET`/`rule_version`; `review/ID_manifest.json` | Generates candidates from SWI + anatomy; excludes mimics; ranks | NIfTI SWI/T1/FLAIR/phase, labels | `ID_candidates.csv/.nii.gz`, `ID_excluded.csv`, `ID_dropped.csv`, QC, manifest | **Connected** (production) | Human-in-the-loop: thresholds fitted offline by probes against reviewer calls with "protected cSS"; optional learned exclusion E30 (`fit_confidence.py`, lopo_min cut) and ranker (now `--research-unverified`) | No automatic, versioned, validated adaptation loop; not named ALBUS; feeds Percival only as `math` (score_v4 Platt-recalibrated, order unchanged) |
| **NOX** (named module) | `uengine/nox.py` | Range/validity checks on a feature dict; custom-feature registry | feature dict (defaults in app) | `NoxMeasurements` | **Disconnected** | `learn_from_pensieve`: no caller | Measures nothing itself |
| **NOX** (actual quantitative function) | `detect_css.py` columns (CHAR 9: darkness_z, edge_contrast, pial_dist_mm, cortex_frac, tram_frac, tube_ratio, elongation_3d, volume, local_cont_max_mm); `css_features.py` (v5.1.2, ~25 recorded-only); `css_shape` struct_*; `surface_features.py`; region_z; **uScore x1–x5** (`uscore/features.py`, reliable/unreliable/unavailable) | Quantitative description of each candidate | MRI-derived maps, candidates | CSV columns; `uscore/features/ID.json` | **Connected**: CHAR → Percival `char`; x1–x5 → Percival `unified` (`percival_gui._predictors`) | `char` and `unified` are L2-logistic components trained in `meta.train_cycle`; component ablation in `intelligence.py` | Feature-level informativeness / discovery; most recorded features (css_features, struct_*, surf_*) never reach a model; no versioned feature registry tied to models |
| **LUMOS** (named module) | `uengine/lumos.py` (wraps `percival/cnn.py SmallCNN`) | CNN patch inference + TTA | patch arrays (app passes **None** → "no visual evidence") | `LumosInference` | **Disconnected** | Loads weights only from Vault `models/LUMOS/`; otherwise untrained baseline; no training call | Not linked to the trained Percival CNN |
| **LUMOS** (actual image function) | Percival `image` component: `SmallCNN` trained in `meta.train_cycle` on `uengine/imaging/patches` (`percival_gui._maps`) | Learns from MRI patches; TTA spread; image OOD | patch maps per candidate | image logit per candidate (`components.image`) | **Connected** (training + scoring) | Trained (patient-grouped OOF) | Not independently versioned/promotable; likely weak with few patients (ablation will show) |
| **PERCIVAL** (named CORE) | `uengine/percival_core.py` | Fixed weights (ALBUS .25, LUMOS .40, NOX .30, interaction .15, bias −.8), fixed Platt; 0–100 "Percival Score", bands | the three named modules' outputs | `PercivalAssessment` → only `s["experimental_core"]` | **Disconnected** since Phase 0 (before: overwrote the trained score) | `fit()` exists, **no caller** | Untrained; inputs are defaults |
| **PERCIVAL** (actual central engine) | **Percival Score engine** `uengine/percival/meta.py` + `learners.py`, `intelligence.py`, `nested.py`; app `percival_gui._train/score_study`; registry, runs, prediction ledger | Combines 5 components (math, unified, char, image, fusion); meta-model family chosen by patient-grouped CV (1-SE rule); Platt; bootstrap thresholds; OOD; per-candidate reasons, components, contributions, pairwise disagreement patterns; manual promotion | gathered rows + eligible expert labels via dataset manifest + locked split + leakage audit | `registry/vNNN/model.json`; `scores/ID.json`; immutable `ledger/` | **Connected** (training path; scoring after promotion) | Yes (only working training path) | Components retrained as one bundle (no per-component version/promotion); disagreement pattern at scoring only for char×image; no intake of SHADOW proposals; ALBUS evidence only recalibrated, not learned; does not use Pensieve |
| **PENSIEVE** | `uengine/pensieve.py` (SQLite, 8 tables) + `DurableLocalJournal` | Intended shared memory | reviewer calls/completion (`review_web.py:522–541, 1097–1114`), ALBUS/CORE candidates, Shadow findings, governance promotions | `pensieve.db`; GUI tiles (`percival_view.js:117–118`); `/api/percival/pensieve*`, `missed_lesions` | **Partially connected, functionally broken** (see §5) | none (store) | Per-project DB, study registration, stable IDs, provenance, idempotence, rebuildability |
| **SHADOW** (Lab) | `uengine/shadow_lab.py` + `governance.py`; app `shadow_lab_state`, `shadow_run_trial` (`/api/percival/shadow_run`) | Fixed, hard-coded trials per component; proposals; governance evaluate/promote/rollback | cohort from `pensieve.get_training_dataset` (never populated → always the **random synthetic** cohort) | experiments, proposals, Pensieve `scientific_findings`, `model_evolution`, Vault `promoted_active.json` | **Disconnected from real data**; promotion writes records **nothing reads** | none real; LUMOS trial uses the **true label** (`depth_signal`) | Real data access, hypothesis registry, discovery/confirmation separation, PERCIVAL re-validation, component promotion |
| SHADOW-like capabilities elsewhere | probes (`zone/struct/shape/midline_probe.py`, `v53_compare.py`, `rule_test.py`), `intelligence.ablation/disagreement/OOD`, `classify_surface_patches` ablations A–G, `unified_fusion.incremental_value`, `experiment.py` (synthetic) | read-only feature/rule discovery against calls; incremental value | candidates + calls | reports/CSVs | human-run tools / inside train_cycle | — | No common experiment record, no promotion path |
| shadow MODE | `uengine/shadow.py`, `run_engine.py shadow` | Unified Score engine NEXT TO the output (deterministic fallback) | candidates, QC, score | `unified_engine/shadow/ID.json` | hidden prototype screen | synthetic demo model only | Not discovery; overlaps Percival scoring |
| **uScore** (a) features | `unified_score/uscore/features.py`, `detectors.py`, `perturb.py` | x1–x5 with reliability; perturbation stability | candidates + MRI | `uscore/features/ID.json` | **Connected** (Percival `unified`) | n/a | — |
| **uScore** (b) model | `uscore/pipeline.train/score/freeze/evaluate_heldout`; `run_unified.py`; app "Unified (experimental)" | Separate ridge scorer with own cohort manifest/split and held-out protection | derived `ID_calls.csv`, study-level split | `uscore/model_*.json`, reports | Hidden prototype; training disabled (paused review, uncommitted) | ridge LR (no Phase 3A provenance) | Redundant as a scorer (Percival `unified` is already an L2 logistic on x1–x5) |
| **Percival Score** | = the actual central engine above | | | | | | |

## B. Original versus current

| Intended | What exists | Connected? | Overlap | Missing | Contradiction? |
|---|---|---|---|---|---|
| ALBUS: adaptive mathematical detector | detect_css (real) + albus.py (formula shell) | detect_css yes; albus.py no | albus `formula_v4_baseline` ≡ score_v4; ranker; E30 | automated, validated, versioned adaptation | albus.py claims "discovery from MRI" but only sees feature dicts; Pensieve attributes **every** expert rejection to ALBUS even though detect_css proposed the candidate |
| NOX: quantitative features, learns informativeness | detect CHAR, css_features, struct, surface, uScore x1–x5; nox.py validator | CHAR + x1–x5 yes; rest recorded only; nox.py no | uScore reliability states ≈ NOX validity | feature-level discovery & registry | none fundamental |
| LUMOS: visual patterns | Percival CNN (trained); lumos.py (same class, untrained) | CNN yes; lumos.py no | identical network class | link lumos.py to trained weights; independent versioning | lumos.py historically reported random weights as usable (Phase 2 finding) |
| PERCIVAL: learned evidence integration, disagreement, traceability | Percival Score engine; percival_core.py | engine yes; core no | two things both called "Percival Score" | per-component versions; SHADOW intake; all-pair disagreement at scoring | **naming collision**: a fixed-weight heuristic and the trained model share the name |
| PENSIEVE: shared memory for all | pensieve.db + journal; real working memory is elsewhere (call ledger + reviewer journals = ground truth; percival store = datasets/registry/prediction ledger; uscore/ outputs) | partially; broken | Pensieve duplicates ledger/journal/prediction-ledger roles | working, per-project, provenance-preserving store | hard-coded to the live project path (`DEFAULT_LIVE_PENSIEVE_DB = ~/Percival_project/app_data/pensieve.db`) regardless of project |
| SHADOW: hypothesis → experiment → PERCIVAL validation → promotion | Shadow Lab (fixed trials, synthetic), governance (records only), probes (real but manual) | no | probes ≈ discovery; intelligence.py ≈ evaluation | real-data experiments with separation; independent validation; promotion into components | LUMOS trial uses the label (self-validation leak); API promotion with `override` writes "active" to `model_evolution` although nothing became active |

## C. Data flow

### C1. Current actual data flow (`═══` = implemented and used; `---` = implemented, off / not reached; `···` = broken)

```
 MRI (raw/ID) ══> prep_anat (FreeSurfer) ══> detect_css.py ══> review/ID_candidates.csv (+score_v4, CHAR, QC, manifest)
                                                  │                         │
                                                  │                         ├══> uscore extract ══> uscore/features/ID.json (x1–x5)
                                                  │                         ├══> imaging/patches ══> patch maps
                                                  ▼                         ▼
                              browser reviewer (blind first read) ══> per-reviewer calls + journals ══> call_ledger (roles, consensus,
                                     │                 ···> Pensieve (journal / FK-failing inserts)      provenance, matching)
                                     │                                                                    │
                                     ▼                                                                    ▼
                                score_css.py (0–4)                                   label_summary → eligibility → dataset dsNNN
                                                                                       → locked patient split → leakage audit
                                                                                                          │
   rows: math(score_v4) + unified(x1–x5) + char(CHAR) + image(patches) ════════════════════════════════════┤
                                                                                                          ▼
                                                                   Percival Score engine: train_cycle (components + meta + Platt)
                                                                     → registry vNNN (candidate) → manual promotion
                                                                     → score_study → scores/ID.json + immutable prediction ledger
   --- ALBUS/LUMOS/NOX/CORE (features.experimental_core=off; default inputs) ---> s["experimental_core"] only
   --- uScore model (training disabled) ---  --- shadow MODE (prototype) ---
   --- Shadow Lab (synthetic cohort) ---> Governance ---> Pensieve model_evolution / Vault promoted_active.json (no reader)
```

### C2. Intended complete architecture (`═══` = exists and can be reused as is; `+++` = proposed new connection)

```
 MRI ══> ALBUS [detect_css + score_v4 + rules, versioned RULESET] ══> candidates ══╗
                                                                                 ║
          NOX  [CHAR + x1–x5 + registered extra features, with reliability] ═════╣ +++ component contract
          LUMOS[Percival CNN on patches, own version] ═══════════════════════════╣     (value, reliability, version, input hash)
                                                                                 ▼
                     PERCIVAL [meta-model + calibration + OOD + disagreement + reasons; per-component versions +++]
                                  │                                   ▲
                 AI decision ═════╪══> prediction ledger ═══+++══> PENSIEVE (per project; derived, append-only;
                                  │                                 expert vs model separated; stable candidate identity)
 expert review (blind) ═══> call ledger + journals ══════════+++══════════╝        │
          │                                                                       │ +++ development-partition data only
          └══> eligible ground truth ══> dataset + locked split + audit ══> PERCIVAL training
                                                                                  ▼
                     SHADOW +++ [hypothesis registry → experiment on discovery patients (development) → record]
                                  │ +++ proposal
                                  ▼
                     PERCIVAL +++ independent re-evaluation on confirmation patients (never seen by SHADOW); test locked
                                  │ +++ human approval (Model Center)
                                  ▼
                     new ALBUS / NOX / LUMOS version in the registry (rollback by registry status) ══> next cycle
```

## D. Integration plan (phased; preserves working code; no duplicate models)

**I0 — finish the paused safety review** (before first training): uScore training gate, content-hash caches + same-millisecond test,
abstention tests + documentation, release integrity. Keep the experimental layer off.

**I1 — component contracts and adapters (naming without moving code).**
- Define one per-candidate contract: `component, version, value, reliability, inputs_hash`.
- ALBUS adapter over `detect_css` outputs (score_v4, rule fates, RULESET, manifest hash) = today's `math` input.
- NOX adapter over CHAR + uScore x1–x5 (reliability states kept) = today's `char` + `unified` inputs; recorded-only features listed as NOX candidate features (not used until validated).
- LUMOS adapter = the Percival `image` component; `lumos.py` loads the registry's trained CNN weights instead of Vault-only/untrained (one network, no duplicate).
- `albus.py`, `nox.py`, `percival_core.py` kept as labelled baselines (CORE's fixed-weight fusion becomes a comparator in the meta-model discovery table, never a score).
- Resolve the naming collision in the GUI/docs: "Percival Score" = trained engine only.

**I2 — Pensieve as the safe shared memory.**
- Per-project location (under the project's Percival store), never a hard-coded live path; test isolation respected.
- Derived and rebuildable from authoritative sources (call ledger/journals with provenance class; prediction ledger with model version; detector manifests; matching decisions) → reproducible, cannot drift; idempotent keys (no `time.time()` ids).
- Study registration at import/processing; one candidate identity from the 3B matcher/lineage (retire Pensieve's own centroid matcher).
- Separate expert and model tables kept; corrections attributed to the detector version that produced the candidate, not "ALBUS" by default.
- Training continues to read the ledger/dataset; Pensieve serves history, queries and SHADOW. Existing `pensieve.db`: read-only migration plan first.

**I3 — PERCIVAL central engine extensions.**
- Per-component artifacts with their own version/hash inside the registry; components can be retrained/frozen independently, meta-model refitted on top; component-level reports (OOF metrics, ablation already exist).
- Disagreement patterns for all component pairs at scoring; "which component was right" statistics per pattern from expert-reviewed development data (extends `intelligence.disagreement`).
- Intake of SHADOW proposals as a separate evaluation job.

**I4 — SHADOW on real, provenance-checked data.**
- Data: development-partition dataset manifests + Pensieve history only; never test patients.
- Hypothesis registry (pre-registered: feature/formula, target component, primary metric, sensitivity constraint).
- Development patients split once into discovery / confirmation (patient-level, versioned like the locked split). SHADOW explores on discovery only.
- Experiments reuse existing tools: probes, `intelligence.ablation`, `unified_fusion.incremental_value`, nested patient-grouped CV.
- Proposal → PERCIVAL re-evaluates on confirmation patients → human approval → new component version → rollback through registry status.
- Replace the hard-coded trials (kept as demos labelled synthetic); remove the label-using LUMOS trial from any evidence path; governance records only what actually changed.

**I5 — ALBUS controlled adaptation.**
- Detector parameters/rules as versioned configuration; changes proposed through SHADOW, evaluated on missed-lesion recall (eligible expert missed marks + `label_missed` fates) with protected cSS; learned exclusion (E30 pattern) and ranker as ALBUS learning modes under the same gate.
- Re-detection after an approved change → 3B matcher carries calls; labels never change.

**I6 — complete loop**: scheduled cycles with human gates at promotion; audit report per cycle.

## E. First-training strategy

Use the Percival Score engine as it is; interpret its inputs as the architecture's components (documentation only at this stage):
- ALBUS contributes candidates and `score_v4` (fixed, recalibrated) + recorded missed-lesion fates (for later sensitivity work).
- NOX contributes CHAR (9) and uScore x1–x5 (reliable values only).
- LUMOS contributes the CNN on patches.
- PERCIVAL = meta-model with 1-SE selection, calibration, OOD, thresholds; registry candidate; manual promotion.
- Pensieve and SHADOW are **not needed** for the first run (training reads the call ledger → dataset → split → audit).

First realistic milestone: the first registered model trained on eligible expert labels of the development partition (≥ 3 cSS, ≥ 3 not-cSS,
≥ 10 labels; realistically 10–20 patients), with `component_metrics` and `intelligence.ablation` as the **first evidence of what each
component contributes**. With few patients the 1-SE rule will likely choose a simple model (math-only or an equal mean) — that is the
honest answer, not a failure. The locked test cohort is evaluated once, after freezing.

## F. Risks (priority order)

1. **Pensieve hard-coded to the live project path, shared across projects; silent write failures; misattribution** (`pensieve.py:248`, `get_pensieve` singleton, review_web sync) — any future consumer would read wrong or empty history. Not used for training now.
2. **Shadow Lab produces evidence-shaped output from synthetic data and a label-leaking trial; governance can record "active" promotions (with `override`) that change nothing** — risk of false discovery claims.
3. **Two "Percival Score"s / two COREs** — a fixed heuristic could again be presented as the trained model (code prevents it since Phase 0; names/GUI tiles still suggest it).
4. **Bundle retraining** — no per-component accountability or rollback; blocks "assign improvement to NOX/LUMOS/ALBUS".
5. **Duplicate scoring systems**: Percival meta, uScore model, CORE, shadow-mode unified engine, ranker, `unified_fusion` — confusion and parallel split/label paths (uScore's own manifest/split).
6. **Three candidate matchers** (3B `match_one_to_one`, `candidate_lineage`, Pensieve `evaluate_candidate_identity`).
7. **Detector thresholds fitted on M02–M11 reviewer calls** (in-sample; some by a non-expert reader) — ALBUS "learning" so far is unvalidated on independent data.
8. **LUMOS/CNN with few patients** — unstable; image OOD and ablation must be read before trusting it.
9. **Experimental layer receives default inputs** if switched on — constant, meaningless output.
10. GUI Pensieve memory tiles show empty/misleading counts.

## G. Roadmap

- **Before first real-data training**: I0 (finish the paused safety review); real cohort + experts + blind reads; readiness card all green. No architecture change required.
- **Initial PERCIVAL integration**: I1 (contracts/adapters, LUMOS weight link, CORE as comparator, naming), I3 (per-component versions, all-pair disagreement).
- **Complete self-improvement loop**: I2 (Pensieve per project, derived, provenance-preserving), I4 (SHADOW with discovery/confirmation separation and PERCIVAL re-validation), I5 (ALBUS controlled adaptation), I6.
- **Longer-term research**: NOX feature discovery over recorded-only features (css_features, struct_*, surface), surface-aligned patch models for LUMOS, phase/QSM-dependent features where available, multi-site calibration.
