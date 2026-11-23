# Handover verification record (2026-11-23)

Subject: the Gemini Antigravity handover package in `docs/handover_claude/` (five files, untracked, kept
unmodified for historical reference). **It is not a technical specification.** The source code at
`65b0e49` is authoritative. This record lists where the package disagrees with the code, so that nobody
relies on it later.

How it was verified: by reading the code (three independent audits + direct spot-checks of every
high-severity claim) and running the suites once on 2026-11-23 (114 unit tests OK, JS syntax check OK).
That one run was done as the handover instructed and wrote to the live project (see "Test isolation").

## Factual discrepancies

| Handover claim | Code / system reality |
|---|---|
| FreeSurfer 7.4.1 at `/Applications/freesurfer/7.4.1` | 8.2.0 at `/Applications/freesurfer/8.2.0` |
| Python 3.11.11 | 3.11.17 (`css` env) |
| Working tree clean | handover docs untracked |
| 37 JS syntax tests | correct (37 PASS lines + the ALL PASS summary; an earlier count of 38 in this record included the summary line) |
| Per-file test counts (e.g. ALBUS 5, NOX 5, CORE 6) | ALBUS 3, LUMOS 3, NOX 2, CORE 3, failure scenarios 21, adversarial 8, services 5 (total 114 matches) |
| 37 preserved studies | 22 verifiable locally (11 `raw/import_source_preserved`, 11 `app_data/import_src`); 15 on `/Volumes/Percival/Dicom` unverifiable (not mounted); `raw/STUDY-016..019` duplicate `import_src` IDs |
| `stage_study_to_ssd` / `archive_study_to_vault` | do not exist; methods are `stage_study` / `archive_study` |
| 1 MB streaming chunks | `DEFAULT_CHUNK_SIZE` = 4 MB |
| `system_config.json` canonical config | file does not exist; config spread over settings.json, setup_state.json, setup_done.json, `~/.percival_vault_config.json`, `~/Library/Application Support/Percival Dev/project_path` |
| Setup wizard: 6 steps | 7 steps |
| Settings: 23 buttons replaced by 5 categories | the same 23 sections under 5 headings |
| File Manager: 10-category rail | 15 categories (+ a Quarantine button whose key is unknown → error) |
| Tests use temp directories | two suites import `css_app` bound to the live project; others write `~/.percival_local_journal.db`, `project_path`, `~/.percival_vault_config.json` |

## Status claims ("Fully Implemented / Verified: YES") that the code does not support

- **Transfer engine**: per-file copy real; verification happened after `os.replace` (a mismatch deleted
  the destination); engine object rebuilt per request (pause/cancel/active never work); only 5 of 13
  states ever set; no queue/worker; resume unreachable; clone path unverified; dotfiles skipped then the
  move deleted the source tree.
- **Transfer Center UI**: throws on first render (`round()` undefined); poll checks `window.V` (never set);
  no queue reordering; Resume/Discard buttons have no handlers.
- **File Manager**: browse/reconcile/register work; copy/move/rename/delete UI disabled or unbound;
  server endpoints existed with almost no path protection.
- **Sync Center**: preview compares size only; category toggles not read; auto-triggers stored, never
  acted on; `execute_sync` copied any client-supplied path; "Sync Now" crashes on `round()`.
- **Safe eject**: safety check reads a table nothing writes (always READY); `eject_vault` never consulted
  it; force unmount had no server-side confirmation.
- **Pensieve**: hard-coded DB path (5 other modules expect other locations); FK-failing inserts swallowed;
  candidate IDs never match; duplicate annotations; journal replay drops missed lesions.
- **ALBUS / LUMOS / NOX / CORE**: heuristic scorers over feature dicts with hard-coded defaults; no
  NIfTI, no Hessian, no trained LUMOS weights (random init reported `status="ok"`). The real image
  pipeline is `scripts/run_css.sh` → `detect_css.py`. The diagram "ALBUS → LUMOS → NOX → CORE → SCORE →
  Pensieve" is not the production path.
- **Scientific integrity**: `percival_gui.score_study` (commit `84dafdd`) overwrote the trained Percival
  Score with `None` whenever CORE returned nothing, then scored the study with zero accepted candidates
  (an unassessable study recorded as score 0).

## Test isolation incident (2026-11-23)

Running the suite exactly as the handover instructs (12:33) wrote to the live project. Evidence and the
backup are in `PHASE0_SAFETY_PLAN.md` §2. No study data, Pensieve DB, patients.json or MRI was touched.
