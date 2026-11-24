# Phase 3A.2 — Server-enforced blinded initial read (+ assessment of the remaining write paths)

Not installed or activated: the live app runs `~/Percival_project/scripts` / `app`, unchanged. Synthetic, isolated tests only.

## Part 1 — Remaining write paths after 3A.1 (assessment; no code changed for these)

| Path | Can modify | Bypasses journal / lock? | Inconsistent state possible | Milestone |
|---|---|---|---|---|
| **`scripts/review_css.py`** (legacy matplotlib reviewer, CLI; not launched by the app) | Expert annotations: writes the reader's calls into the **shared** `review/<ID>_calls.csv` via `css_common.save_calls` (plain `to_csv`; no reviewer name, time, comment); then runs `mark_css.py` (rewrites the candidates' accept column and `ID_score.json`); preview PNG | Yes: no study lock, no journal, not atomic; no read phase (an unblinded, detector-ordered read) | (a) per-reviewer files exist → the ledger ignores the shared file as a source; consumers that read `ID_calls.csv` directly (`score_css`/`mark_css`, `uscore/pipeline.py:133`, `study_split.py:70`, `css_common.load_calls` users) see its calls until the next `materialize` silently replaces them (earlier copy kept in `call_history/`). (b) no per-reviewer file → its calls become the legacy source "(unnamed, before v5.4)": no identity, no provenance, blinding unknown. A run concurrent with the reviewer can interleave with `materialize` | **3A.3** (single writer of reviewer data: route through `review_io` as a named reviewer with read phase "unblinded legacy", or refuse while per-reviewer files exist). Labels it produces are already "blinding unknown" for 3A.4 eligibility (no journal phase) |
| **App op `percival/missed_lesion`** (`app/css_app.py` 1272-1295; no GUI caller, used by `tests/test_pensieve.py`, `tests/test_albus.py`) | Expert annotations: appends a missed-cSS row to the shared `review/<ID>_missed.csv` (after a Pensieve write) | Yes: no lock, no journal (since 3A.1 the change is detected afterwards and recorded as `external_change`) | **Corrupts the file**: different 13-column order (`slice,plane,shape` before `vox_i`), unquoted comment (a comma or newline breaks the row), `missed_id` = epoch seconds, reviewer defaults to "reviewer", no validation of `study_id` (a value with `../` writes outside `review/`). The reviewer's `missed()` then fails (`astype(int)` on missing `can_i`) → the study cannot be opened; `label_summary` would read shifted columns as lesion coordinates. In production today the preceding Pensieve insert normally fails its foreign-key check first (nothing written); with the Vault disconnected the Pensieve write is journaled and the CSV append happens | **3A.3** (first item: the op stops writing - refusal; the two tests adjusted). Recommended to keep it out of any installation until then |
| **Label tools** (`expert_sheet.py`, `expert_import.py`, `label_missed.py`, `consensus.py`, `study_meta.py`) | Expert annotations and derived labels in `labels/` (`candidate_labels.csv`, `missed_lesions.csv`, `consensus.csv`, `adjudication_todo.csv`, `agreement_stats.json`, `study_meta.csv`) and `review/<ID>_expert_<reader>.csv`, `<ID>_expert_key.csv` | Not part of the review journal (separate store); plain `to_csv`, no lock | `append_rows` and `label_missed` **replace** earlier rows with the same study/reader/session key → corrections overwrite history; concurrent runs can lose rows; `expert_import` records unlisted sheet numbers as "N" (defaulted). Not read by the ledger or Percival (which use `call_ledger`), but read by `evaluate.py`, `train_ranker.py`, `classify_surface_patches.py`, `training_gui`, `surface_overlay`, `uengine/funnel.py` → a second, unreconciled ground truth | **Later (3A.5 migration / 3B labels & training)**, before any evaluation or training on `labels/`. Not a blinding path |
| **Read-only ledger path** (`call_ledger.sources/ledger/effective`, used by the app's calls view, review status, Percival `label_summary`, and by `materialize`) | Never writes reviewer files. `materialize` (called after any reviewer's save or a policy change) rewrites the **derived** shared `ID_calls.csv`, `ID_score.json`, `ID_effective.json` | Reads without `review_io` recovery | A damaged reviewer file is silently skipped (`_read` → empty) → Percival labels lose that reviewer without a message, and the next `materialize` rewrites the shared file without their calls (recoverable: reviewer file untouched, previous derived copy in `call_history/`). After a crash, a file one change behind its journal is read as such until a reviewer window repairs it | **3A.3**: read-only verification against the journal in the ledger; `materialize` refuses (keeps the previous derived file) and Percival marks the study "reviewer file needs repair" |

None of these is a path of the browser reviewer, so none blocks 3A.2.

## Part 2 — 3A.2 implementation

New `scripts/review_blind.py`; changes in `scripts/review_web.py`, `scripts/review_web.html`, `app/css_app.py` (one line).

**Read phase from the server.** `initial` until the reviewer's journal holds `initial_completed` (written by the server on a final save in which every shown candidate has a call) and then `unblind` (POST `/api/unblind`, refused with 409 before completion). The page follows `meta.blind`; leaving the validation read during the blind phase asks the server. No browser parameter (`mode`, `read_phase`, `open`, …) and no `--open` flag changes the phase. The app no longer passes `--open`.

**Blinded candidate identifiers.** Per study and reviewer, a random permutation (`secrets.SystemRandom`) of 1..N over the shown candidates and the excluded-audit objects together (so an audit object stays unrecognisable by its number); keyed by candidate fingerprint, stable across sessions and restarts; new objects after a re-detection get ids above the existing ones. The mapping is journaled (`blind_ids` events, hash-chained) and never sent. Requests are translated on the server (unknown id → "unknown candidate", no echo); the label volume is remapped to blinded ids; calls are stored under the original candidate (+ fingerprint) with the blinded id recorded in the journal. An anonymous viewer gets an in-memory mapping and writes nothing.

**Removed during the blind read** (server-side): meter / band / suspicion / reason / source / tier (constant placeholder), confidence and its reason, evidence and score features (only extent and slice count kept), Percival score, AI score (not even computed), call-policy text, import sources (other reviewers' files), other reviewers' missed marks, the detector fate of missed marks, the excluded-object rule, AI parts of `/api/finish` (text, AI score, audit rules, final record whitelist), the browser's meter in the review log and journal, the meter line of the snapshot side-car. Refused (403): `/api/struct3d`, `/api/uscore`, `/api/morph3d`, `/api/import`. Deleting / editing another reviewer's missed mark is refused.

**Route table.** `review_web.ROUTES` classifies every route (static, image, settings, redacted, refused, write); an unlisted route is not served; a test parses the handlers and requires the table to match exactly.

**Errors and logs.** During the blind read an unexpected error returns only "the request could not be completed (reference xxxxxxxx)"; the server log gets the reference, the exception type and the message with every digit masked. Blind-read refusals and storage errors (`RecoveryError`, `LockTimeout`) keep their identifier-free messages.

**Recorded by the server.** Each journaled change carries `read_phase` and `ai_visible` (and `blind_id`); the final record's `read_mode` / `meter_visible` / `read_phase` / `ai_visible` come from the server, not the page.

## Tests

`tests/test_phase3a2_blind.py` (13): route table = handled routes; **every route** called during the blind read (with `--show-excluded`) against sentinel values planted in every AI channel and sentinel original candidate / excluded ids — replies, label-volume values, server log, review log and snapshot side-car searched; refusals 403 / 409 checked; the same routes after a completed read + unblind **must** show the sentinels (proves the search sees each channel); partial final save does not complete; `--open` and browser parameters cannot unblind (journal shows `initial` / not visible / no client meter); phase + blinded id + original id recorded by the server; ids stable per reviewer and extended after re-detection; label volume carries the blinded id at each candidate; ids decorrelated from rank (400 draws, mean r < 0.05); anonymous viewer blind and writes nothing; other reviewers' marks not deletable; internal errors generic, logged without digits; the app no longer launches with `--open`.

Existing checks adapted to the new rule (first read blind): `check_app_unified.py` (see results), `check_review_web.py` (blind assertions for a new reviewer, the anonymous view and `--open`; a test fixture writes the journal events of an earlier completed read for the readers whose second-look behaviour it checks; final read mode now from the server), `check_inherit.py` (confirms the inherited call under its blinded id, from the internal mapping, and checks it is stored under the original candidate), `check_app_percival.py` (Percival hidden in the blind first read, shown in the second look).

Results:
- `test_phase3a2_blind.py`: 13/13; full isolated suite: **325 run, 0 failures, 0 errors, 0 skipped**, live fingerprints changed 0.
- Official `tests/run_tests.sh` (temporary HOME): `ALL TESTS PASSED`, 51 sections, the same single pre-existing SKIP as the baseline.
  (A first run failed my own new assertion "blinded ids 1..N": with `--audit` the audit objects share the shuffled id space - intended -
  so the assertion was corrected to "distinct, within 1..N+M, not the detector ids".)
- `tests/run_uscore_tests.sh` on copies (temporary HOME): unmodified HEAD 14 failing checks; this change the **same 14** (environment:
  headless-Chrome 120 s timeouts and network-blocked re-runs in `check_local_only`). One real regression found in the comparison and fixed:
  `check_app_unified` asked the reviewer for `/api/uscore` without a reviewer name (now a blind request, 403) - adapted (403 in the blind
  read, report in a fixture second look); re-run alone: identical to the baseline (only the pre-existing T4 protocol failure).
- `check_app_percival.py` (adapted) did not reach its viewer section in either run (stops earlier on headless-Chrome timeouts, baseline
  too): **its 3A.2 adaptation is not yet exercised**. `check_viewer.py` (Playwright) is not installed here and was not run; it drives the
  real page and will likely need the same adaptation.
- Mutations: **22/22 caught** (B1-B22: full payload in blind read; AI opinion kept; `--open` bypass; page mode decides; original ids sent; ids in rank order; label volume not remapped; refused routes served; import allowed; browser meter recorded; read mode from the page; unblind without completion; partial save completes; others' marks shown; detector fate shown; error detail returned; others' marks deletable; app launches with `--open`; route missing from the table; snapshot meter kept; finish reply not redacted; calls reply keyed by original ids).

## Limitations / residual risks
- Local files are not confidential: the journal (mapping), review log and calls files hold original ids by design (provenance); a reviewer opening them on disk can see the rank.
- The candidate list itself is detector output; the independent whole-study review (safeguard B) is a separate milestone.
- Pre-filled calls from `inherit_calls.py` or earlier imports are visible during a blind read (they are the reviewer's own file); their provenance treatment is 3A.4.
- 3-D shape views are refused (not redacted) during the blind read; a geometry-only variant could be added later.
- Earlier reviews (before 3A.2) have no read phase: "blinding unknown" (3A.6).

## Part 3 — Main application (completes 3A.2)

New `app/blind_gate.py`; wired in `app/css_app.py`; display in `app/css_app.html`, `app/percival_view.js`; provenance in `scripts/review_blind.py` /
`scripts/review_web.py`.

**Rule (per study, server-side, from the reviewers' journals).** The app has no trustworthy user identity (the reviewer name lives in the
browser), so a study's AI outputs are withheld while it is *pending*: no completed blind initial read, or a blind read in progress (blinded ids
issued / calls made, not completed). *Complete* = at least one completed blind read and none open; a review finished before Phase 3A
(final record without a journal) counts as complete. *Released* = the user released the study's AI results without a blind read
(typed confirmation `RELEASE AI RESULTS` + reason; journaled under the pseudo-reviewer "(app release)"); every later reviewer action on that
study records `ai_released_in_app=true`. Fail-closed: unreadable journal modules or an invalid study key → pending.

**Access paths gated.**
- `GET /api/results` (Studies sheet, study detail, Results view; also the results workbook and `/api/open_results`, both built from it):
  `ai_L/R/total`, `ai_err`, `unified_*` counts removed, `unified_status` → "hidden", the "AI only, not validated" label → "blind review
  pending", plus `ai_hidden` (reason) and `blind_review` (status).
- PERCIVAL Center: `GET /api/percival/score` and `/history` → `hidden` with the reason; `POST /api/percival/score` and `/score_unified` →
  refused (`hidden`).
- New: `GET /api/blind/state?code=`, `POST /api/blind/release`.
- GUI: "hidden until blind review 🔒" in the three places the AI score was shown, a "Release…" control in the study detail (prompt for the
  reason and the typed confirmation), a note in the PERCIVAL explorer.

**Tests.** `tests/test_phase3a2_app_gate.py` (9, in-process app on the isolated project, sentinel AI values): before any blind read every
path withheld (results JSON, Percival score / history, on-demand scoring); workbook masked; normal display after a completed blind read; a
second blind read in progress withholds again; pre-3A finished review = complete; release needs typed confirmation and a reason and is
journaled; release recorded; fail-closed; GUI markers. Plus `test_phase3a2_blind.py::test_a_release_in_the_app_is_recorded_with_the_reviewers_calls`
(end to end through the reviewer server). `check_app_unified.py` adapted (counts withheld before / shown after a fixture blind read; fixture
removed afterwards) - re-run on a copy: identical to the baseline (only the pre-existing T4 failure). `check_app_percival.py` unaffected (its
studies have pre-3A finished reviews); its viewer-page checks now render a fixture second look (not verifiable here: headless Chrome does not
render on this Mac, baseline too).
Mutations G1-G11 all caught (results not masked; Percival score/history not gated; on-demand scoring not gated; blind read in progress
ignored; pre-3A reviews not counted; release without confirmation; without reason; fail-open; release not recorded for the reviewer — also
caught end to end; unified counts left; GUI shows the score anyway). Focused runs: `test_phase0*` 32, `test_phase1e*` 24, `test_phase3a*` 48
— all pass, isolation PASS; GUI JavaScript syntax check passes. The full suite was not re-run (changes confined to the gated paths).

**Remaining limitations (main app).**
- Per study, not per person: after one reader completes, a second reader who has not opened the study yet can see its AI results in the
  app (an opened-but-incomplete read does withhold). Per-reader gating needs reviewer identity / roles (3A.4).
- Not gated: the hidden prototype screens (`/api/u/*` unified candidates, `/api/se/*`, `/api/im/*`, `/api/train/*`; off unless
  `show_prototypes`), the unified "score all" prototype op, Shadow Lab and shadow-run summaries (aggregate agreement only), study file export
  (`/api/xs`, copies result files such as `ID_score_ai.json` / unified reports), and files on disk.
- AI scores are still computed in the background for every study (needed for the later display); only their display is withheld.
- The release control uses browser prompts; GUI rendering is not machine-tested here.
