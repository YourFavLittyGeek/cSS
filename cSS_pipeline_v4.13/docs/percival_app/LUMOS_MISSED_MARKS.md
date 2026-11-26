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
