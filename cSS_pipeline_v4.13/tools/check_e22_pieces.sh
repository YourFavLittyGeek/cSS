#!/bin/bash
# M11 #12 (you called it cSS) was lost to rule E22 because the second merge pass joined it with neighbours into a 29.5 mm "sheet".
# This re-runs the acceptance test on COPIES with CSS_E22_PIECES=1 (E22 judged on first-pass pieces, no new threshold). Main project untouched, no redetect.
# usage: conda activate css ; caffeinate -i bash ~/css_project/tools/check_e22_pieces.sh      (about 15-20 min, one study at a time)
BASE=${CSS_BASE:-$HOME/css_project}; cd "$BASE" || exit 1
STUDIES=${STUDIES:-M02,M03,M04,M05,M06,M07,M08,M09,M10,M11}; S=$BASE/scripts; R=$BASE/review
echo "version: $(cat $S/VERSION)"
# 1. record your decision (once): M11 object 12 of the current list = cSS (replaces the reads for that object)
A=$R/adjudication.csv
[ -f "$A" ] || echo "study_id,fate,obj_id,call,note" > "$A"
grep -q "^M11,shown,12," "$A" || echo "M11,shown,12,cSS,reader decision after the v5.7-E acceptance test" >> "$A"
# 2. keep the previous acceptance result, then run with the switch
for f in v53_compare.csv v53_compare_summary.txt v53_objects.csv; do [ -f "$R/$f" ] && cp "$R/$f" "$R/before_e22pieces_$f"; done
CSS_E22_PIECES=1 python "$S/v53_compare.py" "$STUDIES" 2>&1 | tee "$R/e22_pieces.log" | tail -45
cp "$R/v53_compare_summary.txt" "$R/e22_pieces_summary.txt"; cp "$R/v53_compare.csv" "$R/e22_pieces_compare.csv"; cp "$R/v53_objects.csv" "$R/e22_pieces_objects.csv"
cd "$R" && rm -f results_e22_pieces.zip && zip -q results_e22_pieces.zip e22_pieces.log e22_pieces_summary.txt e22_pieces_compare.csv e22_pieces_objects.csv adjudication.csv
echo "DONE. Send: $R/results_e22_pieces.zip"
