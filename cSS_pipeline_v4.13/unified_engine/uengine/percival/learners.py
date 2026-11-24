"""learners.py - Percival v5.23: model families that are COMPARED (never assumed) for Characteristic ML and Image ML. Pure numpy, CPU,
deterministic seeds; no scikit-learn / XGBoost / PyTorch (the shared 'css' environment of the production pipeline is not changed).

CHARACTERISTIC ML candidates (structured measurements of the candidate, CHAR columns):
  logistic   L2-penalised logistic regression, penalty by patient-grouped inner CV (interpretable: one coefficient per measurement)
  gbt        gradient-boosted regression trees of depth 2 (log loss, shrinkage 0.1, 100 rounds, row subsampling 0.8) - captures
             thresholds and pairwise interactions
  forest     random forest of 100 classification trees, depth <= 4, min leaf 5, sqrt(p) features per split, patient-bootstrap rows
  Selection: patient-grouped CV log loss; the SIMPLEST model within one bootstrap SE of the best (order logistic < gbt < forest).
  XGBoost / LightGBM were not used: not installed in the local environment, and with the expected tens-to-hundreds of labelled
  candidates per class their extra capacity is a liability, not an asset (gbt above is the same model family).
IMAGE ML candidates (the candidate's MRI patch pixels, cnn.IN_SHAPE = 3 maps x 49 x 25):
  pixel_logistic   L2 logistic on the maps block-averaged to 3 x 7 x 5 (105 pixels) - the simple image baseline
  cnn              the small convolutional network (cnn.SmallCNN)
  Selection by the same 1-SE rule (the network must beat the linear pixel model to be used).
Missing values: trees impute the training median (recorded in the model); logistic models use the shared Preprocessor."""
import numpy as np
from ..ml_component import PenalizedLogistic, sigmoid

LAMBDAS = np.logspace(-2, 3, 9)
CHAR_KINDS = ["logistic", "gbt", "forest"]          # simplicity order
IMAGE_KINDS = ["pixel_logistic", "cnn"]


# ------------------------------------------------------------------ trees (numpy)
def _impute(X, med):
    X = np.asarray(X, float); return np.where(np.isfinite(X), X, med)


def _candidate_thresholds(x, n=12):
    q = np.unique(np.percentile(x, np.linspace(5, 95, n)))
    return q


class RegTree:
    """least-squares regression tree on (gradient, hessian) for boosting: leaf value = sum g / (sum h + 1)"""
    def __init__(self, depth=2, min_leaf=5): self.depth, self.min_leaf, self.nodes = depth, min_leaf, None

    def fit(self, X, g, h, w):
        self.nodes = []; self._grow(X, g, h, w, np.arange(len(g)), 0); return self

    def _leaf(self, g, h, w, idx):
        return len(self.nodes), self.nodes.append(("leaf", float((w[idx] * g[idx]).sum() / ((w[idx] * h[idx]).sum() + 1.0))))

    def _grow(self, X, g, h, w, idx, d):
        if d >= self.depth or len(idx) < 2 * self.min_leaf: return self._leaf(g, h, w, idx)[0]
        G, Hs = (w[idx] * g[idx]).sum(), (w[idx] * h[idx]).sum(); base = G * G / (Hs + 1.0); best = None
        for j in range(X.shape[1]):
            x = X[idx, j]
            for t in _candidate_thresholds(x):
                L = x <= t; nl = L.sum()
                if nl < self.min_leaf or len(idx) - nl < self.min_leaf: continue
                gl, hl = (w[idx][L] * g[idx][L]).sum(), (w[idx][L] * h[idx][L]).sum()
                gain = gl * gl / (hl + 1.0) + (G - gl) ** 2 / (Hs - hl + 1.0) - base
                if best is None or gain > best[0]: best = (gain, j, float(t), L)
        if best is None or best[0] <= 1e-9: return self._leaf(g, h, w, idx)[0]
        _, j, t, L = best; me = len(self.nodes); self.nodes.append(None)
        l = self._grow(X, g, h, w, idx[L], d + 1); r = self._grow(X, g, h, w, idx[~L], d + 1)
        self.nodes[me] = ("split", j, t, l, r); return me

    def predict(self, X):
        out = np.empty(len(X))
        for i, x in enumerate(X):
            k = 0
            while self.nodes[k][0] == "split":
                _, j, t, l, r = self.nodes[k]; k = l if x[j] <= t else r
            out[i] = self.nodes[k][1]
        return out


class ClsTree:
    """Gini classification tree; leaf = weighted P(y=1) (Laplace-smoothed)"""
    def __init__(self, depth=4, min_leaf=5, mtry=None, rng=None):
        self.depth, self.min_leaf, self.mtry, self.rng, self.nodes = depth, min_leaf, mtry, rng or np.random.default_rng(0), None

    def fit(self, X, y, w):
        self.nodes = []; self._grow(X, y, w, np.arange(len(y)), 0); return self

    def _leaf(self, y, w, idx):
        k = len(self.nodes); self.nodes.append(("leaf", float(((w[idx] * y[idx]).sum() + 1) / (w[idx].sum() + 2)))); return k

    def _grow(self, X, y, w, idx, d):
        yy, ww = y[idx], w[idx]; W = ww.sum(); p = (ww * yy).sum() / max(W, 1e-12)
        if d >= self.depth or len(idx) < 2 * self.min_leaf or p in (0.0, 1.0): return self._leaf(y, w, idx)
        feats = np.arange(X.shape[1]) if not self.mtry else self.rng.choice(X.shape[1], min(self.mtry, X.shape[1]), replace=False)
        parent = W * 2 * p * (1 - p); best = None
        for j in feats:
            x = X[idx, j]
            for t in _candidate_thresholds(x):
                L = x <= t; nl = L.sum()
                if nl < self.min_leaf or len(idx) - nl < self.min_leaf: continue
                wl, wr = ww[L].sum(), ww[~L].sum(); pl = (ww[L] * yy[L]).sum() / max(wl, 1e-12); pr = (ww[~L] * yy[~L]).sum() / max(wr, 1e-12)
                gain = parent - wl * 2 * pl * (1 - pl) - wr * 2 * pr * (1 - pr)
                if best is None or gain > best[0]: best = (gain, j, float(t), L)
        if best is None or best[0] <= 1e-12: return self._leaf(y, w, idx)
        _, j, t, L = best; me = len(self.nodes); self.nodes.append(None)
        l = self._grow(X, y, w, idx[L], d + 1); r = self._grow(X, y, w, idx[~L], d + 1)
        self.nodes[me] = ("split", int(j), t, l, r); return me

    predict = RegTree.predict


def _tree_json(t): return [list(n) for n in t.nodes]
def _tree_from(nodes, cls):
    t = cls.__new__(cls); t.nodes = [tuple(n) for n in nodes]; return t


def _balanced(y, w):
    w = np.ones(len(y)) if w is None else np.asarray(w, float); pi = np.average(y, weights=w)
    return w * np.where(y == 1, 0.5 / max(pi, 1e-3), 0.5 / max(1 - pi, 1e-3))


class GBTrees:
    def __init__(self, columns, n=100, lr=0.1, depth=2, subsample=0.8, seed=0):
        self.columns, self.n, self.lr, self.depth, self.subsample, self.seed = list(columns), n, lr, depth, subsample, seed
        self.trees, self.f0, self.median = [], 0.0, None

    def fit(self, X, y, w=None):
        X = np.asarray(X, float); y = np.asarray(y, float)
        if len(np.unique(y)) < 2: raise ValueError("both classes are required to fit")
        self.median = np.array([np.nanmedian(c) if np.isfinite(c).any() else 0.0 for c in X.T]); Xi = _impute(X, self.median)
        w = _balanced(y, w); rng = np.random.default_rng(self.seed); F = np.zeros(len(y)); self.f0 = 0.0; self.trees = []
        for _ in range(self.n):
            p = sigmoid(F); g = y - p; h = np.maximum(p * (1 - p), 1e-6)
            s = rng.random(len(y)) < self.subsample
            if s.sum() < 10 or len(np.unique(y[s])) < 2: s = np.ones(len(y), bool)
            t = RegTree(self.depth).fit(Xi[s], g[s], h[s], w[s]); self.trees.append(t); F += self.lr * t.predict(Xi)
        return self

    def logit(self, X):
        Xi = _impute(X, self.median); return self.f0 + self.lr * sum((t.predict(Xi) for t in self.trees), np.zeros(len(Xi)))

    def importance(self):
        c = np.zeros(len(self.columns))
        for t in self.trees:
            for nd in t.nodes:
                if nd[0] == "split": c[nd[1]] += 1
        return dict(zip(self.columns, (c / max(c.sum(), 1)).round(3).tolist()))

    def to_json(self): return dict(type="gbt", columns=self.columns, lr=self.lr, f0=self.f0, median=self.median.tolist(), trees=[_tree_json(t) for t in self.trees])

    @classmethod
    def from_json(cls, d):
        m = cls(d["columns"], lr=d["lr"]); m.f0, m.median = d["f0"], np.array(d["median"], float); m.trees = [_tree_from(t, RegTree) for t in d["trees"]]; return m


class Forest:
    def __init__(self, columns, n=100, depth=4, min_leaf=5, seed=0):
        self.columns, self.n, self.depth, self.min_leaf, self.seed, self.trees, self.median = list(columns), n, depth, min_leaf, seed, [], None

    def fit(self, X, y, w=None, groups=None):
        X = np.asarray(X, float); y = np.asarray(y, float)
        if len(np.unique(y)) < 2: raise ValueError("both classes are required to fit")
        self.median = np.array([np.nanmedian(c) if np.isfinite(c).any() else 0.0 for c in X.T]); Xi = _impute(X, self.median)
        w = _balanced(y, w); rng = np.random.default_rng(self.seed); mtry = max(1, int(round(np.sqrt(X.shape[1])))); self.trees = []
        g = np.asarray(groups).astype(str) if groups is not None else np.arange(len(y)).astype(str); u = np.unique(g); gi = {k: np.where(g == k)[0] for k in u}
        for _ in range(self.n):
            idx = np.concatenate([gi[k] for k in rng.choice(u, len(u))])                # bootstrap of PATIENTS (not rows)
            if len(np.unique(y[idx])) < 2: idx = np.arange(len(y))
            self.trees.append(ClsTree(self.depth, self.min_leaf, mtry, rng).fit(Xi[idx], y[idx], w[idx]))
        return self

    def proba(self, X):
        Xi = _impute(X, self.median); return np.mean([t.predict(Xi) for t in self.trees], axis=0)

    def logit(self, X):
        p = np.clip(self.proba(X), 1e-4, 1 - 1e-4); return np.log(p / (1 - p))

    def importance(self):
        c = np.zeros(len(self.columns))
        for t in self.trees:
            for nd in t.nodes:
                if nd[0] == "split": c[nd[1]] += 1
        return dict(zip(self.columns, (c / max(c.sum(), 1)).round(3).tolist()))

    def to_json(self): return dict(type="forest", columns=self.columns, median=self.median.tolist(), trees=[_tree_json(t) for t in self.trees])

    @classmethod
    def from_json(cls, d):
        m = cls(d["columns"]); m.median = np.array(d["median"], float); m.trees = [_tree_from(t, ClsTree) for t in d["trees"]]; return m


# ------------------------------------------------------------------ one interface for every tabular model
def pl_json(m): return dict(type="logistic", columns=m.columns, lam=m.lam, beta=m.beta.tolist(), median=m.pre.median.tolist(), mean=m.pre.mean.tolist(), sd=m.pre.sd.tolist())


def pl_from(q):
    class _Pre:
        def __init__(self, q): self.median, self.mean, self.sd = (np.array(q[k], float) for k in ("median", "mean", "sd")); self.n_imputed = [0] * len(self.mean)
        def transform(self, X): X = np.asarray(X, float); return (np.where(np.isfinite(X), X, self.median) - self.mean) / self.sd
    m = PenalizedLogistic(list(q["columns"])); m.beta = np.array(q["beta"], float); m.lam = q["lam"]; m.pre = _Pre(q); return m


def fit_tabular(kind, X, y, g, w, cols, seed=0):
    """-> fitted model with .logit(X), or None when it cannot be fitted"""
    X = np.asarray(X, float); y = np.asarray(y, float)
    if not np.isfinite(X).any() or len(np.unique(y)) < 2: return None
    try:
        if kind == "logistic":
            m = PenalizedLogistic(list(cols), class_weight="balanced")
            return m.fit_nested(X, y, g, w=w, lambdas=LAMBDAS) if len(np.unique(g)) >= 3 else m.fit(X, y, 1.0, w=w)
        if kind == "gbt": return GBTrees(cols, seed=seed).fit(X, y, w)
        if kind == "forest": return Forest(cols, seed=seed).fit(X, y, w, groups=g)
    except ValueError:
        if kind == "logistic":
            try: return PenalizedLogistic(list(cols), class_weight="balanced").fit(X, y, 1.0, w=w)
            except ValueError: return None
        return None
    raise ValueError(f"unknown model kind {kind}")


def tab_json(m):
    if m is None: return None
    if isinstance(m, PenalizedLogistic): return pl_json(m)
    return m.to_json()


def tab_from(d):
    if d is None: return None
    t = d.get("type", "logistic")
    return GBTrees.from_json(d) if t == "gbt" else Forest.from_json(d) if t == "forest" else pl_from(d)


def importance(m):
    if m is None: return None
    if isinstance(m, PenalizedLogistic): return dict(kind="standardised coefficient", values=dict(zip(m.columns, np.round(m.beta[1:], 3).tolist())))
    return dict(kind="share of tree splits", values=m.importance())


# ------------------------------------------------------------------ image baseline
POOL = (7, 5)


def pool_maps(M):
    """(N, 3, 49, 25) -> (N, 105) block means (7 x 5 blocks per map)"""
    M = np.asarray(M, np.float32); N, C, H, W = M.shape; bh, bw = H // POOL[0], W // POOL[1]
    return M[:, :, :bh * POOL[0], :bw * POOL[1]].reshape(N, C, POOL[0], bh, POOL[1], bw).mean(axis=(3, 5)).reshape(N, -1)


POOL_COLS = [f"m{c}_{i}_{j}" for c in range(3) for i in range(POOL[0]) for j in range(POOL[1])]


class PixelLogistic:
    """the simple image model: L2 logistic on block-averaged patch pixels; flip-augmented training (u axis, as the CNN)"""
    def __init__(self, seed=0): self.seed, self.m = seed, None

    def fit(self, M, y, groups, epochs=None):
        M = np.asarray(M, np.float32); Mf = M[:, :, ::-1, :]
        X = np.r_[pool_maps(M), pool_maps(Mf)]; yy = np.r_[y, y]; gg = np.r_[np.asarray(groups).astype(str)] ; gg = np.r_[gg, gg]
        self.m = PenalizedLogistic(POOL_COLS, class_weight="balanced")
        try: self.m.fit_nested(X, yy, gg, lambdas=np.logspace(0, 4, 7)) if len(np.unique(gg)) >= 3 else self.m.fit(X, yy, 10.0)
        except ValueError: self.m.fit(X, yy, 10.0)
        return self

    def logit(self, M, batch=None): return self.m.logit(pool_maps(M)) if len(M) else np.zeros(0)

    def logit_tta(self, M):
        a, b = self.logit(M), self.logit(np.asarray(M)[:, :, ::-1, :]); return (a + b) / 2, np.abs(a - b) / 2

    def to_json(self): return dict(arch="PixelLogistic(3x7x5 block means)", type="pixel_logistic", model=pl_json(self.m))

    @classmethod
    def from_json(cls, d): x = cls(); x.m = pl_from(d["model"]); return x


def image_model_from(d):
    from .cnn import SmallCNN
    if d is None: return None
    if d.get("type") == "cnn_ensemble":
        from .cnn import SeedEnsemble
        return SeedEnsemble.from_json(d)
    return PixelLogistic.from_json(d) if d.get("type") == "pixel_logistic" else SmallCNN.from_json(d)
