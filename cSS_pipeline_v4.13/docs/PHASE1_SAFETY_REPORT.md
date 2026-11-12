# Phase 1 report - safety fixes (branch `phase1/safety-fixes`, baseline tag `baseline-v5.10.6`)

Research software; expert review required. Nothing here is a claim of clinical accuracy.
Evidence tags: [code] in the repository, [test] run in the sandbox on synthetic phantoms, [Mac] from the user's earlier runs, [todo-Mac] must be measured on the user's data.

## Scope
Only the four requested items. No detection threshold, exclusion rule or scoring logic outside them was changed.
With thin slices (< 2.4 mm), an acceptable registration and no confidence model, the detector's output is byte-identical to v5.10.6 apart from one appended
column (`single_slice`, always 0) [test: check_phase1 part 1, check_v53].

## 1. Slice gate (generation gate G2)
- Before: an object needed >= 2 slices. Set on 1.2 mm slices (2.4 mm through-plane). On 3 mm slices it meant >= 6 mm, so a focus on one slice was dropped.
- Now: passes when it spans >= 2 slices OR slices x slice thickness >= `MIN_SI_MM` = 2.4 mm. 2.4 mm is not a new fitted number: it is the old gate
  expressed in mm on the protocol it was set on. Volume (>= 25 mm3) and elongation (>= 2.0) gates are unchanged and still apply.
- Objects admitted only by the mm criterion carry `single_slice = 1` (appended column). `CSS_SLICE_GATE=legacy` restores the old gate. Recorded in the manifest.
- Files: `scripts/detect_css.py` (`passes_slice_gate`, gate G2, 3-D seed list, column, manifest).
- Tests [test]: 1.2 mm phantom: identical lists with and without the switch. 3.6 mm phantom (PH3 slices averaged in threes): every legacy object kept,
  objects 10 -> 29 before exclusion rules, the 19 added all `single_slice = 1`; shown list 9 -> 10; true lesions 6/6 in both.
- Concern: on the phantom the fix added candidates and found no extra lesion (all six were already found). Whether it recovers real single-slice cSS, and
  how many extra objects it costs on real 3 mm scans, is unknown [todo-Mac: tools/phase1_measure.sh step 2, on copies of M05 and M11].
  Only the user's 3 mm studies are affected (M05, M11, M12, M13).

## 2. Confidence exclusion (E30)
Review of the logic [Mac data]:
- The applied cut (24.2 %) was the minimum over the model's own training patients. Leave-one-patient-out: 6 of 54 cSS fall below it.
- A size guard was considered and NOT added: on the development data it does not help (all six leave-one-patient-out losses are < 100 mm3; a guard at
  60 / 80 / 100 / 150 / 200 mm3 leaves 5 / 5 / 6 / 6 / 6 of them lost). The only evidence for a size guard is one 223 mm3 object in M15, an evaluation
  patient; using it would be tuning on evaluation data.
Changes:
- `fit_confidence.py` writes `cut_method` (lopo_min / insample_min / manual) and refuses any study listed in `review/evaluation_studies.txt`.
- `detect_css.py` applies E30 only for `cut_method = lopo_min`. Any other model (including the user's current file, which has no cut_method) is NOT applied
  unless `CSS_CONF_ALLOW_OPTIMISTIC=1`; `confidence_pct` is still recorded; a message says so. The manifest records model present, role of the study
  (development = fit study, evaluation = other), cut, method, and whether the exclusion was applied.
- `eval_confidence.py` (new, read-only): reports a frozen model on evaluation studies, refuses fit studies, prints the "already examined" note.
- Consequence the user must know: the next redetect with `CSS_CONF=1` will NOT apply the current 24.2 % model. The lists return to the no-confidence-exclusion
  state unless the model is refitted with the default cut (about 8 % on the earlier fit, about 5 non-cSS removed) or the override is set deliberately.
- Tests [test]: check_phase1 part 3; check_confidence (fit, cut below every in-sample and leave-one-patient-out cSS, side guard).

## 3. Registration gate
- Before: a measured label shift > 1.5 mm only set `low_confidence_review`; lists and scores were produced.
- Now: `css_qc.py` writes `registration_ok` (true / false / null = not measurable) and `registration_note`. With T1 anatomy and `registration_ok` false,
  `detect_css.py` stops with exit code 5 BEFORE writing any list (existing lists, calls, fates untouched), records `detect_refused` in the manifest;
  `score_css.py` refuses with exit code 5. `CSS_ALLOW_BAD_REG=1` proceeds knowingly. The limit is the existing `EDGE_LOW_CONF_MM` (1.5 mm); no new threshold.
- Not measurable (null) is NOT treated as a failure: it stays `low_confidence_review`, as before. This is a known gap: an unmeasurable registration is unverified.
- KNOWN FALSE ALARM [test]: the shift is measured by fitting the label boundary to the SWI cortex edge. A dark band just outside the cortex fools it: the
  synthetic skull phantom (labels exactly aligned, dark line 0.6-2 mm outside the cortex) reads a 2.33 mm shift and is stopped. The failure direction is safe
  (a valid case is held back, never a bad one scored), and the override exists, but on real scans with thin CSF and a dark inner skull table the gate may
  stop correctly registered studies. The user's studies have read 0.1-0.2 mm so far [Mac]. Making the estimator robust to this is a separate change.
- Files: `scripts/css_qc.py`, `scripts/detect_css.py`, `scripts/score_css.py`.
- Tests [test]: check_qc (shift 0 / 0.8 mm run, >= 2.5 mm stop with exit 5 and no list), check_phase1 part 2 (lists keep their bytes, manifest entry, score refused, override works).
- Expected effect on the user's studies: none (label shifts reported so far 0.1-0.2 mm) [todo-Mac: tools/phase1_measure.sh step 1 lists every study].

## 4. Records and fates
- The fate invariant is unchanged and still enforced (exit 4). New objects from the slice gate enter the same shown / excluded / dropped bookkeeping.
- A stopped detection writes nothing over existing files [test].
- Not changed in this phase (still a risk, audit item Mo1): `redetect.py` replaces `review/ID_candidates.*` in place after a backup. Versioned detection
  folders are a Phase "foundations" item and were not requested here.

## 5. Regression tests added or changed
- `tests/check_phase1.py` (new; in `run_tests.sh`): the three parts above.
- `tests/check_qc.py`: accepts exit 5 from the detector for shifted labels and asserts the gate.
- `tests/check_v53.py`: column contract now ends with `single_slice` (37 appended columns).
- Full suite and shell-flow test: see "Test status" in the chat report for this commit.

## 6. Modified files
scripts/detect_css.py, scripts/css_qc.py, scripts/score_css.py, scripts/fit_confidence.py, scripts/run_experiment.py (new switches allowed),
scripts/eval_confidence.py (new), tests/check_phase1.py (new), tests/check_qc.py, tests/check_v53.py, tests/run_tests.sh,
tools/phase1_measure.sh (new), docs/PHASE1_SAFETY_REPORT.md (new), scripts/VERSION (v5.11.0-phase1), PROJECT_HANDOFF.md (added to the repository).

## 7. Open decisions for the user
1. Slice gate: keep the mm gate as default, or keep legacy until the measurement on M05 / M11 is in.
2. Confidence exclusion: refit with the leave-one-patient-out cut, keep the 24.2 % cut with the explicit override, or switch the exclusion off.
3. Whether an unmeasurable registration should also stop the detector.
