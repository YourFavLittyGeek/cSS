# Local dataset audit: review package

Branch `experimental/unified-gui`, uncommitted. **Nothing has been run on clinical data.** Every test used small synthetic fixtures.

## Contents
| File | sha256 |
|---|---|
| `audit_local_dataset.py`: the audit you run on the Mac | `66578e23…` |
| `check_audit_local.py`: its test on a synthetic base | `74f140e2…` |
| `check_local_only.py`: the app-wide network / local-only test | `9327afcd…` |
| `netguard/sitecustomize.py`: test-only network blocker used by `check_local_only.py` | `9d605cd7…` |

Check the hashes with `shasum -a 256 *.py netguard/*.py` (full values in the session report).

## How to run (on the lab Mac)
```
conda activate css
cd ~/css_project/scripts            # after the file is installed there, or from wherever you keep it
python3 -B audit_local_dataset.py ~/css_project
```
- `-B`: no `__pycache__` files are written.
- The output folder defaults to `~/cSS_audit_reports/`. Choose another with `--out /Volumes/LabDisk/audit`.
- These output folders are **refused**:
  - anywhere inside the dataset;
  - `~/Desktop` and `~/Documents` (iCloud "Desktop & Documents" may sync them);
  - iCloud Drive, `~/Library/CloudStorage` (Dropbox, Google Drive, OneDrive, Box), and other cloud folders.
- Network: the script blocks every connection from its own process except to this computer, and it makes none itself.

## What it READS (never writes)
| Source | What is taken from it |
|---|---|
| `data/<ID>_swi.nii*` | sha256 of the file (identical exports), header only via nibabel: voxel size, dimensions |
| `review/<ID>_candidates.csv` | row count; whether a `confidence_pct` column exists (first line) |
| `review/<ID>_calls.csv`, **development studies only** | column names; the `call` value of each row, counted against a fixed vocabulary (cSS, Vessel / Vein, Normal, Artifact, Microbleed, Unsure, Near ICH, …). Anything else is counted as "(other free text)" and its text is never copied |
| `labels/study_meta.csv` | the split (dev / test) and status (pos / neg / uncertain) counts, development rows only; used in memory to find the held-out studies |
| `labels/*.csv` | header line only: are there patient-like columns (patient / subject / MRN / pseudo / person)? |
| `unified_score/**/manifest*.csv`, `uscore/**/manifest*.csv` | `role`, to find held-out studies |
| `app_data/patients.json` | field names; counts of records with grades / radiologist; status / mode counts; repeated source-folder hashes |
| `review/<ID>_score_ai.json`, `review/<ID>_manifest.json` | the scoring-method and detector-version strings |
| `review/reviewers.json` or `app_data/reviewers.json` | whether it exists and how many entries |
| `reference_audit/blind_read/*` | number of blind-read packets |

## What it deliberately does NOT read
- **Calls of protected held-out / test studies.** These are:
  - `split = test` in `study_meta.csv`;
  - role held-out in a unified-score manifest;
  - always M01, M12, M13, M14, M15.

  For these studies the file is only counted as present; its content is never opened.
- **Image voxel data.** For each SWI, only the header and the file hash are read.
- **Never opened:** T1 / FLAIR content, FreeSurfer directories, `private/names.csv`, `raw/` DICOM, and reviewer comment text.

## What it WRITES
Exactly two files, both outside the dataset:
```
~/cSS_audit_reports/
  audit_<YYYYmmdd_HHMM>.json
  audit_<YYYYmmdd_HHMM>.md      (the same content, readable)
```

The report sections are:
- `studies_found`;
- `study_meta` (counts);
- `protected_heldout_studies` (count; `labels_opened: false`);
- `mri`:
  - studies with an SWI;
  - unique SWI files;
  - duplicate groups;
  - duplicates that span development and held-out;
  - voxel-size and dimension distributions;
- `patient_grouping`:
  - per label table (named `label_table_1`, `label_table_2`, … and never by file name), the column names that look like patient identifiers;
  - a finding sentence;
- `app_patients` (counts);
- `candidates`:
  - total candidates;
  - calls files present;
  - held-out calls files not opened;
  - call-value counts and blank calls;
  - call-file column names;
  - files with a candidate fingerprint;
  - development studies with and without any cSS call;
- `provenance`:
  - AI score files and their methods;
  - detector versions;
  - studies with the confidence-model output;
  - reviewer file present / count;
  - blind-read packets;
  - `review_condition_recorded: false`, plus the AI-assisted finding;
- `missing_for_training`: what must be supplied before any training, stated and never invented.

**Never in the report:**
- study codes;
- names;
- file names or paths;
- dates of birth;
- DICOM headers;
- feature values;
- free-text call values or comments.

Column names that don't look like ordinary identifiers are shown as "(unusual column name)".

## Tests (synthetic; all pass in the development container)
`check_audit_local.py` (17 checks):
- the run succeeds;
- nothing inside the dataset is created, changed or removed (sha256 of every file before and after);
- exactly two report files, outside the dataset;
- the held-out study's calls are never opened (a marker value in that file never appears);
- no study code, path or file name in the report;
- free text is bucketed, never copied;
- refused output folders: inside the dataset, `~/Desktop`, iCloud;
- no bytecode cache;
- the held-out file is counted as present only;
- duplicates are found, including one that spans development and held-out;
- a missing patient key is reported, not invented;
- a non-loopback connection is blocked.

`check_local_only.py` (6 checks):
- static scan of `app/`, `scripts/` and `unified_score/`: no network library and no external host. The one listed exception is `run_lemon.sh`, the optional public-dataset downloader, which sends no local data and is never called by the app;
- both servers bind to 127.0.0.1;
- the Processing Manager and app tests pass with all outside connections blocked and logged, and none was attempted;
- backup / export destinations in cloud folders are refused.

## Known limits
- The fixed held-out list (M01, M12–M15) is from the project notes. If your protected set differs, edit `HELDOUT_FIXED` before running.
- Patient grouping can only be reported, not done: the script finds no patient key unless a labels table has one.
- It can't tell whether a reviewer saw the AI score. Per your description, all existing grading is treated as AI-assisted.
- A cloud-sync check by path can't see every sync tool (e.g. a third-party tool syncing an arbitrary folder). Choose a folder you know is local.
