"""PERCIVAL validation methodology (2026-11-28, audit 2026-11-27 findings S1/S2/S3/S4/S6).

Why this module exists - the v001 failure, reproduced on the user's cached scores:
  every one of the 5 meta-level folds ranked cSS in the RIGHT direction (per-fold slopes 0.34 / 0.39 / 0.32 / 0.99 / 0.04), yet the
  out-of-fold predictions POOLED across folds gave AUC 0.508, and a random predictor through the same procedure gave 0.42 on average.
  Pooling the outputs of fold-specific models mixes fold-specific intercepts; with few positive patients and unstratified folds the held-out
  prevalence differs between folds (0.023 - 0.098) and the between-fold offsets dominate a weak within-fold ranking. A Platt calibration fitted
  on that pooled table then got slope -0.41 and reversed a correctly ordered model (test AUC 0.92 -> 0.09).

What is done instead (each function is used by meta.py / nested.py):
  folds()          patient-grouped AND stratified: patients with and without cSS are dealt separately, positive candidates balanced
  fold_auc()       discrimination WITHIN each held-out fold, pair-weighted over folds (immune to between-fold offsets); a random
                   predictor has expectation 0.5
  select_kind()    paired patient-bootstrap comparison on the same candidates and folds; the simplest model is chosen only when it is within
                   one PAIRED standard error of the best; 'informative' only when the chosen model's lower 95 % bound is above 0.5
  calibrate()      Platt calibration with one intercept per fold and ONE common slope (between-fold offsets cannot bias the slope); the
                   global intercept is then refitted to the development base rate; per-fold slopes and their sign agreement are reported
  patient_level(), lesion_level()   test-cohort metrics at the patient and lesion level
Nothing here can push an AUC above what the data support: there is no transformation of scores, only how they are compared and calibrated."""
import numpy as np
from ..ml_component import sigmoid, irls, SLOPE_MIN

METHOD_VERSION = "percival-validation/2.0"
N_BOOT = 300
META_REPEATS = 3


def _auc(y, s):
    y = np.asarray(y, float); s = np.asarray(s, float); m = np.isfinite(s); y, s = y[m], s[m]
    n1, n0 = int((y == 1).sum()), int((y == 0).sum())
    if n1 == 0 or n0 == 0: return None
    order = s.argsort(kind="mergesort"); r = np.empty(len(s)); r[order] = np.arange(1, len(s) + 1)
    for v in np.unique(s):
        k = s == v
        if k.sum() > 1: r[k] = r[k].mean()
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


# ------------------------------------------------------------------ folds
def folds(groups, k=5, seed=0, y=None):
    """patient-grouped folds -> [(train_idx, test_idx)]. With y (candidate labels): stratified - patients with >= 1 cSS candidate are dealt
    first (most positive candidates first) to the fold with the fewest positive candidates, then patients without cSS to the fold with the
    fewest patients. Deterministic for (groups, k, seed, y). Without y: the previous random patient partition (unchanged behaviour)."""
    g = np.asarray(groups).astype(str); u = np.unique(g); r = np.random.default_rng(seed); u = u[r.permutation(len(u))]
    k = max(2, min(k, len(u)))
    if y is None:
        parts = [u[i::k] for i in range(k)]
    else:
        y = np.asarray(y, float); npos = {p: float(y[g == p].sum()) for p in u}
        pos = sorted([p for p in u if npos[p] > 0], key=lambda p: -npos[p]); neg = [p for p in u if npos[p] == 0]   # stable: permuted order kept on ties
        bins = [[] for _ in range(k)]; cpos = [0.0] * k; ppat = [0] * k; cpat = [0] * k
        for p in pos:
            j = min(range(k), key=lambda i: (cpos[i], ppat[i], i)); bins[j].append(p); cpos[j] += npos[p]; ppat[j] += 1; cpat[j] += 1
        for p in neg:
            j = min(range(k), key=lambda i: (cpat[i], i)); bins[j].append(p); cpat[j] += 1
        parts = [np.array(b) for b in bins]
    return [(np.where(~np.isin(g, p))[0], np.where(np.isin(g, p))[0]) for p in parts]


def fold_ids(n, F):
    fid = np.full(n, -1, int)
    for i, (_, te) in enumerate(F): fid[te] = i
    return fid


# ------------------------------------------------------------------ discrimination within folds
def fold_auc(y, s, fid):
    """pair-weighted mean of the AUC inside each held-out fold (pairs of one cSS and one non-cSS candidate held out TOGETHER). A pooled AUC
    over fold-specific models compares scores from different models; this does not."""
    y = np.asarray(y, float); s = np.asarray(s, float); fid = np.asarray(fid); num = den = 0.0
    for f in np.unique(fid):
        m = (fid == f) & np.isfinite(s); n1 = int((y[m] == 1).sum()); n0 = int((y[m] == 0).sum())
        if n1 == 0 or n0 == 0: continue
        num += _auc(y[m], s[m]) * n1 * n0; den += n1 * n0
    return float(num / den) if den else None


def _boot_index(g, n, seed):
    g = np.asarray(g).astype(str); u = np.unique(g); idx = {p: np.where(g == p)[0] for p in u}; rng = np.random.default_rng(seed)
    return [np.concatenate([idx[p] for p in rng.choice(u, len(u))]) for _ in range(n)]


def boot_fold_auc(y, scores, fid, g, n=N_BOOT, seed=0):
    """the same patient resamples for every score vector (paired) -> {kind: array of bootstrap fold-AUCs}"""
    B = _boot_index(g, n, seed); y = np.asarray(y, float); fid = np.asarray(fid); out = {}
    for k_, s in scores.items():
        s = np.asarray(s, float); out[k_] = np.array([np.nan if (a := fold_auc(y[b], s[b], fid[b])) is None else a for b in B])
    return out


def select_kind(scores, y, fid, g, order, n=N_BOOT, seed=0):
    """transparent model choice -> (chosen, report, informative).
    1. point estimate = fold-stratified AUC of each candidate model (same candidates, same folds);
    2. best = highest point estimate; paired patient bootstrap of (best - other) on the SAME resamples;
    3. chosen = the simplest model (order) whose gap to the best is <= one PAIRED standard error (a simpler model is preferred only when the
       data cannot tell it apart from the best - never merely because it is simpler);
    4. informative = the chosen model's bootstrap 2.5th percentile is above 0.5 (better than chance with 95 % confidence)."""
    pts = {k_: fold_auc(y, s, fid) for k_, s in scores.items()}
    ok = [k_ for k_ in order if k_ in pts and pts[k_] is not None]
    if not ok: return None, {k_: dict(fold_auc=None) for k_ in scores}, False
    BS = boot_fold_auc(y, {k_: scores[k_] for k_ in ok}, fid, g, n, seed)
    best = max(ok, key=lambda k_: pts[k_]); rep = {}
    for k_ in ok:
        d = BS[best] - BS[k_]; d = d[np.isfinite(d)]; se = float(np.std(d)) if len(d) > 1 else 0.0; b = BS[k_][np.isfinite(BS[k_])]
        rep[k_] = dict(fold_auc=pts[k_], ci=[float(np.percentile(b, 2.5)), float(np.percentile(b, 97.5))] if len(b) > 20 else None,
                       gap_to_best=float(pts[best] - pts[k_]), paired_se=se, within_one_paired_se=bool(pts[best] - pts[k_] <= se))
    for k_ in scores:
        if k_ not in rep: rep[k_] = dict(fold_auc=None)
    chosen = next(k_ for k_ in ok if rep[k_]["within_one_paired_se"])
    ci = rep[chosen]["ci"]; informative = bool(ci is not None and ci[0] > 0.5)
    rep["_best"] = best
    return chosen, rep, informative


SELECTION_RULE = ("fold-stratified AUC (discrimination inside each held-out patient fold) compared on the same candidates with a paired patient "
                  "bootstrap; the simplest model within one PAIRED standard error of the best is chosen; the model is 'informative' only when its "
                  "lower 95 % bound is above 0.5")


# ------------------------------------------------------------------ calibration
def _newton_fold_slope(Zf, z, y, w, lam_slope, iters=100):
    """logistic regression with one free intercept per fold (Zf one-hot) and one common slope on z; ridge only on the slope"""
    A = np.c_[Zf, z]; b = np.zeros(A.shape[1]); P = np.zeros(A.shape[1]); P[-1] = lam_slope
    for _ in range(iters):
        mu = sigmoid(A @ b); W = w * mu * (1 - mu) + 1e-12
        H = A.T @ (W[:, None] * A) + np.diag(P) + 1e-9 * np.eye(len(b)); gr = A.T @ (w * (y - mu)) - P * b
        st = np.linalg.solve(H, gr); b = b + st
        if np.max(np.abs(st)) < 1e-9: break
    return b


def calibrate(z, y, fid, w=None, lam=1.0):
    """Platt calibration of out-of-fold log-odds z that is valid for pooled fold-specific models -> dict(a, b, clamped, sign_consistent, ...).
    The slope is estimated WITHIN folds (one intercept per fold, common slope); then the intercept is refitted on all candidates with the slope
    fixed (base rate). Slope < SLOPE_MIN -> held at SLOPE_MIN (order kept) and flagged: the model is then not calibratable on these data."""
    z = np.nan_to_num(np.asarray(z, float)); y = np.asarray(y, float); fid = np.asarray(fid); w = np.ones(len(y)) if w is None else np.asarray(w, float)
    fs = [f for f in np.unique(fid) if f >= 0]; m = np.isin(fid, fs)
    per = {}
    for f in fs:
        mf = fid == f
        if len(np.unique(y[mf])) == 2 and np.std(z[mf]) > 0:
            bf, _, _ = irls(z[mf][:, None], y[mf], lam, None, w[mf]); per[int(f)] = float(bf[1])
    if len(fs) >= 2 and m.sum() >= 5 and len(np.unique(y[m])) == 2:
        Zf = (fid[m][:, None] == np.array(fs)[None, :]).astype(float)
        slope = float(_newton_fold_slope(Zf, z[m], y[m], w[m], lam)[-1])
    else:
        bb, _, _ = irls(z[:, None], y, lam, None, w); slope = float(bb[1])
    clamped = not (np.isfinite(slope) and slope >= SLOPE_MIN)
    b = SLOPE_MIN if clamped else slope
    a_, _, _ = irls(np.zeros((len(z), 0)), y, 0.0, b * z, w); a = float(a_[0])
    vals = list(per.values()); sign_ok = bool(vals) and all(v > 0 for v in vals)
    return dict(a=a, b=b, ridge=lam, clamped=bool(clamped), slope_within_folds=slope, fold_slopes=per, sign_consistent=sign_ok,
                method="within-fold Platt: one intercept per held-out fold, common slope; intercept refitted to the development base rate")


# ------------------------------------------------------------------ test-cohort levels
def patient_level(y, p, g, extra_pos=(), n=N_BOOT, seed=0):
    """patient = positive when any of its candidates is cSS OR it is listed in extra_pos (expert-marked missed cSS); patient score = its
    highest candidate score (a patient whose cSS was missed entirely still has a score: its highest NON-cSS candidate). -> dict"""
    y = np.asarray(y, float); p = np.asarray(p, float); g = np.asarray(g).astype(str); ex = {str(x) for x in extra_pos}
    U = sorted(set(g)); yp = np.array([1.0 if (y[g == u].max() == 1 or u in ex) else 0.0 for u in U])
    sp = np.array([np.nanmax(p[g == u]) if np.isfinite(p[g == u]).any() else np.nan for u in U])
    out = dict(patients=len(U), with_css=int(yp.sum()), without_css=int((1 - yp).sum()), auc=_auc(yp, sp), score="highest candidate score per patient")
    if out["with_css"] and out["without_css"]:
        rng = np.random.default_rng(seed); A = []
        for _ in range(n):
            i = rng.integers(0, len(U), len(U)); a = _auc(yp[i], sp[i])
            if a is not None: A.append(a)
        out["auc_ci"] = [float(np.percentile(A, 2.5)), float(np.percentile(A, 97.5))] if len(A) > 20 else None
    out["ci_reliable"] = bool(min(out["with_css"], out["without_css"]) >= 10)
    out["note"] = ("fewer than 10 patients in a class: the interval is shown but is not a reliable estimate" if not out["ci_reliable"] else "")
    return out


def at_threshold_patients(y, p, g, t, extra_pos=()):
    y = np.asarray(y, float); p = np.asarray(p, float); g = np.asarray(g).astype(str); ex = {str(x) for x in extra_pos}
    U = sorted(set(g)); yp = np.array([(y[g == u].max() == 1) or (u in ex) for u in U]); fl = np.array([bool((p[g == u] >= t).any()) for u in U])
    tp, fn = int((fl & yp).sum()), int((~fl & yp).sum()); fp, tn = int((fl & ~yp).sum()), int((~fl & ~yp).sum())
    return dict(threshold=float(t), tp=tp, fn=fn, fp=fp, tn=tn, sensitivity=tp / (tp + fn) if tp + fn else None, specificity=tn / (tn + fp) if tn + fp else None)


def lesion_level(y, p, studies, n_missed=0, fp_per_study=(0.5, 1, 2, 4)):
    """lesion sensitivity at fixed false positives per study. Denominator of sensitivity = cSS candidates + expert-marked missed cSS (a lesion
    the detector never proposed counts as missed at every threshold). -> dict"""
    y = np.asarray(y, float); p = np.asarray(p, float); s = np.asarray(studies).astype(str); m = np.isfinite(p)
    n_st = len(set(s)); n_les = int(y.sum()) + int(n_missed)
    if n_st == 0 or n_les == 0: return dict(n_studies=n_st, n_lesions=n_les, points=[])
    ts = np.unique(p[m])[::-1]; pts = []
    for f in fp_per_study:
        best = None
        for t in ts:
            sel = m & (p >= t); fpps = float((sel & (y == 0)).sum()) / n_st
            if fpps > f: break
            best = (t, int((sel & (y == 1)).sum()), fpps)
        pts.append(dict(fp_per_study=f, threshold=None if best is None else float(best[0]), sensitivity=0.0 if best is None else best[1] / n_les,
                        achieved_fp_per_study=None if best is None else best[2]))
    return dict(n_studies=n_st, n_lesions=n_les, n_missed_by_detector=int(n_missed), points=pts,
                basis="sensitivity = detected cSS at the threshold / (cSS candidates + expert-marked missed cSS); FP = non-cSS candidates at or above it")
