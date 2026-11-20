# ML_ARCHITECTURE.md - Unified Score engine (shadow mode)

Research software. Not for clinical use. The only model shipped is trained on SYNTHETIC data and is refused for real studies.

## 1. Where it lives

| path | role |
|---|---|
| `unified_engine/uengine/` | the engine package (pure Python: numpy, scipy, pandas) |
| `unified_engine/run_engine.py` | CLI; the app runs it in a subprocess (`shadow`, `models`, `verify`, `demo-base`, `train-synthetic`) |
| `unified_engine/models/synthetic_demo_offset_v1.0.0.json` | bundled SYNTHETIC demo model (+ card) |
| `unified_engine/tests/`, `unified_engine/run_tests.sh`, `unified_engine/tools/` | tests, runner, static check, schema-doc generator |
| `app/shadow_engine_gui.py`, `app/shadow_view.js` | GUI back end (subprocess calls only) and the "Shadow ML" screen |
| `tests/check_app_shadow_engine.py` | end-to-end test through the real app + headless browser |

## 2. Components (each separately importable and replaceable)

```
review/ID_candidates.csv + ID_excluded.csv + ID_qc.json + ID_score.json      (read only)
        │ prototype/inputs.sanitize  - keys, duplicates, corrupt strings / inf -> NaN 'corrupt', hard ranges -> 'out_of_range'
        v
 MATH  prototype/components.MathComponent  ── math_component.py executes the REPOSITORY'S OWN detect_css.py text verbatim
        score_v4 (recorded = authoritative; verbatim re-check), css / vein evidence, E1-E29 fate, review tiers, recorded 0-4
        + 2-parameter monotone recalibration (math logit) - the only learned piece of MATH
 CHARACTERISTICS  prototype/components.CharacteristicsComponent  ── feature_schema.py (157 columns classified, 99 measured)
        10 declared inputs, per-value status, training range (values beyond are clipped + flagged), structural-missing indicator
 PAST EXPERIENCE  prototype/components.IncrementComponent  ── ml_component.PenalizedLogistic (IRLS, L2, offset, nested penalty)
        learned log-odds INCREMENT beyond the math logit, per-feature contributions; alternatives: learned-only, joint, null
 FUSION  prototype/fusion.UnifiedScorer(mode=offset)
        p = sigmoid(math_logit + increment); 30 patient-bootstrap refits -> 5-95 % interval; category; full trace
 REGISTRY  registry.py  ── load, version, card, health (ok / incompatible / corrupt / missing), apply policy
 SHADOW  shadow.py  ── per study: deterministic block always; ML only if the model is healthy AND allowed for the study;
        any failure -> deterministic fallback; writes ONLY unified_engine/shadow/ID.json; re-hashes inputs afterwards
 PATIENT  prototype/patient.py  ── PatientResult (separate type; the recorded 0-4 is carried, never mixed with candidate p)
```

## 3. Reuse decisions (existing models inspected)

| existing component | decision | why |
|---|---|---|
| `detect_css.py` score_v4 / evidence / exclusion_v4, `css_tiers.py` | **reused verbatim** (executed from the repository file; sha256 pinned) | it is the deterministic system; re-implementing it would risk silent drift |
| v5.10 confidence model (`css_confidence.py`, E30) | **not reused as an input**; available as a comparator adapter | fitted on the same reads (circular), 24 of its 30 inputs are MATH inputs, median imputation without missingness indicators, l2 chosen by pooled LOPO AUC; its model file has no `cut_method` |
| v5.2 ranker (`train_ranker.py`) | **not reused**; comparator adapter only | never trained (no expert labels); uses `mimic_score`, a rule output, as a feature |
| unified score (`unified_score/uscore`) | **kept untouched, runs as before**; its procedure is a comparator | its evaluation pooled LOPO predictions -> AUC ~0.25 on pure noise in simulation (prevalence artefact); predictors are image-derived x1-x5, not detector columns; the trained file on the Mac was not used |
| `css_model.fit_lr` | not reused | class-balanced weights distort calibration; the new IRLS supports offsets and per-fold selection |

## 4. Data and privacy boundaries (enforced in code)

- Fitting (`UnifiedScorer.fit`) and ML prediction (`predict`) require `data_kind="synthetic"`, every row `synthetic=True` and SYN identifiers.
- A study counts as synthetic only if its code starts with SYN **and** the base carries `unified_engine/SYNTHETIC_BASE`.
- A model's `data_kind` is part of its hash-protected training record; a card edited to another kind is `incompatible`.
- For real studies the engine computes only the deterministic block (recorded values) and characteristic statuses; ML is `withheld`.
- The engine never imports into the app process; the app's write guard (`CSS_EXPERIMENTAL=1`) covers the subprocess too.
