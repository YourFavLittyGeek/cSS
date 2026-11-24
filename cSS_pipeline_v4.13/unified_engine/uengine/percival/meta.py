"""meta.py - PERCIVAL SCORE: components, meta-assessment discovery, calibration, thresholds, uncertainty, acceptance (v5.22; v5.23 additions
below). Local, numpy.
v5.23: Characteristic ML, Image ML and Fusion each choose their model FAMILY by patient-grouped CV (learners.py; fusion late / feature /
hybrid, with a paired test of whether fusion beats the better single model); Percival Intelligence analyses (intelligence.py: input
provenance, ablation, disagreement patterns, out-of-distribution, reliability table); bootstrap-stable thresholds; per-candidate reasons.

COMPONENTS (level 0; each an independent, traceable assessment of a candidate; trained with patient-grouped out-of-fold predictions):
  math     MATH - the deterministic detector score (score_v4), Platt-recalibrated to log-odds (monotone: never changes the MATH order)
  unified  Unified Score - the structured predictor model: L2 logistic on the 5 predictors x1-x5 (vessel continuity, core contrast,
           pial distance, sulcal alignment, extracranial continuation)
  char     Characteristic ML - L2 logistic on the detector's measured candidate characteristics (darkness, edge contrast, pial distance,
           cortex fraction, tram fraction, tube ratio, elongation, volume, local continuity)
  image    Image ML - a small convolutional network on the candidate's MRI patch pixels (cnn.py)
  fusion   Fusion - feature-level fusion of characteristics + the image network's out-of-fold logit (L2 logistic)
Fusion already contains Characteristic and Image information, so no meta-model uses fusion together with char or image (double counting).

META-MODEL DISCOVERY (on the development cohort only; the locked test cohort is not touched until the final evaluation):
  M0 math_only        MATH alone (the existing system; baseline)
  M1 fusion_only      Fusion alone
  M2 equal_mean       mean of the available component log-odds (math, unified, char, image) - a fixed, NOT learned, combination
  M3 stack_logit      logistic stacking on math, unified, char, image log-odds + missing-input indicators (light penalty)
  M4 stack_reg        regularised stacking (penalty by nested CV) + disagreement terms (spread and max pairwise gap of the log-odds)
  M5 stack_fusion     regularised stacking on math, unified, fusion (the double-counting-free alternative to M4)
  M6 boosted          gradient-boosted decision stumps on the M4 inputs (only when both classes have >= 50 candidates)
  Each is evaluated by patient-grouped cross-validation on the out-of-fold component table (log loss, Brier, AUC, PR-AUC, calibration
  slope / intercept). Selection: the SIMPLEST model whose log loss is within one bootstrap standard error of the best (1-SE rule) - a
  more complex model must earn its place.
FINAL: components refitted on the whole development cohort, the selected meta-model on the out-of-fold table, Platt calibration on its
out-of-fold log-odds. Percival Score = 100 x calibrated probability (bounded 0-100).
THRESHOLDS (documented strategy): from the development out-of-fold calibrated scores - red below the highest score that keeps
sensitivity >= 0.95 (missing a cSS is the costlier error in a reader-assisted workflow), green at or above the lowest score with
specificity >= 0.90, yellow between. Reported with their sensitivity / specificity on the locked test cohort.
UNCERTAINTY: a 20-member patient-bootstrap ensemble of the meta-model gives a score spread; inputs missing / unreliable are counted;
component disagreement is reported. A candidate with no learned evidence (only MATH, or nothing) is 'insufficient evidence' - never a
reassuring low score.
ACCEPTANCE (promotion of a newly trained model): minimum data; on the locked test cohort AUC >= MATH alone, AUC >= active model - 0.01,
Brier <= active + 0.01, calibration slope in [0.6, 1.6]; no data-integrity error. Otherwise the model stays a candidate (kept, reported).
"""
import datetime, hashlib, json
import numpy as np
from ..ml_component import PenalizedLogistic, MathRecalibration, sigmoid, irls
from .cnn import SmallCNN
from . import learners as LR, intelligence as IN
from .learners import PixelLogistic

PREDICTORS = ["x1_vessel_continuity_mm", "x2_core_contrast_nu", "x3_pial_distance_mm", "x4_sulcal_alignment", "x5_extracranial_mm"]
CHAR = ["darkness_z", "edge_contrast", "pial_dist_mm", "cortex_frac", "tram_frac", "tube_ratio", "elongation_3d", "log_volume_mm3", "local_cont_max_mm"]
COMPONENTS = ["math", "unified", "char", "image", "fusion"]
INDEP = ["math", "unified", "char", "image"]
LAMBDAS = np.logspace(-2, 3, 9)
SIMPLICITY = ["math_only", "equal_mean", "fusion_only", "stack_logit", "stack_fusion", "stack_reg", "boosted"]
MIN_STUDIES, MIN_CANDIDATES, MIN_PER_CLASS = 30, 100, 10
TEST_FRACTION = 0.2
CAL_LAMBDA = 1.0


def now(): return datetime.datetime.now().isoformat(timespec="seconds")
def logit(p): p = np.clip(p, 1e-6, 1 - 1e-6); return np.log(p / (1 - p))


# ------------------------------------------------------------------ metrics
def auc(y, s):
    y = np.asarray(y); s = np.asarray(s, float); m = np.isfinite(s); y, s = y[m], s[m]
    if (y == 1).sum() == 0 or (y == 0).sum() == 0: return None
    order = s.argsort(kind="mergesort"); r = np.empty(len(s)); r[order] = np.arange(1, len(s) + 1)
    for v in np.unique(s):
        k = s == v
        if k.sum() > 1: r[k] = r[k].mean()
    n1 = (y == 1).sum(); return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * (y == 0).sum()))


def pr_auc(y, s):
    y = np.asarray(y); s = np.asarray(s, float); o = np.argsort(-s); y = y[o]; tp = np.cumsum(y); fp = np.cumsum(1 - y)
    if tp[-1] == 0: return None
    prec = tp / np.maximum(tp + fp, 1); rec = tp / tp[-1]; return float(np.sum(np.diff(np.r_[0, rec]) * prec))


def calib(y, p):
    """calibration slope / intercept (logistic recalibration of logit p)"""
    z = logit(np.asarray(p, float))[:, None]
    try: b, _, _ = irls(z, np.asarray(y, float), 1e-6); return float(b[1]), float(b[0])
    except Exception: return None, None


def metrics(y, p, groups=None, boot=200, seed=0):
    y = np.asarray(y, float); p = np.asarray(p, float); m = np.isfinite(p); y, p = y[m], p[m]
    if len(y) < 5 or len(np.unique(y)) < 2: return dict(n=int(len(y)), auc=None)
    pc = np.clip(p, 1e-6, 1 - 1e-6); sl, ic = calib(y, pc)
    out = dict(n=int(len(y)), n_pos=int(y.sum()), auc=auc(y, p), pr_auc=pr_auc(y, p), brier=float(np.mean((p - y) ** 2)),
               logloss=float(-np.mean(y * np.log(pc) + (1 - y) * np.log(1 - pc))), calib_slope=sl, calib_intercept=ic)
    if groups is not None and boot:
        g = np.asarray(groups).astype(str)[m]; u = np.unique(g); idx = {k: np.where(g == k)[0] for k in u}; rng = np.random.default_rng(seed); A, L = [], []
        for _ in range(boot):
            t = np.concatenate([idx[k] for k in rng.choice(u, len(u))]); a = auc(y[t], p[t])
            if a is not None: A.append(a)
            L.append(-np.mean(y[t] * np.log(pc[t]) + (1 - y[t]) * np.log(1 - pc[t])))
        out["auc_ci"] = [float(np.percentile(A, 2.5)), float(np.percentile(A, 97.5))] if len(A) > 20 else None
        out["logloss_se"] = float(np.std(L))
    return out


def sens_spec(y, p, t):
    y = np.asarray(y); p = np.asarray(p); pos = p >= t
    return dict(threshold=float(t), sensitivity=float((pos & (y == 1)).sum() / max((y == 1).sum(), 1)), specificity=float((~pos & (y == 0)).sum() / max((y == 0).sum(), 1)))


# ------------------------------------------------------------------ patient partitions
ENGINE = "percival-engine/5.25"


def folds(groups, k=5, seed=0):
    g = np.asarray(groups).astype(str); u = np.unique(g); r = np.random.default_rng(seed); u = u[r.permutation(len(u))]
    k = max(2, min(k, len(u))); parts = [u[i::k] for i in range(k)]
    return [(np.where(~np.isin(g, p))[0], np.where(np.isin(g, p))[0]) for p in parts]


def test_assignment(patient, fraction=TEST_FRACTION, salt="percival-test-cohort-v1"):
    """deterministic, permanent: a patient is in the locked test cohort iff the hash of its id falls below the fraction"""
    h = int(hashlib.sha256((salt + str(patient)).encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return h < fraction


def patient_weights(rows, cap=20):
    """one patient with many candidates must not dominate: weight = min(1, cap / candidates of that patient)"""
    from collections import Counter
    n = Counter(r["patient"] for r in rows); return np.array([min(1.0, cap / n[r["patient"]]) for r in rows])


# ------------------------------------------------------------------ inputs
def X_of(rows, cols, key):
    return np.array([[(r.get(key) or {}).get(c, np.nan) if (r.get(key) or {}).get(c) is not None else np.nan for c in cols] for r in rows], float)


def patch_stats(M):
    """v5.24 image out-of-distribution descriptor: per channel mean, SD and mean absolute gradient along each patch axis (structure)"""
    M = np.asarray(M, np.float32)
    if M.ndim == 3: M = M[None]
    ax = tuple(range(2, M.ndim)); f = [M.mean(ax), M.std(ax)]
    for a in range(2, M.ndim): f.append(np.abs(np.diff(M, axis=a)).mean(ax))
    return np.concatenate(f, axis=1)


def maps_of(rows):
    have = np.array([r.get("maps") is not None for r in rows])
    from .cnn import IN_SHAPE
    M = np.zeros((len(rows),) + IN_SHAPE, np.float32)
    for i, r in enumerate(rows):
        if r.get("maps") is not None: M[i] = np.asarray(r["maps"], np.float32)
    return M, have


def _pl_fit(X, y, g, w, cols, nested=True):
    ok = np.isfinite(X).any(0)
    if not ok.any() or len(np.unique(y)) < 2: return None
    m = PenalizedLogistic(list(cols), class_weight="balanced")
    try: return m.fit_nested(X, y, g, w=w, lambdas=LAMBDAS) if nested and len(np.unique(g)) >= 3 else m.fit(X, y, 1.0, w=w)
    except ValueError:
        try: return m.fit(X, y, 1.0, w=w)
        except ValueError: return None


# ------------------------------------------------------------------ level-0 components
FUSION_KINDS = ["late", "feature", "hybrid"]          # simplicity order
FUSION_DOC = dict(late="decision-level: logistic on the Characteristic ML and Image ML log-odds",
                  feature="feature-level: logistic on the measured characteristics + the Image ML log-odds",
                  hybrid="hybrid: logistic on the characteristics + the Image ML log-odds + the Characteristic ML log-odds")


def _fusion_X(kind, Xc, il, cl):
    il = np.asarray(il, float)[:, None]; cl = np.asarray(cl, float)[:, None]
    return np.c_[cl, il] if kind == "late" else np.c_[Xc, il] if kind == "feature" else np.c_[Xc, il, cl]


def _fusion_cols(kind): return ["char_logit", "image_logit"] if kind == "late" else CHAR + ["image_logit"] if kind == "feature" else CHAR + ["image_logit", "char_logit"]


def _fit_image(kind, M, y, g, seed, epochs):
    if kind == "pixel_logistic": return PixelLogistic(seed).fit(M, y, g)
    return SmallCNN(seed).fit(M, y, g, epochs=epochs)


class Components:
    """fit on rows -> predict log-odds of each component (NaN when the component has no input for a row).
    v5.23: the model family of Characteristic ML (logistic / gbt / forest), Image ML (pixel_logistic / cnn) and Fusion (late / feature /
    hybrid) is chosen by component_oof() on patient-grouped CV and passed in; the defaults reproduce v5.22."""
    def __init__(self, char_kind="logistic", image_kind="cnn", fusion_kind="feature"):
        self.char_kind, self.image_kind, self.fusion_kind = char_kind, image_kind, fusion_kind; self.ood = None; self.image_ood = None

    def fit(self, rows, seed=0, image_logit_oof=None, char_logit_oof=None, cnn_epochs=30):
        y = np.array([r["y"] for r in rows], float); g = [r["patient"] for r in rows]; w = patient_weights(rows)
        self.math = MathRecalibration().fit(np.array([r["math"] for r in rows], float), y, w)
        self.unified = _pl_fit(X_of(rows, PREDICTORS, "pred"), y, g, w, PREDICTORS)
        Xc = X_of(rows, CHAR, "char"); self.char = LR.fit_tabular(self.char_kind, Xc, y, g, w, CHAR, seed)
        M, have = maps_of(rows); self.image = None
        if cnn_epochs and have.sum() >= 20 and len(np.unique(y[have])) == 2:
            try: self.image = _fit_image(self.image_kind, M[have], y[have], np.asarray(g)[have], seed, cnn_epochs)
            except ValueError: self.image = None
        il = image_logit_oof if image_logit_oof is not None else self._img(rows)[0]
        cl = char_logit_oof if char_logit_oof is not None else self._char(Xc)
        self.fusion = None
        if np.isfinite(il).sum() >= 10:
            self.fusion = _pl_fit(_fusion_X(self.fusion_kind, Xc, il, cl), y, g, w, _fusion_cols(self.fusion_kind))
        self.ood = IN.OOD().fit(np.c_[Xc, X_of(rows, PREDICTORS, "pred")])
        self.image_ood = IN.OOD().fit(patch_stats(M[have])) if have.sum() >= 20 else None      # v5.24: patches unlike the training patches
        return self

    def _char(self, Xc):
        out = np.full(len(Xc), np.nan)
        if self.char is not None:
            have = np.isfinite(Xc).any(1)
            if have.any(): out[have] = self.char.logit(Xc[have])
        return out

    def _img(self, rows):
        out = np.full(len(rows), np.nan); sp = np.full(len(rows), np.nan)
        if self.image is None: return out, sp
        M, have = maps_of(rows)
        if have.any(): out[have], sp[have] = self.image.logit_tta(M[have])
        return out, sp

    def predict(self, rows, extras=False):
        s = np.array([r["math"] for r in rows], float); Z = dict(math=self.math.logit(s))
        X = X_of(rows, PREDICTORS, "pred"); out = np.full(len(rows), np.nan)
        if self.unified is not None:
            have = np.isfinite(X).any(1)
            if have.any(): out[have] = self.unified.logit(X[have])
        Z["unified"] = out; Xc = X_of(rows, CHAR, "char"); Z["char"] = self._char(Xc)
        Z["image"], spread = self._img(rows)
        out = np.full(len(rows), np.nan)
        if self.fusion is not None and self.image is not None:
            have = np.isfinite(Z["image"])                                  # fusion is defined only where the image model has an output
            if have.any(): out[have] = self.fusion.logit(_fusion_X(self.fusion_kind, Xc[have], Z["image"][have], Z["char"][have]))
        Z["fusion"] = out
        if not extras: return Z
        ood = self.ood.distance(np.c_[Xc, X]) if self.ood is not None else np.full(len(rows), np.nan)
        iood = np.full(len(rows), np.nan)
        if self.image_ood is not None:
            Mm, have = maps_of(rows)
            if have.any(): iood[have] = self.image_ood.distance(patch_stats(Mm[have]))
        return Z, dict(image_spread=spread, ood=ood, ood_limit=self.ood.limit if self.ood is not None else None, image_ood=iood,
                       image_ood_limit=self.image_ood.limit if self.image_ood is not None else None)

    def to_json(self):
        return dict(kinds=dict(char=self.char_kind, image=self.image_kind, fusion=self.fusion_kind),
                    math=dict(a=self.math.a, b=self.math.b, eps=self.math.eps), unified=LR.tab_json(self.unified), char=LR.tab_json(self.char),
                    image=None if self.image is None else self.image.to_json(), fusion=LR.tab_json(self.fusion),
                    ood=None if self.ood is None else self.ood.to_json(), image_ood=None if self.image_ood is None else self.image_ood.to_json())

    @classmethod
    def from_json(cls, d):
        k = d.get("kinds") or dict(char="logistic", image="cnn", fusion="feature")          # v5.22 models: the old fixed families
        c = cls(k["char"], k["image"], k["fusion"]); c.math = MathRecalibration(**d["math"]); c.unified = LR.tab_from(d["unified"])
        c.char = LR.tab_from(d["char"]); c.image = LR.image_model_from(d.get("image"))
        f = d.get("fusion"); c.fusion = c.char if f == "char" else LR.tab_from(f)
        if f == "char": c.fusion = None                                       # v5.22 stored 'char' when no image model existed
        c.ood = IN.OOD.from_json(d["ood"]) if d.get("ood") else None
        c.image_ood = IN.OOD.from_json(d["image_ood"]) if d.get("image_ood") else None; return c          # models before v5.24: none


def _select(oofs, y, g, order):
    """1-SE rule over candidate OOF predictions (log-odds) -> chosen kind, metrics per kind"""
    res = {k: metrics(y[np.isfinite(v)], sigmoid(v[np.isfinite(v)]), np.asarray(g)[np.isfinite(v)]) if np.isfinite(v).sum() >= 5 else dict(n=int(np.isfinite(v).sum()))
           for k, v in oofs.items()}
    ok = {k: r for k, r in res.items() if r.get("logloss") is not None}
    if not ok: return None, res
    best = min(ok, key=lambda k: ok[k]["logloss"])
    se = ok[best].get("logloss_se")
    has_se = se is not None and np.isfinite(se) and se > 0
    lim = ok[best]["logloss"] + (se if has_se else 0.0)
    return next(k for k in order if k in ok and ok[k]["logloss"] <= lim), res


def _common(oofs):
    m = np.ones(len(next(iter(oofs.values()))), bool)
    for v in oofs.values(): m &= np.isfinite(v)
    return m


def component_oof(rows, k=5, seed=0, cnn_epochs=30, progress=None, char_kinds=None, image_kinds=None, fusion_kinds=None):
    """patient-grouped out-of-fold log-odds of every component for the given (development) rows, and the model-family comparisons
    (Characteristic ML, Image ML, Fusion) on the SAME folds. -> Z, report"""
    say = progress or (lambda *a: None)
    char_kinds = char_kinds or LR.CHAR_KINDS; image_kinds = image_kinds or LR.IMAGE_KINDS; fusion_kinds = fusion_kinds or FUSION_KINDS
    y = np.array([r["y"] for r in rows], float); g = np.array([r["patient"] for r in rows]); w = patient_weights(rows); F = folds(g, k, seed)
    Xc = X_of(rows, CHAR, "char"); M, have = maps_of(rows); rep = {}
    # 1. Image ML families (their OOF logit is an input of Fusion)
    img = {kd: np.full(len(rows), np.nan) for kd in image_kinds}; spread = np.full(len(rows), np.nan)
    for i, (tr, te) in enumerate(F):
        htr, hte = tr[have[tr]], te[have[te]]
        if len(htr) >= 20 and len(np.unique(y[htr])) == 2 and len(hte):
            for kd in image_kinds:
                try:
                    net = _fit_image(kd, M[htr], y[htr], g[htr], seed + i, cnn_epochs); lg, sp = net.logit_tta(M[hte]); img[kd][hte] = lg
                    if kd == "cnn": spread[hte] = sp
                except ValueError: pass
        say(f"image models fold {i + 1}/{len(F)}", 0.1 + 0.25 * (i + 1) / len(F))
    m = _common(img); ik, ires = _select({kd: np.where(m, v, np.nan) for kd, v in img.items()}, y, g, LR.IMAGE_KINDS)
    ik = ik or image_kinds[-1]; img_oof = img[ik]
    rep["image"] = dict(chosen=ik, results=ires, n_with_image=int(have.sum()), tta_spread_median=float(np.nanmedian(spread)) if np.isfinite(spread).any() else None,
                        rule="simplest image model within one bootstrap SE of the lowest CV log loss (pixel_logistic < cnn)", compared_on=int(m.sum()))
    # 2. Characteristic ML families
    ch = {kd: np.full(len(rows), np.nan) for kd in char_kinds}
    for i, (tr, te) in enumerate(F):
        if len(np.unique(y[tr])) < 2: continue
        for kd in char_kinds:
            mdl = LR.fit_tabular(kd, Xc[tr], y[tr], g[tr], w[tr], CHAR, seed + i)
            if mdl is not None:
                hv = np.isfinite(Xc[te]).any(1)
                if hv.any(): ch[kd][te[hv]] = mdl.logit(Xc[te[hv]])
        say(f"characteristic models fold {i + 1}/{len(F)}", 0.35 + 0.15 * (i + 1) / len(F))
    ck, cres = _select(ch, y, g, LR.CHAR_KINDS); ck = ck or "logistic"
    final_char = LR.fit_tabular(ck, Xc, y, g, w, CHAR, seed)
    rep["char"] = dict(chosen=ck, results=cres, importance=LR.importance(final_char), rule="simplest model within one bootstrap SE of the lowest CV log loss (logistic < gbt < forest)",
                       feature_auc={c: auc(y, (Xc[:, j] if np.isfinite(Xc[:, j]).sum() >= 5 else np.full(len(y), np.nan))) for j, c in enumerate(CHAR)})
    # 3. every component out-of-fold + Fusion families. Fusion is a second-level model: it is trained on the Characteristic and Image
    #    log-odds of the TRAINING rows, which must themselves be out-of-sample AND must never come from a model that saw the held-out
    #    fold. v5.25 fix (indirect validation leakage): before, the training rows' image log-odds were img_oof[tr] - produced by image
    #    models fitted on the other outer folds, i.e. INCLUDING the held-out fold te. Now both the Characteristic and the Image inputs of
    #    the training rows come from an inner patient-grouped CV restricted to tr; the held-out rows get the outputs of models fitted on
    #    tr only (char: the fold model; image: an image model refitted on tr). No row of te influences anything fitted for fold i.
    Z = {c: np.full(len(rows), np.nan) for c in COMPONENTS}; fu = {kd: np.full(len(rows), np.nan) for kd in fusion_kinds}
    fold_prov = []
    for i, (tr, te) in enumerate(F):
        assert not set(g[tr]) & set(g[te]), "patient in both the training and the held-out fold"
        R = [rows[j] for j in tr]; T = [rows[j] for j in te]
        if len(np.unique(y[tr])) < 2: continue
        c = Components(ck, ik, fusion_kinds[0]).fit(R, seed, image_logit_oof=np.full(len(tr), np.nan), char_logit_oof=np.zeros(len(tr)), cnn_epochs=0)
        P = c.predict(T)
        for k_ in ("math", "unified", "char"): Z[k_][te] = P[k_]
        inner = np.full(len(tr), np.nan); inner_img = np.full(len(tr), np.nan); htr_all = have[tr]
        for itr, ite in folds(g[tr], 3, seed + 31 + i):
            if len(np.unique(y[tr][itr])) < 2: continue
            mi = LR.fit_tabular(ck, Xc[tr][itr], y[tr][itr], g[tr][itr], w[tr][itr], CHAR, seed)
            if mi is not None: inner[ite] = mi.logit(Xc[tr][ite])
            a, b = itr[htr_all[itr]], ite[htr_all[ite]]                  # inner image model: inner-training patients of tr only
            if len(a) >= 20 and len(np.unique(y[tr][a])) == 2 and len(b):
                try: inner_img[b] = _fit_image(ik, M[tr][a], y[tr][a], g[tr][a], seed + 31 + i, cnn_epochs).logit_tta(M[tr][b])[0]
                except ValueError: pass
        inner = np.where(np.isfinite(inner), inner, np.nanmedian(inner) if np.isfinite(inner).any() else 0.0)
        hte = np.isfinite(img_oof[te])                                      # img_oof[te]: image model fitted on tr only (step 1)
        if np.isfinite(inner_img).sum() >= 10 and hte.any():
            fin = np.isfinite(inner_img)
            for kd in fusion_kinds:
                f = _pl_fit(_fusion_X(kd, Xc[tr][fin], inner_img[fin], inner[fin]), y[tr][fin], g[tr][fin], w[tr][fin], _fusion_cols(kd))
                if f is not None: fu[kd][te[hte]] = f.logit(_fusion_X(kd, Xc[te][hte], img_oof[te][hte], P["char"][hte]))
        fold_prov.append(dict(fold=i, n_train=int(len(tr)), n_heldout=int(len(te)), train_patients=int(len(set(g[tr]))), heldout_patients=sorted(set(map(str, g[te]))),
                              fusion_trained_on=int(np.isfinite(inner_img).sum()), fusion_inputs="inner patient-grouped CV within the training fold"))
        say(f"components and fusion fold {i + 1}/{len(F)}", 0.5 + 0.12 * (i + 1) / len(F))
    rep["folds"] = fold_prov
    Z["image"] = img_oof
    mf = _common(fu) & np.isfinite(Z["char"]) & np.isfinite(img_oof)
    fk, fres = _select({kd: np.where(mf, v, np.nan) for kd, v in fu.items()}, y, g, FUSION_KINDS)
    fk = fk or "feature"; Z["fusion"] = fu[fk]
    # does fusion earn its place? paired patient bootstrap of the log-loss difference against the better single model, same candidates
    single = {"char": Z["char"], "image": img_oof}; sres = {kd: metrics(y[mf], sigmoid(v[mf]), g[mf]) for kd, v in single.items()} if mf.sum() >= 5 else {}
    benefit = None
    if mf.sum() >= 10 and all(r.get("logloss") is not None for r in sres.values()):
        best_single = min(sres, key=lambda kd: sres[kd]["logloss"]); ll = lambda v: IN._ll(y[mf], sigmoid(v[mf]))
        d = ll(Z["fusion"]) - ll(single[best_single]); gg = g[mf]; u = np.unique(gg); gi = {q: np.where(gg == q)[0] for q in u}; rr = np.random.default_rng(seed + 5)
        bd = [float(d[np.concatenate([gi[q] for q in rr.choice(u, len(u))])].mean()) for _ in range(200)]
        lo, hi = float(np.percentile(bd, 2.5)), float(np.percentile(bd, 97.5))
        benefit = dict(best_single=best_single, delta_logloss=float(d.mean()), ci=[lo, hi],
                       verdict="fusion improves on the better single model" if hi < 0 else ("fusion is worse than the better single model" if lo > 0 else "no demonstrated improvement"))
    rep["fusion"] = dict(chosen=fk, results=fres, single=sres, benefit=benefit, compared_on=int(mf.sum()), doc=FUSION_DOC,
                         rule="simplest fusion within one bootstrap SE of the lowest CV log loss (late < feature < hybrid)")
    return Z, rep


# ------------------------------------------------------------------ meta-model candidates
def meta_inputs(Z, kind):
    L = np.c_[[Z[c] for c in INDEP]].T if kind != "stack_fusion" else np.c_[[Z[c] for c in ("math", "unified", "fusion")]].T
    miss = ~np.isfinite(L); Lf = np.where(miss, np.nan, L)
    if kind in ("stack_reg", "boosted"):
        with np.errstate(all="ignore"):
            spread = np.nanstd(Lf, axis=1); gap = np.nanmax(Lf, axis=1) - np.nanmin(Lf, axis=1)
        return np.c_[Lf, miss[:, 1:].astype(float), np.nan_to_num(spread), np.nan_to_num(gap)]
    if kind in ("stack_logit", "stack_fusion"): return np.c_[Lf, miss[:, 1:].astype(float)]
    return Lf


def meta_columns(kind):
    base = INDEP if kind != "stack_fusion" else ["math", "unified", "fusion"]
    cols = list(base) + ([f"{c}_missing" for c in base[1:]] if kind in ("stack_logit", "stack_fusion", "stack_reg", "boosted") else [])
    return cols + (["disagreement_spread", "disagreement_gap"] if kind in ("stack_reg", "boosted") else [])


class Stumps:
    """gradient-boosted decision stumps (log loss), shrinkage 0.1; NaN go to their own branch"""
    def __init__(self, n=150, lr=0.1): self.n, self.lr, self.trees, self.f0 = n, lr, [], 0.0
    def fit(self, X, y, w=None):
        w = np.ones(len(y)) if w is None else w; p0 = np.clip(np.average(y, weights=w), 1e-3, 1 - 1e-3); self.f0 = float(np.log(p0 / (1 - p0))); F = np.full(len(y), self.f0)
        for _ in range(self.n):
            p = sigmoid(F); gr = y - p; h = np.maximum(p * (1 - p), 1e-6); best = None
            for j in range(X.shape[1]):
                x = X[:, j]; fin = np.isfinite(x)
                for t in np.unique(np.percentile(x[fin], [10, 25, 40, 50, 60, 75, 90])) if fin.any() else []:
                    L = fin & (x <= t); Rr = fin & (x > t); N = ~fin; vals = []; gain = 0
                    for m in (L, Rr, N):
                        v = (w[m] * gr[m]).sum() / ((w[m] * h[m]).sum() + 1.0); vals.append(v); gain += (w[m] * gr[m]).sum() * v
                    if best is None or gain > best[0]: best = (gain, j, t, vals)
            if best is None: break
            _, j, t, vals = best; self.trees.append((j, float(t), [float(v) for v in vals])); F += self.lr * self._apply(X, j, t, vals)
        return self
    @staticmethod
    def _apply(X, j, t, vals):
        x = X[:, j]; out = np.full(len(x), vals[2]); fin = np.isfinite(x); out[fin & (x <= t)] = vals[0]; out[fin & (x > t)] = vals[1]; return out
    def logit(self, X): return self.f0 + self.lr * sum((self._apply(X, j, t, v) for j, t, v in self.trees), np.zeros(len(X)))
    def to_json(self): return dict(f0=self.f0, lr=self.lr, trees=self.trees)
    @classmethod
    def from_json(cls, d): m = cls(); m.f0, m.lr, m.trees = d["f0"], d["lr"], [tuple(t) for t in d["trees"]]; return m


class Meta:
    def __init__(self, kind): self.kind = kind; self.model = None
    def fit(self, Z, y, g, w=None):
        X = meta_inputs(Z, self.kind); k = self.kind
        if k == "math_only" or k == "fusion_only":
            src = "math" if k == "math_only" else "fusion"; x = Z[src]; fin = np.isfinite(x)
            b, _, _ = irls(np.nan_to_num(x)[:, None], y, 1e-6, None, w); self.model = dict(a=float(b[0]), b=float(b[1]), src=src)
        elif k == "equal_mean": self.model = dict()
        elif k == "boosted": self.model = Stumps().fit(X, y, w)
        else:
            pl = PenalizedLogistic(meta_columns(k))
            self.model = pl.fit_nested(X, y, g, w=w, lambdas=LAMBDAS) if k in ("stack_reg", "stack_fusion") else pl.fit(X, y, 1e-2, w=w)
        return self
    def logit(self, Z):
        k = self.kind; X = meta_inputs(Z, k)
        if k in ("math_only", "fusion_only"): return self.model["a"] + self.model["b"] * np.nan_to_num(Z[self.model["src"]], nan=0.0)
        if k == "equal_mean":
            with np.errstate(all="ignore"): return np.nan_to_num(np.nanmean(X, axis=1))
        return self.model.logit(X)
    def contributions(self, Z):
        """per-input log-odds contribution (linear meta-models: coefficient x standardised input)"""
        if isinstance(self.model, PenalizedLogistic): return dict(zip(self.model.columns, self.model.contributions(meta_inputs(Z, self.kind)).T)), float(self.model.beta[0])
        return None, None
    def to_json(self):
        m = self.model
        if isinstance(m, PenalizedLogistic): return dict(kind=self.kind, type="logistic", columns=m.columns, lam=m.lam, beta=m.beta.tolist(), median=m.pre.median.tolist(), mean=m.pre.mean.tolist(), sd=m.pre.sd.tolist())
        if isinstance(m, Stumps): return dict(kind=self.kind, type="stumps", **m.to_json())
        return dict(kind=self.kind, type="fixed", params=m)
    @classmethod
    def from_json(cls, d):
        x = cls(d["kind"])
        if d["type"] == "logistic": x.model = LR.pl_from(d)
        elif d["type"] == "stumps": x.model = Stumps.from_json(d)
        else: x.model = d["params"]
        return x


def discover(Z, y, g, w=None, k=5, seed=0):
    """compare the meta-model candidates by patient-grouped CV on the out-of-fold component table; select by the 1-SE rule"""
    y = np.asarray(y, float); n_pos, n_neg = int(y.sum()), int((1 - y).sum()); res = {}
    pos_pts = len({p for p, t in zip(g, y) if t == 1})
    neg_pts = len({p for p, t in zip(g, y) if t == 0})
    kinds = [s for s in SIMPLICITY if s != "boosted" or (min(n_pos, n_neg) >= 50 and min(pos_pts, neg_pts) >= 8)]
    for kind in kinds:
        oof = np.full(len(y), np.nan)
        for tr, te in folds(g, k, seed + 7):
            if len(np.unique(y[tr])) < 2: continue
            Ztr = {c: v[tr] for c, v in Z.items()}; Zte = {c: v[te] for c, v in Z.items()}
            try: oof[te] = Meta(kind).fit(Ztr, y[tr], np.asarray(g)[tr], None if w is None else w[tr]).logit(Zte)
            except Exception: pass
        res[kind] = dict(metrics=metrics(y, sigmoid(oof), g), oof=oof)
    if "boosted" not in kinds:
        res["boosted"] = dict(metrics=dict(skipped=f"needs >= 50 candidates and >= 8 patients per class (cSS {n_pos} in {pos_pts} pts, not cSS {n_neg} in {neg_pts} pts)"), oof=None)
    ok = {k_: v for k_, v in res.items() if v["oof"] is not None and v["metrics"].get("logloss") is not None}
    best = min(ok, key=lambda k_: ok[k_]["metrics"]["logloss"])
    se = ok[best]["metrics"].get("logloss_se")
    has_se = se is not None and np.isfinite(se) and se > 0
    lim = ok[best]["metrics"]["logloss"] + (se if has_se else 0.0)
    chosen = next(k_ for k_ in SIMPLICITY if k_ in ok and ok[k_]["metrics"]["logloss"] <= lim)
    rule_desc = "simplest model within one bootstrap SE of the lowest cross-validated log loss (1-SE rule)" if has_se else "lowest cross-validated log loss (bootstrap SE unavailable)"
    return dict(results={k_: v["metrics"] for k_, v in res.items()}, best_logloss=best, chosen=chosen,
                rule=rule_desc), {k_: v["oof"] for k_, v in res.items()}


def thresholds(y, p):
    y = np.asarray(y); p = np.asarray(p); ts = np.unique(np.r_[0.0, p, 1.0])
    lo = max([t for t in ts if sens_spec(y, p, t)["sensitivity"] >= 0.95] or [0.0])
    hi = min([t for t in ts if sens_spec(y, p, t)["specificity"] >= 0.90] or [1.0]); hi = max(hi, lo)
    return dict(red_below=float(lo), green_from=float(hi), strategy="red below the highest score keeping sensitivity >= 0.95; green from the lowest score with specificity >= 0.90; yellow between (development out-of-fold, calibrated)",
                dev_at_red=sens_spec(y, p, lo), dev_at_green=sens_spec(y, p, hi))


def agreement(Z, y):
    """pairwise agreement (Spearman of log-odds, agreement of the >= 0.5 call) and the dependence between components"""
    names = [c for c in COMPONENTS if np.isfinite(Z[c]).sum() >= 5]; out = []
    def rank(v): o = v.argsort(); r = np.empty(len(v)); r[o] = np.arange(len(v)); return r
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            m = np.isfinite(Z[a]) & np.isfinite(Z[b])
            if m.sum() < 5: continue
            sp = float(np.corrcoef(rank(Z[a][m]), rank(Z[b][m]))[0, 1]); ag = float(np.mean((Z[a][m] >= 0) == (Z[b][m] >= 0)))
            out.append(dict(a=a, b=b, spearman=sp, call_agreement=ag, n=int(m.sum())))
    return out


def check_partitions(rows):
    """v5.25: every examination of a patient must be in the same partition, and every row must carry a patient identity"""
    no_pat = sorted({r.get("study") for r in rows if not r.get("patient")})
    if no_pat: raise ValueError(f"no verified patient identity for {len(no_pat)} studies ({', '.join(map(str, no_pat[:5]))}) - patient-level validation refused")
    side = {}
    for r in rows:
        side.setdefault(str(r["patient"]), set()).add(bool(r.get("test")))
    split = sorted(p for p, s in side.items() if len(s) > 1)
    if split: raise ValueError(f"patient(s) in both the development and the locked test cohort: {split[:5]} - refused")


def train_cycle(rows, version, seed=0, cnn_epochs=30, progress=None, mins=None, nested=True):
    """one complete, reproducible training cycle -> model dict (components + meta + calibration + thresholds + full report)"""
    mins = mins or dict(studies=MIN_STUDIES, candidates=MIN_CANDIDATES, per_class=MIN_PER_CLASS)
    check_partitions(rows)
    test = [r for r in rows if r.get("test")]; dev = [r for r in rows if not r.get("test")]
    if len(dev) < 10: raise ValueError(f"too few development candidates ({len(dev)})")
    y = np.array([r["y"] for r in dev], float); g = np.array([r["patient"] for r in dev]); w = patient_weights(dev)
    if min(y.sum(), (1 - y).sum()) < 3: raise ValueError(f"both classes are needed (cSS {int(y.sum())}, not cSS {int((1 - y).sum())})")
    say = progress or (lambda *a: None); say("component out-of-fold predictions", 0.08)
    Z, fam = component_oof(dev, seed=seed, cnn_epochs=cnn_epochs, progress=say)
    comp_metrics = {c: metrics(y, sigmoid(Z[c]), g) for c in COMPONENTS}
    say("meta-model discovery", 0.62); D, oofs = discover(Z, y, g, w, seed=seed)
    chosen = D["chosen"]; meta_oof = oofs[chosen]
    # Platt calibration with a mild ridge on the slope (CAL_LAMBDA): without it, separable development data drive the slope to
    # infinity and every score to 0 or 100 (seen in v5.22: calibration slope 7.9 on the test cohort)
    cal_b, _, _ = irls(np.nan_to_num(meta_oof)[:, None], y, CAL_LAMBDA); cal = dict(a=float(cal_b[0]), b=float(cal_b[1]), ridge=CAL_LAMBDA)
    p_dev = sigmoid(cal["a"] + cal["b"] * meta_oof); th = IN.stable_thresholds(y, p_dev, g, sens_spec, seed=seed)
    say("PERCIVAL analyses: ablation, disagreement, reliability", 0.66)
    intel = dict(provenance=IN.PROVENANCE, overlap=IN.overlap(), ablation=IN.ablation(Z, y, g, INDEP, folds(g, 5, seed + 7), auc, seed=seed),
                 disagreement=IN.disagreement(Z, y, COMPONENTS), reliability=IN.reliability(y, p_dev), families=fam,
                 note="all analyses on the development cohort's patient-grouped out-of-fold predictions; the locked test cohort is not used")
    say("final fit on the development cohort", 0.7)
    C = Components(fam["char"]["chosen"], fam["image"]["chosen"], fam["fusion"]["chosen"]).fit(dev, seed, image_logit_oof=Z["image"], char_logit_oof=Z["char"], cnn_epochs=cnn_epochs)
    M = Meta(chosen).fit(Z, y, g, w)
    ens = []
    rng = np.random.default_rng(seed + 99); u = np.unique(g)
    for b in range(20):
        pick = rng.choice(u, len(u)); idx = np.concatenate([np.where(g == p)[0] for p in pick])
        try: ens.append(Meta(chosen).fit({c: v[idx] for c, v in Z.items()}, y[idx], g[idx]).to_json())
        except Exception: pass
    model = dict(schema="percival-score-model/1.0", version=version, created=now(), local_only=True, seed=seed,
                 components=C.to_json(), meta=M.to_json(), meta_ensemble=ens, calibration=cal, thresholds=th,
                 discovery=D, component_metrics=comp_metrics, agreement=agreement(Z, y), intelligence=intel,
                 engine=ENGINE,
                 data=dict(dev_candidates=len(dev), dev_patients=int(len(u)), dev_studies=len({r["study"] for r in dev}), test_candidates=len(test),
                           test_patients=len({r["patient"] for r in test}), css=int(sum(r["y"] for r in rows)), not_css=int(sum(1 - r["y"] for r in rows)),
                           studies=len({r["study"] for r in rows}), with_image=int(sum(r.get("maps") is not None for r in rows)),
                           trained_on=sorted({r["study"] for r in dev}),
                           dataset_hash=hashlib.sha256(json.dumps(sorted((r["study"], r["cand_id"], r["y"]) for r in rows)).encode()).hexdigest()[:16]),
                 note="experimental assessment score - trained on this computer on this project's expert reviews; not clinically validated",
                 interpretation="PERCIVAL score = 100 x a CALIBRATED model output on the development cohort. It is a ranking / assessment score, "
                                "not a validated probability of cSS: calibration is checked on the locked test cohort and only on this project's data.")
    model["ready"] = model["data"]["studies"] >= mins["studies"] and len(rows) >= mins["candidates"] and min(model["data"]["css"], model["data"]["not_css"]) >= mins["per_class"]
    model["minimum"] = mins
    # v5.25: the development threshold figures above are IN-SAMPLE for the calibration and the threshold choice (both fitted on the same
    # out-of-fold scores); they are labelled as such. Honest development estimates come from the nested procedure below.
    th["dev_basis"] = "in-sample for calibration and threshold selection (fitted on the same development out-of-fold scores) - see nested"
    model["level0_cv_basis"] = ("single-level patient-grouped CV after family selection on the same folds: optimistic, used for model "
                                "selection only; nested cross-fitting gives the development estimate")
    if nested:
        say("nested cross-fitting of the whole procedure (development cohort)", 0.72)
        from . import nested as NS
        model["nested"], _ = NS.nested_crossfit(dev, seed=seed, cnn_epochs=cnn_epochs, progress=lambda m, p: say(m, 0.72 + 0.12 * p))
    say("evaluation on the locked test cohort", 0.85)
    model["test"] = evaluate_test(model, test)
    return model


# ------------------------------------------------------------------ scoring (final Percival Score) and test evaluation
def score_rows(model, rows):
    """-> per row: Percival Score 0-100 (or None with status 'insufficient'), band, status + reasons, components, contributions, uncertainty,
    out-of-distribution distance, the disagreement pattern and its historical cSS rate. Deterministic for a fixed model and input."""
    if not rows: return []
    C = Components.from_json(model["components"]); Z, X = C.predict(rows, extras=True); M = Meta.from_json(model["meta"]); cal = model["calibration"]
    lg = M.logit(Z); p = sigmoid(cal["a"] + cal["b"] * lg)
    ens = [sigmoid(cal["a"] + cal["b"] * Meta.from_json(e).logit(Z)) for e in model.get("meta_ensemble", [])]
    sd = np.std(np.array(ens), axis=0) * 100 if ens else np.zeros(len(rows))
    contrib, base = M.contributions(Z); th = model["thresholds"]; out = []
    dis_table = (model.get("intelligence") or {}).get("disagreement"); lim = X["ood_limit"]
    for i, r in enumerate(rows):
        avail = [c for c in INDEP if np.isfinite(Z[c][i])]; learned = [c for c in avail if c != "math"]
        with np.errstate(all="ignore"): spread = float(np.nanstd([Z[c][i] for c in avail])) if len(avail) > 1 else 0.0
        reasons = []; qc = r.get("qc") or ""; ood = float(X["ood"][i]) if np.isfinite(X["ood"][i]) else None; isp = X["image_spread"][i]
        if sd[i] > 15: reasons.append(f"meta-model ensemble spread {sd[i]:.0f} points")
        if spread > 2.5: reasons.append("the components disagree strongly")
        if lim is not None and ood is not None and ood > lim: reasons.append("measurements outside the training data (out-of-distribution)")
        if np.isfinite(isp) and isp > 1.0: reasons.append("image model unstable under mirroring")
        io = X.get("image_ood"); ilim = X.get("image_ood_limit")
        iood = float(io[i]) if io is not None and np.isfinite(io[i]) else None; img_ood = ilim is not None and iood is not None and iood > ilim
        if img_ood: reasons.append("MRI patch unlike the training patches (image out-of-distribution)")
        missing = [c for c in INDEP if c not in avail]
        if missing and learned: reasons.append("missing: " + ", ".join(missing))
        if qc == "low_confidence_review": reasons.append("study image quality: low confidence")
        if not learned: status = "insufficient"; reasons.insert(0, "no learned source of evidence for this candidate")
        elif qc == "insufficient_quality": status = "review"; reasons.insert(0, "study image quality insufficient - expert review required")
        elif sd[i] > 15 or spread > 2.5 or (lim is not None and ood is not None and ood > lim) or qc == "low_confidence_review" or (np.isfinite(isp) and isp > 1.0) or img_ood: status = "uncertain"
        else: status = "reliable"
        sc = None if status == "insufficient" else float(np.clip(100 * p[i], 0, 100))
        band = None if sc is None else ("red" if sc / 100 < th["red_below"] else "green" if sc / 100 >= th["green_from"] else "yellow")
        pat = IN.pattern_of(dis_table, "char", "image", Z["char"][i], Z["image"][i]) if dis_table else None
        out.append(dict(cand_id=r["cand_id"], percival_score=None if sc is None else round(sc, 1), band=band, status=status, reasons=reasons,
                        uncertainty_sd=round(float(sd[i]), 1), missing=missing, disagreement=round(spread, 2),
                        ood_distance=None if ood is None else round(ood, 2), ood_limit=None if lim is None else round(float(lim), 2),
                        image_tta_spread=None if not np.isfinite(isp) else round(float(isp), 2), qc=qc or None, pattern=pat,
                        image_ood_distance=None if iood is None else round(iood, 2), image_ood_limit=None if ilim is None else round(float(ilim), 2),
                        components={c: (None if not np.isfinite(Z[c][i]) else round(float(sigmoid(Z[c][i])) * 100, 1)) for c in COMPONENTS},
                        contributions=None if contrib is None else {k: round(float(v[i]), 3) for k, v in contrib.items()}, baseline=base))
    return out


def evaluate_test(model, test):
    if not test: return dict(n=0, note="no candidate in the locked test cohort yet")
    S = score_rows(model, test); y = np.array([r["y"] for r in test], float); g = [r["patient"] for r in test]
    p = np.array([np.nan if s["percival_score"] is None else s["percival_score"] / 100 for s in S])
    C = Components.from_json(model["components"]); Z = C.predict(test)
    th = model["thresholds"]; out_ext = {c: metrics(y, sigmoid(Z[c]), g) for c in COMPONENTS if np.isfinite(Z[c]).sum() >= 5}; m = np.isfinite(p)
    pos = {str(q) for q, t in zip(g, y) if t == 1}
    out = dict(percival=metrics(y[m], p[m], np.asarray(g)[m]) if m.sum() >= 5 else dict(n=int(m.sum())),
               math=metrics(y, sigmoid(Z["math"]), g), insufficient=int((~m).sum()), n=len(test), components=out_ext,
               patients=len(set(g)), patient_classes=dict(with_css=len(pos), without_css=len(set(map(str, g)) - pos)),
               reliability=IN.reliability(y[m], p[m]) if m.sum() >= 10 else None,
               basis="locked test cohort: patients assigned permanently by a hash of the patient id, never used for fitting, selection, "
                     "calibration or thresholds; internal held-out evaluation on this project, not a clinical validation")
    if m.sum() >= 5 and len(np.unique(y[m])) == 2:
        out["at_red"] = sens_spec(y[m], p[m], th["red_below"]); out["at_green"] = sens_spec(y[m], p[m], th["green_from"])
        comp = np.array([not s["missing"] for s in S]); hi = np.array([s["disagreement"] > 1.5 for s in S])
        for name, mask in (("complete_inputs", comp & m), ("missing_inputs", ~comp & m), ("high_disagreement", hi & m), ("low_disagreement", ~hi & m)):
            out[f"subgroup_{name}"] = metrics(y[mask], p[mask], None) if mask.sum() >= 5 else dict(n=int(mask.sum()))
    return out


def acceptance(model, active):
    t = model.get("test", {}); pc = t.get("percival", {}); mt = t.get("math", {}); reasons = []
    if not model.get("ready"): reasons.append("below the minimum data")
    if pc.get("auc") is None: reasons.append("no locked-test evaluation possible yet (too few test candidates)")
    else:
        if mt.get("auc") is not None and pc["auc"] + 1e-9 < mt["auc"]: reasons.append(f"test AUC {pc['auc']:.3f} below MATH alone {mt['auc']:.3f}")
        if active and (active.get("test", {}).get("percival", {}).get("auc") is not None) and pc["auc"] < active["test"]["percival"]["auc"] - 0.01:
            reasons.append(f"test AUC below the active model by more than 0.01")
        if active and active.get("test", {}).get("percival", {}).get("brier") is not None and pc.get("brier") is not None and pc["brier"] > active["test"]["percival"]["brier"] + 0.01:
            reasons.append("Brier score worse than the active model by more than 0.01")
        sl = pc.get("calib_slope")
        if sl is not None and not (0.6 <= sl <= 1.6): reasons.append(f"calibration slope {sl:.2f} outside 0.6-1.6")
        if pc.get("auc_ci") is None: reasons.append("no confidence interval on the locked test cohort (too few patients for the patient bootstrap)")
    # v5.25 evidence gates (component-specific numbers are reported, never a universal AUC bar)
    tp_pos, tp_neg = _patient_classes(t.get("patient_classes"))
    if tp_pos is not None and (tp_pos < MIN_TEST_PATIENTS_PER_CLASS or tp_neg < MIN_TEST_PATIENTS_PER_CLASS):
        reasons.append(f"locked test cohort has {tp_pos} patients with cSS and {tp_neg} without (at least {MIN_TEST_PATIENTS_PER_CLASS} of each are required)")
    ns = model.get("nested")
    if not ns: reasons.append("no nested (leakage-free) development evaluation recorded")
    else:
        sup = ns.get("support") or {}
        if (sup.get("evaluable_folds") or 0) < 3: reasons.append(f"nested evaluation: only {sup.get('evaluable_folds', 0)} evaluable outer folds")
        np_ = (ns.get("percival") or {}).get("auc"); nm = ((ns.get("ablation") or {}).get("MATH alone") or {}).get("auc")
        if np_ is None: reasons.append("nested evaluation produced no AUC")
        elif nm is not None and np_ + 1e-9 < nm: reasons.append(f"nested development AUC {np_:.3f} below MATH alone {nm:.3f}")
    iden = (model.get("data") or {}).get("identity") or {}
    if iden.get("assumed"): reasons.append(f"patient identity is assumed (one patient per study, not verified) for {iden['assumed']} studies")
    return dict(passed=not reasons, reasons=reasons,
                criteria=f"minimum data; locked test: >= {MIN_TEST_PATIENTS_PER_CLASS} patients per class, AUC >= MATH alone, AUC >= active - 0.01, "
                         "Brier <= active + 0.01, calibration slope 0.6-1.6, patient-bootstrap CI available; nested development evaluation "
                         ">= 3 evaluable folds and not below MATH alone; verified patient identity. Passing makes a model a CANDIDATE only - "
                         "activation always needs explicit human approval.")


MIN_TEST_PATIENTS_PER_CLASS = 5


def _patient_classes(pc):
    if not pc: return None, None
    return pc.get("with_css"), pc.get("without_css")
