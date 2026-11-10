# v5.4 — browser reviewer (`scripts/review_web.py` + `review_web.html`)

Research software; expert review required. The detector is unchanged. The old reviewer (`review_css.py`) still works
and both write the same `review/ID_calls.csv`, so marking and scoring are unchanged.

    conda activate css
    python ~/css_project/scripts/review_web.py M12            # or M12,M13,M14,M15 (study drop-down)
Opens http://127.0.0.1:8765/ in the browser; the server listens on this computer only. Stop it with Ctrl+C.

## What it has
- Three linked planes scrolled like a DICOM viewer (radiological orientation, R / L / A / P / S / I shown):
  wheel = slices, Ctrl+wheel or = / - = zoom, drag = pan, click = crosshair, right-drag = contrast / brightness.
- Themes light / dark / eye-preserving blue (T). Reviewer name box (upper right) with the earlier names in a
  drop-down and the last one filled in; a decision without a name is refused.
- Decisions Y cSS, V vein, N normal cortex, A artifact, U unsure, H near ICH; saved at once; Z undo; Backspace clear;
  auto-next (G); comment box (C); candidate strip coloured by call; summary + score (Q).
- Marking on / off (M), other candidates' markings (O), minIP slab (I), sequence drop-down (S, 1-5): SWI, FLAIR, T1,
  T2, filtered phase — only those that exist for the patient. T1 on the SWI grid is made once with `mri_vol2vol`
  (same transform as the labels); T2 is shown only if `work/ID_t2_swispace.nii.gz` exists (the pipeline does not
  import T2).
- Tools: darkness probe (D; 3 x 3 mean as % of normal cortex and in SD, the detector's measure), ruler (L, mm),
  missed-cSS mark (X; click, note, delete).
- Help window (?) with the decision rules, the meter and every key.

## Files written (all in `review/`)
`ID_calls.csv` (active reviewer, old format), `ID_calls_<reviewer>.csv` (with comment + time), `ID_review_log.csv`
(append-only: every action with reviewer, time and the meter value on screen), `ID_missed.csv` (voxel in the SWI's own
indices + mm + reviewer + note), `reviewers.json`. Calls are re-attached by candidate fingerprint after a detector
re-run, as before.

## The meter — read this before relying on it
The number is `css_evidence / (css_evidence + vein_evidence)`, multiplied by 0.8 / 0.6 / 0.5 for review-priority tiers
2 / 3 / 4 and by 0.4 for the v5.3 skull-band or midline measures (or `score_model` when a trained ranker has written
it). Bands: red < 0.33, yellow 0.33–0.66, green >= 0.66. **It is not a probability and has not been validated**: the
weights are hand-set, and nothing has been compared with expert labels. Showing it before the decision can bias the
reader; the reviewer keeps it visible as requested, K hides it, and the log records whether it was on screen. For
reads used to test the detector (M12–M15), hiding it is the safer protocol.

## Tested
`tests/check_review_web.py` (server: name required, calls / comment / missed mark stored and re-loaded per reviewer,
old calls format kept) and a headless-browser run on the phantom (keys, wheel, zoom, probe, ruler, missed mark,
sequence switch, themes, help, summary; no page errors). Not yet used on a patient: large 3 T volumes (tens of MB
per sequence) load once per sequence and have not been timed on the Mac.

## v5.4.1 — reviewer additions
- Menu bar (File, Edit, View, Candidate, Tools, Help) and a right-click menu on the image with ticks; hovering
  "Sequence" opens the available sequences (the others are greyed out). Right-click without moving = menu,
  right-drag (or Shift+drag) = contrast / brightness; on a Mac, Ctrl+click works as right-click.
- Magnifier lens (B), 2.5x, follows the mouse.
- Zoom: + = - keys, numeric keypad, Cmd+wheel (Mac) / Ctrl+wheel (Windows), trackpad pinch.
- Right panel in three tabs: Viewer (F1), Candidates (F2: list + missed marks), Calls summary (F3: AI meter vs the
  reviewer's call per candidate, a 4 x 3 table, "only differ", CSV export with E).
- Comment: one rounded line, grey "Add a comment…" placeholder, C to type, Enter saves.
- Missed cSS (X): rectangle (default) or pen (W switches, several strokes, Backspace removes the last), optional
  note, Save (Enter) / Cancel (Esc). One slice per mark. Stored in `review/ID_missed.csv` with plane, slice, outline
  points and what the detector did there (overlaps a shown candidate / excluded by a rule / below a gate / not
  generated). Reported with the score; not counted in the 0–4 score.
- `scripts/redetect.py`: re-runs only the detection (optionally `--v53`) on prepared studies, with a backup of the
  previous lists and calls. No skull-stripping, FreeSurfer or registration is repeated.
"Agree" in the calls summary = cSS + green, or another call + red; yellow and "Unsure" count as neither. The meter is
still rule-based and not validated.
