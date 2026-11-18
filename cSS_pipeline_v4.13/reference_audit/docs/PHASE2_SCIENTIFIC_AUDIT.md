# Phase 2, Task 1 — scientific audit of the real-data validation (run 20261118T195441Z)

All numbers below were recomputed from the run's own tables:
- `all_objects_full_table.csv`
- `MODULE_PERFORMANCE_COMPARISON.csv`
- `analysis_log.txt`
- `reader_missed_marks.csv`

I also read the analysis code again. Where my previous interpretation (`VALIDATION_INTERPRETATION.md`) was wrong or incomplete, it is stated below.

## 1. Object counts and denominators

| Quantity | Value | Check |
|---|---|---|
| Objects | 954 = 154 shown + 800 rule-excluded | dev 664 (118 shown / 546 excluded); held-out 290 (36 / 254) |
| Generation-gate drops | **not included** | the run never evaluated `work/ID_dropped` objects |
| Reads used | 496 from 5 readers | 56 of them inherited calls |
| Calls left out because the list was re-detected | **140** | my interpretation said "115" — **wrong**; the log sums to 140 |
| Labelled objects, dev | 42 cSS (22 definite + 20 probable) vs 176 non-cSS | — |
| Labelled objects, held-out | 15 probable vs 19 non-cSS | single reader, so "definite" is impossible |

**The dev negatives are of two kinds.**
- 47 are shown objects.
- 129 are rule-excluded objects read in excluded-object audits.
  - These audits exist for M02–M06 only.
  - They were read with `--show-excluded`, where **the viewer shows the exclusion rule**, so the reads were not blinded.

The held-out negatives are 19 shown objects only. The dev and held-out denominators are therefore different populations.

## 2. Correction: dev AUCs were inflated by easy negatives

The "dev AUC" pooled shown candidates with rule-excluded objects that are mostly obviously not cSS (skull band, tentorium and similar). Restricted to the clinically relevant question — is a **shown** object cSS? — the results change:

| Score | Dev, all labelled (as reported) | **Dev, shown objects only (42 vs 47)** | Held-out, shown only (15 vs 19) |
|---|---|---|---|
| Production score_v4 | 0.76 | **0.67** | 0.33 |
| Production meter | 0.66 | 0.54 | 0.41 |
| E same-depth contrast | 0.68 | **0.53** | 0.44 |
| B subpial share | 0.67 | **0.46** | 0.44 |

- **What changes:** the earlier statement "E is the best experimental score (0.68)" is wrong in substance. E only re-discovers what the exclusion rules already removed. Among shown objects it is at chance.
- **What stands, and is stronger:** no module improves on production.
- **Production is weak too.** Among shown objects score_v4 reaches 0.67 in development (fitted on the same patients) and 0.33 on held-out. The production ranking itself is not established.

## 3. Production sensitivity was never measured

- Every labelled cSS object was a shown object, because cSS calls could only be made on shown objects. Excluded objects were read only in unblinded audits (M02–M06), and generation-gate drops not at all.
- **The "100 % sensitivity" in the run's tables is a property of the labelling, not a measurement.** My interpretation said so; the auto-generated tables do not, and must not be quoted.
- **Direct evidence of misses already exists.** The reader-drawn missed-lesion marks are 11 rows, 10 unique: M06 #1 and #2 are the same point.
  - 6 overlap a shown candidate. These record the extent of a lesion beyond the candidate, not a miss.
  - At least 4 are production misses:

| Mark | Production fate |
|---|---|
| M06 #3 | never generated |
| M06 #5 | never generated |
| M06 #4 | below a generation gate |
| M14 #1 | rule-excluded: "off the cortex" |

  - A further mark, M06 #1, lies partly in two skull-band exclusions and a gate drop.
  - These came from casual marking during candidate review, not a systematic search, so they are a floor, not an estimate.

## 4. Cross-validation and leakage

- **LOPO code** (`css_model.lopo`, read again):
  - one patient left out per fold;
  - median imputation and scaling are fitted on the training patients only;
  - L2 fixed at 1, no feature or threshold selection inside folds;
  - feature sets were fixed before the run.
  - Correct. Note that the pooled LOPO AUC mixes predictions from 10 different models.
- **Bootstrap:** every confidence interval resamples patients (2,000 resamples). Correct. With 10 dev and 4 held-out patients, the intervals are themselves unstable.
- **Leakage into production performance** (not into the modules):
  - Production rules E12–E30 and the confidence cut were tuned on M02–M11 calls by the same readers.
  - Many of those calls were made with the AI meter visible.
  - Production's dev numbers are therefore optimistic. The held-out drop (0.67 → 0.33 among shown objects) is consistent with that.
- **Module thresholds:** fixed from definitions and phantoms (one phantom amendment), not from patient data. No module threshold was tuned on M02–M15 in this run.
- **Held-out use:** in this run M12–M15 were only scored, never fitted (`LOPO` runs on `cohort == "dev"` only). They had been examined once before, during the feature validation, so they are held out from tuning but not pristine.
- **Label leakage:** inherited calls (56) were carried from earlier lists by the same reader. They are not independent reads.

## 5. Three kinds of performance — kept apart

| Kind | What the run computed | Limits |
|---|---|---|
| Object-level AUC | P(cSS object scores higher than a non-cSS object), patient-bootstrap CI | Mixed populations (section 2); reader labels |
| Patient (hemisphere) level | Binary: hemisphere positive if ≥ 1 object passes; reference = radiologist side grade > 0 (dev 14 positive / 6 negative sides) | **No patient-level AUC was computed.** Production shows objects on every hemisphere, so its patient-level specificity is 0 by construction. |
| Threshold-based | Sensitivity, specificity, PPV, NPV, F1 at fixed pre-registered rules | Conditional on the shown list (section 3) |

## 6. Other checks

- **Inter-reader agreement (aggregate, 5 anonymised readers, 10 pairs, 431 paired object reads):** median Cohen kappa 0.68 (interquartile range 0.65–0.72), median raw agreement 0.84. Some pairs rest on 3 patients only; per-reader values are kept out of the repository.
- **Disputed objects:** 14 in dev, excluded from the primary analysis.
- **Verdict rule:** applied as pre-registered. All five modules fell into "should not be integrated (as a filter)" because each lost cSS that production shows.
- **Reproducibility:** module columns identical alone vs combined (114 / 114); production files unchanged (sha256).

## 7. Conclusion of the audit

- **Still valid:** none of modules A–F improves on production. Among shown objects the case is stronger: E and B are at chance.
- **Not supportable, and must be withdrawn:**
  - any statement about production sensitivity;
  - the 0.76 dev AUC as a measure of how well production ranks what readers see;
  - "E is the most promising module".
- **Root problem:** the reference standard.
  - The labels are calls on detector-selected objects.
  - The audits of excluded objects were not blinded.
  - Generation-gate drops and never-generated lesions were never read.
  - Phase 2 Tasks 2–6 address exactly this.
