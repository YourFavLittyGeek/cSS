"""analysis.py - Stage 3 small-data honesty analyses of the PERCIVAL Decision Engine (pure numpy; development cohort only unless stated).

  by_availability        performance by which component inputs were available (missing data are reported, never hidden)
  model_hash             content hash of a trained model (excluding run metadata) -> retraining on the same data is checked against it
  learning_curve         meta-level performance vs number of development patients (does more data still help?)
  subgroup_calibration   calibration by field strength / sequence / anatomy route / QC status; recalibration only RECOMMENDED when the
                         subgroup has the data (never applied automatically)
  abstention_curve       coverage vs accuracy when the most uncertain candidates are sent to 'review required'
  study_agreement        study-level 0-4 multifocality vs expert patient grades: quadratic weighted kappa (patient bootstrap CI),
                         exact agreement, Bland-Altman
  prioritise             second-review priority list (uncertain / disagreeing candidates) - NEVER used for the blind first read
Every function returns JSON-serialisable dicts with an explicit basis / note.
"""
import hashlib
import json

import numpy as np

INDEP = ["math", "unified", "char", "image"]
VOLATILE = ("created", "run_id", "reason", "integrity", "acceptance", "previous_active", "status", "model_hash", "model_hash_basis",
            "reproducibility", "component_versions", "cnn_epochs")
HASHED = ("components", "meta", "meta_ensemble", "calibration", "thresholds", "features", "component_config", "discovery")


def _metrics(y, p, g=None):
    from .meta import metrics
    return metrics(y, p, g)


def by_availability(Z, y, p, g=None, min_n=5):
    """metrics of the calibrated score p per pattern of available component inputs (e.g. 'math+char', 'math+char+image')"""
    y = np.asarray(y, float); p = np.asarray(p, float); n = len(y); g = None if g is None else np.asarray(g)
    pat = np.array(["+".join(c for c in INDEP if np.isfinite(np.asarray(Z[c], float)[i])) or "none" for i in range(n)])
    out = {}
    for k in sorted(set(pat)):
        m = (pat == k) & np.isfinite(p)
        e = _metrics(y[m], p[m], None if g is None else g[m]) if m.sum() >= min_n and len(np.unique(y[m])) == 2 else dict(n=int(m.sum()))
        e["n"] = int(m.sum()); e["n_css"] = int(y[m].sum()); out[k] = e
    return dict(patterns=out, note="performance by which inputs were available; a missing component is never imputed as negative evidence")


def model_hash(M):
    """deterministic content hash of the trained parts of a model (run metadata excluded)"""
    core = {k: M.get(k) for k in HASHED if k in M}
    return hashlib.sha256(json.dumps(core, sort_keys=True, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o)).encode()).hexdigest()[:20]


def reproducibility(M1, M2):
    """compare two models trained on the same dataset -> same hash, or which parts differ (and why it matters)"""
    h1, h2 = model_hash(M1), model_hash(M2)
    diff = [k for k in HASHED if json.dumps(M1.get(k), sort_keys=True, default=str) != json.dumps(M2.get(k), sort_keys=True, default=str)]
    same_data = (M1.get("data") or {}).get("dataset_hash") == (M2.get("data") or {}).get("dataset_hash")
    return dict(identical=h1 == h2, hash_a=h1, hash_b=h2, differing_parts=diff, same_dataset=same_data,
                why=None if h1 == h2 else ("different datasets" if not same_data else "same dataset, different trained parts: " + ", ".join(diff)
                                                                                    + " (seeds, library versions or non-deterministic arithmetic)"))


def learning_curve(Z, y, g, kind, fractions=(0.25, 0.5, 0.75, 1.0), reps=5, seed=0):
    """meta-model AUC by patient-grouped CV on random patient subsets of the development out-of-fold table"""
    from .meta import Meta, folds, auc
    from ..ml_component import sigmoid
    y = np.asarray(y, float); g = np.asarray(g).astype(str); u = np.unique(g); r = np.random.default_rng(seed + 404); pts = []
    for f in fractions:
        k = max(4, int(round(f * len(u)))); vals = []
        if k > len(u): continue
        for rep in range(reps if f < 1.0 else 1):
            sel = set(r.choice(u, k, replace=False)) if f < 1.0 else set(u); m = np.isin(g, list(sel))
            if len(np.unique(y[m])) < 2: continue
            Zs = {c: np.asarray(v)[m] for c, v in Z.items()}; ys, gs = y[m], g[m]; oof = np.full(m.sum(), np.nan)
            for tr, te in folds(gs, 5, seed + rep):
                if len(np.unique(ys[tr])) < 2: continue
                try: oof[te] = Meta(kind).fit({c: v[tr] for c, v in Zs.items()}, ys[tr], gs[tr]).logit({c: v[te] for c, v in Zs.items()})
                except Exception: pass
            fin = np.isfinite(oof)
            if fin.sum() >= 5 and len(np.unique(ys[fin])) == 2: vals.append(auc(ys[fin], sigmoid(oof[fin])))
        vals = [v for v in vals if v is not None and np.isfinite(v)]
        pts.append(dict(patients=int(k), auc_mean=float(np.mean(vals)) if vals else None, auc_sd=float(np.std(vals)) if len(vals) > 1 else None, reps=len(vals)))
    a = [p_["auc_mean"] for p_ in pts if p_["auc_mean"] is not None]
    slope = (a[-1] - a[-2]) if len(a) >= 2 else None
    return dict(kind=kind, points=pts, last_step_gain=slope,
                still_improving=None if slope is None else bool(slope > 0.01),
                basis="meta-model learning curve on the development out-of-fold component table (components were fitted fold-wise on "
                      "all development patients): shows whether more patients still help - not a validation")


def subgroup_calibration(y, p, groups, min_n=100, min_class=20):
    """groups: {name: array of labels per row}. Recalibration is recommended only where a subgroup has the data; never applied here."""
    from .meta import calib
    y = np.asarray(y, float); p = np.asarray(p, float); out = {}
    for name, lab in groups.items():
        lab = np.array(["unknown" if v in (None, "", "nan") else str(v) for v in lab]); lv = {}
        for L in sorted(set(lab)):
            m = (lab == L) & np.isfinite(p); n1 = int(y[m].sum()); n0 = int(m.sum()) - n1
            e = dict(n=int(m.sum()), n_css=n1, mean_predicted=float(p[m].mean()) if m.any() else None, observed_rate=float(y[m].mean()) if m.any() else None)
            if m.sum() >= 10 and n1 >= 2 and n0 >= 2:
                sl, ic = calib(y[m], np.clip(p[m], 1e-6, 1 - 1e-6)); e.update(calib_slope=sl, calib_intercept=ic, brier=float(np.mean((p[m] - y[m]) ** 2)))
            enough = e["n"] >= min_n and min(n1, n0) >= min_class
            off = e.get("calib_slope") is not None and not (0.8 <= e["calib_slope"] <= 1.25)
            e["recalibration"] = ("recommended (enough data, slope outside 0.8-1.25) - requires approval; not applied automatically" if enough and off
                                  else "not needed" if enough else f"insufficient data (needs >= {min_n} candidates and >= {min_class} per class)")
            lv[L] = e
        out[name] = lv
    return dict(subgroups=out, applied=False, note="subgroup calibration is reported; per-subgroup recalibration is never applied automatically")


def abstention_curve(y, p, risk, coverages=(1.0, 0.9, 0.8, 0.7, 0.6, 0.5)):
    """sort by risk (higher = less reliable); keep the most reliable fraction -> accuracy (call >= 0.5), Brier, sensitivity on the kept part"""
    y = np.asarray(y, float); p = np.asarray(p, float); risk = np.nan_to_num(np.asarray(risk, float), nan=np.inf)
    o = np.argsort(risk, kind="stable"); pts = []
    for c in coverages:
        k = max(1, int(round(c * len(y)))); m = o[:k]; yy, pp = y[m], p[m]; call = pp >= 0.5
        pts.append(dict(coverage=float(c), n=int(k), accuracy=float(np.mean(call == (yy == 1))), brier=float(np.mean((pp - yy) ** 2)),
                        sensitivity=float(call[yy == 1].mean()) if (yy == 1).any() else None, review_required=int(len(y) - k)))
    return dict(points=pts, risk="component disagreement spread + number of missing components + ensemble spread (development out-of-fold)")


def qwk(a, b, k=5):
    a = np.asarray(a, int); b = np.asarray(b, int); O = np.zeros((k, k))
    for i, j in zip(a, b): O[i, j] += 1
    W = np.array([[(i - j) ** 2 / (k - 1) ** 2 for j in range(k)] for i in range(k)])
    E = np.outer(O.sum(1), O.sum(0)) / max(O.sum(), 1)
    den = (W * E).sum()
    return float(1 - (W * O).sum() / den) if den > 0 else None


def study_agreement(pred, expert, boot=500, seed=0):
    """pred / expert: {study: 0-4 grade}. Only studies with both. -> kappa (quadratic), exact agreement, Bland-Altman"""
    ids = sorted(set(pred) & set(expert))
    if len(ids) < 2: return dict(n=len(ids), available=False, note="awaiting expert patient-level grades (0-4) for scored studies")
    a = np.array([int(pred[i]) for i in ids]); b = np.array([int(expert[i]) for i in ids]); d = a - b; r = np.random.default_rng(seed)
    ks = [qwk(a[s], b[s]) for s in (r.integers(0, len(ids), len(ids)) for _ in range(boot))]
    ks = [k_ for k_ in ks if k_ is not None]
    return dict(n=len(ids), available=True, kappa_quadratic=qwk(a, b), kappa_ci=[float(np.percentile(ks, 2.5)), float(np.percentile(ks, 97.5))] if ks else None,
                exact_agreement=float(np.mean(d == 0)), within_one=float(np.mean(np.abs(d) <= 1)),
                bland_altman=dict(mean_difference=float(d.mean()), loa=[float(d.mean() - 1.96 * d.std(ddof=1)), float(d.mean() + 1.96 * d.std(ddof=1))] if len(d) > 2 else None),
                basis="study-level PERCIVAL multifocality (candidates scored >= 50 -> score_css) vs expert patient grades; patient bootstrap CI")


def prioritise(scored, k=20):
    """second-review queue: candidates with the most uncertainty / disagreement first. NEVER for the blind first read (callers gate it)."""
    def risk(s):
        return (2.0 if s.get("status") in ("uncertain", "review") else 0.0) + float(s.get("disagreement") or 0) + float(s.get("uncertainty_sd") or 0) / 10 \
               + (1.0 if s.get("percival_score") is not None and 35 <= s["percival_score"] <= 65 else 0.0)
    q = sorted(scored, key=lambda s: -risk(s))[:k]
    return [dict(cand_id=s.get("cand_id"), priority=round(risk(s), 2), status=s.get("status"), why=(s.get("reasons") or [])[:3]) for s in q]
