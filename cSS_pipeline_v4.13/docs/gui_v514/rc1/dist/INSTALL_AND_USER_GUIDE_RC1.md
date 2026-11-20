# cSS Experimental — local test release candidate 1 (v5.14.2-rc1)

Research software. Not clinically validated, not for diagnosis.

**Source:** branch `experimental/unified-gui`, uncommitted, on top of production commit `3bbfa14`. The build writes the exact commit and "+uncommitted changes" into `BUILD_INFO.txt` and into the app's pipeline `BUILD` file.

**Not verified on a Mac.** The bundle was built and its launcher run on Linux as a stand-in (see the test report). Installing and launching it on your Apple Silicon Mac is the first step below.

## 1. What it is and how it stays separate from production
| | Production (unchanged) | Experimental (this build) |
|---|---|---|
| App | `cSS Pipeline.app` | `cSS Experimental.app`, bundle id `research.css.pipeline.experimental` |
| Project folder | `~/css_project` | `~/cSS_experimental` (the launcher **refuses** `~/css_project`) |
| Port | 8800 | 8810 (both can run at the same time) |
| Pipeline code | `~/css_project/scripts` | `~/cSS_experimental/scripts`, installed from the bundle on first start |
| Your existing studies | — | brought in **read-only**: files copied, FreeSurfer **linked**, never written |

## 2. Requirements (already on your Mac)
- Apple Silicon Mac, macOS 12 or later.
- Miniforge with the conda environment `css` (python 3.11, nibabel, numpy, scipy, scikit-image, pandas, matplotlib). No new packages are needed.
- FreeSurfer 8.2 in `/Applications/freesurfer/…` with its licence. It is only **read** for existing studies; nothing is reconstructed.
- No internet connection is needed. The app makes no outside connection.

## 3. Build (on the Mac, from the repository)
```
cd <repo>/cSS_pipeline_v4.13
git status                     # branch experimental/unified-gui
bash tools/build_experimental_app.sh ~/cSS_experimental_build
cat ~/cSS_experimental_build/BUILD_INFO.txt   # version, commit, "+uncommitted changes", zip sha256
```
Output in `~/cSS_experimental_build/`:
- `cSS Experimental.app`;
- `cSS_Experimental_v5.14.2-rc1.zip`;
- `BUILD_INFO.txt`;
- `uninstall_experimental.sh`;
- this guide.

## 4. Install and first launch
1. Drag `cSS Experimental.app` into `/Applications`.
2. First time only: right-click the app → **Open** → **Open**. The app is unsigned, so macOS asks once.
3. On first start the launcher:
   - creates `~/cSS_experimental`;
   - installs the bundled pipeline into it (a later build backs up the old scripts first);
   - copies the app code;
   - activates conda `css` and finds FreeSurfer;
   - starts the app on port 8810.
4. Check the version in the top bar: it must read `pipeline v5.14.2-rc1 (experimental/unified-gui, local test release candidate)`.
5. Errors are written to `~/cSS_experimental/app_data/logs/launcher.log`.

**Two settings must be the same as in production**, because the app has its own settings file: FreeSurfer folder and licence. Open **Settings** and confirm them before step 6.

## 5. Bring in your existing processed studies (read-only)
**Processing** tab → *Bring in studies from another project folder* → **Choose…** → `~/css_project` → **List studies** → tick the studies → **Bring selected into this project**.

| What | How |
|---|---|
| SWI, T1, FLAIR, phase (`data/`) | copied (sha256 recorded in `runs/<ID>/link.json`) |
| registrations, labels on the SWI grid, vessel / dark maps (`work/`), SynthSeg (`synthseg/`) | copied |
| earlier candidates, QC, manifest, AI score (`review/`) and unified reports | copied: they become the **historical run** |
| FreeSurfer `subjects/<ID>` | **symlink**: read, never written; no reconstruction |
| reader files: calls, final, score, review log, missed outlines | copied to `historical/<ID>/` only; never shown to the pipeline |
| raw DICOM (`raw/`) | **not** copied: anatomy and registration can't be re-run for a linked study (by design) |

Copying uses disk space: roughly the size of each study's `data/` + `work/` folders.

## 6. Check compatibility and run the new detection
Select a study in the Processing tab.
- **MRI identity:** sha256, dimensions, voxel size and orientation of the SWI / T1; the FreeSurfer version and `-no-v8` from its scripts folder; the previous detection version.
- **Compatibility per stage** (anatomy → registration → labels → detection → unified score):

  | Status | Meaning |
  |---|---|
  | compatible | can be reused |
  | compatible with limitations | can be reused; the limitation is shown (e.g. no pial surfaces, low-confidence QC, SWI-only) |
  | incomplete | the stage did not finish |
  | incompatible | e.g. made from a different SWI / T1, registration rejected by QC, or older than the current candidates |
  | corrupted | an unreadable or truncated file |
  | unknown | outputs exist but nothing links them to this MRI yet |
  | not applicable | e.g. registration on the SWI-only route |
  | missing | no output found |
  | needs re-run | an earlier stage must be re-run first |

- **Unknown outputs:** press **Confirm and record as run** once. This changes no file; it records the outputs on disk as the first run (the historical run).
- **New detection run** (recommended): reuses anatomy, registration and labels, then runs again with this version:
  - cSS detection with the production flags `CSS_V53` / `CSS_ZONE2` / `CSS_CONF`;
  - surface features, when pial surfaces and the registration exist;
  - morphology inputs;
  - AI score;
  - unified score and explanations.

  **FreeSurfer is never re-run from here.**
- **Re-run from a stage:** alignment / detection / unified, with later stages following. Anatomy / registration can only be re-run for studies added through *Add patients* (they need the raw series), via **Patients → Re-run**. That path reuses a finished FreeSurfer automatically, and a new reconstruction is never started unless you ask for it.
- **Before every run** the current outputs are archived in `runs/<ID>/<run_id>/files/`.
  - **If the run fails** they are put back, and the failed run's own files are kept in `failed_outputs/`.
  - **If the app is closed mid-run**, the next start marks the run *interrupted* and puts the previous outputs back.

## 7. Review the new candidates
- **Processing → Open candidates in the reviewer**, or **Results / Review**.
- The reviewer shows the new candidate list.
- The **3-D** button opens the morphology panel:
  - surface / voxels;
  - local shape with the *unresolved* and *acquisition-limited* classes, and a box explaining why a part is not resolved (unresolved ≠ absent);
  - Hessian shape, thickness, skeleton, cross-sections, layers.
- The **Unified score** card shows the five predictors (x4 = surface conformity) with reliability and the explanation.
- **Not validated:** the AI score and unified score are labelled as such in the app.

## 8. Processing history
History table per study:
- run id, start and end, stages run and reused, status, software version;
- **Details:** per-stage states, MRI hashes, parent run, archive folder, error message with log tail, run log;
- **Make active…** (with confirmation): restores the outputs of an older completed run; the current outputs stay archived;
- **Resume…:** for failed / interrupted runs, starts a new run from the first unfinished stage.

## 9. Export, backup and local-only rules
- **Export / Share package:**
  - writes only to the **export folder** set in Settings;
  - shows a clinical-data warning that must be confirmed every time;
  - never uses the Desktop.
- **Backup:** same rule for the backup folder.
- **Refused folders:** `~/Desktop`, `~/Documents` (iCloud "Desktop & Documents" can sync them silently), iCloud Drive, `~/Library/CloudStorage` (Dropbox, Google Drive, OneDrive, Box) and missing or read-only folders.
- **Network:** the app and the reviewer listen on 127.0.0.1 only and make no outside connection. No telemetry, no upload.

## 10. Your verification steps on the Mac (please report each as pass / fail)
1. **Build:** run the build, then `cat BUILD_INFO.txt`. Commit `3bbfa14…` +uncommitted changes, version v5.14.2-rc1.
2. **Launch:** right-click → Open. The window opens; the top bar shows v5.14.2-rc1. `~/cSS_experimental` exists, and `~/css_project` is untouched (`ls -la ~/css_project` shows the same dates as before).
3. **Production still works:** open `cSS Pipeline.app` at the same time (port 8800); it shows the production version.
4. **Offline:** turn Wi-Fi off and repeat steps 5–8 below. Everything must work.
5. **Bring in:** bring in 2–3 processed studies, including one with recon-all. In Finder, `~/cSS_experimental/subjects/<ID>` is an alias to `~/css_project/subjects/<ID>`.
6. **Compatibility:** per-stage statuses look right for those studies; FreeSurfer shows version 8.2.0. Confirm the earlier outputs.
7. **New detection run:** run it on one study and watch the stage; it should take minutes, not hours. History shows two runs, the new one active.
8. **Review:** open the reviewer.
   - The candidate count matches the new run.
   - The 3-D panel opens.
   - On a 1.5 T 3 mm study, check that some candidates read acquisition-limited, with the explanation box.
9. **Make active:** make the historical run active, then the new one again; the candidate list switches back and forth.
10. **Recovery:** start a run and quit the app (Settings → Quit) while it is working; reopen. The run is *interrupted* and the previous candidates are back.
11. **Export:** with no export folder set, Export is refused. Choose `~/Desktop` as export folder: refused. Choose a folder on an external disk: the warning appears, and after ticking the box the file is written there.
12. **Integrity:** afterwards, `find ~/css_project -newer ~/cSS_experimental_build/BUILD_INFO.txt` lists nothing.

## 11. Uninstall
```
bash ~/cSS_experimental_build/uninstall_experimental.sh                   # removes the app; keeps ~/cSS_experimental
bash ~/cSS_experimental_build/uninstall_experimental.sh --remove-project  # also moves ~/cSS_experimental to the Trash (asks; type DELETE)
```
- Linked FreeSurfer folders are symlinks: removing the experimental project never removes your originals.
- Production `cSS Pipeline.app` and `~/css_project` are never touched.

## 12. Known limitations
See `RC1_INVENTORY.md`, section "Known limitations".
