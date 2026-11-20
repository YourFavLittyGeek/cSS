# INTEGRATION_REPORT.md - Unified Score engine in the experimental Unified GUI (Percival), SHADOW MODE

## 1. Environment (verified 2026-11-20)

| item | value |
|---|---|
| repository | `/Users/tarabeah.selim/Projects/cSS` (remote `origin` = YourFavLittyGeek/cSS); its checkout stays on `claude/css-detection-audit-2esnbb` @ `7936c16`, untouched |
| experimental Unified GUI | branch `origin/experimental/unified-gui` @ `6f0ca44` (Percival v5.14.2-rc5); no local checkout existed; the installed copy `~/cSS_experimental` is hash-identical to it and was not modified |
| development worktree | `/Users/tarabeah.selim/Projects/cSS-unified-score-ml` |
| branch | `feature/unified-score-ml-integration` (from `6f0ca44`, `--no-track`: no upstream, nothing pushed) |
| framework | Python stdlib `http.server` back end (`app/css_app.py`, 127.0.0.1 only, POST needs header `X-CSS-App: 1`), single-page HTML/JS front end (`app/css_app.html`, `unified_view.js`), optional pywebview window; Mac launcher `app/mac*`; write guard `app/guard` (`CSS_EXPERIMENTAL=1`) |
| entry point | `python app/css_app.py [--port N] [--no-window]`, data root `$CSS_BASE` (default `~/css_project` - never used in this work) |
| existing Unified Score | `unified_score/uscore` (x1-x5, "Model" screen, `/api/u/*`) - unchanged |

## 2. What was integrated (diff against 6f0ca44)

| file | change |
|---|---|
| `app/css_app.py` | +1 default setting `features.shadow_engine=False`; GET `/shadow_view.js`, GET `/api/se/*`, POST `/api/se/*` (dispatch functions `shadow_get` / `shadow_post`, each wrapped in try/except); after a patient is done and its results are saved: `shadow_engine_gui.after_done(code, SET)` in try/except (runs only when switched on) |
| `app/css_app.html` | nav entry "Shadow ML" (Research group), its title, a guarded render branch (`typeof shadowView`), `<script src="/shadow_view.js">`; optional URL hash (`#shadow`, `#shadow:SYN01`) - without a hash the app opens on Studies as before |
| `app/shadow_engine_gui.py` (new) | back end; runs `unified_engine/run_engine.py` in a subprocess (timeout 180 s); never imports the engine; deterministic fallback read with the csv module |
| `app/shadow_view.js` (new) | the screen |
| `unified_engine/` (new) | engine, CLI, synthetic demo model, tests, tools |
| `tests/check_app_shadow_engine.py` (new) | end-to-end test |

No detector, rule, threshold, scoring, model, export or reader file was changed. `git diff 6f0ca44 -- scripts/ unified_score/` is empty.

## 3. The screen (Research > Shadow ML)

- Permanent **SHADOW MODE** banner; **SYNTHETIC DEMO BASE** banner when the base carries the marker.
- Model pill: name, version, data_kind, health; a "Models not used" card lists unhealthy models with the reason.
- Switch "Run after each finished study" (default **Off**); "Run all finished studies"; per-study Run / Open.
- Study table: shadow run status and time, ML applied / withheld, Unified category counts, "Existing outputs unchanged ✓ verified".
- Study detail with the three outputs **always separate**: (1) existing deterministic 0-4 score and per-candidate score_v4 / tier / rule,
  (2) experimental ML increment, (3) experimental Unified p with 5-95 % interval and category; missing / invalid indicators and quality
  flags; the two largest learned corrections to MATH; click a row for the full trace (formula, model hash, values used, statuses,
  contributions, JSON).
- Fallback view: if no shadow result exists or the engine failed, the existing deterministic values straight from the detector lists.

## 4. Shadow-mode guarantees and how they are verified

| guarantee | mechanism | verified by |
|---|---|---|
| existing outputs never change | engine reads only; writes only `unified_engine/shadow/ID.json`; re-hashes inputs | check_app_shadow_engine: review/ byte-identical, study records unchanged, after runs and after a crash; engine records `original_outputs_unchanged` |
| ML cannot change scoring / decisions | no write path into lists, calls, scores, results; nothing reads shadow output except the screen | code review of the diff (section 2); tests above |
| app survives engine failure | subprocess + timeout; try/except around every hook and route | test: `CSS_ENGINE_FAIL=1` -> job failed, deterministic rows served, app keeps serving |
| every experimental value identifies its model and status | trace (model hash, versions, formula); header (engine, model, data_kind, shadow_mode, experimental) | tests: every candidate carries model hash / version / formula |
| synthetic model never used for a real study | registry apply policy + synthetic marker + SYN prefix | test: non-synthetic study -> ML withheld with reason |
| bad models are never used | health: hash, schema, detector, engine version, data_kind consistency | unit tests + app test with a corrupt configured model |

## 5. Launch commands

```zsh
# synthetic demonstration (safe: a SYNTHETIC base in a scratch folder; never ~/css_project)
cd /Users/tarabeah.selim/Projects/cSS-unified-score-ml/cSS_pipeline_v4.13 && conda activate css
python unified_engine/run_engine.py demo-base /tmp/uengine_demo_base --n 6
CSS_BASE=/tmp/uengine_demo_base CSS_EXPERIMENTAL=1 PYTHONPATH=app/guard python app/css_app.py --port 8820
# then open http://127.0.0.1:8820/#shadow  (or #shadow:SYN02)
```
Do not point `CSS_BASE` at a real project for this branch without a separate decision; on a real base the screen works but ML is withheld.

## 6. Screenshots
`docs/unified_engine/screenshots/`: `shadow_overview.png`, `shadow_study_SYN01.png` (ML applied), `shadow_fallback_TST01.png` (non-synthetic
study: deterministic fallback) - produced by `tests/check_app_shadow_engine.py --shots DIR` with headless Chrome on a synthetic base.
