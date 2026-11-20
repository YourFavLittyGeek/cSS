# UX audit — Percival experimental app (before the redesign, commit 7e0f5d7)

**Inspected in the running app:** synthetic demo project, both themes, 1440 px. Screenshots are in `before/`.
**Code paths traced:** `app/css_app.html` (shell and views), `app/unified_view.js` (Unified tab), `app/css_app.py` (HTTP API → pipeline, Processing Manager, notifications, study selection).

## 1. Current information architecture
Top bar: **8 tabs** (Home · Add patients · Patients · Processing · Results · Review / Blind read · Unified (experimental) · Settings), plus the bell, awake toggle, theme toggle and "Show log".

| Tab | What it really is | Problems found |
|---|---|---|
| Home | setup check (9 rows), pipeline install / rollback, a queue summary that only links to other tabs | A one-off system check takes the whole first screen; it tells nothing about the studies. Install / rollback is a rare maintenance task on the main screen |
| Add patients | DICOM folder import (single / batch, series choice, codes, cohort, grades sheet, pathway) → summary → start | Works, but is called "patients" here and "studies" elsewhere. Importing from another project lives in a different tab (Processing) |
| Patients | the processing queue: parallel setting, memory bar, counts, per-patient pathway / status / Log / QC / Retry / Stop / Pause / Re-run / Review | A process manager, a capacity monitor and a study list in one table; 4–6 buttons per row; memory internals on the main path |
| Processing | Processing Manager: studies on disk, compatibility per stage, new detection run, history, make active, resume, bring-in | The same studies as Patients and Results under a third name; technical identity (sha256, voxel size, orientation) shown first; history buried at the bottom |
| Results | scores per study, reader vs AI vs radiologist, export / share / Excel / AI-score refresh / review cohort | A third list of the same studies; actions in a dropdown |
| Review / Blind read | reviewer launcher (tick studies) + blind-read packets | Duplicates "Review" from Patients and "Review cohort" from Results |
| Unified (experimental) | 9-step model workflow + test protocol | Fine for its expert audience, but 9 equal cards look like a developer pipeline |
| Settings | FreeSurfer, pathway behaviour, re-run, reviewer, retry, folders, notifications, features, quit, version | One long page that mixes everyday preferences with advanced processing policy |

## 2. Main problems
1. **One study, four screens.** A study's status (Patients), outputs (Results), processing history (Processing) and review (Review) are split across tabs that each re-list every study. Answering "what is the state of M05?" means visiting three tabs.
2. **No overview.** Nothing answers at a glance: how many studies, how many done, which need attention, is anything running.
3. **Process management is scattered.** Processing appears in three places that never show together:
   - the pipeline queue (Patients);
   - Processing-Manager runs (Processing tab);
   - model jobs (Unified tab).
4. **Developer terminology on the main path:** pathway names (SynthSeg, coreg_masked, SynthMorph), "anatomy / align / detect / qc", "adopt", "compatible with limitations", sha256 hashes, memory zones.
5. **Too many buttons per row** (Log, !, QC ↗, Pause, Stop, Retry, Remove, Re-run, Review). The primary action isn't distinguished.
6. **Visual noise:** every section is a bordered card; pills, tags and coloured counters compete; tables are dense; the top bar is crowded with 8 tabs plus 5 controls.
7. **Rare tasks are prominent:** setup check, version install / rollback and capacity internals sit on main screens.
8. **Inconsistent names:** patient / study / case; Results / Review / Review cohort; Processing / Patients queue.
9. **Errors** arrive as raw messages (e.g. "registration_ok false: label shift 3.9 mm") without a plain-language next step in the same place.

## 3. Essential but poorly presented
- **Study state and next action** (exists, scattered).
- **Running work with real progress:**
  - pipeline step k of 5 is real;
  - the time left is an estimate from earlier runs, labelled ≈;
  - unified jobs report real progress fractions.
- **Failure handling:** misregistration retry choice, pathway change, retry all, requeue under memory pressure.
- **Processing history with restore** (make active, resume).
- **Export with the clinical-data warning.**

## 4. Can be grouped, moved or hidden
- Setup check → shown only when something is wrong (banner); full list under Settings → System.
- Install / rollback, version → Settings → System.
- Memory bar, parallel limit, "why N" → "Capacity" inside Activity (collapsed when normal), with a warning banner in the danger zone.
- Technical study identity, per-stage compatibility → the study's "Technical" section.
- Pathway names → shown as "Anatomy method" in the study's Processing section and in advanced dialogs.

## 5. Processing defects found
None. No processing defect was found during the audit. The UI-level bugs fixed earlier (scroll jumps, reviewer top bar) were already resolved in rc4.
