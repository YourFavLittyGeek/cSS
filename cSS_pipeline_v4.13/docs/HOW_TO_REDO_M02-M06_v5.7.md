# Redo M02-M06 with v5.7 Stage A (blind validation read) - research software; expert review required

What this run is: a third, BLIND read of M02-M06 on the current v5.3 detection, under a NEW reviewer name, with the
AI meter hidden, the candidates shuffled and numbered 1..N, and a 20 % sample of the EXCLUDED objects mixed in unmarked
(so we learn whether any rule removes real cSS). Microbleeds get their own key (B). Detection does not change in Stage A,
so no redetect is needed. Your Redo_v53 calls stay untouched and stay the primary (shared) read.

Run every block in Terminal (zsh), one block at a time. Nothing heavy runs here: the reviewer is a small local web server.

## 1. Install the update
```
cd ~/Downloads && unzip -o cSS_v5.7-A_update.zip
cp -R cSS_v5.7-A_update/scripts/* ~/css_project/scripts/
cp -R cSS_v5.7-A_update/tests ~/css_project/ 2>/dev/null; cp -R cSS_v5.7-A_update/docs ~/css_project/ 2>/dev/null
cat ~/css_project/scripts/VERSION
```
The last line must print `v5.7-A`.

## 2. Keep Redo_v53 as the primary reviewer of M02-M06
Only the primary reviewer writes the shared `ID_calls.csv` / `ID_score.json`. Fix it to Redo_v53 BEFORE the blind read,
otherwise the first reviewer who saves (the blind read) would become primary.
```
conda activate css
cd ~/css_project
python - <<'EOF'
import json, time
for s in ["M02", "M03", "M04", "M05", "M06"]:
    json.dump(dict(reviewer="Redo_v53", set=time.strftime("%Y-%m-%d %H:%M:%S")), open(f"review/{s}_primary.json", "w"), indent=1)
    print(s, "primary = Redo_v53")
EOF
```

## 3. Check the detection is the one you read (no change expected)
```
cd ~/css_project
for s in M02 M03 M04 M05 M06; do echo "$s: $(($(wc -l < review/${s}_candidates.csv) - 1)) candidates, $(($(wc -l < review/${s}_excluded.csv) - 1)) excluded"; done
```
Expected candidates: M02 9, M03 20, M04 33, M05 6, M06 21 (as in your Redo_v53 report).

## 4. The blind read
```
cd ~/css_project
python scripts/review_web.py M02,M03,M04,M05,M06 --reviewer "Blind_v57"
```
In the browser:
- The blue **VALIDATION READ** badge must be on. The AI meter is hidden and locked, and the candidates are numbered 1..N
  in a shuffled order. Do not switch the mode off during this read.
- Keys: **Y** cSS, **V** vein, **N** normal cortex, **A** artifact, **B** microbleed (round blob, not a line),
  **U** unsure, **H** near ICH. Magnifier moved to **W**. Use the 2x2 layout (`\`) for midline objects.
- Some objects are excluded objects mixed in. Read them exactly like the others.
- At the end of each study press **Q** (no comparison window in this mode): the final record is saved.
- Switch study with the drop-down at the top left. Stop the server with Ctrl+C in Terminal when all five are saved.

## 5. Reports
```
cd ~/css_project
python scripts/css_report.py
python scripts/compare_reads.py M02,M03,M04,M05,M06 --reviewer Blind_v57 --old-reviewer Redo_v53
open review/css_report.xlsx
open review/compare_reads_summary.txt
```
`css_report.xlsx` now has one row per study AND reviewer (Redo_v53 and Blind_v57), with "Microbleeds called",
"Read mode", "Excluded objects audited" and "Excluded objects called cSS (audit)".
`compare_reads_summary.txt` compares your Redo_v53 read with the blind read object by object (same detection).

## 6. Send back
- `~/css_project/review/css_report.csv`
- `~/css_project/review/compare_reads_summary.txt` and `compare_reads.csv`
- `~/css_project/review/M0?_excluded_audit_Blind_v57.csv` (one per study)

These tell us (a) how stable your cSS calls are with the meter hidden, (b) whether any excluded object is cSS, by rule,
and (c) how many microbleeds are in the lists - the labels Stage B needs for the blob rule.
