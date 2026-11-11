# v5.7-D: acceptance of the new exclusion rules + shape probe (research software; expert review required)

New in the detector (all under CSS_V53=1): E22 midline sheet, E24 skull-base cortex zone, E25 interhemispheric fissure (left AND right cortex
both within 3 mm), E12 over 3000 mm3. New read-only tools: zone_probe.py (updated), shape_probe.py (blob / straight-in-sulcus measures).
Your five final decisions are in `docs/adjudication_M02-M11_v1.csv` (M03 excluded #5 and #28, M04 excluded #18, M04 #13: not cSS; M05 #3: cSS).

Run each block in Terminal (zsh), one at a time, with no other heavy job running.

## 1. Install
```
cd ~/Downloads && unzip -o cSS_v5.7-D_update.zip
cp -R cSS_v5.7-D_update/scripts/* ~/css_project/scripts/
cp -R cSS_v5.7-D_update/tests ~/css_project/ 2>/dev/null
cp cSS_v5.7-D_update/docs/adjudication_M02-M11_v1.csv ~/css_project/review/adjudication.csv
cat ~/css_project/scripts/VERSION
```
The last line must print `v5.7-D`.

## 2. Acceptance test of the new rules (project untouched; 3-5 minutes per study, one after the other)
It runs the NEW detector on copies and checks that every object you called cSS is still shown.
```
conda activate css
cd ~/css_project
python scripts/v53_compare.py M02,M03,M04,M05,M06,M07,M08,M09,M10,M11
open review/v53_compare_summary.txt
```
Send me `review/v53_compare_summary.txt`, `review/v53_compare.csv` and `review/v53_objects.csv`.
In the summary, "cSS calls still shown" must be N / N. Any line starting with `LOST` means a rule removed a cSS: do NOT redetect, send me the files.
(The calls v53_compare uses are the shared `ID_calls.csv`; M05 #3 and M04 #13 follow your decisions only in the probes, so one cSS line for M04 #13
may appear as "kept"/"lost" in the summary: tell me and I will read it against the adjudication.)

## 3. Shape probe (read-only; about 2 minutes per study)
```
python scripts/shape_probe.py M02,M03,M04,M05,M06,M07,M08,M09,M10,M11 --reads Redo_v53,Blind_v57
open review/shape_probe_summary.txt
```
Send `review/shape_probe.csv` and `review/shape_probe_summary.txt`. They show, next to your calls: how blob-like each object is (microbleeds),
how straight it runs in a sulcus and how far it tracks into the adjacent cortex, and the angle of its long axis to the axial plane.

## 4. Redetect (ONLY after step 2 is clean)
```
python scripts/v53_change_report.py snapshot M07,M08,M09,M10,M11
python scripts/redetect.py M02,M03,M04,M05,M06,M07,M08,M09,M10,M11 --v53
python scripts/v53_change_report.py after M07,M08,M09,M10,M11
python scripts/inherit_calls.py M07,M08,M09,M10,M11 --reviewer "FirstRead"
head -n 1 review/M04_candidates.csv | tr ',' '\n' | grep -c "dual_contact_frac"
```
The last line must print `1`.
