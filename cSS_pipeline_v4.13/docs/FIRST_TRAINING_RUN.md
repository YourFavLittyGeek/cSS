# PERCIVAL — first real training run (Percival Score learning engine)

Research software. Not for clinical use. Synthetic test results are never real-data performance.

## What trains
The trainable model is the **Percival Score learning engine** (`unified_engine/uengine/percival`): characteristic, image and fusion
components, a meta-model chosen by patient-grouped cross-validation, calibration, and a locked patient-level test cohort. ALBUS / LUMOS /
NOX / CORE are an experimental heuristic layer (off by default) without a dataset-consuming training interface.

## Names used in the app
PERCIVAL is the integrated system: **ALBUS** (mathematical detection, the detector), **NOX** (quantitative measurements + uScore x1–x5),
**LUMOS** (the image network), the **PERCIVAL Decision Engine** (the trainable meta-model; its output is the PERCIVAL score), **CORE**
(fixed-weight comparison baseline, never the prediction), **PENSIEVE** (memory) and **SHADOW** (discovery lab). The first run trains the
PERCIVAL Decision Engine; ALBUS / NOX / LUMOS contribute through it. Screen: PERCIVAL (left menu).

## Ground truth that counts
* Calls of **designated experts** (roles set by the administrator with a typed confirmation) who **completed** their review.
* Per candidate, the completed experts agree (consensus, default quorum 1); a disagreement, an expert who completed the review without a
  call on the candidate, or only abstentions → unresolved (never trained on). Adjudications are recorded but are not training labels.
* Provenance class **verified_blind_post_3A** (blind first read recorded by the server) or **historical_blinding_verified** (an older read
  with a documented verification of exactly those calls). Everything else is kept, shown, and excluded with a reason.
* Missed-cSS marks of designated experts with eligible provenance.

### Exact consensus behaviour (default rule: consensus of designated experts, quorum 1)
Participants = designated experts who COMPLETED their review of the study. Per candidate, only definite calls vote (cSS / not-cSS classes;
Near ICH = out of scope); **Unsure is an abstention, never a vote and never an effective call**.
| Situation | Status | Trained on? |
|---|---|---|
| every completed expert agrees (≥ quorum definite votes) | resolved (effective call = the most frequent subtype among the votes) | yes, if the provenance class is eligible |
| one expert Unsure, the other(s) definite and agreeing | resolved by the definite call(s) only | yes (raise the quorum to require more votes) |
| all experts Unsure | abstained | no |
| definite calls of different classes | disagreement | no (an adjudication is recorded, not ground truth) |
| fewer definite votes than the quorum | insufficient | no |
| a completed expert made no call on the candidate | incomplete (never resolved by the others) | no |
| experts still reviewing | pending_review | no |
| only non-experts called it / nobody did | no_expert / missing | no |

## Before you start (checklist)
1. Import and process the new cohort in the app (FreeSurfer anatomy, detection, QC). Check every study's patient identity
   (Training Center › Patient identity) — the patient is the unit of the split.
2. Reviewer calls › **Set role…** → `expert` for each designated expert (typed `ASSIGN ROLE` + reason); optionally **Allow adjudication…**.
3. Each expert opens the reviewer from the app and completes a **blind first read** of every study: every candidate called (Unsure is a
   call), then the final save. Optionally File › *Whole-study search for missed cSS* (no candidates shown) and *Search complete*.
4. Reviewer calls: check the per-study table (resolved / disagree / abstained / no expert call); adjudicate if needed (recorded only).
5. Percival Intelligence › **Switch on** (local learning).
6. Training Center: the **readiness** card at the top must show ✓ for every check (designated experts, local learning, eligible labels
   ≥ 3 cSS + ≥ 3 not-cSS + ≥ 10 in development, verified identities, locked split, last dataset audit).

## Start the run
Training Center › **Train** — or, from the same Mac while the app runs:

    curl -s -X POST -H 'X-CSS-App: 1' -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:8800/api/percival/train

The run: builds the dataset manifest (`percival/datasets/dsNNN.json`: every candidate with label, provenance class, consensus status,
reviewer, partition, source-file hashes, split version) → saves the leakage audit (`percival/split/audit_dsNNN.json`) → **refuses to start**
on any audit failure or non-eligible label → trains → registers `percival/registry/vNNN/model.json` (records dataset id + content hash,
split, audit, rules, code version) as *candidate* / *experimental*. Nothing becomes active without your approval in Model Center.

## After the run
* `GET /api/percival/runs` — run record; `GET /api/percival/split` — split version and audits.
* `POST /api/percival/dataset_export {"id": "dsNNN"}` → `percival/exports/dsNNN_<time>/` (examples.csv, manifest.json, split.json, SHA256SUMS).
* The locked test cohort is never trained on; changing the test fraction needs a new split version (previous test patients stay test).

## Command-line administration (optional)
`CSS_BASE=<project> python scripts/review_admin.py roles | role "NAME" expert --by ADMIN --reason TEXT --confirm "ASSIGN ROLE" |
status STUDY | adjudicate STUDY CAND CALL --adjudicator NAME --reason TEXT | verify STUDY REVIEWER ... --confirm "VERIFY BLINDING"`.
Existing reviews: `python scripts/review_migrate.py plan` (read only) before any `apply`.


## Before the first real cohort (consolidation, 2026-11-24)
- Automatic training cycles are **off** by default (`percival_autocycle`); start each cycle by hand in Training Center.
- Register the **evaluation plan** (PERCIVAL › System › Validation governance: test size, metrics, acceptance, external / temporal validation)
  and declare the first **milestone** before training. Without them a locked-test result is reported but cannot support acceptance; the locked
  test cohort supports acceptance once per milestone.
- Expert patient-level grades for the study-level check go in `labels/expert_grades.csv` (`study,total`), entered by the experts.
- A 10-20 patient pilot is a technical pilot: below the engine's minimum data (30 studies, 10 per class) and below 5 test patients per class,
  acceptance cannot pass; any activation is an override with a recorded reason (research use).
