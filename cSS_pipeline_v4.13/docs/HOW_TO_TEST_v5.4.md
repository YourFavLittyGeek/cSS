# How to test v5.3 + v5.4 on the cohort (M01–M15)

Research software; expert review required. Nothing here repeats skull-stripping, FreeSurfer or registration:
those results are already in `data/` and `work/` and are reused. Only the detection (a few minutes per patient)
is run again. One command at a time; do not start anything else heavy while one runs.

## 0. Install (once)
    cd ~/Downloads/cSS_pipeline_v5.4.1
    cp scripts/*.py scripts/*.html scripts/*.sh ~/css_project/scripts/
    conda activate css

## 1. Try the new reviewer on a patient you already read (changes nothing in the detection)
    python ~/css_project/scripts/review_web.py M02
Your old calls load under your name. Check: scrolling, zoom (+ / -), right-click menu, magnifier (B), a missed-cSS
mark (X) and its deletion, the Calls summary tab (F3). Stop with Ctrl+C in the Terminal.

## 2. Acceptance test of the v5.3 detection rules on the 10 read patients (project is not modified)
    python ~/css_project/scripts/v53_compare.py M02,M03,M04,M05,M06,M07,M08,M09,M10,M11
Works in `~/css_project/v53_eval/`. Result: `review/v53_compare_summary.txt` (+ `v53_compare.csv`).
Targets: cSS calls still shown 61 / 61 (or each loss explained), Artifact < 25, Normal < 80, cSS in tier 3 < 6.
Send the summary before going on. If cSS calls are lost, the rules are adjusted first.

## 3. Only if step 2 is acceptable: the untouched test patients
    python ~/css_project/scripts/redetect.py M12,M13,M14,M15 --v53
    python ~/css_project/scripts/review_web.py M12,M13,M14,M15
Read them with the AI meter hidden (K) if the reading is to count as a test of the detector. Press Q at the end
of each patient for the score. M01 still needs its recon-all to finish (run_css.sh) before it can be detected.

## 4. Optional: apply v5.3 to the patients already read
    python ~/css_project/scripts/redetect.py M02,M03,M04,M05,M06,M07,M08,M09,M10,M11 --v53
The previous lists and calls are copied to `review/backup_<date_time>/`. Calls are re-attached by candidate
fingerprint; candidates that v5.3 merged or reshaped lose their call and must be read again (the reviewer shows
them as not read). To go back: copy the files from the backup folder into `review/`.

## 5. Compare with the radiologist (after all patients are read)
    python ~/css_project/scripts/compare_grades.py        # as before

## What is NOT redone
Skull-stripping / SWI masking, recon-all, registration, FLAIR alignment. They are needed again only for a new
patient or new images (`run_css.sh`).
