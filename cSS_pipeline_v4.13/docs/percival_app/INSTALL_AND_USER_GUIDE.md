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
Studies › select a study › **Edit identifiers** changes patient-level fields (all examinations of the patient) or examination-level
fields (this examination only); every change is audited; internal ids and file names never change.

## 3. Import studies
**Add studies › Open guided import** (recommended): data folder → what the patient folder names are (MRN / patient name /
de-identified patient code) → mode → `Percival_Import_Template.xlsx` (MRN · patient_name · accession_number · code (de-identifier); one row
per examination) → validated preview (duplicates, conflicts, missing identifiers) → confirm. Re-imports are recognised and left out.
The older "From image folders" table is still available; it now shows explained duplicate warnings and no longer scrolls sideways.

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

## 6. Research screens (experimental)
- **Training**: A Image ML (model card, weights, synthetic performance) · B Characteristic ML / Unified Score · C expert labels
  (css-labels/2.0) · D evaluation (synthetic and clinical results in separate panels; run a new synthetic evaluation).
- **Model** (Unified Score: study selection, training, validation), **Shadow ML** (Stage 1 engine, shadow mode), **Image ML**
  (synthetic studies only).

## 7. Tests
```zsh
bash tests/run_uscore_tests.sh            # app suite (stops at check_ui_poll without Node; see the handover for the no-stop run)
bash unified_engine/run_tests.sh /tmp/u.log
bash tests/run_tests.sh                   # pipeline suite on synthetic phantoms
```
