#!/bin/bash
# v5.10 confidence model: record the new measures, fit the model, test it on copies, and only then exclude low-confidence objects. Research software.
# usage: conda activate css ; caffeinate -i bash ~/css_project/tools/run_v510.sh        (about 2 hours, one study at a time; close other heavy programs)
# STOPS before changing the lists if any cSS call would be lost.
BASE=${CSS_BASE:-$HOME/css_project}; cd "$BASE" || exit 1; S=$BASE/scripts; R=$BASE/review
FIT=${FIT:-M02,M03,M04,M05,M06,M07,M08,M09,M10,M11}; TEST=${TEST:-M12,M13,M14,M15}; READS=${READS:-ST,ML,Redo_v53,Blind_v57}
export CSS_ZONE2=1; echo "version: $(cat $S/VERSION)"
# radiologist grades (reference): R / L cSS score per hemisphere. Only the FIT studies are used for fitting.
G=$R/radiologist_grades.csv
[ -f "$G" ] || printf 'study_id,R,L\nM02,0,2\nM03,1,0\nM04,0,2\nM05,2,1\nM06,2,1\nM07,1,0\nM08,2,1\nM09,0,2\nM10,2,0\nM11,2,2\nM12,2,0\nM13,2,2\nM14,0,2\nM15,2,2\n' > "$G"
echo "=== 1/5 record the new measures (redetect, rules unchanged)  $(date '+%H:%M')"
rm -f "$R/confidence_model.json"
F1=${FIT%%,*}; if head -1 "$R/${F1}_candidates.csv" | grep -q "minip_cont" && [ -z "$FORCE_REDETECT" ]; then SKIP1=1; echo "    the lists already hold the new measures: step 1 skipped (FORCE_REDETECT=1 to redo)"; fi
python -c "import sys; sys.path.insert(0, '$S'); import css_shape, css_confidence, css_common; assert hasattr(css_shape, 'struct_measures') and hasattr(css_common, 'norm_call')" 2>/dev/null \
  || { echo "STOP: the installed scripts are incomplete (css_shape.py / css_common.py older than v5.9.1). Unzip the CUMULATIVE v5.10.1 zip and run again."; exit 1; }
[ -n "$SKIP1" ] || { python "$S/redetect.py" "$FIT" --v53 > "$R/v510_redetect1.log" 2>&1; grep -E "done:|NOT done" "$R/v510_redetect1.log"; }
F1=${FIT%%,*}; head -1 "$R/${F1}_candidates.csv" | grep -q "minip_cont" || { echo "STOP: the redetect did not write the new measures. Last lines of the log:"; tail -25 "$R/v510_redetect1.log"; cd "$R" && zip -q results_v510.zip v510_redetect1.log; echo "Send $R/results_v510.zip"; exit 1; }
echo "=== 2/5 fit the confidence model  $(date '+%H:%M')"
python "$S/fit_confidence.py" "$FIT" --reads "$READS" --grades "$G" > "$R/v510_fit.log" 2>&1 || { tail -5 "$R/v510_fit.log"; echo "STOP: the fit failed. Send $R/v510_fit.log"; exit 1; }
grep -E "objects:|leave-one-patient-out AUC|lowest protected|at this cut|HONEST CHECK" "$R/v510_fit.log"
cp "$G" "$BASE/v53_eval/review/" 2>/dev/null
echo "=== 3/5 acceptance test on copies with the low-confidence exclusion  $(date '+%H:%M')"
mkdir -p "$BASE/v53_eval/review"; cp "$R/confidence_model.json" "$BASE/v53_eval/review/"
export CSS_GRADES="$G"
CSS_CONF=1 python "$S/v53_compare.py" "$FIT" > "$R/v510_acceptance.log" 2>&1
cp "$R/v53_compare_summary.txt" "$R/v510_summary.txt"; cp "$R/v53_compare.csv" "$R/v510_compare.csv"
L=$(grep "cSS calls still shown:" "$R/v510_summary.txt"); echo "$L"; grep -A8 "Excluded by rule" "$R/v510_summary.txt"
bundle() { cd "$R" && rm -f results_v510.zip && zip -q results_v510.zip v510_*.log v510_summary.txt v510_compare.csv confidence_fit.csv confidence_fit_summary.txt confidence_model.json radiologist_grades.csv 2>/dev/null; cd "$BASE"; }
read A N <<< "$(echo "$L" | sed -E 's/.*: *([0-9]+) *\/ *([0-9]+).*/\1 \2/')"
if [ -z "$A" ] || [ "$A" != "$N" ]; then bundle; echo "STOP: a cSS call would be lost - lists NOT changed. Send $R/results_v510.zip"; exit 1; fi
echo "=== 4/5 apply: redetect with the low-confidence exclusion (fit studies + held-out studies, model frozen)  $(date '+%H:%M')"
CSS_CONF=1 python "$S/redetect.py" "$FIT,$TEST" --v53 > "$R/v510_redetect2.log" 2>&1; grep -E "done:|NOT done|backup" "$R/v510_redetect2.log"
echo "=== 5/5 result"
for s in ${FIT//,/ } ${TEST//,/ }; do echo "$s $(($(wc -l < $R/${s}_candidates.csv) - 1)) candidates, $(grep -c 'low confidence' $R/${s}_excluded.csv) excluded for low confidence"; done | tee "$R/v510_counts.log"
bundle; echo "DONE. Send $R/results_v510.zip"
