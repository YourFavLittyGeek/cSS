# LUMOS learns from the expert-marked missed cSS (2026-11-25, user decision)

**Why.** A missed cSS is a lesion the expert saw and ALBUS did not detect. Before this change only ALBUS (sensitivity, detector
versions) and PERCIVAL's detection labels used the marks. LUMOS (the image module) learned only from detector candidates, so it
never saw the lesions the detector misses.

**How a mark becomes an image example**
1. The mark is read from `review/ID_missed.csv`: rectangle, pen outline or point, in the reviewer's canonical voxel coordinates.
2. The drawn region is formed: the box, the filled outline, or the voxel, plus or minus 1 voxel through the drawn plane. It is
   then mapped onto the SWI grid.
3. The object is the dark voxels inside the drawing (largest connected part):
   - the detector's own dark map (`work/ID_dark.nii.gz`) when it has voxels there,
   - otherwise voxels below -3 robust SD of the local brain,
   - otherwise the drawn region itself.
   The object never grows beyond the drawing: on the phantom, growing leaked into neighbouring veins.
4. The patch comes from the same surface-aligned extractor, frame and size as every candidate patch (`patches.extract_marks`).
   It is cached in `percival/cache/ID.npz` as `missed_<id>`.

**Which marks are used**
A mark is used only when it meets all of these:
- it is eligible expert truth: an expert reviewer and an eligible read,
- the patient is in the development partition,
- the study is included,
- it does not lie on a candidate the detector showed (that candidate has its own call).

**How they enter training**
- Marks are extra cSS examples in LUMOS's training folds, and only for that fold's training patients. A held-out fold patient or a
  locked-test patient is never used.
- Every out-of-fold prediction, metric, PERCIVAL input and test result stays on candidates.
- A drawn mark only partly resembles a detector candidate: one drawn slice gives a partial object and a different surface frame.
  For that reason, every cycle trains LUMOS on the same folds with and without the marks. The marks are used only when LUMOS's
  log loss on the candidates is not worse. The decision and both results are stored in the model:
  - `data.lumos_missed_marks`
  - `intelligence.families.image.missed_marks`
  - `modules.LUMOS`
  The Model Center module card shows "N missed-cSS marks learned".
- Nested cross-fitting uses the cycle's decision; it does not compare again inside each outer fold, to save time.
- The marks are part of the dataset hash.

**Not done:** NOX gets no measurements for marks (there is no detector object, so the 30 measurements do not exist). PERCIVAL
does not score marks.

## LUMOS checks the marks + second look (2026-11-25, user decision: built, inactive until enough marks)
**LUMOS checks the marks.** In every training cycle, each fold model scores the missed-cSS marks of the patients it was not trained
on. The result is stored as `heldout_check` (n, recognised, recall). It is the readiness test.

**Second look** (`uengine/percival/second_look.py`)
- What it scans: dark connected spots in the cortical band (within 2 mm of the pial surface) that ALBUS did not show. Any spot within
  2 voxels of a shown or excluded detector object is skipped. At most 200 spots per study, darkest × largest first.
- How it scores: each spot gets a patch from the same extractor, and the active model's LUMOS scores it.
- What the reviewer sees: up to 10 suggestions with P ≥ 0.5, best first.

**Activation gate** (`status()`; stored in every trained model as `model.second_look`). The second look turns on only when all of
these hold:
- LUMOS learned from ≥ 50 marks,
- those marks come from ≥ 10 patients,
- LUMOS recognises ≥ 70 % of the held-out patients' marks,
- the model has an image model.
It is also limited to the active model and can be switched off in Settings (`lumos_second_look`).

**Reviewer**
- Card "LUMOS second look" with dashed green "LUMOS? #n" circles on the image.
- ✓ cSS: saves a missed-cSS mark with context `lumos_suggestion`. It was AI-prompted, so the eligibility policy treats it as not blind
  primary ground truth.
- ✗ not cSS: writes `review/ID_lumos_rejects_by_<reviewer>.csv`. Expert rejects are LUMOS "not cSS" examples (y = 0) in the next
  training, never from test patients. This is how false suggestions drop with training.
- Refused during a blind initial read, both by the reviewer route table and by the app.

**Fixed on the way:** saved marks store the plane as a name since 01e95bc, but the viewer read a number. Rectangles and pen outlines
then showed only as a circle, and "go to" failed. Now `planeIdx()` reads both.

## Missed-cSS plan steps 1-4 (2026-11-26, user decision)
**1. ALBUS re-detects every mark** (`app/albus_redetect.py`, `scripts/albus_measure.py`)
- **ALBUS's object:**
  - the detector's own excluded or gate-dropped object under the mark (ALBUS found the lesion and removed it),
  - else the dark voxels inside the drawing (detector dark map first),
  - at least 5 voxels.
- **Measurement:** by the production detector. `albus_measure.py` checks `detect_css.py` against its pinned sha256; the file is NOT
  changed, so every pin stays valid. The forced objects replace the generated ones in memory. The rule that would exclude an object
  is recorded (`forced_would_exclude`) and not applied. Gates are soft.
- **Where it runs:** on a disposable copy of the study (APFS clones in `percival/albus_redetect/albus_<sid>_*`, removed afterwards).
  The project is never written by the detector. uScore x1 / x2 / x5 are measured on the same copy.
- **Result:** `percival/albus_redetect/<sid>.json` + `.npz`, keyed by the marks + detector + wrapper versions. It runs in the
  background, one study at a time, when the reviewer opens a study whose marks changed.
- **Confirmation in the reviewer:** each mark shows ALBUS's orange outline, its size and the rule or gate that lost it, with
  "✓ outline correct" / "✗ wrong". Answers are saved to `review/ID_missed_confirm_by_<reviewer>.csv` and refused during a blind read.
  An object counts as confirmed only when an expert said "correct" for THIS object (object_sha) and no expert said "wrong".
- **LUMOS:** uses the confirmed ALBUS object's patch instead of the drawn region.

**2. NOX learns from confirmed objects**, training patients only. The marks are used only when both hold:
- **Origin test:** a model cannot tell a re-detected mark from a detected cSS by its measurements (patient-grouped CV, origin
  AUC ≤ 0.75).
- **No harm:** NOX predicts the candidates no worse on the same folds. "Worse" means a paired increase in the per-candidate log loss
  larger than its patient-bootstrap standard error (`meta.no_harm`). LUMOS now uses the same paired rule. The strict "never worse"
  rule threw away helpful marks by chance; a 1-SE rule on the separate log losses let harmful marks through.

The fold models also score held-out patients' marks (`heldout_check`).

**3. PERCIVAL scores marks without ALBUS** (`meta.NoAlbus`)
- A regularised logistic regression on the NOX and LUMOS log-odds, fitted on the development CANDIDATES. ALBUS is never an input, so
  "no ALBUS score" cannot be learned as a sign of cSS.
- Reported separately, never mixed into the candidate metrics:
  - development recall of out-of-fold marks: `percival_marks.development`,
  - locked-test recall: `test.missed_lesions`.
- `score_study` adds `missed_marks` to every study score.

**4. Where ALBUS loses cSS** (`fate_report`, Model Center): every expert mark counted by category (exclusion rule, generation gate,
never generated) and cause. It is evidence for a new detector version, which must pass the ALBUS non-inferiority gate.

Viewer fixes on the way:
- The Save button never saved: `onclick=saveDraft` took the click event for the drawing.
- A pen stroke past the image edge made the server refuse the whole mark; points are now clipped to the image.
Browser-tested on the synthetic demo.
