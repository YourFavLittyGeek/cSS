# IMPORT_WORKFLOW.md - guided import (v5.16)

Open **Add studies › Open guided import** (or `#import`).

1. **Data folder** - one sub-folder per patient. A patient folder may hold one examination (its series directly) or several
   examination folders (`<patient>/<exam>/...`); DICOM series are grouped by StudyInstanceUID.
2. **What the patient folder names are** - MRN, patient name or de-identified patient code. Always asked, never assumed. It only tells
   Percival how to read the folder names; it never replaces the study identifier.
3. **Mode for this import** - Standard (accession number) or Incognito (de-identified study code), independent of the folder naming.
   De-identified folder names recommend Incognito (with the reason). Standard needs the unlocked vault.
4. **Manifest** - download `Percival_Import_Template.xlsx` (always the four columns `MRN · patient_name · accession_number ·
   code (de-identifier)`, in this order, in both modes; one row per examination; repeat MRN / name for each examination of a patient),
   or choose a completed one. Incognito: optionally let Percival generate missing codes (once, persistently).
5. **Validate identifiers** - Standard: accession present and unique (also against the project), MRN present; Incognito: code present
   (or to be generated) and unique; codes 1-32 letters / digits / - / _; conflicting names on one MRN flagged; the same name under several
   MRNs kept as different patients (never merged).
6. **Preview** - patient folders, examinations, series, identifiers (Incognito: none of MRN / name / accession / folder names / paths),
   the manifest row of each examination (matched by DICOM AccessionNumber, a code equal to the examination folder, or the only examination
   of the patient; otherwise you assign it), duplicate status (new / new exam of an existing patient / already imported -> left out /
   conflict -> must be fixed), display name. Errors block the import.
7. **Confirm** - only a valid preview can be imported. Percival creates the patient / examination records (identifiers into the vault),
   copies the chosen series into the project under neutral names, queues the examinations under their file keys and lists the generated
   codes.

Re-importing an existing examination never overwrites reviews or processing: it is recognised by its image content / StudyInstanceUID
and left out.
