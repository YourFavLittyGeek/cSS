# Phase 3B–3D — Ground-truth integration and first-training readiness

Uncommitted, uninstalled. Synthetic, isolated tests only. Base: `8c2f611` (Phase 3A.3–3A.6, committed).

## Key finding about "Albus"
`uengine/albus.py` is a heuristic discovery engine (formula registry, adaptive thresholds, Pensieve-driven "learning"); it has **no
dataset-consuming training interface**. The trainable model in PERCIVAL is the **Percival Score learning engine** (`uengine/percival`:
meta-model + char/image/fusion components, patient-grouped CV, Platt, ensemble, registry, manual promotion), which consumes the dataset
manifests. Readiness therefore targets that engine. No new model architecture was added; Albus stays an experimental layer (off by default).

## Changes
| Area | Change (files) |
|---|---|
| Part 1 consensus | Only designated experts who COMPLETED their review take part (blind read completed, pre-3A final record, documented verification, or a completed review_css session); a completed expert without a call → `incomplete`; experts still reviewing → `pending_review` (`scripts/call_ledger.py`). |
| Part 1 provenance | `historical_adjudicated` and new `adjudicated_post_3A` kept as categories, **not** eligible; eligible: `verified_blind_post_3A`, `historical_blinding_verified` only. A verification needs an existing review (`scripts/review_roles.py`). New eligibility reasons INCOMPLETE_REVIEW, REVIEW_NOT_COMPLETED, ADJUDICATED_NOT_CONSENSUS (`eligibility.py` 1.4, `app/percival_gui.py`). |
| 3B matching | `css_common.match_one_to_one`: one-to-one, centroid ≤ 2 voxels + volume ±15 % + same hemisphere; `ambiguous` (2nd candidate within 0.5 voxel), `contested` (two records → one candidate: none attached, even with identical calls), `no_candidate` (split / merge / gone). Used by the ledger (whole file, not row by row), the reviewer (`review_web.py`), `inherit_calls.py`, `match_calls` (same API, stricter) and `match_one`. Every decision is in the ledger entries and the derived `review/<ID>_matching.json`. Object-level split / merge lineage stays in `candidate_lineage.py` (only confident matches carry calls). |
| 3C dataset | `datasets.py` schema 1.2: deterministic order (no `hash()`), provenance class + consensus status per example, source-file hashes (candidates, detector manifest/build, reviewer files, journal heads, missed file) and split version **in the content hash**; `readiness()` refuses non-eligible / non-expert labels; `reproduce()` compares today's source hashes; `export()` (examples.csv, manifest.json, split.json, SHA256SUMS). |
| 3D split | New `uengine/percival/split.py`: one locked patient-level split per version (same salted rule as before, so existing assignments are reproduced); additions recorded; new version only with `NEW SPLIT VERSION` + person + reason; previous test patients always stay test; `leakage_audit` (patient in both partitions, same examination fingerprint, studies held out by study_meta / uscore used for development, no patient, non-expert label source, duplicates). App: test fraction no longer changeable once a split exists (`css_app.py`). |
| Training gate | `_train`: sources + split recorded, audit saved to `percival/split/audit_<ds>.json`, **training refuses** on a failed audit or readiness problem; the model records dataset id + hash, split, audit, rules, code version. Fixed a pre-existing crash: "not enough labels" now ends in the valid state `insufficient_data` instead of `invalid training-job transition`. `readiness()` checklist, `split`, `split_new_version`, `dataset_export` endpoints (`app/percival_gui.py`, `app/css_app.py`). |
| Part 5 legacy paths | `scripts/label_guard.py`: `train_ranker.py`, `evaluate.py`, `classify_surface_patches.py train / lopo-manifest` refuse unless `--research-unverified`; outputs stamped `research_only_unverified`. Shadow Lab: `leakage_audit_passed=False` (no audit exists; its score uses the true label), cohort labelled SYNTHETIC / unverified Pensieve. |
| review_css | A completed session journals `review_completed` (read phase `unblinded_legacy`: consensus for scoring, never training-eligible). |

## Training / evaluation paths inspected
| Path | Labels from | Status |
|---|---|---|
| Percival Score engine (`percival_gui._train`, `meta.train_cycle`) | call ledger → eligibility → dataset → split → audit | **Integrated** (primary path) |
| Percival shadow mode / score_study | registry models | inference only |
| uscore (Unified score, hidden prototype) | derived `ID_calls.csv` (expert consensus, provenance not checked), own split | experimental, not primary — documented risk |
| `train_ranker.py`, `evaluate.py`, `classify_surface_patches.py` | `labels/` (no roles / consensus / provenance; study-level split) | **refused** unless `--research-unverified`; outputs stamped |
| Shadow Lab / governance | Pensieve or synthetic cohort | experimental; no audit claimed; synthetic labelled |
| Albus / LUMOS / NOX / CORE | heuristics, Pensieve | experimental, off by default; no training interface |
| `training_gui` image-ML evaluation | synthetic | display only (time-seeded; not evidence) |

## Tests
- Targeted: `test_phase3bcd_readiness.py` 14/14 (adversarial matcher: contested, ambiguous, nearby, split, merge, disappear, new, hemisphere, reorder, redetection with audit; determinism across processes with different `PYTHONHASHSEED`; readiness; split lock / reproducibility / versions / app refusal; leakage audit 6 failure kinds; legacy guards; Shadow Lab; state fix). All Phase 3 tests 82/82.
- Synthetic end-to-end (`check_percival.py`, SYNTHETIC cohort — not real performance): training completed; dataset only eligible expert labels; audit passed and saved; locked split recorded; model traceable to dataset hash + split + audit + code version; source hashes recorded; dataset reproduces identically; export verifies; duplicate examination flagged; injected leakage (study held out elsewhere used for development) → **training refused, nothing registered**.
- Full runs, mutations: see the final message.

## Remaining risks / limitations
- No real cohort or expert labels exist on this Mac; nothing here is evidence of real-data performance.
- Matching tolerances are in voxels (resolution dependent); splits / merges are left unresolved (by design) and need human confirmation via lineage.
- An abstention does not block consensus when the other completed experts agree with enough definite calls (documented choice; raise the quorum to require more).
- uscore (hidden prototype) trains on consensus calls without the provenance gate.
- Patient identity correctness is upstream (identity registry); the audit can only use recorded patient ids / fingerprints.
- Pre-existing failing checks (environment / unrelated): headless-Chrome DOM checks, `check_percival_learning` K14 (outdated component list).

## Prerequisites for the first real training run
1. A new MRI cohort imported and processed in the app (FreeSurfer anatomy + detection + QC), each study with a verified patient identity (Training Center › Patient identity).
2. Designated experts assigned in the app (Reviewer calls › Set role, typed confirmation) and, if wanted, one adjudicator.
3. Each expert completes a **blind initial read** of every study (final save with every candidate called); optional whole-study search for missed cSS.
4. Disagreements reviewed (adjudication is recorded but is not training ground truth); at least 3 eligible cSS + 3 eligible not-cSS and 10 in all in the development partition.
5. Local learning switched on (Percival Intelligence › Switch on).
6. Readiness: `GET /api/percival/readiness` — every check true.

## Launch workflow (once the prerequisites are met)
In the app: Training Center › **Train**. Equivalent request (app on its usual port, from the same Mac):
```
curl -s -X POST -H 'X-CSS-App: 1' -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:8800/api/percival/train
```
The run builds the dataset (manifest with sources, split, provenance), saves the leakage audit, refuses on any failure, trains, and registers
the model as candidate / experimental (never active automatically). Then: `GET /api/percival/runs`, the dataset id in the model
(`percival/registry/vNNN/model.json → data.dataset / split / leakage_audit`), export with
`POST /api/percival/dataset_export {"id": "dsNNN"}`, promotion only by explicit approval in Model Center.
