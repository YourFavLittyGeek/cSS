# Redesign plan — Percival experimental app

**Principle:** simple by default, powerful when needed. One place per study, one place for all running work, everything rare behind Settings or "Details".
**Scope:** only the GUI (`app/css_app.html`, `app/unified_view.js`), plus one read-only aggregation helper in `app/css_app.py`. No pipeline, detector, threshold, model, feature, default or file-format change.

## New information architecture
Left sidebar (always visible, icon + label), replacing the 8-tab top bar:

| Section | Purpose | Replaces |
|---|---|---|
| **Studies** (start screen) | Project overview + the one study list with plain-language status; click a study → **study panel** | Home, Patients (list), Results, Processing (list) |
| **Add studies** | Import from DICOM / NIfTI folders, or bring in already-processed studies from another project | Add patients + Processing "bring in" |
| **Activity** | The Process Manager: everything running, waiting, needing attention, recently finished (pipeline queue, new detection runs, model jobs) + capacity | Patients (queue part), Processing (runs), Unified job boxes |
| **Review** | Open the reviewer (validation read or AI visible) and blind reads | Review / Blind read, "Review cohort" |
| **Model** | The experimental unified score workflow (study selection, training, validation, freeze, …) — expert area | Unified (experimental) |
| **Settings** | General · Processing (advanced) · Notifications · System (setup check, version, install / rollback) | Settings, Home setup check, Home version box |

The top bar keeps only: project name, the notification bell, theme, and the log (moved to "Details" in Activity and the study panel).

## Study status vocabulary (one plain label per study)
| Label | Underlying state |
|---|---|
| **Not processed** | on disk / imported, no candidates |
| **Waiting** | queued |
| **Processing** · step k of 5 (Importing images / Brain anatomy / Aligning labels / Detecting candidates / Quality check) | running / starting / paused |
| **Needs your decision** | pathway decision |
| **Needs attention** · plain reason | failed / stopped / processing-run failed / interrupted |
| **Ready for review** | done, not read |
| **Review in progress** | some calls |
| **Reviewed** | reader score saved |

## Study panel (right sheet, opened from the list)
- **Header:** code, cohort, status, primary action (Review / Retry / Start processing / Resume).
- **Summary:** candidates, reader score, AI score ("not validated"), radiologist grade, QC grade, warnings in plain language.
- **Processing:**
  - anatomy method (pathway) with change / re-run;
  - new detection run (reuses anatomy);
  - stop / pause;
  - processing history with make active / resume / details.
- **Technical** (collapsed): MRI identity, per-stage compatibility, earlier-output confirmation.
- **Log** (collapsed).

## Process Manager (Activity)
- **Sections:** Needs attention · Running · Waiting · Finished (last 24 h).
- **One row per process:** what (study + kind: Pipeline / New detection run / Model job), current step in plain words, elapsed time.
  - **Progress bar only where real:** pipeline step fraction; model jobs' own progress.
  - **Estimated time left only from the existing timing model**, labelled "≈ estimate".
- **Actions per row** (only valid ones): Pause, Resume, Stop, Retry, Remove, Resume run, Details (log).
- **Queue:** "Run N at the same time" (existing setting), "Retry all failed".
- **Capacity** (memory, CPU, disk, recommendation) collapsed; auto-expanded with a warning in the danger zone ("Stop newest" kept).

## Simplified workflows
| Task | Before | After |
|---|---|---|
| See a study's state, scores and history | Patients + Results + Processing tabs | Studies → click the row |
| New detection run on an imported study | Processing tab → select study → read the compatibility table → choose option → Start → confirm | Studies → study → "New detection run" → confirm (compatibility shown only if something blocks it) |
| Find what is running / failed | Patients + Processing + Unified | Activity (and a counter in the sidebar) |
| Review a batch | Results → Review cohort, or Review tab → tick | Studies → tick → Review, or Review section |
| Retry a failed study | Patients → find row → choose pathway → Retry | Activity "Needs attention" → Retry (pathway choice in the same dialog as before) |

**Kept on purpose:** confirmations for stopping, recon-all (2–3 h), new detection runs, making an older run active; the clinical-data export warning; the training gate.

## Visual system
- **Tokens:** a neutral grey surface scale, one accent (clinical blue), status colours used only for status.
- **Type:** system font; sizes 12 / 13 / 14 / 16 / 20.
- **Layout:** 8 px spacing grid; separators instead of nested cards; tables with generous rows and no zebra stripes.
- **Buttons:** one primary button per view; secondary actions as quiet buttons or a "More" menu.
- **Themes:** light and dark, from the same tokens.
- **Responsive:** the sidebar collapses to icons below 1100 px; the study panel overlays below 1200 px.
