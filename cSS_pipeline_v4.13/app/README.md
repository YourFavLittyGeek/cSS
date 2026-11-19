# app/ — cSS Pipeline desktop app (no Terminal)
css_app.py (local server + queue, 127.0.0.1 only), css_app.html (interface), series_detect.py (finds SWI / T1 / FLAIR / phase in
DICOM or NIfTI folders), ai_score_cli.py (Automatic mode: AI-only score, not validated), mac/cSS Pipeline.app (launcher).
It runs the installed pipeline (scripts/cohort.py, run_css.sh with CSS_V53=1 CSS_ZONE2=1 CSS_CONF=1) one patient at a time and never
changes detector thresholds or rules. Names (optional) only in $CSS_BASE/private/names.csv. App data in $CSS_BASE/app_data/.
