# NOX measurement set (built-in, registry v000; 2026-11-25)

Architecture (user decision, 2026-11-25): **MRI -> ALBUS (detects) -> NOX (measures) + LUMOS (sees the image) -> PERCIVAL (the only
combiner)**. The former "Unified" component (uScore x1-x5 as its own model) and the "Fusion" layer (NOX + LUMOS combined below PERCIVAL)
were removed. Code: `unified_engine/uengine/percival/meta.py` (`NOX_V000`, `NOX_ADDED`, `PREDICTORS`, `CHAR`).

## How the set was chosen
From the 159 columns the detector writes for every candidate (`review/<study>_candidates.csv`) and the uScore extractor
(`unified_score/uscore/features.py`). They were checked on the user's 51 real studies (772 candidates). A measurement is in the set when it:
- exists for (almost) every candidate (coverage 100 %; tram_frac 70 %; missing values are imputed with the training median and counted),
- is a continuous measurement, not a rule decision (E-rule flags, tiers), not a composite score (score_v4, css_evidence and vein_evidence
  belong to ALBUS), not a deprecated column (vein_tree_mm, mirror_dark_frac, branch_per10mm) and not label-like,
- describes something the 9 original measurements did not cover, or covers it from a different angle.
NOX models are regularised (L2 logistic with a nested penalty, or shallow trees / forest, chosen by patient-grouped CV with the 1-SE rule),
so extra measurements that carry no signal are shrunk instead of adding noise. The feature importance and each measurement's own AUC are
recorded in every model (`intelligence.families.char`), so the set can be pruned or extended later. A new set becomes active only as an
approved NOX registry version (`component_registry.py`, named person + typed phrase + reason; rollback possible).

## The 30 measurements
| Group | Measurement | What it measures | Why it helps (cSS vs mimics) |
|---|---|---|---|
| original 9 | darkness_z | candidate darkness vs local cortex (MAD units) | cSS is dark; veins are often darker |
| | edge_contrast | contrast at the object's edge | sharp hemosiderin rim vs blurry artifact |
| | pial_dist_mm | median signed distance to the pial surface | cSS lies on the surface |
| | cortex_frac | share of voxels in the cortex | cSS follows the cortex |
| | tram_frac | share with the two-bank "tram-track" pattern | typical cSS sign |
| | tube_ratio | 3-D Hessian tube vs sheet | veins are tubes, cSS sheets |
| | elongation_3d | 3-D elongation | long thin structures |
| | log_volume_mm3 | size (log) | |
| | local_cont_max_mm | longest continuation through dark / vessel voxels | veins continue, cSS stops |
| surface | bank_frac | share on one sulcal bank | cSS coats a bank |
| | dual_contact_frac | contact with both banks | tram-track from the other side |
| | surface_contact_frac_1mm | share within 1 mm of the CSF surface | surface coating |
| | csf_adjacent_frac | share next to CSF | subarachnoid position |
| | sulcal_depth_mm | depth inside the sulcus | cSS sits in sulci; convexity veins on top |
| shape | flatness_3d | 3-D flatness | sheet-like cSS |
| | sphericity | how round | microbleeds / blobs are round |
| | tortuosity | path length / straight distance | winding veins |
| | struct_thick_mm | thickness of the whole dark structure | |
| | cand_radius_med_mm | median in-plane half-width | thin line vs wider band |
| darkness pattern | dark_frac_z3 | share darker than 3 SD | |
| | darkness_z_p10 | darkest 10 % | core darkness |
| | region_z | darkness vs its own cortical region | naturally dark cortex (motor strip) |
| | dark_cv | variation of darkness along the object | uniform vein vs patchy deposit |
| vessel | vessel_wm_mm | continuation into the deep white matter | transcortical veins |
| | local_branch_points | branching near the object | vein trees branch |
| position | rel_height | height in the cerebrum | skull-base artifacts low |
| | skull_frac | share next to the skull | air / bone susceptibility |
| uScore | x1_vessel_continuity_mm | vessel pieces traversing the candidate (sum of the two longest reaches) | a vessel passing through |
| | x2_core_contrast_nu | contrast of the decomposed dark core (noise units) | real deposit vs faint shading |
| | x5_extracranial_mm | dark region continuing outside the brain | extracranial / skull artifacts |

Left out on purpose: uScore x3 (pial distance) and x4 (surface conformity) duplicate ALBUS's `pdist` / `aln`; phase and FLAIR columns
(present in 8 % / 33 % of the candidates: a missing-input imbalance across scanners); coordinates (vox_i/j/k); call / review columns.

## Where the values come from
- detector columns: read from `review/<study>_candidates.csv` when the study is gathered for learning,
- x1 / x2 / x5: `uscore/features/<study>.json`, extracted without the 16 perturbation runs (values only) the first time a study is gathered,
- studies moved to Pensieve are brought back (verified) before their images are read; the gathered values and image patches are cached
  in `percival/cache/`, so a later move does not lose them.
