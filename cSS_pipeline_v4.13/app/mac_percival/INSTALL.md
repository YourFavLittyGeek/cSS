# Percival Dev - read me first (development build v5.24-dev)

**Research software, not a diagnostic device.** Percival learns only on this Mac, from your own MRI and expert reviews. The models it
comes with were tested on SYNTHETIC data only; nothing in this build is clinically validated. No internet and no external AI service
are used once it is installed. It is separate from the production app (`~/css_project`) and the Percival RC app (`~/cSS_experimental`)
and refuses to open either of those project folders.

## What is in the folder
| Item | What it is |
|---|---|
| **Percival Dev.app** | the application for your project |
| **Percival Demo.app** | the same application on a synthetic demo project (6 phantom studies, no patient data) - for trying things out |
| `docs/` | how Percival works (`PERCIVAL_ARCHITECTURE.md`), the local-only design, the v5.23 report |
| `USER_GUIDE.md` | screen-by-screen user guide |
| `environment.yml`, `uninstall_percival_dev.sh` | for administrators only - not needed for normal use |

## Install - no Terminal needed
1. Drag **Percival Dev.app** and **Percival Demo.app** into **Applications**.
2. Double-click **Percival Dev**. If macOS says it cannot verify the developer (the app is not notarised): right-click the app ›
   **Open** › **Open**. This is needed only the first time.
3. **First start only** - Percival asks two things:
   - **Where to keep your project** (default: `Percival_project` in your home folder; an existing one is reused automatically).
     Desktop, Documents and cloud-synced folders are refused.
   - **The one-time installation** of its Python components (when this Mac does not have them yet): press **Install**. It downloads
     open-source packages from conda-forge (about 2 GB, 5-15 minutes, internet needed once) and tells you when it is finished. Your
     projects are never sent anywhere. An existing `css` environment of the production pipeline is used if it is complete and is never
     changed; otherwise Percival makes its own environment called `percival`.
4. The Percival window opens and the **setup wizard** starts by itself: choose the **FreeSurfer** folder and its **licence file**
   (Browse › Validate › Test the installation › Save), then **Finish setup**. FreeSurfer 8.x itself is installed separately (it is large
   and has its own licence). Without FreeSurfer you can still review, look at results and use the research screens.

Double-clicking Percival again while it runs just brings its window back.

## Try it first with the demo
Double-click **Percival Demo**. It creates synthetic studies in `~/Percival_demo` and opens on them (port 8831), so it never mixes with
your project.

## What is new in v5.24
- **You decide which model is used.** A newly trained model is never switched on by itself. It is listed in Percival Intelligence ›
  Model Center as *candidate* (passed the acceptance checks) or *experimental* (did not pass). Press *Make active* to use it. A model
  that did not pass can only be made active with a written reason. *Reject*, *Restore* and *Roll back* are there too, and every change
  is logged.
- **Training Center shows the whole learning process:** every training run (including failed ones), which reviewed candidates each
  part of Percival may learn from and why others are left out, the dataset versions, and a check that a dataset can be rebuilt
  exactly from your reviews.
- **Older reviews count for learning.** Reviews made with earlier versions (including the old call name *Vein*, now *Vessel*), partly
  reviewed studies, studies re-detected after review and reviews brought in from an earlier project are all used. Only candidates you
  actually called become examples; uncalled candidates are never treated as "not cSS".
- **Training Center** (Percival Intelligence) shows every study's states separately (processed / reviewed / called / eligible / used) and
  for every called candidate whether it can be used by each part of Percival and why not.
- **Data integrity** shows where your data is, its format version, every migration and backup, and a compatibility line per study.
  *Find reviews in earlier projects* brings in reviews of the same examinations from your earlier Percival / production project
  (verified copy; the other project is only read).
- The older research screens (Training, Predictor model, Shadow ML, Image ML) are hidden from the menu; Settings can show them again.
  They never fed the Percival Score.

## Your data, updates, backups and recovery
- Everything you create stays in your **project folder** (default `~/Percival_project`): studies, reviews, results, Percival models and
  predictions (`percival/`). The app itself contains program files only.
- **Updating**: replace the app. On the next start Percival checks the format of your data; if it must be converted it first copies it to
  `<project>/backups/percival/`, converts it, verifies every file and keeps the old copy. Nothing is deleted.
- If a newer Percival created your data, an older app refuses to change it and says so - open it with the newer app.
- **Restore** an earlier state: quit Percival, rename `<project>/percival` (e.g. `percival_broken`), copy the wanted folder from
  `<project>/backups/percival/` to `<project>/percival`, start Percival.
- Back up the whole project folder regularly (e.g. Time Machine or an encrypted external disk). Never put it in a cloud-synced folder.

## Using the Percival Score
1. Research › **Percival Intelligence** › **Switch on local learning** (once per project).
2. Review studies as usual (every candidate you call counts; **Save final** marks the study finished).
3. **Start a training cycle** (or let one start after every 5 newly finished studies). A new model is used only if it passes the
   acceptance tests on patients it never learned from; otherwise it is kept as a candidate (Registry: Make active / Roll back).
4. In the reviewer each candidate has **one Percival Score (0-100)** with red / yellow / green; **Why this score** shows the evidence.
   It is hidden during a blind validation read.
The score is an experimental assessment calibrated on your own reviews - not a probability of cSS.

## Update / uninstall
- **Update**: drag the newer Percival Dev.app over the old one. On the next start it updates the pipeline in your project; old scripts
  are backed up; your calls, grades, results and models are kept.
- **Uninstall**: drag the two apps to the Trash. Your project folder stays until you delete it yourself.

## If something does not work
- Installation log: `~/Library/Application Support/Percival Dev/setup.log`
- App log: `<your project>/app_data/logs/launcher.log`
- "Port 8830 is used by another program": quit the other program or the other Percival, then open Percival again.
- To choose a different project folder later: delete `~/Library/Application Support/Percival Dev/project_path` (Finder › Go › Go to
  Folder…) and open Percival again.
