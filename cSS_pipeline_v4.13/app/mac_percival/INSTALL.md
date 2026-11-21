# Percival Dev - install and use (development build v5.17-dev)

**Research software, not a diagnostic device.** The learned models in this build were trained on SYNTHETIC data only. The app runs
entirely on this Mac, with no internet and no external AI service. It is separate from the production app (`~/css_project`, port 8800)
and the Percival RC app (`~/cSS_experimental`, port 8810), and it refuses to open or write to either of those project folders.

## What is in the zip
| item | what it is |
|---|---|
| `Percival Dev.app` | the app, with the cSS pipeline scripts, the Unified Score code, the Unified engine and the synthetic image model inside |
| `environment.yml` | the Python environment the app needs (conda env `css`) |
| `USER_GUIDE.md` | screen-by-screen user guide |
| `uninstall_percival_dev.sh` | removes the app (keeps your project folder unless you ask) |

## Install (once)
1. **Miniforge (conda)**: if `conda` is not installed yet, install Miniforge from conda-forge.
2. **Python environment** (in Terminal, from the unzipped folder):
   ```zsh
   conda env create -f environment.yml          # first time
   conda env update -n css -f environment.yml   # if the "css" environment already exists (adds cryptography, openpyxl)
   ```
3. **FreeSurfer 8.x** and its licence file (`license.txt`), installed in any folder. Percival does not assume a location; you choose
   it in the setup wizard. `dcm2niix` is needed for DICOM input (`brew install dcm2niix`).
4. Drag **Percival Dev.app** into Applications. The app is not signed, so the first time: right-click › **Open** › **Open**.

## First start
- On first start the app creates its project folder **`~/Percival_project`** and installs the bundled pipeline into it (scripts are
  backed up on later updates).
- The **setup wizard** opens by itself:
  1. Installation check (required and optional items).
  2. FreeSurfer folder and licence: Browse, Validate, then Test the installation and Save. The licence contents are never shown.
  3. Readiness report, then **Finish setup**.
- The window opens at http://127.0.0.1:8830. Closing the window does not stop processing; Settings › **Quit the app** does.
- To use another project folder or port, start the app from Terminal:
  ```zsh
  PERCIVAL_BASE=~/Percival_other PERCIVAL_PORT=8831 "/Applications/Percival Dev.app/Contents/MacOS/Percival Dev"
  ```
  Desktop, Documents and cloud-synced folders are refused.

## Try it on synthetic data first
```zsh
conda activate css
python "/Applications/Percival Dev.app/Contents/Resources/pipeline/unified_engine/run_imaging.py" cohort ~/Percival_demo --n 4 --seed 42
PERCIVAL_BASE=~/Percival_demo "/Applications/Percival Dev.app/Contents/MacOS/Percival Dev"
```
This makes four synthetic studies (SYN001-SYN004) that work with every screen, including Image ML. Image ML only runs on synthetic
studies.

## Daily use
1. **Identification**: the header switch is **Standard | Incognito**.
   - Incognito (the default) shows only de-identified study codes.
   - Standard shows MRN, name and accession number from the encrypted vault on this Mac. It asks for the vault passphrase after each
     start; keep the passphrase somewhere separate.
2. **Add studies › Open guided import**: choose the data folder and say what the patient folder names are.
   - Fill in **Percival_Import_Template.xlsx** (MRN · patient_name · accession_number · code; one row per examination). Download it
     from the wizard.
   - Check the preview (duplicates, conflicts, missing identifiers), then confirm.
   - Every examination needs an accession number (Standard) or a de-identified code (Incognito). Percival never makes up accession
     numbers.
3. **Activity**: processing runs from the queue.
4. **Review**: give your call per candidate.
   - Calls are grouped as cSS / mimics / other, with subtype chips. Keys: Y V N B A U H; Shift+1..6 picks a subtype; Z undoes.
   - The AI meter is the rule-based detector, not a reviewer.
5. **Studies › Reviewer calls**: every reviewer's calls are kept, with date and time.
   - The newest call is used by default, or a chosen reviewer per study, per cohort or for all studies.
   - "Rewrite old calls" asks for a typed confirmation and archives the old calls first.
6. **Re-run** reprocesses a study from the original MRI.
   - Earlier calls move to the new candidates only on a confident match.
   - Possible matches wait for you in **Compare runs**.
7. **Anatomy QC**: FreeSurfer / SynthSeg / registration outputs, the QC image, Freeview.
8. **Research screens** (experimental): Training, Model (Unified Score), Shadow ML, Image ML.

## Update / uninstall
- **Update**: replace the app with a newer build. On the next start it reinstalls the pipeline into the project; old scripts go to
  `scripts/backup_*`, and your calls, grades and results are kept.
- **Uninstall**: `bash uninstall_percival_dev.sh` removes the app. Adding `--remove-project` moves the project to the Trash, after a
  typed confirmation.

## Logs and help
- Logs: `~/Percival_project/app_data/logs/launcher.log`.
- If the app does not open, check that log first. The usual causes are: conda env `css` missing, the env missing cryptography (step 2),
  or port 8830 already in use (set `PERCIVAL_PORT`).
