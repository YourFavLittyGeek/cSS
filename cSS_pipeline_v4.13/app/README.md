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
- app10: Settings "When a retry is needed" (retry automatically / let me choose); every failed registration is recorded and the
  recommendation moves on (Fast re-registration -> SynthMorph -> recon-all -> SWI-only); expected time beside each option,
  recommended in green; old "processing failed" rows re-read from the run log at start; QC opens in its own window (arrows step
  through patients); recommended number of patients at once recalculated from the pathways in the queue (memory per pathway:
  SynthSeg / masked 12 GB, recon-all 5 GB, SynthMorph / SWI-only alone); optional pywebview window with a Dock icon that
  follows the Mac appearance (Home > Setup check > Install).
- app12: icon-only Awake (☕) / Sleep (🛏) and theme (☀ / ☾, dark = grey) switches; QC grade from the label shift
  (A+ <= 0.5, A <= 0.8, B+ <= 1.0, B <= 1.5 pass, C <= 2.5, F; low-confidence one grade lower, a pass stays >= B);
  red ! = change the pathway by hand (automatic mode applies at once with a notice, "let me choose" asks);
  AI score computed automatically for every finished patient (and back-filled at start); results workbook
  <results folder or $CSS_BASE/results>/cSS_results.xlsx updated after every patient, "Open Excel"; Share as xlsx / csv /
  docx / pdf (codes only, Desktop); Review opens the window at the click (pop-up fix) with every finished patient, the
  reviewer has Cohort + Patient drop-downs and ◂ ▸ (review_web.py --groups FILE --start ID); live run log in the Log
  window; "no progress for N min" after 20 min without a log line.
- app13 (reviewer): after the final save a small card (bottom right) shows your score and the AI score with a green / grey
  "next patient automatically" switch and a countdown to the next patient of the cohort (Stay / Next / details).
  Settings menu: "Go to the next patient automatically" (default on) and "Close the summary after" Immediately (no summary) /
  3 / 5 / 10 (default) / 20 / 30 s. The last patient of a cohort keeps the full summary ("Cohort finished").
- app14: reviewer menu bar File / Candidate / View / Tools / Help + 💾 Save final (⌘↩; shows unread count) + ⚙ Settings (one grouped
  window: reading incl. blind read, after the final save, AI support, image, panel, screenshots); settings are stored in
  review/viewer_settings.json and shared by every reviewer window and the app (Settings / Review screen: "Reviewer settings…").
  Blind read also in File. Screenshot (File, Tools, camera in the left tool strip): macOS screencapture of the reviewer window,
  or an area chosen with the mouse (Settings). Theme stays in the top bar. App: Re-run asks for the pathway (default; Settings:
  automatic = same pathway as last run).
- v5.14: after each finished patient the app also runs the EXPERIMENTAL unified candidate score (Settings feature
  `unified_score`, default on): `$CSS_BASE/unified_score/run_unified.py app ID` -> `$CSS_BASE/uscore/reports/ID.json`; results
  workbook columns unified_css_compatible / unified_uncertain / unified_alternative / unified_model. Without a trained model
  ("no model yet") only the alternative-explanation detectors and feature reliability are reported. Nothing is hidden or
  suppressed; reader files are never touched. install.sh copies unified_score/ to $CSS_BASE. No screen layout changed.
- v5.14.1-gui: tab **Unified (experimental)** (workflow + test protocol) - see docs/GUI_VALIDATION_WORKFLOW_v514.md. The unified score
  after each patient is now OFF by default (switch in that tab) and runs only after the patient is done and its results are saved.
