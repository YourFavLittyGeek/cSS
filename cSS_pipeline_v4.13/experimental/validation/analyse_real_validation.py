"""Real-data validation analysis of the experimental structural modules (read-only; descriptive; nothing is tuned).

Usage: analyse_real_validation.py RUN_DIR --dev "M02 M03 ..." --heldout "M12 ..." --scripts $CSS_BASE/scripts [--no-inherited]

Inputs: RUN_DIR/configs/<CFG>/<ID>/features.csv (+ seeds.csv for D) from run_real_validation.sh and, read-only from
$CSS_BASE/review: ID_candidates.csv, ID_excluded.csv, ID_calls_<reader>.csv (or ID_calls.csv), ID_excluded_audit_<reader>.csv,
ID_missed.csv, adjudication.csv, radiologist_grades.csv.

LABELS (no expert lesion-level annotation exists for this cohort; these are READER levels and are never merged silently):
  per read: cSS | non-cSS (Vessel, Normal, Artifact, Microbleed) | indeterminate (Unsure, Near ICH, anything else)
  consensus per object (radiologist patient-level grade = only expert reference, used for the side):
    definite_cSS   >= 2 reads, all cSS, side graded > 0 (or adjudicated cSS)
    probable_cSS   >= 1 cSS read, no non-cSS read, side graded > 0, not definite (single reader or cSS + unsure)
    disputed       cSS and non-cSS reads on a side graded > 0
    non_cSS        >= 1 read, no cSS read (or adjudicated non-cSS) - includes read objects on radiologist-zero sides
    conflict_zero  a cSS read on a side the radiologist graded 0
    unread_zero    no read, side graded 0  (NOT treated as a negative in the primary analysis)
    indeterminate  only indeterminate reads;  unread  no read on a positive side
  primary:   positive = definite + probable, negative = non_cSS
  secondary: positive = definite only;  sensitivity: + disputed as positive; + unread_zero as negative
STATISTICS: patient-cluster bootstrap (2,000 resamples of patients) for every CI; candidates of one patient are never treated
as independent. All thresholds are the ones fixed in structural_detection/fusion.py BEFORE this run (pre-registered);
held-out studies are only scored, never used to choose anything."""
import sys, os, glob, json, re, numpy as np, pandas as pd

A = sys.argv[1:]
if not A: sys.exit(__doc__)
RUN = A[0]
arg = lambda k, d=None: A[A.index(k) + 1] if k in A else d
DEV = arg("--dev", "").split(); HELD = arg("--heldout", "").split(); SCR = arg("--scripts")
B = os.environ.get("CSS_BASE", os.path.expanduser("~/css_project"))
sys.path.insert(0, SCR); sys.path.insert(0, os.path.join(B, "experimental"))
from css_common import match_calls, norm_call                       # production helpers, read-only
from structural_detection import fusion as FU
import css_model as CM
OUT = os.path.join(RUN, "report"); FIG = os.path.join(OUT, "figures"); os.makedirs(FIG, exist_ok=True)
RNG_SEED, NB = 20261118, 2000
NONCSS = {"Vessel", "Normal", "Artifact", "Microbleed"}
LOG = open(os.path.join(OUT, "analysis_log.txt"), "w")
def log(*s):
    t = " ".join(str(x) for x in s); print(t); LOG.write(t + "\n")

# ------------------------------------------------------------------ objects + production features
def read_cfg(cfg, sid):
    p = os.path.join(RUN, "configs", cfg, sid, "features.csv")
    return pd.read_csv(p) if os.path.exists(p) else None

PROD_COLS = ["hemi", "region", "volume_mm3", "extent_mm", "darkness_z", "score_v4", "score", "css_evidence", "vein_evidence", "tube_ratio",
             "skull_frac", "skullbase_frac", "midline_frac", "rel_height", "pial_dist_mm", "sulcal_depth_mm", "vox_i", "vox_j", "vox_k"]
objs = []
for sid in DEV + HELD:
    c = pd.read_csv(f"{B}/review/{sid}_candidates.csv"); e = pd.read_csv(f"{B}/review/{sid}_excluded.csv")
    c = c.assign(fate="shown", obj_id=c.cand_id, excl_reason=""); e = e.assign(fate="excluded", obj_id=e.excl_id, excl_reason=e.get("reason", ""))
    for df in (c, e):
        keep = [x for x in PROD_COLS if x in df.columns]
        d = df[["fate", "obj_id", "excl_reason"] + keep].copy(); d.insert(0, "study_id", sid); d.insert(1, "cohort", "dev" if sid in DEV else "heldout")
        objs.append(d)
O = pd.concat(objs, ignore_index=True)
O["source"] = np.where(O.fate == "shown", "candidate", "excluded")
import warnings; warnings.simplefilter("ignore", pd.errors.PerformanceWarning)
for cfg in ("A", "B", "C", "E", "F", "ALL"):
    parts = [read_cfg(cfg, s) for s in DEV + HELD]; parts = [p for p in parts if p is not None]
    if not parts: log(f"config {cfg}: no features found"); continue
    F_ = pd.concat(parts, ignore_index=True).drop(columns=["vol_mm3"], errors="ignore")
    F_ = F_.rename(columns={c_: f"{cfg}__{c_}" for c_ in F_.columns if c_ not in ("study_id", "source", "obj_id")})
    O = O.merge(F_, on=["study_id", "source", "obj_id"], how="left")
# reproducibility check: a module's columns must be identical whether it ran alone or with all modules
rep = []
for cfg in ("A", "B", "C", "E", "F"):
    for col in [c_ for c_ in O.columns if c_.startswith(cfg + "__")]:
        base_col = col.split("__", 1)[1]; other = "ALL__" + base_col
        if other in O.columns:
            a_, b_ = O[col], O[other]; num = pd.api.types.is_numeric_dtype(a_) and pd.api.types.is_numeric_dtype(b_)
            same = np.isclose(a_.astype(float), b_.astype(float), equal_nan=True).all() if num else (a_.astype(str) == b_.astype(str)).all()
            rep.append(dict(module=cfg, column=base_col, identical_alone_vs_combined=bool(same)))
pd.DataFrame(rep).to_csv(os.path.join(OUT, "reproducibility_alone_vs_combined.csv"), index=False)
log(f"objects: {len(O)} ({(O.fate == 'shown').sum()} shown, {(O.fate == 'excluded').sum()} excluded) in {O.study_id.nunique()} studies; "
    f"module columns identical alone vs combined: {sum(r['identical_alone_vs_combined'] for r in rep)}/{len(rep)}")

# ------------------------------------------------------------------ reads
def klass(call):
    c = norm_call(str(call).strip()) if isinstance(call, str) else ""
    return "cSS" if c == "cSS" else "non" if c in NONCSS else "indet" if c else ""
reads = []                           # study, fate, obj_id, reader, call, class, inherited
for sid in DEV + HELD:
    cand = pd.read_csv(f"{B}/review/{sid}_candidates.csv")
    files = sorted(glob.glob(f"{B}/review/{sid}_calls_*.csv")) or ([f"{B}/review/{sid}_calls.csv"] if os.path.exists(f"{B}/review/{sid}_calls.csv") else [])
    for f in files:
        rd = re.sub(rf"^{sid}_calls_?", "", os.path.basename(f)[:-4]) or "shared"
        calls = pd.read_csv(f)
        m, ndrop = match_calls(cand, calls)
        if m is None: log(f"{sid} {rd}: calls file has no fingerprint columns - not used"); continue
        if ndrop: log(f"{sid} {rd}: {ndrop} calls do not match the current list (re-detected objects) - not used")
        inh = {}
        if "comment" in calls.columns:
            mm, _ = match_calls(cand, calls.assign(call=calls.comment.fillna("").str.contains(r"\[inherited").map({True: "1", False: ""})))
            inh = {k: v == "1" for k, v in (mm or {}).items()}
        for k, v in m.items():
            if isinstance(v, str) and v.strip():
                reads.append(dict(study_id=sid, fate="shown", obj_id=int(k), reader=rd, call=norm_call(v.strip()), cls=klass(v), inherited=bool(inh.get(k, False))))
    for f in sorted(glob.glob(f"{B}/review/{sid}_excluded_audit_*.csv")):
        rd = re.sub(rf"^{sid}_excluded_audit_", "", os.path.basename(f)[:-4]); a = pd.read_csv(f)
        for _, r in a.iterrows():
            if isinstance(r.get("call"), str) and r.call.strip():
                reads.append(dict(study_id=sid, fate="excluded", obj_id=int(r.excl_id), reader=rd, call=norm_call(r.call.strip()), cls=klass(r.call), inherited=False))
R = pd.DataFrame(reads, columns=["study_id", "fate", "obj_id", "reader", "call", "cls", "inherited"])
if "--no-inherited" in A: R = R[~R.inherited]
R.to_csv(os.path.join(OUT, "reads_long.csv"), index=False)
log(f"reads: {len(R)} ({R.inherited.sum()} inherited) by readers {sorted(R.reader.unique())}")

g = pd.read_csv(f"{B}/review/radiologist_grades.csv"); g["study_id"] = g.study_id.astype(str)
grade = {(r.study_id, h): float(r[h]) for _, r in g.iterrows() for h in ("R", "L") if pd.notna(r[h])}
adj = pd.read_csv(f"{B}/review/adjudication.csv") if os.path.exists(f"{B}/review/adjudication.csv") else pd.DataFrame(columns=["study_id", "fate", "obj_id", "call"])
adjd = {(r.study_id, r.fate, int(r.obj_id)): norm_call(str(r.call).strip()) for _, r in adj.iterrows()}

def consensus(row, rr):
    gr = grade.get((row.study_id, row.hemi), np.nan)
    a = adjd.get((row.study_id, row.fate, int(row.obj_id)))
    ncss, nnon, nind = (rr.cls == "cSS").sum(), (rr.cls == "non").sum(), (rr.cls == "indet").sum()
    if a is not None:
        return ("definite_cSS" if gr != 0 else "conflict_zero") if a == "cSS" else "non_cSS"
    if gr == 0:
        return "conflict_zero" if ncss else ("non_cSS" if nnon + nind else "unread_zero")
    if ncss >= 2 and nnon == 0 and nind == 0: return "definite_cSS"
    if ncss >= 1 and nnon == 0: return "probable_cSS"
    if ncss >= 1 and nnon >= 1: return "disputed"
    if nnon >= 1: return "non_cSS"
    if nind >= 1: return "indeterminate"
    return "unread"
Rg = {k: v for k, v in R.groupby(["study_id", "fate", "obj_id"])}
emp = R.iloc[:0]
O["side_grade"] = [grade.get((s, h), np.nan) for s, h in zip(O.study_id, O.hemi)]
O["label"] = [consensus(r, Rg.get((r.study_id, r.fate, int(r.obj_id)), emp)) for r in O.itertuples()]
O["n_reads"] = [len(Rg.get((r.study_id, r.fate, int(r.obj_id)), emp)) for r in O.itertuples()]
O["reads"] = [" | ".join(f"{x.reader}:{x.call}{'*' if x.inherited else ''}" for x in Rg.get((r.study_id, r.fate, int(r.obj_id)), emp).itertuples()) for r in O.itertuples()]
O["reader_calls_set"] = [",".join(sorted(set(Rg.get((r.study_id, r.fate, int(r.obj_id)), emp).call))) for r in O.itertuples()]
log("label counts by cohort:\n" + pd.crosstab(O.label, O.cohort).to_string())

# ------------------------------------------------------------------ inter-reader agreement (separate from labels)
def kappa(a, b):
    a, b = np.asarray(a), np.asarray(b); po = (a == b).mean(); pe = sum((a == k).mean() * (b == k).mean() for k in set(a) | set(b))
    return (po - pe) / (1 - pe) if pe < 1 else np.nan
ir = []
Rb = R[R.cls.isin(["cSS", "non"])]
W = Rb.pivot_table(index=["study_id", "fate", "obj_id"], columns="reader", values="cls", aggfunc="first")
rng = np.random.default_rng(RNG_SEED)
for i, r1 in enumerate(W.columns):
    for r2 in W.columns[i + 1:]:
        d = W[[r1, r2]].dropna()
        if len(d) < 5: continue
        st = d.index.get_level_values(0).to_numpy(); u = np.unique(st); ks = []
        for _ in range(NB):
            idx = np.concatenate([np.nonzero(st == q)[0] for q in rng.choice(u, len(u))]); x = d.iloc[idx]
            ks.append(kappa(x[r1], x[r2]))
        ir.append(dict(reader_1=r1, reader_2=r2, n_objects=len(d), patients=len(u), agreement=round(float((d[r1] == d[r2]).mean()), 3),
                       kappa_cSS_vs_not=round(kappa(d[r1], d[r2]), 3), ci_low=round(float(np.nanpercentile(ks, 2.5)), 3), ci_high=round(float(np.nanpercentile(ks, 97.5)), 3),
                       both_cSS=int(((d[r1] == "cSS") & (d[r2] == "cSS")).sum()), disagree=int((d[r1] != d[r2]).sum())))
pd.DataFrame(ir).to_csv(os.path.join(OUT, "INTER_READER_AGREEMENT.csv"), index=False)

# ------------------------------------------------------------------ methods (all pre-specified; higher score = more cSS-like)
def col(name): return O[name] if name in O.columns else pd.Series(np.nan, index=O.index)
ev = col("css_evidence") / (col("css_evidence") + col("vein_evidence"))
SCORES = {"PROD_score_v4": col("score_v4"), "PROD_meter": ev, "PROD_tube_ratio(-)": -col("tube_ratio"),
          "A_tube_prod(-)": -col("A__tube_ratio_prod_med"), "A_tube_signed(-)": -col("A__tube_ratio_signed_med"),
          "A_saddle_frac(-)": -col("A__hf_saddle_frac"), "A_plate_minus_tube": col("A__hf_plate_minus_tube"),
          "B_subpial_frac": col("B__sc_subpial_frac"), "B_depth(-)": -col("B__sc_depth_med"),
          "C_continuation(-)": -col("C__vg_ext_length_mm"), "E_contrast(-)": -col("E__sr_contrast_z"), "E_shared_dark(-)": -col("E__sr_ref_dark_frac")}
ORD = {"css_supporting": 3, "indeterminate": 2, "mixed": 2, "not_evaluable": 2, "normal_dark_cortex": 1, "microbleed_like": 1, "vessel_supporting": 0}
SCORES["FUSION_ordinal"] = col("ALL__fusion_category").map(ORD)

def sig_from(prefix):
    rows = []
    for _, r in O.iterrows():
        d = {k.split("__", 1)[1]: r[k] for k in O.columns if k.startswith(prefix + "__")}
        rows.append(FU.signals(d))
    return pd.DataFrame(rows, index=O.index)
S_A, S_B, S_C, S_E = sig_from("A"), sig_from("B"), sig_from("C"), sig_from("E")
shown = O.fate == "shown"
cat = col("ALL__fusion_category")
DECIDE = {"PROD_shown": shown,
          "A_plate": S_A.plate == True, "B_surface": S_B.surface == True, "C_no_continuation": S_C.continues == False,
          "E_focal": S_E.focal == True, "FUSION_css_supporting": cat == "css_supporting",
          "FUSION_not_mimic": ~cat.isin(["vessel_supporting", "microbleed_like", "normal_dark_cortex"]),
          "PROD_shown_AND_A_plate": shown & (S_A.plate == True), "PROD_shown_AND_B_surface": shown & (S_B.surface == True),
          "PROD_shown_AND_C_no_continuation": shown & (S_C.continues == False), "PROD_shown_AND_E_focal": shown & (S_E.focal == True),
          "PROD_shown_AND_FUSION_not_mimic": shown & ~cat.isin(["vessel_supporting", "microbleed_like", "normal_dark_cortex"]),
          "PROD_shown_AND_FUSION_css": shown & (cat == "css_supporting")}
# fusion ablations: drop one module's inputs and re-categorise (same thresholds)
MODCOLS = {"A": ["hf_plate_minus_tube", "tube_ratio_signed_med", "hf_blob_frac"], "B": ["sc_subpial_frac", "sc_csf_frac", "sc_depth_med"],
           "C": ["vg_evidence"], "E": ["sr_contrast_z", "sr_ref_dark_frac", "sr_ref_valid"], "F": ["dec_mixed_object"]}
abl = {}
for m, cols_ in MODCOLS.items():
    cats = []
    for _, r in O.iterrows():
        d = {k.split("__", 1)[1]: r[k] for k in O.columns if k.startswith("ALL__")}
        for c_ in cols_: d[c_] = None
        cats.append(FU.categorise(d)[0] if d else np.nan)
    abl[m] = pd.Series(cats, index=O.index)
    DECIDE[f"FUSION_without_{m}_css"] = abl[m] == "css_supporting"
    DECIDE[f"PROD_shown_AND_FUSION_without_{m}_not_mimic"] = shown & ~abl[m].isin(["vessel_supporting", "microbleed_like", "normal_dark_cortex"])

# ------------------------------------------------------------------ metrics with patient-cluster bootstrap
def auc(y, s):
    y = np.asarray(y); s = np.asarray(s, float); k = np.isfinite(s); y, s = y[k], s[k]; p, n = s[y == 1], s[y == 0]
    if not len(p) or not len(n): return np.nan
    return float(((p[:, None] > n[None]).sum() + 0.5 * (p[:, None] == n[None]).sum()) / (len(p) * len(n)))
def ap(y, s):            # average precision (step-wise PR AUC); ties broken pessimistically
    y = np.asarray(y); s = np.asarray(s, float); k = np.isfinite(s); y, s = y[k], s[k]
    if y.sum() == 0: return np.nan
    o = np.lexsort((y, -s)); y = y[o]; tp = np.cumsum(y); prec = tp / np.arange(1, len(y) + 1)
    return float((prec * y).sum() / y.sum())
def binm(y, d):
    y = np.asarray(y).astype(int); d = np.asarray(d).astype(bool)
    tp, fp, fn, tn = (d & (y == 1)).sum(), (d & (y == 0)).sum(), (~d & (y == 1)).sum(), (~d & (y == 0)).sum()
    f = lambda a, b: a / b if b else np.nan
    se, sp, ppv, npv = f(tp, tp + fn), f(tn, tn + fp), f(tp, tp + fp), f(tn, tn + fn)
    return dict(tp=int(tp), fp=int(fp), fn=int(fn), tn=int(tn), sensitivity=se, specificity=sp, ppv=ppv, npv=npv,
                f1=f(2 * tp, 2 * tp + fp + fn))
class _V(dict):
    __getattr__ = dict.__getitem__
def boot(df, fn, keys):
    """patient-cluster bootstrap on numpy arrays (only the columns the statistic uses)"""
    use = [c_ for c_ in df.columns if c_ in ("y", "s", "d", "base") or str(c_).startswith("oof_")]
    arrs = {c_: df[c_].to_numpy() for c_ in use}
    st = df.study_id.to_numpy(); u = np.unique(st); rng = np.random.default_rng(RNG_SEED); res = {k: [] for k in keys}
    pos = {q: np.nonzero(st == q)[0] for q in u}
    for _ in range(NB):
        idx = np.concatenate([pos[q] for q in rng.choice(u, len(u))]); r = fn(_V({c_: a[idx] for c_, a in arrs.items()}))
        for k in keys: res[k].append(r.get(k, np.nan))
    out = {}
    for k, v in res.items():
        v = np.asarray(v, float)
        out[k] = (np.nanpercentile(v, 2.5), np.nanpercentile(v, 97.5)) if np.isfinite(v).any() else (np.nan, np.nan)
    return out

LABELSETS = {"primary_definite+probable_vs_non": (["definite_cSS", "probable_cSS"], ["non_cSS"]),
             "secondary_definite_vs_non": (["definite_cSS"], ["non_cSS"]),
             "sensitivity_incl_disputed": (["definite_cSS", "probable_cSS", "disputed"], ["non_cSS"]),
             "sensitivity_unread_zero_as_neg": (["definite_cSS", "probable_cSS"], ["non_cSS", "unread_zero"])}
perf = []
for coh in ("dev", "heldout"):
    for ls, (pos, neg) in LABELSETS.items():
        D = O[(O.cohort == coh) & O.label.isin(pos + neg)].copy(); D["y"] = D.label.isin(pos).astype(int)
        if D.y.sum() == 0 or (1 - D.y).sum() == 0 or D.empty: continue
        nscan = D.study_id.nunique()
        for nm, s in SCORES.items():
            D["s"] = s.loc[D.index]
            if D.s.notna().sum() == 0: continue
            fnc = lambda x: dict(auc=auc(x.y, x.s), pr_auc=ap(x.y, x.s))
            pt = fnc(D); ci = boot(D, fnc, ["auc", "pr_auc"])
            perf.append(dict(cohort=coh, label_set=ls, method=nm, kind="continuous", n_pos=int(D.y.sum()), n_neg=int((1 - D.y).sum()), patients=nscan,
                             missing=int(D.s.isna().sum()), prevalence=round(D.y.mean(), 3), auc=pt["auc"], auc_ci_low=ci["auc"][0], auc_ci_high=ci["auc"][1],
                             pr_auc=pt["pr_auc"], pr_auc_ci_low=ci["pr_auc"][0], pr_auc_ci_high=ci["pr_auc"][1]))
        for nm, dec in DECIDE.items():
            D["d"] = dec.loc[D.index].fillna(False).astype(bool)
            fnc = lambda x: binm(x.y, x.d)
            pt = fnc(D); ci = boot(D, fnc, ["sensitivity", "specificity", "ppv", "npv", "f1"])
            row = dict(cohort=coh, label_set=ls, method=nm, kind="binary", n_pos=int(D.y.sum()), n_neg=int((1 - D.y).sum()), patients=nscan,
                       prevalence=round(D.y.mean(), 3), fp_per_scan=pt["fp"] / nscan, fn_per_scan=pt["fn"] / nscan, **pt)
            for k in ("sensitivity", "specificity", "ppv", "npv", "f1"): row[f"{k}_ci_low"], row[f"{k}_ci_high"] = ci[k]
            perf.append(row)
P = pd.DataFrame(perf)
num = P.select_dtypes("number").columns; P[num] = P[num].round(4)
P.to_csv(os.path.join(OUT, "MODULE_PERFORMANCE_COMPARISON.csv"), index=False)

# paired difference vs production score (same objects) and LOPO incremental value (pre-specified feature sets, L2 = 1)
inc = []
for coh in ("dev", "heldout"):
    pos, neg = LABELSETS["primary_definite+probable_vs_non"]
    D = O[(O.cohort == coh) & O.label.isin(pos + neg)].copy(); D["y"] = D.label.isin(pos).astype(int)
    if D.empty or D.y.nunique() < 2: continue
    D["base"] = SCORES["PROD_score_v4"].loc[D.index]
    for nm, s in SCORES.items():
        if nm == "PROD_score_v4": continue
        D["s"] = s.loc[D.index]; k = D.s.notna() & D.base.notna(); X = D[k]
        if X.empty or X.y.nunique() < 2: continue
        fnc = lambda x: dict(d=auc(x.y, x.s) - auc(x.y, x.base)); ci = boot(X, fnc, ["d"])
        inc.append(dict(cohort=coh, comparison=f"{nm} vs PROD_score_v4 (paired AUC difference)", n=len(X), delta_auc=round(fnc(X)["d"], 4),
                        ci_low=round(ci["d"][0], 4), ci_high=round(ci["d"][1], 4)))
FSETS = {"PROD": ["score_v4"], "PROD+A": ["score_v4", "A__tube_ratio_signed_med", "A__hf_saddle_frac", "A__hf_plate_minus_tube"],
         "PROD+B": ["score_v4", "B__sc_subpial_frac", "B__sc_depth_med"], "PROD+C": ["score_v4", "C__vg_ext_length_mm"],
         "PROD+E": ["score_v4", "E__sr_contrast_z", "E__sr_ref_dark_frac"],
         "PROD+A+B+C+E": ["score_v4", "A__tube_ratio_signed_med", "A__hf_saddle_frac", "A__hf_plate_minus_tube", "B__sc_subpial_frac",
                          "B__sc_depth_med", "C__vg_ext_length_mm", "E__sr_contrast_z", "E__sr_ref_dark_frac"]}
pos, neg = LABELSETS["primary_definite+probable_vs_non"]
D = O[(O.cohort == "dev") & O.label.isin(pos + neg)].copy(); D["y"] = D.label.isin(pos).astype(int)
lopo = {}
if D.study_id.nunique() >= 3 and D.y.nunique() == 2:
    for nm, fs in FSETS.items():
        fs = [f for f in fs if f in D.columns]
        X = D[fs].apply(pd.to_numeric, errors="coerce").to_numpy(float)
        oof, _ = CM.lopo(X, D.y.to_numpy(int), D.study_id.to_numpy(), l2=1.0, nested=False); D[f"oof_{nm}"] = oof; lopo[nm] = oof
        k = np.isfinite(oof)
        inc.append(dict(cohort="dev", comparison=f"LOPO logistic {nm}", n=int(k.sum()), delta_auc=round(auc(D.y[k], oof[k]), 4), ci_low=np.nan, ci_high=np.nan,
                        note="value = pooled leave-one-patient-out AUC (not a difference)"))
    for nm in FSETS:
        if nm == "PROD" or f"oof_{nm}" not in D: continue
        k = D[f"oof_{nm}"].notna() & D["oof_PROD"].notna(); X = D[k].copy()
        fnc = lambda x: dict(d=auc(x.y, x[f"oof_{nm}"]) - auc(x.y, x["oof_PROD"])); ci = boot(X, fnc, ["d"])
        inc.append(dict(cohort="dev", comparison=f"LOPO {nm} minus LOPO PROD", n=len(X), delta_auc=round(fnc(X)["d"], 4), ci_low=round(ci["d"][0], 4), ci_high=round(ci["d"][1], 4)))
INC = pd.DataFrame(inc); INC.to_csv(os.path.join(OUT, "incremental_value.csv"), index=False)

# ------------------------------------------------------------------ patient level (reference = radiologist side grade > 0)
pl = []
for (sid, coh), sub in O.groupby(["study_id", "cohort"]):
    for h in ("R", "L"):
        gr = grade.get((sid, h), np.nan); s_ = sub[sub.hemi == h]
        r = dict(study_id=sid, cohort=coh, hemi=h, radiologist_grade=gr, reference_positive=bool(gr > 0) if np.isfinite(gr) else np.nan,
                 n_objects=len(s_), n_shown=int((s_.fate == "shown").sum()), n_reader_cSS_objects=int(s_.label.isin(["definite_cSS", "probable_cSS"]).sum()))
        for nm, dec in DECIDE.items():
            if nm.startswith("FUSION_without"): continue
            r[f"n_{nm}"] = int(dec.loc[s_.index].fillna(False).sum())
        pl.append(r)
PL = pd.DataFrame(pl)
miss_rows = []
for sid in DEV + HELD:
    p = f"{B}/review/{sid}_missed.csv"
    if os.path.exists(p):
        mm = pd.read_csv(p); mm["study_id"] = sid; miss_rows.append(mm)
MISS = pd.concat(miss_rows, ignore_index=True) if miss_rows else pd.DataFrame()
PL["n_missed_marks"] = [int(((MISS.study_id == r.study_id)).sum()) if len(MISS) else 0 for r in PL.itertuples()]
PL.to_csv(os.path.join(OUT, "PATIENT_LEVEL_PERFORMANCE.csv"), index=False)
plm = []
for coh in ("dev", "heldout"):
    X = PL[(PL.cohort == coh) & PL.reference_positive.notna()].copy()
    if X.empty: continue
    X["y"] = X.reference_positive.astype(int)
    for nm in [k for k in DECIDE if not k.startswith("FUSION_without")]:
        X["d"] = X[f"n_{nm}"] > 0; fnc = lambda x: binm(x.y, x.d); pt = fnc(X); ci = boot(X, fnc, ["sensitivity", "specificity"])
        plm.append(dict(cohort=coh, method=nm, unit="hemisphere", n_pos=int(X.y.sum()), n_neg=int((1 - X.y).sum()), patients=X.study_id.nunique(), **pt,
                        sens_ci=f"{ci['sensitivity'][0]:.2f}-{ci['sensitivity'][1]:.2f}", spec_ci=f"{ci['specificity'][0]:.2f}-{ci['specificity'][1]:.2f}"))
PLM = pd.DataFrame(plm); PLM.to_csv(os.path.join(OUT, "patient_level_summary.csv"), index=False)

# ------------------------------------------------------------------ module D: multi-view seeds vs production + reader missed marks
dr = []
for sid in DEV + HELD:
    p = os.path.join(RUN, "configs", "D", sid, "seeds.csv")
    if not os.path.exists(p): continue
    sd = pd.read_csv(p); mm = MISS[MISS.study_id == sid] if len(MISS) else pd.DataFrame()
    new = sd[sd.status == "new"]
    hit = 0
    if len(mm) and len(new):
        for _, m in mm.iterrows():
            dd = np.sqrt((new.vox_i - m.vox_i) ** 2 + (new.vox_j - m.vox_j) ** 2 + (new.vox_k - m.vox_k) ** 2)
            hit += int((dd <= 6).any())            # within 6 voxels of the reader's mark centre
    dr.append(dict(study_id=sid, cohort="dev" if sid in DEV else "heldout", seeds=len(sd), new_seeds=len(new), new_not_axial=int((~new.axial_seen.astype(bool)).sum()),
                   reader_missed_marks=len(mm), missed_marks_near_a_new_seed=hit))
DR = pd.DataFrame(dr); DR.to_csv(os.path.join(OUT, "module_D_multiview_seeds.csv"), index=False)

# ------------------------------------------------------------------ module F: splitting
fr = O[["study_id", "cohort", "fate", "obj_id", "label", "volume_mm3"] + [c_ for c_ in O.columns if c_.startswith("F__dec_")]].copy()
fr.to_csv(os.path.join(OUT, "module_F_splitting.csv"), index=False)

# ------------------------------------------------------------------ error atlas (category rules are position/feature bins, NOT annotations)
def fp_cat(r):
    call = r.reader_calls_set
    if (r.get("skullbase_frac", 0) or 0) >= 0.3 or (np.isfinite(r.get("rel_height", np.nan)) and r.rel_height < 0.2): return "4 skull-base artifact"
    if (r.get("midline_frac", 0) or 0) >= 0.3: return "5 dural structure (midline)"
    if "Microbleed" in call or (r.get("ALL__hf_blob_frac", 0) or 0) >= 0.3: return "6 hemosiderin mimic (microbleed-like)"
    if "Artifact" in call: return "7 susceptibility artifact"
    if "Vessel" in call:
        dep = r.get("ALL__sc_depth_med", np.nan)
        if not np.isfinite(dep): return "8 other (vessel, depth unknown)"
        return "2 sulcal vessel (in CSF > +0.5 mm)" if dep > 0.5 else "3 pial vessel (-0.5..+0.5 mm)" if dep >= -0.5 else "1 cortical vein (within cortex)"
    return "8 other (" + (call or "unread") + ")"
def fn_cat(r):
    if r.get("ALL__dec_mixed_object") is True or r.get("ALL__vg_evidence") == "vascular_continuation": return "6 merged with / touching a vessel"
    if (r.get("volume_mm3", 0) or 0) >= 1000: return "3 extensive confluent"
    if np.isfinite(r.get("sulcal_depth_mm", np.nan)) and r.sulcal_depth_mm >= 10: return "4 deep sulcal"
    if (np.isfinite(r.get("ALL__sc_normal_thickness_mm", np.nan)) and r["ALL__sc_normal_thickness_mm"] <= 1.5) or (r.get("volume_mm3", 99) or 99) < 50: return "1 thin"
    if (np.isfinite(r.get("extent_mm", np.nan)) and r.extent_mm < 10) or (r.get("ALL__dec_n_components", 0) or 0) >= 3: return "2 short / discontinuous"
    if np.isfinite(r.get("darkness_z", np.nan)) and abs(r.darkness_z) < 3: return "5 low-signal / subtle"
    return "7 other"
pos, neg = LABELSETS["primary_definite+probable_vs_non"]
E = O[O.label.isin(pos + neg)].copy(); E["y"] = E.label.isin(pos).astype(int)
for nm in ("PROD_shown", "FUSION_css_supporting", "PROD_shown_AND_FUSION_not_mimic", "PROD_shown_AND_A_plate", "PROD_shown_AND_C_no_continuation", "PROD_shown_AND_E_focal"):
    d = DECIDE[nm].loc[E.index].fillna(False).astype(bool)
    E[f"err_{nm}"] = np.where(d & (E.y == 1), "TP", np.where(d & (E.y == 0), "FP", np.where(~d & (E.y == 1), "FN", "TN")))
E["fp_category"] = [fp_cat(r) if r.y == 0 else "" for _, r in E.iterrows()]
E["fn_category"] = [fn_cat(r) if r.y == 1 else "" for _, r in E.iterrows()]
E["category_source"] = "rule on reader call + recorded features (see report); not an annotation"
E["fusion_signals"] = col("ALL__fusion_signals").loc[E.index]
keepc = ["study_id", "cohort", "fate", "obj_id", "hemi", "region", "label", "reads", "side_grade", "volume_mm3", "extent_mm", "darkness_z", "score_v4", "tube_ratio",
         "ALL__tube_ratio_signed_med", "ALL__hf_saddle_frac", "ALL__hf_plate_minus_tube", "ALL__sc_depth_med", "ALL__sc_subpial_frac", "ALL__vg_ext_length_mm",
         "ALL__sr_contrast_z", "ALL__sr_ref_dark_frac", "ALL__dec_mixed_object", "ALL__fusion_category", "fusion_signals", "excl_reason"]
keepc = [c_ for c_ in keepc if c_ in E.columns] + [c_ for c_ in E.columns if c_.startswith("err_")] + ["fp_category", "fn_category", "category_source"]
E[keepc].to_csv(os.path.join(OUT, "OBJECT_LEVEL_ERROR_ANALYSIS.csv"), index=False)
if len(MISS):
    MISS[["study_id", "missed_id", "reviewer", "vox_i", "vox_j", "vox_k", "detector_fate"]].to_csv(os.path.join(OUT, "reader_missed_marks.csv"), index=False)
# cases for images: FP / FN of the fusion filter on shown candidates (render_cases.py handles candidates only)
ex = E[(E.fate == "shown") & E[["err_PROD_shown_AND_FUSION_not_mimic"]].isin(["FP", "FN"]).any(axis=1)].copy()
ex["case"] = ex["err_PROD_shown_AND_FUSION_not_mimic"] + " " + np.where(ex.y == 1, ex.fn_category, ex.fp_category)
ex = ex.merge(O[["study_id", "fate", "obj_id"] + [c_ for c_ in ("vox_i", "vox_j", "vox_k") if c_ in O.columns]], on=["study_id", "fate", "obj_id"], how="left")
for c_ in ("vox_i", "vox_j", "vox_k"):
    if c_ not in ex: ex[c_] = np.nan
ex.rename(columns={"obj_id": "object_id"})[["case", "study_id", "object_id", "volume_mm3", "vox_i", "vox_j", "vox_k"]].head(40).to_csv(os.path.join(OUT, "error_cases_for_rendering.csv"), index=False)
O.to_csv(os.path.join(OUT, "all_objects_full_table.csv"), index=False)

# ------------------------------------------------------------------ figures (from the tables above only)
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
PAL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
plt.rcParams.update({"font.size": 8, "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": "#e6e5e1",
                     "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb"})
def roc_pts(y, s):
    k = np.isfinite(s); y, s = np.asarray(y)[k], np.asarray(s)[k]; th = np.unique(s)[::-1]
    P_, N_ = (y == 1).sum(), (y == 0).sum(); xs, ys = [0], [0]
    for t in th: d = s >= t; xs.append(((d) & (y == 0)).sum() / N_); ys.append(((d) & (y == 1)).sum() / P_)
    return xs, ys
def pr_pts(y, s):
    k = np.isfinite(s); y, s = np.asarray(y)[k], np.asarray(s)[k]; o = np.argsort(-s); y = y[o]; tp = np.cumsum(y)
    return tp / max(y.sum(), 1), tp / np.arange(1, len(y) + 1)
SHOW = ["PROD_score_v4", "PROD_tube_ratio(-)", "A_tube_signed(-)", "A_saddle_frac(-)", "B_subpial_frac", "C_continuation(-)", "E_contrast(-)", "FUSION_ordinal"]
for coh in ("dev", "heldout"):
    D = O[(O.cohort == coh) & O.label.isin(pos + neg)].copy(); D["y"] = D.label.isin(pos).astype(int)
    if D.empty or D.y.nunique() < 2: continue
    fig, ax = plt.subplots(1, 2, figsize=(9, 4))
    for i, nm in enumerate(SHOW):
        s = SCORES[nm].loc[D.index].to_numpy(float)
        if not np.isfinite(s).any(): continue
        x, y = roc_pts(D.y.to_numpy(), s); ax[0].plot(x, y, color=PAL[i], lw=1.5, label=f"{nm} {auc(D.y, s):.2f}")
        r_, p_ = pr_pts(D.y.to_numpy(), s); ax[1].plot(r_, p_, color=PAL[i], lw=1.5, label=f"{nm} {ap(D.y, s):.2f}")
    ax[0].plot([0, 1], [0, 1], color="#999", lw=0.8, ls="--"); ax[0].set_xlabel("1 - specificity"); ax[0].set_ylabel("sensitivity"); ax[0].legend(frameon=False, fontsize=6)
    ax[1].axhline(D.y.mean(), color="#999", lw=0.8, ls="--"); ax[1].set_xlabel("recall"); ax[1].set_ylabel("precision"); ax[1].legend(frameon=False, fontsize=6)
    fig.suptitle(f"{coh}: definite+probable cSS ({int(D.y.sum())}) vs non-cSS ({int((1 - D.y).sum())}) objects, {D.study_id.nunique()} patients - reader labels", fontsize=8)
    fig.tight_layout(); fig.savefig(os.path.join(FIG, f"roc_pr_{coh}.png"), dpi=180); plt.close(fig)
    Bn = P[(P.cohort == coh) & (P.label_set == "primary_definite+probable_vs_non") & (P.kind == "binary") & ~P.method.str.contains("without")]
    if len(Bn):
        fig, ax = plt.subplots(figsize=(7, 0.32 * len(Bn) + 1)); yy = np.arange(len(Bn))
        ax.errorbar(Bn.sensitivity, yy - 0.15, xerr=[Bn.sensitivity - Bn.sensitivity_ci_low, Bn.sensitivity_ci_high - Bn.sensitivity], fmt="o", color=PAL[0], label="sensitivity", ms=4)
        ax.errorbar(Bn.specificity, yy + 0.15, xerr=[Bn.specificity - Bn.specificity_ci_low, Bn.specificity_ci_high - Bn.specificity], fmt="o", color=PAL[1], label="specificity", ms=4)
        ax.set_yticks(yy); ax.set_yticklabels(Bn.method); ax.set_xlim(0, 1); ax.legend(frameon=False, loc="lower right"); ax.set_title(f"{coh}: object-level, 95 % patient-bootstrap CI", loc="left")
        fig.tight_layout(); fig.savefig(os.path.join(FIG, f"sens_spec_{coh}.png"), dpi=180); plt.close(fig)
if len(INC):
    X = INC[INC.comparison.str.contains("minus LOPO|paired")].copy()
    if len(X):
        fig, ax = plt.subplots(figsize=(7, 0.3 * len(X) + 1)); yy = np.arange(len(X))
        ax.errorbar(X.delta_auc, yy, xerr=[(X.delta_auc - X.ci_low).fillna(0), (X.ci_high - X.delta_auc).fillna(0)], fmt="o", color=PAL[0], ms=4)
        ax.axvline(0, color="#999", lw=0.8); ax.set_yticks(yy); ax.set_yticklabels([f"{c} [{h}]" for c, h in zip(X.comparison, X.cohort)], fontsize=6)
        ax.set_xlabel("AUC difference vs production score_v4 (95 % patient-bootstrap CI)"); fig.tight_layout(); fig.savefig(os.path.join(FIG, "module_contribution.png"), dpi=180); plt.close(fig)
for kind, colm in (("FP", "fp_category"), ("FN", "fn_category")):
    rows_ = []
    for nm in [c_ for c_ in E.columns if c_.startswith("err_")]:
        vc = E[E[nm] == kind][colm].value_counts()
        for k, v in vc.items(): rows_.append(dict(method=nm[4:], category=k, n=v))
    T = pd.DataFrame(rows_)
    if len(T):
        pv = T.pivot_table(index="method", columns="category", values="n", fill_value=0)
        fig, ax = plt.subplots(figsize=(8, 0.35 * len(pv) + 1.4)); left = np.zeros(len(pv))
        for i, c_ in enumerate(pv.columns):
            ax.barh(pv.index, pv[c_], left=left, color=PAL[i % len(PAL)], edgecolor="#fcfcfb", label=c_); left += pv[c_].to_numpy()
        ax.legend(frameon=False, fontsize=6, ncol=2, loc="lower right"); ax.set_xlabel(f"{kind} objects (all cohorts, primary labels)")
        fig.tight_layout(); fig.savefig(os.path.join(FIG, f"{kind.lower()}_distribution.png"), dpi=180); plt.close(fig)

# ------------------------------------------------------------------ pre-registered decision rule per module (applied mechanically)
def get(coh, ls, m, k):
    x = P[(P.cohort == coh) & (P.label_set == ls) & (P.method == m)]
    return float(x[k].iloc[0]) if len(x) and k in x and pd.notna(x[k].iloc[0]) else np.nan
LS = "primary_definite+probable_vs_non"
base_sens_dev, base_spec_dev = get("dev", LS, "PROD_shown", "sensitivity"), get("dev", LS, "PROD_shown", "specificity")
dec_rows = []
for mod, filt, scores in (("A", "PROD_shown_AND_A_plate", ["A_tube_signed(-)", "A_saddle_frac(-)"]), ("B", "PROD_shown_AND_B_surface", ["B_subpial_frac"]),
                          ("C", "PROD_shown_AND_C_no_continuation", ["C_continuation(-)"]), ("E", "PROD_shown_AND_E_focal", ["E_contrast(-)"]),
                          ("FUSION", "PROD_shown_AND_FUSION_not_mimic", ["FUSION_ordinal"])):
    se_d, sp_d = get("dev", LS, filt, "sensitivity"), get("dev", LS, filt, "specificity")
    sp_lo = get("dev", LS, filt, "specificity_ci_low"); fn_d = get("dev", LS, filt, "fn") - get("dev", LS, "PROD_shown", "fn")
    best = max(scores, key=lambda s: get("dev", LS, s, "auc") if np.isfinite(get("dev", LS, s, "auc")) else -1)
    a_d, a_lo, a_h = get("dev", LS, best, "auc"), get("dev", LS, best, "auc_ci_low"), get("heldout", LS, best, "auc")
    d_row = INC[(INC.cohort == "dev") & (INC.comparison == f"LOPO PROD+{mod} minus LOPO PROD")] if mod != "FUSION" else INC.iloc[:0]
    d_lo = float(d_row.ci_low.iloc[0]) if len(d_row) else np.nan
    if (np.isfinite(fn_d) and fn_d > 0) or (np.isfinite(a_lo) and a_lo <= 0.5) or (np.isfinite(a_h) and a_h < 0.5):
        verdict = "SHOULD NOT BE INTEGRATED (as a filter)" if np.isfinite(fn_d) and fn_d > 0 else "SHOULD NOT BE INTEGRATED"
    elif np.isfinite(a_lo) and a_lo > 0.5 and (not np.isfinite(a_h) or a_h > 0.5) and (np.isfinite(d_lo) and d_lo > 0) and sp_d > base_spec_dev:
        verdict = "SAFE TO INTEGRATE (recorded / ranking only)"
    else: verdict = "NEEDS FURTHER VALIDATION"
    dec_rows.append(dict(module=mod, best_score=best, dev_auc=a_d, dev_auc_ci_low=a_lo, heldout_auc=a_h, lopo_delta_ci_low=d_lo,
                         filter=filt, dev_sensitivity=se_d, dev_specificity=sp_d, prod_sensitivity=base_sens_dev, prod_specificity=base_spec_dev,
                         extra_cSS_lost_vs_production=fn_d, verdict=verdict))
DEC = pd.DataFrame(dec_rows); DEC.to_csv(os.path.join(OUT, "preregistered_verdicts.csv"), index=False)

# ------------------------------------------------------------------ text deliverables (numbers only; interpretation follows in review)
def md(df, n=60):
    """markdown table without the optional 'tabulate' package"""
    if df is None or not len(df): return "(none)"
    d = df.head(n); f = lambda v: "" if (isinstance(v, float) and not np.isfinite(v)) else (f"{v:.3g}" if isinstance(v, float) else str(v))
    return "\n".join(["| " + " | ".join(map(str, d.columns)) + " |", "|" + "---|" * len(d.columns)] + ["| " + " | ".join(f(v) for v in r) + " |" for r in d.itertuples(index=False)])
env = open(os.path.join(RUN, "environment.txt")).read() if os.path.exists(os.path.join(RUN, "environment.txt")) else ""
lab_tab = pd.crosstab(O.label, O.cohort).reset_index()
main = P[(P.label_set == LS)][["cohort", "method", "kind", "n_pos", "n_neg", "patients", "auc", "auc_ci_low", "auc_ci_high", "pr_auc", "sensitivity", "specificity",
                                "ppv", "npv", "f1", "fp_per_scan", "fn_per_scan"]]
open(os.path.join(OUT, "REAL_DATA_VALIDATION_REPORT.md"), "w").write(f"""# Real-data validation report (generated from the run; reader labels, not expert lesion labels)

Run folder: `{RUN}`  (generated by analyse_real_validation.py; every number is computed from the files listed in inputs_before.csv)

## Environment
```
{env}```

## Reference labels
No expert lesion-level annotation exists. Object labels are READER consensus levels (definitions in the script header);
patient/hemisphere reference = the radiologist's grade (R/L 0-2). Inherited calls (carried from an earlier list) are included
and marked `*` in `reads`. Readers: {sorted(R.reader.unique())}.

{md(lab_tab)}

Inter-reader agreement (cSS vs not, objects read by both; patient-bootstrap CI): see INTER_READER_AGREEMENT.csv
{md(pd.DataFrame(ir))}

## Object-level performance (primary: definite + probable cSS vs non-cSS; 95 % patient-bootstrap CI in MODULE_PERFORMANCE_COMPARISON.csv)
{md(main.round(3), 120)}

## Incremental value over production (paired AUC differences; LOPO logistic models with pre-specified feature sets)
{md(INC.round(3), 60)}

## Patient level (hemisphere positive if >= 1 object passes the method; reference = radiologist grade > 0)
{md(PLM, 60)}

## Module D (multi-view seeds)
{md(DR)}

## Module F (splitting): objects with plate + tube components by label
{md(pd.crosstab(fr.label, fr.get('F__dec_mixed_object', pd.Series(index=fr.index, dtype=object))).reset_index()) if 'F__dec_mixed_object' in fr else '(no F output)'}

## Reproducibility: module columns identical alone vs combined: {sum(r['identical_alone_vs_combined'] for r in rep)}/{len(rep)}

## Pre-registered verdicts (rule fixed before the run; see RECOMMENDED_NEXT_STEPS.md)
{md(DEC.round(3))}

## Limitations (always true for this cohort)
10 development patients and 4 held-out patients; candidates are clustered within patients (all CIs resample patients, so they are
wide); labels are reader calls, some made with the AI meter visible; the held-out set was examined once before (blind ST read,
feature analysis) - it is held out from tuning but not pristine; objects never generated by production are invisible here except
through reader-drawn missed marks; error categories are rule-based bins, not annotations.
""")
open(os.path.join(OUT, "ABLATION_ANALYSIS.md"), "w").write(f"""# Ablation analysis (generated)

## Fusion with one module's inputs removed (same thresholds), primary labels
{md(P[(P.label_set == LS) & P.method.str.contains('FUSION')][['cohort', 'method', 'sensitivity', 'specificity', 'ppv', 'f1', 'fp_per_scan', 'fn_per_scan']].round(3), 80)}

## Each module as an additional filter on production-shown objects
{md(P[(P.label_set == LS) & P.method.str.startswith('PROD_shown')][['cohort', 'method', 'tp', 'fp', 'fn', 'sensitivity', 'specificity', 'fp_per_scan', 'fn_per_scan']].round(3), 80)}

## LOPO logistic models (production score + module features; L2 = 1, no selection)
{md(INC[INC.comparison.str.contains('LOPO')].round(3))}

Reading guide: a module "improves specificity without sacrificing sensitivity" only if its filter row has the same fn as
PROD_shown and a higher specificity; "redundant" if removing it from fusion changes nothing.
""")
open(os.path.join(OUT, "RECOMMENDED_NEXT_STEPS.md"), "w").write(f"""# Recommended next steps (pre-registered rule, applied mechanically; to be reviewed with the run's numbers)

Rule (fixed before any real data was seen):
- SAFE TO INTEGRATE (recorded / ranking only, never exclusion): dev AUC CI lower bound > 0.5, held-out AUC > 0.5, LOPO
  increment over production with CI lower bound > 0, and as a filter on shown objects no additional cSS lost and higher specificity.
- SHOULD NOT BE INTEGRATED: dev AUC CI includes 0.5, or held-out AUC < 0.5, or the filter loses any definite/probable cSS
  that production shows.
- NEEDS FURTHER VALIDATION: everything else.

{md(DEC.round(3))}

Whatever the verdicts: no production threshold is changed and no candidate is excluded automatically on this evidence.
""")
log(f"report -> {OUT}")
