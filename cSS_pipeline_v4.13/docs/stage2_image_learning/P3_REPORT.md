# P3_REPORT.md - Stage 2 P3: parametric synthetic cohort (and the Image ML prototype built on it), 2026-11-20

Synthetic data only. The prototype that uses this cohort (model, inference, GUI screen) is described in IMAGE_ML_PROTOTYPE.md; it covers
roadmap items P5 (option A image stream) and part of P7 (GUI) in prototype form, built at the user's request of 2026-11-20.

## Generator (`unified_engine/uengine/imaging/synthetic_cohort.py`)
- **Acquisition profile per study**: vendor (phase sign +1 / -1), field 1.5 / 3 T, TE by field, in-plane 0.5-1.0 mm, slices 1.0-3.0 mm,
  SNR 6-40 with Rician magnitude noise, multiplicative bias field 0-30 %, motion ghost (5 % severe), tilt 0-15 deg, storage RAS / LAS / LPS,
  SWI or T2*-GRE, FLAIR present (85 %) and occasionally misregistered.
- **Objects (world-defined, partial volume on a 2x sub-voxel grid)**: cSS subpial sheets; mimics vein_surface, vein_sulcal,
  vein_transcortical, microbleed, calcification (diamagnetic: opposite phase), normal_iron_cortex (mild), artifact_airbone (inferior frontal,
  dipole phase). Blooming = geometric growth of susceptibility sources by 0.4 mm x (TE / 20 ms) x (B0 / 3 T).
- **Truth** per object under `unified_engine/image_truth/` (never in the detector-like tables); study-level insufficient quality when the
  ghost >= 0.35 or SNR < 8.
- **Simulated readers** R1 (expert) / R2 (trainee) writing css-labels/2.0-shaped rows: insufficient_quality in bad studies, indeterminate and
  errors rising with difficulty (contrast-to-noise, size, confusable kinds), errors drawn from a configured confusion table.
- **Negative control** `signal=0`: each object is rendered as a kind drawn independently of its label.

## Tests (`unified_engine/tests/test_synthetic_cohort.py`, 15, all pass)
Every kind darker than its surroundings; phase sign follows source and vendor (calcium opposite to haemosiderin); blooming grows with TE and
field; thick slices dilute thin sheets; noise level and bias field recovered; quality truth; files / tables / truth separation (no label word
in the detector tables); truth recovered through P1 + P2 for every patch; byte-reproducible cohorts; reader rows in the 2.0 schema; reader
error and indeterminate rates match the configured model within 4 binomial SE; only configured confusions; difficulty raises indeterminate;
insufficient-quality calls concentrated in bad studies; negative control independent of labels; P1 residual-shift thresholds re-checked.

## P1 threshold re-check
On four varied profiles (slices 1.0-2.5 mm, SNR 10-30, bias 0-30 %): a 0 mm FLAIR shift was never classified misregistered and a 3.5 mm
shift always was. The 1-2 mm band (low_confidence) was not re-tuned; thresholds stay provisional.

## Findings
1. The first blooming model (Gaussian blur added to the occupancy) made small objects SHRINK at long TE: blurring lowers a tiny object's
   peak. Caught by the blooming test; replaced by geometric growth on the sub-voxel grid.
2. A 0.25 mm blooming scale was invisible on 0.8 mm voxels; the effect size is a design choice, now 0.4 mm at TE 20 ms / 3 T.
3. On small signal-free cohorts the K-fold CV AUC of the image model ranged 0.26-0.82 across seeds (fold prevalence artefact). The decision
   value for the negative control is now an independent null cohort with a patient-bootstrap CI (0.505 [0.378-0.629] for the bundled model).
4. The GUI first reported MATH as "available" for image studies because the table carries a rule_version tag; MATH now requires score_v4.
