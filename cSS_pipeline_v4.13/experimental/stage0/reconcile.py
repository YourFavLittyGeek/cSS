"""Stage 0 reconciliation of the 111 / 141 object sets and the tube_ratio AUC direction (read-only)."""
import sys, numpy as np, pandas as pd, json
R = sys.argv[1]; OUT = sys.argv[2]
cmp_ = pd.read_csv(f"{R}/v510_compare.csv"); fit = pd.read_csv(f"{R}/confidence_fit.csv"); g = pd.read_csv(f"{R}/radiologist_grades.csv")
neg = {(r.study_id, h) for _, r in g.iterrows() for h in ("R", "L") if r[h] == 0}
cmp_["goldneg"] = [(s, h) in neg for s, h in zip(cmp_.study_id, cmp_.hemi)]
rows = []
rows.append(dict(set="v510_compare.csv (all rows)", rows=len(cmp_), unique_study_object=cmp_.groupby(["study_id", "cand_id"]).ngroups, note="147 objects of the M02-M11 lists; one row per object; features of the copy-run object (v5.10 detector, CSS_CONF=1)"))
sh = cmp_[cmp_.fate == "shown"]
rows.append(dict(set="  of which shown in the copy run", rows=len(sh), unique_study_object=sh.groupby(["study_id", "cand_id"]).ngroups, note="29 objects excluded by E30 (24.2 % cut) in the copy run are removed here"))
y = np.where(sh.goldneg, 0, np.where(sh.reader_call == "cSS", 1, np.where(sh.reader_call.isin(["Vessel", "Vein", "Normal", "Artifact", "Near ICH", "Microbleed", "cSS (radiologist: none)"]), 0, -1)))
t = sh[y >= 0]
rows.append(dict(set="audit feature_table.csv = shown & labelled", rows=len(t), unique_study_object=t.groupby(["study_id", "cand_id"]).ngroups,
                 note=f"label = PRIMARY reader shared call; negatives include radiologist-zero-side objects (also unread) and Near ICH / overruled cSS; calls: {t.reader_call.fillna('(none)').value_counts().to_dict()}"))
rows.append(dict(set="confidence_fit.csv (fit_confidence.py)", rows=len(fit), unique_study_object=fit.groupby(["study_id", "obj_id"]).ngroups,
                 note=f"141 labelled of the 147 shown objects of the FULL lists (before any cut); label = cSS if ANY of reads ST/ML/Redo_v53/Blind_v57 + adjudication said cSS; radiologist-zero side -> 0; y counts {fit.y.value_counts().to_dict()}"))
m = fit.merge(cmp_, left_on=["study_id", "obj_id"], right_on=["study_id", "cand_id"], how="outer", indicator=True)
rows.append(dict(set="join confidence_fit x v510_compare on (study, object id)", rows=len(m), unique_study_object=int((m._merge == "both").sum()), note=f"merge result {m._merge.value_counts().to_dict()}"))
both = m[m._merge == "both"].copy()
both["prim_css"] = (both.reader_call == "cSS") & ~both.goldneg
diff = both[(both.y == 1) != both.prim_css]
rows.append(dict(set="objects whose cSS status differs between the two label definitions", rows=len(diff), unique_study_object=len(diff),
                 note="; ".join(f"{r.study_id}#{int(r.obj_id)} fit y={int(r.y)} primary={r.reader_call}" for r in diff.itertuples())[:900]))
pd.DataFrame(rows).to_csv(f"{OUT}/reconciliation_111_vs_141.csv", index=False)
# AUC direction, explicit
def auc(y, s):
    s = np.asarray(s, float); y = np.asarray(y); m_ = np.isfinite(s); y, s = y[m_], s[m_]; p, n = s[y == 1], s[y == 0]
    return float(((p[:, None] > n[None, :]).sum() + .5 * (p[:, None] == n[None, :]).sum()) / (len(p) * len(n)))
rng = np.random.default_rng(1)
def cboot(df, col, B=2000):
    st = df.study_id.to_numpy(); u = np.unique(st); yy = df.yy.to_numpy(); s = df[col].to_numpy(float); out = []
    for _ in range(B):
        pk = rng.choice(u, len(u)); idx = np.concatenate([np.nonzero(st == p)[0] for p in pk])
        if len(set(yy[idx])) == 2: out.append(auc(yy[idx], s[idx]))
    return np.percentile(out, [2.5, 97.5])
res = []
for nm, df in (("previous audit set: shown, cSS(A) vs Vessel", sh[(sh.reader_call.isin(["cSS", "Vessel"])) & ~sh.goldneg]),
               ("all 147: cSS(A) vs Vessel", cmp_[(cmp_.reader_call.isin(["cSS", "Vessel"])) & ~(cmp_.goldneg & (cmp_.reader_call == "cSS"))]),
               ("previous audit set: cSS vs all labelled non-cSS (feature-matrix value)", t)):
    df = df.copy()
    df["yy"] = ((df.reader_call == "cSS") & ~df.goldneg).astype(int)
    a = auc(df.yy, df.v53_tube_ratio); lo, hi = cboot(df, "v53_tube_ratio")
    res.append(dict(comparison=nm, positive_class="cSS call", n_pos=int(df.yy.sum()), n_neg=int((1 - df.yy).sum()), patients=df.study_id.nunique(),
                    auc_raw_P_cSS_greater=round(a, 3), auc_reversed_P_cSS_smaller=round(1 - a, 3), ci_raw_patient_bootstrap=f"{lo:.2f}-{hi:.2f}",
                    ci_reversed=f"{1 - hi:.2f}-{1 - lo:.2f}", direction="smaller tube_ratio = cSS" if a < .5 else "larger = cSS"))
pd.DataFrame(res).to_csv(f"{OUT}/auc_direction.csv", index=False)
print(pd.DataFrame(rows).to_string(index=False)); print(pd.DataFrame(res).to_string(index=False))
