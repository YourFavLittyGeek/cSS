"""ablation.py - SYNTHETIC ablation and stress experiment for the Unified Score architecture, run THROUGH the prototype
(prototype.fusion.UnifiedScorer) on identical patient-grouped folds.

Models (same inputs, same folds):
  math_only            MATH alone (recalibrated score_v4)
  learned_only         PAST EXPERIENCE on CHARACTERISTICS without MATH
  offset               proposed: MATH logit + learned increment (offset model)
  offset_nonoverlap    offset model on the 5 inputs NOT used by score_v4 (edge_contrast, cortex_frac, elongation_3d, log_volume_mm3,
                       local_cont_max_mm; tram_frac_missing is excluded because score_v4 already treats a missing tram_frac as 0)
  naive                MATH logit + independent learned logit (double counting)
  joint                characteristics + math logit as a free column
  legacy_confidence    v5.10 procedure (comparator; baseline scenario only - slow)
  lofo:<col>           offset model without one input column (baseline scenario only)
Scenarios: baseline (signal 1), weak signal, pure noise, difficult mimics, MCAR missing, informative missing, scanner darkness variation,
volume scaling, and 'truth = MATH only' (labels regenerated from score_v4: any learned gain there is spurious).
Metrics per model: within-patient AUC (primary), fold-wise AUC, pooled AUC, AP, log loss, Brier, calibration slope / CITL / ECE,
sensitivity / specificity at a training-part threshold (target sensitivity 0.9), patient-cluster bootstrap CIs, paired bootstrap of the
within-patient AUC difference vs math_only."""
import numpy as np
from . import synthetic as sy, experiment as ex, patient_split as ps, model_evaluation as ev, feature_schema as fs, ml_component as ml
from .calibration import calibration_slope_intercept, reliability
from .prototype.fusion import UnifiedScorer

NONOVERLAP = [c for c in fs.INITIAL_COLUMNS if (fs.TRANSFORMS[c][0] if c in fs.TRANSFORMS else fs.INITIAL_INDICATORS.get(c, c)) not in fs.MATH_USE["score_v4"]]
SCENARIOS = {
    "baseline": dict(signal=1.0), "weak_signal": dict(signal=0.4), "pure_noise": dict(signal=0.0),
    "difficult_mimics": dict(signal=1.0, mimic_overlap=0.7), "missing_mcar_25pct": dict(signal=1.0, extra_missing=0.25),
    "missing_informative_tram": dict(signal=1.0, informative_missing=0.6), "scanner_darkness_sd1.5": dict(signal=1.0, dark_offset_sd=1.5),
    "volume_scaling_sd0.7": dict(signal=1.0, volume_scale_sd=0.7), "truth_math_only": dict(signal=1.0, relabel_from_math=True)}


def _proto(mode, columns=None):
    class S:
        name = mode
        def fit(self, d, y, p):
            self.u = UnifiedScorer(mode, columns or fs.INITIAL_COLUMNS, n_boot=0).fit(d, y); return self
        def score(self, d):
            return np.array([r.unified["p"] if r.unified["p"] is not None else np.nan for r in self.u.predict(d)], float)
    return S


def cohort(seed, n_patients=40, relabel_from_math=False, **kw):
    O, E, P = sy.make_cohort(n_patients, seed=seed, **kw); D = ex.population(O)
    if relabel_from_math:                                    # labels caused by MATH only (synthetic truth); characteristics unchanged
        r = np.random.default_rng(seed + 991); lp = -1.0 + 2.2 * np.log(D.score_v4.to_numpy(float) + 0.05)
        D = D.assign(y=(r.random(len(D)) < ml.sigmoid(lp)).astype(float))
        P = P.assign(positive=[int(D.y[D.patient_key == q].max()) if (D.patient_key == q).any() else 0 for q in P.patient_key])
    return D, E, P


def metrics(y, s, pid, folds, thresholds, B=300, seed=0):
    ok = np.isfinite(s); d = ev.auc_decomposition(y[ok], s[ok], pid[ok])
    fa = [ev.auc(y[ok & (folds == k)], s[ok & (folds == k)]) for k in sorted(set(folds[ok]))]
    conf = [ev.confusion(y[ok & (folds == k)], s[ok & (folds == k)], t) for k, t in thresholds.items() if np.isfinite(t)]
    tp, fn, fp, tn = (sum(c[x] for c in conf) for x in ("tp", "fn", "fp", "tn"))
    c = calibration_slope_intercept(y[ok], s[ok]); wi = lambda a, b, p: ev.auc_decomposition(a, b, p)["within"]
    return dict(within=d["within"], within_ci=ev.cluster_bootstrap(wi, y[ok], s[ok], pid[ok], B=B, seed=seed), pooled=d["pooled"],
                between=d["between"], fold_auc_mean=float(np.nanmean(fa)), fold_auc_sd=float(np.nanstd(fa)), ap=ev.average_precision(y[ok], s[ok]),
                logloss=ml.logloss(y[ok], np.clip(s[ok], 1e-6, 1 - 1e-6)), brier=ev.brier(y[ok], s[ok]), cal_slope=c["slope"], cal_citl=c["citl"],
                ece=reliability(y[ok], s[ok])[1], sensitivity=tp / (tp + fn) if tp + fn else np.nan, specificity=tn / (tn + fp) if tn + fp else np.nan,
                n_scored=int(ok.sum()))


def paired_delta(y, s1, s0, pid, B=300, seed=0):
    ok = np.isfinite(s1) & np.isfinite(s0); S = np.c_[s1[ok], s0[ok]]
    f = lambda a, b, p: ev.auc_decomposition(a, b[:, 0], p)["within"] - ev.auc_decomposition(a, b[:, 1], p)["within"]
    return f(y[ok], S, pid[ok]), ev.cluster_bootstrap(f, y[ok], S, pid[ok], B=B, seed=seed)


def run_scenario(name, seed, n_splits=5, n_repeats=2, legacy=False, lofo=False, B=300, n_patients=40):
    kw = dict(SCENARIOS[name]); D, E, P = cohort(seed, n_patients=n_patients, **kw)
    y = D.y.to_numpy(float); pid = D.patient_key.astype(str).to_numpy(); lab = {q: int(y[pid == q].max()) for q in set(pid)}
    A = ps.grouped_folds(sorted(set(pid)), n_splits, n_repeats, seed, lab)
    scorers = [ev.Scorer(m, _proto(m)) for m in ("math_only", "learned_only", "offset", "naive", "joint")]
    scorers.append(ev.Scorer("offset_nonoverlap", _proto("offset", NONOVERLAP)))
    if legacy: scorers.append(ev.Scorer("legacy_confidence", ml.LegacyConfidence))
    if lofo: scorers += [ev.Scorer(f"lofo:{c}", _proto("offset", [x for x in fs.INITIAL_COLUMNS if x != c])) for c in fs.INITIAL_COLUMNS]
    R = ev.cross_validate(D, y, pid, A, scorers)
    out = dict(scenario=name, seed=seed, config=kw, n_candidates=len(D), n_cSS=int(y.sum()), n_patients=len(set(pid)),
               prevalence=float(y.mean()), assignment_digest=A.digest(), failures={k: v.failures for k, v in R.items() if v.failures}, models={})
    base = R["math_only"].oof[0]; full = R["offset"].oof[0]
    for k, res in R.items():
        reps = [metrics(y, res.oof[r], pid, res.fold[r], {kk: t for (rr, kk), t in res.thresholds.items() if rr == r}, B=B if r == 0 else 0, seed=seed)
                for r in res.oof]
        m = {f: float(np.nanmean([x[f] for x in reps if x[f] is not None])) for f in reps[0] if f not in ("within_ci",)}
        m["within_ci"] = reps[0]["within_ci"]
        m["delta_vs_math"], m["delta_vs_math_ci"] = paired_delta(y, res.oof[0], base, pid, B=B, seed=seed) if k != "math_only" else (0.0, None)
        if k.startswith("lofo:"): m["delta_vs_full_offset"], m["delta_vs_full_ci"] = paired_delta(y, res.oof[0], full, pid, B=B, seed=seed)
        out["models"][k] = m
    return out


def uncertainty_check(seed, n_boot=30, **kw):
    """offset model with bootstrap intervals, one CV repeat: observed cSS rate per category (does 'uncertain' hold the hard cases?)"""
    D, E, P = cohort(seed, **(kw or SCENARIOS["baseline"])); y = D.y.to_numpy(float); pid = D.patient_key.astype(str).to_numpy()
    A = ps.grouped_folds(sorted(set(pid)), 5, 1, seed, {q: int(y[pid == q].max()) for q in set(pid)})
    cat = np.empty(len(D), object); p = np.full(len(D), np.nan)
    for tr, te in ps.fold_indices(A, pid, 0):
        u = UnifiedScorer("offset", n_boot=n_boot, seed=seed).fit(D.iloc[tr].reset_index(drop=True), y[tr])
        for i, r in zip(te, u.predict(D.iloc[te].reset_index(drop=True))): cat[i] = r.unified["category"]; p[i] = r.unified["p"]
    rows = {}
    for c in ("likely_cSS", "uncertain", "unlikely_cSS", "not_scorable"):
        m = cat == c; rows[c] = dict(n=int(m.sum()), observed_cSS_rate=float(y[m].mean()) if m.any() else None,
                                     mean_p=float(np.nanmean(p[m])) if m.any() else None)
    return dict(seed=seed, n=len(D), categories=rows)


PERMUTE_SOURCES = ["darkness_z", "edge_contrast", "pial_dist_mm", "cortex_frac", "tram_frac", "tube_ratio", "elongation_3d", "volume_mm3",
                   "local_cont_max_mm"]


def _cv_within(D, y, pid, A, mode, columns=None):
    s = np.full(len(y), np.nan)
    for tr, te in ps.fold_indices(A, pid, 0):
        u = UnifiedScorer(mode, columns or fs.INITIAL_COLUMNS, n_boot=0).fit(D.iloc[tr].reset_index(drop=True), y[tr])
        s[te] = [r.unified["p"] for r in u.predict(D.iloc[te].reset_index(drop=True))]
    ok = np.isfinite(s); return ev.auc_decomposition(y[ok], s[ok], pid[ok])["within"], s


def permutation_test_increment(name, seed, n_perm=39, n_patients=40, B=300):
    """H0: the characteristics carry no information beyond MATH. Null: permute the 9 measured characteristic columns JOINTLY among the
    candidates of the same patient (keeps their joint distribution, the patient structure and every MATH output; breaks only the
    characteristics-label link given MATH), refit the whole cross-validated offset model each time. p = (1 + #null >= observed) / (1 + n_perm).
    Also returns the paired patient-bootstrap CI of the same observed delta, to compare the two decision rules."""
    kw = dict(SCENARIOS[name]); D, E, P = cohort(seed, n_patients=n_patients, **kw)
    y = D.y.to_numpy(float); pid = D.patient_key.astype(str).to_numpy()
    A = ps.grouped_folds(sorted(set(pid)), 5, 1, seed, {q: int(y[pid == q].max()) for q in set(pid)})
    w0, s0 = _cv_within(D, y, pid, A, "math_only"); w1, s1 = _cv_within(D, y, pid, A, "offset")
    obs = w1 - w0; _, ci = paired_delta(y, s1, s0, pid, B=B, seed=seed)
    rng = np.random.default_rng(seed + 7); null = []; groups = [np.where(pid == q)[0] for q in sorted(set(pid))]
    cols = [c for c in PERMUTE_SOURCES if c in D.columns]
    for _ in range(n_perm):
        Dp = D.copy(); V = Dp[cols].to_numpy(copy=True)
        for g in groups: V[g] = V[rng.permutation(g)]
        Dp[cols] = V; null.append(_cv_within(Dp, y, pid, A, "offset")[0] - w0)
    null = np.array(null)
    return dict(scenario=name, seed=seed, observed_delta=float(obs), bootstrap_ci=ci, bootstrap_excludes_0=bool(ci and ci[0] > 0),
                perm_p=float((1 + (null >= obs).sum()) / (1 + n_perm)), null_mean=float(null.mean()), null_sd=float(null.std()),
                null_q95=float(np.quantile(null, 0.95)), n_perm=n_perm)
