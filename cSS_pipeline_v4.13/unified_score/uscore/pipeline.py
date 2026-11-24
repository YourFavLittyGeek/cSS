"""pipeline.py - study loading, per-candidate extraction, development training, scoring, reports.
Reads production outputs READ-ONLY from $CSS_BASE; writes only under <base>/uscore/ (or --out). Never touches review/, work/, data/.

Steps (run_unified.py is the CLI):
  extract  every included study (development AND held-out): features, decomposition, detectors, perturbation rows. No labels.
  train    development studies only; labels through LabelAccess(mode='development'); nested LOPO; final model frozen + hashed.
  score    frozen model on any included study: probability (if justified), decision, per-candidate reports. No labels.
  heldout  held-out labels, only with the frozen model file and its hash (LabelAccess mode 'heldout_evaluation')."""
import os, json, glob
import numpy as np
from scipy import ndimage as ndi
from .common import (Cohort, LabelAccess, PREDICTORS, registration_state, versions, sha256_file, CohortError, MODEL_VERSION)
from . import features as fe, detectors as dt, perturb as pt, decision as dc, model as md

MARGIN_MM = 20.0


def _load(p):
    import nibabel as nib
    return nib.load(p) if os.path.exists(p) else None


def load_study(base, sid):
    import nibabel as nib, pandas as pd
    S = dict(sid=sid)
    lab = _load(f"{base}/review/{sid}_candidates.nii.gz")
    swi = _load(f"{base}/data/{sid}_swi.nii") or _load(f"{base}/data/{sid}_swi.nii.gz")
    if lab is None or swi is None: raise FileNotFoundError(f"{sid}: candidates or SWI missing")
    S["lab"] = np.asarray(lab.dataobj).astype(np.int32); S["img"] = swi.get_fdata(dtype=np.float32)
    S["vox"] = tuple(float(v) for v in swi.header.get_zooms()[:3]); S["brain"] = S["img"] != 0
    S["cand_table"] = pd.read_csv(f"{base}/review/{sid}_candidates.csv")
    v = _load(f"{base}/work/{sid}_vessels.nii.gz"); S["ves"] = None if v is None else np.asarray(v.dataobj) > 0
    p = _load(f"{base}/work/{sid}_pial_sd.nii.gz"); S["psd"] = None if p is None else p.get_fdata(dtype=np.float32)
    S["raw"] = None; S["raw_note"] = "no unmasked SWI in raw/"
    for f in sorted(glob.glob(f"{base}/raw/{sid}/SWI/*.nii*")):
        r = nib.load(f)
        if r.shape[:3] != S["img"].shape: continue
        a = r.get_fdata(dtype=np.float32); a = a[..., 0] if a.ndim == 4 else a
        m = S["brain"]; cc = np.corrcoef(a[m][::50], S["img"][m][::50])[0, 1] if m.any() else 0
        if cc > 0.95: S["raw"], S["raw_note"] = a, f"{os.path.basename(f)} (r={cc:.3f} inside the brain)"; break
        S["raw_note"] = f"raw SWI found but not the same image as data/ (r={cc:.2f})"
    try: S["qc"] = json.load(open(f"{base}/review/{sid}_qc.json"))
    except Exception: S["qc"] = {}
    S["reg"] = registration_state(S["qc"])
    S["input_hash"] = sha256_file(f"{base}/review/{sid}_candidates.nii.gz")[:16] + ":" + (
        sha256_file(f"{base}/data/{sid}_swi.nii", 1 << 22)[:16] if os.path.exists(f"{base}/data/{sid}_swi.nii") else "gz")
    return S


def crop(S, cid):
    m = S["lab"] == cid; P = np.argwhere(m)
    mg = np.ceil(MARGIN_MM / np.array(S["vox"])).astype(int)
    lo = np.maximum(P.min(0) - mg, 0); hi = np.minimum(P.max(0) + mg + 1, m.shape); sl = tuple(slice(a, b) for a, b in zip(lo, hi))
    g = lambda a: None if a is None else a[sl]
    edge = np.zeros(m[sl].shape, bool); edge[[0, -1]] = edge[:, [0, -1]] = edge[:, :, [0, -1]] = True
    return dict(cand=m[sl], img=S["img"][sl], raw=g(S["raw"]), ves=g(S["ves"]), psd=g(S["psd"]), brain=S["brain"][sl], edge=edge,
                origin=lo.tolist())


def _lite(F): return {k: (v if k == "_meta" else dict(value=v["value"], unit=v["unit"], status=v["status"], reasons=v["reasons"], extra=v["extra"]))
                      for k, v in F.items()}


def _clean(v):
    """NaN / numpy scalars -> JSON-safe values (NaN is not valid JSON and breaks the app's pages)"""
    try:
        if v is None: return None
        if isinstance(v, (float, np.floating)) and not np.isfinite(v): return None
        if isinstance(v, np.generic): return v.item()
    except Exception: pass
    return v


def candidate_record(S, cid, do_perturb=True):
    C = crop(S, cid)
    F, D = fe.extract(C["cand"], C["img"], S["vox"], raw=C["raw"], ves=C["ves"], psd=C["psd"], brain=C["brain"], reg=S["reg"], crop_edge=C["edge"])
    stab, rows = (pt.stability(C["cand"], C["img"], S["vox"], C["raw"], C["ves"], C["psd"], C["brain"], S["reg"], C["edge"], F, D)
                  if do_perturb else (None, []))
    det = dt.run_all(F, D, C["cand"], C["ves"], C["raw"], C["brain"], S["vox"], stab)
    row = S["cand_table"].set_index("cand_id").loc[cid].to_dict() if cid in set(S["cand_table"].cand_id) else {}
    flags = dc.protective_flags(F, D, det, stab, S["reg"], row)
    return dict(study=S["sid"], cand_id=int(cid), F=_lite(F), detectors=det, stability=stab, perturbation_rows=rows,
                protective_flags_pre=flags, registration=S["reg"], raw_note=S["raw_note"], input_hash=S["input_hash"],
                v510_confidence_pct=_clean(row.get("confidence_pct")), cand_row={k: _clean(row.get(k)) for k in ("infra_frac", "infratentorial", "near_ich_suggest", "region")},
                voxel_mm=list(S["vox"]), versions=versions())


def extract_study(base, sid, cohort, out, do_perturb=True, application=False):
    """application=True (the app, any patient): features only, for display; the study is NOT added to any cohort, labels are
    never read, and train() / reports use manifest roles only. Otherwise refuses non-M / excluded / unknown studies."""
    if application:
        try: role = cohort.role(sid)
        except CohortError: role = "application (not in the study cohort)"
    else: role = cohort.role(sid)
    S = load_study(base, sid)
    ids = [int(i) for i in S["cand_table"].cand_id] if len(S["cand_table"]) else []
    recs = [candidate_record(S, i, do_perturb) for i in ids if (S["lab"] == i).any()]
    os.makedirs(f"{out}/features", exist_ok=True)
    json.dump(dict(study=sid, role=role, n=len(recs), registration=S["reg"], raw_note=S["raw_note"], records=recs),
              open(f"{out}/features/{sid}.json", "w"), default=_np)
    return recs


def _np(o):
    if isinstance(o, (np.integer,)): return int(o)
    if isinstance(o, (np.floating,)): return float(o)
    if isinstance(o, np.ndarray): return o.tolist()
    if isinstance(o, (np.bool_,)): return bool(o)
    return str(o)


def load_records(out, sids):
    R = []
    for s in sids:
        p = f"{out}/features/{s}.json"
        if not os.path.exists(p): raise FileNotFoundError(f"features of {s} not extracted ({p})")
        R += json.load(open(p))["records"]
    return R


def _jl_gate(base):
    p = os.path.join(base, "app_data", "split", "gate.json")
    if not os.path.exists(p): return None                        # no gate configured yet: legacy behaviour (open)
    try: return json.load(open(p))
    except Exception: return dict(open=False, by="unreadable gate file")


def _label_fingerprints(base, studies):
    """sha256 of each training study's shared calls file at training time (the app compares it later: 'calls changed after training')"""
    import hashlib
    out = {}
    for s in studies:
        p = os.path.join(base, "review", f"{s}_calls.csv")
        out[s] = hashlib.sha256(open(p, "rb").read()).hexdigest() if os.path.exists(p) else None
    return out


TRAINING_DISABLED = ("uScore training is DISABLED: this experimental prototype learns from the derived shared ID_calls.csv without the "
                     "Phase 3A/3B safeguards (expert roles, completed-review consensus, label provenance / blinding) and splits by study, "
                     "not by patient. Primary training: Percival (Training Center). Synthetic research only: run_unified.py train --research-unverified")


class TrainingDisabled(PermissionError):
    pass


def train(base, cohort, out, labels_access=None, research_unverified=False):
    """development only. Returns the model dict (frozen) and the development report dict.
    Phase 3D review: refused unless research_unverified=True (explicit synthetic / research run); such models are stamped unverified."""
    if not research_unverified: raise TrainingDisabled(TRAINING_DISABLED)
    gate = _jl_gate(base)                                       # v5.14.2-rc4: the user's training gate (app_data/split/gate.json)
    if gate is not None and not gate.get("open"):
        raise CohortError(f"training gate is CLOSED (closed {gate.get('at', '')} by {gate.get('by', '?')}) - open it in the app (Unified > Study selection)")
    dev = cohort.studies("development"); cohort.check_fit_set(dev)
    LA = labels_access or LabelAccess(cohort, base, mode="development", log_dir=out)
    if LA.mode != "development": raise CohortError("training accepts only a development-mode label boundary")
    import pandas as pd
    rows, y, pid, warn = [], [], [], []
    for s in dev:
        recs = load_records(out, [s])
        tab = pd.read_csv(f"{base}/review/{s}_candidates.csv")
        lab, w = LA.labels(s, tab)
        if w: warn.append(w)
        for r in recs:
            if r["cand_id"] in lab: rows.append(r); y.append(lab[r["cand_id"]]); pid.append(s)
    y = np.array(y, float); pid = np.array(pid)
    if len(rows) < 10 or y.sum() < 3: raise ValueError(f"too few labelled development candidates ({len(rows)}, {int(y.sum())} cSS)")
    log = []; preds = md.choose_predictors(y, log)
    p_raw, p_cal, folds = md.nested_lopo(rows, y, pid, preds)
    ok = np.isfinite(p_cal)
    stab = md.stability_report(folds, preds)
    slope, inter = md.calib_slope(y[ok], p_cal[ok]) if ok.sum() > 5 else (None, None)
    a_cal = md.auc(y[ok], p_cal[ok]); a_raw = md.auc(y[ok], p_raw[ok])
    v510 = np.array([np.nan if r.get("v510_confidence_pct") in (None, "") else float(r["v510_confidence_pct"]) for r in rows])
    vok = ok & np.isfinite(v510)
    prob_ok = bool(stab.get("min_sign_agreement") is not None and stab["min_sign_agreement"] >= 0.8 and slope is not None and 0.7 <= slope <= 1.3)
    cut = md.ordering_threshold(y[ok], p_cal[ok] if prob_ok else p_raw[ok])
    lam_all, z_all = md.inner_lopo(rows, y, pid, preds); zz = np.isfinite(z_all)
    final = md.fit(rows, y, preds, lam_all); final.platt = md.platt_fit(z_all[zz], y[zz])
    rep = dict(n_candidates=len(rows), n_cSS=int(y.sum()), n_patients=len(set(pid)), predictors=preds, fallback_log=log,
               outer_auc_calibrated=a_cal, outer_auc_raw=a_raw,
               outer_auc_ci=md.bootstrap_ci(y[ok], p_cal[ok], pid[ok], md.auc),
               outer_brier=float(np.mean((p_cal[ok] - y[ok]) ** 2)), outer_brier_ci=md.bootstrap_ci(y[ok], p_cal[ok], pid[ok], lambda a, b: float(np.mean((b - a) ** 2))),
               calibration_slope=slope, calibration_intercept=inter, reliability_bins=_bins(y[ok], p_cal[ok]),
               coefficient_stability=stab, folds=folds, probability_output=prob_ok, ordering_cut=cut,
               v510_auc_same_candidates=md.auc(y[vok], v510[vok]) if vok.sum() else None,
               v510_note="v5.10 was fitted on the M02-M11 calls (part of the development set): its AUC here is IN-SAMPLE (optimistic), the unified score's is out-of-fold",
               penalty_at_grid_boundary=bool(any(f['lam'] in (md.LAMBDAS[0], md.LAMBDAS[-1]) for f in folds)),
               label_warnings=warn, feature_missingness=_missing(rows), estimate_type="CROSS-VALIDATION (nested leave-one-patient-out on the development patients; every prediction out-of-fold)")
    rep.update(_operating(y[ok], (p_cal if prob_ok else p_raw)[ok], pid[ok], cut))
    M = final.to_json(train_studies=dev, ordering_cut=cut, probability_output=prob_ok, cohort_manifest_sha=cohort.manifest_sha,
                      synthetic_test=cohort.synthetic, development_report_summary=dict(auc=a_cal, slope=slope),
                      split_version=getattr(cohort, "split_version", None), label_fingerprints=_label_fingerprints(base, dev))
    M["frozen"] = False                    # v5.14-gui: training never freezes; freeze() is a separate, confirmed step
    M.update(research_only_unverified=True, label_provenance="derived ID_calls.csv - NOT Phase 3A ground truth (no roles / consensus / provenance checks; study-level split)")
    M["model_hash"] = md.model_hash(M)     # the stamp is model content: covered by the hash checked at the held-out boundary
    os.makedirs(out, exist_ok=True)
    json.dump(M, open(f"{out}/model_trained.json", "w"), indent=1)
    json.dump(dict(oof=[dict(study=r["study"], cand_id=r["cand_id"], y=int(t), p_raw=float(a), p_cal=float(b)) for r, t, a, b in zip(rows, y, p_raw, p_cal) if np.isfinite(b)],
                   **rep), open(f"{out}/development_report.json", "w"), indent=1, default=_np)
    return M, rep


def freeze(out, confirm):
    """Freezes the trained model (model_trained.json -> model_frozen.json, frozen=True). confirm must be the text 'FREEZE'."""
    if confirm != "FREEZE": raise ValueError("freeze refused: confirmation text must be FREEZE")
    p = f"{out}/model_trained.json"
    if not os.path.exists(p): raise FileNotFoundError("no trained model: run train first")
    M = json.load(open(p))
    if M.get("synthetic_test") is None: raise ValueError("model has no cohort mode")
    import datetime as _dt
    M["frozen"] = True; M["frozen_at"] = _dt.datetime.now().isoformat(timespec="seconds")
    json.dump(M, open(f"{out}/model_frozen.json", "w"), indent=1)
    return dict(model_hash=M["model_hash"], frozen_at=M["frozen_at"], synthetic_test=M["synthetic_test"])


from .common import HELDOUT_STATEMENT, heldout_authorization      # kept importable from here (GUI, tests)


def _bins(y, p, k=5):
    q = np.quantile(p, np.linspace(0, 1, k + 1)); out = []
    for a, b in zip(q[:-1], q[1:]):
        m = (p >= a) & (p <= b)
        if m.any(): out.append(dict(p_mean=float(p[m].mean()), observed=float(y[m].mean()), n=int(m.sum())))
    return out


def _missing(rows):
    return {k: {s: float(np.mean([r["F"][k]["status"] == s for r in rows])) for s in ("reliable", "unreliable", "unavailable")} for k in PREDICTORS}


def _operating(y, p, pid, cut):
    if cut is None: return {}
    pr = p >= cut; tp = int((pr & (y == 1)).sum()); fn = int((~pr & (y == 1)).sum()); fp = int((pr & (y == 0)).sum()); tn = int((~pr & (y == 0)).sum())
    pats = sorted(set(pid)); pos_p = [q for q in pats if y[pid == q].max() == 1]
    det_p = [q for q in pos_p if (pr & (y == 1) & (pid == q)).any()]
    return dict(candidate_sensitivity=tp / max(tp + fn, 1), candidate_specificity=tn / max(tn + fp, 1), tp=tp, fn=fn, fp=fp, tn=tn,
                fp_per_patient=fp / max(len(pats), 1), patient_sensitivity=len(det_p) / max(len(pos_p), 1), cSS_positive_patients=len(pos_p),
                note="operating point = ordering cut (prioritisation only; nothing is suppressed)")


def score(cohort, out, sids, model_path=None):
    M = json.load(open(model_path or f"{out}/model_frozen.json"))
    if not M.get("frozen"): raise ValueError("model is not frozen")
    if M.get("synthetic_test") != cohort.synthetic: raise CohortError("model / cohort mode mismatch (synthetic test vs real)")
    m = md.Fitted.from_json(M); cut = M["ordering_cut"]; prob_ok = M["probability_output"]
    reports = []
    for s in sids:
        cohort.role(s)
        for r in load_records(out, [s]):
            praw = float(m.p_raw([r])[0]); pcal = float(m.p_cal([r])[0]) if m.platt else None
            p = pcal if prob_ok else praw
            stab = r["stability"]
            if stab is not None and r["perturbation_rows"]:
                sc = [float((m.p_cal if prob_ok else m.p_raw)([dict(F={**r["F"], **pr["F"]})])[0]) for pr in r["perturbation_rows"]]
                stab = dict(stab, score_range=[min(sc + [p]), max(sc + [p])])
                if stab["score_range"][1] - stab["score_range"][0] > 0.2: stab["unstable"] = True
            dec = _decide_from_record(r, stab, p, cut)
            dc.propose_suppression(s, r["cand_id"], dec, p, r["detectors"], r["F"], M["model_hash"], r["input_hash"], f"{out}/suppression_audit.jsonl")
            reports.append(candidate_report(r, m, M, praw, pcal, prob_ok, stab, dec))
    os.makedirs(f"{out}/reports", exist_ok=True)
    json.dump(reports, open(f"{out}/reports/candidates.json", "w"), indent=1, default=_np)
    return reports


def _decide_from_record(r, stab, p, cut):
    """decision from the stored record; protective flags recomputed with the score-level stability."""
    fl = list(r["protective_flags_pre"])
    if stab and stab.get("unstable") and "unstable under perturbation" not in fl: fl.append("unstable under perturbation")
    return dc.categorise(r["F"], fl, r["detectors"], p, cut)


def candidate_report(r, m, M, praw, pcal, prob_ok, stab, dec):
    con = m.contributions(r)
    pos = [f"{k}: +{v['contribution']:.2f} log-odds" for k, v in con.items() if not v["imputed"] and v["contribution"] > 0.05]
    neg = [f"{k}: {v['contribution']:.2f} log-odds" for k, v in con.items() if not v["imputed"] and v["contribution"] < -0.05]
    miss = [f"{k}: {r['F'][k]['status']} ({'; '.join(r['F'][k]['reasons'])}) - no evidence either way" for k, v in con.items() if v["imputed"]]
    return dict(study=r["study"], cand_id=r["cand_id"],
                probability=pcal if prob_ok else None, raw_score=praw,
                score_note=None if prob_ok else "calibration / coefficient stability not adequate: raw score and feature profile only, NOT a probability",
                predictors={k: dict(value=r["F"][k]["value"], unit=r["F"][k]["unit"], status=r["F"][k]["status"], reasons=r["F"][k]["reasons"]) for k in PREDICTORS},
                contributions=con, positive_evidence=pos, negative_evidence=neg, missing_or_unreliable=miss,
                alternative_detectors=[dict(detector=d["detector"], status=d["status"], support=d["support"], against=d["against"],
                                            unresolved=d["unresolved"], reliability=d["reliability"]) for d in r["detectors"]],
                stability=stab, category=dec["category"], category_reasons=dec["reasons"], protective_flags=dec["protective_flags"],
                v510_confidence_pct=r.get("v510_confidence_pct"), decomposition=r["F"]["_meta"], registration=r["registration"],
                model_version=M["model_version"], model_hash=M["model_hash"], feature_version=r["F"]["_meta"]["feature_version"],
                synthetic_test=M.get("synthetic_test", False),
                disclaimer="EXPERIMENTAL research output; not a diagnosis; the dark core is an experimental representation, not ground truth")


def score_application(base, sid, cohort, out, model_path=None):
    """App step for ONE patient: extract (application mode) + categories. With a frozen real model: score as in score();
    without one: detectors + protective rules only (no probability). Writes out/reports/<sid>.json. Never reads labels."""
    recs = extract_study(base, sid, cohort, out, application=True)
    mp = model_path or f"{out}/model_frozen.json"
    M = json.load(open(mp)) if os.path.exists(mp) else None
    if M and (not M.get("frozen") or bool(M.get("synthetic_test")) != bool(cohort.synthetic)): M = None   # never mix synthetic and real
    m = md.Fitted.from_json(M) if M else None
    reps = []
    for r in recs:
        if m:
            praw = float(m.p_raw([r])[0]); pcal = float(m.p_cal([r])[0]) if m.platt else None
            p = pcal if M["probability_output"] else praw; cut = M["ordering_cut"]
        else: praw = pcal = p = cut = None
        dec = _decide_from_record(r, r["stability"], p, cut)
        if m:
            dc.propose_suppression(sid, r["cand_id"], dec, p, r["detectors"], r["F"], M["model_hash"], r["input_hash"], f"{out}/suppression_audit.jsonl")
            reps.append(candidate_report(r, m, M, praw, pcal, M["probability_output"], r["stability"], dec))
        else:
            reps.append(dict(study=sid, cand_id=r["cand_id"], probability=None, raw_score=None,
                             score_note="no fitted unified model yet (run 'train' on the development studies): detectors and feature profile only",
                             predictors={k: dict(value=r["F"][k]["value"], unit=r["F"][k]["unit"], status=r["F"][k]["status"], reasons=r["F"][k]["reasons"]) for k in PREDICTORS},
                             alternative_detectors=[dict(detector=d["detector"], status=d["status"], support=d["support"], against=d["against"],
                                                         unresolved=d["unresolved"]) for d in r["detectors"]],
                             stability=r["stability"], category=dec["category"], category_reasons=dec["reasons"], protective_flags=dec["protective_flags"],
                             registration=r["registration"], model_version=None, feature_version=r["F"]["_meta"]["feature_version"],
                             disclaimer="EXPERIMENTAL research output; not a diagnosis"))
    os.makedirs(f"{out}/reports", exist_ok=True)
    json.dump(dict(study=sid, model_hash=M["model_hash"] if M else None, reports=reps), open(f"{out}/reports/{sid}.json", "w"), indent=1, default=_np)
    cnt = {c: sum(r["category"] == c for r in reps) for c in ("css_compatible", "uncertain", "alternative_high_confidence")}
    return dict(study=sid, n=len(reps), model=bool(M), **cnt)


def evaluate_heldout(base, cohort, out, frozen_hash):
    """Held-out evaluation with the frozen model. Opens held-out labels ONLY here, after the hash check."""
    import pandas as pd
    LA = LabelAccess(                      # authorization, recomputed hash and model integrity are enforced inside LabelAccess
cohort, base, mode="heldout_evaluation", frozen_model=f"{out}/model_frozen.json", frozen_hash=frozen_hash, log_dir=out)
    M = json.load(open(f"{out}/model_frozen.json")); m = md.Fitted.from_json(M); prob_ok = M["probability_output"]
    y, p, pid = [], [], []
    for s in cohort.studies("held-out"):
        if not os.path.exists(f"{out}/features/{s}.json"): continue
        lab, _ = LA.labels(s, pd.read_csv(f"{base}/review/{s}_candidates.csv"))
        for r in load_records(out, [s]):
            if r["cand_id"] in lab:
                y.append(lab[r["cand_id"]]); pid.append(s); p.append(float((m.p_cal if prob_ok else m.p_raw)([r])[0]))
    y, p, pid = np.array(y, float), np.array(p), np.array(pid)
    rep = dict(estimate_type="INDEPENDENT HELD-OUT (frozen model)", n=len(y), n_cSS=int(y.sum()), patients=len(set(pid)),
               auc=md.auc(y, p), auc_ci=md.bootstrap_ci(y, p, pid, md.auc) if len(y) else None,
               brier=float(np.mean((p - y) ** 2)) if len(y) else None, model_hash=M["model_hash"])
    if len(y) > 5: rep["calibration_slope"], rep["calibration_intercept"] = md.calib_slope(y, p)
    rep.update(_operating(y, p, pid, M["ordering_cut"]))
    json.dump(rep, open(f"{out}/heldout_report.json", "w"), indent=1, default=_np)
    try:                                                         # v5.14.2-rc4: these test studies are now "spent" for this model
        import datetime as _dt
        sp = os.path.join(base, "app_data", "split", "spent.json"); os.makedirs(os.path.dirname(sp), exist_ok=True)
        d = json.load(open(sp)) if os.path.exists(sp) else {}
        for s_ in cohort.studies("held-out"): d.setdefault(s_, []).append(dict(model_hash=frozen_hash, at=_dt.datetime.now().isoformat(timespec="seconds")))
        json.dump(d, open(sp, "w"), indent=1)
    except Exception: pass
    return rep
