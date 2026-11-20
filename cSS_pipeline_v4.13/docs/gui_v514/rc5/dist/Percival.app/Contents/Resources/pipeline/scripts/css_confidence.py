"""cSS confidence model (v5.10). Research software; expert review required. NOT a validated probability.
One logistic model over measures the detector records, grouped in the evidence domains of docs/cSS recognition guide:
  location   skullbase_frac, sylvian_frac, dual_contact_frac, midline_frac, out_frac, infra_frac, rel_height
  form       struct_cls (ball / tube / ribbon indicators), struct_s2_mm / struct_s3_mm (width : thickness), struct_thick_mm, cmb_like
  surface    struct_ctx_frac, struct_surf_cos, cortex_frac, bank_frac, tram_frac, pial_dist_mm
  course     struct_cont, local_cont_max_mm, vessel_wm_mm
  minip      minip_cont, minip_len_mm
  darkness   dark_cv, dark_gap_frac, edge_contrast, darkness_z
  size       log volume, extent_mm
fit(df, y, groups)        -> model dict (weights on standardised features, median imputation; css_model.fit_lr, class-balanced, L2)
confidence(model, df)     -> array 0..100 (sigmoid of the linear score x 100)
explain(model, row)       -> short text: the two domains that lower and the one that raises the score most
A model file review/confidence_model.json is written by fit_confidence.py and read by detect_css.py (column confidence_pct; exclusion E30 with CSS_CONF=1)."""
import json, numpy as np, pandas as pd
import css_model as cm

DOMAINS = dict(
    location=["skullbase_frac", "sylvian_frac", "dual_contact_frac", "midline_frac", "out_frac", "infra_frac", "rel_height"],
    form=["is_ball", "is_tube", "is_ribbon", "width_over_thick", "struct_thick_mm", "cmb_like"],
    surface=["struct_ctx_frac", "struct_surf_cos", "cortex_frac", "bank_frac", "tram_frac", "pial_dist_mm"],
    course=["struct_cont", "local_cont_max_mm", "vessel_wm_mm"],
    minip=["minip_cont", "minip_len_mm"],
    darkness=["dark_cv", "dark_gap_frac", "edge_contrast", "darkness_z"],
    size=["log_volume", "extent_mm"])
FEATURES = [f for d in DOMAINS.values() for f in d]
SCHEMA = "css-confidence/1.0"


def table(df):
    """the feature table (one row per object) from detector columns; missing columns -> NaN (imputed with the training median)"""
    d = pd.DataFrame(df).copy(); g = lambda k: pd.to_numeric(d[k], errors="coerce") if k in d.columns else pd.Series(np.nan, index=d.index)
    cls = d["struct_cls"].astype(str) if "struct_cls" in d.columns else pd.Series("", index=d.index)
    X = pd.DataFrame(index=d.index)
    for f in FEATURES:
        if f == "is_ball": X[f] = (cls == "BALL").astype(float)
        elif f == "is_tube": X[f] = (cls == "TUBE").astype(float)
        elif f == "is_ribbon": X[f] = (cls == "RIBBON").astype(float)
        elif f == "width_over_thick": X[f] = g("struct_s2_mm") / g("struct_s3_mm").clip(lower=0.1)
        elif f == "log_volume": X[f] = np.log(g("volume_mm3").clip(lower=1.0))
        else: X[f] = g(f)
    return X


def fit(df, y, l2=1.0):
    X = table(df).to_numpy(float); Z, med, mu, sd = cm.prep(X); w, b = cm.fit_lr(Z, np.asarray(y, float), l2)
    return dict(schema=SCHEMA, features=FEATURES, med=med.tolist(), mu=mu.tolist(), sd=sd.tolist(), w=np.asarray(w).tolist(), b=float(b), l2=l2)


def _z(model, df):
    X = table(df)[model["features"]].to_numpy(float); med, mu, sd = (np.array(model[k], float) for k in ("med", "mu", "sd"))
    return (np.where(np.isfinite(X), X, med) - mu) / sd


def confidence(model, df):
    t = _z(model, df) @ np.array(model["w"], float) + model["b"]
    return np.round(100.0 / (1.0 + np.exp(-np.clip(t, -40, 40))), 1)


def explain(model, row):
    Z = _z(model, pd.DataFrame([dict(row)]))[0]; w = np.array(model["w"], float); c = {}
    for dom, fs in DOMAINS.items(): c[dom] = float(sum(w[model["features"].index(f)] * Z[model["features"].index(f)] for f in fs))
    o = sorted(c.items(), key=lambda kv: kv[1]); low = [f"{k} {v:+.1f}" for k, v in o[:2] if v < -0.05]; up = [f"{k} {v:+.1f}" for k, v in o[-1:] if v > 0.05]
    return ("lowered by " + ", ".join(low) if low else "nothing lowers it") + ("; raised by " + ", ".join(up) if up else "")


def load(path):
    m = json.load(open(path))
    if m.get("schema") != SCHEMA or m.get("features") != FEATURES: raise ValueError(f"confidence model {path}: schema or feature list differs from this code - refit with fit_confidence.py")
    return m
