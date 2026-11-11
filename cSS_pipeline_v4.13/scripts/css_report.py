#!/usr/bin/env python3
"""cSS grade report for the cohort (Excel + CSV). Research software; expert review required.
usage: css_report.py [--out review/css_report]
One row per study that has a final review (review/ID_final.json, written by review_web.py when the reviewer saves):
  reviewer, date, hemisphere scores (0-2 each), total 0-4, focal / disseminated category, sulci and continuous cSS
  lines, the detector's own ("AI") score for comparison, candidates read, disagreements, missed cSS marked.
Scales (as used by score_css.py):
  Hemisphere score: 0 = no cSS; 1 = one sulcus or up to 3 immediately adjacent sulci; 2 = 2 or more non-adjacent
  sulci, or more than 3 adjacent sulci. Total = left + right (0-4).
  Category: focal = 1-3 sulci; disseminated (diffuse) = more than 3 sulci; absent = none.
The AI score is the same scoring applied to the candidates the rule-based meter puts in its green band. It is NOT
validated and is listed only for comparison. Writes <out>.csv and, when openpyxl is installed, <out>.xlsx."""
import sys, os, glob, json, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from css_common import base as _base
CAT = {"absent": "Absent", "focal": "Focal (1-3 sulci)", "disseminated": "Disseminated / diffuse (> 3 sulci)"}

def build(B, out=None):
    out = out or f"{B}/review/css_report"; rows = []
    for p in sorted(glob.glob(f"{B}/review/*_final.json")):
        try: f = json.load(open(p))
        except Exception: continue
        r, a = f.get("reviewer_score") or {}, f.get("ai_score") or {}
        g = lambda d, k: d.get(k, "")
        rows.append({"Study": f.get("study", ""), "Reviewer": f.get("reviewer", ""), "Saved": f.get("saved", ""),
                     "R cSS (0-2)": g(r, "R_score"), "L cSS (0-2)": g(r, "L_score"), "cSS score (0-4)": g(r, "multifocality_0_4"),
                     "Category": CAT.get(g(r, "category"), g(r, "category")), "Sulci involved": g(r, "n_sulci_total"),
                     "Continuous cSS lines": g(r, "n_lines_total"), "Scoring method": g(r, "scoring_method"),
                     "AI R (0-2)": g(a, "R_score"), "AI L (0-2)": g(a, "L_score"), "AI score (0-4)": g(a, "multifocality_0_4"),
                     "AI category": CAT.get(g(a, "category"), g(a, "category")),
                     "Score difference (reviewer - AI)": (r["multifocality_0_4"] - a["multifocality_0_4"])
                     if "multifocality_0_4" in r and "multifocality_0_4" in a else "",
                     "Candidates": f.get("n_candidates", ""), "Read": f.get("n_read", ""), "Called cSS": f.get("n_css", ""),
                     "Calls differing from AI": f.get("n_differ", ""), "Missed cSS marked": f.get("n_missed", ""),
                     "Calls changed after the AI comparison": f.get("n_revoted", ""), "Inherited calls not re-confirmed": f.get("n_inherited_unconfirmed", ""), "AI meter visible": f.get("meter_visible", ""),
                     "Note": "lower bound: not all candidates read" if f.get("n_read", 0) != f.get("n_candidates", 0) else ""})
    d = pd.DataFrame(rows); d.to_csv(out + ".csv", index=False); xl = ""
    try:
        import openpyxl  # noqa: F401
        legend = pd.DataFrame({"cSS grading": [
            "Hemisphere score 0: no cSS", "Hemisphere score 1: cSS in a single sulcus or up to 3 immediately adjacent sulci",
            "Hemisphere score 2: cSS in 2 or more non-adjacent sulci, or more than 3 adjacent sulci",
            "Total score 0-4 = left + right hemisphere", "Focal cSS: 1 to 3 sulci involved", "Disseminated (diffuse) cSS: more than 3 sulci involved",
            "Continuous cSS lines: accepted candidates within 6 mm of each other are counted as one line",
            "AI score: the same scoring applied to the detector's green-band candidates; rule-based, NOT validated",
            "Research software - expert review required"]})
        with pd.ExcelWriter(out + ".xlsx", engine="openpyxl") as w:
            d.to_excel(w, sheet_name="cSS grades", index=False); legend.to_excel(w, sheet_name="scales", index=False)
            ws = w.sheets["cSS grades"]
            for i, c in enumerate(d.columns, 1): ws.column_dimensions[ws.cell(1, i).column_letter].width = max(12, min(40, len(c) + 2))
            w.sheets["scales"].column_dimensions["A"].width = 100
        xl = " and .xlsx"
    except ImportError:
        xl = " (for the .xlsx: conda install -n css -c conda-forge openpyxl)"
    return out, len(d), xl

if __name__ == "__main__":
    a = sys.argv[1:]; B = _base()
    if "-h" in a or "--help" in a: sys.exit(__doc__)
    out, n, xl = build(B, a[a.index("--out") + 1] if "--out" in a else None)
    print(f"cSS report: {n} studies with a final review -> {out}.csv{xl}")
