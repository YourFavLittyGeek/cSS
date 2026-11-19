"""model.py - primary model: ridge logistic regression on the five predictors, z = b0 + sum_j b_j x_j, p_raw = 1/(1+exp(-z)).

- Unreliable / unavailable predictor values are replaced by the training mean (zero contribution after standardising): never
  evidence. Standardisation statistics come from the training patients' RELIABLE values only.
- Nested leave-one-patient-out (LOPO): outer patient k held out; inside the training patients T an inner LOPO chooses the ridge
  penalty and produces inner out-of-fold scores; Platt scaling is fitted on those inner scores (T only); the model refitted on T
  scores patient k and Platt_k is applied. No calibrator sees the patient it is applied to.
- Effective degrees of freedom = trace of the ridge hat matrix, reported per fold.
- Predeclared fallback: if events / slopes < 10, drop x4, then x5. Probability output is withheld when coefficient signs agree in
  < 80 % of outer folds or the outer calibration slope is outside 0.7-1.3.
- Only development studies may be fitted (Cohort.check_fit_set)."""
import json, hashlib
import numpy as np
from .common import PREDICTORS, FALLBACK_DROP_ORDER, MODEL_VERSION, FEATURE_VERSION

LAMBDAS = np.logspace(-2, 3, 11)


def sigmoid(z): return 1.0 / (1.0 + np.exp(-np.clip(z, -35, 35)))


def design(rows, predictors, stats=None):
    """rows: list of dicts with features F. Returns X (raw, NaN where not reliable), mask of reliable values."""
    X = np.full((len(rows), len(predictors)), np.nan)
    for i, r in enumerate(rows):
        for j, k in enumerate(predictors):
            f = r["F"][k]
            if f["status"] == "reliable" and f["value"] is not None: X[i, j] = f["value"]
    return X


def standardise_fit(X):
    mu = np.array([np.nanmean(c) if np.isfinite(c).any() else 0.0 for c in X.T])
    sd = np.array([np.nanstd(c) if np.isfinite(c).sum() > 1 else 1.0 for c in X.T]); sd[sd < 1e-9] = 1.0
    return mu, sd


def standardise(X, mu, sd):
    Z = (X - mu) / sd; Z[~np.isfinite(Z)] = 0.0; return Z


def ridge_fit(Z, y, lam, w=None, it=100):
    """IRLS for L2-penalised logistic regression (intercept unpenalised). Returns beta (incl. intercept first), edf."""
    n, p = Z.shape; A = np.c_[np.ones(n), Z]; b = np.zeros(p + 1)
    P = np.eye(p + 1) * lam; P[0, 0] = 0.0; w = np.ones(n) if w is None else w
    for _ in range(it):
        mu = sigmoid(A @ b); W = w * mu * (1 - mu) + 1e-9
        H = A.T @ (W[:, None] * A) + P; g = A.T @ (w * (y - mu)) - P @ b
        step = np.linalg.solve(H, g); b += step
        if np.abs(step).max() < 1e-8: break
    mu = sigmoid(A @ b); W = mu * (1 - mu)
    H = A.T @ (W[:, None] * A) + P
    edf = float(np.trace(np.linalg.solve(H, A.T @ (W[:, None] * A))))
    return b, edf


def logloss(y, p): p = np.clip(p, 1e-9, 1 - 1e-9); return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def auc(y, s):
    y = np.asarray(y); s = np.asarray(s); pos, neg = s[y == 1], s[y == 0]
    if not len(pos) or not len(neg): return None
    allv = np.r_[pos, neg]; rk = np.empty(len(allv))
    order = np.argsort(allv); i = 0
    while i < len(allv):
        j = i
        while j + 1 < len(allv) and allv[order[j + 1]] == allv[order[i]]: j += 1
        rk[order[i:j + 1]] = (i + j) / 2 + 1; i = j + 1
    return float((rk[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def platt_fit(z, y):
    b, _ = ridge_fit(z[:, None], y, 1e-6); return float(b[1]), float(b[0])


def calib_slope(y, p):
    lp = np.log(np.clip(p, 1e-9, 1 - 1e-9) / np.clip(1 - p, 1e-9, 1))
    b, _ = ridge_fit(lp[:, None], y, 1e-6); return float(b[1]), float(b[0])


HASH_EXCLUDE = ("model_hash", "frozen", "frozen_at")


def model_hash(d):
    """sha256 of the model content (everything except the hash itself and the freeze stamp). Used when the model is written
    AND recomputed independently at the held-out label boundary, so an edited model file cannot pass with its old hash."""
    return hashlib.sha256(json.dumps({k: v for k, v in d.items() if k not in HASH_EXCLUDE}, sort_keys=True).encode()).hexdigest()


class Fitted:
    def __init__(self, predictors, beta, mu, sd, lam, edf, platt=None):
        self.predictors, self.beta, self.mu, self.sd, self.lam, self.edf, self.platt = predictors, beta, mu, sd, lam, edf, platt

    def z(self, rows):
        return np.c_[np.ones(len(rows)), standardise(design(rows, self.predictors), self.mu, self.sd)] @ self.beta

    def p_raw(self, rows): return sigmoid(self.z(rows))

    def p_cal(self, rows):
        if self.platt is None: return None
        a, b = self.platt; return sigmoid(a * self.z(rows) + b)

    def contributions(self, row):
        """per-predictor contribution to z (log-odds) and whether it is evidence (reliable) or imputed (0)."""
        X = design([row], self.predictors); Z = standardise(X, self.mu, self.sd)[0]
        return {k: dict(contribution=float(self.beta[j + 1] * Z[j]), imputed=bool(not np.isfinite(X[0, j])), beta_std=float(self.beta[j + 1]))
                for j, k in enumerate(self.predictors)}

    def to_json(self, **extra):
        d = dict(model_version=MODEL_VERSION, feature_version=FEATURE_VERSION, predictors=self.predictors, beta=list(map(float, self.beta)),
                 mu=list(map(float, self.mu)), sd=list(map(float, self.sd)), lam=float(self.lam), edf=float(self.edf),
                 platt=None if self.platt is None else list(self.platt), **extra)
        d["model_hash"] = model_hash(d)
        return d

    @staticmethod
    def from_json(d):
        return Fitted(d["predictors"], np.array(d["beta"]), np.array(d["mu"]), np.array(d["sd"]), d["lam"], d["edf"],
                      None if d["platt"] is None else tuple(d["platt"]))


def fit(rows, y, predictors, lam):
    X = design(rows, predictors); mu, sd = standardise_fit(X)
    b, edf = ridge_fit(standardise(X, mu, sd), y, lam)
    return Fitted(predictors, b, mu, sd, lam, edf)


def inner_lopo(rows, y, pid, predictors):
    """returns best lambda and the inner out-of-fold z at that lambda (training patients only)."""
    pats = sorted(set(pid)); best = None
    for lam in LAMBDAS:
        z = np.full(len(rows), np.nan)
        for q in pats:
            tr = pid != q; te = ~tr
            if y[tr].min() == y[tr].max(): continue
            m = fit([rows[i] for i in np.where(tr)[0]], y[tr], predictors, lam); z[te] = m.z([rows[i] for i in np.where(te)[0]])
        ok = np.isfinite(z)
        if ok.sum() < 5: continue
        ll = logloss(y[ok], sigmoid(z[ok]))
        if best is None or ll < best[0]: best = (ll, lam, z)
    if best is None: raise ValueError("inner LOPO could not be fitted (too few events in the training patients)")
    return best[1], best[2]


def choose_predictors(y, log):
    preds = list(PREDICTORS); ev = int(min(y.sum(), (1 - y).sum()))
    for d in FALLBACK_DROP_ORDER:
        if ev / len(preds) >= 10: break
        preds.remove(d); log.append(f"fallback: {ev} events / {len(preds) + 1} slopes < 10 -> dropped {d}")
    return preds


def nested_lopo(rows, y, pid, predictors):
    """Outer LOPO with inner penalty choice + inner-fold Platt. Returns outer predictions and per-fold info."""
    pats = sorted(set(pid)); n = len(rows)
    p_raw = np.full(n, np.nan); p_cal = np.full(n, np.nan); folds = []
    for k in pats:
        tr = np.where(pid != k)[0]; te = np.where(pid == k)[0]
        if y[tr].min() == y[tr].max(): continue
        R = [rows[i] for i in tr]
        lam, z_in = inner_lopo(R, y[tr], pid[tr], predictors)
        ok = np.isfinite(z_in); a, b = platt_fit(z_in[ok], y[tr][ok])
        m = fit(R, y[tr], predictors, lam); zk = m.z([rows[i] for i in te])
        p_raw[te] = sigmoid(zk); p_cal[te] = sigmoid(a * zk + b)
        folds.append(dict(outer=k, lam=float(lam), edf=m.edf, beta=list(map(float, m.beta)), platt=[a, b], n_train=len(tr), n_test=len(te)))
    return p_raw, p_cal, folds


def bootstrap_ci(y, s, pid, fn, B=2000, seed=0):
    rng = np.random.default_rng(seed); pats = np.array(sorted(set(pid))); vals = []
    idx = {q: np.where(pid == q)[0] for q in pats}
    for _ in range(B):
        sel = np.concatenate([idx[q] for q in rng.choice(pats, len(pats))])
        v = fn(y[sel], s[sel])
        if v is not None: vals.append(v)
    return [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))] if vals else None


def stability_report(folds, predictors):
    B = np.array([f["beta"][1:] for f in folds])
    if not len(B): return dict(sign_agreement=None)
    sign = np.sign(B); agree = [float(max((s > 0).mean(), (s < 0).mean())) for s in sign.T]
    return dict(coef_mean=dict(zip(predictors, map(float, B.mean(0)))), coef_sd=dict(zip(predictors, map(float, B.std(0)))),
                sign_agreement=dict(zip(predictors, agree)), min_sign_agreement=float(min(agree)),
                edf=[f["edf"] for f in folds], lam=[f["lam"] for f in folds])


def ordering_threshold(y, p, target_sens=0.9):
    """cut used ONLY to order / prioritise (cSS-compatible band): highest p with outer sensitivity >= target. Never suppresses."""
    pos = np.sort(p[y == 1])
    if not len(pos): return None
    return float(pos[int(np.floor((1 - target_sens) * len(pos)))])
