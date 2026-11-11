# Accept v5.7-C on M02-M11, then redetect (research software; expert review required)

What changed: the detector now has E22 (midline sheets), E24 (skull-base cortex zone: orbitofrontal / frontal pole / temporal pole)
and E12 (objects over 3000 mm3), all under CSS_V53=1. Your M02-M06 lists were made without E22 and M07-M11 still carry the old
v5.2 detection, so objects of these rules are still shown there.

The acceptance test runs the NEW detector on a COPY of each study (project untouched) and checks that every object you called
cSS is still shown. It must report no cSS lost. Only then redetect.

## 1. Install
```
cd ~/Downloads && unzip -o cSS_v5.7-C_update.zip
cp -R cSS_v5.7-C_update/scripts/* ~/css_project/scripts/
cp -R cSS_v5.7-C_update/tests ~/css_project/ 2>/dev/null
cat ~/css_project/scripts/VERSION
```
The last line must print `v5.7-C`.

## 2. Acceptance test (no other heavy job running; about 3-5 minutes per study, one study at a time)
```
conda activate css
cd ~/css_project
python scripts/v53_compare.py M02,M03,M04,M05,M06,M07,M08,M09,M10,M11
open review/v53_compare_summary.txt
```
Send me `review/v53_compare_summary.txt`, `review/v53_compare.csv` and `review/v53_objects.csv`.
Look at the line "cSS calls still shown": it must be N / N. If any line starts with `LOST`, do NOT redetect; send me the files.

## 3. Redetect (only after the acceptance test is clean)
```
cd ~/css_project
python scripts/v53_change_report.py snapshot M07,M08,M09,M10,M11
python scripts/redetect.py M02,M03,M04,M05,M06,M07,M08,M09,M10,M11 --v53
python scripts/v53_change_report.py after M07,M08,M09,M10,M11
python scripts/inherit_calls.py M07,M08,M09,M10,M11 --reviewer "FirstRead"
head -n 1 review/M04_candidates.csv | tr ',' '\n' | grep -c "skullbase_frac"
```
The last line must print `1` (the new detector wrote its columns). Redetect keeps backups of the old lists and calls. M02-M06: calls are matched by fingerprint, so calls on objects that did not change stay
with Redo_v53 and Blind_v57 automatically. M07-M11: their first-read calls (the shared file) are written for the name "FirstRead" (dashed in the
reviewer until a reader presses the same key).

## 4. Check
```
python scripts/zone_probe.py M02,M03,M04,M05,M06,M07,M08,M09,M10,M11 --reads Redo_v53,Blind_v57
open review/zone_probe_summary.txt
```
Send `zone_probe_summary.txt` again: the shown non-cSS objects of the zone rules should now be gone.
