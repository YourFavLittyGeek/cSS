"""data_validation.py - input-table validation and leakage checks (feature leakage, label leakage, partition leakage).

Checks (each returns findings; assert_* variants raise):
  predictors_allowed       no identifier / label / score / rule flag / model output / provenance / deprecated column as a predictor
  partition_disjoint       no patient on both sides of any split; protected test patients never in development data
  near_perfect_separation  a single predictor with training AUC >= 0.98 (or <= 0.02) is flagged as a leakage suspect
  derived_from_model_output a predictor almost identical (|r| >= 0.98) to a historical model output present in the table
  duplicate_objects        identical object fingerprints / identical feature vectors in different patients (copied exams)
  test_label_invariance    fitted procedure: changing the TEST labels must not change any test prediction
  preprocessing_isolation  fitted procedure: changing TEST feature values must not change the fitted preprocessing / weights
  schema_ranges            hard-range violations per column (counts), via characteristics_component.check_value"""
import numpy as np
from . import feature_schema as fs
from .characteristics_component import check_value


class LeakageError(RuntimeError): pass


def predictors_allowed(columns):
    return [c for c in columns if fs.is_forbidden_predictor(c)]


def assert_predictors_allowed(columns):
    bad = predictors_allowed(columns)
    if bad: raise LeakageError(f"forbidden predictors (ids / labels / scores / model outputs / flags): {bad}")


def partition_disjoint(train_patients, test_patients, protected=None):
    tr, te = set(map(str, train_patients)), set(map(str, test_patients)); f = []
    if tr & te: f.append(f"patients on both sides: {sorted(tr & te)[:5]}")
    if protected is not None:
        p = set(protected.patients)
        if p & tr: f.append(f"protected test patients in the training part: {sorted(p & tr)[:5]}")
    return f


def near_perfect_separation(X, y, names, hi=0.98):
    from .model_evaluation import auc
    out = []
    for j, n in enumerate(names):
        x = np.asarray(X)[:, j]; ok = np.isfinite(x)
        if ok.sum() < 10 or len(set(np.asarray(y)[ok])) < 2: continue
        a = auc(np.asarray(y)[ok], x[ok])
        if a >= hi or a <= 1 - hi: out.append(dict(column=n, auc=round(float(a), 4)))
    return out


def derived_from_model_output(df, predictors, r_hi=0.98):
    outs = [c for c in fs.columns_by_role("model_output") + ["score_model", "p_cal", "p_raw", "confidence_lopo_pct"] if c in df.columns]
    f = []
    for p in predictors:
        if p not in df.columns: continue
        for o in outs:
            a = np.asarray(df[p], float); b = np.asarray(df[o], float) if df[o].dtype != object else None
            if b is None: continue
            ok = np.isfinite(a) & np.isfinite(b)
            if ok.sum() > 10 and np.std(a[ok]) > 0 and np.std(b[ok]) > 0 and abs(np.corrcoef(a[ok], b[ok])[0, 1]) >= r_hi:
                f.append(dict(predictor=p, model_output=o))
    return f


def duplicate_objects(df, patient_col="patient_key", feature_cols=None):
    f = []
    feats = feature_cols or [c for c in fs.INITIAL_FEATURES if c in df.columns]
    if feats:
        A = np.round(df[feats].apply(lambda c: c.astype(float)).to_numpy(float), 6)
        key = ["|".join("nan" if not np.isfinite(v) else repr(float(v)) for v in row) for row in A]   # NaN-safe (pandas 3 keeps NaN as float)
        for k, g in df.groupby(np.asarray(key)):
            if g[patient_col].nunique() > 1 and len(feats) >= 3: f.append(dict(kind="identical feature vector", patients=sorted(g[patient_col].unique())[:5]))
    return f


def schema_ranges(df):
    out = {}
    for c in fs.measured():
        if c not in df.columns: continue
        st = [check_value(c, v)[1] for v in df[c]]
        n = sum(s == "out_of_range" for s in st)
        if n: out[c] = n
    return out


def test_label_invariance(fit_predict, X, y, tr, te, seed=0):
    """fit_predict(X, y, tr, te) -> predictions for te. Flipping y[te] must not change them."""
    p1 = np.asarray(fit_predict(X, y, tr, te), float)
    y2 = np.asarray(y, float).copy(); y2[te] = 1 - y2[te]
    p2 = np.asarray(fit_predict(X, y2, tr, te), float)
    return bool(np.allclose(p1, p2, equal_nan=True))


def preprocessing_isolation(fit_params, X, y, tr, te, seed=0):
    """fit_params(X, y, tr) -> 1-D array of fitted parameters. Overwriting X[te] with noise must not change them."""
    a = np.asarray(fit_params(X, y, tr), float)
    X2 = np.array(X, float, copy=True); X2[te] = np.random.default_rng(seed).normal(0, 100, X2[te].shape)
    b = np.asarray(fit_params(X2, y, tr), float)
    return bool(np.allclose(a, b))
