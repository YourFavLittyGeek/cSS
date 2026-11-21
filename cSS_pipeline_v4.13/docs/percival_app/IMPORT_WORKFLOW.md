# IMPORT_WORKFLOW.md - Add studies (v5.18: one pathway)

**Add studies** has two tabs: **From folders** (described here) and **From another project**. The v5.16 "guided import" and the v5.17
"From image folders" batch table were merged into From folders, so there is only one way to import images. The "Store names" option is
gone: patient names come only from the Excel file or from patient-name folders, and they go only into the encrypted vault.

## Terms
- **Examination (exam):** one MRI visit of one patient, identified by its accession number. It contains several series (T1, SWI,
  phase, FLAIR...). Percival needs the SWI, and preferably a T1. In the preview, exam `2.1` means folder 2, examination 1.
- **Excel row (manifest row):** one line of `Percival_Import_Template.xlsx`, describing one examination. The preview shows which row
  was matched to each examination, and why.

## Identification rules
| | Standard | Incognito |
|---|---|---|
| MRN | **required** (Excel file or MRN folder names) | **required in the key** |
| accession number | **required**, unique (Excel file or accession-number folder names); never generated | **required in the key** |
| patient name | optional | optional in the key |
| code (de-identifier) | may be blank: a unique code is generated, so the study also works in Incognito | **required**: the study's unique identifier (Excel file, code folder names, or typed in the preview) |
| Excel file | needed unless the folder names give both MRN and accession | **always needed**: the key (MRN, name, accession, code) |
| vault | unlocked (Standard view) | the passphrase is asked so the key can be stored; the screens stay de-identified, and the vault is locked again after the import |
| grouping | examinations grouped by MRN (a patient can have several examinations) | none shown: studies are listed by code |
| study library | `library/<MRN>/<accession number>/` | `library/<code>/` |

The DICOM header (AccessionNumber, PatientID, StudyDate) is never a source of identifiers. It only cross-checks: an Excel row whose
accession number differs from the scan header's is not matched automatically.

## Steps
1. **Data folder.** Either one examination folder, or a folder holding many (one sub-folder per patient or per examination). Percival
   detects which. Your folders are only read: nothing is renamed, moved or changed.
2. **The folder names are** *patient name · MRN · accession number · code · irrelevant*. This is a helper: Percival uses the names to
   fill in values automatically. When the folders hold examination sub-folders, you can also say whether those sub-folders are named
   by accession number or by code (for example `MRN/accession/` needs no Excel file in Standard).
   - **Irrelevant:** the Excel file is required, and every row must name its examination's folder in the `folder` column (relative to
     the data folder). Matching is done by that column only.
   - **MRN, accession number or code:** the `folder` column is not needed.
3. **Mode:** Standard or Incognito (the rules above).
4. **Excel file.** Columns, in this order:
   - `MRN · patient_name · accession_number · code (de-identifier)` (always the first four);
   - optional: `folder · study_date · radiologist · grade_R · grade_L`. The radiologist's grades used to need a separate grades file.

   Files with only the four columns still work.
5. **Study library** (optional; the location is remembered and can be changed here or in Settings): a verified copy of each
   examination.
   - Choose "chosen series" (T1, SWI, phase) or "whole examination" (every series).
   - Every file is checked with sha256, and file names inside the copy are neutral (`SWI/SWI.nii`, `T1/T1_00001.dcm`...).
   - An existing library folder is never overwritten: the same examination is reported "already in the library", and a different one
     blocks the import until the identifiers are fixed.
   - Cloud-synced folders, Desktop and Documents are refused. Standard library folder names contain MRN and accession number, so keep
     the library on an encrypted local disk.
6. **Processing:** cohort, anatomy (SynthSeg / recon-all), semi-automatic or automatic, and an optional extra results folder.
7. **Preview** has two tabs.
   - **1 · Series review** opens first. For each examination it shows SWI · T1 · FLAIR · Phase: a picture of the middle slice of the
     chosen series, made on this Mac, and a list of every series of the examination to choose another one. Your choice is marked
     "chosen by you".
     - Beside each examination: **warnings and recommendations** - no or several SWI, no usable or 2-D T1, a T1 that was not chosen and
       why, T1 and SWI from different dates, FLAIR or phase available (optional).
     - SWI and T1 are chosen automatically. FLAIR and phase are chosen when present; they are optional, and the pipeline uses FLAIR when
       it is given.
   - **2 · Identifiers and import:** separate columns for patient name, MRN, accession number and code (each with its source), the Excel
     row and how it was matched, the pathway with its check, and library place / duplicate status / problems. In Incognito the patient
     column is an incognito icon and only the code is shown.
   Errors block the import.
8. **Import and start:** creates the patient and examination records (identifiers only in the vault), makes neutral copies for
   processing, queues the examinations, then copies them into the library in the background and shows the progress.

### Automatic series choice
- **SWI:** a susceptibility magnitude or processed series (SWI / SWAN / SWIp / susceptibility...). Phase, minIP and mIP are never used
  as the SWI; among several, the highest resolution wins.
- **T1:** 3-D (MPRAGE / BRAVO / SPGR / TFE), about 1 mm or finer, covering the whole brain. Neck, orbit, partial and 2-D series are
  skipped, with the reason shown.

### Matching Excel rows to examinations
Strongest evidence first; each rule applies only when it gives exactly one row:
1. accession number = DICOM AccessionNumber, or = the accession-number folder name;
2. code = folder name;
3. the Excel `folder` column;
4. MRN folder + `study_date`;
5. the only examination plus the only row of that patient.

Anything else is left for you to assign in the preview; nothing is guessed.

Re-importing an existing examination never overwrites reviews or processing. It is recognised by its image content or
StudyInstanceUID and left out.

## Export with files (Studies › Export ▾ › Studies with files…)
Exports the selected studies (or the filtered list) to a local folder you choose, after the clinical-data confirmation.
- **Always included:** results (candidates, every reviewer's calls, scores, QC, lineage, Unified / Shadow / Image ML outputs, QC image)
  and `results.xlsx`.
- **Optional:** processed files (pipeline images, registrations, segmentations, masks, run archive), the FreeSurfer / SynthSeg folder,
  the original MRI (the library copy) and the logs.

Folder layout: Standard `<MRN>/<accession number>/`, Incognito `<code>/`. In Incognito, DICOM files are left out because their headers
hold patient identifiers, and source paths in the logs are hidden.

Before copying, the export checks the free space. Every file is verified against `export_manifest.json` (sha256). The export is written
to `<name>.partial` and renamed only when complete, and an existing export folder is never overwritten.
