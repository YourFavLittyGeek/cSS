# Feature preservation matrix

Every capability of the pre-redesign GUI (commit 7e0f5d7) → where it lives now. Retired = nothing retired: every capability below is kept.
The backend API (`/api/...`) is unchanged; every action calls the same endpoint as before.

| # | Capability (before: where) | API | After: where |
|---|---|---|---|
| 1 | Setup check, 9 items + Install dcm2niix / pywebview / licence fixes (Home) | /api/preflight, /api/fix | Settings → System (full list + fix buttons); a banner on Studies when any item fails |
| 2 | Pipeline version, install from zip, roll back (Home) | /api/install, /api/rollback | Settings → System |
| 3 | Queue summary + links (Home) | /api/state | Studies overview strip + Activity |
| 4 | Add patients: single / batch, folder choose / scan, folder-is code / name, code rule, store names, series table, T1 / SWI choice, pathway check, grades sheet + template, cohort, anatomy, mode, results folder, summary, start | /api/scan, /api/grades, /api/grades_template.xlsx, /api/queue, /api/pick | Add studies → "From image folders" (same flow, new layout) |
| 5 | Bring in studies from another project (Processing) | /api/proc/scan_source, /api/proc/link | Add studies → "From another project" |
| 6 | Production-model status card (Processing) | /api/proc/models | Add studies → "From another project" (after bringing in) and study panel → Technical |
| 7 | Queue parallel setting + recommendation + "why" (Patients) | /api/settings, /api/state | Activity → "Run N at the same time" + Capacity |
| 8 | Memory / CPU / disk bar, zones, "Stop newest patient" (Patients) | /api/state, /api/control requeue | Activity → Capacity (auto-opens with a warning in the danger zone) |
| 9 | Pathway-change notes + OK / OK to all (Patients pill) | /api/control accept / pathway | Activity → Needs attention (decision rows) |
| 10 | Per-patient Pause / Resume / Stop / Retry / Remove / Re-run with pathway dialog / "!" pathway change / misregistration retry choice + help | /api/control | Activity rows + study panel (same dialogs, same confirmations incl. recon-all) |
| 11 | Retry all failed | /api/retry_failed | Activity header |
| 12 | Edit name, rename code before processing (Patients) | /api/edit | Study panel → header (name, code ✎ while waiting) |
| 13 | Hide names, cohort filter (Patients, Results) | — | Studies toolbar |
| 14 | QC snapshot window (Patients) | /qc | Study panel → Summary → "QC image" |
| 15 | Log viewer + copy (top bar) | /api/log | Study panel → Log; Activity → Details |
| 16 | Results table: candidates, reviewed / cSS, reader score, AI score, radiologist grade, version, agreement | /api/results | Studies list columns + study panel Summary; agreement line under the list |
| 17 | Review cohort, Update AI scores, Open Excel, Share ▾ (xlsx / csv / docx / pdf / package, with warning) | /api/review, /api/ai_scores, /api/open_results, /api/export, /api/share | Studies toolbar: Review, Export ▾ (same formats, same warning); "Update AI scores" in the Export menu |
| 18 | Review launcher with reviewer name, reviewer settings | /api/review, /api/vset | Review section (+ Review button on Studies / study panel) |
| 19 | Blind read: existing packet / new packet | /api/packets, /api/blind | Review section |
| 20 | Processing Manager: study list, MRI identity, per-stage compatibility, confirm earlier outputs, options (new detection run / from stage / reuse / full re-run), history, make active, resume, details + log | /api/proc/* | Study panel → Processing + Technical |
| 21 | Interrupted / rolled-back notices (Processing) | /api/proc/studies | Activity → Needs attention + notifications |
| 22 | Unified workflow steps 0–8 + test protocol | /api/u/*, /api/sel/* | Model section (unchanged content, restyled) |
| 23 | Notification bell, curtain, remove / snooze, settings | /api/notif/* | Top bar bell (unchanged) + Settings → Notifications |
| 24 | Awake toggle | /api/settings | Activity header ("Keep Mac awake while processing") + Settings → General |
| 25 | Theme toggle | /api/settings | Top bar (unchanged) + Settings → General |
| 26 | Settings: FreeSurfer folder / licence / threads, SynthSeg fallback, re-run mode, retry mode, reviewer settings, backup / export folders, features, quit | /api/settings, /api/quit | Settings → General (folders, features, quit) / Processing (FreeSurfer, threads, fallback, re-run, retry) |
| 27 | Version in Settings | /api/state | Settings → System |
