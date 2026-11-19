# RC2 test report: v5.14.2-rc2 (rc1 + production write guard + isolated, verified import)

**Package:**

| | |
|---|---|
| Zip | `dist/cSS_Experimental_v5.14.2-rc2.zip` |
| sha256 | `a5a7bac927d387d79190c8cd4c076b741400d94a1a8328da81729371b4690a91` |
| Built | 2026-11-19 22:28 UTC |
| Source | `3bbfa14` + uncommitted changes on `experimental/unified-gui` (`dist/BUILD_INFO.txt`) |

**Where tested:** Linux container (x86_64), synthetic data only, headless Chromium. **Not on macOS**; no real FreeSurfer, no real MRI.

## Results (rc2 logs in this folder; rc1 logs, including the failed first attempt, kept in `../rc1/`)
| Command | Result | Log |
|---|---|---|
| `bash tests/run_tests.sh` | ALL TESTS PASSED, exit 0 | `TEST_run_tests.txt` |
| `bash tests/run_uscore_tests.sh` (now incl. `check_write_guard.py`, the rewritten `check_link_study.py`, `check_pm_full_pipeline.py`) | all passed: 361 PASS lines, 0 FAIL, exit 0 | `TEST_uscore_and_app.txt` |
| `bash tests/test_shell.sh` | SHELL TESTS PASSED, exit 0 | `TEST_shell.txt` |
| `python3 tests/e2e_rc1.py docs/gui_v514/rc2` (builds the rc2 bundle, real launcher, real detector, GUI, restart, integrity, network) | 37 PASS, 0 FAIL, exit 0 | `TEST_e2e.txt`, `E2E_RC1_RESULT.txt`, screenshots `R01`–`R14` |

- **rc2:** every suite passed on its first full run.
- **rc1 history:** the failure is kept as `../rc1/TEST_uscore_and_app_attempt1_FAILED_T4.txt`, and the successful rerun as `../rc1/TEST_uscore_and_app.txt`.
- **Before the full run:** while developing rc2, two of the new checks failed on test-fixture gaps and were fixed in the tests, not in the guard:
  - the fixture had no registration file, so the manager correctly blocked detection;
  - the `TMPDIR` attack: Python fell back to the system temp folder, which is safe isolation, and the test now checks where the file landed.

## Your requested attacks (`tests/check_write_guard.py`, 28 checks; each refused or safely isolated)
| Attempt | Result |
|---|---|
| Export into `~/css_project` (itself, inside, through a symlink); tampered settings file | refused |
| Backup into `~/css_project` (same three; tampered settings) | refused, logged in `logs/backup.log` |
| `CSS_EXP_BASE` = production subfolder / path through a symlink into production / folder containing production | launcher refuses before creating anything; app refuses to start (also production itself) |
| Symlink to a production directory: as destination, as project folder, creating one, writing through one | refused |
| Results folder inside production (Add patients; also a symlink into production; per-patient copy) | refused |
| Writing through a linked FreeSurfer directory | no longer possible by construction (isolated copy); writing through any symlink into production is refused |
| A pipeline child process writing into production during a real run | refused by the guard (logged), run outputs went to the experimental project |
| Starting a program aimed at production (`subprocess`, `os.system`, working folder) | refused |
| Temporary files with `TMPDIR` inside production | isolated: Python's tempfile falls back to the system temp folder; nothing written into production |
| Interrupting an import (mid-copy; crash during placement; source changing during import) | rolled back, reported, nothing half-imported (`check_link_study.py`) |
| Interrupting a processing run (app closed mid-run) | interrupted, previous outputs restored (E2E + `check_processing_manager.py`) |
| **Production project after all attacks** | **every file and folder: content and modification time identical** |

E2E additionally showed:
- the running app has the guard active (`CSS_EXPERIMENTAL=1`, guard on `PYTHONPATH`);
- the import is verified (`import.json`), with FreeSurfer as a real folder;
- the production sandbox is unchanged;
- no outside network connection was attempted.

## Tested only on Linux / still needs your Mac
- APFS copy-on-write clone (`clonefile`): Linux used the normal-copy path. Both are verified by sha256, but the clone path itself has not run.
- Gatekeeper first open; native window; osascript folder pickers; launcher dialogs.
- Real FreeSurfer recon import (size, time), real detection on your study, Wi-Fi-off run.
- The guard on macOS paths (`/Users/...`, `/Volumes/...`, iCloud folder names).
