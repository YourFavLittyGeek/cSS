# Phase 2 execution guide (Mac) — reference standard and production sensitivity

Nothing here changes the detector, its thresholds or your existing calls. All output goes to `~/css_project/reference_audit/`.
Do not redetect any study between step 2 and the end of the study (the inventory and every sampled object refer to the current lists);
if a redetect is unavoidable, start a new inventory and new batches.

## 0. Install (adds the folder `reference_audit/` and the protocol files; nothing else is replaced)
```zsh
cd ~/css_project && unzip -o ~/Downloads/cSS_phase2_reference_audit.zip -d ~/css_project && ls reference_audit reference_audit/docs
```

## 0b. Self-test on phantoms (no patient data; ~2 min; must end with ALL REFERENCE-AUDIT CHECKS PASSED)
```zsh
cd ~/css_project && conda activate css && bash reference_audit/tests/check_reference_audit.sh | tail -3
```

## 1. Inventory every production object (read-only, minutes)
```zsh
cd ~/css_project && conda activate css && python reference_audit/inventory.py M02 M03 M04 M05 M06 M07 M08 M09 M10 M11 M12 M13 M14 M15
```
Send me `~/css_project/reference_audit/inventory/*_objects_concealed.csv` if you want the gate-drop counts checked before sampling.

## 2. Draw the blinded excluded-object batch (pathway B)
```zsh
cd ~/css_project && conda activate css && python reference_audit/sample.py B01 --studies M02,M03,M04,M05,M06,M07,M08,M09,M10,M11,M12,M13,M14,M15 --plan reference_audit/EXCLUDED_OBJECT_SAMPLING.csv --include-shown 2 --seed 20261119 && python reference_audit/render_batch.py B01 --masks
```
About 320-350 objects (204 rule-excluded per the plan + up to 30 per generation gate + 2 shown controls per study), ~30 s each.

## 3. Prepare the whole-scan packet (pathway A); replace READER1,READER2 with the readers' codes (no names needed)
```zsh
cd ~/css_project && conda activate css && python reference_audit/ws_prepare.py W1 --studies M02,M03,M04,M05,M06,M07,M08,M09,M10,M11,M12,M13,M14,M15 --readers READER1,READER2 --seed 20261119
```

## 4. Hand out (what each reader gets - and nothing else)
- Pathway A first: `reference_audit/whole_scan/W1/cases/` (all case folders), `reading_order_<reader>.csv`, `lesion_annotations_<reader>.csv`,
  `patient_annotations_<reader>.csv`, and `EXPERT_ANNOTATION_PROTOCOL.md`.
- Pathway B, >= 2 weeks later: `reference_audit/batches/B01/review/` (PNG, masks, `annotation_sheet.csv` -> the reader saves a copy as
  `annotations_<reader>.csv`).
- Never hand out `key_CONCEALED.csv`, `*_concealed.csv`, `sampling_frame.csv`, `review/`, `work/`, or the cSS reviewer.
```zsh
cd ~/css_project/reference_audit && zip -qr ~/Desktop/W1_for_READER1.zip whole_scan/W1/cases whole_scan/W1/reading_order_READER1.csv whole_scan/W1/lesion_annotations_READER1.csv whole_scan/W1/patient_annotations_READER1.csv && echo "~/Desktop/W1_for_READER1.zip"
```
(repeat with READER2; for pathway B: `zip -qr ~/Desktop/B01_review.zip batches/B01/review`)

## 5. When the readers return their files (put them back in the same folders)
```zsh
cd ~/css_project && conda activate css && for f in reference_audit/whole_scan/W1/lesion_annotations_*.csv; do python reference_audit/validate_annotations.py "$f" lesion; done; for f in reference_audit/batches/B01/review/annotations_*.csv; do python reference_audit/validate_annotations.py "$f" object; done
```
Return any reported row to its reader for correction (they add a corrected row; nothing is edited by you).
```zsh
cd ~/css_project && conda activate css && python reference_audit/agreement.py whole_scan W1 && python reference_audit/agreement.py objects B01
```
Give the adjudicator `whole_scan/W1/adjudication_TEMPLATE.csv` and `batches/B01/review/adjudication_TEMPLATE.csv` (+ the images); the filled
copies are saved as `adjudication.csv` in the same folders.

## 6. Production performance against the reference
```zsh
cd ~/css_project && conda activate css && python reference_audit/evaluate.py R1 --packet W1 --batches B01 && cd reference_audit && zip -qr ~/Desktop/phase2_results.zip results/R1 whole_scan/W1/agreement_summary.csv whole_scan/W1/lesion_clusters.csv batches/B01/review/agreement_summary.csv batches/B01/sampling_frame.csv inventory/*_concealed.csv
```
Send `~/Desktop/phase2_results.zip`. I then write the sensitivity report (by failure type, mechanism, size, morphology, location,
confidence), with patient-cluster CIs.

## What only humans can do
| Task | Who | Effort (estimate) |
|---|---|---|
| Choose >= 2 readers (ideally not previously exposed to these lists / the meter) + 1 adjudicator | you / PI | - |
| Whole-scan reads, 14 examinations | each reader | ~15-25 min per examination |
| Excluded-object reads, ~350 objects | each reader | ~3-4 h |
| Adjudication of disagreements | adjudicator | depends on agreement |
| 10 % re-read after 4 weeks | each reader | ~1 h |
