# IDENTITY_SCHEMA_AND_MIGRATION.md - Percival patient / MRI-examination identification (v5.16, 2026-11-20)

Decisions (user, 2026-11-20): encryption with the `cryptography` package (AES-256-GCM); the vault is unlocked by a passphrase per app
session; existing studies are migrated ADDITIVELY and `private/names.csv` is kept untouched; in Standard mode a study without an
accession number is flagged and new (re-)processing / exports of it are refused until the accession is entered (never generated).

## 1. Model
```
Patient (patient_uuid, permanent)            registry: pseudonym (de-identified patient identity, editable)
│                                            vault:    MRN, patient name
└── MRI examination (study_uuid, permanent)  registry: file_key (never changes), deid_code (unique, required), display_name,
    │                                                  image content fingerprint, salted hash of the DICOM StudyInstanceUID
    │                                        vault:    accession number (unique per institution), institution, DICOM StudyInstanceUID
    ├── processing runs, candidates, AI predictions, human reviews   (all filed under the file_key - unchanged by any identifier edit)
```
- **study identifier of the active mode**: Standard = accession number (required, unique per institution); Incognito = de-identified
  study code (required, unique in the project). A patient identifier is never used as a study identifier.
- **file_key**: the name every pipeline file uses (`data/<key>_swi.nii`, `review/<key>_*`, ...). Existing studies: their current code.
  New imports: the de-identified code given in the manifest (when it is a valid 1-32 character code and unused) or a generated code - never
  an accession number, MRN or name. It never changes after import, so renaming identifiers never breaks a link.
- **generated codes**: `PCV-XXXX-XXXX-XXXX`, 12 symbols from a 30-symbol unambiguous alphabet (no 0/O, 1/I/L, U; ~59 bits, `secrets`),
  uniqueness checked against every code and file key; stored once in the registry, so later screens, re-imports and exports reuse it.

## 2. Files
| file | content | protection |
|---|---|---|
| `app_data/identity/registry.json` (schema `percival-identity/1.0`) | uuids, file keys, deid codes, pseudonyms, display names, fingerprints, UID hashes, non-sensitive edit history | no direct identifiers by design (tested) |
| `private/identity_vault.enc` (schema `percival-identity-vault/1.0`) | MRN, names, accession numbers, institution, StudyInstanceUID, sensitive edit history (old / new values) | AES-256-GCM; key = scrypt(passphrase, n=2^15, r=8, p=1); file mode 0600; key kept in memory only while unlocked |
| `private/vault_backups/` | the encrypted vault before every write (last 20) | still encrypted |
| `app_data/import_src/<file_key>/` | the chosen series of a guided import, copied (APFS clone) under neutral names | no source path or file name is stored |
| `private/names.csv` | legacy plain-text names (before v5.16) | unchanged; copied into the vault on set-up / unlock; delete it yourself once you have checked the vault |

## 3. Migration (additive, automatic, idempotent)
At start the app gives every study in `app_data/patients.json` a uuid and a patient record; its code stays its file key and becomes its
de-identified code. When the vault is created or unlocked, names from `private/names.csv` are copied in (the file is not changed). Older
studies have no accession number: in Standard mode they show "accession missing". Fingerprints from before v5.15 are upgraded only from the
study's own raw copy (see PHASE_B_REPORT). No file is renamed, moved or deleted. Roll-back = delete `app_data/identity/` and
`private/identity_vault.enc` (the old app ignores them).

## 4. Modes
- **Incognito** (default while no vault exists): the server never returns an MRN, a patient name or an accession number - in the Studies
  screen, search, Activity, Process Manager, training (Model), Shadow ML, Image ML, Anatomy QC, notifications, import previews (no folder
  names or paths either), exports and the log viewer (absolute paths outside the project are hidden). The vault is locked when switching
  to Incognito.
- **Standard**: shows MRN, name and accession from the vault; requires the passphrase after each app start; locked again on quit.
- Switching changes only what is displayed: no record, uuid, file key, run, call or prediction changes.

## 5. Edits (Studies › study panel › Edit identifiers)
Patient-level (MRN, name / pseudonym) apply to every examination of the patient; study-level (accession, deid code, display name) to
one examination. Uniqueness is checked before saving; an MRN that belongs to another patient is refused (patients are never merged
automatically); sensitive edits need confirmation; every change is audited (time, field, old -> new, who, reason) - the values of sensitive
edits only inside the vault. The uuid and the file key are not editable.

## 6. Duplicate and conflict classification (examination level)
new · same patient / new examination (existing MRN) · same examination (identical image content or DICOM StudyInstanceUID: re-import,
moved or renamed folder - left out) · conflict (the identifier belongs to a different examination, or the accession belongs to a different
patient - must be resolved). Nothing is merged automatically.

## 7. Limitations and risks
1. Legacy study codes are file keys; if a legacy code itself was a patient name (the old "folder name looks like a name" warning), it
   stays visible as the code until the study is re-imported - rename it (deid code) only changes the displayed code, not file names.
2. Studies added through the older "From image folders" flow still store their source paths (as before v5.16); the guided import does not.
3. Pipeline logs written before v5.16 may contain source file names; the log viewer hides absolute paths in Incognito, not bare names.
4. The reviewer (separate window) shows file keys only - never names - but in Standard mode it does not show accession numbers either.
5. Losing the passphrase AND every vault backup = original identities unrecoverable (by design); de-identified codes keep working.
6. Re-processing from scratch with candidate lineage (Phase C) is not built yet; "Needs re-review" comes from the review ledger.
