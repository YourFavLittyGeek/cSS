# ARCHITECTURE_DESIGN.md - Stage 2: candidate-level SWI image learning for Percival

Status: DESIGN ONLY, awaiting approval. Nothing here is implemented. Research software; not for clinical use.
Basis: code inspection of branch `feature/unified-score-ml-integration` @ `9d0e3dc` (no clinical file opened).

## 1. What already exists (reuse, do not rebuild)

| need | existing component | state |
|---|---|---|
| candidate identity | `review/ID_candidates.{csv,nii.gz}`, `ID_excluded.{csv,nii.gz}` (label map: value = object id, saved with the SWI affine); `css_common.cand_uid` = `study:vox_i:vox_j:vox_k:volume_mm3` | stable across re-runs; used by all label tables |
| candidate-centred patches | `scripts/surface_aligned_patch.py` (v5.2, schema `css-patch/1.0`): fixed PHYSICAL size (default 24 x 12 x 8 mm, 0.5 mm grid) in a right-handed surface frame (u = long axis in the tangent plane, v = across, n = outward pial normal), channels swi / phase / flair / labels, per-channel validity masks, stale-channel refusal, oblique affines handled | tested (`tests/check_v52.py`); never run on clinical data in this work |
| hand-crafted patch features + classifier | `scripts/classify_surface_patches.py` (features, LOPO, nested L2, schema + hash checks, test split refused) | cSS vs vein only |
| measured characteristics | 157 detector columns; Stage 1 `uengine.characteristics_component` (10 prespecified inputs, status per value) | Stage 1, tested |
| MATH | `uengine.math_component` executes `detect_css.py` / `css_tiers.py` code verbatim (pinned sha256) | Stage 1, tested |
| fusion + registry + shadow screen | `uengine.prototype.fusion` (offset fusion), `uengine.registry`, `uengine.shadow`, `app/shadow_view.js` | Stage 1, tested |
| expert labels | `css_common.LABELS` (19 fine codes, confidence 1-5), `expert_sheet.py` / `expert_import.py` -> `labels/candidate_labels.csv` (`css-labels/1.0`), `consensus.py`, `review_web.py` calls + `ID_missed.csv` | schema exists; candidate-level expert labels are the blocker (section 6) |
| synthetic images | `tests/phantom_v4.py` (0.8 x 0.8 x 1.2 mm phantom with truth cSS: tram-track, convexity, single bank; mimics: sulcal, surface, transcortical veins), `phantom_surfvein.py`, `morph_phantoms.py` (partial volume) | usable for Stage 2 synthetic work. NOT `scripts/make_synthetic.py`: it inserts lesions into a REAL host image |
| QC / geometry | `css_qc.py` (orientation, coverage, anatomy source, edge agreement), detector stop if array axis 2 is not S-I | reported only |

## 2. Target architecture (four evidence streams, one fusion layer)

```
 SWI (+phase, FLAIR, labels) --> geometry gate --> patch extractor (css-patch/2.0) --+--> [I] IMAGE stream
                                                                                  |
 detector tables (candidates / excluded.csv) -------------------------------------+--> [C] CHARACTERISTICS stream
                                                                                  |
 detect_css.py / css_tiers.py verbatim -------------------------------------------+--> [M] MATH stream
                                                                                  |
                                       FUSION  (offset on M, cross-fitted increments from C and I,
                                                redundancy control, calibration, uncertainty, missingness)
                                                                                  |
                     shadow result  unified_engine/shadow/ID.json  (schema 2) --> Shadow ML screen (read-only)
```

- **[M] MATH**: unchanged Stage 1 component; the anchor (offset) of the fusion. Never retrained.
- **[C] CHARACTERISTICS**: unchanged Stage 1 component; L2 logistic increment fitted with the MATH offset.
- **[I] IMAGE**: new. Input = one candidate-centred patch tensor + validity masks + geometry record. Output = an image
  logit increment, an availability flag and a per-candidate uncertainty. Two interchangeable implementations behind
  one interface (section 4): I-a radiomics-style patch features + penalised logistic; I-b small 2.5D CNN.
- **FUSION**: logit p = a + b*MATH_logit + g_C*C_incr + g_I*I_incr, fitted in two cross-fitted stages
  (UNIFIED_SCORE_DESIGN Stage 1 extended; MODEL_EVALUATION_PLAN section 5). Missing streams contribute 0 with an
  availability indicator; categories become "uncertain" when the image stream is unavailable AND it is the only
  stream that disagrees with MATH.

Component interface (all three learned/derived streams):
`fit(train_rows, patient_ids) -> artefact`, `predict(rows) -> {increment, available, status, uncertainty, trace}`,
`card() -> model card`, every artefact hash-protected and registered (`uengine.registry`, `data_kind` enforced).

## 3. Options evaluated for the IMAGE stream

Realistic data: the repository manifest lists 36 studies (26 development, 10 held-out); detector output on real SWI
was 70-100 candidates per study, with few cSS per positive study. Plausible labelled set after an expert read:
2 500-3 500 candidates, of which perhaps 100-400 cSS, from ~25-36 patients. Patients, not candidates, are the
effective sample size. Acquisition varies (SWI vs T2*-GRE, vendor, field, TE, 0.5-2 mm slices; recorded by
`score_css.py`).

| option | parameters | needs | strengths | weaknesses at n ~ 30 patients | verdict |
|---|---|---|---|---|---|
| **A. Image-derived features + conventional ML** (I-a) | 50-150 features, ~10-30 effective after penalty | existing extractor; numpy / scipy only | interpretable, stable, works with 100s of positives, patient-grouped CV cheap, geometry-explicit (profiles along n, extent along v) | ceiling limited by feature design | **recommended first** |
| **B. 2D multi-slice / 2.5D CNN** on surface-aligned slabs (I-b) | 20k-200k (tiny) | PyTorch (not installed), augmentation, ensembling | learns texture/shape beyond hand-crafted features; 2.5D keeps in-plane resolution of anisotropic SWI | overfits patients and scanners; unstable across seeds; planning assumption (not a measured threshold): >=500 positives from >=50 patients before it can be expected to beat A reliably | **second, only if A plateaus AND data grows; gated** |
| **C. 3D CNN** on isotropic crops | 100k-5M | GPU-class compute, PyTorch / MONAI | full context | slice thickness 1.2-2 mm makes 3D resampling invent through-plane detail; far too little data; poor calibration | **not recommended** at this data size |
| **D. Hybrid image + tabular network** (joint) | B + tabular head | as B | single model | hides double counting with MATH / C; joint fit was the losing design in Stage 1 synthetic experiments | **not recommended**; do hybrid at the FUSION layer instead (late fusion with offsets) |
| E. Pretrained foundation encoder (frozen) + linear head | head only | external weights (licence, provenance), torch | few labels needed | domain gap (natural / CT images); weights must be audited; patches are tiny | optional research arm under B's gate |
| F. Self-supervised pretraining on unlabelled candidates | as B | CLINICAL images without labels | uses all candidates | is still processing / training on clinical images: needs explicit approval | out of scope until approved |

**Recommendation.** Build the stream interface once; implement **A (I-a) first** on the existing surface-aligned
patches, extended with a native-slice 2.5D context (IMAGE_PIPELINE_DESIGN section 4), fused LATE as an offset
increment. Keep **B** as a gated second implementation of the same interface: it is only trained when (i) A has been
evaluated on held-out patients, (ii) >= 50 labelled patients / >= 500 expert cSS candidates exist or the permutation
test shows A leaves signal on the table, and (iii) the PyTorch dependency is approved. 3D CNN and joint hybrids are
rejected for this data size.

## 4. Separation and safety (same rules as Stage 1)

- No write path into candidates, exclusions, calls, scores or the 0-4 score. Shadow results only, schema 2.
- A model whose card / training record says `synthetic` is never applied to a real study (Stage 1 policy, unchanged).
- Patient-level separation everywhere (folds, calibration, bootstrap, early stopping, augmentation statistics).
- Every prediction records: model hash, image sha256, patch schema, geometry hash, registration chain, detector
  version, engine version, availability of each channel (DATA_SCHEMA section 5).

## 5. Integration into the Shadow ML screen

Adds a fourth, always-separate output group "Experimental IMAGE model" (increment, availability, channel validity,
uncertainty) between "Experimental ML" and "Experimental Unified"; a patch thumbnail (u-v plane at n = 0 and the
n-profile) generated from the synthetic patch only; trace adds the image block. Existing outputs and screens are
unchanged; the fourth block is absent (not zero) when no image model is registered.

## 6. Blockers before ANY clinical training (owner: user / study team)

1. **Candidate-level expert labels** with the new label schema (DATA_SCHEMA section 3): current labels are non-expert
   and patient-level for radiologists; a blinded expert read of shown AND excluded objects is required.
2. **Patient keys**: exam -> patient mapping (repeat exams must stay on one side of every split).
3. **Frozen detector version** for the training cohort (candidates change between detector versions; cand_uid only
   carries over through `inherit_calls.py`).
4. **Governance approval** to process clinical images for training (IRB / data-use), and a written decision that
   nothing leaves the Mac.
5. **Dependency decision**: PyTorch (CNN arm) is not installed; numpy / scipy suffice for option A.
6. **Acquisition inventory** (vendor, field, TE, voxel size, SWI vs GRE) as counts only, to fix the stratification
   and the held-out design.
7. **Held-out set definition** frozen before any image model is fitted (existing 10 held-out studies, or new).
