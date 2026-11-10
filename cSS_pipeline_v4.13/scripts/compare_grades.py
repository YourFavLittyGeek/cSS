#!/usr/bin/env python3
"""Compare the pipeline's cSS multifocality score with an expert's PATIENT-LEVEL grades (v5.2.1). Research software.
usage: compare_grades.py --template                       -> labels/expert_grades.csv to fill (ids from cohort_import.csv)
       compare_grades.py [--expert labels/expert_grades.csv] [--scores review/css_scores.csv] [--boot 2000]
                         [--out results/grade_comparison]
       compare_grades.py --results-only     -> results/css_results.xlsx (+ .csv): the pipeline's scores alone
Expert file (.csv or .xlsx; one row per patient; the radiologist's own sheet works as it is: "Patient name", "ID",
"R css", "L css", "cSS score (0-4)" are recognised): study_id, expert_L (0-2), expert_R (0-2), expert_total (0-4; filled from L + R
when empty; a total that differs from L + R is reported, the given total is used). Optional column note.
Pipeline scores: review/css_scores.csv (score_css.py, after the cases were READ with review_css.py or expert_import
--score); qc_status from review/ID_qc.json, build from review/ID_manifest.json.
Writes (opens in Excel / Numbers):
  <out>_results.csv    the radiologist's layout: Patient name, ID, R cSS, L cSS, cSS score (0-4) of the pipeline, the
                       radiologist's three values, difference, agree, field strength, QC, notes (first sheet in .xlsx)
  <out>_patients.csv   one row per patient: expert and pipeline L / R / total, differences, presence, QC, flags
  <out>_summary.csv    per scale (total 0-4, left 0-2, right 0-2): n, exact agreement, within +-1, quadratic weighted
                       kappa with patient-bootstrap 95 % CI, unweighted kappa, Spearman rho, mean difference (pipeline -
                       expert) with 95 % limits of agreement; cSS presence per patient and per hemisphere: sensitivity,
                       specificity, counts
  <out>_confusion_total.csv  expert (rows) x pipeline (columns), total score 0-4
  <out>.xlsx           the same three tables as sheets, when openpyxl is installed
Patients without a pipeline score are listed, not dropped silently; scores with unreviewed candidates are flagged
(n_unreviewed > 0: the score is a lower bound), and so are patients whose series had missing slices interpolated on
import (cohort.py --repair-missing; column repaired_series). Patient-level grades cannot measure lesion-level sensitivity or false
positives - that needs candidate labels (expert_sheet.py / expert_import.py)."""
import sys, os, re, json, argparse, numpy as np, pandas as pd
from scipy.stats import spearmanr
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from css_common import base as _base, cohen_kappa

# v5.2.3: the radiologist's own sheet can be given as it is - column names are matched case / space / bracket-blind
ALIASES = {**dict.fromkeys(["studyid", "patientname", "patient", "name", "subject", "code"], "study_id"),
           **dict.fromkeys(["id", "patientid"], "patient_id"),
           **dict.fromkeys(["expertr", "rcss", "rightcss", "r", "right", "rscore", "rightscore"], "expert_R"),
           **dict.fromkeys(["expertl", "lcss", "leftcss", "l", "left", "lscore", "leftscore"], "expert_L"),
           **dict.fromkeys(["experttotal", "cssscore04", "cssscore", "total", "totalscore", "score", "csstotal"], "expert_total"),
           **dict.fromkeys(["note", "notes", "comment", "comments"], "note")}
RESULT_COLS = ["Patient name", "ID", "R cSS", "L cSS", "cSS score (0-4)"]
SCALES = [("total", "expert_total", "pipe_total", list(range(5))), ("left", "expert_L", "pipe_L", [0, 1, 2]),
          ("right", "expert_R", "pipe_R", [0, 1, 2])]


def read_json(p):
    try: return json.load(open(p))
    except Exception: return {}


def load(expert_p, scores_p, B):
    E = (pd.read_excel(expert_p, dtype=str) if expert_p.lower().endswith((".xlsx", ".xls"))
         else pd.read_csv(expert_p, dtype=str))                         # .xlsx needs openpyxl
    E = E.rename(columns=lambda c: ALIASES.get(re.sub(r"[^a-z0-9]", "", str(c).lower()), c))
    E = E.dropna(how="all")
    for c in ("study_id", "patient_id"):
        if c in E.columns: E[c] = E[c].astype(str).str.strip()
    need = {"study_id", "expert_L", "expert_R"} - set(E.columns)
    if need: sys.exit(f"{expert_p}: missing columns {sorted(need)}")
    if "expert_total" not in E.columns: E["expert_total"] = np.nan
    for c in ("expert_L", "expert_R", "expert_total"): E[c] = pd.to_numeric(E[c], errors="coerce")
    E["expert_LR_sum"] = E.expert_L + E.expert_R
    E["expert_total_mismatch"] = (E.expert_total.notna() & (E.expert_total != E.expert_LR_sum)).astype(int)
    E["expert_total"] = E.expert_total.fillna(E.expert_LR_sum)
    bad = E[(~E.expert_L.isin([0, 1, 2])) | (~E.expert_R.isin([0, 1, 2])) | (~E.expert_total.isin(range(5)))]
    if len(bad): sys.exit(f"{expert_p}: grades out of range (L/R 0-2, total 0-4) for {bad.study_id.tolist()}")
    S = pd.read_csv(scores_p, dtype={"subject": str}) if os.path.exists(scores_p) else pd.DataFrame(columns=["subject"])
    S = S.drop_duplicates("subject", keep="last").rename(columns={"subject": "study_id", "L_score": "pipe_L",
                                                                  "R_score": "pipe_R", "multifocality_0_4": "pipe_total"})
    keep = [c for c in ("study_id", "pipe_L", "pipe_R", "pipe_total", "scoring_method", "n_candidates", "n_unreviewed")
            if c in S.columns]
    D = E.merge(S[keep], on="study_id", how="left")
    D["qc_status"] = [read_json(f"{B}/review/{s}_qc.json").get("status", "") for s in D.study_id]
    D["field_T"] = [read_json(f"{B}/review/{s}_score.json").get("field_T", "") for s in D.study_id]
    D["build"] = [str(((read_json(f"{B}/review/{s}_manifest.json").get("detect") or {}).get("environment") or {}).get("build", ""))
                  for s in D.study_id]
    D["n_accepted"] = [int(pd.read_csv(p).get("accept", pd.Series(dtype=float)).fillna(0).sum())
                       if os.path.exists(p := f"{B}/review/{s}_candidates.csv") else np.nan for s in D.study_id]
    for e, p in (("expert_L", "pipe_L"), ("expert_R", "pipe_R"), ("expert_total", "pipe_total")):
        if p not in D.columns: D[p] = np.nan
        D[f"diff_{p[5:]}"] = D[p] - D[e]
    D["expert_css"] = (D.expert_total > 0).astype(int)
    D["pipe_css"] = np.where(D.pipe_total.notna(), (D.pipe_total > 0).astype(float), np.nan)
    ci = f"{B}/review/cohort_import.csv"                    # v5.2.2: series repaired by interpolation on import
    imp = pd.read_csv(ci, dtype=str).fillna("").set_index("study_id")["flags"] if os.path.exists(ci) else pd.Series(dtype=str)
    D["repaired_series"] = [";".join(x for x in imp.get(s, "").split(";") if "_repaired_" in x) for s in D.study_id]
    fl = []
    for _, r in D.iterrows():
        f = []
        if r.repaired_series: f.append(f"slices interpolated on import ({r.repaired_series}) - preliminary")
        if pd.isna(r.pipe_total): f.append("no pipeline score")
        if r.get("n_unreviewed", 0) and r.get("n_unreviewed", 0) > 0: f.append(f"{int(r.n_unreviewed)} candidates unreviewed")
        if r.expert_total_mismatch: f.append("expert total != L + R")
        if str(r.qc_status) not in ("", "ok"): f.append(f"QC {r.qc_status}")
        if str(r.get("scoring_method", "")).startswith("euclid"): f.append("Euclidean approximation (no Destrieux labels)")
        fl.append("; ".join(f))
    D["flags"] = fl
    return D


def results_table(D):
    """the radiologist's layout: Patient name, ID, R cSS, L cSS, cSS score (0-4) - pipeline, then radiologist, then
    the difference and agreement per patient (only the pipeline columns when there are no expert grades)"""
    iv = lambda v: "" if pd.isna(v) else int(v)
    rows = []
    for _, r in D.iterrows():
        row = {"Patient name": r.study_id, "ID": r.get("patient_id", "") if pd.notna(r.get("patient_id", "")) else "",
               "R cSS": iv(r.pipe_R), "L cSS": iv(r.pipe_L), "cSS score (0-4)": iv(r.pipe_total)}
        if "expert_total" in D.columns:
            row.update({"radiologist R cSS": iv(r.expert_R), "radiologist L cSS": iv(r.expert_L),
                        "radiologist cSS score (0-4)": iv(r.expert_total),
                        "difference (pipeline - radiologist)": iv(r.diff_total),
                        "agree": "" if pd.isna(r.pipe_total) else ("yes" if r.pipe_total == r.expert_total else "no")})
        row.update({"field (T)": r.get("field_T", ""), "QC": r.get("qc_status", ""), "notes": r.get("flags", "")})
        rows.append(row)
    return pd.DataFrame(rows)


def boot_kappa(a, b, cats, n, seed):
    rng = np.random.default_rng(seed); v = []
    for _ in range(n):
        i = rng.integers(0, len(a), len(a)); k = cohen_kappa(a[i], b[i], cats, "quadratic")
        if np.isfinite(k): v.append(k)
    return [round(float(np.percentile(v, 2.5)), 3), round(float(np.percentile(v, 97.5)), 3)] if len(v) > 20 else [None, None]


def presence(y, p):
    tp, fn = int(((y == 1) & (p == 1)).sum()), int(((y == 1) & (p == 0)).sum())
    tn, fp = int(((y == 0) & (p == 0)).sum()), int(((y == 0) & (p == 1)).sum())
    return dict(tp=tp, fn=fn, tn=tn, fp=fp, sensitivity=round(tp / (tp + fn), 3) if tp + fn else None,
                specificity=round(tn / (tn + fp), 3) if tn + fp else None)


def summarise(D, boot, seed):
    rows = []
    for name, e, p, cats in SCALES:
        d = D[D[p].notna()]; a, b = d[e].astype(int).values, d[p].astype(int).values
        if not len(d): rows.append(dict(scale=name, n=0)); continue
        diff = b - a; sd = float(np.std(diff, ddof=1)) if len(diff) > 1 else np.nan
        rho = spearmanr(a, b).statistic if len(set(a)) > 1 and len(set(b)) > 1 else np.nan
        rows.append(dict(scale=name, n=len(d), exact_agreement=round(float((diff == 0).mean()), 3),
                         within_1=round(float((np.abs(diff) <= 1).mean()), 3),
                         kappa_quadratic=round(cohen_kappa(a, b, cats, "quadratic"), 3),
                         kappa_quadratic_ci95=boot_kappa(a, b, cats, boot, seed),
                         kappa_unweighted=round(cohen_kappa(a, b, cats), 3),
                         spearman_rho=None if not np.isfinite(rho) else round(float(rho), 3),
                         mean_diff_pipeline_minus_expert=round(float(diff.mean()), 3),
                         loa95_low=None if not np.isfinite(sd) else round(float(diff.mean() - 1.96 * sd), 3),
                         loa95_high=None if not np.isfinite(sd) else round(float(diff.mean() + 1.96 * sd), 3),
                         pipeline_higher=int((diff > 0).sum()), pipeline_lower=int((diff < 0).sum())))
    d = D[D.pipe_total.notna()]
    rows.append(dict(scale="cSS present (patient, total > 0)", n=len(d),
                     **presence(d.expert_css.values, d.pipe_css.astype(int).values)))
    hy = np.r_[(d.expert_L > 0).values, (d.expert_R > 0).values].astype(int)
    hp = np.r_[(d.pipe_L > 0).values, (d.pipe_R > 0).values].astype(int)
    rows.append(dict(scale="cSS present (hemisphere, score > 0)", n=2 * len(d), **presence(hy, hp)))
    return pd.DataFrame(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--template", action="store_true"); ap.add_argument("--expert", default="")
    ap.add_argument("--scores", default=""); ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=1); ap.add_argument("--out", default="")
    ap.add_argument("--results-only", action="store_true", help="pipeline scores in the radiologist's layout, no comparison")
    a = ap.parse_args(); B = _base()
    ep = a.expert or f"{B}/labels/expert_grades.csv"
    if a.template:
        ci = f"{B}/review/cohort_import.csv"
        ids = pd.read_csv(ci, dtype=str).study_id.tolist() if os.path.exists(ci) else []
        if os.path.exists(ep): sys.exit(f"{ep} exists - not overwritten")
        os.makedirs(os.path.dirname(ep), exist_ok=True)
        pd.DataFrame(dict(study_id=ids, expert_L="", expert_R="", expert_total="", note="")).to_csv(ep, index=False)
        sys.exit(print(f"-> {ep} with {len(ids)} rows: fill expert_L / expert_R (0-2) and expert_total (0-4)") or 0)
    if a.results_only:                   # no expert file: every scored patient, pipeline columns only
        ids = pd.read_csv(a.scores or f"{B}/review/css_scores.csv", dtype=str).subject.drop_duplicates().tolist()
        tmp = f"{B}/results/.ids_only.csv"; os.makedirs(os.path.dirname(tmp), exist_ok=True)
        pd.DataFrame(dict(study_id=ids, expert_L=0, expert_R=0)).to_csv(tmp, index=False)
        D = load(tmp, a.scores or f"{B}/review/css_scores.csv", B); os.remove(tmp)
        R = results_table(D.drop(columns=["expert_total"]))
        R["notes"] = [f.replace("expert total != L + R", "").strip("; ") for f in R.notes]
        out = a.out or f"{B}/results/css_results"; R.to_csv(f"{out}.csv", index=False)
        try:
            R.to_excel(f"{out}.xlsx", sheet_name="results", index=False); xl = f" and {out}.xlsx"
        except ImportError:
            xl = " (.xlsx: conda install -n css -c conda-forge openpyxl)"
        print(R[RESULT_COLS].to_string(index=False))
        sys.exit(print(f"-> {out}.csv{xl}   [research software: pipeline + reader scores, not validated]") or 0)
    D = load(ep, a.scores or f"{B}/review/css_scores.csv", B)
    out = a.out or f"{B}/results/grade_comparison"; os.makedirs(os.path.dirname(out), exist_ok=True)
    cols = ["study_id", "expert_L", "pipe_L", "diff_L", "expert_R", "pipe_R", "diff_R", "expert_total", "pipe_total",
            "diff_total", "expert_css", "pipe_css", "scoring_method", "qc_status", "n_candidates", "n_accepted",
            "n_unreviewed", "build", "repaired_series", "flags"] + [c for c in ("note",) if c in D.columns]
    P = D[[c for c in cols if c in D.columns]]; Sm = summarise(D, a.boot, a.seed)
    sc = D[D.pipe_total.notna()]
    C = pd.crosstab(pd.Categorical(sc.expert_total.astype(int), categories=range(5)),
                    pd.Categorical(sc.pipe_total.astype(int), categories=range(5)), rownames=["expert"], colnames=["pipeline"], dropna=False)
    Rt = results_table(D)
    P.to_csv(f"{out}_patients.csv", index=False); Sm.to_csv(f"{out}_summary.csv", index=False); C.to_csv(f"{out}_confusion_total.csv")
    Rt.to_csv(f"{out}_results.csv", index=False)
    try:
        import openpyxl  # noqa: F401
        with pd.ExcelWriter(f"{out}.xlsx") as w:
            Rt.to_excel(w, sheet_name="results", index=False)
            P.to_excel(w, sheet_name="patients", index=False); Sm.to_excel(w, sheet_name="summary", index=False)
            C.to_excel(w, sheet_name="confusion_total")
        xl = f" and {out}.xlsx"
    except ImportError:
        xl = " (for one .xlsx workbook: conda install -n css -c conda-forge openpyxl)"
    miss = D[D.pipe_total.isna()].study_id.tolist()
    t = Sm.iloc[0]
    print(f"compare_grades: {len(D)} patients with expert grades, {len(sc)} with a pipeline score"
          + (f"; NO pipeline score: {', '.join(miss)}" if miss else ""))
    if len(sc):
        print(f"  total 0-4: exact {t.exact_agreement:.0%}, within 1 {t.within_1:.0%}, weighted kappa {t.kappa_quadratic} "
              f"{t.kappa_quadratic_ci95}, mean difference {t.mean_diff_pipeline_minus_expert:+.2f} "
              f"(LoA {t.loa95_low} to {t.loa95_high})")
        for _, r in Sm.iloc[1:3].iterrows():
            print(f"  {r.scale:5s} 0-2: exact {r.exact_agreement:.0%}, weighted kappa {r.kappa_quadratic} {r.kappa_quadratic_ci95}")
        for _, r in Sm.iloc[3:].iterrows():
            print(f"  {r.scale}: sensitivity {r.sensitivity}, specificity {r.specificity} (TP {r.tp} FN {r.fn} TN {r.tn} FP {r.fp})")
    fl = P[P["flags"] != ""]
    for _, r in fl.iterrows(): print(f"  {r.study_id}: {r['flags']}")
    print(f"-> {out}_results.csv, _patients.csv, _summary.csv, _confusion_total.csv{xl}   [research software; n = {len(sc)}: read the intervals]")
