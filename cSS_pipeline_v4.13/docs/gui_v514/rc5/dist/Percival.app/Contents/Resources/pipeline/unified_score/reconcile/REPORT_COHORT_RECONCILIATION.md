# Cohort reconciliation report (unified-score, cohort-audit stage)

Branch `experimental/unified-score` from `115721f`. Read-only on the container test bases. **No patient data exists in this container**: every container identifier is a phantom, a synthetic test case or an app-test fixture. Real M studies exist only on the user's Mac, so their final verification is `cohort_audit.py` on the Mac.

Reproduce: `python unified_score/reconcile/reconcile_cohort.py` (writes `reconcile/reconciliation.csv`, `cohort_manifest_RECONCILED.csv`).

## 1. The two identifier lists

**Container test data (55 identifiers)**, collected from every test base under /tmp that has `review/` outputs, plus app-test input folders (`data/<ID>/SWI|T1`):

M16 M17 M18 M19 M20 M21 M24 M25 M26 PH1 PH1S PH2 PH2S PH3 PH4 PH4S PH5 PH6 PH7A PH7B PH7C PH7D PHA PHB PHC PHD PHG PHI PHK PHL0 PHM PHM0 PHO15 PHO25 PHQ1 PHQ2 PHR PHS PHS0 PHS1 PHS2 PHS4 PHT PHU PHX PX Q00 Q01 S1 S2 S3 T1S VG1 VG2 VG3

**Provisional manifest (95 identifiers)** = the original 74 + 21 test-phantom variants added in revision 3:

M01 M02 M03 M04 M05 M06 M07 M08 M09 M10 M11 M12 M13 M14 M15 M16 M17 M18 M19 M20 M21 M22 M23 M24 M25 M26 P001 P002 P003 P004 P005 P005S P006 P007 P008 P009 P010 P010S P011 P012 P013 P014 P020 P201 P202 P203 P204 PH1 PH1S PH2 PH2S PH3 PH4 PH4S PH5 PH6 PH7A PH7B PH7C PH7D PHA PHC PHG PHI PHK PHL0 PHM PHM0 PHO15 PHO25 PHQ1 PHQ2 PHR PHS0 PHS1 PHS2 PHS4 PHT PHU PHX T01 T02 T03 T04 T05 T06 T07 T08 T09 T10 T11 T12 T13 T14 T15

## 2. Set relationships

| Set | n | Identifiers |
|---|---|---|
| container ∩ manifest | 42 | M16 M17 M18 M19 M20 M21 M24 M25 M26 PH1 PH1S PH2 PH2S PH3 PH4 PH4S PH5 PH6 PH7A PH7B PH7C PH7D PHA PHC PHG PHI PHK PHL0 PHM PHM0 PHO15 PHO25 PHQ1 PHQ2 PHR PHS0 PHS1 PHS2 PHS4 PHT PHU PHX |
| of which M-named random-noise app fixtures (name collision with real patients) | 9 | M16 M17 M18 M19 M20 M21 M24 M25 M26 |
| of which phantoms | 33 | PH1 PH1S PH2 PH2S PH3 PH4 PH4S PH5 PH6 PH7A PH7B PH7C PH7D PHA PHC PHG PHI PHK PHL0 PHM PHM0 PHO15 PHO25 PHQ1 PHQ2 PHR PHS0 PHS1 PHS2 PHS4 PHT PHU PHX |
| container only (missing from the manifest) | 13 | PHB PHD PHS PX Q00 Q01 S1 S2 S3 T1S VG1 VG2 VG3 |
| manifest only (no data in the container) | 53 | M01 M02 M03 M04 M05 M06 M07 M08 M09 M10 M11 M12 M13 M14 M15 M22 M23 P001 P002 P003 P004 P005 P005S P006 P007 P008 P009 P010 P010S P011 P012 P013 P014 P020 P201 P202 P203 P204 T01 T02 T03 T04 T05 T06 T07 T08 T09 T10 T11 T12 T13 T14 T15 |
| union = reconciled manifest | 108 | |

### What the earlier numbers (33 / 62 / 21) actually were

- **33** = the phantom identifiers present in both the container and the manifest (33 above). These are the 12 phantom IDs already in the original 74 (PH1, PH1S, PH2, PH2S, PH3, PH4, PH5, PH6, PH7A–D) + the 21 added variants. **All 21 added variants are container IDs**; they are a subset of the 33, not a third group.
- **62** = the manifest identifiers with no real data in the container: the 53 manifest-only IDs + the 9 M names whose container copies are noise fixtures. 33 + 62 = 95 holds **only if** those fixtures are treated as not-data, which the earlier text did not say.
- **What the earlier statement missed**: the container also holds **13 identifiers absent from the manifest** (PHB PHD PHS PX Q00 Q01 S1 S2 S3 T1S VG1 VG2 VG3). The manifest was therefore incomplete. They are now added as excluded (non-M), giving **108 identifiers**. The earlier count most likely came from the main test base only; the 13 come from the ranker / evaluate / vessel-gate / v5.2-check sub-bases.

## 3. Data-quality problem found: M-named fixtures in the container

The app tests (CSS_APP_FAKE_RUN) generated folders named M16 M17 M18 M19 M20 M21 M24 M25 M26: uniform random-noise NIfTI (values 0–1, mean 0.50; shapes 40×40×60 / 176×40×40 / 40×40×30) or review/QC files only. **They share names with real held-out patients.** They are not patients and are ignored. Guards added to `cohort_audit.py`: (1) it refuses to run on a base under /tmp or a scratchpad; (2) any M study whose SWI is a uniform-noise image is reported as a PROBLEM ('remove it from the base'). Tested on a temporary fake base (deleted afterwards).

## 4. Every inclusion / exclusion decision

| study_id | container | manifest | decision | role | reason |
|---|---|---|---|---|---|
| M02 | — | yes | include | development | M study, approved role |
| M03 | — | yes | include | development | M study, approved role |
| M04 | — | yes | include | development | M study, approved role |
| M05 | — | yes | include | development | M study, approved role |
| M06 | — | yes | include | development | M study, approved role |
| M07 | — | yes | include | development | M study, approved role |
| M08 | — | yes | include | development | M study, approved role |
| M09 | — | yes | include | development | M study, approved role |
| M10 | — | yes | include | development | M study, approved role |
| M11 | — | yes | include | development | M study, approved role |
| M01 | — | yes | include | held-out | M study, approved role |
| M12 | — | yes | include | held-out | M study, approved role |
| M13 | — | yes | include | held-out | M study, approved role |
| M14 | — | yes | include | held-out | M study, approved role |
| M15 | — | yes | include | held-out | M study, approved role |
| M16 | noise fixture (ignored) | yes | include | held-out | M study, approved role |
| M17 | noise fixture (ignored) | yes | include | held-out | M study, approved role |
| M18 | noise fixture (ignored) | yes | include | held-out | M study, approved role |
| M19 | noise fixture (ignored) | yes | include | held-out | M study, approved role |
| M20 | noise fixture (ignored) | yes | include | held-out | M study, approved role |
| M21 | noise fixture (ignored) | yes | include | held-out | M study, approved role |
| M22 | — | yes | include | held-out | M study, approved role |
| M23 | — | yes | include | held-out | M study, approved role |
| M24 | noise fixture (ignored) | yes | include | held-out | M study, approved role |
| M25 | noise fixture (ignored) | yes | include | held-out | M study, approved role |
| M26 | noise fixture (ignored) | yes | include | held-out | M study, approved role |
| T01 | — | yes | exclude | excluded | does not start with M; re-export of the same patient as M01 (duplicate identity) |
| T02 | — | yes | exclude | excluded | does not start with M; re-export of the same patient as M02 (duplicate identity) |
| T03 | — | yes | exclude | excluded | does not start with M; re-export of the same patient as M03 (duplicate identity) |
| T04 | — | yes | exclude | excluded | does not start with M; re-export of the same patient as M04 (duplicate identity) |
| T05 | — | yes | exclude | excluded | does not start with M; re-export of the same patient as M05 (duplicate identity) |
| T06 | — | yes | exclude | excluded | does not start with M; re-export of the same patient as M06 (duplicate identity) |
| T07 | — | yes | exclude | excluded | does not start with M; re-export of the same patient as M07 (duplicate identity) |
| T08 | — | yes | exclude | excluded | does not start with M; re-export of the same patient as M08 (duplicate identity) |
| T09 | — | yes | exclude | excluded | does not start with M; re-export of the same patient as M09 (duplicate identity) |
| T10 | — | yes | exclude | excluded | does not start with M; re-export of the same patient as M10 (duplicate identity) |
| T11 | — | yes | exclude | excluded | does not start with M; re-export of the same patient as M11 (duplicate identity) |
| T12 | — | yes | exclude | excluded | does not start with M; re-export of the same patient as M12 (duplicate identity) |
| T13 | — | yes | exclude | excluded | does not start with M; re-export of the same patient as M13 (duplicate identity) |
| T14 | — | yes | exclude | excluded | does not start with M; re-export of the same patient as M14 (duplicate identity) |
| T15 | — | yes | exclude | excluded | does not start with M; re-export of the same patient as M15 (duplicate identity) |
| P001 | — | yes | exclude | excluded | does not start with M (P study) |
| P002 | — | yes | exclude | excluded | does not start with M (P study) |
| P003 | — | yes | exclude | excluded | does not start with M (P study) |
| P004 | — | yes | exclude | excluded | does not start with M (P study) |
| P005 | — | yes | exclude | excluded | does not start with M (P study) |
| P007 | — | yes | exclude | excluded | does not start with M (P study) |
| P008 | — | yes | exclude | excluded | does not start with M (P study) |
| P009 | — | yes | exclude | excluded | does not start with M (P study) |
| P012 | — | yes | exclude | excluded | does not start with M (P study) |
| P013 | — | yes | exclude | excluded | does not start with M (P study) |
| P014 | — | yes | exclude | excluded | does not start with M (P study) |
| P020 | — | yes | exclude | excluded | does not start with M (P study) |
| P006 | — | yes | exclude | excluded | does not start with M (P study); explicitly excluded by the user |
| P010 | — | yes | exclude | excluded | does not start with M (P study) |
| P011 | — | yes | exclude | excluded | does not start with M (P study) |
| P201 | — | yes | exclude | excluded | does not start with M (LEMON healthy volunteer, P2xx) |
| P202 | — | yes | exclude | excluded | does not start with M (LEMON healthy volunteer, P2xx) |
| P203 | — | yes | exclude | excluded | does not start with M (LEMON healthy volunteer, P2xx) |
| P204 | — | yes | exclude | excluded | does not start with M (LEMON healthy volunteer, P2xx) |
| P005S | — | yes | exclude | excluded | does not start with M (phantom / synthetic) |
| P010S | — | yes | exclude | excluded | does not start with M (phantom / synthetic) |
| PH1 | phantom | yes | exclude | excluded | does not start with M (phantom / synthetic) |
| PH1S | phantom | yes | exclude | excluded | does not start with M (phantom / synthetic) |
| PH2 | phantom | yes | exclude | excluded | does not start with M (phantom / synthetic) |
| PH2S | phantom | yes | exclude | excluded | does not start with M (phantom / synthetic) |
| PH3 | phantom | yes | exclude | excluded | does not start with M (phantom / synthetic) |
| PH4 | phantom | yes | exclude | excluded | does not start with M (phantom / synthetic) |
| PH5 | phantom | yes | exclude | excluded | does not start with M (phantom / synthetic) |
| PH6 | phantom | yes | exclude | excluded | does not start with M (phantom / synthetic) |
| PH7A | phantom | yes | exclude | excluded | does not start with M (phantom / synthetic) |
| PH7B | phantom | yes | exclude | excluded | does not start with M (phantom / synthetic) |
| PH7C | phantom | yes | exclude | excluded | does not start with M (phantom / synthetic) |
| PH7D | phantom | yes | exclude | excluded | does not start with M (phantom / synthetic) |
| PH4S | phantom | yes | exclude | excluded | does not start with M (test phantom variant created by tests/run_tests.sh) |
| PHA | phantom | yes | exclude | excluded | does not start with M (test phantom variant created by tests/run_tests.sh) |
| PHC | phantom | yes | exclude | excluded | does not start with M (test phantom variant created by tests/run_tests.sh) |
| PHG | phantom | yes | exclude | excluded | does not start with M (test phantom variant created by tests/run_tests.sh) |
| PHI | phantom | yes | exclude | excluded | does not start with M (test phantom variant created by tests/run_tests.sh) |
| PHK | phantom | yes | exclude | excluded | does not start with M (test phantom variant created by tests/run_tests.sh) |
| PHL0 | phantom | yes | exclude | excluded | does not start with M (test phantom variant created by tests/run_tests.sh) |
| PHM | phantom | yes | exclude | excluded | does not start with M (test phantom variant created by tests/run_tests.sh) |
| PHM0 | phantom | yes | exclude | excluded | does not start with M (test phantom variant created by tests/run_tests.sh) |
| PHO15 | phantom | yes | exclude | excluded | does not start with M (test phantom variant created by tests/run_tests.sh) |
| PHO25 | phantom | yes | exclude | excluded | does not start with M (test phantom variant created by tests/run_tests.sh) |
| PHQ1 | phantom | yes | exclude | excluded | does not start with M (test phantom variant created by tests/run_tests.sh) |
| PHQ2 | phantom | yes | exclude | excluded | does not start with M (test phantom variant created by tests/run_tests.sh) |
| PHR | phantom | yes | exclude | excluded | does not start with M (test phantom variant created by tests/run_tests.sh) |
| PHS0 | phantom | yes | exclude | excluded | does not start with M (test phantom variant created by tests/run_tests.sh) |
| PHS1 | phantom | yes | exclude | excluded | does not start with M (test phantom variant created by tests/run_tests.sh) |
| PHS2 | phantom | yes | exclude | excluded | does not start with M (test phantom variant created by tests/run_tests.sh) |
| PHS4 | phantom | yes | exclude | excluded | does not start with M (test phantom variant created by tests/run_tests.sh) |
| PHT | phantom | yes | exclude | excluded | does not start with M (test phantom variant created by tests/run_tests.sh) |
| PHU | phantom | yes | exclude | excluded | does not start with M (test phantom variant created by tests/run_tests.sh) |
| PHX | phantom | yes | exclude | excluded | does not start with M (test phantom variant created by tests/run_tests.sh) |
| PHB | phantom | added | exclude | excluded | does not start with M (phantom; container test data, found in reconciliation) |
| PHD | phantom | added | exclude | excluded | does not start with M (phantom; container test data, found in reconciliation) |
| PHS | phantom | added | exclude | excluded | does not start with M (phantom; container test data, found in reconciliation) |
| PX | phantom | added | exclude | excluded | does not start with M (phantom; container test data, found in reconciliation) |
| Q00 | synthetic ranker-test case | added | exclude | excluded | does not start with M (synthetic ranker-test case; container test data, found in reconciliation) |
| Q01 | synthetic ranker-test case | added | exclude | excluded | does not start with M (synthetic ranker-test case; container test data, found in reconciliation) |
| S1 | synthetic evaluate-test case | added | exclude | excluded | does not start with M (synthetic evaluate-test case; container test data, found in reconciliation) |
| S2 | synthetic evaluate-test case | added | exclude | excluded | does not start with M (synthetic evaluate-test case; container test data, found in reconciliation) |
| S3 | synthetic evaluate-test case | added | exclude | excluded | does not start with M (synthetic evaluate-test case; container test data, found in reconciliation) |
| T1S | synthetic v5.2 T1-mask test case | added | exclude | excluded | does not start with M (synthetic v5.2 T1-mask test case; container test data, found in reconciliation) |
| VG1 | synthetic vessel-gate test case | added | exclude | excluded | does not start with M (synthetic vessel-gate test case; container test data, found in reconciliation) |
| VG2 | synthetic vessel-gate test case | added | exclude | excluded | does not start with M (synthetic vessel-gate test case; container test data, found in reconciliation) |
| VG3 | synthetic vessel-gate test case | added | exclude | excluded | does not start with M (synthetic vessel-gate test case; container test data, found in reconciliation) |

## 5. Final M-only included cohort (26)

- Development (10): M02 M03 M04 M05 M06 M07 M08 M09 M10 M11
- Held-out (16): M01 M12 M13 M14 M15 M16 M17 M18 M19 M20 M21 M22 M23 M24 M25 M26
- No P / PH / T / synthetic study is included. T01–T15 are excluded as duplicate identities of M01–M15. No held-out study was moved to development.

## 6. Scoreability by feature group (from project records; to be measured on the Mac)

Groups: A location / pial distance, B dark-core contrast, C vessel continuity, D morphology, E sulcal alignment, F Hessian, G extracranial continuation, H size, I context. 'expected ok (unverified)' = no recorded problem; `cohort_audit.py` writes the measured version (`cohort_scoreability.csv`) from each study's QC file.

| study | role | A | B | C | D | E | F | G | H | I | source |
|---|---|---|---|---|---|---|---|---|---|---|---|
| M02 | development | ok? | ok? | ok? | ok? | ok? | ok? | ok? | ok? | ok? | no record of a problem; to be measured by cohort_audit.py |
| M03 | development | ok? | ok? | ok? | ok? | ok? | ok? | ok? | ok? | ok? | no record of a problem; to be measured by cohort_audit.py |
| M04 | development | ok? | ok? | ok? | ok? | ok? | ok? | ok? | ok? | ok? | no record of a problem; to be measured by cohort_audit.py |
| M05 | development | ok? | ok? | ok? | limited (1.5 T, 3 mm slices) | ok? | limited (1.5 T, 3 mm slices) | ok? | limited (1.5 T, 3 mm slices) | ok? | v5.2.3 record: 1.5 T 3 mm SWI TE 40 |
| M06 | development | ok? | ok? | ok? | ok? | ok? | ok? | ok? | ok? | ok? | no record of a problem; to be measured by cohort_audit.py |
| M07 | development | ok? | ok? | ok? | ok? | ok? | ok? | ok? | ok? | ok? | no record of a problem; to be measured by cohort_audit.py |
| M08 | development | ok? | ok? | ok? | ok? | ok? | ok? | ok? | ok? | ok? | no record of a problem; to be measured by cohort_audit.py |
| M09 | development | ok? | ok? | ok? | ok? | ok? | ok? | ok? | ok? | ok? | no record of a problem; to be measured by cohort_audit.py |
| M10 | development | ok? | ok? | ok? | ok? | ok? | ok? | ok? | ok? | ok? | no record of a problem; to be measured by cohort_audit.py |
| M11 | development | ok? | ok? | ok? | limited (1.5 T, 3 mm slices) | ok? | limited (1.5 T, 3 mm slices) | ok? | limited (1.5 T, 3 mm slices) | ok? | v5.2.3 record: 1.5 T 3 mm SWI TE 40 |
| M01 | held-out | ok? | ok? | ok? | limited (1.5 T, 3 mm slices) | ok? | limited (1.5 T, 3 mm slices) | ok? | limited (1.5 T, 3 mm slices) | ok? | v5.2.3 record: 1.5 T 3 mm SWI TE 40 |
| M12 | held-out | ok? | ok? | ok? | limited (1.5 T, 3 mm slices) | ok? | limited (1.5 T, 3 mm slices) | ok? | limited (1.5 T, 3 mm slices) | ok? | v5.2.3 record: 1.5 T 3 mm SWI TE 40 |
| M13 | held-out | ok? | ok? | ok? | limited (1.5 T, 3 mm slices) | ok? | limited (1.5 T, 3 mm slices) | ok? | limited (1.5 T, 3 mm slices) | ok? | v5.2.3 record: 1.5 T 3 mm SWI TE 40 |
| M14 | held-out | ok? | ok? | ok? | ok? | ok? | ok? | ok? | ok? | ok? | no record of a problem; to be measured by cohort_audit.py |
| M15 | held-out | ok? | ok? | ok? | ok? | ok? | ok? | ok? | ok? | ok? | no record of a problem; to be measured by cohort_audit.py |
| M16 | held-out | ok? | ok? | ok? | ok? | ok? | ok? | ok? | ok? | ok? | no record of a problem; to be measured by cohort_audit.py |
| M17 | held-out | ok? | ok? | ok? | ok? | ok? | ok? | ok? | ok? | ok? | no record of a problem; to be measured by cohort_audit.py |
| M18 | held-out | unreliable (label shift 4.25 mm) | ok? | unreliable (vessel map restricted by the shifted labels) | ok? | unreliable (label shift 4.25 mm) | ok? | unreliable (brain-mask boundary from the shifted labels) | ok? | ok? | T1/SWI misalignment 4.25 mm (project record); shift vector not in this container; re-registration pending |
| M19 | held-out | ok? | ok? | ok? | ok? | ok? | ok? | ok? | ok? | ok? | no record of a problem; to be measured by cohort_audit.py |
| M20 | held-out | ok? | ok? | ok? | ok? | ok? | ok? | ok? | ok? | ok? | no record of a problem; to be measured by cohort_audit.py |
| M21 | held-out | ok? | ok? | ok? | ok? | ok? | ok? | ok? | ok? | ok? | no record of a problem; to be measured by cohort_audit.py |
| M22 | held-out | ok? | ok? | ok? | ok? | ok? | ok? | ok? | ok? | ok? | no record of a problem; to be measured by cohort_audit.py |
| M23 | held-out | unreliable (label shift 3.16 mm) | ok? | unreliable (vessel map restricted by the shifted labels) | ok? | unreliable (label shift 3.16 mm) | ok? | unreliable (brain-mask boundary from the shifted labels) | ok? | ok? | T1/SWI misalignment 3.16 mm (project record); shift vector not in this container; re-registration pending |
| M24 | held-out | ok? | ok? | ok? | ok? | ok? | ok? | ok? | ok? | ok? | no record of a problem; to be measured by cohort_audit.py |
| M25 | held-out | coarse (SWI-only SynthSeg anatomy) | ok? | coarse (vessel map restricted by SWI-SynthSeg labels) | ok? | coarse (SWI-only anatomy; no recon-all / Destrieux) | ok? | coarse (SynthStrip mask, SWI-only route) | ok? | ok? | no T1 (project record) |
| M26 | held-out | ok? | ok? | ok? | ok? | ok? | ok? | ok? | ok? | ok? | no record of a problem; to be measured by cohort_audit.py |

`ok?` = expected ok, unverified.

## 7. M18 and M23: registration assessed per feature

Synthetic test (`reconcile/shift_sensitivity.py`; folded cortex, sulcal period 12 mm, depth 10 mm; not patient data). Rigid label shift d, error at cortical points:

| shift direction | d (mm) | pial-distance error median / p90 (mm) | sulcal-direction error median / p90 (deg) |
|---|---|---|---|
| S-I (across surface) | 1.00 | 0.44 / 0.79 | 8.0 / 31.8 |
| S-I (across surface) | 3.16 | 1.31 / 2.70 | 12.7 / 30.5 |
| S-I (across surface) | 4.25 | 1.92 / 3.78 | 17.9 / 34.1 |
| L-R (across sulci) | 1.00 | 0.87 / 1.21 | 14.3 / 50.7 |
| L-R (across sulci) | 3.16 | 2.33 / 3.27 | 37.4 / 88.4 |
| L-R (across sulci) | 4.25 | 2.42 / 4.13 | 48.0 / 84.0 |
| oblique | 3.16 | 1.38 / 2.53 | 20.3 / 64.3 |
| oblique | 4.25 | 1.71 / 3.42 | 30.8 / 69.8 |
| A-P (along sulcus) | any | 0.00 / 0.00 | 0.0 / 0.0 |

Conclusions (provisional):
- **Surface distance (x3)**: at 3.16 / 4.25 mm the median error (1.3–2.4 mm) is larger than the cSS-vs-vessel separation the feature relies on (about 1 mm on the phantoms). **Unreliable** for M18 and M23.
- **Sulcal alignment (x4) is also affected**, not only location: the median direction error is 13–48° and the p90 is 30–88°. A shift is harmless only along a sulcus, and sulcal directions vary across the brain, so no single shift vector spares the whole brain. **Unreliable** for M18 and M23. Even 1 mm gives p90 errors of 30–50°, so 0.5–1.0 mm is marked 'marginal' in the audit.
- **Vessel continuity (x1)** and **extracranial continuation (x5)** also depend on the labels: the vessel map is restricted to the labelled cortical band and white matter, and the brain-mask boundary comes from T1 labels + 5 mm. They are marked unreliable for M18 and M23 as well. Only **B (core contrast, label-free local shell)**, D / F / H (image-only) and I remain scoreable.
- Consequence: M18 and M23 stay in the held-out manifest, recorded with these groups 'unreliable'. If re-registration succeeds (label shift ≤ 0.5 mm), they are re-audited. They are never dropped silently.
- The real shift vectors are in `review/M18_qc.json` / `M23_qc.json` on the Mac (`label_shift_vec_mm`); the audit reports them.

## 8. Corrections to earlier statements
- **M25**: the design said location / sulcal features are 'unavailable'. More exactly, the SWI-only route gives SynthSeg-on-SWI anatomy, so A / C / E / G are **coarse**, not absent; only Destrieux / recon-all features are unavailable.
- **95 → 108**: the 13 container-only identifiers were missing (section 2).

## 9. Unresolved
- **No measured scoreability yet** for any real M study: run `CSS_BASE=~/css_project python unified_score/cohort_audit.py` on the Mac.
- Field strength / slice thickness of M14–M26 are not in the project records; the Mac audit reads them.
- Whether M18 / M23 can be re-registered (bbregister) is unknown.
- Duplicate-scan check (SWI hash) across M01–M26 can only run on the Mac.
- The noise fixtures M16–M26 in the container's scratchpad should be deleted, or renamed (e.g. `FX16`) in the app tests. That is test code on another branch: not done here.
