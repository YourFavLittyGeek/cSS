#!/usr/bin/env python3
"""Independent evaluation of a FROZEN confidence model. Research software; expert review required. Not a validation of clinical accuracy.
usage: eval_confidence.py M12,M13,...  [--reads ST,ML]  [--grades review/radiologist_grades.csv]
READ-ONLY: nothing is fitted, no list, call or model is changed. Refuses any study the model was fitted on (model["studies"]).
For each study it reads the detection as it is (review/ID_candidates.csv + ID_excluded.csv, made by detect_css.py with the model present) and reports, for
the objects the other rules keep (shown + those excluded as "low confidence"):
  - how many lie below the model's cut, split by the readers' calls (when read) and by the radiologist's grade of that hemisphere (when a grades file exists)
  - per hemisphere: objects called cSS that would remain after the cut
The reference here is reader calls and patient-level grades, not expert lesion labels: this measures what the cut removes, not sensitivity.
Studies listed in review/evaluation_studies.txt with a note (e.g. "M12,examined 2026-11") are reported with that note: a set that has been looked at is no
longer an untouched test set. Writes review/confidence_eval.csv and confidence_eval_summary.txt."""
import sys, os, json, numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from css_common import base as _base
import css_confidence as cc, probe_common as pc

B = _base(); a = sys.argv[1:]
if not a or a[0].startswith("-"): sys.exit(__doc__)
ids = [s for s in a[0].split(",") if s]
reads = (a[a.index("--reads") + 1] if "--reads" in a else "ST,ML").split(",")
gp = a[a.index("--grades") + 1] if "--grades" in a else f"{B}/review/radiologist_grades.csv"
mp = f"{B}/review/confidence_model.json"
if not os.path.exists(mp): sys.exit("no review/confidence_model.json - fit one on the development studies first (fit_confidence.py)")
model = cc.load(mp); fit = {str(s) for s in model.get("studies", [])}
if fit & set(ids): sys.exit(f"STOP: {sorted(fit & set(ids))} were used to fit this model - they cannot be evaluation studies.")
cut = float(model.get("cut_pct", 0)); notes = {}
evp = f"{B}/review/evaluation_studies.txt"
if os.path.exists(evp):
    for l in open(evp):
        if l.strip() and not l.startswith("#"): k, _, n = l.strip().partition(","); notes[k.strip()] = n.strip()
grades = {}
if os.path.exists(gp):
    g = pd.read_csv(gp)
    for _, r in g.iterrows():
        for h in ("R", "L"):
            if h in g.columns and pd.notna(r[h]): grades[(str(r.study_id), h)] = int(r[h])
rows = []
for sid in ids:
    cp, xp, lp, xl = (f"{B}/review/{sid}_{n}" for n in ("candidates.csv", "excluded.csv", "candidates.nii.gz", "excluded.nii.gz"))
    if not os.path.exists(cp): print(f"{sid}: no candidates - skipped"); continue
    c = pd.read_csv(cp); x = pd.read_csv(xp) if os.path.exists(xp) else pd.DataFrame()
    if "confidence_pct" not in c.columns: print(f"{sid}: the list has no confidence_pct (detected without the model) - skipped"); continue
    cl = pc.object_calls(B, sid, "shown", pc.lab(lp), reads, c)
    for _, r in c.iterrows():
        rows.append(dict(study_id=sid, fate="shown", obj_id=int(r.cand_id), hemi=r.hemi, region=str(r.region), volume_mm3=float(r.volume_mm3),
                         confidence_pct=cc.confidence(model, pd.DataFrame([r]))[0], **pc.summarize(cl.get(int(r.cand_id), []))))
    if len(x) and "reason" in x.columns:
        lo = x[x.reason.astype(str).str.startswith("low confidence")]
        cx = pc.object_calls(B, sid, "excluded", pc.lab(xl), reads) if len(lo) and os.path.exists(xl) else {}
        for _, r in lo.iterrows():
            rows.append(dict(study_id=sid, fate="excluded_low_confidence", obj_id=int(r.excl_id), hemi=r.hemi, region=str(r.region), volume_mm3=float(r.volume_mm3),
                             confidence_pct=cc.confidence(model, pd.DataFrame([r]))[0], **pc.summarize(cx.get(int(r.excl_id), []))))
if not rows: sys.exit("nothing to evaluate")
d = pd.DataFrame(rows); d["below_cut"] = (d.confidence_pct < cut).astype(int)
d["rad_side"] = [grades.get((s, h), np.nan) for s, h in zip(d.study_id, d.hemi)]
d["group"] = np.where(d.css_any == 1, "called cSS", np.where(d.non_css == 1, "called not cSS", "not read"))
d.to_csv(f"{B}/review/confidence_eval.csv", index=False)
out = ["Evaluation of a frozen confidence model (research software; reader calls and patient grades are the reference, not expert lesion labels)",
       f"model: cut {cut:g} % ({model.get('cut_method', 'cut method not recorded')}), fitted on {', '.join(sorted(fit)) or '?'}",
       f"evaluation studies: {', '.join(ids)}   reads: {', '.join(reads)}", ""]
for s in ids:
    if notes.get(s): out.append(f"NOTE {s}: {notes[s]} - not an untouched test study")
out += ["", "objects the other rules keep, by reader call and position against the cut:", pd.crosstab(d.group, d.below_cut.map({0: "at or above cut", 1: "below cut"}), margins=True).to_string(), ""]
css = d[d.css_any == 1]
out.append(f"objects called cSS below the cut: {int(css.below_cut.sum())} of {len(css)}" + ("" if not len(css) else f"; of these in a radiologist-positive hemisphere: {int((css.below_cut.eq(1) & (css.rad_side > 0)).sum())}"))
non = d[d.non_css == 1]; out.append(f"objects called not cSS below the cut: {int(non.below_cut.sum())} of {len(non)}"); out.append("")
out.append("per hemisphere: radiologist grade | objects called cSS | of them at or above the cut (a positive side that drops to 0 would change the patient score)")
for (s, h), g in d.groupby(["study_id", "hemi"]):
    n = int((g.css_any == 1).sum()); k = int(((g.css_any == 1) & (g.below_cut == 0)).sum()); rg = grades.get((s, h), "?")
    out.append(f"   {s} {h}: grade {rg} | cSS called {n} | remain {k}" + ("   <-- side emptied by the cut" if n > 0 and k == 0 else ""))
if len(css[css.below_cut == 1]):
    out += ["", "objects called cSS that lie below the cut:", css[css.below_cut == 1][["study_id", "fate", "obj_id", "hemi", "region", "volume_mm3", "confidence_pct", "rad_side", "calls"]].to_string(index=False)]
out.append("\nNothing was changed.")
open(f"{B}/review/confidence_eval_summary.txt", "w").write("\n".join(out) + "\n"); print("\n".join(out))
