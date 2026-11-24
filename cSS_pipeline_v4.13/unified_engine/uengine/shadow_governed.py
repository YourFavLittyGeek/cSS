"""shadow_governed.py - SHADOW · Experimental Discovery Lab, governed workflow (architecture integration).

Replaces the evidence path of the old Shadow Lab trials (fixed formulas on a random cohort, one trial scored with the true label, no
patient separation). The old trials stay available only as labelled SYNTHETIC demonstrations.

  data          ONLY eligible expert ground truth of DEVELOPMENT patients (from the PERCIVAL dataset; locked-test patients are refused)
  split         one locked discovery / confirmation split of the development patients (salted SHA-256 of the patient id; a patient never
                changes side; stored in <store>/shadow/discovery_split.json). SHADOW sees discovery patients only.
  hypothesis    registered BEFORE any experiment: target component, kind, variable(s), rationale (<store>/shadow/hypotheses/HNNN.json)
  discovery     SHADOW: patient-grouped cross-validation on discovery patients - baseline (the active NOX measurement set) vs baseline + the
                proposed measurement; out-of-fold AUC / log loss, paired patient bootstrap CI of the difference. The label is used only to fit
                inside training folds and to score held-out folds (never as an input); label-like variables are refused.
  confirmation  PERCIVAL (independent, once per hypothesis): both models fitted on ALL discovery patients, evaluated on the confirmation
                patients SHADOW never saw; effect size, CI, failure cases. A second confirmation run is refused (no tuning on it).
  approval      a named person (never SHADOW / PERCIVAL / an automated actor), typed phrase, reason; only after a passed confirmation (or an
                explicit override with reason). Approval creates a new component version (component_registry) - previous version kept
                for rollback. Synthetic evidence is stamped and can never be presented as a validated improvement.
Implemented kinds: 'nox_measurement' (add a recorded quantitative measurement to NOX). Other kinds can be registered; their experiments
are reported as not implemented (never as passed)."""
import hashlib
import json
import os
import time

import numpy as np

SALT = "percival-shadow-discovery-v1"
CONFIRM_FRACTION = 0.4
KINDS = ("nox_measurement", "albus_rule", "lumos_pattern", "interaction")
IMPLEMENTED = ("nox_measurement",)
FORBIDDEN = ("y", "label", "call", "expert", "cand_id", "study", "patient", "percival_score", "score_model", "rank_model", "reviewer",
             "adjudicat", "consensus", "gt_", "truth")
LAMBDA = 1.0


class ShadowError(ValueError):
    pass


def _dir(store, *a): return os.path.join(store, "shadow", *a)


def _js(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".tmp", "w") as f: json.dump(obj, f, indent=1, sort_keys=True, default=str); f.flush(); os.fsync(f.fileno())
    os.replace(p + ".tmp", p)


def _jl(p, d=None):
    try:
        with open(p) as f: return json.load(f)
    except Exception: return d


def _side(patient, fraction):
    return "confirmation" if int(hashlib.sha256((SALT + str(patient)).encode()).hexdigest()[:8], 16) / 0xFFFFFFFF < fraction else "discovery"


def split_of(store, patients):
    """the locked discovery / confirmation split; new development patients are added by the rule and recorded"""
    p = _dir(store, "discovery_split.json"); S = _jl(p) or dict(schema="shadow-split/1.0", salt=SALT, confirmation_fraction=CONFIRM_FRACTION,
                                                                 created=time.strftime("%Y-%m-%d %H:%M:%S"), assignment={}, additions=[])
    changed = False
    for q in sorted({str(x) for x in patients if x}):
        if q not in S["assignment"]:
            S["assignment"][q] = _side(q, S["confirmation_fraction"]); S["additions"].append(dict(patient=q, side=S["assignment"][q])); changed = True
    if changed or not os.path.exists(p): _js(p, S)
    return S


def _check_rows(rows):
    if not rows: raise ShadowError("no eligible development examples")
    bad = [r for r in rows if r.get("partition") != "development"]
    if bad: raise ShadowError(f"refused: {len(bad)} example(s) outside the development partition (locked-test patients are never available to SHADOW)")
    nopat = [r for r in rows if not r.get("patient")]
    if nopat: raise ShadowError(f"refused: {len(nopat)} example(s) without a patient identity")
    if any(r.get("y") not in (0, 1) for r in rows): raise ShadowError("refused: every example needs an eligible expert label (0/1)")


def register(store, target_component, kind, variables, rationale, created_by="SHADOW"):
    if kind not in KINDS: raise ShadowError(f"unknown kind {kind}")
    if target_component not in ("ALBUS", "NOX", "LUMOS"): raise ShadowError("target must be ALBUS, NOX or LUMOS")
    variables = [str(v) for v in (variables or [])]
    for v in variables:
        if any(t in v.lower() for t in FORBIDDEN): raise ShadowError(f"refused: '{v}' is a label, identifier or model output - not a measurement")
    if not str(rationale or "").strip(): raise ShadowError("a rationale is required")
    d = _dir(store, "hypotheses"); os.makedirs(d, exist_ok=True)
    hid = f"H{len([f for f in os.listdir(d) if f.endswith('.json')]) + 1:03d}"
    H = dict(id=hid, target_component=target_component, kind=kind, variables=variables, rationale=str(rationale).strip(), created_by=created_by,
             created=time.strftime("%Y-%m-%d %H:%M:%S"), status="registered", implemented=kind in IMPLEMENTED)
    _js(os.path.join(d, f"{hid}.json"), H); return H


def load(store, hid):
    H = _jl(_dir(store, "hypotheses", f"{hid}.json"))
    if not H: raise ShadowError(f"unknown hypothesis {hid}")
    return H


def listing(store):
    d = _dir(store, "hypotheses")
    return [_jl(os.path.join(d, f)) for f in sorted(os.listdir(d)) if f.endswith(".json")] if os.path.isdir(d) else []


def _X(rows, cols):
    return np.array([[np.nan if r["features"].get(c) is None else float(r["features"][c]) for c in cols] for r in rows], float)


def _fit_pred(Xtr, ytr, Xte):
    from uengine.ml_component import PenalizedLogistic
    m = PenalizedLogistic(columns=[f"c{i}" for i in range(Xtr.shape[1])], class_weight="balanced").fit(Xtr, ytr, LAMBDA)
    return m.predict(Xte)


def _logloss(y, p): p = np.clip(p, 1e-6, 1 - 1e-6); return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def _paired_boot(y, pa, pb, g, metric, n=500, seed=0):
    rng = np.random.default_rng(seed); u = np.unique(g); out = []
    idx = {q: np.where(g == q)[0] for q in u}
    for _ in range(n):
        s = np.concatenate([idx[q] for q in rng.choice(u, len(u))])
        a, b = metric(y[s], pa[s]), metric(y[s], pb[s])
        if a is not None and b is not None: out.append(b - a)
    return [float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))] if len(out) >= 50 else None


def _compare(y, pa, pb, g, seed):
    from uengine.percival.meta import auc
    da = None if auc(y, pa) is None or auc(y, pb) is None else auc(y, pb) - auc(y, pa)
    return dict(baseline=dict(auc=auc(y, pa), log_loss=_logloss(y, pa)), extended=dict(auc=auc(y, pb), log_loss=_logloss(y, pb)),
                delta_auc=da, delta_auc_ci=_paired_boot(y, pa, pb, g, auc, seed=seed),
                delta_log_loss=_logloss(y, pb) - _logloss(y, pa), n=int(len(y)), n_patients=int(len(np.unique(g))), n_css=int(y.sum()))


def _prepare(store, H, rows, baseline_features):
    _check_rows(rows)
    S = split_of(store, [r["patient"] for r in rows])
    for r in rows: r["_side"] = S["assignment"][str(r["patient"])]
    disc = [r for r in rows if r["_side"] == "discovery"]; conf = [r for r in rows if r["_side"] == "confirmation"]
    if set(r["patient"] for r in disc) & set(r["patient"] for r in conf): raise ShadowError("patient in both discovery and confirmation")
    return S, disc, conf, list(baseline_features), list(baseline_features) + [v for v in H["variables"] if v not in baseline_features]


def run_discovery(store, hid, rows, baseline_features, synthetic=False, seed=0, k=5):
    """SHADOW: experiment on discovery patients only. rows: dict(study, cand_id, patient, partition, y, features {name: value})"""
    H = load(store, hid)
    if not H["implemented"]: H.update(status="not_implemented", note=f"experiments for kind '{H['kind']}' are not implemented"); _js(_dir(store, "hypotheses", f"{hid}.json"), H); return H
    if H.get("discovery"): raise ShadowError(f"{hid}: discovery already recorded (register a new hypothesis to change it)")
    from uengine.percival.meta import folds
    S, disc, conf, base_cols, ext_cols = _prepare(store, H, rows, baseline_features)
    y = np.array([r["y"] for r in disc], float); g = np.array([str(r["patient"]) for r in disc])
    if len(np.unique(g)) < 3 or min(y.sum(), (1 - y).sum()) < 3: raise ShadowError("too few discovery patients / labels for a cross-validated experiment")
    Xa, Xb = _X(disc, base_cols), _X(disc, ext_cols); pa, pb = np.full(len(y), np.nan), np.full(len(y), np.nan)
    for tr, te in folds(g, k, seed):
        if len(np.unique(y[tr])) < 2: continue
        pa[te] = _fit_pred(Xa[tr], y[tr], Xa[te]); pb[te] = _fit_pred(Xb[tr], y[tr], Xb[te])
    ok = np.isfinite(pa) & np.isfinite(pb)
    R = _compare(y[ok], pa[ok], pb[ok], g[ok], seed)
    flags = []
    if R["extended"]["auc"] is not None and R["extended"]["auc"] >= 0.999: flags.append("near-perfect separation: check the variable for label leakage before any confirmation")
    cover = float(np.mean([r["features"].get(v) is not None for r in disc for v in H["variables"]])) if H["variables"] else 0.0
    H["discovery"] = dict(by="SHADOW", at=time.strftime("%Y-%m-%d %H:%M:%S"), seed=seed, folds=k, baseline_features=base_cols, extended_features=ext_cols,
                          patients=sorted(set(g.tolist())), n_confirmation_patients_reserved=len({r["patient"] for r in conf}), result=R, flags=flags,
                          variable_coverage=round(cover, 3), synthetic=bool(synthetic),
                          data_hash=hashlib.sha256(json.dumps(sorted((r["study"], str(r["cand_id"]), r["y"]) for r in disc)).encode()).hexdigest()[:16],
                          evidence_note="SYNTHETIC data - infrastructure test, not a discovery" if synthetic else "development patients (discovery side)")
    H["status"] = "discovery_done"; _js(_dir(store, "hypotheses", f"{hid}.json"), H); return H


def confirm(store, hid, rows, actor="PERCIVAL", seed=0, min_patients=3):
    """PERCIVAL: independent evaluation on the confirmation patients (once). Passed iff the lower CI of the AUC gain is > 0."""
    if actor != "PERCIVAL": raise ShadowError("refused: confirmation is performed by PERCIVAL, not by the proposer")
    H = load(store, hid)
    if not H.get("discovery"): raise ShadowError(f"{hid}: no discovery result to confirm")
    if H.get("confirmation"): raise ShadowError(f"{hid}: already confirmed once - repeated confirmation is refused (no tuning on confirmation data)")
    D = H["discovery"]; S, disc, conf, _, _ = _prepare(store, H, rows, D["baseline_features"])
    leak = set(D["patients"]) & {str(r["patient"]) for r in conf}
    if leak: raise ShadowError(f"refused: {len(leak)} confirmation patient(s) were used in discovery")
    yd = np.array([r["y"] for r in disc], float); yc = np.array([r["y"] for r in conf], float); gc = np.array([str(r["patient"]) for r in conf])
    if len(np.unique(gc)) < min_patients or min(yc.sum(), (1 - yc).sum()) < 1:
        R = dict(status="insufficient_confirmation_data", n=int(len(yc)), n_patients=int(len(np.unique(gc))))
        H["confirmation"] = dict(by="PERCIVAL", at=time.strftime("%Y-%m-%d %H:%M:%S"), result=R, passed=False,
                                 reason="too few confirmation patients / classes - the proposal cannot be validated yet")
        H["status"] = "confirmation_insufficient"; _js(_dir(store, "hypotheses", f"{hid}.json"), H); return H
    pa = _fit_pred(_X(disc, D["baseline_features"]), yd, _X(conf, D["baseline_features"]))
    pb = _fit_pred(_X(disc, D["extended_features"]), yd, _X(conf, D["extended_features"]))
    R = _compare(yc, pa, pb, gc, seed)
    err = np.abs(pb - yc) - np.abs(pa - yc)
    fails = [dict(study=conf[i]["study"], cand_id=conf[i]["cand_id"], y=int(yc[i]), baseline_p=round(float(pa[i]), 3), extended_p=round(float(pb[i]), 3))
             for i in np.argsort(-err)[:5] if err[i] > 0]
    passed = R["delta_auc_ci"] is not None and R["delta_auc_ci"][0] > 0
    H["confirmation"] = dict(by="PERCIVAL", at=time.strftime("%Y-%m-%d %H:%M:%S"), result=R, passed=bool(passed), failure_cases=fails,
                             rule="passed iff the lower 95 % bound of the paired patient-bootstrap AUC gain on confirmation patients is > 0",
                             patients=sorted(set(gc.tolist())), synthetic=D["synthetic"])
    H["status"] = "confirmed" if passed else "not_confirmed"; _js(_dir(store, "hypotheses", f"{hid}.json"), H); return H


def approve(store, hid, by, reason, confirm_phrase, override=False, allow_synthetic=False):
    """human approval -> a new version of the target component (component_registry). Never automatic."""
    from uengine.percival import component_registry as CR
    H = load(store, hid)
    C = H.get("confirmation") or {}
    if not C: raise ShadowError(f"{hid}: not confirmed by PERCIVAL yet")
    if not C.get("passed") and not override: raise ShadowError(f"{hid}: PERCIVAL confirmation did not pass - approval needs override=True and a reason")
    if H["discovery"].get("synthetic") and not allow_synthetic: raise ShadowError("refused: synthetic evidence cannot change a component")
    cur = CR.active(store, H["target_component"]); cfg = dict(cur.get("config") or {})
    if H["kind"] == "nox_measurement":
        cfg["feature_set"] = list(cfg.get("feature_set") or []) + [v for v in H["variables"] if v not in (cfg.get("feature_set") or [])]
    V = CR.approve(store, H["target_component"], cfg, by, reason, confirm_phrase,
                   evidence=dict(hypothesis=hid, discovery=H["discovery"]["result"], confirmation=C.get("result"), override=bool(override and not C.get("passed"))),
                   synthetic=H["discovery"].get("synthetic"))
    H.update(status="approved", approved=dict(by=V["by"], at=V["created"], version=V["version"], override=bool(override and not C.get("passed"))))
    _js(_dir(store, "hypotheses", f"{hid}.json"), H); return H, V
