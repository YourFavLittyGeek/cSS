"""auc_investigation.py - why a candidate model on PURE NOISE can show a pooled AUC far below 0.5 (SYNTHETIC simulation).

Mechanism (leave-one-patient-out, LOPO, or any CV with few patients per fold):
  The prediction for held-out patient k comes from a model fitted WITHOUT patient k. Its intercept follows the training prevalence
  (N_pos - pos_k) / (N - n_k): the more cSS patient k has, the LOWER the training prevalence and the LOWER every score given to k.
  Pooling the out-of-fold scores of all patients then compares scores produced by DIFFERENT models: positives (concentrated in
  high-prevalence patients) systematically receive lower scores than negatives -> pooled AUC < 0.5 although no model has
  learned anything. The within-patient AUC (pairs inside one patient, one model) stays near 0.5. With prevalence varying strongly
  between patients the pooled AUC can fall to ~0.3. Platt scaling and standardisation fitted per fold do not remove it.
Terms (as used in the reports):
  genuine discrimination   ranking cSS above non-cSS INSIDE the same scan (within-patient AUC > 0.5)
  between-patient prevalence variation   patients differ in their share of cSS candidates; it moves pooled AUCs without any
                           candidate-level discrimination (either direction, depending on the evaluation)
  pooled candidate AUC     all out-of-fold candidates in one ranking: mixes within- and between-patient pairs (decomposition)
  patient-grouped evaluation  folds by patient; metrics computed where every score comes from ONE model (fold-wise) and
                           within patients; pooled numbers only with their decomposition
This module runs the ORIGINAL uscore nested_lopo (verbatim snapshot) and the new framework on the same synthetic data."""
import numpy as np
from . import provenance as pv
from .model_evaluation import auc_decomposition, auc
from .ml_component import PenalizedLogistic
from . import patient_split as ps

P3 = ["x1_vessel_continuity_mm", "x2_core_contrast_nu", "x3_pial_distance_mm"]


def simulate(n_patients=10, cands=(6, 25), prevalence="beta", n_features=3, signal=0.0, seed=0, confounder=0.0):
    """pure noise (signal = 0) or a true feature effect (signal > 0 on feature 0). confounder > 0: a patient-level variable moves both
    the patient's prevalence and feature 1 (between-patient association without within-patient discrimination)."""
    r = np.random.default_rng(seed); npp = r.integers(cands[0], cands[1], n_patients)
    if prevalence == "beta": pr = r.beta(1, 1.5, n_patients)
    elif prevalence == "equal": pr = np.full(n_patients, 0.4)
    else: pr = np.asarray(prevalence, float)
    u = r.normal(size=n_patients)
    if confounder: pr = np.clip(pr + 0.2 * confounder * u, 0.02, 0.95)
    pid = np.repeat([f"SYN{i:02d}" for i in range(n_patients)], npp)
    y = np.concatenate([r.random(k) < p for k, p in zip(npp, pr)]).astype(float)
    X = r.normal(size=(len(y), n_features))
    if signal: X[:, 0] += signal * y
    if confounder: X[:, 1] += confounder * np.repeat(u, npp)
    return X, y, pid


def _rows(X):
    return [dict(F={k: dict(value=float(v), status="reliable") for k, v in zip(P3, x)}) for x in X]


def original_uscore_nested_lopo(X, y, pid):
    """the unmodified uscore.model.nested_lopo (snapshot) -> calibrated outer predictions"""
    md = pv.load_legacy("uscore.model", "unified_score")
    _, p_cal, _ = md.nested_lopo(_rows(X[:, :3]), y, pid, P3)
    return p_cal


def intercept_only_lopo(y, pid):
    """no features at all: the held-out patient's score = training prevalence. Shows the mechanism in its purest form."""
    s = np.full(len(y), np.nan)
    for q in sorted(set(pid)):
        tr = pid != q; s[pid == q] = y[tr].mean()
    return s


def new_framework_cv(X, y, pid, n_splits=5, seed=0, lopo=False):
    """new penalised LR (training-fold preprocessing, nested penalty by mean per-fold log loss) -> out-of-fold scores + fold ids"""
    pats = sorted(set(pid)); k = len(pats) if lopo else n_splits
    a = ps.grouped_folds(pats, k, 1, seed, keymap_verified=True)
    s = np.full(len(y), np.nan); f = np.full(len(y), -1)
    for i, (tr, te) in enumerate(ps.fold_indices(a, pid, 0)):
        if len(np.unique(y[tr])) < 2: continue
        m = PenalizedLogistic([f"x{j}" for j in range(X.shape[1])]).fit_nested(X[tr], y[tr], pid[tr], n_inner=min(5, len(set(pid[tr]))), seed=seed)
        s[te] = m.predict(X[te]); f[te] = i
    return s, f


def fold_wise_auc(y, s, f):
    v = [auc(y[(f == k)], s[(f == k)]) for k in sorted(set(f[f >= 0]))]
    v = [a for a in v if np.isfinite(a)]
    return (float(np.mean(v)), len(v)) if v else (np.nan, 0)


def run(seeds=range(10), n_patients=10, scenarios=None, include_original=True):
    """-> list of dict rows (one per scenario x method), mean / min / max over seeds. SYNTHETIC."""
    scenarios = scenarios or [
        dict(name="pure noise, equal prevalence", prevalence="equal", signal=0.0),
        dict(name="pure noise, prevalence varies between patients", prevalence="beta", signal=0.0),
        dict(name="true within-patient signal (d=1.0), prevalence varies", prevalence="beta", signal=1.0),
        dict(name="patient-level confounder only (no within-patient signal)", prevalence="beta", signal=0.0, confounder=1.5)]
    rows = []
    for sc in scenarios:
        acc = {}
        for sd in seeds:
            X, y, pid = simulate(n_patients, prevalence=sc["prevalence"], signal=sc.get("signal", 0.0), seed=sd, confounder=sc.get("confounder", 0.0))
            meth = {}
            if include_original:
                p = original_uscore_nested_lopo(X, y, pid); ok = np.isfinite(p); meth["original uscore nested LOPO (pooled)"] = (y[ok], p[ok], pid[ok], None)
            s = intercept_only_lopo(y, pid); meth["intercept-only LOPO, no features (pooled)"] = (y, s, pid, None)
            s, f = new_framework_cv(X, y, pid, lopo=True); ok = np.isfinite(s); meth["new LR, LOPO (pooled)"] = (y[ok], s[ok], pid[ok], f[ok])
            s, f = new_framework_cv(X, y, pid, n_splits=5, seed=sd); ok = np.isfinite(s); meth["new LR, 5-fold grouped (pooled)"] = (y[ok], s[ok], pid[ok], f[ok])
            for name, (yy, ss, pp, ff) in meth.items():
                d = auc_decomposition(yy, ss, pp)
                a = acc.setdefault(name, dict(pooled=[], within=[], between=[], fold=[]))
                a["pooled"].append(d["pooled"]); a["within"].append(d["within"]); a["between"].append(d["between"])
                if ff is not None: a["fold"].append(fold_wise_auc(yy, ss, ff)[0])
        for name, a in acc.items():
            st = lambda v: None if not v else dict(mean=float(np.nanmean(v)), min=float(np.nanmin(v)), max=float(np.nanmax(v)))
            rows.append(dict(scenario=sc["name"], method=name, n_seeds=len(list(seeds)), pooled=st(a["pooled"]), within=st(a["within"]),
                             between=st(a["between"]), fold_wise=st([v for v in a["fold"] if np.isfinite(v)]), synthetic=True))
    return rows
