# PROJECT_HANDOFF.md — cSS detection and grading pipeline

Handoff for a new Claude Code session. Written 2026-11-12 from the repository itself plus this session's history.
Statements are marked with where they come from: **[repo]** = verified against the files in this repository, **[test]** = verified by a test
run in this sandbox, **[Mac]** = reported from the user's own runs on real patient data (cannot be re-checked here, there is no patient data
in this sandbox).

Read `CLAUDE.md` (same folder) as well: it holds the long version history v3 to v5.7 and the standing project rules.

---

## 0. Exact first actions for the new session

1. **Do not change any rule or threshold yet.** Before anything else, ask the user for the output of the v5.10.6 redetect
   (side guard) and for their look at the four M15 cSS objects the confidence cut removed (section 7, item P0-1).
2. Run the fast test suite once to confirm the environment: `cd cSS_pipeline_v4.13 && bash tests/run_tests.sh` (about 25 min in this
   sandbox; no FreeSurfer or patient data needed). Expected last line: `ALL TESTS PASSED`.
3. Remember: **push to GitHub is blocked** (403, GitHub account disconnected). The user receives code as zip files; see section 9.

---

## 1. Project overview

Semi-automatic detection and grading of **cortical superficial siderosis (cSS)** on SWI MRI, for cerebral amyloid angiopathy (CAA) research
(neuroradiology fellowship project). Research software, not for clinical use.

- Input per study: SWI (required), T1 (strongly recommended), FLAIR (optional), phase (optional).
- Output: candidate cSS objects for a human reader, the reader's calls, and a **patient-level cSS multifocality score 0–4**
  (per hemisphere 0 / 1 / 2: 0 none; 1 = one sulcus or ≤ 3 immediately adjacent sulci; 2 = ≥ 2 non-adjacent or > 3 adjacent sulci;
  total = R + L), plus focal / disseminated category and continuous measures.
- **Reference standard:** a radiologist's patient-level grades (R, L, total) for M01–M15. The user stated explicitly:
  *"the radiologist grading is right, we are wrong"*. Only cSS-versus-not-cSS matters; the reader's Normal / Vessel / Artifact
  categories are unreliable and are never used as ground truth.
- The user's goal for the next phase: **speed and scale** (about 3000 cases later) and **fewer false positives** (user prefers aggressive
  exclusion).

### Users, environment, constraints (standing rules from the user and the system)
- User's machine: macOS Apple M3, 36 GB RAM, FreeSurfer 8.2.0, conda env `css` (python 3.11), project data in `~/css_project`
  (`$CSS_BASE`). Code is installed there by unzipping update zips into `~/css_project` (scripts/, tests/, tools/).
- Terminal commands for the user must be **copy-paste-ready zsh**, one block at a time, never including the prompt line
  (pasting the prompt once caused `zsh: parse error`).
- Heavy jobs **one study at a time**, nothing else heavy running (SynthStrip once took 31–85 GB and froze the Mac).
- **No code for a visible UI change before the user approves a sketch.**
- **Never commit patient data**; study codes only (M01–M15, P006, P201…). No names, MRNs, dates.
- Do not create pull requests unless asked. Develop on the designated branch (section 9).
- My own working rule, kept throughout: when fitting a rule, **stop and ask if any reference cSS would be lost or the margin is < 10 %**.
- M12–M15 (and M01) are **held-out test cases** — never tune on them. They have now been looked at once (section 6); treat any further
  tuning on them as contaminated.
- M01: the user does **not** have this patient. Drop it from every command.

---

## 2. Repository map  [repo]

Git repository root: `/home/user/My-Claude-`. Project folder: `cSS_pipeline_v4.13/` (this file lives there).

```
cSS_pipeline_v4.13/
  CLAUDE.md            long history + rules (keep appending)
  PIPELINE.md RUNBOOK.md README.md   older method / operating docs
  ALL_CODE.md          generated code dump (STALE: last regenerated at v5.7-E; tools/make_all_code.py)
  environment.yml      conda env (python 3.11, numpy, scipy, nibabel, pandas, scikit-image, matplotlib, pydicom, dcmtk, openpyxl)
  install.sh
  scripts/  (64 .py + 5 .sh + review_web.html; VERSION = v5.10.6)
  tests/    (run_tests.sh, test_shell.sh, phantoms, check_*.py, check_viewer.js)
  tools/    (release / batch helper scripts, see below)
  docs/     (changelogs, plans, how-tos; adjudication_M02-M11_v1.csv = study codes + object ids + call only)
```

### Pipeline scripts (execution order)
| Step | Script | Role |
|---|---|---|
| 1 | `scripts/run_css.sh ID swi [--t1 T1] [--flair F] [--recon] [--phase P]` | import, SWI mask, calls prep_anat, align_seg, detect, surface features |
| 1a | `scripts/prep_anat.sh` | `--recon`: FreeSurfer recon-all (`-no-v8` classic stream) + bbregister; without `--recon`: SynthSeg `--parc --robust` on T1 + `mri_coreg`; FLAIR coreg |
| 1b | `scripts/swi_mask_from_t1.py` | SWI skull mask from T1 labels + 5 mm (replaces SynthStrip on the SWI, v5.2.5) |
| 1c | `scripts/align_seg.py` | labels on the SWI grid → `work/ID_seg_swispace.nii.gz` |
| 2 | `scripts/detect_css.py ID` | **the detector** (1380 lines): candidates, exclusion rules, features, manifest |
| 2b | `scripts/surface_features.py` | pial-surface features (recon-all only; recorded only) |
| 3 | `scripts/review_web.py IDs --reviewer NAME [--open] [--show-excluded] [--audit]` + `review_web.html` | browser reviewer (127.0.0.1, stdlib server, canvas viewer) |
| 4 | `scripts/score_css.py ID` | 0–4 score (Destrieux sulcal scoring when recon-all labels exist, else Euclidean approximation) |
| — | `scripts/redetect.py IDs --v53` | re-run detection only on prepared studies, backs up lists + calls to `review/backup_<stamp>/` |
| — | `scripts/cohort.py` | import M01–M15-style folders (DICOM / NIfTI), batch run_css one at a time |
| — | `scripts/compare_grades.py` | patient-level score vs radiologist sheet (kappa, Bland-Altman, xlsx) |
| — | `scripts/css_report.py` | cohort Excel/CSV report of reviewer + AI scores |

### Analysis / probe scripts (read-only unless noted)
`v53_compare.py` (acceptance test on COPIES in `$CSS_BASE/v53_eval`), `v53_change_report.py` (before/after per patient; needs a snapshot),
`snapshot_from_backup.py` (rebuilds the snapshot from a redetect backup), `inherit_calls.py` (carries unanimous old calls to new objects,
dashed until confirmed), `compare_reads.py` (two reads per object, kappa), `compare_pipelines.py` + `run_experiment.py` (switch experiments on
copies), probes `midline_probe.py`, `zone_probe.py`, `shape_probe.py`, `struct_probe.py`, `pial_compare.py`, shared `probe_common.py`,
`fit_confidence.py` (fits the confidence model; writes `review/confidence_model.json`).

### Shared modules
`css_common.py` (base path, call matching by fingerprint, `norm_call`), `css_shape.py` (principal extents, blob measures, **3-D structure
`struct_measures` / `classify3d`**), `css_confidence.py` (confidence model), `css_model.py` (balanced L2 logistic regression, LOPO),
`css_sheet3d.py`, `css_vessel.py`, `css_pieces.py`, `css_features.py`, `css_tiers.py`, `css_qc.py`, `css_surface.py`, `mimic_rules.py`.

### tools/
`run_v510.sh` (confidence-model workflow: redetect → fit → acceptance → apply; stops if a cSS is lost), `run_v58.sh` (acceptance + redetect
with `CSS_ZONE2=1`), `run_all_v57E.sh`, `rerun_failed_v57E.sh`, `check_e22_pieces.sh`, `make_release.sh`, `make_all_code.py`, `build_workbook.py`.

---

## 3. Current architecture of the detector  [repo: scripts/detect_css.py]

1. **Normalisation:** darkness z = (I − local cortex mean, Gaussian σ 10 mm, 2-pass excluding dark cortex) / cortical MAD.
   v5.10: a **reader-drawn ICH** (`work/ID_ich.nii.gz`) plus a 4 mm rim is left out of this reference.
2. **Search zone:** pial band −3.5 … +4 mm (signed distance to labelled tissue), minus WM / deep nuclei / 3 mm brain-mask rim.
3. **Seeds:** per-slice 2-D Sato ridge filter (sigmas 0.6/1.2/1.8 mm), hysteresis per hemisphere (strong z < −2.5 & ridge > 85th pct,
   weak z < −2.0 & > 80th pct).
4. **Generation gates:** ≥ 25 mm³, ≥ 2 slices, elongation ≥ 2.0, cortex label nearby; drops logged in `work/ID_dropped.csv`.
5. **Merging:** pass 1 gap 3–4 mm (40 mm cap); with `CSS_V53=1` pass 2 gap 5 mm, **same aparc region only**, 80 mm cap.
6. **Features per object** (≈ 180 columns, append-only contract): pial distance, bank / tram-track, tube ratio, vessel continuation,
   v5.3 measures (midline, skull band, mask edge, ventricle, out_frac), plane features (E22), skull-base share, dual contact (E25),
   zone2 / Sylvian shares, **struct_*** (3-D form of the whole dark structure, measured on a 22 mm wider window),
   **dark_cv / dark_gap_frac** (darkness continuity along the long axis), **minip_len_mm / minip_cont** (±4 mm axial minIP continuity),
   **ich_contact_frac**, **confidence_pct / confidence_why / conf_guard**.
7. **Exclusion rules** (`exclusion()` → `exclusion_v4()`), first match wins, order in the file:
   E1 infratentorial, E2 basal cisterns, E3 skull base lowest 20 %, E4 speck, then (only `CSS_V53=1`, T1 anatomy) E15 skull band, E12 extent
   > 3000 mm³ (first-pass object), E16 ventricle, E17 outside cortex, E20/E19/E21 (skull-backed & large / dark / off cortex), E18 ill-defined,
   E26 (off: threshold 0), E27 Sylvian (`CSS_ZONE2=1`), E28/E29 (`CSS_STRUCT=1`, provisional), E25 interhemispheric fissure, E13 midline,
   E22 midline sheet (judged per first-pass piece by default), E24 skull-base cortex zone, E14 orbitofrontal; then E5 vein-in-CSF,
   E6 vessel into WM, E7 off cortex, E8 skull-base artifact zone, E9 faint, E10/E11 mimic (opt-in). Finally **E30 low confidence**
   (`CSS_CONF=1` and a model file) in `exclusion()`, followed by the **side guard** (`CSS_CONF_GUARD`, default on).
8. **Fate invariant:** every object is exactly one of shown / excluded / dropped (exit 4 if violated). Manifest
   `review/ID_manifest.json` records inputs (sha256), thresholds (`frozen_rules`), switches, versions.

### Environment switches  [repo]
| Switch | Default | Effect |
|---|---|---|
| `CSS_V53=1` | off (but `redetect.py --v53` sets it; all current lists use it) | v5.3+ rules, second merge |
| `CSS_ZONE2=1` | off | enables E27 (Sylvian ≥ 0.2) and E26 (inactive, threshold 0) |
| `CSS_CONF=1` | off | E30 low-confidence exclusion, needs `review/confidence_model.json` |
| `CSS_CONF_GUARD=0` | guard on | turn off the side guard |
| `CSS_E22_PIECES=0` | pieces on with V53 | E22 on the merged object (old behaviour) |
| `CSS_STRUCT=1` | off | E28 ball / E29 tube (thresholds NOT fitted) |
| `CSS_SOFT_GATES`, `CSS_3D_SEEDS`, `CSS_USE_MIMIC`, `CSS_MIXED_REVIEW`, `CSS_QC_STRICT`, `CSS_KEEP_ALL`, `CSS_RANK`, `CSS_SATO_LEGACY`, `CSS_ALLOW_ORIENT` | off | experimental / legacy |

The user's real lists were last produced with `CSS_V53=1 CSS_ZONE2=1 CSS_CONF=1` (cut 24.2 %) — see section 6.

### Reviewer  [repo: scripts/review_web.py, review_web.html]
Keys Y cSS, V **Vessel**, N Normal, A Artifact, B Microbleed, U Unsure, H Near ICH; W magnifier; K hides the meter; **3** hides the 3-D card.
Per-reviewer files `review/ID_calls_<name>.csv`; the **primary reviewer** alone writes the shared `ID_calls.csv` / `ID_score.json`.
A new reviewer name starts empty and in **validation-read mode** (meter, AI score, export locked; shuffled numbering) until its final save,
unless `--open`. Rule-excluded objects are hidden unless `--show-excluded` (all, with rule) or `--audit` (20 % sample in validation reads);
their calls go to `ID_excluded_audit_<name>.csv` and are never scored. 3-D card (`/api/struct3d`): regrown structure (red), detector object
(yellow), cortex (grey), drag/zoom, shape reading hidden in validation reads. Confidence line under the AI evidence. POSTs need header `X-CSS: 1`.

---

## 4. Work completed in this session (chronological)  [repo: git log 1f5146b..4b4059d, 54 commits on the branch]

Version tags are in `scripts/VERSION` and commit subjects. "Tested" = automated test in this sandbox unless marked [Mac].

### Reviewer / viewer (v5.6.1 – v5.7, v5.8.2–3, v5.9.1, v5.10)
- R badge only, mirror left-right (menu + right-click), narrow auto-hide tool strip, crosshair off by default, rail with 3 buttons,
  theme symbol slider, validation eye-lock symbol, centred content-sized decision buttons. Tested: `tests/check_viewer.py` (Playwright).
- Separate reviewers, primary reviewer, import window, Microbleed call (key B; magnifier moved to W), validation read with audit sample.
- `--open` (full viewer without validation read), `--show-excluded` (all excluded objects listed with rule), excluded audit sample only with
  `--audit` (was default in validation read; user saw skull/vessel objects and asked for them gone). Tested: `check_review_web.py`.
- 3-D card + `/api/struct3d`; confidence line. Tested: `check_viewer.js` (card visible by default, non-blank canvas, rotates, key 3 toggles).

### Detector rules
- **E22** midline sheet (plane ≤ 8 mm, cos ≥ 0.9, length ≥ 25 mm); v5.7-E-fix2/3: judged on **first-pass pieces** by default because
  the second merge joined a true cSS (M11 #12) into a 29.5 mm "sheet". [Mac] acceptance went 55/56 → 56/56.
- **E24** skull-base cortex zone (nearest-cortex label orbitofrontal / frontal pole / temporal pole / entorhinal / pars orbitalis);
  threshold 0.5 → **0.2** in v5.8.4 (no cSS call has any share > 0.00 on M02–M11).
- **E25** interhemispheric fissure (left and right cortex both within 3 mm of ≥ 30 %), checked before E13.
- **E26** outside cortex + sulci (v5.8.0) — **switched off in v5.8.1** (threshold 0): lost M04 #28 (zone2_frac 0.42), gained ≤ 1.
- **E27** Sylvian fissure (within 3 mm of insula AND opercular cortex): 0.6 → 0.4 (v5.8.1) → **0.2** (v5.8.4); cSS max 0.09.
- **E28/E29** 3-D ball / tube (v5.9.1): **opt-in, thresholds provisional, never fitted** (struct_probe results not received).
- **E30** low confidence + **side guard** (v5.10.0 – v5.10.6).
- Tested on phantoms: `check_v53.py` (each rule positive test; switches off = unchanged output; no true lesion lost), `check_confidence.py`.
  [Mac] acceptance test after v5.8.4: 52/52 reader cSS calls shown, 12 more non-cSS removed (159 → 147 shown in M02–M11).

### Measurement / probes
- Probes (read-only): midline, zone, shape, struct, pial_compare; experiments (`run_experiment.py`, `compare_pipelines.py`).
- `css_shape.struct_measures`: regrows the whole dark structure (≤ 20 mm) and classifies BALL / TUBE / RIBBON / OTHER / UNRESOLVED,
  with cortex share, axis vs pial normal, continuation factor; plain-language verdict.
- `cont_feats` in detect_css: darkness continuity and minIP continuity.

### Confidence model (v5.10)
- `css_confidence.py`: one class-balanced L2 logistic model over 7 evidence domains (location, form, surface, course, minIP, darkness, size).
- `fit_confidence.py`: labels = reads (ST, ML, Redo_v53, Blind_v57 + `adjudication.csv`) **plus every object in a radiologist-zero
  hemisphere as negative** (`review/radiologist_grades.csv`). Reports LOPO AUC and an honest leave-one-patient-out check.
  Cut default (v5.10.2) = 0.9 × lower of final-model and LOPO minimum cSS confidence; `--cut-insample` = old optimistic cut; `--cut X`.
- `v53_compare.py` (v5.10.2) relabels reader cSS calls in radiologist-zero hemispheres (`CSS_GRADES`).
- `tools/run_v510.sh` (v5.10.1–4): module check, redetect (skipped only if lists hold the measures AND no low-confidence exclusions),
  fit, acceptance, apply on M02–M15; `CUT_ARGS` passes cut options.
- Side guard (v5.10.5, fixed v5.10.6): the confidence rule may never empty a hemisphere; keeps its highest-confidence E30 object.

### Data-handling and workflow tools
- Vein → **Vessel** everywhere user-facing (v5.9.1). Old files saying "Vein" are read as Vessel through `css_common.norm_call`
  (never rewritten). Internal column names (`vein_evidence`, `vein_tree_mm`, `vein_like`, label names `vein_surface`…) **kept on purpose**.
  `expert_import.py --vein` kept as alias of `--vessel`. Tested: `check_vessel_rename.py`.
- `snapshot_from_backup.py`, `inherit_calls.py` delivered (inherit_calls existed since v5.5.2 but had never reached the user's install).
- `pial_compare.py` / `probe_common.py` crash fixes (real label volumes, non-3-D guard), `compare_pipelines.py` adjudication columns.

### Files created in this session  [repo: git diff --name-status 1f5146b HEAD]
scripts: VERSION, compare_pipelines.py, compare_reads.py, css_confidence.py, css_shape.py, css_sheet3d.py, fit_confidence.py,
midline_probe.py, pial_compare.py, probe_common.py, run_experiment.py, shape_probe.py, snapshot_from_backup.py, struct_probe.py, zone_probe.py.
tests: check_compare_pipelines.py, check_confidence.py, check_pial_compare.py, check_probe_common.py, check_shape.py, check_shape_probe.py,
check_sheet3d.py, check_struct_probe.py, check_vessel_rename.py, check_viewer.js, check_viewer.py, check_zone_probe.py.
tools: check_e22_pieces.sh, make_all_code.py, make_release.sh, rerun_failed_v57E.sh, run_all_v57E.sh, run_v510.sh, run_v58.sh.
docs: AUDIT_IMPLEMENTATION_PLAN_v5.7.md, AUDIT_v5.6.4_and_PLAN_v5.7.md, CHANGELOG_audit_branch.md, CHANGELOG_v5.7.md,
HOW_TO_ACCEPT_v5.7-C.md, HOW_TO_REDO_M02-M06_v5.7.md, HOW_TO_RUN_v5.7-D.md, HOW_TO_RUN_zone_probe_v5.7.md, HOW_TO_audit_experiments.md,
PLAN_v5.8_search_zone.md, PROMPT_v5.7_implementation.md, adjudication_M02-M11_v1.csv. Plus this file.

### Files modified in this session
ALL_CODE.md, CLAUDE.md, docs/CHANGELOG_v5.6.md, scripts/css_common.py, css_report.py, detect_css.py, expert_import.py,
export_candidates.py, feature_report.py, review_css.py, review_web.html, review_web.py, score_css.py, v53_change_report.py, v53_compare.py,
tests/check_inherit.py, check_labels.py, check_review_web.py, check_v53.py, run_tests.sh, tools/build_workbook.py.
(Other test files were edited only for the Vein → Vessel rename.) No files were deleted.

---

## 5. Testing status

### Automated (this sandbox, synthetic phantoms only, no FreeSurfer)  [test]
- `bash tests/run_tests.sh` — **ALL TESTS PASSED, exit 0**, run on the v5.10.6 code (log in the session scratchpad; last stage is
  check_inherit). Earlier full runs also passed at v5.9.1 and v5.10.0.
- Individually re-run after the last edits: `check_v53.py` OK, `check_confidence.py` OK, `check_review_web.py` OK, `check_viewer.py` OK.
- Not run in this session: `tests/test_shell.sh` (stubbed FreeSurfer shell flow).
- What the tests prove: mechanics (rules fire on constructed cases, switches off = unchanged, no phantom lesion lost, read-only probes do
  not touch the project). They say **nothing about performance on patients**.

### Real data (user's Mac)  [Mac]
- Cohort M01–M15 (radiologist grades R/L): M01 0/0 (not available), M02 0/2, M03 1/0, M04 0/2, M05 2/1, M06 2/1, M07 1/0, M08 2/1,
  M09 0/2, M10 2/0, M11 2/2, M12 2/0, M13 2/2, M14 0/2, M15 2/2. (Stored by `run_v510.sh` in `review/radiologist_grades.csv` on the Mac.)
- 1.5 T 3 mm SWI in M01/05/11/12/13; 3 T elsewhere; phase only in M08. All processed with recon-all.
- Readers: ST (the user), ML (second reader), Redo_v53 / Blind_v57 / first (older reads by the user).
- **ST vs ML on M02–M06** (meter visible): cSS-vs-not agreement 92 %, kappa 0.83. Against the radiologist: ML exact in 8/10 hemispheres,
  ST 6/10; both missed M02 left (L1 vs L2) and M03 right.
- `--show-excluded` audit of M02/M03 by ST: 102 excluded objects, **0 called cSS** (rules did not remove the missing lesions).
- **Held-out M12–M15** (blind ST read, v5.8.3 rules): total score exact 3/4 (AI 2/4), hemispheres exact 2/8 for both; M13 read 0 vs
  radiologist 4 (ST called 8/10 candidates Artifact). Reading, not detection, was the main error.
- **Confidence model fit (M02–M11, full lists):** 141 labelled objects (54 cSS / 87 not), LOPO AUC **0.69** vs score_v4 0.66 (in-sample 0.86).
  Cut 24.2 % (in-sample): 0 cSS lost / 28 non-cSS removed in-sample; **LOPO honest check: 6/54 cSS lost**, 22/87 non-cSS removed.
  Applied with `--cut-insample` (user chose aggressive exclusion). Acceptance 47/47 radiologist-consistent cSS calls kept.
- **Held-out effect of the 24.2 % cut:** 51 → 36 candidates; excluded 15 = 6 Artifact, 4 Vessel, 1 Normal, **4 cSS** (all M15 right,
  where 8 cSS objects remain; incl. one 223 mm³ rostral middle frontal object). No patient score changes by the counts.
- v5.10.6 (side guard) redetect: **commands given, result not yet received.**

### Expected output files per study (`$CSS_BASE/review`)
`ID_candidates.csv/.nii.gz`, `ID_excluded.csv/.nii.gz`, `ID_rule_audit.csv`, `ID_manifest.json`, `ID_qc.json`, `ID_calls*.csv`,
`ID_score*.json`, `ID_final_<name>.json`, `ID_review_log.csv`, `ID_missed.csv`, `ID_surface_features.csv`; work/: `ID_dropped.csv`,
`ID_dark.nii.gz`, `ID_pial_sd.nii.gz`, `ID_gen.nii.gz`, `ID_seg_swispace.nii.gz`. Column contract: new columns are **appended only**
(check_v53 asserts the last 36 column names).

### Regression risks
- Any change of the search zone or object shape (not just exclusion) changes seeds and objects: v5.3.0 and v5.3.1 each lost 3 cSS this way.
- The confidence model is fitted on 10 patients and depends on the column set; `css_confidence.load` refuses a model whose feature list differs.
- `run_v510.sh` skip logic: a fit on already-reduced lists is meaningless (happened once: AUC 0.47, cut 0 %); fixed in v5.10.4.
- Viewer changes: check_viewer.js covers layout, mirror, panel, themes, 3-D card; not every menu.

---

## 6. Current state of the user's data  [Mac, as last reported]

- M02–M15 lists: detector v5.10.4+ code, `CSS_V53=1 CSS_ZONE2=1 CSS_CONF=1`, confidence model cut 24.2 % (fitted on M02–M11, in-sample cut).
  Counts: M02 4, M03 11, M04 23, M05 4, M06 12, M07 9, M08 7, M09 7, M10 16, M11 25, M12 11, M13 6, M14 5, M15 14.
- Backups of earlier lists: `review/backup_<date_time>/` (several, latest 20261112_*).
- `review/confidence_model.json` (cut 24.2), `review/radiologist_grades.csv`, `review/adjudication.csv` (6 decisions).
- Reads on the current lists: ST and ML on M02–M06 were made on the v5.8.2 lists; ST blind read of M12–M15 on v5.8.3 lists. Objects removed
  since then lose their calls in those files (calls are matched by fingerprint; unmatched calls are reported, never moved).

---

## 7. Known issues and outstanding work (prioritised)

### P0 — affects reliability of current results
1. **Confidence cut loses cSS on new patients.** LOPO: 6/54 at 24.2 %; held-out: 4/21 ST cSS calls in M15 (one 223 mm³). The user chose this
   aggressive cut knowingly. Next action: get the user's verdict on the four M15 objects (`review_web.py M15,M13 --reviewer ST --open
   --show-excluded`). If real: add a **size guard** (never E30 above a volume, e.g. 150 mm³) in `exclusion()` in `scripts/detect_css.py`,
   test in `tests/check_confidence.py`, re-run `run_v510.sh`. Do not lower the cut silently; the user decides.
2. **v5.10.6 side-guard redetect not confirmed on the Mac.** Ask for the output (`grep "side guard"` lines).
3. **Patient scores after all list changes were never recomputed against the radiologist** for M02–M15 together. The reads were made on
   older lists. Next: `compare_grades.py` / `css_report.py` once the reads are current.
4. **GitHub push blocked (403).** The user must reconnect GitHub (claude.ai → Settings → Connectors). Until then the user's Mac is the only
   other copy; local commits exist only in this sandbox.

### P1 — scientific validity
1. **Reading accuracy is the main error** on held-out cases (M13 read 0 vs 4; sides wrong in M12/M14). ML's blind read of M12–M15 is still
   missing. Next: commands `review_web.py M12,M13,M14,M15 --reviewer "ML"` (no `--open`), then `compare_reads.py ... --reviewer ML --old-reviewer ST`.
2. **Radiologist's missing lesions (M02 left 2nd sulcus, M03 right)** are neither shown nor excluded objects (ST audit). Either never
   generated or read as Vessel. No location from the radiologist exists; missed-cSS drawing (`X` in the reviewer) is the only way to learn
   the detector fate.
3. **Thresholds fitted on M02–M11 with one non-expert reader** (repeat-read kappa 0.65 meter visible / 0.87 hidden). Every rule E12–E30 is
   "low" confidence in `RULE_CONF`.
4. **E28/E29 (3-D ball/tube) unfitted.** `struct_probe.py` was delivered (v5.9.0/5.9.1) but the user never sent `results_struct.zip`.
   Fit only with protected cSS = 0 and ≥ 10 % margin.
5. **0–4 score depends on recon-all Destrieux labels**; the fast route (SynthSeg) falls back to a Euclidean approximation that gave L2 vs L1
   on P006. Validate before switching.
6. M12–M15 have now been seen once; any further tuning on them is contaminated — say so in any report.

### P2 — performance and architecture (user wants ~3000 cases)
1. Time per MRI ≈ 2 h, mostly recon-all. **Fast route already exists** (`run_css.sh` without `--recon`: SynthSeg + mri_coreg, est. 10–15 min,
   still needs FreeSurfer installed). Next: comparison script on 3 patients (fast vs recon-all: labels, candidates, cSS kept, 0–4 vs radiologist);
   mri_coreg slipped 3.9 mm on P011 → QC flag must gate batch cases.
2. Detection ≈ 4 min/case [Mac estimate]; `struct_feats` + `cont_feats` run for every object including ones later excluded — compute after the
   cheap rules. Add per-stage timing to the manifest first.
3. Batch runner: parallel workers with memory cap, resume, one summary row per case, QC-based flagging. Cluster (Slurm array) or institutional
   HPC recommended for patient data; FreeSurfer runs on Linux.
4. FreeSurfer-free version (FastSurfer/SynthSeg package + rigid registration library) is possible but large; sulcal scoring needs a Destrieux
   replacement. Not started.
5. ALL_CODE.md is stale (regenerate with `tools/make_all_code.py`).

### P3 — research opportunities
- ICH: cut objects at the ICH border; sulcal distance to the ICH (Charidimou ≥ 3 unaffected sulci rule) using `ich_contact_frac`. Tools
  surveyed (none ready for SWI ICH): DeepBleed, ICH_segmentation (MATLAB, unsupervised), ichseg (CT). Microbleed tools: SHIVA-CMB, DEEPMIR,
  MixMicrobleed — could supply a microbleed mask to separate CMB from cSS.
- Ranking/classification model on more patients (train_ranker.py, classify_surface_patches.py exist; nested LOPO).
- Triage for 3000 cases using the confidence model (clear negative / clear positive / uncertain).

---

## 8. Failed or rejected approaches (do not repeat without new evidence)

| Approach | Result | Where |
|---|---|---|
| Narrowing the search zone (v5.3.0) | shifted ridge percentiles, lost 3 cSS | CLAUDE.md v5.3.1 |
| Trimming object voxels > 1.5 mm outside cortex (v5.3.1) | 3 cSS fell below size gates | CLAUDE.md |
| E22 on the merged object | lost M11 #12 (merged 29.5 mm sheet) → pieces | v5.7-E-fix2/3 |
| E26 outside cortex+sulci | lost M04 #28 at 0.42, ≤ 1 gain → off | v5.8.1 |
| "Depth from brain surface > 21 mm" rule | would lose 3 cSS calls | analysis v5.8.4 |
| region_z (darkness vs own region) rule | loses 2 of 6 known P006 lesions | CLAUDE.md v4.19.2 |
| Blob / microbleed rule on object shape | called microbleeds measure 17–28 mm, fill 0.06–0.17 | shape_probe |
| "Straight in sulcus" rule | ≈ 4 objects gain, fragile margin (M10 #3) | shape_probe |
| Mesh-based pial distance (audit F1) | AUC 0.57 vs 0.57, F1 not supported | pial_compare |
| Soft generation gates (F4) | +114 objects to read, no cSS gained | run_experiment |
| 3-D plate seeds (F2) | 77–87 % overlap, 4 tiny extra objects | recorded only |
| Patient-wise normalisation of confidence features | LOPO AUC 0.72 → 0.72, no gain | offline analysis |
| Size alone as a rule | 12 of 56 cSS < 50 mm³ | analysis |
| vein_tree_mm / mirror features | merge brain-wide / uninformative | CLAUDE.md |
| SynthStrip on whole-head images | 31–85 GB, froze the Mac | v5.2.4–6 |

---

## 9. Git, delivery and environment

- **Branch in use:** `fix/audit-v5.7-priority1` (created at the user's request), HEAD `4b4059d` "v5.10.6: side guard moved after the per-object
  loop". The designated push branch is `claude/css-detection-audit-2esnbb` (local copy is old, at `7936c16`). Push command used:
  `git push -u origin fix/audit-v5.7-priority1:claude/css-detection-audit-2esnbb` — fails with **403** (GitHub authentication required).
  No remote-tracking branch exists. Nothing has reached GitHub from this session.
- Working tree at handoff: clean except this new file `PROJECT_HANDOFF.md` (untracked, not committed per the user's instruction).
- **Delivery to the user:** zip of changed files (`zip -q <scratchpad>/cSS_vX_update.zip scripts/... tests/... tools/...` from
  `cSS_pipeline_v4.13/`), sent with SendUserFile; user installs with
  `cd ~/css_project && unzip -o ~/Downloads/<zip> -d ~/css_project && conda activate css && cat scripts/VERSION`.
  Lesson learned: ship **cumulative** zips (a missing intermediate zip broke v5.10.0 on the Mac). Last zip sent: `cSS_v5.10.6_update.zip`
  (detect_css.py, VERSION, check_confidence.py, check_v53.py, run_v510.sh).
- Commit messages end with the attribution lines given by the system reminder; never put model names in code or docs.
- Sandbox: python 3.13 with the packages of environment.yml; Playwright + Chromium preinstalled for check_viewer; no FreeSurfer.

---

## 10. Exact next recommended action

Ask the user for (a) the output of the v5.10.6 redetect command (`side guard` lines and `done:` line) and (b) their verdict on the four
M15 cSS objects excluded at 24.2 % (especially the 223 mm³ rostral middle frontal one). Then:
- if any of them is real cSS → implement the size guard for E30 (P0-1), test (`tests/check_confidence.py`, full suite), deliver a cumulative
  zip, and re-run `tools/run_v510.sh` with `CUT_ARGS="--cut-insample"`;
- otherwise → move to P1-1 (ML's blind read of M12–M15) and P2-1 (fast-route comparison script on three patients).
