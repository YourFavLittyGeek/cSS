# STUDY_ADMINISTRATION.md - identifiers, editing, archive, removal, duplicates, previous version (v5.20)

## One identifier rule
- **Standard (vault unlocked):** the **accession number** identifies a study everywhere. That includes Activity, the reviewer window,
  Anatomy QC, Training, Image ML, Shadow ML, Compare runs, notifications, pick lists and the log viewer. The code is shown only on
  **Add studies** and the **Studies** screen (its own column, and small in the study panel).
- **Incognito:** the **code** is used everywhere.
- **Vault locked in Standard:** the code is shown with a lock icon.
- **Internally:** every study keeps a permanent file key, and all files are named by it, so a change to what is displayed never renames a
  file. The reviewer window receives the labels from the app in memory; nothing with identifiers is written to disk for this.
- **macOS banners** are stored by macOS outside the app. In Standard they never carry an identifier ("A study finished").

## Study panel
- **Standard:** at the top, **MRN · patient name**; then cohort, accession number and the code (small); then the patient's examinations
  (click to switch).
- **Incognito:** the code only.
- `#studies?open=<key>` opens a study's panel directly.

## Edit
- **Edit** in the study panel opens a form with **Save** and **Discard**.
  - Standard: MRN and patient name (patient level, every examination of the patient); accession, code and display name (this examination);
    cohort.
  - Incognito: code, display name and cohort.
- **Edit** in the Studies toolbar changes the cohort or display name of the ticked studies. Identifiers are edited one study at a time.
- **Checkpoint** - one rule set used before any identifier is saved, by edit, import and bring-in:
  - the accession number is not used by another examination (archived ones included);
  - the code is not used by another examination and is not another study's internal key;
  - the MRN is not another patient's (patients are never merged automatically);
  - the library folder for the new identifier is free.

  A failed check changes nothing.
- **All-or-nothing:** every field is applied together or not at all. Afterwards the study library folder is renamed
  (`<MRN>/<accession>` or `<code>`) and the grades file is rebuilt. Every change is audited with its reason.

## Archive
- **Studies › Archive ▾:** archive the ticked studies, or a whole cohort.
- Archived studies leave Studies, Activity and Review; a waiting archived study is not processed. Every file is kept, and their
  identifiers stay reserved.
- **Studies › Archive ▾ › Open the archive** (`#archive`) lists them, with **Restore**, and has a second tab for removed studies kept for
  machine learning.
- Archived studies are **included in model training by default**. Untick *Settings › Features › Include archived studies in model
  training* to exclude them.

## Remove and Purge (Studies › Remove…, the ticked studies)
- **Remove (keep for ML):**
  - Images and processing files, and the study library copy (optional, ticked by default), go to the **Trash**.
  - Candidate tables, every reviewer's calls, labels, scores, features and image patches are kept.
  - The study is **retired**: it gets a new identifier `RET-xxxx-xxxx-xxxx` (kept files renamed, the key inside them too), and its
    accession number and code are released. The old values stay only in the encrypted audit.
  - Retired studies are in model training and are listed on the Archive screen.
  - Importing the same examination again is allowed, with the note "previously removed - results kept for ML as RET-…".
- **Purge:** every file of the study (and its library copy) goes to the Trash, and its identity record is deleted. The identifiers become
  free again; the audit keeps the event.
- **Safeguards:**
  - a preview of what goes to the Trash and what is kept, with sizes and a warning about reviewer calls;
  - typed confirmation (**REMOVE** / **PURGE**);
  - refused while a study is processing;
  - Remove needs the vault unlocked, because it releases the accession number into the encrypted audit.

## Duplicates during import
When an examination is the same as an existing study (same images), or reuses its accession number or code with different images, the
preview shows the existing study (identifier, status, processed or not, reviewer calls) and a choice:

| Choice | What happens |
|---|---|
| **Skip** | Not imported. This is the default for the same images. |
| **Replace** | The old study is **purged** (Trash), then the new one is imported. You must type **REPLACE** when importing. |
| **Import, keep the old results for ML** | The old study is **removed and retired** (RET-…, results kept); the new one takes the identifier. |
| **Cancel** | Leave the import and correct the identifier in the Excel file or folder name. |

## Studies processed in a previous version
- **Add studies › From another project › Projects found on this Mac** lists the previous Percival version (`~/cSS_experimental`), the
  production project (`~/css_project`), other `~/Percival_project*` folders and folders you add. For each it shows the processed studies
  and how many are already here.
- **Bring in N processed studies** copies them and verifies every file. The other project is only read.
- Every new folder import is checked against the enabled projects. If an examination is the same as a study processed there (image
  fingerprint in any form earlier versions recorded), the preview offers **Reuse earlier processing** (on by default): the results are
  brought in, not processed again. If bringing them in fails, the study is processed normally.
- Studies brought in from a version before the identity vault have only their code. In Standard, enter the accession number in the
  study panel (**Edit**); the checkpoint applies.
