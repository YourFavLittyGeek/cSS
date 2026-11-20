# Percival rc4 test report (v5.14.2-rc4)

**Where:** Linux container, synthetic data only. Not on macOS, no real MRI.

| Suite | Result | Log |
|---|---|---|
| `bash tests/run_tests.sh` | ALL TESTS PASSED, exit 0 | `TEST_run_tests.txt` |
| `bash tests/run_uscore_tests.sh` (incl. new `check_selection_notifications.py`, `check_ui_poll.py`) | all passed: 421 PASS, 0 FAIL, exit 0 | `TEST_uscore_and_app.txt` |
| `bash tests/test_shell.sh` | SHELL TESTS PASSED, exit 0 | `TEST_shell.txt` |
| `python3 tests/e2e_rc1.py` (builds Percival.app, real launcher + detector) | 37 PASS, 0 FAIL, exit 0 | `TEST_e2e.txt` |

## Failures along the way (kept honest)
1. **First rc4 run: 4 failures in `check_uscore_pipeline.py`.** The test still expected the old held-out studies; the cohort split had changed to M01–M26 / M27–M36. The failing checks were:
   - "M18 / M23 / M25 listed as held-out";
   - "fitting on a held-out study refused";
   - "held-out labels refused in development mode";
   - "refused access is logged".

   The test was updated to the new held-out studies (M27 …). Its rerun passed, 0 FAIL.

   **The log of that failed run was deleted by mistake** when the logs were reset for the next run. These four names are the record.
2. **`check_selection_notifications.py`, first run:** "Trained model ready" was missing. A real bug: a training run shorter than the watcher interval was never noticed. Fixed by tracking each run's start; the rerun passed.
3. **`check_ui_poll.py`:** run against the previous screen code, it fails exactly as reported (scroll 738 → 0, sections closed). It passes on the fixed code.
4. **Reviewer top bar:** at 1024 / 1280 px the reviewer name ended at 1395 px (off-screen). After the fix it fits at 1024 / 1280 / 1440.

## New behaviour covered (`check_selection_notifications.py`, 28 checks)
- **Gate:** closed → training refused in the training code itself.
- **Apply refusals:** Exclude without a reason; the same patient on Train and Test. A refused Apply writes nothing.
- **Versions:** v1 / v2 kept; restoring v1 creates v3.
- **Training:** uses the selection version; held studies are left out; label fingerprints are recorded.
- **Notifications:** trained-model-ready; calls-changed (urgent, a label, resolved by Hold); snooze returns after its time; a removed item stays in the log; settings are saved.
- **Recommendations:** registration rejected → Exclude recommended, not applied.
- **Auto-train:** starts when a Train study's calls change (gate open, threshold).
- **GUI:** no page errors; no horizontal overflow at 1024 / 1280 / 1440 px.
