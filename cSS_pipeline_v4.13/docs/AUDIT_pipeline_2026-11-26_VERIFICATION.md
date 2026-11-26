# Verification of AUDIT_pipeline_2026-11-26.md, and what was fixed (2026-11-26)

The audit (branch `claude/pensive-brahmagupta-09dlhu`, commit 335951f; copied here unchanged as `AUDIT_pipeline_2026-11-26.md`) was
written against b8bd34e. Every claim was checked against the code at b543b6a and, read-only, against the user's project (study codes
and counts only). Nothing was changed before this verification.

## New defect found during the verification (not in the audit), fixed
**The final save left the shared calls and the shared grade at 0.** `review_web.py /api/finish` rebuilt the effective calls
(`call_ledger.materialize`) BEFORE writing the final record and the blind-read completion. Consensus counts only completed expert
reviews, so the reviewer did not count yet: 0 effective calls, shared `ID_score.json` = 0.
- **User's project:** 17 of 47 studies had 0 stored effective calls while the ledger resolves all of them. 13 patients showed grade 0
  in the Results tab and `results/cSS_results.xlsx` where the expert graded 1-4: 026, 027, 033 (4), 039, 041, 042, 047, 048, 056, 057,
  058, 059, 060.
- **Second cause (039, 041, 042):** a later rebuild did not re-score while the study was on Pensieve.
- **Not affected:**
  - the reviewers' own files,
  - `review/css_report.xlsx` (it reads the final records),
  - training (it resolves the ledger directly).

Fix:
1. The final save rebuilds again after the final record and the completion are written.
2. `stale_effective()` finds studies whose stored count differs from the ledger or whose score was computed from other calls (failed
   score attempts are not retried at every start).
3. At startup `calls_refresh_stale()` rebuilds those studies. The ones on Pensieve are brought back (verified) and re-scored in the
   background, one at a time, with a notification.

Tests: `tests/test_role_refresh.py`. Browser-checked on the synthetic demo: an expert's final save gives 6 effective calls and a
shared score of 1, where before both were 0.

## Defects (section 2A)
| # | Verdict | Action |
|---|---|---|
| A1 grade from `percival_score >= 50` | true. The score is calibrated, so 50 = "more likely than not", but the model's cuts were unused. Also, candidates PERCIVAL held back for review were dropped silently | **fixed**: `total` = green (likely), `total_upper` = green + yellow (possible); abstained candidates -> status `needs_review`, lower bound; cuts recorded |
| A2 several "AI" numbers; the rule meter drives the AI score | true. No ranker model in the project, so it is the pure rule meter | **fixed**: the reviewer and Results show the PERCIVAL grade when it exists, the rule meter only as a labelled fallback; new fields withheld in blind reads |
| A3 legacy `albus.py` | true (both bugs reproduced); off by default, nothing live uses it | **fixed**: threshold recorded before the update; at most 3 misses per patient count; docstring says retired |
| A4 delete ~4,000 lines incl. `pensieve.py` / `vault.py` | partly wrong: `vault.py` (Vault, backups, transfers) and `pensieve.py` (`DurableLocalJournal`) are LIVE | not deleted; the retired modules stay behind the off-by-default comparison adapter |
| A5 unused `test_assignment` imports | true, harmless (the split is only `split.py`) | left as is |

## Limits (section 2B)
1. **"Labels from one non-expert; training set may be empty":** wrong for this project. 543 calls in 47 studies; 44 studies were read
   blind by the expert-role reviewer; 39 cSS calls in 16 studies. Real limit: the locked test group has 4 patients with cSS and 5
   without, and acceptance needs 5 + 5.
2. **"No grade-level evaluation":** partly wrong. `analysis.study_agreement` (quadratic weighted kappa vs expert grades) exists in
   `study_level_state`. It is not part of training or acceptance.
3. **Sensitivity counts only lesions experts found:** true by design; missed-cSS marking + ALBUS re-detection address it.
4. **Per-scan relative ridge threshold, so every scan yields candidates:** true.
5. **OOD limit from the training distances:** true.
6. **Optimistic family selection:** true and documented in the code (honest numbers: nested + locked test).
7. **2-D seeds:** true.
8. **Mixed rule sets possible:** possible, but not the case now. All 51 studies' manifests record the same switches.

## Recommendations not done here
- stratified test group (needed once there are more patients with cSS);
- a grade-level objective in training and acceptance;
- an absolute detector threshold with a scan-level "no cSS" decision;
- one frozen rule set per release;
- OOD from out-of-fold distances;
- moving the retired modules to `legacy/`.
