"""model_evaluation.py - patient-grouped evaluation.

Candidate level (each row a candidate, grouped by patient):
  auc_decomposition  exact identity  pooled AUC = (W * within + B * between) / (W + B), W / B = numbers of positive-negative pairs
                     inside one patient / across two patients. 'within' is the discrimination a reader of ONE scan experiences;
                     'between' mixes in differences of score level between patients (prevalence, scanner, fold-specific intercepts).
  fold-wise AUC      AUC inside each test fold, where every score comes from ONE fitted model; mean and SD over folds / repeats
  pooled AUC         reported, with the decomposition, never alone
  AP (PR-AUC), Brier, calibration, sensitivity / specificity / PPV / NPV at a threshold chosen on the TRAINING part
Patient level: candidate scores aggregated per patient (max) and compared with the patient-level reference (separate table).
Uncertainty: patient-cluster bootstrap (resample patients with replacement; all candidates of a drawn patient come along).
Subgroups: same metrics per subgroup, with patient counts; fewer than min_patients -> 'insufficient' (no point estimate shown)."""
from dataclasses import dataclass, field
import numpy as np
from . import patient_split as ps
from .calibration import calibration_slope_intercept, reliability


# ---------------- metrics
def auc(y, s):
    y = np.asarray(y); s = np.asarray(s, float); pos, neg = s[y == 1], s[y == 0]
    if not len(pos) or not len(neg): return np.nan
    from scipy.stats import rankdata
    r = rankdata(np.r_[pos, neg])
    return float((r[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def _pairs(a, b):
    """sum over pairs (pos in a, neg in b) of 1[a > b] + 0.5 1[a == b]"""
    if not len(a) or not len(b): return 0.0
    bs = np.sort(b); lt = np.searchsorted(bs, a, side="left"); le = np.searchsorted(bs, a, side="right")
    return float(lt.sum() + 0.5 * (le - lt).sum())


def auc_decomposition(y, s, pid):
    y = np.asarray(y); s = np.asarray(s, float); pid = np.asarray(pid).astype(str)
    pats = sorted(set(pid)); P = {q: s[(pid == q) & (y == 1)] for q in pats}; N = {q: s[(pid == q) & (y == 0)] for q in pats}
    allneg = s[y == 0]; Wc = Wn = Bc = Bn = 0.0
    for q in pats:
        if not len(P[q]): continue
        c_all, n_all = _pairs(P[q], allneg), len(P[q]) * len(allneg)
        c_in, n_in = _pairs(P[q], N[q]), len(P[q]) * len(N[q])
        Wc += c_in; Wn += n_in; Bc += c_all - c_in; Bn += n_all - n_in
    pooled = (Wc + Bc) / (Wn + Bn) if Wn + Bn else np.nan
    return dict(pooled=pooled, within=Wc / Wn if Wn else np.nan, between=Bc / Bn if Bn else np.nan,
                within_pairs=int(Wn), between_pairs=int(Bn), within_share=Wn / (Wn + Bn) if Wn + Bn else np.nan,
                patients_with_both=int(sum(len(P[q]) > 0 and len(N[q]) > 0 for q in pats)))


def average_precision(y, s):
    y = np.asarray(y); s = np.asarray(s, float)
    if not (y == 1).any(): return np.nan
    o = np.argsort(-s, kind="stable"); yy = y[o]; tp = np.cumsum(yy)
    return float((tp[yy == 1] / (np.nonzero(yy == 1)[0] + 1)).mean())


def brier(y, p): return float(np.mean((np.asarray(p, float) - np.asarray(y, float)) ** 2))


def threshold_for_sensitivity(y, s, target=0.9):
    pos = np.sort(np.asarray(s, float)[np.asarray(y) == 1])
    if not len(pos): return np.nan
    return float(pos[int(np.floor((1 - target) * len(pos)))])


def confusion(y, s, thr):
    y = np.asarray(y); pr = np.asarray(s, float) >= thr
    tp, fp = int((pr & (y == 1)).sum()), int((pr & (y == 0)).sum()); fn, tn = int((~pr & (y == 1)).sum()), int((~pr & (y == 0)).sum())
    d = lambda a, b: a / b if b else np.nan
    return dict(threshold=float(thr), tp=tp, fp=fp, fn=fn, tn=tn, sensitivity=d(tp, tp + fn), specificity=d(tn, tn + fp),
                ppv=d(tp, tp + fp), npv=d(tn, tn + fn), recall=d(tp, tp + fn), precision=d(tp, tp + fp))


def cluster_bootstrap(fn, y, s, pid, B=1000, seed=0, **kw):
    """95 % percentile interval of fn(y, s, pid, **kw) over patient resamples; None when < 20 finite draws"""
    rng = np.random.default_rng(seed); pid = np.asarray(pid).astype(str); pats = np.array(sorted(set(pid)))
    idx = {q: np.where(pid == q)[0] for q in pats}; vals = []
    for b in range(B):
        draw = rng.choice(pats, len(pats), replace=True)
        sel = np.concatenate([idx[q] for q in draw])
        newpid = np.concatenate([np.full(len(idx[q]), f"{q}#{i}") for i, q in enumerate(draw)])   # a patient drawn twice = two patients
        v = fn(np.asarray(y)[sel], np.asarray(s)[sel], newpid, **kw)
        if v is not None and np.isfinite(v): vals.append(v)
    return [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))] if len(vals) >= 20 else None


def quadratic_weighted_kappa(a, b, k=5):
    a = np.asarray(a, int); b = np.asarray(b, int); O = np.zeros((k, k))
    for i, j in zip(a, b): O[i, j] += 1
    W = np.array([[(i - j) ** 2 for j in range(k)] for i in range(k)]) / (k - 1) ** 2
    E = np.outer(O.sum(1), O.sum(0)) / max(O.sum(), 1)
    return float(1 - (W * O).sum() / (W * E).sum()) if (W * E).sum() else np.nan


# ---------------- cross-validation driver
@dataclass
class Scorer:
    """name; fit(df_train, y_train, patients_train) -> fitted object with .score(df) ; fitted=False for fixed scores (score_v4)"""
    name: str
    make: object
    fitted: bool = True
    is_probability: bool = True


@dataclass
class CVResult:
    name: str
    oof: dict                                      # repeat -> array of out-of-fold scores (NaN where a fold could not be fitted)
    fold: dict                                     # repeat -> array of fold ids
    thresholds: dict = field(default_factory=dict)  # (repeat, fold) -> threshold chosen on the training part
    failures: list = field(default_factory=list)


def cross_validate(df, y, patients, assignment, scorers, target_sens=0.9):
    """identical patient folds for every scorer. Returns {name: CVResult}."""
    y = np.asarray(y, float); pats = np.asarray(patients).astype(str); out = {}
    for sc in scorers:
        res = CVResult(sc.name, {}, {})
        for r in range(assignment.n_repeats):
            o = np.full(len(y), np.nan); fid = np.full(len(y), -1)
            for k, (tr, te) in enumerate(ps.fold_indices(assignment, pats, r)):
                fid[te] = k
                try:
                    if sc.fitted:
                        if len(np.unique(y[tr])) < 2: raise ValueError("training part has one class")
                        m = sc.make().fit(df.iloc[tr].reset_index(drop=True), y[tr], pats[tr])
                        s_tr = np.asarray(m.score(df.iloc[tr].reset_index(drop=True)), float)
                        o[te] = np.asarray(m.score(df.iloc[te].reset_index(drop=True)), float)
                    else:
                        s_tr = np.asarray(sc.make(df.iloc[tr]), float); o[te] = np.asarray(sc.make(df.iloc[te]), float)
                    res.thresholds[(r, k)] = threshold_for_sensitivity(y[tr], s_tr, target_sens)
                except Exception as e:
                    res.failures.append(dict(repeat=r, fold=k, error=f"{type(e).__name__}: {e}"))
            res.oof[r] = o; res.fold[r] = fid
        out[sc.name] = res
    return out


def summarise(res: CVResult, y, patients, is_probability=True, B=500, seed=0):
    """candidate-level summary over repeats (mean of per-repeat values; fold-wise AUC mean / SD over all folds)"""
    y = np.asarray(y); pid = np.asarray(patients).astype(str); per = []
    fold_aucs = []
    for r, o in res.oof.items():
        ok = np.isfinite(o)
        if ok.sum() < 3: continue
        d = auc_decomposition(y[ok], o[ok], pid[ok])
        conf_rows = []
        for k in sorted(set(res.fold[r][ok])):
            m = ok & (res.fold[r] == k)
            a = auc(y[m], o[m])
            if np.isfinite(a): fold_aucs.append(a)
            t = res.thresholds.get((r, k))
            if t is not None and np.isfinite(t): conf_rows.append(confusion(y[m], o[m], t))
        tp = sum(c["tp"] for c in conf_rows); fn = sum(c["fn"] for c in conf_rows); fp = sum(c["fp"] for c in conf_rows); tn = sum(c["tn"] for c in conf_rows)
        row = dict(repeat=r, pooled_auc=d["pooled"], within_patient_auc=d["within"], between_patient_auc=d["between"],
                   within_pair_share=d["within_share"], ap=average_precision(y[ok], o[ok]),
                   sensitivity=tp / (tp + fn) if tp + fn else np.nan, specificity=tn / (tn + fp) if tn + fp else np.nan,
                   ppv=tp / (tp + fp) if tp + fp else np.nan, npv=tn / (tn + fn) if tn + fn else np.nan)
        if is_probability:
            row["brier"] = brier(y[ok], o[ok]); row.update({f"cal_{k}": v for k, v in calibration_slope_intercept(y[ok], o[ok]).items()})
            row["ece"] = reliability(y[ok], o[ok])[1]
        per.append(row)
    mean = lambda k: float(np.nanmean([p[k] for p in per if p.get(k) is not None])) if per else np.nan
    keys = ["pooled_auc", "within_patient_auc", "between_patient_auc", "within_pair_share", "ap", "sensitivity", "specificity", "ppv", "npv"] + \
           (["brier", "cal_slope", "cal_citl", "ece"] if is_probability else [])
    S = {k: mean(k) for k in keys}
    S["fold_auc_mean"] = float(np.mean(fold_aucs)) if fold_aucs else np.nan
    S["fold_auc_sd"] = float(np.std(fold_aucs)) if fold_aucs else np.nan
    S["n_folds_scored"] = len(fold_aucs); S["failures"] = len(res.failures)
    o0 = res.oof[0]; ok = np.isfinite(o0)
    wi = lambda yy, ss, pp: auc_decomposition(yy, ss, pp)["within"]
    S["within_patient_auc_ci_repeat0"] = cluster_bootstrap(wi, y[ok], o0[ok], pid[ok], B=B, seed=seed) if ok.sum() > 10 else None
    S["per_repeat"] = per
    return S


def patient_level(res: CVResult, patients, patient_ref, repeat=0, agg="max"):
    """patient-level AUC of the aggregated candidate score against patient_ref (dict patient -> 0/1)"""
    pid = np.asarray(patients).astype(str); o = res.oof[repeat]; ok = np.isfinite(o)
    pats = sorted(set(pid[ok]) & set(patient_ref))
    s = np.array([np.max(o[ok & (pid == q)]) if agg == "max" else np.mean(o[ok & (pid == q)]) for q in pats])
    yy = np.array([patient_ref[q] for q in pats])
    return dict(n_patients=len(pats), n_positive=int(yy.sum()), auc=auc(yy, s),
                note="patients without any candidate are not scored here (they are a detector miss, not a model error)")


def subgroup(res: CVResult, y, patients, groups, min_patients=8, repeat=0, B=500, seed=0):
    y = np.asarray(y); pid = np.asarray(patients).astype(str); g = np.asarray(groups).astype(str); o = res.oof[repeat]; out = {}
    for v in sorted(set(g)):
        m = (g == v) & np.isfinite(o); npat = len(set(pid[m]))
        if npat < min_patients or len(set(y[m])) < 2:
            out[v] = dict(n_candidates=int(m.sum()), n_patients=npat, status="insufficient", within_patient_auc=None, ci=None); continue
        d = auc_decomposition(y[m], o[m], pid[m]); wi = lambda yy, ss, pp: auc_decomposition(yy, ss, pp)["within"]
        out[v] = dict(n_candidates=int(m.sum()), n_patients=npat, status="ok", within_patient_auc=d["within"], pooled_auc=d["pooled"],
                      ci=cluster_bootstrap(wi, y[m], o[m], pid[m], B=B, seed=seed))
    return out
