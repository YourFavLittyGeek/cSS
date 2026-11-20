# Production models in RC3: code paths, restoration, remaining differences

Authorization: restore the two existing production models only. No training, no recalibration, no change to coefficients, thresholds or formulas, no change to the unified model.

## 1. How the two models act in production (traced in the code)
### `review/confidence_model.json` (v5.10 confidence model, fitted earlier by `fit_confidence.py`)
- **Loading** (`detect_css.py`, around l. 1242):
  - `css_confidence.load()` accepts only schema `css-confidence/1.0` with exactly the code's 31-feature list. Otherwise: "confidence model ignored" and no confidence at all.
  - **Every** candidate and excluded object then gets `confidence_pct` (0–100, sigmoid × 100 of the model's linear score, **not a validated probability**) and `confidence_why` (the domains that lower or raise it).
- **Rule E30** (only with `CSS_CONF=1`, which the production app sets):
  - an object the other rules keep is excluded when `confidence_pct` < the model's own `cut_pct`;
  - this happens only if the model's `cut_method` is `lopo_min` (or `CSS_CONF_ALLOW_OPTIMISTIC=1`);
  - side guard: E30 alone may never empty a hemisphere; the highest-confidence object is kept (`conf_guard = 1`).
- **Manifest:** the study's role for the model (development / evaluation) is written to it.
- **Effect:** decides which candidates are **shown vs excluded**, and therefore the list, the reviewer, the meter's green band and the AI score.

### `review/ranker_model.json` (v5.0 trained ranking model, fitted earlier by `train_ranker.py`)
- **When it runs:** only `run_css.sh` step [3c] runs `rank_candidates.py`, and only when the file exists **and** the study's split in `labels/study_meta.csv` is `dev`. Test-split and unassigned studies are not ranked. `redetect.py` never ranks.
- **Checks in `rank_candidates.py`:**
  - refuses studies the model was trained on;
  - warns (refuses only with `CSS_QC_STRICT=1`) if the labels changed since the fit or the detector build differs;
  - missing features are filled with the training median.
- **Output:** columns `score_model` (0–1, not calibrated) and `rank_model` are appended to the candidate list. Nothing is excluded and `cand_id` is unchanged.
- **Reviewer:** `ai_opinion()` uses `score_model` as the meter base **instead of** css_evidence / (css + vein evidence) when present. It therefore changes the meter colour, the green band and the AI score 0–4.

## 2. What RC3 does
| Step | Behaviour |
|---|---|
| Import (each time studies are brought in) | both files copied from `~/css_project/review/` to `~/cSS_experimental/review/`, byte-for-byte: temporary copy → sha256 equal to the source → atomic rename. The source is re-checked unchanged (sha256 + modification time). A record with both sha256s goes to `review/production_models.json` |
| Existing different copy (production model changed later) | never overwritten: reported as **CONFLICT**, parity false |
| Compatibility check | **Confidence model:** the same `css_confidence.load()` check detection uses (schema + feature list); E30 applicability from `cut_method`. **Ranking model:** structure (features / mean / sd / weights / bias / impute_median present and the same length); training studies and detector builds reported |
| Each detection run | the run log and the run record name each model's state: verified copy and compatible, or **PRODUCTION PARITY NOT MET** with the reason |
| Detection | `detect_css.py` unchanged; with the model file present and `CSS_CONF=1` (already set), confidence_pct and E30 behave exactly as in production |
| Ranking | reproduces `run_css.sh` [3c]: only if the model file exists **and** the study's production split (read at import from `labels/study_meta.csv`; only the split value is used, recorded in `runs/<ID>/import.json`) is `dev`; same messages; incompatible model → not applied, logged |
| Surface features | condition aligned with `run_css.sh` [3b] (`lh.pial` + `orig.mgz` + `swi2t1.lta`). rc2 checked only `lh.pial` + `lta` |
| Processing tab | card "Production models in this project": verified copy / compatible / not present / parity not met |

## 3. Evidence (synthetic; `tests/check_production_models.py`)
- Byte-for-byte copy; source and destination sha256 recorded and equal.
- Production files (models, labels, every file) unchanged in content and modification time.
- **Parity:** the same synthetic studies were detected two ways: the production way (scripts run directly in a copy of the production project, plus `rank_candidates.py` for the dev study, as `run_css.sh` does), and through the RC3 app. Results:
  - candidate lists identical (all 157–159 columns);
  - excluded objects identical, with identical rule ids;
  - E30 exercised in both (one low-confidence object excluded);
  - dev study ranked, test study not.
- Missing models → "not present / parity not met"; a changed feature list or inconsistent weights → **INCOMPATIBLE**; a changed production model → **CONFLICT**. None of these is ever reported as parity.

## 4. Remaining differences between production and RC3
1. **Build stamp:**
   - The experimental manifest records the experimental build, not your production build.
   - If your ranking model lists `detector_builds`, `rank_candidates.py` prints its stale-build *warning* ("detected with build …"), exactly as production does for any build mismatch.
   - It still ranks (production behaviour without `CSS_QC_STRICT`).
   - The detector code itself is identical to `3bbfa14`.
2. **Split snapshot:** the study's split is read once, at import. A later change in production `labels/study_meta.csv` is not seen until the study is imported again.
3. **Model snapshot:** models are copied at import. A later production refit shows as CONFLICT on the next import and is not adopted silently.
4. **Studies added directly in the experimental project** (Add patients there) use the experimental project's own `labels/study_meta.csv`, which is absent unless you create it, so they are not ranked. That is the same rule production applies to studies without a split.
5. **Stages that are reused, not re-run, in a Processing-tab run:** import, skull-strip / masking, anatomy, registration, alignment. Production `run_css.sh` re-runs them on a full re-run. This is by design (FreeSurfer reuse).
6. **Unified score:** a Processing-tab run always runs the unified step; production runs it only when the opt-in feature is on. It has no model and changes no detector output.
7. **`score_css.py`:** the one-line display fix (unchanged scoring).
8. **Not verified:** parity on your real models and studies, and models with `detector_builds` / `label_file` set. Real-data verification needs your Mac.
