"""demo_base.py - writes a SYNTHETIC demonstration base laid out like a production $CSS_BASE (tables only), for the GUI demo and the
integration tests. Study codes SYN01..SYNnn; a marker file unified_engine/SYNTHETIC_BASE identifies the base as synthetic.
review/SYNnn_candidates.csv / _excluded.csv carry detector columns ONLY (no label); the synthetic truth is written separately to
unified_engine/demo_truth.csv (never read by the GUI or the shadow runner). Nothing here resembles a patient."""
import json, os, time
import numpy as np
import pandas as pd
from . import feature_schema as fs, synthetic as sy

MARKER = os.path.join("unified_engine", "SYNTHETIC_BASE")
LABEL_COLS = {"y", "y_true", "cls", "fate", "measurement_complete", "rule_id", "obj_index", "synthetic", "_list", "patient_key", "exam_id", "registration",
              "gate_id"}


def is_synthetic_base(base): return os.path.exists(os.path.join(base, MARKER))


def write(base, n_patients=8, seed=900, signal=1.0):
    if os.path.exists(os.path.join(base, "review")) and not is_synthetic_base(base) and os.listdir(os.path.join(base, "review")):
        raise RuntimeError(f"{base} has a non-synthetic review/ folder - refusing to write a demo base into it")
    O, E, P = sy.make_cohort(n_patients, seed=seed, signal=signal, repeat_rate=0.0, reg_fail_rate=0.0)
    for d in ("review", "app_data", "unified_engine"): os.makedirs(os.path.join(base, d), exist_ok=True)
    open(os.path.join(base, MARKER), "w").write("SYNTHETIC demonstration base written by uengine.demo_base - no patient data\n")
    detcols = [c for c in fs.SCHEMA]
    truth, pats = [], []
    exams = sorted(O.exam_id.unique())
    for i, ex in enumerate(exams, 1):
        sid = f"SYN{i:02d}"; g = O[(O.exam_id == ex) & O.fate.isin(["shown", "rule_excluded", "learned_excluded"])].copy()
        sh = g[g.fate == "shown"].sort_values("score_v4", ascending=False).reset_index(drop=True); sh.insert(0, "cand_id", np.arange(1, len(sh) + 1))
        xs = g[g.fate != "shown"].sort_values("score_v4", ascending=False).reset_index(drop=True); xs.insert(0, "excl_id", np.arange(1, len(xs) + 1))
        for lst, d, idc in (("candidates", sh, "cand_id"), ("excluded", xs, "excl_id")):
            cols = [idc] + (["reason"] if lst == "excluded" else []) + [c for c in detcols if c in d.columns and c not in (idc, "cand_id") and c not in LABEL_COLS] + ["rule_version"]
            d[[c for c in dict.fromkeys(cols) if c in d.columns]].to_csv(os.path.join(base, "review", f"{sid}_{lst}.csv"), index=False)
            truth += [dict(study=sid, list=lst, id=int(r[idc]), y_true=int(r.y_true), cls=r.cls) for _, r in d.iterrows()]
        shift = float(E.loc[E.exam_id == ex, "label_shift_mm"].iloc[0])
        json.dump(dict(anatomy="T1", label_shift_mm=shift, registration_ok=shift <= 1.5, status="ok", synthetic=True),
                  open(os.path.join(base, "review", f"{sid}_qc.json"), "w"))
        pr = P[P.patient_key == g.patient_key.iloc[0]].iloc[0]
        json.dump(dict(subject=sid, L_score=int(pr.grade_L), R_score=int(pr.grade_R), multifocality_0_4=int(pr.grade_total), synthetic=True,
                       scoring_method="SYNTHETIC (generator grade, not score_css.py)"), open(os.path.join(base, "review", f"{sid}_score.json"), "w"))
        pats.append(dict(code=sid, status="done", cohort="synthetic", mode="single", anatomy="synthseg", series={}, step="", steps_done={}, tried=[],
                         reg_method="", error="", ai_note="", started=time.time() - 60, finished=time.time() - 30, pathway="synthseg"))
    pd.DataFrame(truth).to_csv(os.path.join(base, "unified_engine", "demo_truth.csv"), index=False)
    pp = os.path.join(base, "app_data", "patients.json")
    old = json.load(open(pp)) if os.path.exists(pp) else []
    json.dump([p for p in old if p.get("code") not in {x["code"] for x in pats}] + pats, open(pp, "w"))
    return [p["code"] for p in pats]
