#!/bin/bash
# v5.8 new false-positive rules E26 (outside cortex + sulci / fissure) and E27 (Sylvian fissure). Research software; expert review required.
# usage: conda activate css ; caffeinate -i bash ~/css_project/tools/run_v58.sh        (about 40 min, one study at a time)
# 1. acceptance test on COPIES with CSS_ZONE2=1 (project untouched). 2. ONLY if every cSS call is still shown: snapshot + redetect M02-M11 with the
# new rules (backup made automatically). If a cSS is lost it STOPS before the redetect and bundles the files for Claude.
BASE=${CSS_BASE:-$HOME/css_project}; cd "$BASE" || exit 1; S=$BASE/scripts; R=$BASE/review
STUDIES=${STUDIES:-M02,M03,M04,M05,M06,M07,M08,M09,M10,M11}; export CSS_ZONE2=1
echo "version: $(cat $S/VERSION)"
for f in v53_compare.csv v53_compare_summary.txt v53_objects.csv; do [ -f "$R/$f" ] && cp "$R/$f" "$R/before_v58_$f"; done
python "$S/v53_compare.py" "$STUDIES" > "$R/v58_acceptance.log" 2>&1
cp "$R/v53_compare_summary.txt" "$R/v58_summary.txt"; cp "$R/v53_compare.csv" "$R/v58_compare.csv"; cp "$R/v53_objects.csv" "$R/v58_objects.csv"
cd "$R" && rm -f results_v58.zip && zip -q results_v58.zip v58_acceptance.log v58_summary.txt v58_compare.csv v58_objects.csv
L=$(grep "cSS calls still shown:" v58_summary.txt); echo "$L"; grep -A12 "Excluded by rule" v58_summary.txt
read A N <<< "$(echo "$L" | sed -E 's/.*: *([0-9]+) *\/ *([0-9]+).*/\1 \2/')"
if [ -z "$A" ] || [ "$A" != "$N" ]; then echo "STOP: a cSS call would be lost - NOT redetecting. Send $R/results_v58.zip"; exit 1; fi
cd "$BASE"
python "$S/v53_change_report.py" snapshot "$STUDIES" > "$R/v58_snapshot.log" 2>&1
python "$S/redetect.py" "$STUDIES" --v53 2>&1 | tee "$R/v58_redetect.log" | grep -E "raw components|done:|NOT done|backup"
python "$S/v53_change_report.py" after "$STUDIES" > "$R/v58_change_report.log" 2>&1
cd "$R" && zip -q results_v58.zip v58_snapshot.log v58_redetect.log v58_change_report.log changes/change_report.txt changes/change_report.csv
for s in ${STUDIES//,/ }; do echo "$s $(($(wc -l < ${s}_candidates.csv) - 1)) candidates"; done
echo "DONE. Send $R/results_v58.zip   - then read with the reviewer (see the commands from Claude)"
