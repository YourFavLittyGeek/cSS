# Run the zone probe on M02-M11 (read-only) - research software; expert review required

Purpose: measure, for every object the detector produced (shown AND excluded), where it lies in an anatomical compartment map
(outside the brain / free CSF / cerebellum-brainstem / skull base / interhemispheric fissure / cortical surface), next to your
calls. From this I fit the automatic exclusion rules so that **no cSS you called is ever removed**. The probe changes nothing.

cSS (any read) = an object you called cSS in ANY read (Redo_v53, Blind_v57, the first read, or an audit call). These are PROTECTED:
a rule is only accepted if it flags none of them.

## 1. Install (once)
```
cd ~/Downloads && unzip -o cSS_v5.7-B_update.zip
cp -R cSS_v5.7-B_update/scripts/* ~/css_project/scripts/
cp -R cSS_v5.7-B_update/tests ~/css_project/ 2>/dev/null
cat ~/css_project/scripts/VERSION
```
The last line must print `v5.7-B`.

## 2. Run the probe (no other heavy job running)
About 1-2 minutes per study and about 3 GB of memory; the studies are processed one after the other.
```
conda activate css
cd ~/css_project
python scripts/zone_probe.py M02,M03,M04,M05,M06,M07,M08,M09,M10,M11 --reads Redo_v53,Blind_v57
open review/zone_probe_summary.txt
```
Studies without Redo_v53 / Blind_v57 files (M07-M11) take their calls from the shared file of the first read.

## 3. Send back
- `~/css_project/review/zone_probe.csv`
- `~/css_project/review/zone_probe_summary.txt`

## 4. Before you send: look again at these objects (they decide whether a rule is safe)
Open the reviewer as Redo_v53 (`python scripts/review_web.py M03,M04 --reviewer "Redo_v53"`, validation read off in Settings if it asks)
and decide again, cSS or not cSS, for:
- M03 excluded #5 (midline rule), #28 (ill-defined rule)
- M04 excluded #18 (outside-the-cortex rule)
- M04 #13 (precuneus, medial surface) and M05 #3 (pericalcarine)
Use Candidate > Excluded audit objects after the final save to reach the first three. Your answer on these decides whether the fissure
and outside-cortex rules may be as strict as planned.
