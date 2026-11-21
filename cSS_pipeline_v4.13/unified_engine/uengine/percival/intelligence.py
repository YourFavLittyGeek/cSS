"""intelligence.py - PERCIVAL INTELLIGENCE (v5.23): how much each source of evidence really contributes, where the sources share inputs,
what their disagreements mean, and when a candidate is outside what the models have seen. Local, numpy. Used by meta.train_cycle (on the
development cohort's patient-grouped OUT-OF-FOLD component predictions only) and meta.score_rows (per candidate).

  PROVENANCE        static, from the code: which measurements each component consumes (MATH: detect_css.py score_v4; Unified Score:
                    uscore predictors x1-x5; Characteristic ML: CHAR; Image ML: patch pixels; Fusion: Characteristic + Image) and their
                    pairwise overlap (Jaccard of measurement concepts). Overlap means the components can NOT be treated as independent.
  ablation()        incremental value: patient-grouped CV log loss / AUC of a logistic stack on (a) all independent components, (b) all but
                    one, (c) each alone; the change from (a) to (b) with a paired patient-bootstrap 95 % CI. A component whose removal does
                    not worsen the stack adds no information beyond the others (redundant), whatever its own AUC.
  disagreement()    learned from expert-reviewed cases: for every component pair, the four agreement patterns (both >= 0.5, both < 0.5,
                    A only, B only) with n, observed cSS rate (expert label) and Wilson 95 % CI; and, when they disagree, how often each
                    one sided with the expert. At scoring, the candidate's pattern and its historical cSS rate are reported.
  OOD               Mahalanobis distance of the standardised measurements (CHAR + predictors, medians imputed, Ledoit-Wolf-type shrinkage)
                    to the development cohort; limit = 99th percentile of the development distances. Above -> 'outside the training
                    data' -> the candidate is flagged for expert review (the score is shown but marked uncertain).
  reliability()     calibration table (deciles of the calibrated score: mean score vs observed cSS rate, n).
  stable_thresholds() red / green cut-points with patient-bootstrap uncertainty: red below the 10th percentile of the bootstrap
                    distribution of the sensitivity-0.95 cut, green from the 90th percentile of the specificity-0.90 cut. The yellow band
                    therefore contains both genuine class overlap AND the cut-points' own uncertainty; it is empty only when even the
                    bootstrap shows no overlap (reported as such, never widened by an arbitrary margin)."""
import numpy as np
from ..ml_component import PenalizedLogistic, sigmoid

# measurement concepts per component (derived from the code, not assumed)
PROVENANCE = {
    "math": dict(source="scripts/detect_css.py score_v4 (deterministic product formula, untrained)",
                 concepts=["darkness", "pial_distance", "tubularity", "surface_alignment", "tram_track", "artifact_zone", "midline", "long_structure", "infratentorial"]),
    "unified": dict(source="unified_score/uscore predictors x1-x5 (reliable values only)",
                    concepts=["vessel_continuity", "core_contrast", "pial_distance", "surface_alignment", "extracranial_continuation"]),
    "char": dict(source="detector characteristics (review/<study>_candidates.csv)",
                 concepts=["darkness", "edge_contrast", "pial_distance", "cortex_fraction", "tram_track", "tubularity", "elongation", "volume", "vessel_continuity"]),
    "image": dict(source="surface-aligned MRI patch pixels (minIP, mean, footprint maps)", concepts=["patch_pixels"]),
    "fusion": dict(source="Characteristic ML inputs + Image ML output", concepts=None),
}
PROVENANCE["fusion"]["concepts"] = sorted(set(PROVENANCE["char"]["concepts"]) | set(PROVENANCE["image"]["concepts"]))


def overlap():
    names = list(PROVENANCE); out = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            A, B = set(PROVENANCE[a]["concepts"]), set(PROVENANCE[b]["concepts"])
            out.append(dict(a=a, b=b, shared=sorted(A & B), jaccard=round(len(A & B) / max(len(A | B), 1), 2)))
    return out


# ------------------------------------------------------------------ helpers
def _ll(y, p): p = np.clip(p, 1e-6, 1 - 1e-6); return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def _stack_X(Z, cols):
    L = np.c_[[Z[c] for c in cols]].T; miss = ~np.isfinite(L)
    keep = [j for j in range(len(cols)) if miss[:, j].any() and not miss[:, j].all()]
    return np.c_[np.where(miss, 0.0, L), miss[:, keep].astype(float)]


def _cv_stack(Z, y, g, cols, folds):
    X = _stack_X(Z, cols); oof = np.full(len(y), np.nan)
    for tr, te in folds:
        if len(np.unique(y[tr])) < 2: continue
        try: oof[te] = sigmoid(PenalizedLogistic([f"c{j}" for j in range(X.shape[1])]).fit(X[tr], y[tr], 0.1).logit(X[te]))
        except ValueError: pass
    return oof


def ablation(Z, y, g, comps, folds, auc, boot=200, seed=0):
    y = np.asarray(y, float); g = np.asarray(g).astype(str)
    comps = [c for c in comps if np.isfinite(Z[c]).sum() >= 5]
    if len(comps) < 2: return dict(note="fewer than two components with predictions")
    full = _cv_stack(Z, y, g, comps, folds); ok = np.isfinite(full)
    u = np.unique(g[ok]); gi = {k: np.where((g == k) & ok)[0] for k in u}; rng = np.random.default_rng(seed)
    B = [np.concatenate([gi[k] for k in rng.choice(u, len(u))]) for _ in range(boot)]
    res = dict(all=dict(components=comps, logloss=float(_ll(y[ok], full[ok]).mean()), auc=auc(y[ok], full[ok])), without={}, alone={})
    for c in comps:
        rest = [x for x in comps if x != c]; o = _cv_stack(Z, y, g, rest, folds); m = ok & np.isfinite(o)
        d = _ll(y, o) - _ll(y, full)                                     # > 0: removing c makes the stack worse (c adds information)
        bd = [float(np.nanmean(d[b])) for b in B]
        res["without"][c] = dict(logloss=float(_ll(y[m], o[m]).mean()), auc=auc(y[m], o[m]), delta_logloss=float(np.nanmean(d[m])),
                                 delta_ci=[float(np.percentile(bd, 2.5)), float(np.percentile(bd, 97.5))],
                                 verdict="adds information" if np.percentile(bd, 2.5) > 0 else ("redundant given the others" if np.percentile(bd, 97.5) <= 0.002 else "uncertain"))
        a = _cv_stack(Z, y, g, [c], folds); m2 = np.isfinite(a)
        res["alone"][c] = dict(logloss=float(_ll(y[m2], a[m2]).mean()) if m2.any() else None, auc=auc(y[m2], a[m2]) if m2.any() else None)
    res["note"] = ("delta_logloss = CV log loss of the stack WITHOUT the component minus WITH it (paired, patient bootstrap 95 % CI). "
                   "> 0 with the CI above 0: the component adds information the others do not carry.")
    return res


def _wilson(k, n, z=1.96):
    if n == 0: return [None, None]
    p = k / n; d = 1 + z * z / n; c = (p + z * z / (2 * n)) / d; h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 3), round(min(1.0, c + h), 3)]


def disagreement(Z, y, comps):
    y = np.asarray(y, float); out = []
    for i, a in enumerate(comps):
        for b in comps[i + 1:]:
            m = np.isfinite(Z[a]) & np.isfinite(Z[b])
            if m.sum() < 5: continue
            A, Bv = Z[a][m] >= 0, Z[b][m] >= 0; yy = y[m]; pats = {}
            for name, mask in (("both_high", A & Bv), ("both_low", ~A & ~Bv), (f"{a}_only", A & ~Bv), (f"{b}_only", ~A & Bv)):
                n = int(mask.sum()); k = int(yy[mask].sum())
                pats[name] = dict(n=n, css_rate=round(k / n, 3) if n else None, ci=_wilson(k, n))
            dis = A != Bv; nd = int(dis.sum())
            out.append(dict(a=a, b=b, n=int(m.sum()), patterns=pats, n_disagree=nd,
                            a_right=round(float(((A == (yy == 1)) & dis).sum() / nd), 3) if nd else None,
                            b_right=round(float(((Bv == (yy == 1)) & dis).sum() / nd), 3) if nd else None))
    return out


def pattern_of(table, a, b, la, lb):
    """the candidate's agreement pattern for the pair (a, b) and the cSS rate seen in expert-reviewed cases with that pattern"""
    if la is None or lb is None or not np.isfinite(la) or not np.isfinite(lb): return None
    for t in table or []:
        if t["a"] == a and t["b"] == b:
            k = "both_high" if la >= 0 and lb >= 0 else "both_low" if la < 0 and lb < 0 else (f"{a}_only" if la >= 0 else f"{b}_only")
            return dict(pair=f"{a} vs {b}", pattern=k, **t["patterns"][k])
    return None


# ------------------------------------------------------------------ out-of-distribution
class OOD:
    def fit(self, X):
        X = np.asarray(X, float); self.med = np.array([np.nanmedian(c) if np.isfinite(c).any() else 0.0 for c in X.T])
        Xi = np.where(np.isfinite(X), X, self.med); self.mu = Xi.mean(0); sd = Xi.std(0); self.sd = np.where(sd > 1e-9, sd, 1.0)
        Zs = (Xi - self.mu) / self.sd; S = np.cov(Zs, rowvar=False) if len(Zs) > 2 else np.eye(Zs.shape[1]); S = np.atleast_2d(S)
        a = min(1.0, Zs.shape[1] / max(len(Zs), 1)); S = (1 - a) * S + a * np.eye(S.shape[0])      # shrinkage toward identity
        self.P = np.linalg.pinv(S); d = self.distance(X); self.limit = float(np.percentile(d, 99)) if len(d) else np.inf
        self.n = int(len(X)); return self

    def distance(self, X):
        X = np.asarray(X, float); Zs = (np.where(np.isfinite(X), X, self.med) - self.mu) / self.sd
        return np.sqrt(np.maximum(np.einsum("ij,jk,ik->i", Zs, self.P, Zs), 0))

    def to_json(self): return dict(med=self.med.tolist(), mu=self.mu.tolist(), sd=self.sd.tolist(), P=self.P.tolist(), limit=self.limit, n=self.n)

    @classmethod
    def from_json(cls, d):
        o = cls(); o.med, o.mu, o.sd, o.P = (np.array(d[k], float) for k in ("med", "mu", "sd", "P")); o.limit, o.n = d["limit"], d.get("n"); return o


# ------------------------------------------------------------------ calibration table + thresholds
def reliability(y, p, bins=10):
    y = np.asarray(y, float); p = np.asarray(p, float); m = np.isfinite(p); y, p = y[m], p[m]
    if len(p) < bins: bins = max(2, len(p) // 2)
    q = np.unique(np.percentile(p, np.linspace(0, 100, bins + 1))); out = []
    for i in range(len(q) - 1):
        k = (p >= q[i]) & ((p <= q[i + 1]) if i == len(q) - 2 else (p < q[i + 1]))
        if k.any(): out.append(dict(lo=round(float(q[i]), 3), hi=round(float(q[i + 1]), 3), mean_score=round(float(p[k].mean()), 3),
                                    observed=round(float(y[k].mean()), 3), n=int(k.sum()), ci=_wilson(int(y[k].sum()), int(k.sum()))))
    return out


def _cuts(y, p, ss):
    ts = np.unique(np.r_[0.0, p, 1.0])
    lo = max([t for t in ts if ss(y, p, t)["sensitivity"] >= 0.95] or [0.0])
    hi = min([t for t in ts if ss(y, p, t)["specificity"] >= 0.90] or [1.0])
    return lo, hi


def stable_thresholds(y, p, g, ss, boot=200, seed=0):
    y = np.asarray(y); p = np.asarray(p, float); g = np.asarray(g).astype(str); lo0, hi0 = _cuts(y, p, ss)
    u = np.unique(g); gi = {k: np.where(g == k)[0] for k in u}; rng = np.random.default_rng(seed); L, H = [], []
    for _ in range(boot if len(u) >= 3 else 0):
        t = np.concatenate([gi[k] for k in rng.choice(u, len(u))])
        if len(np.unique(y[t])) < 2: continue
        a, b = _cuts(y[t], p[t], ss); L.append(a); H.append(b)
    red = float(min(lo0, np.percentile(L, 10))) if L else float(lo0)
    green = float(max(hi0, np.percentile(H, 90))) if H else float(hi0)
    green = max(green, red)
    return dict(red_below=red, green_from=green, point_estimates=dict(red_below=float(lo0), green_from=float(hi0)),
                bootstrap=dict(n=len(L), red_cut_p10_p50_p90=[float(np.percentile(L, q)) for q in (10, 50, 90)] if L else None,
                               green_cut_p10_p50_p90=[float(np.percentile(H, q)) for q in (10, 50, 90)] if H else None),
                yellow_empty=bool(green <= red),
                strategy=("red below the 10th percentile (patient bootstrap) of the highest score keeping sensitivity >= 0.95; green from the "
                          "90th percentile of the lowest score with specificity >= 0.90; yellow between = class overlap + cut-point uncertainty "
                          "(development out-of-fold, calibrated). Missing a cSS is the costlier error in a reader-assisted workflow."),
                dev_at_red=ss(y, p, red), dev_at_green=ss(y, p, green))
