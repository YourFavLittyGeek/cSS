# RC1: answers before Mac installation (verified against the code and files)

## 1. Checksum
**`cSS_Experimental_v5.14.2-rc1.zip` sha256:**
`0b3febbe34d020e2c6829d5185a0761d3ec3504422f9f7f7b2f92652afe35b95`

This is the zip delivered in the conversation, built on Linux at 2026-11-19 21:25 UTC.

To check it on the Mac:
```
shasum -a 256 cSS_Experimental_v5.14.2-rc1.zip
```

A zip you build yourself will have a **different** checksum, because the build date and file times differ.

## 2. Build procedure and what "native" means here
- **The bundle is not a compiled program.** `Contents/MacOS/cSS Experimental` is a bash script, exactly like the production app.
  - It starts the Python of your conda environment `css`. On your Mac that is Miniforge arm64, so it runs natively on Apple Silicon.
  - Nothing is compiled, so there is no architecture-specific binary to produce. Building on Linux or on the Mac gives the same bundle content apart from the build stamp.
- **The source of this build is not on your Mac.** It exists only as uncommitted changes in this cloud session, so you can't build it from your repository until it is committed and pushed, and that needs your approval. Until then, use the delivered zip:
  1. Check the sha256 above.
  2. Double-click the zip. Archive Utility keeps the launcher's executable permission (it is stored in the zip as `-rwxr-xr-x`).
  3. Drag `cSS Experimental.app` into `/Applications`.
  4. Right-click → Open → Open. The app is unsigned.
  5. If macOS says the app "is damaged" (a quarantine flag on downloaded files), run:
     ```
     xattr -dr com.apple.quarantine "/Applications/cSS Experimental.app"
     ```
- **Building on the Mac, once the branch is pushed:** run `bash tools/build_experimental_app.sh <outdir>`. `BUILD_INFO.txt` names the commit; compare that rather than the zip checksum.

## 3. The `score_css.py` change
**Exact diff** (the only change to any detector / scorer / registration file against `3bbfa14`):
```diff
@@ -374,7 +374,7 @@
-print(f"  regions: {', '.join(result['regions'])}")
+print(f"  regions: {', '.join(map(str, result['regions']))}")
```
- **What it does:** it changes only how a list is printed on screen. `', '.join()` requires text; region labels are text when FreeSurfer's colour table is available and numbers when it is not. The numeric case crashed.
- **No scoring effect:**
  - The score files are written **before** this line: `review/<ID>_score.json` / `_score_<tag>.json` at lines 356–358, the summary CSV at 364.
  - No calculation, threshold, rule or detector output is touched; `result` is not modified.
  - Before the fix, the crash only made the script exit with an error after saving. The app then reported "AI score not available" although the file had been written.
- **Expected effect on your Mac:** with FreeSurfer installed, region labels are names, so the crash most likely never occurred there and the change has no visible effect.
- **Evidence:**
  - Full phantom suite passes (`TEST_run_tests.txt`).
  - The app's integrity check T4 flagged the changed file (`TEST_uscore_and_app_attempt1_FAILED_T4.txt`, kept). The reference now records it as changed, with this reason; the rerun passes (`TEST_uscore_and_app.txt`, kept).

## 4. Are linked FreeSurfer folders genuinely protected against writes? **No, not by the operating system.**
A symlink gives the same access as the original folder. Any process running as you could write through it.

**What protects it today (code-level):**
- No script the experimental app runs writes into `subjects/<ID>`. This was checked in the code:
  - `detect_css`, `align_seg`, `surface_features`, `css_surface`, `score_css`, the reviewer and `unified_score` write only to `review/`, `work/` and `uscore/`;
  - `surface_overlay.py` writes to `review/` and is not called by the app.
- The Processing Manager never writes its `.css_input.json` into a linked folder.
- Its rename operations act on the link itself, not the target.
- Re-running anatomy / registration is refused for linked studies, so `recon-all` / `bbregister` can't run there.
- The E2E test confirmed that every file of the source project kept its exact content and modification time.

**What it does not protect against:** future code, a FreeSurfer command run by hand in that folder, or a bug that hasn't been found.

**To make it genuine for your test (OS-level, no code change):** before the test, make the test study's production folders read-only, and undo it afterwards.
```
chmod -R a-w ~/css_project/subjects/<ID>       # before the test
chmod -R u+w ~/css_project/subjects/<ID>       # after the test (production processing of this study needs it writable)
```
Any write attempt will then fail with "Permission denied" and appear in the log, which makes it visible evidence.

## 5. Can the experimental app write to `~/css_project`? **It is not prevented in every path.**
**Prevented / not done:**
- The project folder is `~/cSS_experimental`; the launcher refuses `~/css_project` itself.
- Bringing studies in only **reads** the source: copies are made into the experimental project.
- Pipeline runs write only inside the experimental project.

**Gaps found while answering (not fixed: you asked for no changes in this phase):**

| Gap | How it could write into production |
|---|---|
| A. Export / backup folder | `verify_local_dest` does not refuse a folder **inside** `~/css_project`. If you chose one, exports / backups would be written there |
| B. "Results folder" on Add patients (not used for linked studies) | the same, if set inside `~/css_project` |
| C. `CSS_EXP_BASE` | the launcher refuses `~/css_project` itself but not a **subfolder** such as `~/css_project/exp` |
| D. Linked FreeSurfer folders | as in 4 |

For your test, none of these is triggered unless you choose such a folder. **Recommended:**
- set the export / backup folders to a folder outside `~/css_project`, or leave them empty;
- don't set `CSS_EXP_BASE`;
- use the `chmod` protection from 4;
- after the test, run:
  ```
  find ~/css_project -newer ~/cSS_experimental/app_data/logs/launcher.log
  ```
  It should list nothing caused by the experimental app (production activity in that period would also show).

**If you want genuine code-level guarantees**, a small safety change can close A–C: refuse any destination or project path inside `~/css_project`. For D, FreeSurfer can be copied instead of linked, at roughly 0.3–1 GB per study. Either change needs a new build, a new checksum and a rerun of the tests, and only with your approval.

## 6. What happens to each file when a study is brought in (`processing_manager.link_study`)
`<SRC>` = the production project (`~/css_project`), `<EXP>` = `~/cSS_experimental`, `<ID>` = the study code.

| Source | Treatment | Destination |
|---|---|---|
| `<SRC>/data/<ID>_*` (SWI, T1, FLAIR, phase …) | **copied** | `<EXP>/data/` |
| `<SRC>/work/<ID>_*` (registrations `.lta` / `reg.json`, labels on the SWI grid, a2009s, FLAIR on the SWI grid, dark / vessel / pial-distance maps, ICH masks, dropped / gen maps …), except temporary robustness copies `<ID>_R<k>_*` | **copied** | `<EXP>/work/` |
| `<SRC>/synthseg/<ID>_*` | **copied** | `<EXP>/synthseg/` |
| `<SRC>/review/<ID>_*` detector outputs: candidates `.csv` / `.nii.gz`, excluded, qc, manifest, `score_ai.json`, surface features, other detector files | **copied** (become the historical run) | `<EXP>/review/` |
| `<SRC>/review/<ID>_*` reader files: names containing `_calls`, `_final`, `_review_log`, `_missed`, `_excluded_audit`, `_robustness`, and every `_score*.json` except `_score_ai.json` | **copied for comparison only** | `<EXP>/historical/<ID>/review/` (never read by the pipeline) |
| `<SRC>/uscore/features/<ID>.json`, `uscore/reports/<ID>.json` | **copied** | `<EXP>/uscore/…` |
| `<SRC>/subjects/<ID>/` (FreeSurfer) | **linked** (symlink; see 4) | `<EXP>/subjects/<ID>` → `<SRC>/subjects/<ID>` |
| `<SRC>/raw/`, `logs/`, `labels/`, `app_data/`, `private/`, `results/`, shared review files (`review/reviewers.json`, `css_scores.csv`, …) | **not touched, not copied** | — |

- Every copied file's path and sha256 are recorded in `<EXP>/runs/<ID>/link.json`, together with the source folder and the FreeSurfer link target.
- The source is opened **for reading only**: `shutil.copy2` reads it, and nothing is written, renamed or deleted there.

## Release documentation kept
- `TEST_uscore_and_app_attempt1_FAILED_T4.txt` (initial failure) and `TEST_uscore_and_app.txt` (successful rerun).
- Main suite, shell and E2E logs; `TEST_REPORT_RC1.md`.
