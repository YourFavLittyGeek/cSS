# RC3 test report: v5.14.2-rc3 (rc2 + restored production confidence / ranking models)

**Package:**

| | |
|---|---|
| Zip | `dist/cSS_Experimental_v5.14.2-rc3.zip` |
| sha256 | `4467622d777d79e78077548379d6bd975472682b95bb009e95c1f6d33aa49114` |
| Built | 2026-11-19 23:24 UTC |
| Source | `3bbfa14` + uncommitted changes on `experimental/unified-gui` (`dist/BUILD_INFO.txt`) |

**Where tested:** Linux container, synthetic data only. Not on macOS, no real models, no real MRI.

| Command | Result | Log |
|---|---|---|
| `bash tests/run_tests.sh` | ALL TESTS PASSED, exit 0 | `TEST_run_tests.txt` |
| `bash tests/run_uscore_tests.sh` (now incl. `check_production_models.py`) | all passed: 388 PASS lines, 0 FAIL, exit 0 | `TEST_uscore_and_app.txt` |
| `bash tests/test_shell.sh` | SHELL TESTS PASSED, exit 0 | `TEST_shell.txt` |
| `python3 tests/e2e_rc1.py docs/gui_v514/rc3` | 37 PASS, 0 FAIL, exit 0 | `TEST_e2e.txt`, screenshots |

**Full suite:** every suite passed on its first full run.

**During development of the new test, two of its own checks failed** (kept honest here):
1. **First version:** the synthetic confidence model never pushed a candidate below its cut, so E30 was not actually exercised. The test caught this as "vacuous". The synthetic model's intercept was changed so one candidate falls below the cut.
2. **The E30 count read the wrong column:** `reason` holds the text, `rule_version` holds the rule id. It now counts by `rule_version`, and also requires identical rule ids.

**Earlier releases:** the failed and successful logs remain in `../rc1/` and `../rc2/`.

## `tests/check_production_models.py` (requirements 1–9)
| Requirement | Check |
|---|---|
| Local copy only | the copy is made by the app process, under the write guard and network guard (`check_local_only`); nothing is sent anywhere |
| Byte-for-byte, sha256 recorded and equal | both files: source sha = destination sha = recomputed; bytes compared directly |
| Production untouched | every file of the source project (models, labels, …): content + modification time identical |
| Confidence + E30 restored (`CSS_CONF=1`) | confidence_pct filled for every candidate; E30 fires in both runs |
| Ranking only where production applies it | dev study ranked (`score_model` present, "[3c]" logged); test study not ("split is 'test'" logged) |
| **Parity** | candidate lists (157–159 columns) and excluded lists with rule ids identical between a production-way run and an RC3 app run of the same study |
| Compatibility before use | the same `css_confidence.load` schema / feature check as detection; ranker structure check |
| Missing / incompatible / failed / changed | reported as not present / INCOMPATIBLE / CONFLICT, parity False, and named in every run log as "PRODUCTION PARITY NOT MET" |
| No retraining or changes | no fitting code is called; detector, `css_confidence.py` and `rank_candidates.py` unchanged against `3bbfa14` |
