#!/usr/bin/env python3
"""Fit the cSS confidence model on the read studies. Research software; expert review required. The result is NOT a validated probability.
usage: fit_confidence.py M02,M03,...  [--reads ST,ML,Redo_v53]  [--grades review/radiologist_grades.csv]  [--margin 0.10]  [--dry-run]
Needs the lists of a detection made with v5.10+ (columns struct_*, dark_*, minip_*): run redetect.py first.
Labels of the SHOWN objects:
  cSS (protected)   any of the reads (or review/adjudication.csv, which replaces them) called it cSS
  not cSS           read and never called cSS;  AND every object in a hemisphere the radiologist graded 0 (grades file: study_id,R,L) - the radiologist
                    overrules a reader's cSS call there
  unread objects elsewhere are left out.
Reports: leave-one-PATIENT-out AUC of the model against the detector's score_v4 on the same objects, the weight of each evidence domain, and the cut:
  cut = (1 - margin) x the lowest confidence of a protected cSS, taking the LOWER of the final model and the leave-one-patient-out prediction (each patient
  scored by a model that never saw that patient). v5.10.2: this is the default because the final-model cut alone lost 6 of 54 cSS in the leave-one-patient-out
  check on M02-M11. --cut-insample restores the old, optimistic cut; --cut X sets it by hand (percent). Objects below the cut are excluded (E30, CSS_CONF=1).
Development vs evaluation (Phase 1): studies listed in review/evaluation_studies.txt (one study id per line, optional ",note") are EVALUATION studies. They may
never be fitted on: the script stops if any of them is given. The model file records the fit studies, the cut and how the cut was set (cut_method: lopo_min /
insample_min / manual); detect_css.py applies the exclusion only for lopo_min unless CSS_CONF_ALLOW_OPTIMISTIC=1. eval_confidence.py reports a frozen model on
evaluation studies without changing anything.
Writes review/confidence_model.json (unless --dry-run), review/confidence_fit.csv and confidence_fit_summary.txt. The project's lists and calls are not changed."""
import sys, os, json, numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from css_common import base as _base
import css_confidence as cc, css_model as cm, probe_common as pc

B = _base(); a = sys.argv[1:]
if not a or a[0].startswith("-"): sys.exit(__doc__)
ids = [s for s in a[0].split(",") if s]
reads = (a[a.index("--reads") + 1] if "--reads" in a else "ST,ML,Redo_v53,Blind_v57").split(",")
gp = a[a.index("--grades") + 1] if "--grades" in a else f"{B}/review/radiologist_grades.csv"
margin = float(a[a.index("--margin") + 1]) if "--margin" in a else 0.10
_evp = f"{B}/review/evaluation_studies.txt"
EVAL = {l.split(",")[0].strip() for l in open(_evp) if l.strip() and not l.startswith("#")} if os.path.exists(_evp) else set()
if EVAL & set(ids): sys.exit(f"STOP: {sorted(EVAL & set(ids))} are evaluation studies ({_evp}) and may not be used to fit or calibrate the model.")
neg_h = set()
if os.path.exists(gp):
    g = pd.read_csv(gp)
    for _, r in g.iterrows():
        for h in ("R", "L"):
            if h in g.columns and pd.notna(r[h]) and float(r[h]) == 0: neg_h.add((str(r.study_id), h))
rows = []
for sid in ids:
    cp, lp = f"{B}/review/{sid}_candidates.csv", f"{B}/review/{sid}_candidates.nii.gz"
    if not (os.path.exists(cp) and os.path.exists(lp)): print(f"{sid}: no candidates - skipped"); continue
    c = pd.read_csv(cp)
    if "struct_cls" not in c.columns or "minip_cont" not in c.columns: sys.exit(f"{sid}: the candidate list has no struct_* / minip_* columns - redetect with v5.10+ first (redetect.py {sid} --v53)")
    cl = pc.object_calls(B, sid, "shown", pc.lab(lp), reads, c)
    for _, r in c.iterrows():
        rows.append(dict(r, study_id=sid, fate="shown", obj_id=int(r.cand_id), **pc.summarize(cl.get(int(r.cand_id), []))))
if not rows: sys.exit("nothing to fit")
d = pc.apply_adjudication(pd.DataFrame(rows), B)
d["gold_neg"] = [(s, h) in neg_h for s, h in zip(d.study_id, d.hemi)]
d["y"] = np.where(d.gold_neg, 0, np.where(d.css_any == 1, 1, np.where(d.non_css == 1, 0, -1)))
t = d[d.y >= 0].reset_index(drop=True)
out = ["cSS confidence model fit (research software; expert review required; NOT a validated probability)", f"studies: {', '.join(ids)}   reads: {', '.join(reads)}",
       f"radiologist-negative hemispheres used as certain negatives: {sorted(neg_h) if neg_h else 'none (no grades file)'}",
       f"objects: {len(d)} shown, {len(t)} labelled (cSS {int((t.y == 1).sum())}, not cSS {int((t.y == 0).sum())}; reader cSS calls overruled by the radiologist: {int((d.gold_neg & (d.css_any == 1)).sum())}), patients {t.study_id.nunique()}", ""]
if (t.y == 1).sum() < 8 or (t.y == 0).sum() < 8 or t.study_id.nunique() < 3: sys.exit("\n".join(out) + "\ntoo few labelled objects or patients to fit (needs >= 8 per class, >= 3 patients)")
X = cc.table(t).to_numpy(float); y = t.y.to_numpy(int)
oof, log = cm.lopo(X, y, t.study_id.to_numpy(), nested=True); ok = np.isfinite(oof)
l2s = [l["l2"] for l in log if l.get("status") == "evaluated"]; l2 = max(set(l2s), key=l2s.count) if l2s else 1.0
model = cc.fit(t, y, l2); t["confidence_pct"] = cc.confidence(model, t); t["confidence_lopo_pct"] = np.round(100 * oof, 1)
base_s = pd.to_numeric(t.get("score_v4", pd.Series(np.nan, index=t.index)), errors="coerce").to_numpy()
out += [f"leave-one-patient-out AUC (cSS vs not): model {cm.auc(y[ok], oof[ok]):.2f}   detector score_v4 {cm.auc(y[ok & np.isfinite(base_s)], base_s[ok & np.isfinite(base_s)]):.2f}   (same objects; in-sample model AUC {cm.auc(y, t.confidence_pct.to_numpy()):.2f}, optimistic)",
        f"L2 strength {l2:g}; folds skipped: {[l['study_id'] for l in log if l.get('status') != 'evaluated'] or 'none'}", ""]
w = np.array(model["w"]); out.append("evidence domains (sum of |weight| of their measures; the largest single measures in brackets, + raises / - lowers the confidence):")
for dom, fs in cc.DOMAINS.items():
    ws = sorted(((f, w[cc.FEATURES.index(f)]) for f in fs), key=lambda kv: -abs(kv[1]))
    out.append(f"   {dom:<9} {sum(abs(v) for _, v in ws):5.2f}   [" + ", ".join(f"{f} {v:+.2f}" for f, v in ws[:3]) + "]")
prot = t[t.y == 1]; lo_in = float(prot.confidence_pct.min()); lo_oof = float(np.nanmin(prot.confidence_lopo_pct)); lo = lo_in if "--cut-insample" in a else min(lo_in, lo_oof)
cut = float(a[a.index("--cut") + 1]) if "--cut" in a else round((1 - margin) * lo, 1)
neg = t[t.y == 0]; unread = d[d.y < 0].copy(); unread["confidence_pct"] = cc.confidence(model, unread) if len(unread) else []
out += ["", f"lowest protected cSS confidence: final model {lo_in:.1f} %, leave-one-patient-out {lo_oof:.1f} %  ->  cut {cut:.1f} %  (margin {100 * margin:.0f} % below the {'final-model' if '--cut-insample' in a else 'lower'} value{'; set by hand' if '--cut' in a else ''})",
        f"at this cut: protected cSS excluded 0 of {len(prot)};  not-cSS excluded {int((neg.confidence_pct < cut).sum())} of {len(neg)};  unread objects excluded {int((unread.confidence_pct < cut).sum()) if len(unread) else 0} of {len(unread)}",
        f"HONEST CHECK (each patient scored by a model that never saw that patient): protected cSS below the cut {int((prot.confidence_lopo_pct < cut).sum())} of {len(prot)};  not-cSS below the cut {int((neg.confidence_lopo_pct < cut).sum())} of {len(neg)}",
        "", "not-cSS excluded at the cut, by study:  " + str(neg[neg.confidence_pct < cut].study_id.value_counts().sort_index().to_dict()),
        "", "the 8 protected cSS with the lowest confidence (the cut sits below the first):",
        prot.sort_values("confidence_pct").head(8)[["study_id", "obj_id", "region", "volume_mm3", "struct_cls", "confidence_pct", "confidence_lopo_pct", "calls"]].to_string(index=False),
        "", "cut table (final model / leave-one-patient-out):"]
for c_ in sorted({cut, 5.0, 10.0, 15.0, 20.0, 30.0, 40.0, 50.0}):
    out.append(f"   < {c_:5.1f} %   cSS lost {int((prot.confidence_pct < c_).sum()):2d} / {int((prot.confidence_lopo_pct < c_).sum()):2d}    not-cSS removed {int((neg.confidence_pct < c_).sum()):3d} / {int((neg.confidence_lopo_pct < c_).sum()):3d}")
model.update(cut_method="manual" if "--cut" in a else ("insample_min" if "--cut-insample" in a else "lopo_min"), evaluation_studies_excluded=sorted(EVAL),
             cut_pct=cut, margin=margin, studies=ids, reads=reads, n_css=int((y == 1).sum()), n_not=int((y == 0).sum()), lopo_auc=round(float(cm.auc(y[ok], oof[ok])), 3),
             note="fitted on the listed studies; NOT a validated probability; exclusion E30 only with CSS_CONF=1")
t[["study_id", "obj_id", "hemi", "region", "volume_mm3", "calls", "gold_neg", "y", "confidence_pct", "confidence_lopo_pct"] + [f for f in ("struct_cls", "struct_cont", "minip_cont", "dark_cv") if f in t.columns]].to_csv(f"{B}/review/confidence_fit.csv", index=False)
if model["cut_method"] != "lopo_min":
    out.append(f"\nWARNING: cut_method = {model['cut_method']}: this cut was not set from leave-one-patient-out predictions. detect_css.py will NOT apply the exclusion "
               f"with this model unless CSS_CONF_ALLOW_OPTIMISTIC=1.")
if "--dry-run" not in a:
    json.dump(model, open(f"{B}/review/confidence_model.json", "w"), indent=1); out.append(f"\nwrote {B}/review/confidence_model.json (cut {cut:.1f} %). Next: acceptance test with CSS_CONF=1, then redetect.")
else: out.append("\n--dry-run: no model file written.")
open(f"{B}/review/confidence_fit_summary.txt", "w").write("\n".join(out) + "\n"); print("\n".join(out))
