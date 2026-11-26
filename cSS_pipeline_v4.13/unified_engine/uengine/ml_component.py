"""ml_component.py - PAST EXPERIENCE: learned evidence.

New model (prespecified; feature_schema.INITIAL_COLUMNS, <= 10 input columns):
  L2-penalised logistic regression, intercept unpenalised, Newton / IRLS with step halving, optional sample weights and an
  optional OFFSET. With offset = the (recalibrated) MATH logit, the learned coefficients estimate only the information the
  characteristics add BEYOND the math score - the double-counting control of the fusion design (OVERLAP_AND_DOUBLE_COUNTING.md).
  Preprocessing (median imputation, standardisation) is fitted on the training rows only and stored in the model.
  Penalty: chosen by patient-grouped inner CV; criterion = MEAN of per-inner-fold log loss (each fold scored by its own model, no
  pooling of predictions from different models - the pooling is what produced the low AUCs, see auc_investigation.py).
  No class weighting by default (balanced weights distort calibration; available, recorded when used).

Legacy adapters (verbatim procedures from the snapshot, for comparison on IDENTICAL folds):
  LegacyConfidence  css_confidence.fit / confidence (30 features, median imputation, class-balanced L2; l2 by the verbatim nested
                    LOPO of css_model.lopo as fit_confidence.py does)
  LegacyRanker      train_ranker procedure: css_model prep + fit_lr on the train_ranker FEATURES present, l2 by inner LOPO AUC
  LegacyUnified     uscore.model.fit on three PROXY predictors (synthetic tables have no image-derived x1-x5)"""
from dataclasses import dataclass, field
import numpy as np
from . import provenance as pv
from . import patient_split as ps

LAMBDAS = tuple(float(x) for x in np.logspace(-2, 3, 11))


def sigmoid(z): return 1.0 / (1.0 + np.exp(-np.clip(z, -35, 35)))


def logloss(y, p, w=None):
    p = np.clip(p, 1e-9, 1 - 1e-9); w = np.ones(len(y)) if w is None else w
    return float(-np.sum(w * (y * np.log(p) + (1 - y) * np.log(1 - p))) / np.sum(w))


@dataclass
class Preprocessor:
    median: np.ndarray = None
    mean: np.ndarray = None
    sd: np.ndarray = None
    all_missing: list = field(default_factory=list)
    n_imputed: list = field(default_factory=list)

    def fit(self, X):
        X = np.asarray(X, float)
        med = np.array([np.nanmedian(c) if np.isfinite(c).any() else 0.0 for c in X.T])
        self.all_missing = [j for j, c in enumerate(X.T) if not np.isfinite(c).any()]
        Xi = np.where(np.isfinite(X), X, med)
        self.median, self.mean = med, Xi.mean(0)
        sd = Xi.std(0); self.sd = np.where(sd > 1e-12, sd, 1.0)
        self.n_imputed = [int((~np.isfinite(c)).sum()) for c in X.T]
        return self

    def transform(self, X):
        X = np.asarray(X, float)
        return (np.where(np.isfinite(X), X, self.median) - self.mean) / self.sd


def irls(Z, y, lam, offset=None, w=None, max_iter=100, tol=1e-9):
    """argmax sum_i w_i loglik_i(b0 + Z b + offset) - lam/2 |b|^2. -> beta (intercept first), converged flag, iterations"""
    n, p = Z.shape; A = np.c_[np.ones(n), Z]; b = np.zeros(p + 1)
    off = np.zeros(n) if offset is None else np.asarray(offset, float); w = np.ones(n) if w is None else np.asarray(w, float)
    P = np.eye(p + 1) * lam; P[0, 0] = 0.0
    def obj(bb):
        eta = A @ bb + off
        return float(np.sum(w * (y * eta - np.logaddexp(0, eta))) - 0.5 * bb @ P @ bb)
    f = obj(b)
    for it in range(1, max_iter + 1):
        mu = sigmoid(A @ b + off); W = w * mu * (1 - mu) + 1e-12
        H = A.T @ (W[:, None] * A) + P + 1e-10 * np.eye(p + 1)
        g = A.T @ (w * (y - mu)) - P @ b
        step = np.linalg.solve(H, g); t = 1.0
        while True:
            nb = b + t * step; nf = obj(nb)
            if nf >= f - 1e-12 or t < 1e-6: break
            t *= 0.5
        b, f_old, f = nb, f, nf
        if np.max(np.abs(t * step)) < tol or abs(f - f_old) < tol * (1 + abs(f)): return b, True, it
    return b, False, max_iter


@dataclass
class PenalizedLogistic:
    columns: list
    lam: float = None
    beta: np.ndarray = None
    pre: Preprocessor = None
    converged: bool = None
    class_weight: str = "none"           # 'none' | 'balanced'
    selection_log: list = field(default_factory=list)

    def _w(self, y, w):
        w = np.ones(len(y)) if w is None else np.asarray(w, float)
        if self.class_weight == "balanced":
            pi = np.average(y, weights=w); w = w * np.where(y == 1, 0.5 / pi, 0.5 / (1 - pi))
        return w

    def fit(self, X, y, lam, offset=None, w=None):
        y = np.asarray(y, float)
        if len(np.unique(y)) < 2: raise ValueError("both classes are required to fit")
        self.pre = Preprocessor().fit(X); Z = self.pre.transform(X)
        self.beta, self.converged, _ = irls(Z, y, lam, offset, self._w(y, w)); self.lam = lam
        return self

    def logit(self, X, offset=None):
        Z = self.pre.transform(X); off = 0.0 if offset is None else np.asarray(offset, float)
        return np.c_[np.ones(len(Z)), Z] @ self.beta + off

    def predict(self, X, offset=None): return sigmoid(self.logit(X, offset))

    def contributions(self, X):
        """per-column log-odds contribution b_j * z_j (the learned increment, excluding intercept and offset)"""
        return self.pre.transform(X) * self.beta[1:]

    def fit_nested(self, X, y, patients, offset=None, w=None, n_inner=5, seed=0, lambdas=LAMBDAS):
        """penalty by patient-grouped inner CV (mean per-fold log loss), then refit on all rows given"""
        y = np.asarray(y, float); X = np.asarray(X, float); pats = np.asarray(patients).astype(str)
        off = None if offset is None else np.asarray(offset, float)
        folds = ps.inner_folds(pats, n_inner, seed)
        best, log = None, []
        for lam in lambdas:
            losses = []
            for tr, te in folds:
                if len(np.unique(y[tr])) < 2 or len(te) == 0: continue
                m = PenalizedLogistic(self.columns, class_weight=self.class_weight).fit(X[tr], y[tr], lam, None if off is None else off[tr],
                                                                                         None if w is None else np.asarray(w)[tr])
                losses.append(logloss(y[te], m.predict(X[te], None if off is None else off[te])))
            if not losses: continue
            v = float(np.mean(losses)); log.append(dict(lam=lam, mean_fold_logloss=v, n_folds=len(losses)))
            if best is None or v < best[0] - 1e-12: best = (v, lam)
        if best is None: raise ValueError("no inner fold could be fitted (too few events)")
        self.fit(X, y, best[1], off, w); self.selection_log = log
        self.selection_log.append(dict(chosen=best[1], at_grid_edge=best[1] in (lambdas[0], lambdas[-1])))
        return self


# ---------------- order-keeping (monotone) 1-D logistic fit (2026-11-26)
SLOPE_MIN = 1e-3     # a recalibration / calibration may rescale a score, never reverse its order


def monotone_irls(x, y, lam, w=None):
    """logit = a + b x with b >= SLOPE_MIN. The unconstrained fit is used when its slope is positive; otherwise (the data do not
    support the score's direction - seen 2026-11-26: calibration slope -0.41 turned a 0.92 ranking into 0.09) the slope is held at
    SLOPE_MIN (order kept, probabilities near the base rate) and only the intercept is refitted. -> (a, b, clamped)"""
    x = np.nan_to_num(np.asarray(x, float)); y = np.asarray(y, float)
    beta, _, _ = irls(x[:, None], y, lam, None, w)
    if np.isfinite(beta[1]) and beta[1] >= SLOPE_MIN: return float(beta[0]), float(beta[1]), False
    a, _, _ = irls(np.zeros((len(x), 0)), y, 0.0, SLOPE_MIN * x, w)
    return float(a[0]), SLOPE_MIN, True


# ---------------- math recalibration (2 learned parameters; turns the MATH score into a logit for the fusion offset)
@dataclass
class MathRecalibration:
    """logit P(cSS) = a + b * log(score_v4 + eps). Monotone: it never changes the math ORDER. It is LEARNED (needs labels) and
    is therefore fitted inside the training folds like any model. eps keeps score_v4 = 0 finite."""
    a: float = 0.0
    b: float = 1.0
    eps: float = 0.05
    clamped: bool = False        # 2026-11-26: slope held at SLOPE_MIN (the data gave a negative slope) - the order is never reversed

    def x(self, s): return np.log(np.clip(np.asarray(s, float), 0, None) + self.eps)

    def fit(self, s, y, w=None):
        self.a, self.b, self.clamped = monotone_irls(self.x(s), y, 1e-6, w); return self

    def logit(self, s): return self.a + self.b * self.x(s)


# ---------------- legacy adapters (verbatim snapshot code)
class LegacyConfidence:
    name = "legacy_confidence_v5.10"

    def fit(self, df, y, patients):
        cm, cc = pv.load_legacy("css_model"), pv.load_legacy("css_confidence")
        X = cc.table(df).to_numpy(float)
        oof, log = cm.lopo(X, np.asarray(y, int), np.asarray(patients), nested=True)      # as fit_confidence.py
        l2s = [l["l2"] for l in log if l.get("status") == "evaluated"]
        self.l2 = max(set(l2s), key=l2s.count) if l2s else 1.0
        self.model = cc.fit(df, np.asarray(y, int), self.l2); return self

    def score(self, df):
        return pv.load_legacy("css_confidence").confidence(self.model, df) / 100.0


class LegacyRanker:
    name = "legacy_ranker_v5.2"

    def fit(self, df, y, patients):
        cm, tr = pv.load_legacy("css_model"), pv.load_legacy("train_ranker")
        self.feats = [f for f in tr.FEATURES if f in df.columns and df[f].notna().any()]
        X = df[self.feats].apply(lambda c: c.astype(float)).to_numpy(float); y = np.asarray(y, int); g = np.asarray(patients)
        best = (-1, 1.0)
        for cand in cm.L2_GRID:                                       # as train_ranker.py (final-model l2 by LOPO AUC)
            s_in = cm.lopo(X, y, g, cand)[0]; f_ = np.isfinite(s_in); v = cm.auc(y[f_], s_in[f_])
            if np.isfinite(v) and v > best[0]: best = (v, cand)
        self.l2 = best[1]; Z, self.med, self.mu, self.sd = cm.prep(X); self.w, self.b = cm.fit_lr(Z, y, self.l2); return self

    def score(self, df):
        cm = pv.load_legacy("css_model")
        return cm.predict(df[self.feats].apply(lambda c: c.astype(float)).to_numpy(float), self.med, self.mu, self.sd, self.w, self.b)


class LegacyUnified:
    """uscore.model.fit (ridge LR, training-mean imputation of unreliable values) on PROXY predictors; penalty by the verbatim inner LOPO"""
    name = "legacy_unified_procedure_on_proxies"
    PROXY = {"x1_vessel_continuity_mm": "local_cont_max_mm", "x2_core_contrast_nu": "darkness_z", "x3_pial_distance_mm": "pial_dist_mm"}

    def _rows(self, df):
        return [dict(F={k: dict(value=None if not np.isfinite(float(r[c])) else float(r[c]),
                                 status="reliable" if np.isfinite(float(r[c])) else "unreliable") for k, c in self.PROXY.items()})
                for r in df[list(self.PROXY.values())].to_dict("records")]

    def fit(self, df, y, patients):
        md = pv.load_legacy("uscore.model", "unified_score")
        R = self._rows(df); y = np.asarray(y, float); g = np.asarray(patients).astype(str); preds = list(self.PROXY)
        lam, _ = md.inner_lopo(R, y, g, preds); self.m = md.fit(R, y, preds, lam); return self

    def score(self, df): return self.m.p_raw(self._rows(df))
