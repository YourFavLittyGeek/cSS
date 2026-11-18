"""Read-only evaluation of experimental structural features against reader calls (run on the Mac, where images are).
Usage: python -m structural_detection.evaluate_structural FEATURES_GLOB_OR_DIR OUT_DIR [--evaluation]
  inputs: features.csv files from run_structural.py (--include-excluded recommended), $CSS_BASE/review/ID_calls.csv,
          review/radiologist_grades.csv (optional: study_id,R,L) for zero-graded sides.
Studies listed in review/evaluation_studies.txt are REFUSED unless --evaluation is given (held-out, examined once).
Groups: A cSS call on a radiologist-positive side; B Vessel/Vein call; C Normal/Artifact/Microbleed; D unread on a
zero side (reported separately, never pooled as negatives); E conflicts. Per feature: AUC A vs B and A vs B+C with
explicit direction (P(cSS > other)) and patient-cluster bootstrap CI; fusion category x group table.
No thresholds are chosen and nothing is written back to the pipeline."""
import sys, os, glob, numpy as np, pandas as pd

def auc(y, s):
    y = np.asarray(y); s = np.asarray(s, float); k = np.isfinite(s); y, s = y[k], s[k]; p, n = s[y == 1], s[y == 0]
    if not len(p) or not len(n): return np.nan
    return float(((p[:, None] > n[None]).sum() + 0.5 * (p[:, None] == n[None]).sum()) / (len(p) * len(n)))

def cboot(df, col, B=2000, seed=20261118):
    rng = np.random.default_rng(seed); st = df.study_id.to_numpy(); u = np.unique(st); out = []
    for _ in range(B):
        idx = np.concatenate([np.nonzero(st == q)[0] for q in rng.choice(u, len(u))])
        if len(set(df.y.to_numpy()[idx])) == 2: out.append(auc(df.y.to_numpy()[idx], df[col].to_numpy(float)[idx]))
    return np.nanpercentile(out, [2.5, 97.5]) if out else (np.nan, np.nan)

def main(a):
    src, out = a[0], a[1]; os.makedirs(out, exist_ok=True); base = os.environ.get("CSS_BASE", os.path.expanduser("~/css_project"))
    files = sorted(glob.glob(os.path.join(src, "**", "features.csv"), recursive=True)) if os.path.isdir(src) else sorted(glob.glob(src))
    if not files: sys.exit("no features.csv found")
    F = pd.concat([pd.read_csv(f) for f in files]).drop_duplicates(["study_id", "source", "obj_id"], keep="last")
    ev = set(open(f"{base}/review/evaluation_studies.txt").read().split()) if os.path.exists(f"{base}/review/evaluation_studies.txt") else set()
    if ev & set(F.study_id) and "--evaluation" not in a:
        sys.exit(f"refused: evaluation studies {sorted(ev & set(F.study_id))} present; pass --evaluation for the one planned look")
    g = pd.read_csv(f"{base}/review/radiologist_grades.csv") if os.path.exists(f"{base}/review/radiologist_grades.csv") else None
    rows = []
    for sid, sub in F[F.source == "candidate"].groupby("study_id"):
        cp = f"{base}/review/{sid}_calls.csv"
        if not os.path.exists(cp): continue
        c = pd.read_csv(cp)
        cand = pd.read_csv(f"{base}/review/{sid}_candidates.csv")[["cand_id", "hemi", "vox_i", "vox_j", "vox_k"]]
        c = c.merge(cand, on="cand_id", how="left", suffixes=("", "_list"))
        if {"vox_i", "vox_i_list"} <= set(c.columns):          # fingerprint: a call belongs to the object it was made on
            bad = (c[["vox_i", "vox_j", "vox_k"]].to_numpy() != c[["vox_i_list", "vox_j_list", "vox_k_list"]].to_numpy()).any(1)
            if bad.any(): print(f"{sid}: {int(bad.sum())} calls do not match the current list (re-detected?) - left unlabelled")
            c.loc[bad, "call"] = np.nan
        c = c.rename(columns={"cand_id": "obj_id"})
        m = sub.merge(c[["obj_id", "call", "hemi"]], on="obj_id", how="left").rename(columns={"call": "reader_call"})
        rows.append(m)
    if not rows: sys.exit("no calls matched")
    D = pd.concat(rows, ignore_index=True)
    zero = set()
    if g is not None:
        zero = {(r.study_id, h) for r in g.itertuples() for h in ("R", "L") if getattr(r, h) == 0}
    call = D.reader_call.fillna("").str.strip()
    zs = [(s, h) in zero for s, h in zip(D.study_id, D.get("hemi", pd.Series([""] * len(D))))]
    D["group"] = np.select([np.array(zs) & (call == ""), np.array(zs) & (call == "cSS"), call == "cSS", call.isin(["Vessel", "Vein"]),
                            call.isin(["Normal", "Artifact", "Microbleed"])], ["D", "E", "A", "B", "C"], "U")
    D.to_csv(f"{out}/features_with_calls.csv", index=False)
    num = [c for c in D.columns if D[c].dtype.kind in "fi" and c not in ("obj_id",)]
    res = []
    for nm, neg in (("A_vs_B", ["B"]), ("A_vs_BC", ["B", "C"])):
        s = D[D.group.isin(["A"] + neg)].copy(); s["y"] = (s.group == "A").astype(int)
        for col in num:
            a_ = auc(s.y, s[col]); lo, hi = cboot(s, col) if np.isfinite(a_) else (np.nan, np.nan)
            res.append(dict(comparison=nm, feature=col, n_cSS=int(s.y.sum()), n_other=int((1 - s.y).sum()), patients=s.study_id.nunique(),
                            auc_P_cSS_greater=round(a_, 3), ci_low=round(lo, 3), ci_high=round(hi, 3), missing=int(s[col].isna().sum())))
    pd.DataFrame(res).to_csv(f"{out}/feature_auc.csv", index=False)
    if "fusion_category" in D: pd.crosstab(D.fusion_category, D.group).to_csv(f"{out}/fusion_by_group.csv")
    print(f"evaluated {len(D)} objects from {D.study_id.nunique()} studies -> {out} (descriptive; no threshold chosen)")

if __name__ == "__main__":
    if len(sys.argv) < 3: sys.exit(__doc__)
    main(sys.argv[1:])
