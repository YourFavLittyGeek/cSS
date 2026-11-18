"""Inter-reader agreement + disagreement / adjudication queues (original reads are never changed).
usage: python reference_audit/agreement.py whole_scan PACKET            (lesion-level whole-scan reads)
       python reference_audit/agreement.py objects BATCH                (excluded-object batch reads)
Inputs (filled by readers): whole_scan/<PACKET>/lesion_annotations_<reader>.csv + patient_annotations_<reader>.csv;
  batches/<BATCH>/review/annotations_<reader>.csv (copies of annotation_sheet.csv, one per reader).
Outputs next to the inputs (new files only):
  agreement_summary.csv        Cohen kappa per reader pair, Fleiss kappa (all readers), percent agreement, quadratic-weighted kappa for
                               confidence; whole scan also: patient-side presence agreement and lesion localisation agreement
  lesion_clusters.csv          (whole scan) every reader's lesions grouped across readers (centres <= MATCH_MM apart) with each reader's category
  disagreements.csv            every item where readers differ -> adjudication
  adjudication_TEMPLATE.csv    the same items with an empty adjudicated_category column for the adjudicator (copy, fill, save as
                               adjudication.csv - the readers' files stay untouched)"""
import sys, os, glob, re, numpy as np, pandas as pd, nibabel as nib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ra_common as R

MATCH_MM = 5.0
POS = {"definite_cSS", "probable_cSS"}

def cohen(a, b, cats=None):
    a, b = np.asarray(a), np.asarray(b); cats = cats or sorted(set(a) | set(b)); po = (a == b).mean()
    pe = sum((a == c).mean() * (b == c).mean() for c in cats)
    return (po - pe) / (1 - pe) if pe < 1 else np.nan

def wkappa(a, b, k=5):
    a = np.asarray(a, int) - 1; b = np.asarray(b, int) - 1; O = np.zeros((k, k))
    for i, j in zip(a, b): O[i, j] += 1
    W = np.array([[(i - j) ** 2 / (k - 1) ** 2 for j in range(k)] for i in range(k)]); E = np.outer(O.sum(1), O.sum(0)) / O.sum()
    return 1 - (W * O).sum() / (W * E).sum() if (W * E).sum() else np.nan

def fleiss(M):
    """M: items x categories counts (every item rated by the same number of readers)"""
    M = np.asarray(M, float); n = M.sum(1)
    if len(set(n)) != 1 or n[0] < 2: return np.nan
    n = n[0]; p = M.sum(0) / M.sum(); P = ((M ** 2).sum(1) - n) / (n * (n - 1)); Pb, Pe = P.mean(), (p ** 2).sum()
    return (Pb - Pe) / (1 - Pe) if Pe < 1 else np.nan

NB, SEED = 2000, 20261119

def boot_ci(W, stat, patient_of):
    """95 % percentile CI of stat(W) over bootstrap resamples of PATIENTS (all items of a patient move together)"""
    if not len(W): return (np.nan, np.nan)
    pats = np.array([patient_of(i) for i in W.index]); u = np.unique(pats); rng = np.random.default_rng(SEED); v = []
    pos = {q: np.nonzero(pats == q)[0] for q in u}
    for _ in range(NB):
        idx = np.concatenate([pos[q] for q in rng.choice(u, len(u))]); v.append(stat(W.iloc[idx]))
    v = np.asarray(v, float)
    return (round(float(np.nanpercentile(v, 2.5)), 3), round(float(np.nanpercentile(v, 97.5)), 3)) if np.isfinite(v).any() else (np.nan, np.nan)

PATIENT_OF = lambda i: str(i).split("|")[0]          # items are keyed "<patient>|<item>" so the bootstrap can group them

def pairwise(df, item, rater, col, label):
    W = df.pivot_table(index=item, columns=rater, values=col, aggfunc="first"); rows = []
    rs = list(W.columns)
    for i, r1 in enumerate(rs):
        for r2 in rs[i + 1:]:
            d = W[[r1, r2]].dropna()
            if len(d):
                lo, hi = boot_ci(d, lambda x: cohen(x[r1], x[r2]), PATIENT_OF)
                rows.append(dict(measure=label, reader_1=r1, reader_2=r2, n_items=len(d), patients=len({PATIENT_OF(i) for i in d.index}),
                                 agreement=round((d[r1] == d[r2]).mean(), 3), kappa=round(cohen(d[r1], d[r2]), 3), kappa_ci_low=lo, kappa_ci_high=hi))
    full = W.dropna()
    if len(rs) >= 2 and len(full):
        cats = sorted(set(full.values.ravel())); M = np.array([[(row == c).sum() for c in cats] for row in full.values])
        fk = lambda x: fleiss(np.array([[(row == c).sum() for c in cats] for row in x.values]))
        lo, hi = boot_ci(full, fk, PATIENT_OF)
        rows.append(dict(measure=label, reader_1="ALL", reader_2=f"{len(rs)} readers", n_items=len(full), patients=len({PATIENT_OF(i) for i in full.index}),
                         agreement=round(float((full.nunique(1) == 1).mean()), 3), kappa=round(fleiss(M), 3), kappa_ci_low=lo, kappa_ci_high=hi,
                         note="Fleiss kappa (items rated by every reader)"))
    return rows

def objects(batch):
    rv = os.path.join(R.OUT, "batches", batch, "review"); files = sorted(glob.glob(f"{rv}/annotations_*.csv"))
    if len(files) < 2: sys.exit(f"need >= 2 reader files {rv}/annotations_<reader>.csv")
    D = pd.concat([pd.read_csv(f, dtype=str).assign(reader=re.sub(r"^annotations_|\.csv$", "", os.path.basename(f))) for f in files], ignore_index=True).fillna("")
    D["css_yes"] = D.final_category.isin(POS).map({True: "cSS", False: "not"})
    D["case_id"] = D.patient_id + "|" + D.case_id                     # patient-keyed item id (for the cluster bootstrap)
    rows = pairwise(D, "case_id", "reader", "final_category", "4-class category") + pairwise(D, "case_id", "reader", "css_yes", "cSS (definite+probable) vs not")
    C = D[D.confidence_1to5 != ""]; W = C.pivot_table(index="case_id", columns="reader", values="confidence_1to5", aggfunc="first")
    rs = list(W.columns)
    for i, r1 in enumerate(rs):
        for r2 in rs[i + 1:]:
            d = W[[r1, r2]].dropna()
            if len(d):
                lo, hi = boot_ci(d, lambda x: wkappa(x[r1], x[r2]), PATIENT_OF)
                rows.append(dict(measure="confidence 1-5 (quadratic weighted kappa)", reader_1=r1, reader_2=r2, n_items=len(d), kappa=round(wkappa(d[r1], d[r2]), 3), kappa_ci_low=lo, kappa_ci_high=hi))
    pd.DataFrame(rows).to_csv(f"{rv}/agreement_summary.csv", index=False)
    W = D.pivot_table(index="case_id", columns="reader", values="final_category", aggfunc="first")
    dis = W[W.nunique(1) > 1].reset_index(); dis["case_id"] = dis.case_id.str.split("|").str[1]; dis.to_csv(f"{rv}/disagreements.csv", index=False)
    dis.assign(adjudicated_category="", adjudicated_noncss_type="", adjudicator="", adjudication_note="").to_csv(f"{rv}/adjudication_TEMPLATE.csv", index=False)
    print(f"{batch}: {W.shape[0]} cases, {len(dis)} disagreements -> {rv}/agreement_summary.csv")

def whole_scan(packet):
    d = os.path.join(R.OUT, "whole_scan", packet); key = pd.read_csv(f"{d}/key_CONCEALED.csv")
    files = sorted(glob.glob(f"{d}/lesion_annotations_*.csv"))
    L = pd.concat([pd.read_csv(f, dtype=str).assign(reader=re.sub(r"^lesion_annotations_|\.csv$", "", os.path.basename(f))) for f in files], ignore_index=True).fillna("")
    aff = {}
    for r in key.itertuples():
        p = f"{d}/cases/{r.case_code}/" + ("SWI.nii" if os.path.exists(f"{d}/cases/{r.case_code}/SWI.nii") else "SWI.nii.gz")
        aff[r.case_code] = nib.load(p).affine
    def xyz(r):
        A = aff.get(r.patient_id)
        if r.vox_i != "" and A is not None: return (A @ np.r_[float(r.vox_i), float(r.vox_j), float(r.vox_k), 1])[:3]
        if r.x_mm != "": return np.array([float(r.x_mm), float(r.y_mm), float(r.z_mm)])
        return np.array([np.nan] * 3)
    if len(L): P = np.vstack([xyz(r) for r in L.itertuples()]); L["X"], L["Y"], L["Z"] = P[:, 0], P[:, 1], P[:, 2]
    # cluster lesions across readers per case (single linkage <= MATCH_MM)
    L["cluster"] = -1; cid = 0
    for case, g in L.groupby("patient_id"):
        idx = list(g.index); pts = L.loc[idx, ["X", "Y", "Z"]].to_numpy(float); lab = -np.ones(len(idx), int)
        for i in range(len(idx)):
            if lab[i] >= 0: continue
            lab[i] = cid; stack = [i]
            while stack:
                k = stack.pop(); dd = np.sqrt(((pts - pts[k]) ** 2).sum(1))
                for j in np.nonzero((dd <= MATCH_MM) & (lab < 0))[0]: lab[j] = cid; stack.append(j)
            cid += 1
        L.loc[idx, "cluster"] = lab
    readers = sorted(L.reader.unique()); rows = []
    for c, g in L.groupby("cluster"):
        r = dict(cluster_id=int(c), patient_id=g.patient_id.iloc[0], x_mm=round(g.X.mean(), 1), y_mm=round(g.Y.mean(), 1), z_mm=round(g.Z.mean(), 1))
        for rd in readers:
            gg = g[g.reader == rd]
            r[f"{rd}_category"] = "|".join(sorted(set(gg.final_category))) if len(gg) else "not_marked"
            r[f"{rd}_confidence"] = "|".join(gg.confidence_1to5) if len(gg) else ""
            r[f"{rd}_lesion_ids"] = "|".join(gg.lesion_id)
        cats = {r[f"{rd}_category"] for rd in readers}
        r["unanimous"] = len(cats) == 1; r["adjudication_needed"] = not r["unanimous"]
        rows.append(r)
    CL = pd.DataFrame(rows); CL.to_csv(f"{d}/lesion_clusters.csv", index=False)
    srows = []
    long = CL.melt(id_vars=["cluster_id"], value_vars=[f"{rd}_category" for rd in readers], var_name="reader", value_name="cat")
    long["cluster_id"] = long.cluster_id.map(dict(zip(CL.cluster_id, CL.patient_id.astype(str) + "|" + CL.cluster_id.astype(str))))
    long["reader"] = long.reader.str.replace("_category", ""); long["present"] = long.cat.map(lambda x: "cSS" if any(c in POS for c in x.split("|")) else "not")
    srows += pairwise(long, "cluster_id", "reader", "present", "lesion localisation: cSS marked at this location (all clusters)")
    pos_cl = CL[[any(any(c in POS for c in str(r[f"{rd}_category"]).split("|")) for rd in readers) for _, r in CL.iterrows()]]
    for i, r1 in enumerate(readers):
        for r2 in readers[i + 1:]:
            a = pos_cl[f"{r1}_category"].map(lambda x: any(c in POS for c in x.split("|"))); b = pos_cl[f"{r2}_category"].map(lambda x: any(c in POS for c in x.split("|")))
            both = int((a & b).sum())
            AB = pd.DataFrame(dict(a=a.to_numpy(), b=b.to_numpy()), index=pos_cl.patient_id.astype(str) + "|" + pos_cl.cluster_id.astype(str))
            lo, hi = boot_ci(AB, lambda x: 2 * (x.a & x.b).sum() / max(int(x.a.sum()) + int(x.b.sum()), 1), PATIENT_OF)
            srows.append(dict(measure=f"lesion detection overlap (matched within {MATCH_MM:g} mm)", reader_1=r1, reader_2=r2, agreement_ci_low=lo, agreement_ci_high=hi,
                                                        n_items=len(pos_cl), agreement=round(2 * both / max(int(a.sum()) + int(b.sum()), 1), 3), note=f"Dice-like 2M/(n1+n2); both {both}, only {r1} {int((a & ~b).sum())}, only {r2} {int((~a & b).sum())}"))
    pf = sorted(glob.glob(f"{d}/patient_annotations_*.csv"))
    if pf:
        PA = pd.concat([pd.read_csv(f, dtype=str).assign(reader=re.sub(r"^patient_annotations_|\.csv$", "", os.path.basename(f))) for f in pf]).fillna("")
        PL = pd.concat([PA.assign(item=PA.patient_id + "|L", v=PA.css_present_L), PA.assign(item=PA.patient_id + "|R", v=PA.css_present_R)])
        srows += pairwise(PL, "item", "reader", "v", "patient-side cSS presence")
        PL2 = pd.concat([PA.assign(item=PA.patient_id + "|L", v=PA.multifocality_L_0to2), PA.assign(item=PA.patient_id + "|R", v=PA.multifocality_R_0to2)])
        srows += pairwise(PL2, "item", "reader", "v", "patient-side multifocality 0-2 (unweighted)")
        W2 = PL2.pivot_table(index="item", columns="reader", values="v", aggfunc="first")
        for i, r1 in enumerate(W2.columns):
            for r2 in W2.columns[i + 1:]:
                mf = W2[[r1, r2]].dropna(); mf = mf[(mf[r1] != "") & (mf[r2] != "")]
                if len(mf):
                    f = lambda x, r1=r1, r2=r2: wkappa(x[r1].astype(int) + 1, x[r2].astype(int) + 1, k=3)
                    lo, hi = boot_ci(mf, f, PATIENT_OF)
                    srows.append(dict(measure="patient-side multifocality 0-2 (quadratic weighted kappa)", reader_1=r1, reader_2=r2, n_items=len(mf), kappa=round(f(mf), 3), kappa_ci_low=lo, kappa_ci_high=hi))
    pd.DataFrame(srows).to_csv(f"{d}/agreement_summary.csv", index=False)
    dis = CL[CL.adjudication_needed]; dis.to_csv(f"{d}/disagreements.csv", index=False)
    dis.assign(adjudicated_category="", adjudicated_noncss_type="", adjudicator="", adjudication_note="").to_csv(f"{d}/adjudication_TEMPLATE.csv", index=False)
    print(f"{packet}: {len(L)} marks by {readers} -> {len(CL)} lesion clusters, {len(dis)} need adjudication -> {d}")

if __name__ == "__main__":
    if len(sys.argv) < 3: sys.exit(__doc__)
    (whole_scan if sys.argv[1] == "whole_scan" else objects)(sys.argv[2])
