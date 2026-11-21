# Percival (experimental) - installation and user guide · branch `feature/unified-score-ml-integration`

**Research software. Not a diagnostic device. Every learned model in this build was trained on SYNTHETIC data only; the application
stays explicitly experimental until clinical validation is completed.** Everything runs on this computer; nothing is uploaded.

## 1. Install on a new Mac
1. Install Miniforge (conda) and FreeSurfer 8.x (any folder) with its licence file.
2. Create the environment from the package root:
   ```zsh
   conda env create -f cSS_pipeline_v4.13/environment.yml     # includes cryptography (identity vault) and openpyxl
   conda activate css
   ```
3. Start Percival on a project folder (never point a development build at a clinical project without approval):
   ```zsh
   cd cSS_pipeline_v4.13
   CSS_BASE=/path/to/project CSS_EXPERIMENTAL=1 PYTHONPATH=app/guard python app/css_app.py --port 8830
   ```
   and open http://127.0.0.1:8830.
   The project folder must contain the pipeline (`scripts/run_css.sh`); the setup wizard and the Studies banner report it if it is
   missing. To try the app without clinical data, make a synthetic demo project (it has no pipeline, so processing is not available there
   unless you add `CSS_APP_FAKE_RUN=1`, which only simulates runs):
   ```zsh
   python unified_engine/run_imaging.py cohort /tmp/percival_demo --n 4 --seed 42
   CSS_BASE=/tmp/percival_demo CSS_EXPERIMENTAL=1 PYTHONPATH=app/guard python app/css_app.py --port 8830
   ```
4. **First start: the setup wizard opens by itself** (later: Settings › Setup › Open setup wizard):
   - *1 · Installation check* - required items (OS, Python packages, folders, pipeline, FreeSurfer, licence, dcm2niix) and optional ones.
   - *2 · FreeSurfer and licence* - Browse to the FreeSurfer folder (Percival never assumes a location), Validate, choose the licence file,
     Validate (its content is never shown or sent), **Test the installation**, **Save configuration**.
   - *3 · Readiness report* - saved to `app_data/setup_report.json`; **Finish setup**.
   After installation Percival works offline (no internet, no external AI service; the image model weights are in the repository).

## 2. Identification: Standard and Incognito
Header switch **Standard | Incognito**. Incognito (default until a vault exists) shows only de-identified study codes. Standard shows
MRN, patient name and accession number from the encrypted identity vault and asks for the vault passphrase after each start. Set up the
vault the first time you choose Standard; back it up (encrypted) from the vault dialog; keep the passphrase separately.
Every MRI examination needs its identifier: accession number (Standard) or de-identified study code (Incognito).
**Studies:**
- **Standard:** separate columns for code, accession number, patient name and MRN; the list is grouped by MRN, by patient name, or not
  at all.
- **Incognito:** only the code and an incognito icon, with no grouping.
- Every column sorts ascending or descending (click its header).
- Filters: status (every status: needs attention, needs your decision, processing, paused, waiting, not processed, ready for review,
  review in progress, needs re-review, reviewed), cohort, code, accession, MRN and name, plus free search.
- A link like `#studies?grp=none&sort=mrn&dir=desc&status=Reviewed` opens a saved view.

Studies › select a study › **Edit identifiers** changes patient-level fields (all examinations of the patient) or examination-level
fields (this examination only); every change is audited; internal ids and file names never change.

## 3. Add studies (one pathway) and export
**Add studies** has two tabs, **From folders** and **From another project**. From folders:
1. Choose the data folder: one examination, or a folder holding many.
2. Say what the folder names are: patient name · MRN · accession number · code · irrelevant. This is a helper that fills in values
   automatically.
3. Choose the mode, Standard or Incognito:
   - **Standard:** MRN and accession number are required (Excel file or folder names); the name is optional; a blank code is
     generated. Studies are grouped by MRN.
   - **Incognito:** the key is required (Excel file with MRN, name, accession number and code), and every examination needs its code.
     The key is stored only in the encrypted vault, and studies are listed by code.
4. Choose the Excel file `Percival_Import_Template.xlsx`. When the folder names are irrelevant, every row must fill the `folder` column.
   Optional columns: `study_date`, `radiologist`, `grade_R` and `grade_L`.
5. Optionally turn on the **study library**: a verified copy of each examination at `library/<MRN>/<accession>/` (Standard) or
   `library/<code>/` (Incognito). Your original folders are never renamed or changed.
6. Set the processing options: cohort, anatomy and mode.
7. Check the **preview**. It opens on **Series review**: a picture and a choice list for SWI, T1, FLAIR and phase in each examination,
   with warnings and recommendations. Then go to **Identifiers and import**.
8. Press **Import and start**.

**Studies › Export ▾ › Studies with files…** exports results plus, as chosen, processed files, FreeSurfer, the original MRI and logs, to a
local folder you choose. Every file is verified with sha256. In Incognito the folders are named by code and DICOM files are left out.
Full details: `IMPORT_WORKFLOW.md`.

## 3b. Study administration
- **Identifiers:** in Standard the accession number identifies studies everywhere; in Incognito the code does.
- **Study panel:** MRN first, then the patient's examinations. **Edit** opens a form with Save / Discard; a checkpoint stops duplicate
  accession numbers or codes.
- **Studies toolbar:** **Archive ▾** (archive ticked studies or a cohort, or open the archive) and **Remove…** (Remove keeps results for
  ML; Purge removes everything; both move files to the Trash).
- **Import:** duplicates offer Skip / Replace / Import and keep the old results for ML / Cancel.
- **Previous version:** studies processed there are found under **Add studies › From another project**, and reused automatically during
  imports.
- Details: `STUDY_ADMINISTRATION.md`.

## 4. Process, review, re-process
- Processing runs from the queue (Activity). Each run is archived (Studies › study › **Compare runs**).
- **Review** opens the reviewer. *Your call (human reviewer)* - grouped calls (cSS / mimics / other) with subtype chips, keys
  Y V N B A U H, Shift+1..6 for a subtype, Z undo, Delete clear. The AI meter is labelled as the automated rule-based detector.
- A study shows **Reviewed** when every candidate has a call and a reviewer finished (any reviewer); **Needs re-review** when the
  candidates changed afterwards.
- Every reviewer's calls are kept. **Studies › Reviewer calls** (also on the Training screen) chooses whose calls are used - newest by
  default, a named reviewer per study, cohort or all studies; "Rewrite old calls" is protected by a typed confirmation and archived.
- **Re-run** re-processes from the original MRI with the current pipeline; earlier calls move to new candidates only through a
  confident match; possible matches wait for your confirmation in **Compare runs**.

## 5. Quality control
**Anatomy QC**: FreeSurfer installation, per-study FreeSurfer / SynthSeg / registration outputs (missing files listed), QC metrics,
the QC image (labels + brain mask on the SWI; can be made for imported studies), Freeview.

## 6. Older research prototypes (hidden by default since v5.24 - Settings › Show the older research prototypes)
They are separate prototypes and do **not** feed the Percival Score (which has its own Characteristic ML, Image ML and Fusion).
- **Training**: A Image ML (model card, weights, synthetic performance) · B Characteristic ML / Unified Score · C expert labels
  (css-labels/2.0) · D evaluation (synthetic and clinical results in separate panels; run a new synthetic evaluation).
- **Model** (Unified Score: study selection, training, validation), **Shadow ML** (Stage 1 engine, shadow mode), **Image ML**
  (synthetic studies only).

## 6b. Percival Score and Percival Intelligence (v5.22 - v5.24)
How it works: `PERCIVAL_ARCHITECTURE.md`. Local-only design and its verification: `LOCAL_AI_ARCHITECTURE.md`.
1. **Research › Percival Intelligence › Switch on local learning** (once per project; synthetic projects do not need it).
2. Review studies as usual. Every candidate you call (cSS, Vessel, Normal, Artifact, Microbleed) can become a training example; Unsure
   and Near ICH are kept but not used; uncalled candidates are never examples. Each final review is stored with the model outputs that
   existed when you saved it.
3. **Training Center** shows, per study and per candidate, whether a call can be used by Characteristic ML, Image ML, Fusion and the
   Percival meta-model, and why not (not reviewed, Unsure, reviewers disagree, left out, duplicate, no MRI patch, no measurements, locked
   test). Settings there: learn from every study with calls or finished reviews only; reviewer conflicts left out until adjudicated or the
   effective call used; reviews from earlier versions on / off.
4. **Start a training cycle** (or let one start automatically after 5 newly reviewed studies). The cycle first writes a dataset version
   (`percival/datasets/dsNNN.json`) that the new model records. A cycle compares model
   families, chooses the combination by cross-validation, calibrates, sets thresholds, evaluates once on the locked test patients and
   registers the new model as **candidate** (passed the acceptance criteria) or **experimental** (did not pass). **No model becomes
   active by itself:** in the **Model Center** you press *Make active* (a model that did not pass needs a written reason), *Reject*,
   *Restore* or *Roll back*; every training run, including failed ones, is listed in the Training Center.
5. In the reviewer each candidate shows **one Percival Score 0-100** with red / yellow / green; open **Why this score** for the sources,
   contributions, disagreement pattern, uncertainty and reasons. It is hidden during a validation (blind) read. A study whose labels
   trained the model is marked *in-sample*.
6. **Evidence & reliability** (`#intel?tab=evidence`) shows whether each source adds information, where sources share inputs, whether
   fusion helps, what disagreements meant in your reviewed cases, and the calibration plot.

7. **Data integrity** shows the data format version, migrations, backups and a compatibility line per study; *Find reviews in
   earlier projects* brings in the reviews of the same examinations from an earlier project (verified copy; the other project is only read).

The score is an experimental assessment calibrated on this project's reviews - not a probability of cSS and not clinically validated.

## 7. Tests
```zsh
bash tests/run_uscore_tests.sh            # app + Percival suite: runs every check; a check that cannot run here (check_ui_poll without
                                          # Node / npm) is reported SKIPPED, never passed; exit 1 if any check failed
bash unified_engine/run_tests.sh /tmp/u.log
bash tests/run_tests.sh                   # pipeline suite on synthetic phantoms
```
