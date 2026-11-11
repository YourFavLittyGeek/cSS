# v5.5 — final cSS score, AI score, comparison before the final save, Excel report

Research software; expert review required. Detector rules: v5.3.3 (docs/CHANGELOG_v5.3.md), still opt-in (`CSS_V53=1`).

## Scales shown everywhere (score_css.py, unchanged definitions)
- Hemisphere score: 0 = no cSS; 1 = one sulcus or up to 3 immediately adjacent sulci; 2 = two or more non-adjacent
  sulci, or more than 3 adjacent sulci. Total = right + left (0–4).
- Category: focal = 1–3 sulci involved; disseminated (diffuse) = more than 3 sulci; absent = none.
- Continuous cSS lines (new, reported only): accepted candidates within 6 mm of each other count as ONE line
  (`L_lines`, `R_lines`, `n_lines_total`). The 0–4 score counts sulci, so several pieces of one lining never raise it.

## Reviewer (review_web)
- Score chip in the top bar: reviewer score (after Q) and AI score. Calls summary tab: both scores as cards.
- AI score = the same scoring applied to the candidates in the meter's green band (>= 0.66), written to
  `review/ID_score_ai.json` only (`score_css.py --accept-ids ... --tag ai` never touches the reader's files).
  Rule-based, NOT validated.
- Q (or the last decision) opens "Before saving: AI vs reviewer": both scores, the calls that differ from the AI,
  click a row or "Re-review disagreements" to go back, "Save final" to finish. Calls changed after this window are
  logged as `revote`. "Do not show this window again" and Settings → "Show the AI comparison before the final save"
  switch it off / on; without it Q saves the final review directly.
- Final save writes `review/ID_final.json` and the cohort report `review/css_report.xlsx` / `.csv`
  (`python scripts/css_report.py` rebuilds it): R, L, total 0–4, category, sulci, continuous lines, AI scores,
  score difference, candidates read, calls differing from the AI, re-votes, missed cSS marked.
- Settings menu: comparison window, AI meter, auto-next, theme.

## Reading protocol note
Showing the AI score and the comparison before the final save lets the reviewer change calls towards the AI. For a
reading that is meant to test the detector (M12–M15), switch the comparison off, or use the recorded number of
re-votes to report it.
