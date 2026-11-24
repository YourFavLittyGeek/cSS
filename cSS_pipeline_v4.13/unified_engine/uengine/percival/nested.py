"""nested.py - Percival v5.25: patient-specific NESTED cross-fitting of the complete development procedure.

Why: single-level stacking (component out-of-fold predictions first, then cross-validation of the meta-model on that table) lets a
held-out patient influence its own evaluation indirectly - the out-of-fold predictions of the OTHER patients, on which the meta-model
of that fold is trained, came from component models that were fitted with the held-out patient. The same holds for family selection,
penalty choice, calibration and threshold selection when they are done once on all development patients and then "evaluated".

Procedure (for every outer fold; the outer folds partition PATIENTS, never candidates):
  1. the held-out patients are removed completely;
  2. on the remaining (outer-training) patients only: component families are compared and chosen (meta.component_oof with its own
     inner patient-grouped folds), inner out-of-fold component log-odds are produced, Fusion is trained on inner out-of-fold inputs,
     the meta-model is discovered (1-SE rule) on the inner table, Platt calibration is fitted on the meta-model's inner out-of-fold
     log-odds, and the red / green thresholds are chosen on those inner calibrated scores;
  3. the components are refitted on the outer-training patients and applied ONCE to the held-out patients, then the meta-model, the
     calibration and the thresholds of step 2 are applied without refitting;
  4. provenance of the fold is recorded (patients on each side, chosen families, meta-model, calibration, thresholds, hashes).
The concatenated held-out predictions estimate the performance of the WHOLE procedure (selection included) on patients it never saw.
Every learned transformation (imputation medians, standardisation, penalties, tree splits, calibration, thresholds) is fitted in step 2.

Ablations (same nested folds, same held-out predictions of the components): a regularised logistic stack is fitted on the inner table
for each subset of components (missing inputs are imputed with the training median and flagged by an indicator - never a negative)
and applied to the held-out components. Paired patient-bootstrap CIs compare each subset with the full Percival pipeline.

Interpretation: these are internal, patient-separated cross-validated estimates on THIS project's development cohort. They are not an
independent held-out evaluation (that is the locked test cohort) and not a clinical validation.
"""
import hashlib, json
import numpy as np
from ..ml_component import PenalizedLogistic, sigmoid, irls
from . import meta as MT
from . import intelligence as IN

ENGINE = "percival-nested/1.0"
K_OUTER, K_INNER = 5, 3

# subsets of the level-0 components compared in the ablation (names are the user-facing component names)
ABLATIONS = {
    "Characteristic ML alone": ["char"],
    "Image ML alone": ["image"],
    "Unified Score alone": ["unified"],
    "MATH alone": ["math"],
    "Characteristic + Image": ["char", "image"],
    "Characteristic + Unified": ["char", "unified"],
    "Image + Unified": ["image", "unified"],
    "Fusion alone": ["fusion"],
    "All components (stack)": ["math", "unified", "char", "image"],
    "Without Unified Score": ["math", "char", "image"],
    "Without Image ML": ["math", "unified", "char"],
    "Without Characteristic ML": ["math", "unified", "image"],
}


def _subset_X(Z, cols):
    L = np.c_[[np.asarray(Z[c], float) for c in cols]].T
    miss = ~np.isfinite(L)
    return np.c_[L, miss.astype(float)] if len(cols) else L


class SubsetStack:
    """regularised logistic on the log-odds of a subset of components + one missing-input indicator per component"""
    def __init__(self, cols): self.cols, self.m = list(cols), None

    def fit(self, Z, y, g, w=None):
        X = _subset_X(Z, self.cols)
        if not np.isfinite(X[:, :len(self.cols)]).any(): raise ValueError("no input available")
        names = self.cols + [f"{c}_missing" for c in self.cols]
        pl = PenalizedLogistic(names)
        self.m = pl.fit_nested(X, y, g, w=w, lambdas=MT.LAMBDAS) if len(np.unique(g)) >= 3 else pl.fit(X, y, 1.0, w=w)
        return self

    def logit(self, Z):
        X = _subset_X(Z, self.cols); out = self.m.logit(X)
        none = ~np.isfinite(X[:, :len(self.cols)]).any(1)
        out[none] = np.nan                                        # no input at all for this candidate: unavailable, not a value
        return out


def _paired_auc_delta(y, a, b, g, n=500, seed=0):
    """patient-bootstrap distribution of AUC(a) - AUC(b) on the candidates where both are available"""
    m = np.isfinite(a) & np.isfinite(b); y, a, b, g = y[m], a[m], b[m], np.asarray(g).astype(str)[m]
    if len(y) < 10 or len(np.unique(y)) < 2: return None
    u = np.unique(g); gi = {k: np.where(g == k)[0] for k in u}; r = np.random.default_rng(seed); D = []
    for _ in range(n):
        t = np.concatenate([gi[k] for k in r.choice(u, len(u))]); x, z = MT.auc(y[t], a[t]), MT.auc(y[t], b[t])
        if x is not None and z is not None: D.append(x - z)
    if len(D) < 50: return None
    d0 = MT.auc(y, a) - MT.auc(y, b)
    return dict(delta_auc=float(d0), ci=[float(np.percentile(D, 2.5)), float(np.percentile(D, 97.5))], n=int(len(y)), patients=int(len(u)))


def _support(y, g, folds_used):
    g = np.asarray(g).astype(str); pos = {p for p, t in zip(g, y) if t == 1}; allp = set(g)
    return dict(candidates=int(len(y)), patients=len(allp), patients_with_css=len(pos), patients_without_css=len(allp - pos),
                css_candidates=int(np.sum(y)), not_css_candidates=int(len(y) - np.sum(y)), evaluable_folds=int(folds_used))


def _stability(sup):
    """plain-language warning when the estimate rests on too few patients (not a validity threshold)"""
    w = []
    if sup["patients_with_css"] < 10: w.append(f"only {sup['patients_with_css']} patients with cSS - estimates are unstable")
    if sup["patients_without_css"] < 10: w.append(f"only {sup['patients_without_css']} patients without cSS - estimates are unstable")
    if sup["evaluable_folds"] < 3: w.append(f"only {sup['evaluable_folds']} outer folds could be evaluated")
    return w


def nested_crossfit(dev, k_outer=K_OUTER, k_inner=K_INNER, seed=0, cnn_epochs=30, progress=None, ablations=True, char_cols=None, kinds=None):
    """-> report dict (JSON-serialisable) and arrays dict (held-out predictions, for tests)"""
    say = progress or (lambda *a: None)
    y = np.array([r["y"] for r in dev], float); g = np.array([str(r["patient"]) for r in dev]); w = MT.patient_weights(dev)
    F = MT.folds(g, k_outer, seed + 101)
    Zout = {c: np.full(len(dev), np.nan) for c in MT.COMPONENTS}
    lg_out = np.full(len(dev), np.nan); p_out = np.full(len(dev), np.nan); band = np.array([None] * len(dev), dtype=object)
    abl_out = {name: np.full(len(dev), np.nan) for name in ABLATIONS} if ablations else {}
    prov, used = [], 0
    for i, (tr, te) in enumerate(F):
        leak = set(g[tr]) & set(g[te])
        if leak: raise AssertionError(f"patient leakage in outer fold {i}: {sorted(leak)[:3]}")
        R = [dev[j] for j in tr]; T = [dev[j] for j in te]
        if len(np.unique(y[tr])) < 2 or min(y[tr].sum(), (1 - y[tr]).sum()) < 3:
            prov.append(dict(fold=i, skipped="the outer-training patients do not contain both classes (>= 3 each)", heldout_patients=sorted(set(g[te]))))
            continue
        sub = lambda m, p: say(f"nested fold {i + 1}/{len(F)}: {m}", (i + p) / len(F))
        # step 2: the whole development procedure on the outer-training patients only
        Zin, fam = MT.component_oof(R, k=k_inner, seed=seed + 1000 * (i + 1), cnn_epochs=cnn_epochs, progress=lambda m, p: sub(m, 0.7 * p), char_cols=char_cols, **(kinds or {}))
        ytr, gtr, wtr = y[tr], g[tr], w[tr]
        C = MT.Components(fam["char"]["chosen"], fam["image"]["chosen"], fam["fusion"]["chosen"], char_cols=char_cols).fit(
            R, seed, image_logit_oof=Zin["image"], char_logit_oof=Zin["char"], cnn_epochs=cnn_epochs)
        D, oofs_in = MT.discover(Zin, ytr, gtr, wtr, k=k_inner, seed=seed + 1000 * (i + 1))
        chosen = D["chosen"]; Mm = MT.Meta(chosen).fit(Zin, ytr, gtr, wtr)
        cb, _, _ = irls(np.nan_to_num(oofs_in[chosen])[:, None], ytr, MT.CAL_LAMBDA); cal = dict(a=float(cb[0]), b=float(cb[1]))
        p_in = sigmoid(cal["a"] + cal["b"] * oofs_in[chosen]); th = MT.thresholds(ytr, p_in)
        sub("held-out scoring", 0.9)
        # step 3: apply once to the held-out patients - nothing is refitted here
        Zt = C.predict(T)
        for c in MT.COMPONENTS: Zout[c][te] = Zt[c]
        lt = Mm.logit(Zt); lg_out[te] = lt; pt = sigmoid(cal["a"] + cal["b"] * lt); p_out[te] = pt
        band[te] = np.where(pt < th["red_below"], "red", np.where(pt >= th["green_from"], "green", "yellow"))
        for name in abl_out:
            cols = ABLATIONS[name]
            try: abl_out[name][te] = SubsetStack(cols).fit(Zin, ytr, gtr, wtr).logit(Zt)
            except Exception: pass
        used += int(len(np.unique(y[te])) == 2)
        prov.append(dict(fold=i, train_patients=len(set(gtr)), heldout_patients=sorted(set(g[te])), n_train=int(len(tr)), n_heldout=int(len(te)),
                         train_hash=hashlib.sha256(json.dumps(sorted(set(gtr))).encode()).hexdigest()[:12],
                         families=dict(char=fam["char"]["chosen"], image=fam["image"]["chosen"], fusion=fam["fusion"]["chosen"]),
                         meta=chosen, calibration=cal, thresholds=dict(red_below=th["red_below"], green_from=th["green_from"]),
                         fitted_on="outer-training patients only (families, penalties, imputation, scaling, fusion, meta-model, calibration, thresholds)"))
    fin = np.isfinite(p_out)
    sup = _support(y[fin], g[fin], used)
    pipe = MT.metrics(y[fin], p_out[fin], g[fin]) if fin.sum() >= 5 else dict(n=int(fin.sum()))
    if fin.sum() >= 5 and len(np.unique(y[fin])) == 2:
        yy, bb = y[fin], band[fin]
        red, green = bb == "red", bb == "green"
        pos = ~red                                                        # "not red" = flagged for attention (sensitivity-oriented cut)
        tp, fn = int((pos & (yy == 1)).sum()), int((~pos & (yy == 1)).sum()); fp, tn = int((pos & (yy == 0)).sum()), int((~pos & (yy == 0)).sum())
        pipe["at_red_cut"] = dict(rule="positive = not red (each fold's own threshold)", tp=tp, fn=fn, fp=fp, tn=tn,
                                  sensitivity=tp / max(tp + fn, 1), specificity=tn / max(tn + fp, 1), ppv=tp / (tp + fp) if tp + fp else None, npv=tn / (tn + fn) if tn + fn else None)
        tp, fn = int((green & (yy == 1)).sum()), int((~green & (yy == 1)).sum()); fp, tn = int((green & (yy == 0)).sum()), int((~green & (yy == 0)).sum())
        pipe["at_green_cut"] = dict(rule="positive = green (each fold's own threshold)", tp=tp, fn=fn, fp=fp, tn=tn,
                                    sensitivity=tp / max(tp + fn, 1), specificity=tn / max(tn + fp, 1), ppv=tp / (tp + fp) if tp + fp else None, npv=tn / (tn + fn) if tn + fn else None)
        pipe["calibration_curve"] = IN.reliability(yy, p_out[fin])
    comps = {c: (MT.metrics(y[np.isfinite(Zout[c])], sigmoid(Zout[c][np.isfinite(Zout[c])]), g[np.isfinite(Zout[c])])
                 if np.isfinite(Zout[c]).sum() >= 5 else dict(n=int(np.isfinite(Zout[c]).sum()))) for c in MT.COMPONENTS}
    abl = {}
    for name, v in abl_out.items():
        m = np.isfinite(v)
        e = MT.metrics(y[m], sigmoid(v[m]), g[m]) if m.sum() >= 5 else dict(n=int(m.sum()))
        e["inputs"] = ABLATIONS[name]; e["vs_percival"] = _paired_auc_delta(y, lg_out, v, g, seed=seed)
        abl[name] = e
    rep = dict(engine=ENGINE, k_outer=k_outer, k_inner=k_inner, seed=seed, support=sup, stability_warnings=_stability(sup),
               percival=pipe, components=comps, ablation=abl, folds=prov,
               basis="nested patient-grouped cross-validation on the development cohort (held-out patients never influence any fitted or "
                     "selected quantity of their fold); internal estimate - not an independent or clinical validation")
    arrays = dict(p=p_out, logit=lg_out, Z=Zout, band=band, ablation=abl_out, folds=F)
    return rep, arrays
