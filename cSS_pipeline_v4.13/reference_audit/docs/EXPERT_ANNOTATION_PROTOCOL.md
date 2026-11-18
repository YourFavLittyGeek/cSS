# Expert annotation protocol — cortical superficial siderosis (cSS) reference standard

Version 1.0 (2026-11-18). Research use. This protocol defines **what is annotated, how, and blind to what**. It does not change
the detector. Field definitions and allowed values: `EXPERT_ANNOTATION_TEMPLATE.csv` (lesion level), `reference_audit/annotation_schema.py`
(the same lists, machine-checked by `validate_annotations.py`).

## 1. Readers and blinding
- At least **two independent readers** for every examination (pathway A) and every sampled object (pathway B); a third, experienced
  neuroradiologist (or neurologist with MRI expertise) adjudicates disagreements only.
- Readers see **only images**: no candidate outlines (except the single object to judge in pathway B), no AI meter or score, no exclusion
  reason, no experimental-module output, no other reader's annotations, no radiology report, no radiologist grade.
- Readers who previously reviewed these patients' candidate lists (any earlier reader or reading session) carry memory and meter exposure.
  Prefer readers who did not; if they must read, record it (`reader_prior_exposure` in the reader log) so the analysis can stratify.
- Case order: independent random order per reader (`reading_order_<reader>.csv`). Pathway A is read **before** pathway B by each reader,
  with at least 2 weeks between them for the same patients.

## 2. Two pathways
**A. Whole-scan review (lesion discovery; the only way to find lesions production never generated).** Open the blinded case folder
(`cases/<CODE>/SWI.nii`, plus FLAIR / T1 / phase / GRE if present) in ITK-SNAP, freeview or the reading station. Read the full
supratentorial and infratentorial extent. Annotate every finding you would call definite or probable cSS, every finding you considered
and rejected as a mimic **if it could plausibly be mistaken for cSS** (these give the specificity side), and every indeterminate finding.
Complete one patient row (presence, multifocality per hemisphere).

**B. Excluded-object review (false-negative estimation per exclusion mechanism).** For each case image (`review/<case_id>.png`, outline =
the object; optional `<case_id>_mask.nii.gz` to open on the full SWI at the given voxel), judge **only the outlined object** and record one
row. Batches mix rule-excluded objects, generation-gate drops and a few shown objects (controls), shuffled - the reader cannot tell which
is which, and must not try to.

## 3. Definitions used for the categories
cSS = linear (gyriform) low signal on SWI / T2*-GRE following the cortical surface, within the superficial cortex and/or the overlying
subarachnoid space, caused by chronic blood products. It is reported per hemisphere as multifocality (0 none; 1 one sulcus or up to 3
adjacent sulci; 2 two or more non-adjacent sulci or more than 3 adjacent sulci).

| Category | Use when |
|---|---|
| **definite_cSS** | Unequivocal curvilinear hypointensity along the cortical surface, seen on >= 2 consecutive slices or in two planes, not explained by a vessel, artifact or other mimic; you would report it clinically |
| **probable_cSS** | Probably cSS but one feature is weak: very thin / short, one slice only, partly confounded by an adjacent vessel or artifact, image quality limits confidence |
| **non_cSS** | A dark finding that is something else - always give `noncss_type` |
| **indeterminate** | Cannot decide between cSS and a mimic even after using all planes / sequences - always give `uncertainty_reason` |

Do **not** force a decision. "Indeterminate" is a valid, analysable answer; consensus is never imposed on a reader.

## 4. Distinguishing cSS from mimics (apply before choosing the category)
| Mimic (`noncss_type`) | Features that favour the mimic | Features that favour cSS |
|---|---|---|
| cortical_vein | Tubular, round cross-section; can be followed across slices as a continuous tube that branches, joins a larger vein or a dural sinus; similar calibre along its course; often bilateral / symmetric | Band that **lines** the gyral surface (follows its curvature), varies in thickness, does not continue into a draining vein, often asymmetric |
| pial_vessel | Thin tube in the sulcal CSF between the banks, not in contact with the cortex along its whole length, crosses the sulcus | Band in contact with the cortical surface along its length; "tram-track" on both banks of one sulcus |
| sulcal_vessel | Lies in the middle of the sulcal CSF, round in cross-section | Lies on the bank, not in the sulcal centre |
| dural_structure | Falx, tentorium, dural sinus, midline / interhemispheric or tentorial location, continuous with dura on coronal / sagittal | Follows a gyrus; separate from the dura |
| skull_base_artifact | Orbitofrontal / temporal-pole / skull-base location next to air-bone interfaces (sinuses, mastoid), blooming shape not following a gyrus, changes with phase-encoding direction, often bright fringes | Gyral pattern away from air-bone interfaces |
| other_susceptibility_artifact | Motion, flow, edge or coil artifact; geometric, crosses tissue boundaries | Respects anatomy |
| microbleed | Round / ovoid dot (2-10 mm), blooming, isolated, often lobar | Linear / curvilinear |
| calcification | Phase opposite to veins (if phase available), dense dot or linear calcification on CT/T1 | Paramagnetic (vein-like phase) |
| normal_dark_cortex | Diffuse, symmetric darkening of an entire gyrus or region (e.g. iron-rich motor cortex), no sharp edge | Focal, sharply marginated band |
| cSAH_acute | FLAIR sulcal hyperintensity in the same sulcus with little or no SWI signal (acute blood); record separately - it is not chronic cSS | Chronic hypointense rim without FLAIR change |
| ICH_related | Hemosiderin directly continuous with a lobar haemorrhage; record and mark `ICH_related` (scoring rules for cSS near ICH are applied later, not by the reader) | - |

Use every plane; scroll through adjacent slices; use the minIP only to follow continuity, never to decide alone (minIP merges veins and cSS).

## 5. Fields per lesion (pathway A; one row per lesion, `lesion_annotations_<reader>.csv`)
1 patient identifier (the blinded case code) · 2 lesion identifier (1, 2, ... per patient; the same integer in your mask file if you draw
one) · 3 hemisphere (L / R / midline) · 4 lobe · 5 cortical region (gyrus name) · 6 sulcal location (sulcus name, "crown", "both banks")
· location: voxel i/j/k of the lesion centre (preferred - shown in every viewer) and/or x/y/z mm (state the viewer: freeview = scanner RAS)
· 7 length (mm, longest extent along the surface) · 8 thickness (mm, across the band) · n_slices · 9 morphology · 10 continuity ·
11 SWI appearance · 12 GRE appearance (or not_available) · 13 FLAIR appearance (or not_available) · 14 associated vascular structure ·
15 confidence (1 very low - 5 certain) · 16 final category · non-cSS type · 17 reason for uncertainty (required for indeterminate and for
confidence <= 2) · comment · reading time.
A lesion = one continuous finding in one sulcus or on one gyral surface. A band that runs through two adjacent sulci is two lesions
(record both, same comment "continuous with lesion k"). Separate foci > 5 mm apart are separate lesions.

## 6. Fields per object (pathway B; `annotations_<reader>.csv` = a copy of the batch's `annotation_sheet.csv`)
final_category, noncss_type, confidence, morphology, continuity, associated vascular structure, whether real cSS extends beyond the
outline (yes / no / unsure), uncertainty reason, comment. Judge the outlined object; if it contains cSS **in any part**, the category is
cSS (definite / probable) and `lesion_extends_beyond_outline` says how it relates.

## 7. Patient row (pathway A; `patient_annotations_<reader>.csv`)
image quality (1-3), sequences available, cSS present L / R (yes / no / indeterminate), multifocality L and R (0-2), counts of definite /
probable / indeterminate lesions, reading time.

## 8. Quality rules
- Annotate in the reader's own copy of the template; never edit another reader's file or an earlier session; corrections are new rows
  with `read_session` + 1 and a comment.
- Run `python reference_audit/validate_annotations.py <file> lesion|object|patient` before returning files; it reports every missing or
  invalid value.
- 10 % of cases are re-read by each reader after >= 4 weeks (`read_session` 2) for intra-reader agreement.
- Adjudication: the adjudicator sees the images and the disagreeing readers' categories and comments (not their identities, not the
  detector) and records `adjudicated_category`; the original reads are kept unchanged (`adjudication.csv` is a separate file).
