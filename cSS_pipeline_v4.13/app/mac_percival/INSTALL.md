# Percival Dev - read me first (development build v5.23-dev)

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

## Using the Percival Score
1. Research › **Percival Intelligence** › **Switch on local learning** (once per project).
2. Review studies as usual and press **Save final**.
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
