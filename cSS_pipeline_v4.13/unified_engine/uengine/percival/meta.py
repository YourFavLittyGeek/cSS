"""meta.py - PERCIVAL SCORE: components, meta-assessment discovery, calibration, thresholds, uncertainty, acceptance (v5.22; v5.23 additions
below). Local, numpy.
v5.23: NOX and LUMOS each choose their model FAMILY by patient-grouped CV (learners.py); Percival Intelligence analyses (intelligence.py: input
provenance, ablation, disagreement patterns, out-of-distribution, reliability table); bootstrap-stable thresholds; per-candidate reasons.

ARCHITECTURE (2026-11-25, user decision): MRI -> ALBUS (detects) -> NOX (measures) + LUMOS (sees the image) -> PERCIVAL (the ONLY place
where evidence is combined). The former "Unified" component (uScore x1-x5 as a separate model) and the "Fusion" component (a second
combiner of NOX + LUMOS below PERCIVAL) were removed: the three non-redundant uScore measurements became NOX measurements, and PERCIVAL's
meta-model does the combining (with its disagreement terms), so no evidence is counted twice and no model sits between NOX/LUMOS and PERCIVAL.

COMPONENTS (level 0; each an independent, traceable assessment of a candidate; trained with patient-grouped out-of-fold predictions):
  math     ALBUS - the deterministic detector score (score_v4), Platt-recalibrated to log-odds (monotone: never changes the ALBUS order)
  char     NOX - the measurement model on the candidate's quantitative measurements (feature list CHAR = the built-in NOX set, or the
           active approved NOX version): logistic / boosted trees / forest chosen by patient-grouped CV
  image    LUMOS - the image model on the candidate's MRI patch pixels (pixel logistic / small CNN / CNN ensemble)

META-MODEL DISCOVERY (PERCIVAL; on the development cohort only; the locked test cohort is not touched until the final evaluation):
  M0 math_only        ALBUS alone (the existing system; baseline)
  M1 equal_mean       mean of the available component log-odds (ALBUS, NOX, LUMOS) - a fixed, NOT learned, combination
  M2 stack_logit      logistic stacking on the ALBUS, NOX, LUMOS log-odds + missing-input indicators (light penalty)
  M3 stack_reg        regularised stacking (penalty by nested CV) + disagreement terms (spread and max pairwise gap of the log-odds)
  M4 stack_unc        regularised stacking + reliability signals + the gap of every component pair (learned uncertainty)
  M5 boosted          gradient-boosted decision stumps on the M3 inputs (only when both classes have >= 50 candidates)
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
from . import component_api as CI          # Stage 2: the engine reads ALBUS / NOX / LUMOS evidence through one component interface

# NOX built-in feature set (registry v000; contents of 2026-11-25). Chosen from what the detector already measures for every candidate (100 % coverage on the
# user's 772 real candidates, continuous, not a rule decision, not a composite score, not a deprecated column) + the three uScore
# measurements that do not repeat ALBUS inputs (uScore x3 pial distance and x4 surface conformity = ALBUS pdist / aln: left out).
# Grouped by what they describe; docs/percival_app/NOX_FEATURES.md gives every definition and the reason it is in the set.
NOX_V000 = ["darkness_z", "edge_contrast", "pial_dist_mm", "cortex_frac", "tram_frac", "tube_ratio", "elongation_3d", "log_volume_mm3", "local_cont_max_mm"]
NOX_ADDED = ["bank_frac", "dual_contact_frac", "surface_contact_frac_1mm", "csf_adjacent_frac", "sulcal_depth_mm",       # relation to the brain surface
             "flatness_3d", "sphericity", "tortuosity", "struct_thick_mm", "cand_radius_med_mm",                        # 3-D shape
             "dark_frac_z3", "darkness_z_p10", "region_z", "dark_cv",                                                     # darkness pattern
             "vessel_wm_mm", "local_branch_points",                                                                       # vessel behaviour
             "rel_height", "skull_frac"]                                                                                  # position
PREDICTORS = ["x1_vessel_continuity_mm", "x2_core_contrast_nu", "x5_extracranial_mm"]   # from uscore/features (reliable values only)
CHAR = NOX_V000 + NOX_ADDED + PREDICTORS
NOX_BUILTIN_VERSION = "v000"          # registry id of the built-in set (approved versions are v001, v002 ...)
COMPONENTS = ["math", "char", "image"]
INDEP = ["math", "char", "image"]
LAMBDAS = np.logspace(-2, 3, 9)
SIMPLICITY = ["math_only", "equal_mean", "stack_logit", "stack_reg", "stack_unc", "boosted"]
# Stage 3: learned uncertainty + disagreement. stack_unc = regularised stacking (penalty by nested CV) on the component log-odds with NEUTRAL
# filling of a missing component (log-odds 0 = no evidence, never a negative) + one missing indicator per component + the components'
# reliability signals (ALBUS rule fate, NOX missing fraction, LUMOS test-time-augmentation spread) + the |gap| of every component pair.
REL = ["rel_albus_tier2", "rel_nox_missing", "rel_lumos_spread"]
PAIRS = [(a, b) for i, a in enumerate(INDEP) for b in INDEP[i + 1:]]
MIN_STUDIES, MIN_CANDIDATES, MIN_PER_CLASS = 30, 100, 10
SUBGROUPS = ("field_strength", "sequence", "anatomy", "qc")         # Stage 3 calibration subgroups (rows['subgroups'], from review/ID_qc.json)
ABSTENTION_POLICY = ("PERCIVAL says 'review required' (no score) when >= 2 independent abstention triggers fire: measurements out of distribution, "
                     "MRI patch out of distribution, strong component disagreement (log-odds SD > 2.5), meta-model ensemble spread > 15 points; "
                     "or when study image quality is insufficient. One trigger -> 'uncertain' with the score shown. No learned evidence -> "
                     "'insufficient'. The coverage / accuracy trade-off of the disagreement-based risk is reported on the development cohort.")
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
def _with_marks(M, y, g, extra, patients):
    """LUMOS learning from expert-marked missed cSS (2026-11-25): add the image patches of the marks whose patient is among the training
    patients (never a held-out or locked-test patient). extra: rows dict(patient, maps, y=1). -> M, y, g, number added"""
    ex = [r for r in (extra or []) if r.get("maps") is not None and str(r["patient"]) in {str(p) for p in patients}]
    if not ex: return M, y, g, 0
    Mx = np.stack([np.asarray(r["maps"], np.float32) for r in ex]); yx = np.array([float(r.get("y", 1)) for r in ex])
    gx = np.array([r["patient"] for r in ex], dtype=np.asarray(g).dtype if np.asarray(g).dtype != object else object)
    return np.concatenate([M, Mx]), np.concatenate([y, yx]), np.concatenate([np.asarray(g), gx]), len(ex)


def _with_char_marks(X, y, g, w, extra, patients, cols):
    """NOX learning from CONFIRMED ALBUS re-detections of expert-marked missed cSS (2026-11-25): add their measurements (y = 1) for the
    training patients only; weight = the median candidate weight. -> X, y, g, w, number added"""
    ex = [r for r in (extra or []) if r.get("char") and str(r["patient"]) in {str(p) for p in patients}]
    if not ex: return X, y, g, w, 0
    Xm = X_of(ex, cols, "char"); wm = np.full(len(ex), float(np.median(w)) if len(w) else 1.0)
    gm = np.array([r["patient"] for r in ex], dtype=g.dtype if g.dtype != object else object)
    return np.vstack([X, Xm]), np.concatenate([y, np.ones(len(ex))]), np.concatenate([g, gm]), np.concatenate([w, wm]), len(ex)


def paired_logloss(y, a, b, g, n=300, seed=0):
    """paired comparison of two out-of-fold log-odds vectors on the SAME candidates: mean per-candidate log-loss difference (b - a) and
    its patient-bootstrap SE -> (diff, se). Much tighter than comparing two separate log losses with their own SEs."""
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 5: return None, None
    y, a, b, g = np.asarray(y, float)[m], a[m], b[m], np.asarray(g).astype(str)[m]
    ll = lambda z: -(y * np.log(np.clip(sigmoid(z), 1e-6, 1)) + (1 - y) * np.log(np.clip(1 - sigmoid(z), 1e-6, 1)))
    d = ll(b) - ll(a); u = np.unique(g); idx = {p: np.where(g == p)[0] for p in u}; rng = np.random.default_rng(seed); bs = []
    for _ in range(n):
        pick = rng.choice(u, len(u)); j = np.concatenate([idx[p] for p in pick]); bs.append(d[j].mean())
    return float(d.mean()), float(np.std(bs))


def no_harm(y, a, b, g):
    """marks are used unless they make the candidates MEASURABLY worse: paired log-loss increase > one bootstrap SE"""
    d, se = paired_logloss(y, a, b, g)
    return (d is None or d <= se), d, se


ORIGIN_AUC_MAX = 0.75          # NOX may learn from the marks only if their measurements do not reveal that they came from a mark


def origin_auc(Xpos, Xmark, gpos, gmark, cols, seed=0):
    """can a model tell a re-detected mark from a detected cSS by its NOX measurements? patient-grouped CV AUC (0.5 = no)"""
    if len(Xmark) < 3 or len(Xpos) < 3: return None
    X = np.vstack([Xpos, Xmark]); o = np.r_[np.zeros(len(Xpos)), np.ones(len(Xmark))]; g = np.r_[np.asarray(gpos, str), np.asarray(gmark, str)]
    oof = np.full(len(o), np.nan)
    for tr, te in folds(g, 5, seed + 3):
        if len(np.unique(o[tr])) < 2: continue
        m = LR.fit_tabular("logistic", X[tr], o[tr], g[tr], np.ones(len(tr)), cols, seed)
        if m is not None: oof[te] = m.logit(X[te])
    return auc(o, oof)


class NoAlbus:
    """PERCIVAL for objects ALBUS did not score (re-detected missed cSS): a regularised logistic on the NOX and LUMOS log-odds (+ a missing
    indicator each), fitted on the development CANDIDATES' out-of-fold table. ALBUS is not an input at all, so 'no ALBUS score' can never
    be learned as a sign of cSS."""
    COLS = ["char", "image"]
    def fit(self, Z, y, g, w=None):
        X = self._X(Z); names = self.COLS + [f"{c}_missing" for c in self.COLS]
        pl = PenalizedLogistic(names); self.m = pl.fit_nested(X, y, g, w=w, lambdas=LAMBDAS) if len(np.unique(g)) >= 3 else pl.fit(X, y, 1.0, w=w)
        return self
    def _X(self, Z):
        L = np.c_[[np.asarray(Z[c], float) for c in self.COLS]].T; return np.c_[L, (~np.isfinite(L)).astype(float)]
    def logit(self, Z):
        X = self._X(Z); out = self.m.logit(X); out[~np.isfinite(X[:, :2]).any(1)] = np.nan; return out
    def to_json(self):
        m = self.m; return dict(type="logistic", columns=m.columns, lam=m.lam, beta=m.beta.tolist(), median=m.pre.median.tolist(), mean=m.pre.mean.tolist(), sd=m.pre.sd.tolist())
    @classmethod
    def from_json(cls, d): x = cls(); x.m = LR.pl_from(d); return x


def _fit_image(kind, M, y, g, seed, epochs):
    if kind == "pixel_logistic": return PixelLogistic(seed).fit(M, y, g)
    if kind == "cnn_ensemble":                                             # Stage 3: augmented, class-balanced seed ensemble (LUMOS registry)
        from .cnn import SeedEnsemble
        return SeedEnsemble(seed).fit(M, y, g, epochs=epochs)
    return SmallCNN(seed).fit(M, y, g, epochs=epochs)


class Components:
    """fit on rows -> predict log-odds of each component (NaN when the component has no input for a row): ALBUS (math), NOX (char), LUMOS
    (image). The model family of NOX (logistic / gbt / forest) and LUMOS (pixel_logistic / cnn / cnn_ensemble) is chosen by component_oof()
    on patient-grouped CV and passed in. fusion_kind is accepted and ignored (models before 2026-11-25)."""
    def __init__(self, char_kind="logistic", image_kind="cnn", fusion_kind=None, char_cols=None):
        self.char_kind, self.image_kind = char_kind, image_kind; self.ood = None; self.image_ood = None
        self.char_cols = list(char_cols or CHAR)              # Stage 2: the NOX feature list is part of the model

    def fit(self, rows, seed=0, image_logit_oof=None, char_logit_oof=None, cnn_epochs=30, image_extra=None, char_extra=None):
        y = np.array([r["y"] for r in rows], float); g = [r["patient"] for r in rows]; w = patient_weights(rows)
        NF = CI.NOX.features(rows, char_cols=self.char_cols)
        self.math = MathRecalibration().fit(CI.ALBUS.features(rows)["math"], y, w)
        Xc = NF["char"]; Xf, yf, gf, wf, self.n_char_marks = _with_char_marks(Xc, y, np.asarray(g), w, char_extra, set(map(str, g)), self.char_cols)
        self.char = LR.fit_tabular(self.char_kind, Xf, yf, gf, wf, self.char_cols, seed)
        LF = CI.LUMOS.features(rows); M, have = LF["image"], LF["have"]; self.image = None; self.n_marks = 0
        if cnn_epochs and have.sum() >= 20 and len(np.unique(y[have])) == 2:
            Mi, yi, gi, self.n_marks = _with_marks(M[have], y[have], np.asarray(g)[have], image_extra, set(map(str, g)))
            try: self.image = _fit_image(self.image_kind, Mi, yi, gi, seed, cnn_epochs)
            except ValueError: self.image = None
        self.ood = IN.OOD().fit(Xc)
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
        NF = CI.NOX.features(rows, char_cols=self.char_cols)
        Z = dict(math=self.math.logit(CI.ALBUS.features(rows)["math"]))
        Xc = NF["char"]; Z["char"] = self._char(Xc)
        Z["image"], spread = self._img(rows)
        for kk, vv in CI.reliability_table(rows, dict(image_spread=spread), char_cols=self.char_cols).items(): Z["rel_" + kk] = vv
        if not extras: return Z
        ood = self.ood.distance(Xc) if self.ood is not None else np.full(len(rows), np.nan)
        iood = np.full(len(rows), np.nan)
        if self.image_ood is not None:
            Mm, have = maps_of(rows)
            if have.any(): iood[have] = self.image_ood.distance(patch_stats(Mm[have]))
        return Z, dict(image_spread=spread, ood=ood, ood_limit=self.ood.limit if self.ood is not None else None, image_ood=iood,
                       image_ood_limit=self.image_ood.limit if self.image_ood is not None else None)

    def to_json(self):
        return dict(kinds=dict(char=self.char_kind, image=self.image_kind), char_cols=list(self.char_cols),
                    math=dict(a=self.math.a, b=self.math.b, eps=self.math.eps), char=LR.tab_json(self.char),
                    image=None if self.image is None else self.image.to_json(),
                    ood=None if self.ood is None else self.ood.to_json(), image_ood=None if self.image_ood is None else self.image_ood.to_json())

    @classmethod
    def from_json(cls, d):
        """models written before 2026-11-25 (with 'unified' / 'fusion' parts) load: those parts are ignored; their OOD descriptor (NOX + x1-x5)
        no longer matches the NOX columns and is dropped (no out-of-distribution flag for such a model)"""
        k = d.get("kinds") or dict(char="logistic", image="cnn")
        c = cls(k.get("char", "logistic"), k.get("image", "cnn"), char_cols=d.get("char_cols") or NOX_V000)
        c.math = MathRecalibration(**d["math"]); c.char = LR.tab_from(d["char"]); c.image = LR.image_model_from(d.get("image"))
        c.ood = IN.OOD.from_json(d["ood"]) if d.get("ood") else None
        if c.ood is not None and (d.get("unified") is not None or "fusion" in (d.get("kinds") or {})): c.ood = None
        c.image_ood = IN.OOD.from_json(d["image_ood"]) if d.get("image_ood") else None; return c


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


def component_oof(rows, k=5, seed=0, cnn_epochs=30, progress=None, char_kinds=None, image_kinds=None, fusion_kinds=None, char_cols=None, image_extra=None, compare_marks=True, char_extra=None):
    """patient-grouped out-of-fold log-odds of every component (ALBUS, NOX, LUMOS) for the given (development) rows, and the model-family
    comparisons of NOX and LUMOS on the SAME folds. -> Z, report. fusion_kinds: accepted and ignored (Fusion removed 2026-11-25).
    image_extra: image patches of expert-marked missed cSS (rows dict(patient, maps, y=1)); added to LUMOS's training folds for the
    training patients only; every out-of-fold prediction and metric stays on candidates."""
    say = progress or (lambda *a: None); CC = list(char_cols or CHAR)
    char_kinds = char_kinds or LR.CHAR_KINDS; image_kinds = image_kinds or LR.IMAGE_KINDS
    y = np.array([r["y"] for r in rows], float); g = np.array([r["patient"] for r in rows]); w = patient_weights(rows); F = folds(g, k, seed)
    Xc = X_of(rows, CC, "char"); M, have = maps_of(rows); rep = {}
    # 1. LUMOS families (with the expert-marked missed cSS: compared on the SAME folds with and without them, used only when they do not
    #    make LUMOS worse on the candidates - a drawn mark gives a patch that only partly resembles a detector candidate's)
    pos_marks = [r for r in (image_extra or []) if r.get("maps") is not None and float(r.get("y", 1)) == 1.0]
    def lumos(extra):
        img = {kd: np.full(len(rows), np.nan) for kd in image_kinds}; spr = {kd: np.full(len(rows), np.nan) for kd in image_kinds}; n_mk = []
        hm = {kd: [] for kd in image_kinds}                     # LUMOS checks the marks: P(cSS) of the marks of the held-out patients
        hk = {kd: {} for kd in image_kinds}
        for i, (tr, te) in enumerate(F):
            htr, hte = tr[have[tr]], te[have[te]]
            if len(htr) >= 20 and len(np.unique(y[htr])) == 2 and len(hte):
                Mi, yi, gi, nm = _with_marks(M[htr], y[htr], g[htr], extra, set(map(str, g[tr]))); n_mk.append(nm)
                for kd in image_kinds:
                    try:
                        net = _fit_image(kd, Mi, yi, gi, seed + i, cnn_epochs); lg, sp = net.logit_tta(M[hte]); img[kd][hte] = lg
                        spr[kd][hte] = sp
                        ho = {str(p) for p in g[te]}; Rh = [r for r in pos_marks if str(r["patient"]) in ho]
                        if Rh:
                            lh = net.logit_tta(np.stack([np.asarray(r["maps"], np.float32) for r in Rh]))[0]
                            hm[kd] += [float(v) for v in sigmoid(lh)]
                            for r, v in zip(Rh, lh): hk[kd][(str(r["study"]), str(r["cand_id"]))] = float(v)
                    except ValueError: pass
            say(f"LUMOS image models{' with the missed-cSS marks' if extra else ''} fold {i + 1}/{len(F)}", 0.1 + 0.3 * (i + 1) / len(F))
        m = _common(img); ik, ires = _select({kd: np.where(m, v, np.nan) for kd, v in img.items()}, y, g, LR.IMAGE_KINDS)
        ik = ik or image_kinds[-1]
        return img, spr, n_mk, m, ik, ires, hm[ik], hk[ik]
    pats = set(map(str, g)); avail = [r for r in (image_extra or []) if r.get("maps") is not None and str(r["patient"]) in pats]
    if avail and compare_marks:
        base = lumos(None); withm = lumos(avail)
        lb = (base[5].get(base[4]) or {}).get("logloss"); lw = (withm[5].get(withm[4]) or {}).get("logloss")
        use, dlt, dse = no_harm(y, base[0][base[4]], withm[0][withm[4]], g)        # paired, same candidates and folds
        use = use and lw is not None
        img, spr, n_mk, m, ik, ires, hprob, hkey = withm if use else base
        mk = dict(available=len(avail), used=bool(use), added_per_fold=withm[2] if use else [], logloss_without=lb, logloss_with=lw,
                  auc_without=(base[5].get(base[4]) or {}).get("auc"), auc_with=(withm[5].get(withm[4]) or {}).get("auc"),
                  paired_delta=dlt, paired_se=dse,
                  decision=("used: LUMOS predicts the candidates no worse with the marks (paired, within one standard error)" if use else
                            "not used this cycle: LUMOS predicted the candidates measurably worse with the marks (kept for the next cycle)"))
    else:
        img, spr, n_mk, m, ik, ires, hprob, hkey = lumos(avail or None)
        mk = dict(available=len(avail), used=bool(avail and any(n_mk)), added_per_fold=n_mk,
                  decision="no expert-marked missed cSS" if not avail else "used (decided by the outer training cycle)")
    mk["heldout_check"] = dict(n=len(hprob), recognised=int(sum(p >= 0.5 for p in hprob)),
                               recall=(float(np.mean([p >= 0.5 for p in hprob])) if hprob else None),
                               median_p=(float(np.median(hprob)) if hprob else None),
                               basis="LUMOS fold models scoring the expert-marked missed cSS of patients they were not trained on (P >= 0.5 = recognised)")
    mk["n_negative_examples"] = sum(1 for r in avail if float(r.get("y", 1)) == 0.0)
    mk["positives"] = sum(1 for r in avail if float(r.get("y", 1)) == 1.0)
    mk["note"] = "expert-marked missed cSS: extra cSS image examples in LUMOS training folds (training patients only); evaluation on candidates only"
    img_oof = img[ik]; spread = spr[ik]
    rep["image"] = dict(chosen=ik, results=ires, n_with_image=int(have.sum()), tta_spread_median=float(np.nanmedian(spread)) if np.isfinite(spread).any() else None,
                        rule="simplest image model within one bootstrap SE of the lowest CV log loss (pixel_logistic < cnn)", compared_on=int(m.sum()),
                        missed_marks=mk)
    # 2. NOX families (+ the CONFIRMED ALBUS re-detections of expert-marked missed cSS: used only when their measurements do not reveal
    #    their origin (origin AUC <= ORIGIN_AUC_MAX) and NOX predicts the candidates no worse with them - compared on the same folds)
    cm = [r for r in (char_extra or []) if r.get("char") and str(r["patient"]) in pats]
    Xm = X_of(cm, CC, "char") if cm else np.zeros((0, len(CC))); gm = np.array([str(r["patient"]) for r in cm])
    def nox(use):
        ch = {kd: np.full(len(rows), np.nan) for kd in char_kinds}; zm = {kd: np.full(len(cm), np.nan) for kd in char_kinds}
        for i, (tr, te) in enumerate(F):
            if len(np.unique(y[tr])) < 2: continue
            Xt, yt, gt, wt, _ = _with_char_marks(Xc[tr], y[tr], g[tr], w[tr], cm if use else None, set(map(str, g[tr])), CC)
            for kd in char_kinds:
                mdl = LR.fit_tabular(kd, Xt, yt, gt, wt, CC, seed + i)
                if mdl is not None:
                    hv = np.isfinite(Xc[te]).any(1)
                    if hv.any(): ch[kd][te[hv]] = mdl.logit(Xc[te[hv]])
                    ho = np.isin(gm, list(map(str, g[te])))
                    if ho.any(): zm[kd][ho] = mdl.logit(Xm[ho])
            say(f"NOX measurement models{' with the re-detected marks' if use else ''} fold {i + 1}/{len(F)}", 0.4 + 0.15 * (i + 1) / len(F))
        ck, cres = _select(ch, y, g, LR.CHAR_KINDS); ck = ck or "logistic"
        return ch, ck, cres, zm[ck]
    nm = dict(available=len(cm), used=False)
    if cm and compare_marks:
        oa = origin_auc(Xc[y == 1], Xm, g[y == 1], gm, CC, seed); nm["origin_auc"] = oa
        b0 = nox(False); b1 = nox(True)
        l0 = (b0[2].get(b0[1]) or {}).get("logloss"); l1 = (b1[2].get(b1[1]) or {}).get("logloss")
        ok_origin = oa is None or oa <= ORIGIN_AUC_MAX
        nh, dlt, dse = no_harm(y, b0[0][b0[1]], b1[0][b1[1]], g)                 # paired, same candidates and folds
        use_c = ok_origin and l1 is not None and nh
        ch, ck, cres, zmark = b1 if use_c else b0
        nm.update(used=bool(use_c), logloss_without=l0, logloss_with=l1, auc_without=(b0[2].get(b0[1]) or {}).get("auc"), auc_with=(b1[2].get(b1[1]) or {}).get("auc"),
                  paired_delta=dlt, paired_se=dse,
                  decision=("used: NOX predicts the candidates no worse with the re-detected marks (paired, within one standard error), and their measurements do not reveal their origin" if use_c else
                            f"not used: the measurements reveal that an object came from a mark (origin AUC {oa:.2f} > {ORIGIN_AUC_MAX})" if not ok_origin else
                            "not used: NOX predicted the candidates measurably worse with the re-detected marks"))
        if not use_c: zmark = b1[3]                       # the held-out check is still reported (NOX with the marks)
    else:
        ch, ck, cres, zmark = nox(bool(cm)); nm.update(used=bool(cm), decision="no confirmed re-detected marks" if not cm else "used (decided by the outer training cycle)")
    hc = [float(v) for v in sigmoid(zmark[np.isfinite(zmark)])] if len(cm) else []
    nm["heldout_check"] = dict(n=len(hc), recognised=int(sum(p >= 0.5 for p in hc)), recall=float(np.mean([p >= 0.5 for p in hc])) if hc else None,
                               basis="NOX fold models scoring the re-detected marks of patients they were not trained on")
    CMU = cm if nm["used"] else []
    Xf, yf, gf, wf, _ = _with_char_marks(Xc, y, g, w, CMU, set(map(str, g)), CC)
    final_char = LR.fit_tabular(ck, Xf, yf, gf, wf, CC, seed)
    rep["char"] = dict(chosen=ck, results=cres, importance=LR.importance(final_char), rule="simplest model within one bootstrap SE of the lowest CV log loss (logistic < gbt < forest)",
                       feature_auc={c: auc(y, (Xc[:, j] if np.isfinite(Xc[:, j]).sum() >= 5 else np.full(len(y), np.nan))) for j, c in enumerate(CC)},
                       coverage={c: float(np.isfinite(Xc[:, j]).mean()) if len(Xc) else 0.0 for j, c in enumerate(CC)}, missed_marks=nm)
    rep["_mark_oof"] = dict(keys=[(str(r["study"]), str(r["cand_id"])) for r in cm], char=zmark, image_by_key=hkey)
    # 3. ALBUS + NOX out-of-fold with the chosen NOX family (fitted on the training fold only); LUMOS out-of-fold = step 1
    Z = {c: np.full(len(rows), np.nan) for c in COMPONENTS}; fold_prov = []
    for i, (tr, te) in enumerate(F):
        assert not set(g[tr]) & set(g[te]), "patient in both the training and the held-out fold"
        if len(np.unique(y[tr])) < 2: continue
        c = Components(ck, ik, char_cols=CC).fit([rows[j] for j in tr], seed, cnn_epochs=0, char_extra=CMU)
        P = c.predict([rows[j] for j in te])
        for k_ in ("math", "char"): Z[k_][te] = P[k_]
        fold_prov.append(dict(fold=i, n_train=int(len(tr)), n_heldout=int(len(te)), train_patients=int(len(set(g[tr]))), heldout_patients=sorted(set(map(str, g[te])))))
        say(f"components fold {i + 1}/{len(F)}", 0.55 + 0.07 * (i + 1) / len(F))
    rep["folds"] = fold_prov
    Z["image"] = img_oof
    for kk, vv in CI.reliability_table(rows, dict(image_spread=np.where(np.isfinite(img_oof), spread, np.nan)), char_cols=CC).items():
        Z["rel_" + kk] = vv                                              # Stage 3: reliability signals, out-of-fold where they are model outputs
    return Z, rep


# ------------------------------------------------------------------ meta-model candidates
def meta_inputs(Z, kind):
    L = np.c_[[Z[c] for c in INDEP]].T
    miss = ~np.isfinite(L); Lf = np.where(miss, np.nan, L)
    if kind == "stack_unc":
        n = len(L); Ln = np.where(miss, 0.0, L)                          # neutral: a missing component is no evidence, never a negative
        rel = [np.nan_to_num(np.asarray(Z.get(k, np.zeros(n)), float), nan=0.0) for k in REL]
        gaps = [np.where(~np.isfinite(Z[a]) | ~np.isfinite(Z[b]), 0.0, np.abs(np.nan_to_num(Z[a]) - np.nan_to_num(Z[b]))) for a, b in PAIRS]
        return np.c_[Ln, miss[:, 1:].astype(float), np.c_[rel].T, np.c_[gaps].T]
    if kind in ("stack_reg", "boosted"):
        with np.errstate(all="ignore"):
            spread = np.nanstd(Lf, axis=1); gap = np.nanmax(Lf, axis=1) - np.nanmin(Lf, axis=1)
        return np.c_[Lf, miss[:, 1:].astype(float), np.nan_to_num(spread), np.nan_to_num(gap)]
    if kind == "stack_logit": return np.c_[Lf, miss[:, 1:].astype(float)]
    return Lf


def meta_columns(kind):
    if kind == "stack_unc": return list(INDEP) + [f"{c}_missing" for c in INDEP[1:]] + list(REL) + [f"gap_{a}_{b}" for a, b in PAIRS]
    base = INDEP
    cols = list(base) + ([f"{c}_missing" for c in base[1:]] if kind in ("stack_logit", "stack_reg", "boosted") else [])
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
        if k == "math_only":
            b, _, _ = irls(np.nan_to_num(Z["math"])[:, None], y, 1e-6, None, w); self.model = dict(a=float(b[0]), b=float(b[1]), src="math")
        elif k == "equal_mean": self.model = dict()
        elif k == "boosted": self.model = Stumps().fit(X, y, w)
        else:
            pl = PenalizedLogistic(meta_columns(k))
            self.model = pl.fit_nested(X, y, g, w=w, lambdas=LAMBDAS) if k in ("stack_reg", "stack_unc") else pl.fit(X, y, 1e-2, w=w)
        return self
    def logit(self, Z):
        k = self.kind; X = meta_inputs(Z, k)
        if k == "math_only": return self.model["a"] + self.model["b"] * np.nan_to_num(Z[self.model["src"]], nan=0.0)
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
    if not all(k_ in Z for k_ in REL): kinds = [s for s in kinds if s != "stack_unc"]          # tables without reliability signals
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


MODULE_OF = dict(math="ALBUS", char="NOX", image="LUMOS")


def module_report(comp_metrics, families, previous=None):
    """2026-11-25 one learning loop per module: every module is evaluated ON ITS OWN (development, patient-grouped out-of-fold) and compared with
    the same module in the previous model. NOX and LUMOS: 'improved' when the cross-validated log loss is lower than the previous version's
    (adopting a module version - component_freeze - requires it); ALBUS is not trained here (its loop = detector versions measured against
    expert truth in albus_detection.py, sensitivity may never drop); PERCIVAL is judged on the locked test (acceptance())."""
    prev = (previous or {}).get("component_metrics") or {}; out = {}
    for k, mod in MODULE_OF.items():
        cur = comp_metrics.get(k) or {}; old = prev.get(k) or {}
        rec = dict(module=mod, logloss=cur.get("logloss"), auc=cur.get("auc"), n=cur.get("n"), previous_model=(previous or {}).get("version"),
                   previous_logloss=old.get("logloss"), previous_auc=old.get("auc"),
                   family=(families.get(k) or {}).get("chosen") if k != "math" else "platt recalibration of score_v4")
        if k == "math": rec.update(verdict="not trained here", loop="detector versions are evaluated against expert truth (ALBUS evaluation); a version that loses a detected cSS is rejected")
        elif cur.get("logloss") is None: rec.update(verdict="not evaluable", loop="retrained every cycle; adopted only when better than its previous version")
        elif old.get("logloss") is None: rec.update(verdict="first version", loop="retrained every cycle; adopted only when better than its previous version")
        else:
            d = cur["logloss"] - old["logloss"]
            rec.update(delta_logloss=round(float(d), 4), verdict="improved" if d < 0 else "not improved",
                       loop="retrained every cycle; adopted only when better than its previous version")
        if k == "image":
            mk = (families.get("image") or {}).get("missed_marks") or {}
            npos = int(mk.get("positives", mk.get("available")) or 0)
            rec["missed_marks"] = npos if mk.get("used") else 0; rec["missed_marks_available"] = npos
            rec["rejected_suggestions"] = int(mk.get("n_negative_examples") or 0) if mk.get("used") else 0
            rec["missed_marks_check"] = mk.get("heldout_check")
            rec["loop"] += ("; learned from the expert-marked missed cSS (extra cSS image examples, training folds only)" if mk.get("used")
                            else f"; {mk.get('available')} expert-marked missed cSS not used this cycle (they made LUMOS worse on the candidates)" if mk.get("available")
                            else "; no expert-marked missed cSS to learn from yet")
        out[mod] = rec
    out["PERCIVAL"] = dict(module="PERCIVAL", verdict="see acceptance (locked test cohort)", loop="refitted on the module outputs every cycle; "
                           "becomes active only after acceptance AND your approval")
    return out


def train_cycle(rows, version, seed=0, cnn_epochs=30, progress=None, mins=None, nested=True, features=None, frozen=None, previous=None, image_extra=None,
                char_extra=None):
    """one complete, reproducible training cycle -> model dict (components + meta + calibration + thresholds + full report)"""
    mins = mins or dict(studies=MIN_STUDIES, candidates=MIN_CANDIDATES, per_class=MIN_PER_CLASS)
    check_partitions(rows)
    test = [r for r in rows if r.get("test")]; dev = [r for r in rows if not r.get("test")]
    if len(dev) < 10: raise ValueError(f"too few development candidates ({len(dev)})")
    y = np.array([r["y"] for r in dev], float); g = np.array([r["patient"] for r in dev]); w = patient_weights(dev)
    if min(y.sum(), (1 - y).sum()) < 3: raise ValueError(f"both classes are needed (cSS {int(y.sum())}, not cSS {int((1 - y).sum())})")
    say = progress or (lambda *a: None); say("component out-of-fold predictions", 0.08)
    CC = list((features or {}).get("char") or CHAR)                # Stage 2: the approved NOX feature set (component registry), else built-in
    FZ = {k: v for k, v in (frozen or {}).items() if v}            # Stage 2: frozen component families (component registry) - no re-selection
    kinds = dict(char_kinds=[FZ["char"]] if "char" in FZ else None, image_kinds=[FZ["image"]] if "image" in FZ else None)
    dev_p = {str(r["patient"]) for r in dev}; test_p = {str(r["patient"]) for r in test}
    XI = [r for r in (image_extra or []) if str(r["patient"]) in dev_p and str(r["patient"]) not in test_p and not r.get("test")]   # never a test patient
    XC = [r for r in (char_extra or []) if str(r["patient"]) in dev_p and str(r["patient"]) not in test_p and not r.get("test")]
    TM = [r for r in (char_extra or []) if str(r["patient"]) in test_p or r.get("test")]                 # locked-test marks: evaluation only
    Z, fam = component_oof(dev, seed=seed, cnn_epochs=cnn_epochs, progress=say, char_cols=CC, image_extra=XI, char_extra=XC, **kinds)
    MO = fam.pop("_mark_oof", None) or {}
    if not ((fam.get("image") or {}).get("missed_marks") or {}).get("used"): XI = []      # the marks did not help LUMOS this cycle
    if not ((fam.get("char") or {}).get("missed_marks") or {}).get("used"): XC = []       # ... NOX
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
    C = Components(fam["char"]["chosen"], fam["image"]["chosen"], char_cols=CC).fit(dev, seed, cnn_epochs=cnn_epochs, image_extra=XI, char_extra=XC)
    M = Meta(chosen).fit(Z, y, g, w)
    # 2026-11-25 PERCIVAL scores the re-detected missed cSS with NOX + LUMOS only (ALBUS did not score them; never an input here)
    NA = None
    try: NA = NoAlbus().fit(Z, y, g, w)
    except Exception: NA = None
    mk_dev = None
    if NA is not None and MO.get("keys"):
        zi = np.array([MO.get("image_by_key", {}).get(k, np.nan) for k in MO["keys"]], float)
        lg_ = NA.logit(dict(char=np.asarray(MO["char"], float), image=zi)); fin = np.isfinite(lg_); pp = sigmoid(lg_[fin])
        mk_dev = dict(n=int(fin.sum()), recognised=int((pp >= 0.5).sum()), recall=float((pp >= 0.5).mean()) if fin.any() else None,
                      basis="development, out-of-fold: NOX and LUMOS fold models never saw the mark's patient; the NOX + LUMOS combiner is "
                            "fitted on candidates only")
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
                           lumos_missed_marks=dict(available=len(image_extra or []), used=sum(1 for r in XI if float(r.get("y", 1)) == 1.0),
                                                   rejected_suggestions_used=sum(1 for r in XI if float(r.get("y", 1)) == 0.0),
                                                   patients=len({str(r["patient"]) for r in XI if float(r.get("y", 1)) == 1.0}),
                                                   in_final_fit=getattr(C, "n_marks", 0), nox_marks_used=len(XC), test_marks=len(TM),
                                                   studies=sorted({r["study"] for r in XI}),
                                                   decision=((fam.get("image") or {}).get("missed_marks") or {}).get("decision")),
                           dataset_hash=hashlib.sha256(json.dumps(sorted((r["study"], r["cand_id"], r["y"]) for r in rows)
                                                     + sorted((r["study"], str(r["cand_id"]), "lumos_mark") for r in XI)
                                                + sorted((r["study"], str(r["cand_id"]), "nox_mark") for r in XC)).encode()).hexdigest()[:16]),
                 note="experimental assessment score - trained on this computer on this project's expert reviews; not clinically validated",
                 interpretation="PERCIVAL score = 100 x a CALIBRATED model output on the development cohort. It is a ranking / assessment score, "
                                "not a validated probability of cSS: calibration is checked on the locked test cohort and only on this project's data.")
    model["percival_marks"] = dict(combiner=None if NA is None else NA.to_json(), inputs=NoAlbus.COLS, development=mk_dev,
                                   nox_used=len(XC), note="PERCIVAL score of a re-detected missed cSS = 100 x P(cSS) of the NOX + LUMOS combiner; "
                                   "reported separately, never mixed into the candidate metrics")
    model["features"] = dict(char=CC, nox_version=(features or {}).get("nox_version", NOX_BUILTIN_VERSION),
                             source="component registry NOX active version" if features else f"built-in NOX set ({NOX_BUILTIN_VERSION})")
    model["architecture"] = "ALBUS + NOX + LUMOS -> PERCIVAL (2026-11-25: no Unified, no Fusion component)"
    model["component_config"] = dict(
        ALBUS=dict(input="score_v4 (Platt recalibration, monotone)", registry_version=(features or {}).get("albus_version", "v000")),
        NOX=dict(char_kind=fam["char"]["chosen"], feature_set=CC, frozen="char" in FZ,
                 registry_version=(features or {}).get("nox_version", NOX_BUILTIN_VERSION)),
        LUMOS=dict(image_kind=fam["image"]["chosen"], epochs=cnn_epochs, frozen="image" in FZ, registry_version=(features or {}).get("lumos_version", "v000")),
        PERCIVAL=dict(meta=chosen))
    model["component_interface"] = CI.describe(model)
    model["modules"] = module_report(comp_metrics, fam, previous)
    # Stage 3 small-data honesty (development cohort only; the locked test cohort is not used here)
    from . import analysis as AN
    model["missing_data"] = AN.by_availability(Z, y, p_dev, g)
    try: model["learning_curve"] = AN.learning_curve(Z, y, g, chosen, seed=seed)
    except Exception as e: model["learning_curve"] = dict(error=f"{type(e).__name__}: {e}")
    sg = {k: [((r.get("subgroups") or {}).get(k)) for r in dev] for k in SUBGROUPS}
    model["subgroup_calibration"] = AN.subgroup_calibration(y, p_dev, sg)
    with np.errstate(all="ignore"):
        Lr = np.c_[[Z[c] for c in INDEP]].T; risk = np.nan_to_num(np.nanstd(Lr, axis=1)) + (~np.isfinite(Lr)).sum(1) * 0.5
    model["abstention"] = dict(policy=ABSTENTION_POLICY, development=AN.abstention_curve(y, p_dev, risk))
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
        model["nested"], _ = NS.nested_crossfit(dev, seed=seed, cnn_epochs=cnn_epochs, progress=lambda m, p: say(m, 0.72 + 0.12 * p), char_cols=CC, kinds=kinds,
                                                image_extra=XI, char_extra=XC)
    say("evaluation on the locked test cohort", 0.85)
    model["test"] = evaluate_test(model, test)
    model["test"]["missed_lesions"] = evaluate_marks(model, TM)
    from . import second_look as SLK                                   # 2026-11-25 LUMOS second look: the activation gate for this model
    model["second_look"] = {k: v for k, v in SLK.status(model, {}).items() if k not in ("active", "switched_on")}
    model["model_hash"] = AN.model_hash(model)
    model["model_hash_basis"] = ("sha256 of the trained parts (components, meta-model, ensemble, calibration, thresholds, discovery, feature list, "
                                 "component configuration); retraining on the same dataset with the same seed must reproduce it")
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
    meas = None                                                          # Stage 3 explainability: the NOX measurements behind the score
    if C.char is not None and hasattr(C.char, "contributions"):
        try:
            Xc = CI.NOX.features(rows, char_cols=C.char_cols)["char"]
            meas = np.where(np.isfinite(Xc), np.asarray(C.char.contributions(Xc), float), np.nan)   # a missing measurement explains nothing
        except Exception: meas = None
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
        trig = [sd[i] > 15, spread > 2.5, lim is not None and ood is not None and ood > lim, img_ood]      # Stage 3 abstention policy
        if not learned: status = "insufficient"; reasons.insert(0, "no learned source of evidence for this candidate")
        elif qc == "insufficient_quality": status = "review"; reasons.insert(0, "study image quality insufficient - expert review required")
        elif sum(map(bool, trig)) >= 2: status = "review"; reasons.insert(0, "review required: two or more abstention triggers (abstention policy)")
        elif sd[i] > 15 or spread > 2.5 or (lim is not None and ood is not None and ood > lim) or qc == "low_confidence_review" or (np.isfinite(isp) and isp > 1.0) or img_ood: status = "uncertain"
        else: status = "reliable"
        sc = None if status == "insufficient" or (status == "review" and qc != "insufficient_quality") else float(np.clip(100 * p[i], 0, 100))
        band = None if sc is None else ("red" if sc / 100 < th["red_below"] else "green" if sc / 100 >= th["green_from"] else "yellow")
        pat = IN.pattern_of(dis_table, "char", "image", Z["char"][i], Z["image"][i]) if dis_table else None
        out.append(dict(cand_id=r["cand_id"], percival_score=None if sc is None else round(sc, 1), band=band, status=status, reasons=reasons,
                        uncertainty_sd=round(float(sd[i]), 1), missing=missing, disagreement=round(spread, 2),
                        ood_distance=None if ood is None else round(ood, 2), ood_limit=None if lim is None else round(float(lim), 2),
                        image_tta_spread=None if not np.isfinite(isp) else round(float(isp), 2), qc=qc or None, pattern=pat,
                        image_ood_distance=None if iood is None else round(iood, 2), image_ood_limit=None if ilim is None else round(float(ilim), 2),
                        components={c: (None if not np.isfinite(Z[c][i]) else round(float(sigmoid(Z[c][i])) * 100, 1)) for c in COMPONENTS},
                        contributions=None if contrib is None else {k: round(float(v[i]), 3) for k, v in contrib.items()}, baseline=base,
                        pairwise={f"{a}|{b}": (None if not (np.isfinite(Z[a][i]) and np.isfinite(Z[b][i])) else
                                               dict(gap=round(float(abs(Z[a][i] - Z[b][i])), 2), agree=bool((Z[a][i] >= 0) == (Z[b][i] >= 0)))) for a, b in PAIRS},
                        measurements=_top_measurements(meas, i, C.char_cols)))
    return out


def _top_measurements(meas, i, cols, k=3):
    """the k NOX measurements with the largest log-odds contribution for row i (linear measurement model only), else None"""
    if meas is None or meas.ndim != 2 or i >= len(meas): return None
    v = meas[i]; o = [j for j in np.argsort(-np.abs(np.nan_to_num(v))) if np.isfinite(v[j]) and v[j] != 0][:k]
    return [dict(measurement=cols[j], contribution=round(float(v[j]), 3), direction="towards cSS" if v[j] > 0 else "against cSS") for j in o]


def score_marks(model, marks):
    """PERCIVAL score of re-detected missed cSS (rows with char / maps, no ALBUS score) -> [dict(cand_id, percival_score, nox, lumos)]"""
    d = (model.get("percival_marks") or {}).get("combiner")
    if not d or not marks: return []
    C = Components.from_json(model["components"]); rows = [dict(r, math=np.nan) for r in marks]
    NF = CI.NOX.features(rows, char_cols=C.char_cols); zc = C._char(NF["char"]); zi, _ = C._img(rows)
    lg = NoAlbus.from_json(d).logit(dict(char=zc, image=zi)); out = []
    for r, l, a, b in zip(marks, lg, zc, zi):
        out.append(dict(cand_id=r["cand_id"], percival_score=None if not np.isfinite(l) else round(float(100 * sigmoid(l)), 1),
                        nox=None if not np.isfinite(a) else round(float(100 * sigmoid(a)), 1), lumos=None if not np.isfinite(b) else round(float(100 * sigmoid(b)), 1)))
    return out


def evaluate_marks(model, marks):
    """locked test: how many re-detected missed cSS of test patients PERCIVAL recognises (score >= 50) - a separate number"""
    if not marks: return dict(n=0, note="no confirmed re-detected missed cSS in the locked test cohort")
    S = [s for s in score_marks(model, marks) if s["percival_score"] is not None]
    if not S: return dict(n=0, note="no PERCIVAL score for the test marks")
    k = sum(s["percival_score"] >= 50 for s in S)
    return dict(n=len(S), recognised=int(k), recall=k / len(S), patients=len({str(r["patient"]) for r in marks}),
                basis="locked test patients' expert-marked missed cSS, re-detected by ALBUS and confirmed; PERCIVAL without ALBUS (NOX + LUMOS)")


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
        from . import analysis as AN
        out["by_availability"] = AN.by_availability(Z, y, p, g)
    return out


def acceptance(model, active):
    t = model.get("test", {}); pc = t.get("percival", {}); mt = t.get("math", {}); reasons = []
    if not model.get("ready"): reasons.append("below the minimum data")
    if pc.get("auc") is None: reasons.append("no locked-test evaluation possible yet (too few test candidates)")
    else:
        if mt.get("auc") is not None and pc["auc"] + 1e-9 < mt["auc"]: reasons.append(f"test AUC {pc['auc']:.3f} below ALBUS alone {mt['auc']:.3f}")
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
        np_ = (ns.get("percival") or {}).get("auc"); A_ = ns.get("ablation") or {}; nm = ((A_.get("ALBUS alone") or A_.get("MATH alone")) or {}).get("auc")
        if np_ is None: reasons.append("nested evaluation produced no AUC")
        elif nm is not None and np_ + 1e-9 < nm: reasons.append(f"nested development AUC {np_:.3f} below ALBUS alone {nm:.3f}")
    iden = (model.get("data") or {}).get("identity") or {}
    if iden.get("assumed"): reasons.append(f"patient identity is assumed (one patient per study, not verified) for {iden['assumed']} studies")
    return dict(passed=not reasons, reasons=reasons,
                criteria=f"minimum data; locked test: >= {MIN_TEST_PATIENTS_PER_CLASS} patients per class, AUC >= ALBUS alone, AUC >= active - 0.01, "
                         "Brier <= active + 0.01, calibration slope 0.6-1.6, patient-bootstrap CI available; nested development evaluation "
                         ">= 3 evaluable folds and not below ALBUS alone; verified patient identity. Passing makes a model a CANDIDATE only - "
                         "activation always needs explicit human approval.")


MIN_TEST_PATIENTS_PER_CLASS = 5


def _patient_classes(pc):
    if not pc: return None, None
    return pc.get("with_css"), pc.get("without_css")
