"""Production performance against the expert reference (run only when expert annotations exist).
usage: python reference_audit/evaluate.py OUT_NAME --packet PACKET [--batches B01,B02] [--radius-mm 3]
Reference = whole-scan lesion clusters (agreement.py): unanimous category, or the adjudicator's category from
whole_scan/<PACKET>/adjudication.csv; clusters that disagree and are not adjudicated are 'unresolved' (reported, not used).
Every reference lesion is traced through production (inventory label map, within --radius-mm of its centre; shown > excluded > dropped):
  retained (shown, with its rank) | excluded (rule mechanism) | dropped (generation gate) | never generated
Excluded-object batches give a design-based (stratified, inverse-inclusion-weighted) estimate of how many rejected objects are cSS.
All intervals: patient-cluster bootstrap (2,000). Writes reference_audit/results/<OUT_NAME>/."""
import sys, os, glob, json, numpy as np, pandas as pd, nibabel as nib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ra_common as R

a = sys.argv[1:]
if not a or a[0].startswith("-"): sys.exit(__doc__)
arg = lambda k, d=None: a[a.index(k) + 1] if k in a else d
NAME, PK = a[0], arg("--packet"); RAD = float(arg("--radius-mm", 3)); NB = 2000; rng = np.random.default_rng(20261119)
out = os.path.join(R.OUT, "results", NAME); os.makedirs(out, exist_ok=True)
POS2 = {"definite_cSS", "probable_cSS"}
def boot_prop(df, num, den, by="study_id"):
    st = df[by].to_numpy(); u = np.unique(st); v = []
    if not len(u): return (np.nan, np.nan)
    pos = {q: np.nonzero(st == q)[0] for q in u}
    for _ in range(NB):
        idx = np.concatenate([pos[q] for q in rng.choice(u, len(u))]); d = df.iloc[idx]
        s = den(d); v.append(num(d) / s if s else np.nan)
    v = np.asarray(v, float); return (np.nanpercentile(v, 2.5), np.nanpercentile(v, 97.5)) if np.isfinite(v).any() else (np.nan, np.nan)

rows_out = {}
# ---------------- whole-scan reference lesions -> production fate
wd = os.path.join(R.OUT, "whole_scan", PK); key = pd.read_csv(f"{wd}/key_CONCEALED.csv").set_index("case_code").study_id.to_dict()
CL = pd.read_csv(f"{wd}/lesion_clusters.csv", dtype=str).fillna("")
for c_ in ("x_mm", "y_mm", "z_mm"): CL[c_] = CL[c_].astype(float)
CL["cluster_id"] = CL.cluster_id.astype(int)
adj = pd.read_csv(f"{wd}/adjudication.csv", dtype=str).fillna("") if os.path.exists(f"{wd}/adjudication.csv") else pd.DataFrame(columns=["cluster_id", "adjudicated_category"])
adjd = {int(r.cluster_id): r.adjudicated_category for r in adj.itertuples() if r.adjudicated_category}
cat_cols = [c for c in CL.columns if c.endswith("_category")]
def ref_cat(r):
    if int(r.cluster_id) in adjd: return adjd[int(r.cluster_id)], "adjudicated"
    vals = {r[c] for c in cat_cols}
    return (vals.pop(), "unanimous") if len(vals) == 1 and "|" not in str(list(vals)[0]) else ("unresolved", "not adjudicated")
CL[["reference_category", "reference_source"]] = [ref_cat(r) for _, r in CL.iterrows()]
CL["study_id"] = CL.patient_id.map(key)
fates = []
for sid, g in CL.groupby("study_id"):
    con = pd.read_csv(f"{R.OUT}/inventory/{sid}_objects_concealed.csv").set_index("label_value")
    img = nib.load(f"{R.OUT}/inventory/{sid}_audit_objects.nii.gz"); Lm = np.asarray(img.dataobj).astype(np.int32); A = np.linalg.inv(img.affine)
    vox = np.array(img.header.get_zooms()[:3], float); r_ = np.ceil(RAD / vox).astype(int)
    oo = np.stack(np.meshgrid(*[np.arange(-k, k + 1) for k in r_], indexing="ij"), -1).reshape(-1, 3); oo = oo[((oo * vox) ** 2).sum(1) <= RAD ** 2]
    for _, r in g.iterrows():
        c = np.round(A @ np.r_[r.x_mm, r.y_mm, r.z_mm, 1])[:3].astype(int); pts = np.clip(c + oo, 0, np.array(Lm.shape) - 1)
        labs = set(Lm[pts[:, 0], pts[:, 1], pts[:, 2]]) - {0}
        best = min(labs, key=lambda v: v // 100000) if labs else None
        if best is None: f = dict(fate="never generated", mechanism="not generated", production_id=np.nan, rank=np.nan)
        else:
            k = con.loc[best]; st = k.stage
            f = dict(fate={"shown": "retained (shown)", "excluded": "generated, excluded by a rule", "dropped": "generated, dropped by a generation gate"}[st],
                     mechanism=k.mechanism, production_id=int(k.production_id), rank=int(k.production_id) if st == "shown" else np.nan,
                     reason=k.reason, matched_labels=len(labs))
        fates.append(dict(cluster_id=r.cluster_id, **f))
CL = CL.merge(pd.DataFrame(fates), on="cluster_id", how="left")
CL.to_csv(f"{out}/reference_lesions_with_production_fate.csv", index=False)
# ---------------- lesion-level sensitivity, per reference definition
res = []
for nm, pos in (("definite only", {"definite_cSS"}), ("definite + probable", POS2)):
    R_ = CL[CL.reference_category.isin(pos)].copy(); R_["hit"] = R_.fate == "retained (shown)"
    if not len(R_): continue
    ci = boot_prop(R_, lambda d: d.hit.sum(), len)
    res.append(dict(measure=f"lesion-level sensitivity ({nm})", value=R_.hit.mean(), ci_low=ci[0], ci_high=ci[1], n=len(R_), patients=R_.study_id.nunique()))
    for f, n in R_.fate.value_counts().items(): res.append(dict(measure=f"  fate of reference lesions ({nm}): {f}", value=n / len(R_), n=n))
    res.append(dict(measure=f"false negatives per scan ({nm})", value=(~R_.hit).sum() / CL.study_id.nunique(), n=int((~R_.hit).sum())))
    for by in ("mechanism",):
        for k, gg in R_.groupby(by): res.append(dict(measure=f"  missed by {by}: {k} ({nm})", value=(~gg.hit).sum(), n=len(gg)))
# strata from reader fields (majority value across readers' marks is in the annotation files; joined here)
marks = pd.concat([pd.read_csv(f, dtype=str).assign(reader=os.path.basename(f)[len("lesion_annotations_"):-4]) for f in glob.glob(f"{wd}/lesion_annotations_*.csv")], ignore_index=True).fillna("")
first = {}
for _, r in CL.iterrows():
    ids = []
    for c in [c for c in CL.columns if c.endswith("_lesion_ids")]:
        rd = c[:-len("_lesion_ids")]
        for lid in str(r[c]).split("|"):
            if lid and lid != "nan": ids.append((rd, lid))
    m = marks[[(x.reader, x.lesion_id) in ids and x.patient_id == r.patient_id for x in marks.itertuples()]]
    first[r.cluster_id] = dict(length_mm=pd.to_numeric(m.length_mm, errors="coerce").median(), morphology=m.morphology.mode().iat[0] if len(m) else "",
                               lobe=m.lobe.mode().iat[0] if len(m) else "", hemisphere=m.hemisphere.mode().iat[0] if len(m) else "", confidence=pd.to_numeric(m.confidence_1to5, errors="coerce").median())
F = CL.merge(pd.DataFrame.from_dict(first, orient="index").rename_axis("cluster_id").reset_index(), on="cluster_id")
F["length_bin"] = pd.cut(F.length_mm, [0, 5, 10, 20, 40, 1e9], labels=["<5", "5-10", "10-20", "20-40", ">=40"]).astype(str)
F["confidence_bin"] = pd.cut(F.confidence, [0, 2.5, 3.5, 5.1], labels=["low 1-2", "mid 3", "high 4-5"]).astype(str)
strat = []
P2 = F[F.reference_category.isin(POS2)].copy(); P2["hit"] = P2.fate == "retained (shown)"
for by in ("length_bin", "morphology", "lobe", "confidence_bin", "reference_category"):
    for k, gg in P2.groupby(by):
        ci = boot_prop(gg, lambda d: d.hit.sum(), len)
        strat.append(dict(stratum=by, value=k, n_lesions=len(gg), patients=gg.study_id.nunique(), sensitivity=gg.hit.mean(), ci_low=ci[0], ci_high=ci[1]))
pd.DataFrame(strat).to_csv(f"{out}/sensitivity_by_stratum.csv", index=False)
# ---------------- shown objects: PPV / FP per scan (a shown object matching no reference cSS lesion = FP)
sh_rows = []
for sid in CL.study_id.dropna().unique():
    con = pd.read_csv(f"{R.OUT}/inventory/{sid}_objects_concealed.csv"); sh = con[con.stage == "shown"]
    hit_ids = set(CL[(CL.study_id == sid) & CL.reference_category.isin(POS2) & (CL.fate == "retained (shown)")].production_id.dropna().astype(int))
    for r in sh.itertuples(): sh_rows.append(dict(study_id=sid, production_id=r.production_id, is_css=r.production_id in hit_ids))
SH = pd.DataFrame(sh_rows)
if len(SH):
    ci = boot_prop(SH, lambda d: d.is_css.sum(), len)
    res.append(dict(measure="object-level PPV of shown objects (definite+probable)", value=SH.is_css.mean(), ci_low=ci[0], ci_high=ci[1], n=len(SH)))
    res.append(dict(measure="false-positive shown objects per scan", value=(~SH.is_css).sum() / SH.study_id.nunique(), n=int((~SH.is_css).sum())))
# ---------------- patient-side level
key_r = {v: k for k, v in key.items()}; ps = []
for sid in CL.study_id.dropna().unique():
    for h in ("L", "R"):
        con = pd.read_csv(f"{R.OUT}/inventory/{sid}_objects_public.csv").merge(pd.read_csv(f"{R.OUT}/inventory/{sid}_objects_concealed.csv"), on=["uid", "study_id"])
        ref = F[(F.study_id == sid) & F.reference_category.isin(POS2)]
        refh = ref.loc[(ref.hemisphere == h).to_numpy()]                      # side as recorded by the readers
        found = refh.fate.eq("retained (shown)").any()
        any_shown = ((con.stage == "shown") & (con.hemi == h)).any()
        ps.append(dict(study_id=sid, hemi=h, reference_positive=len(refh) > 0, detected=bool(found), production_shows_any=bool(any_shown)))
PS = pd.DataFrame(ps); PS.to_csv(f"{out}/patient_side_level.csv", index=False)
if len(PS):
    p = PS[PS.reference_positive]; n = PS[~PS.reference_positive]
    if len(p): res.append(dict(measure="patient-side sensitivity (>=1 reference cSS lesion retained)", value=p.detected.mean(), n=len(p), ci_low=boot_prop(p, lambda d: d.detected.sum(), len)[0], ci_high=boot_prop(p, lambda d: d.detected.sum(), len)[1]))
    if len(n): res.append(dict(measure="patient-side specificity (no shown object on a reference-negative side)", value=(~n.production_shows_any).mean(), n=len(n)))
# ---------------- excluded-object batches: design-based estimate of cSS among rejected objects
# Design: stratified simple random sampling without replacement of the rejected objects of the inventory (sample.py). The union of
# batches is again stratified SRS (each batch draws from the not-yet-sampled remainder of the same strata), so batches are pooled
# per stratum. N_h = rejected objects of the stratum in the inventory; n_h = sampled objects with a resolved category.
# p_h = cSS / n_h; exact Clopper-Pearson 95 % CI per stratum; total T = sum N_h p_h with the stratified-SRS variance including the finite-
# population correction, Var = sum N_h^2 (1 - n_h/N_h) p_h (1 - p_h) / (n_h - 1). Inference is about the rejected objects of THESE scans
# (design-based: correlation of objects within a patient does not bias it); generalising to new patients needs more patients.
# 'indeterminate' / 'unresolved' objects are reported and bounded both ways (as not cSS / as cSS). Strata never sampled are listed and
# NOT extrapolated.
from scipy.stats import beta as _beta, norm as _norm
def cp(k, n):
    if n == 0: return (np.nan, np.nan)
    return (0.0 if k == 0 else float(_beta.ppf(0.025, k, n - k + 1)), 1.0 if k == n else float(_beta.ppf(0.975, k + 1, n - k)))
est = []; bnames = [x for x in (arg("--batches", "") or "").split(",") if x]
if bnames:
    cfgs = [json.load(open(os.path.join(R.OUT, "batches", b, "batch_config.json"))) for b in bnames]
    if any(c["strata"] != cfgs[0]["strata"] for c in cfgs): sys.exit("batches use different strata - cannot be pooled")
    STR = cfgs[0]["strata"]; Ks = []
    for b in bnames:
        bd = os.path.join(R.OUT, "batches", b); k = pd.read_csv(f"{bd}/key_CONCEALED.csv")
        ann = sorted(glob.glob(f"{bd}/review/annotations_*.csv"))
        A_ = pd.concat([pd.read_csv(f, dtype=str) for f in ann]).fillna("") if ann else pd.DataFrame(columns=["case_id", "final_category"])
        adjp = f"{bd}/review/adjudication.csv"; adj_b = pd.read_csv(adjp, dtype=str).fillna("").set_index("case_id").adjudicated_category.to_dict() if os.path.exists(adjp) else {}
        fin = {}
        for cid, g in A_.groupby("case_id"):
            if adj_b.get(cid): fin[cid] = adj_b[cid]
            else: s_ = set(g.final_category); fin[cid] = s_.pop() if len(s_) == 1 else "unresolved"
        k["final"] = k.case_id.map(fin).fillna("not read"); Ks.append(k.assign(batch=b))
    K = pd.concat(Ks, ignore_index=True); K = K[K.stage != "shown"]
    # population N_h from the inventory (not from the batch keys, whose N shrinks as earlier batches remove objects)
    inv = []
    for sid in sorted(set(K.study_id)):
        c = pd.read_csv(f"{R.OUT}/inventory/{sid}_objects_concealed.csv").merge(pd.read_csv(f"{R.OUT}/inventory/{sid}_objects_public.csv"), on=["uid", "study_id"])
        inv.append(c[c.stage != "shown"])
    INV = pd.concat(inv, ignore_index=True)
    INV["confidence_bin"] = pd.cut(pd.to_numeric(INV.get("confidence_pct", np.nan), errors="coerce"), [-1, 10, 20, 30, 50, 101], labels=["<10", "10-20", "20-30", "30-50", ">=50"]).astype(str)
    INV["stratum"] = INV[STR].astype(str).agg("|".join, axis=1)
    studies_sampled = set(K.study_id); INV = INV[INV.study_id.isin(studies_sampled)]
    rows = []
    for st, g in INV.groupby("stratum"):
        s_ = K[K.stratum == st]; Nh = len(g); res_ = s_[s_.final.isin(list(POS2) + ["non_cSS"])]; nh = len(res_); kh = int(res_.final.isin(POS2).sum())
        ind = int(s_.final.isin(["indeterminate", "unresolved"]).sum())
        ph = kh / nh if nh else np.nan; lo, hi = cp(kh, nh)
        rows.append(dict(stratum=st, population_N=Nh, sampled=len(s_), reviewed_resolved_n=nh, css_found=kh, indeterminate_or_unresolved=ind,
                         not_read=int((s_.final == "not read").sum()), p_hat=ph, p_ci_low=lo, p_ci_high=hi, est_css_objects=Nh * ph if nh else np.nan,
                         p_hat_if_indeterminate_are_css=(kh + ind) / (nh + ind) if nh + ind else np.nan,
                         var_component=(Nh ** 2 * (1 - nh / Nh) * ph * (1 - ph) / (nh - 1)) if nh > 1 else (0.0 if nh == Nh and nh else np.nan),
                         status="sampled" if nh else "NOT SAMPLED - not extrapolated"))
    E = pd.DataFrame(rows); S_ = E[E.reviewed_resolved_n > 0]
    if len(S_):
        T = S_.est_css_objects.sum(); V = S_.var_component.fillna(0).sum(); Ncov = S_.population_N.sum(); z = _norm.ppf(0.975)
        res.append(dict(measure="estimated cSS objects among rejected objects (sampled strata)", value=T, ci_low=max(0.0, T - z * np.sqrt(V)), ci_high=T + z * np.sqrt(V), n=int(S_.reviewed_resolved_n.sum())))
        res.append(dict(measure="estimated miss rate among rejected objects (sampled strata; stratified-SRS normal approx.)", value=T / Ncov, ci_low=max(0.0, (T - z * np.sqrt(V)) / Ncov), ci_high=(T + z * np.sqrt(V)) / Ncov, n=int(Ncov),
                        note="unreliable when few cSS are found (collapses to 0-0 when none): use the conservative row below"))
        res.append(dict(measure="estimated miss rate among rejected objects (conservative: N-weighted sum of stratum exact limits)", value=T / Ncov,
                        ci_low=float((S_.population_N * S_.p_ci_low).sum() / Ncov), ci_high=float((S_.population_N * S_.p_ci_high).sum() / Ncov), n=int(Ncov)))
        res.append(dict(measure="NPV of production rejection (sampled strata)", value=1 - T / Ncov, n=int(Ncov)))
        res.append(dict(measure="rejected objects in strata NOT sampled (no estimate)", value=int(E[E.reviewed_resolved_n == 0].population_N.sum()), n=int(len(E) - len(S_))))
        for mech, g in E.assign(mechanism=E.stratum.str.split("|").str[0]).groupby("mechanism"):
            gg = g[g.reviewed_resolved_n > 0]
            if len(gg):
                t = gg.est_css_objects.sum(); v = gg.var_component.fillna(0).sum(); nn = gg.population_N.sum()
                k_all, n_all = int(gg.css_found.sum()), int(gg.reviewed_resolved_n.sum())
                res.append(dict(measure=f"  miss rate, mechanism: {mech} (CI = N-weighted stratum exact limits, conservative)", value=t / nn,
                                ci_low=float((gg.population_N * gg.p_ci_low).sum() / nn), ci_high=float((gg.population_N * gg.p_ci_high).sum() / nn),
                                n=n_all, note=f"{k_all} cSS in {n_all} reviewed; exact upper 95 % bound if 0 found: {1 - 0.05 ** (1 / n_all):.3f}" if k_all == 0 else f"{k_all} cSS in {n_all} reviewed"))
    else: E = pd.DataFrame(rows)
E = E if bnames else pd.DataFrame(); E.to_csv(f"{out}/rejected_objects_css_estimate.csv", index=False)
pd.DataFrame(res).to_csv(f"{out}/production_performance.csv", index=False)
print(pd.DataFrame(res).to_string(index=False)); print(f"-> {out}")
