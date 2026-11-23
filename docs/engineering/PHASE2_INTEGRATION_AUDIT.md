# Phase 2 — PERCIVAL Existing-System Integration Audit (read-only)

Branch `claude/phase0-safety` @ `e64219d`. Code root `cSS_pipeline_v4.13/`. Nothing was modified, installed, run against
live data, or touched on the Vault. Evidence = code reading (file:line). "Tested" means an automated test exists and
exercises the path; **every existing test is synthetic** (phantoms PH1–PH6, temp projects, random cohorts). Real-data
results quoted from CLAUDE.md are the user's earlier runs and were not re-run in this audit.

**Headline finding:** this Mac holds **no expert ground truth and no trained model**. `~/Percival_project` has 0 patients,
an empty Percival registry and an empty Pensieve (0 rows in all 8 tables); no `*_calls*.csv`, `ranker_model.json`,
`candidate_labels.csv` or `*_final*.json` exists anywhere under `$HOME` (depth 6). The M01–M26 cohort and its calls are
presumably on the unmounted Vault — unverified. Every ML/validation claim below is therefore code-level only.

---

## A. Architecture and dependency map

```
 GUI (app/css_app.html + 17 *_view.js)  ──HTTP──>  app/css_app.py (ThreadingHTTPServer, prefix router 2677-2963)
   │                                                 │
   │  Add/Import ─────────> id_post / kp_post ──> scripts/cohort.py import ──> raw/<ID>/{SWI,T1,FLAIR}
   │  Process ────────────> proc_post ──> processing_manager ──> $CSS_BASE/scripts/run_css.sh   (INSTALLED copy)
   │                                         prep_anat.sh (FreeSurfer 8.2: SynthSeg / recon-all -no-v8, bbregister)
   │                                         swi_mask_from_t1.py → align_seg.py → detect_css.py (E1–E27, PIPE_ENV V53/ZONE2/CONF)
   │                                         surface_features.py → rank_candidates.py (only if model + dev) → css_qc.py
   │  Review ─────────────> launch_child ──> scripts/review_web.py (127.0.0.1, --open) ──> review/ID_calls_<rev>.csv,
   │                                         ID_missed.csv, ID_review_log.csv, ID_final_<rev>.json
   │                                         └─> scripts/call_ledger.py materialize ──> shared review/ID_calls.csv
   │                                         └─> (Pensieve sync: fails FK, swallowed)
   │  Score ──────────────> score_css.py (after review; 0–4 multifocality)
   │  Percival Center ────> pg_get/pg_post ──> app/percival_gui.py
   │                                         label_summary ← call_ledger.effective (+ historical/, + Pensieve missed)
   │                                         uengine/percival/eligibility.py → datasets.py (dsNNN) → meta.train_cycle
   │                                         (learners, cnn SmallCNN, nested, Platt, ensemble) → store.py registry/vNNN
   │                                         Model Center promote (manual) ; score_study → immutable ledger
   │  Prototypes (hidden) > /api/u/* uscore, /api/se/* shadow engine, /api/im/* image ML, /api/train/* legacy
   │  shadow_run ─────────> uengine/shadow_lab.py + governance.py  (reachable, NOT gated)
   │  ALBUS/LUMOS/NOX/CORE > percival_gui 858-970, features.experimental_core (no GUI toggle)
   │  Files / Sync ───────> file_manager.py (copy_item, own checksum) ; storage/sync_manager.py
   │  Transfer Center ────> uengine/transfer/api.py → service/journal/copier/workers  (Phase 1; monitor/control only)
   │  Eject / Vault ──────> storage/eject_manager.py, activity.py, vault_check.py   (Phase 1e)
   └  Identity ───────────> app/identity.py, identity_gui.py (registry.json + vault .enc or plaintext .json)

 Stores (no single DB): patients.json (PAT) · identity/registry.json · study_workspace_ledger.json ·
 pensieve.db (hardcoded ~/Percival_project/app_data, shared by all projects) · labels/study_meta.csv ·
 split/current.json · unified_score/cohort_manifest_RECONCILED.csv · review/evaluation_studies.txt · cohorts.json ·
 percival/{datasets,registry,runs,eligibility} · transfer journal (SQLite WAL)
```

Key dependency facts: the app runs the **installed** scripts in `$CSS_BASE/scripts`, not the repo (BUILD 236ad5f
installed); `scripts/css_common.py` in the repo **differs** from `app/production_reference.json` (changed by Gemini
commit `26568a1`; `match_calls` is the re-attachment of expert calls). All other referenced scripts match.

---

## B. Component inventory

| # | Component | Classification | Key evidence | Tested? |
|---|---|---|---|---|
| 1 | **Albus** (ALBUS/LUMOS/NOX/CORE) | **Implemented but disconnected** | Gated by `features.experimental_core` (css_app.py:116; read only percival_gui.py:858-970; no GUI toggle). Heuristic / hard-coded / untrained. Even when enabled, `gather()` rows lack `ci/cj/pdist/patch`, so no score is produced; test s11 masks this. | synthetic only; masked defect |
| — | (Percival Score engine, the real model path) | Implemented and functional — requires validation | `uengine/percival/{meta,cnn,learners,eligibility,datasets,store}.py`; train via `op train`/`maybe_cycle`; manual promotion (`promote:667`); seed 0 | check_percival*.py, check_adversarial_leakage, check_cnn_gradients — synthetic |
| 2 | **Pensieve** | **Implemented but disconnected** | `remember_study` (pensieve.py:464) has no non-test caller → `studies_memory` empty; `foreign_keys=ON` (107, 290) → every annotation / missed insert fails, exception swallowed (review_web.py:466-485). Candidate UID `sid_cand_<id>` vs `sid_hemi_i_j_k` mismatch; journal replays into non-existent `lumos_unc`; duplicates per save (`time.time()` in id); DB path hard-coded & shared across projects; pensieve_backup has no caller. | test_pensieve.py etc. populate `studies_memory` themselves — production path untested |
| 3 | **cSS detection** | **Requires validation** | detect_css.py functional end to end. V53 rules E12–E25 ON in production (PIPE_ENV, css_app.py:~101) and documented "NOT validated", fitted on M02–M11 by one non-expert reader; held-out M12–M15/M01 evaluation never recorded. E26 effectively off, E27 on; E28/E29, E10/E11 opt-in (disconnected); E30 needs a confidence model; E23 absent. `CSS_QC_STRICT` not set by the app; `registration_ok=None` passes. Fate check exit 4 occurs after outputs are written. | phantoms (run_tests.sh, test_shell.sh with stub FreeSurfer); real runs only in CLAUDE.md history |
| 4 | **FreeSurfer** | **Implemented and functional** (caveats) | prep_anat.sh: SynthSeg / `recon-all -no-v8` / bbregister / mri_coreg; FS 8.2.0 present. No version gate (`-no-v8` assumes FS 8); no memory cap on the SWI-only SynthStrip route (64 GB history); fs_env does not source SetUpFreeSurfer. | stubbed in test_shell.sh; real runs P006/LEMON/M02–M11 per CLAUDE.md |
| 5 | **MRI ingestion / preprocessing** | **Implemented but incomplete** | cohort.py import: dcm2niix; **existing raw/<sid>/<mod> is reused** (`if not niftis(out):`, ~l.120-140) → stale-raw risk. series_detect heuristic; minIP refused but unknown series accepted. dicom_repair, make_swi, mp2rage_robust not reachable from the app. swi_mask_from_t1.py overwrites data/ID_swi.nii in place and restores mtime (raw original safe). Non-axial → exit 2. study_library sha256-verified. | check_app_import_v518, check_duplicate_detection (synthetic) |
| 6 | **Study / patient data management** | **Implemented but incomplete** | 6+ independent stores, never reconciled together. `save_pat` tmp+replace, fixed tmp name, no fsync, lock coverage unconfirmed. `reconcile_studies_on_disk` (css_app.py:141) auto-adds folders at startup with no duplicate check. Four split authorities (study_meta.csv, split/current.json, cohort manifest, evaluation_studies.txt) with no cross-check. Identity vault **plaintext by default** (identity.py:60-86); disable-lock bug (existing `.enc` forces lock on restart → later edits ignored). `study_admin.study_files` glob `review/{fk}_*` collides on `_` in codes (purge M02 sweeps M02_redo_*). Workspace ledger stores absolute source paths/folder names. | check_identity, check_app_study_admin, check_processing_manager (temp dirs) |
| 7 | **Expert review** | **Requires validation** | review_web.py functional (calls, fine codes, missed marks, finals, log). **App always launches with `--open`** (css_app.py:2636) → every app read unblinded (meter + AI score visible); validation mode is a client-sent field. Default policy **`newest`** (call_ledger.py:172) + `materialize` on every save (review_web.py:463) → any later reviewer overrides the shared labels. Per-reviewer files rewritten with plain `to_csv` (not atomic); missed marks hard-deleted, ids reused. Two re-attachment matchers (inline 2 vox/15 % in review_web; `match_calls` called row-by-row in call_ledger → one-to-one constraint defeated). App `/missed_lesion` (css_app.py:1266-1295) writes a different column order into the same ID_missed.csv (no GUI caller found). review_css.py legacy writer disconnected. | check_review_web (PH3), check_call_ledger, check_lineage, check_labels, check_consensus; check_viewer prints OK when SKIPPED |
| 8 | **AI dataset generation** | **Implemented but incomplete** | label_summary uses `call_ledger.effective` (correct source); eligibility engine 1.3 functional. Bugs: `_cid_sort` (datasets.py:34) uses Python `hash()` (per-process randomised) → manifest order/hash not reproducible with ≥2 missed lesions; hash excludes feature/pixel content. Missed-lesion positives hard-coded `status="eligible"` (percival_gui.py:473) bypassing identity/exclusion/duplicate checks, and never trained on (`_train:777`) → manifest counts overstate the training set. `percival_test_fraction` accepted from the API unchecked (css_app.py:1251) → locked test patients can move to development. Legacy path: expert_import defaults unread numbers to "N" and train_ranker:151 makes every non-cSS a negative. **AI dataset export: Missing.** | check_percival_learning (same-process reproduce — cannot catch the hash bug) |
| 9 | **AI training** | **Requires validation** | Percival `meta.train_cycle` functional (patient-grouped OOF, nested, Platt, bootstrap ensemble, no auto-promotion). Never run on real labels on this Mac. train_ranker / classify_surface_patches / uscore group by **study**, not patient. Every cycle is compared on the same locked test cohort (adaptive reuse). Shadow Lab (`/shadow_run`, not gated): synthetic fallback cohort, **true label in the score** (shadow_lab.py:278), `leakage_audit_passed=True` hard-coded (217), writes "replicated" findings into Pensieve; governance promote writes a file nothing reads. training_gui evaluation seed = `time.time()`. | synthetic only |
| 10 | **GUI** | **Implemented but incomplete** | ~205 API paths / 322 call sites all route. Breaks: **B1** "Clean Orphan Staging Buffers" posts unknown op `clean_staging` (settings_view.js:1317) → silent failure. **B2** nothing creates journal transfer jobs (`/api/transfer/jobs/create` has no JS caller); File Manager archive uses `file_manager.copy_item` directly (file_manager.py `archive_entry`), Settings › Transfer still drives the old TransferManager → **two transfer systems; the Phase 1 engine has no production producer**. B3 install/rollback, dcm2niix/licence fix, several toggles only in the fallback settings view (unreachable). B4 no toggle for experimental_core. B5 unified/shadow enable only via hidden prototype screens. B6 dead views (homeView, ptsView, resView, procView). B7 server routes with no caller. Blind read resolves scripts under project base B. | Rendering tests only for Transfer Center (Node harness) and e2e_rc1; none for Files, Sync, Settings, Recovery, Vault, Lineage, Calls UI |

---

## C. Data flow: MRI ingestion → AI training (as implemented)

1. **Import** (GUI Add → `id/import/commit` → cohort.py import): DICOM/NIfTI → `raw/<ID>/<mod>` (dcm2niix); duplicate
   check by sha256 / SeriesInstanceUID; PAT record + identity registry. *Gap: existing raw reused silently.*
2. **Preprocess** (run_css.sh, installed copy): SWI whole-head, T1 SynthSeg or recon-all, bbregister → masks
   (in place, mtime kept) → align_seg.
3. **Detect** (detect_css.py, PIPE_ENV V53/ZONE2/CONF): candidates.csv/.nii.gz, excluded.csv, dropped.csv,
   manifest.json, qc.json. *Unvalidated rules on by default; QC lenient.*
4. **Optional ranking / scores**: rank_candidates (only with a model and dev split); uscore `app ID` (opt-in).
5. **Expert review** (review_web.py): per-reviewer calls + missed + log → `call_ledger.materialize` → shared
   ID_calls.csv. *Unblinded via app; newest-wins; non-atomic writes; Pensieve copy silently lost.*
6. **Score** (score_css.py): 0–4 multifocality after review.
7. **Labels** (percival_gui.label_summary): effective ledger call → y∈{1,0,None}; historical/ fingerprint-matched;
   Pensieve missed lesions merged into counts.
8. **Eligibility** (eligibility.py) → **dataset** (datasets.py, dsNNN, content hash, patient split from
   `meta.test_assignment`). *Hash non-deterministic with missed lesions; split fraction mutable.*
9. **Train** (meta.train_cycle) → registry/vNNN (candidate) → manual promotion → score_study → immutable ledger.
10. Parallel, unconnected label/split paths: expert_import → candidate_labels.csv → train_ranker (study-grouped);
    uscore (cohort manifest + split/current.json + LabelAccess held-out protection); study_meta.csv dev/test.

---

## D. Integration gaps and dependencies

| Gap | Depends on / blocks |
|---|---|
| D1 Phase 1 transfer engine has no producer; File Manager archive/stage and Settings › Transfer bypass the journal | Phase 1e eject protection only sees journal jobs → a File Manager copy is invisible to it |
| D2 Three to four independent split authorities; Percival never consults uscore held-out roles or LabelAccess | Patient-level leakage, held-out integrity |
| D3 Two calls matchers + css_common.match_calls changed vs production reference | Ground-truth re-attachment after redetect |
| D4 Pensieve disconnected (no studies_memory writer, UID mismatch, shared cross-project DB) | Anything that reads Pensieve (label_summary missed lesions, Shadow Lab) |
| D5 Repo scripts vs installed scripts (BUILD 236ad5f) | Reproducibility; which code produced which outputs |
| D6 Legacy label path (expert_import → train_ranker) independent of the ledger | Contradictory labels between models |
| D7 Missed-lesion positives in manifests but not in training | Reported dataset sizes |
| D8 GUI toggles missing / hidden (experimental_core, install/rollback, clean_staging broken) | Operability, not safety |
| D9 Ground truth and cohort not on this Mac | Every real-data validation step needs the Vault mounted + manifest verified (read-only) |

---

## E. Missing functionality

- AI dataset export (dsNNN with partitions, labels, provenance).
- Held-out evaluation of the production detector (M12–M15, M01) — tooling exists (evaluate.py, v53_compare.py), never run/recorded.
- A single patient-level split authority shared by Percival, uscore, ranker and study_meta.
- A GUI producer for journal transfer jobs (archive / stage / restore through TransferService).
- Detection of stale raw data on re-import.
- Server-side enforcement of the blind (validation) read and of the locked test fraction.
- Pensieve study registration (or an explicit decision that Pensieve is a derived, per-project index).
- GUI-level tests for Files, Sync, Settings, Recovery, Vault, Lineage, Calls.
- E23 (referenced, absent); confidence model for E30.

---

## F. Prioritised implementation sequence (proposal for Phase 3 — NOT started)

Ordered by risk to ground truth first, reusing existing code; each step small, isolated-tested, separately approved.

1. **Protect expert ground truth (smallest, highest value):** atomic tmp+fsync+replace for `ID_calls_<rev>.csv` and
   `ID_missed.csv` (reuse the Phase 1 copier pattern); fix or remove the conflicting `/missed_lesion` writer; soft-delete
   missed marks; make the app honour the validation read (drop the forced `--open` or make it a setting with the
   validation read as default); default call policy to an explicit primary/expert reviewer instead of `newest`.
2. **Decide `css_common.py` divergence** (keep Gemini's `26568a1` matcher or restore the production version) and make
   call_ledger use `match_calls` one-to-one for the whole set; retire the inline review_web matcher.
3. **Training-data integrity:** deterministic `_cid_sort`; lock `percival_test_fraction` server-side once a test cohort
   exists; route missed-lesion positives through `EL.evaluate` (or drop them from manifest counts); gate `/shadow_run`
   behind `experimental_core` and label its output synthetic/non-evidential.
4. **One patient-level split authority:** pick one existing implementation (`study_split` with patient key, or
   `meta.test_assignment`) and make the others read from it; refuse training when a uscore held-out patient is in
   Percival development.
5. **Connect the Phase 1 transfer engine:** route File Manager archive/stage/restore through `TransferService`
   (`/api/transfer/jobs/create`); then retire the old TransferManager queue in Settings; fix `clean_staging`.
6. **Ingestion:** detect stale raw (series UID / sha256 vs existing raw) and ask instead of reusing.
7. **Identity:** encrypted vault by default (or explicit plaintext warning); fix the disable-lock restart bug; fix the
   purge glob collision.
8. **Pensieve:** decide its role (derived index vs memory); if kept, per-project DB, register studies at import, stable
   candidate UID, idempotent writes.
9. **Real-data validation (needs the Vault mounted and its manifest verified, read-only):** inventory ground truth;
   held-out detector evaluation; first real Percival training cycle.
10. **Albus/LUMOS/NOX/CORE last**, only after 1–9, and only if the user wants it.

---

## G. Risks

**Data integrity**
- Non-atomic rewrites of per-reviewer calls/missed files; mixed-schema ID_missed.csv from the app endpoint.
- Silent Pensieve write failures (FK) → believed-saved annotations are lost.
- Stale raw reuse on re-import; in-place SWI mask with restored mtime (mtime no longer reveals the change).
- File Manager archive bypasses the journal → invisible to eject protection and recovery.
- Purge glob collision across study codes containing `_`.

**Patient-level leakage**
- Four unlinked split authorities; Percival ignores uscore held-out roles.
- Ranker, surface classifier and uscore group by study, not patient (repeat scans leak across folds).
- Mutable Percival test fraction moves locked test patients into development; repeated comparisons on one locked test
  cohort turn it into a selection set.

**Ground-truth contamination**
- App reads are unblinded (AI meter visible); `newest` policy lets any later reviewer overwrite expert labels.
- Two inconsistent matchers; per-row matching allows two calls on one candidate; matcher code differs from production.
- Legacy labels: unread → Normal, ICH-related / infratentorial → negatives.
- Shadow Lab uses the true label inside its score and treats uncertain as negative; missed lesions bypass eligibility.
- Ranker applied to dev studies whose new calls become training labels (feedback loop).

**Reproducibility**
- Installed scripts ≠ repo (css_common.py hash differs from production reference).
- `hash()`-ordered manifests; manifest hash excludes feature/pixel content; time-seeded image-ML evaluation.
- No FreeSurfer version gate; `-no-v8` assumes FS 8.

**Clinical interpretation**
- Production detector rules (E12–E25) are unvalidated and fitted on one non-expert reader's calls for M02–M11.
- Shadow Lab can display "Approved for promotion" from synthetic or leaky metrics.
- QC leniency (`registration_ok=None` passes, strict mode off) can yield scores on poorly registered scans.
- The 0–4 adjacency rule is unresolved (n=1); meter / AI score are not probabilities.
- Research software only — no component is clinically validated.
