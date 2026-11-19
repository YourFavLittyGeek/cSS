# app/ — cSS Pipeline desktop app (no Terminal)
css_app.py (local server + queue, 127.0.0.1 only), css_app.html (interface), series_detect.py (finds SWI / T1 / FLAIR / phase in
DICOM or NIfTI folders), ai_score_cli.py (Automatic mode: AI-only score, not validated), mac/cSS Pipeline.app (launcher).
It runs the installed pipeline (scripts/cohort.py, run_css.sh with CSS_V53=1 CSS_ZONE2=1 CSS_CONF=1) one patient at a time and never
changes detector thresholds or rules. Names (optional) only in $CSS_BASE/private/names.csv. App data in $CSS_BASE/app_data/.

## v5.11.0-phase1 app9 additions
- **Several patients at once**: Patients > Queue > "Run at the same time" (1-4). The recommended number comes from this Mac's
  memory and cores (about 12 GB and 4 cores per SynthSeg patient, 6 GB kept for macOS); choosing more asks for confirmation.
  SWI-only and SynthMorph always run alone. Imports run one at a time (cohort_import.csv is shared).
- **Memory bar**: green < 70 %, yellow 70-85 % (no new patient starts), red >= 85 % (warning + "Stop newest patient", which
  puts it back in the queue).
- **Check before starting** (last step of Add patients): best T1 chosen automatically (3-D, <= 1.2 mm, whole brain, same visit;
  neck / orbit / partial series skipped), recommended pathway per patient, overlap / date check.
- **Automatic pathways** (Settings: "Switch automatically + tell me" / "Ask me first"): no usable T1 -> SWI-only; misregistration
  -> Fast re-registration -> SynthMorph -> then the user decides. A notice lists every change; choosing a non-recommended
  pathway asks for confirmation.
- Icon follows the theme (icon_dark.png / icon_light.png); the Mac app uses AppIcon.icns (dark).
