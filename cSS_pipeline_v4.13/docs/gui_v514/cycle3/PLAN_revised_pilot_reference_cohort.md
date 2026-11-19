# Revised development plan: independent blinded pilot reference cohort (35 studies)

Status: plan and sketches only (`SKETCH_pilot_blinded_review_v3.png`); nothing in it is built. Branch `experimental/unified-gui`, uncommitted.

## What changed in the plan
- **Primary reference:** the 35-study pilot read *from scratch*, blinded, replaces the ~500 AI-assisted reviews.
- **The ~500 historical records:** kept unchanged on disk as "historical AI-assisted" and used only for comparison. Never deleted, never relabelled as independent.
- **The local audit script:** still useful for the historical inventory and for patient grouping. It is no longer on the critical path.
- **Training:** none. Not on the pilot, not on historical data, until you decide after the pilot evaluation.

## Building blocks already in the repository (to be reused, not rewritten)
| Existing | Use in the pilot |
|---|---|
| `reference_audit/blind_read/blind_read.py` | Blind whole-scan reader. It opens only blinded case folders, never detector lists, masks or scores, and writes lesion / patient annotations with an append-only log. Basis of stage ① |
| `reference_audit/annotation_schema.py` | Categories definite / probable cSS, non-cSS type (vessel kinds, artifacts …), indeterminate, confidence 1–5, morphology, patient columns. Extended with "artifact" / "other" as top-level classes as you specified, mapped from the existing non-cSS types |
| `reference_audit/agreement.py`, `evaluate.py` | Matching, agreement, patient-grouped evaluation for stage ③ and the pilot report |
| Reviewer validation read (v5.7) | Shuffled numbering, meter / score locked: basis of stage ② |
| `label_missed.py` fates | "Missed by detector": excluded by rule / dropped at a gate / not generated |
| Processing Manager backend | New detection run per study with anatomy reuse and separate run archive |

## Workflow per study
0. **Prepare.**
   - The Processing Manager creates a **new run** for every pilot study.
   - **Reused, only if compatible:** FreeSurfer, registration, alignment.
   - **Always re-run:** detection, morphology, features and scoring, with the current pipeline version.
   - The historical run is archived, never overwritten.
   - Pilot runs are tagged `pilot-P1`.
   - The new AI outputs are written and hashed **before** the reveal, so they can't be changed after the reader's answers are known.
1. **Blind read (stage ①):**
   - The reader sees the MRI only: no candidates, scores, historical labels or conclusions.
   - The reader marks their own lesions and fills the study-level assessment.
   - **Lock** creates an immutable record; later edits become a new version marked "revised after reveal".
2. **Candidate labels (stage ②):**
   - The new run's candidates are shown with shuffled numbers, no score / meter / explanation.
   - Six classes plus confidence; then lock.
   - **Your decision:** these outlines *are* detector output. Keep stage ② as a separate step, or drop it and label candidates only through matching in ③.
3. **Reveal and compare (stage ③):**
   - Your lesions and the candidates are matched one-to-one (≤ 5 mm, as in `robustness.py` / `evaluate.py`).
   - Outcomes: detected and agree / missed by detector (with its fate) / false-positive candidate / disagreement / unresolved.
   - Comments; send to a second reader or an expert; the adjudicated label is stored as its own record.
   - Nothing is changed automatically.

## Records (append-only, each with provenance)
| Record | Never overwritten by |
|---|---|
| locked blind read: study-level + own lesions | anything; a revision is a new version |
| locked candidate labels | anything |
| new AI run: candidates, morphology, x1–x5 with reliability, score, explanation, model id / hash, pipeline build | human labels |
| match table + outcomes | — (recomputable, versioned) |
| comments, adjudication (reader, role, date, status) | — |
| historical AI-assisted calls / runs | the pilot |

Provenance tags:
- independent blinded review (pilot);
- AI-assisted historical;
- expert-adjudicated;
- uncertain / unresolved.

## Scientific safeguards
- **Patient grouping:**
  - A pseudonymous patient key is entered per study when it is added to the cohort.
  - Repeat examinations are grouped and shown together.
  - Any future split works by patient key only.
- **Held-out studies:** if a held-out study is in the 35, it can be reviewed, but it is flagged and excluded from every training, tuning or threshold choice. The `LabelAccess` lock and the authorization rules stay in force.
- **No automatic training.** The pilot cohort carries `training: off`; only you can switch it later.
- **Everything stays on the Mac.** The pilot evaluation report is counts / aggregates only.

## Pilot evaluation (before any training decision)
- **Annotation quality:**
  - share indeterminate;
  - confidence distribution;
  - "revised after reveal" rate;
  - intra-reader agreement if some studies are re-read after a washout (optional).
- **Pipeline performance on the independent labels:**
  - lesion detection sensitivity, with missed-lesion fates;
  - false-positive candidates per study;
  - study-level agreement.

  All grouped by patient, with patient-bootstrap CIs and the small-n limits stated.
- **Workflow:**
  - time per stage;
  - unresolved cases;
  - adjudication load.
- **Comparison with the historical AI-assisted labels** for the same studies, as a measure of possible automation bias. Comparison only.

## Revised order of work
1. Your decisions on sketches v2 (Processing Manager) and v3 (pilot / blinded review), plus the open points below.
2. Processing Manager screens and the backend gaps: six categories, image identity, FreeSurfer version, per-run errors, Resume.
3. Pilot cohort module:
   - cohort list and patient keys;
   - "prepare new runs" (reuse anatomy, new detection);
   - stages ①–③ built on the existing blind reader and validation read;
   - lock / versioning, matching, adjudication, pilot report.
4. Tests on synthetic studies:
   - nothing from earlier runs reaches stage ①;
   - locks hold;
   - AI outputs can't change after the reveal;
   - historical records stay unchanged;
   - repeat examinations of a patient stay grouped;
   - held-out flags are respected.
5. Your 35-study read on the Mac (yours alone; nothing leaves the Mac).
6. Pilot evaluation, then a decision on further reading or any training.
7. Only after that: AI Learning & Review, Model Laboratory, local assistant (sketches first).

## Decisions needed from you
1. **Stage ②:** keep it (candidates shown, scores hidden) or drop it (labels only via matching after the reveal)?
2. **Study-level fields:** is "focal / disseminated + L / R 0–2 (the 0–4 scale)" the severity you want, or another scale?
3. **Match distance:** ≤ 5 mm one-to-one as in the existing evaluation code, or another rule?
4. **Held-out studies among the 35:** allow them as flagged and never trained (as sketched), or leave them out of the pilot?
5. **Second reader / expert adjudication:** who, and is it in scope for the pilot now or later?
