# IMPLEMENTATION_LOG.md - Unified Score ML engine integration (2026-11-20)

## 1. Location and history
- Worktree `/Users/tarabeah.selim/Projects/cSS-unified-score-ml`, branch `feature/unified-score-ml-integration`, created with
  `git worktree add --no-track -b feature/unified-score-ml-integration <path> origin/experimental/unified-gui` (base `6f0ca44`).
- Local commits only (author `Claude <noreply@anthropic.com>` passed per command, as in the repository's history; git config not changed;
  nothing pushed, merged, tagged or deployed). See the commit list at the end of the handover / `git log 6f0ca44..`.
- Note: the message of commit 2 (`bac5db9`) lists the hash route and test counts written before counting; the hash route is in commit 1
  (`faea197`), and the verified counts are in TEST_REPORT.md (119 engine tests, 35 / 36 integration checks).

## 2. Development cycle (inspect -> design -> implement -> test -> debug -> regress)
1. **Inspect**: worktree created; app architecture read (stdlib HTTP server, single-page front end, `/api/u/*` unified tab, `queue_unified`
   after-done hook, write guard, existing test pattern with temporary HOME and SYN base).
2. **Design**: engine as a separate package run in a SUBPROCESS (same isolation the app already uses for uscore); new screen in the Research
   group; shadow results in their own folder; deterministic fallback without importing the engine.
3. **Port** the tested workspace framework + prototype (`~/cSS_ml_work/src/cssml`, 112 tests passing there) to `unified_engine/uengine`;
   provenance rewritten to execute the repository's own `scripts/detect_css.py` / `css_tiers.py` with pinned sha256 (no snapshot copy).
4. **New**: `registry.py` (load / version / health / policy / never overwrite), `shadow.py` (runner, fallback, input re-hash), `demo_base.py`
   (synthetic base, marker, no labels), `train_demo.py` + bundled synthetic model, `run_engine.py` CLI, `app/shadow_engine_gui.py`,
   `app/shadow_view.js`, minimal `css_app.py` / `css_app.html` edits.
5. **Test / debug**: 7 failures found and fixed (TEST_REPORT.md section 4), incl. diagnosing the patients.json byte change to the
   unchanged app with control runs.
6. **Regress**: engine runner (0 failing stages), port fidelity (identical to the workspace), the app's existing suite (TEST_REPORT.md §3).

## 3. Files created
`app/shadow_engine_gui.py`, `app/shadow_view.js`, `tests/check_app_shadow_engine.py`,
`unified_engine/run_engine.py`, `unified_engine/run_tests.sh`, `unified_engine/models/synthetic_demo_offset_v1.0.0.json`,
`unified_engine/uengine/{__init__, provenance, registry, shadow, demo_base, train_demo}.py` (new) and the ported
`{feature_schema, math_component, characteristics_component, ml_component, calibration, model_evaluation, patient_split, data_validation,
synthetic, funnel, experiment, auc_investigation, unified_fusion, reporting, ablation}.py`, `uengine/prototype/{__init__, inputs,
components, fusion, patient}.py`, `unified_engine/tests/` (19 test files + `_common.py`, `_proto_fixtures.py`, `pinned_blocks.json`),
`unified_engine/tools/{static_check, make_feature_schema_md}.py`, `docs/unified_engine/*.md` (9 documents) + `screenshots/` (3 PNG).

## 4. Files modified
`app/css_app.py` (+33 lines: setting, routes, guarded hook, dispatch functions), `app/css_app.html` (nav entry, title, guarded render
branch, script tag, optional hash route). Nothing else; `git diff 6f0ca44 -- cSS_pipeline_v4.13/scripts cSS_pipeline_v4.13/unified_score`
is empty.

## 5. Changes to ported code (relative to the workspace)
- `provenance.py`: repository paths, `verify_sources()` against pinned sha256 (replaces the snapshot check).
- `prototype/inputs.sanitize(..., require_synthetic=True)`: the synthetic requirement stays mandatory for fitting and ML prediction; the
  shadow runner uses `require_synthetic=False` ONLY for the deterministic display path.
- `math_component.patient_score`: reads score_css.py's `multifocality_0_4` key.
- version strings `uengine/1.0`, `uengine-fusion/1.0`.

## 6. Protection evidence
- Original checkout `~/Projects/cSS`: still `claude/css-detection-audit-2esnbb` @ `7936c16`, working tree unchanged (only the untracked
  `.DS_Store` from before). `~/cSS_experimental` and `~/css_project` never written: the app tests run with the write guard listing them as
  protected and assert unchanged modification times of their review folders; your running Percival app (port 8810) was never contacted.
- No clinical file opened: every base used was a synthetic temporary folder; the only reads of real folders were file modification times.
