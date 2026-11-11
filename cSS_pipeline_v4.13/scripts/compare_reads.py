#!/usr/bin/env python3
"""Your first read vs the redo, object by object. Research software; expert review required.
usage: compare_reads.py M02,M03,...  [--reviewer Redo_v53] [--old-dir DIR]
READ-ONLY. For every candidate you called in the FIRST read (old calls + the candidate list saved before redetect), it follows
the object into the NEW detection (shown / merged with another / excluded by a rule / gone) and compares your old call with
your call in the redo (ID_calls_<reviewer>.csv). It also lists new objects that had no old call.
Inputs per study (all in $CSS_BASE/review):
  old calls               <old-dir>/ID_calls.csv   (default old-dir = review/old_calls_before_redo, else review/changes/ID_before_calls.csv)
  old candidates          changes/ID_before_candidates.csv + .nii.gz   (v53_change_report.py snapshot, made before redetect)
  new candidates/excluded ID_candidates.*, ID_excluded.*;  new calls ID_calls_<reviewer>.csv
Writes review/compare_reads.csv (one row per old call + per new-only object) and compare_reads_summary.txt:
per study the old and new scores, what happened to every old call, agreement of the kept one-to-one pairs (exact class,
cSS vs not, kappa) and the list of changed calls to look at again."""
import sys, os, re, json, glob, numpy as np, pandas as pd, nibabel as nib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from css_common import base as _base, match_calls, cohen_kappa
from review_web import ai_opinion

B = _base(); a = sys.argv[1:]
if not a or a[0].startswith("-"): sys.exit(__doc__)
ids = [s for s in a[0].split(",") if s]
rev = a[a.index("--reviewer") + 1] if "--reviewer" in a else "Redo_v53"
odir = a[a.index("--old-dir") + 1] if "--old-dir" in a else f"{B}/review/old_calls_before_redo"
slug = re.sub(r"[^A-Za-z0-9]+", "_", rev.strip()).strip("_") or "reviewer"    # same as review_web.py
CH = f"{B}/review/changes"


def lab(p): return np.asanyarray(nib.load(p).dataobj).astype(np.int32)


def score(p):
    try: j = json.load(open(p)); return f"{j['multifocality_0_4']}/4 (R {j['R_score']}, L {j['L_score']})"
    except Exception: return "n/a"


CNT = {}


def calls_on(cand, path):
    """{cand_id: (call, comment)} matched to `cand` by fingerprint"""
    if not os.path.exists(path): return None
    c = pd.read_csv(path); m, _ = match_calls(cand, c)
    if m is None: return None
    CNT[path] = (len(c), len(m))
    return {int(cid): (call if isinstance(call, str) else "", "") for cid, call in m.items()}


rows, text = [], ["Your first read vs the redo (research software; expert review required)", f"redo reviewer: {rev}", ""]
tot = dict(old=0, kept=0, excl=0, gone=0, css_lost=0)
pairs_exact, pairs_bin, pairs_band = [], [], []
for sid in ids:
    need = [f"{CH}/{sid}_before_candidates.csv", f"{CH}/{sid}_before_candidates.nii.gz", f"{B}/review/{sid}_candidates.csv",
            f"{B}/review/{sid}_candidates.nii.gz"]
    if any(not os.path.exists(p) for p in need):
        text.append(f"{sid}: missing {[os.path.basename(p) for p in need if not os.path.exists(p)]} - skipped"); continue
    oc, nc = pd.read_csv(need[0]), pd.read_csv(need[2])
    op = next((p for p in (f"{odir}/{sid}_calls.csv", f"{CH}/{sid}_before_calls.csv") if os.path.exists(p)), None)
    nps = f"{B}/review/{sid}_calls_{slug}.csv"
    if op is None or not os.path.exists(nps): text.append(f"{sid}: old calls ({op}) or redo calls ({nps}) not found - skipped"); continue
    old, new = calls_on(oc, op), calls_on(nc, nps)
    band = {int(r.cand_id): (ai_opinion(r)["band"], ai_opinion(r)["score"]) for _, r in nc.iterrows()}
    if not old or new is None: text.append(f"{sid}: calls files have no fingerprint columns - skipped"); continue
    nl, xl = lab(need[3]), lab(f"{B}/review/{sid}_excluded.nii.gz")
    ol = lab(need[1]); xc = pd.read_csv(f"{B}/review/{sid}_excluded.csv")
    why = dict(zip(xc.excl_id, xc.reason)) if len(xc) and "excl_id" in xc.columns else {}
    reg = dict(zip(oc.cand_id, oc.region)); vol = dict(zip(oc.cand_id, oc.volume_mm3)); nreg = dict(zip(nc.cand_id, nc.region))
    info = {}
    for cid in oc.cand_id.astype(int):
        m = ol == cid; n = int(m.sum())
        if not n: info[cid] = ("gone", 0, ""); continue
        nb, xb = np.bincount(nl[m]), np.bincount(xl[m]); n_new, n_x = n - int(nb[0]), n - int(xb[0])
        if n_new >= max(3, 0.1 * n): info[cid] = ("kept", int(np.argmax(nb[1:]) + 1), "")
        elif n_x >= max(3, 0.1 * n): info[cid] = ("excluded", int(np.argmax(xb[1:]) + 1), str(why.get(int(np.argmax(xb[1:]) + 1), "?")).split(" (")[0].split(":")[0])
        else: info[cid] = ("gone", 0, "")
    inv = {}
    for cid, (f, nid, _) in info.items():
        if f == "kept": inv.setdefault(nid, []).append(cid)
    seen_new = set(); loc = []
    for cid, (oc_call, _) in sorted(old.items()):
        f, nid, rule = info.get(cid, ("gone", 0, ""))
        merged = f == "kept" and len(inv.get(nid, [])) > 1
        ncall = new.get(nid, ("", ""))[0] if f == "kept" else ""
        if f == "kept": seen_new.add(nid)
        if f == "kept" and not merged:
            pairs_exact.append((oc_call, ncall)); pairs_bin.append((oc_call == "cSS", ncall == "cSS")); pairs_band.append(band.get(nid, ("", ""))[0])
        if f == "excluded": outcome = "cSS LOST to rule" if oc_call == "cSS" else "removed by rule"
        elif f == "gone": outcome = "cSS LOST (gone)" if oc_call == "cSS" else "gone"
        elif merged: outcome = "merged: " + ("same" if (oc_call == "cSS") == (ncall == "cSS") else "cSS-status differs")
        else: outcome = "same" if oc_call == ncall else ("cSS -> not cSS" if oc_call == "cSS" else "not cSS -> cSS" if ncall == "cSS" else f"{oc_call} -> {ncall}")
        rows.append(dict(study=sid, old_id=cid, old_call=oc_call, region=str(reg.get(cid, "")).replace("ctx-lh-", "").replace("ctx-rh-", ""),
                         volume_mm3=round(float(vol.get(cid, 0)), 0), fate=f, rule=rule, new_id=nid or "", merged_with_old=("+".join(str(x) for x in inv.get(nid, []) if x != cid) if merged else ""),
                         new_call=ncall, outcome=outcome, ai_meter=band.get(nid, ("", ""))[1] if f == "kept" else "", ai_band=band.get(nid, ("", ""))[0] if f == "kept" else ""))
        tot["old"] += 1; tot[{"kept": "kept", "excluded": "excl", "gone": "gone"}[f]] += 1
        if outcome.startswith("cSS LOST"): tot["css_lost"] += 1
    for nid, (ncall, _) in sorted(new.items()):
        if nid in seen_new or nid not in set(nc.cand_id.astype(int)): continue
        rows.append(dict(study=sid, old_id="", old_call="", region=str(nreg.get(nid, "")).replace("ctx-lh-", "").replace("ctx-rh-", ""), volume_mm3=round(float(nc[nc.cand_id == nid].volume_mm3.iloc[0]), 0),
                         fate="new object", rule="", new_id=nid, merged_with_old="", new_call=ncall, outcome="new, no old call", ai_meter=band.get(nid, ("", ""))[1], ai_band=band.get(nid, ("", ""))[0]))
    d = pd.DataFrame([r for r in rows if r["study"] == sid])
    text += [f"=== {sid} ===", f"score: first read {score(f'{odir}/{sid}_score.json')}  ->  redo {score(f'{B}/review/{sid}_score.json')}",
             f"old calls {len(old)} (cSS {sum(1 for v in old.values() if v[0] == 'cSS')}) -> new calls {len(new)} (cSS {sum(1 for v in new.values() if v[0] == 'cSS')}); "
             f"old candidates {len(oc)} -> {len(nc)}",
             f"old calls in the file {CNT[op][0]}, matched to the old candidate list {CNT[op][1]}" + ("   <-- unmatched old calls: this study is NOT a clean comparison" if CNT[op][1] < CNT[op][0] else ""), "what happened to the old calls:"]
    text.append(d[d.old_id != ""].groupby(["old_call", "outcome"]).size().rename("n").reset_index().to_string(index=False) if len(d[d.old_id != ""]) else "   none")
    ch = d[d.outcome.str.contains("->|LOST|differs|new, no old call") & ~((d.outcome == "new, no old call") & (d.new_call != "cSS"))]
    text.append("to look at again (cSS lost, call changed, new cSS):")
    text.append(ch[["old_id", "old_call", "region", "volume_mm3", "fate", "rule", "new_id", "new_call", "ai_meter", "ai_band", "outcome"]].to_string(index=False) if len(ch) else "   none"); text.append("")
if not rows: sys.exit("\n".join(text) + "\nnothing compared")
out = pd.DataFrame(rows); out.to_csv(f"{B}/review/compare_reads.csv", index=False)
ex = [x for x, y in pairs_exact]; ey = [y for x, y in pairs_exact]
text += ["=== all studies ===", f"old calls {tot['old']}: kept {tot['kept']}, excluded by a rule {tot['excl']}, gone {tot['gone']}; cSS calls lost {tot['css_lost']}"]
if pairs_exact:
    bx, by = [int(x) for x, y in pairs_bin], [int(y) for x, y in pairs_bin]
    text += [f"one-to-one pairs (kept, not merged): {len(pairs_exact)}", f"   exact same class {100 * np.mean([x == y for x, y in pairs_exact]):.0f} %",
             f"   cSS vs not-cSS agreement {100 * np.mean([x == y for x, y in zip(bx, by)]):.0f} %, kappa {cohen_kappa(bx, by, [0, 1]):.2f}",
             "   (kappa near 1 = you read the same way twice; the changes listed above are your intra-rater variability or the viewer's effect)",
             "   old class (rows) x new class (columns):", pd.crosstab(pd.Series(ex, name="old"), pd.Series(ey, name="new")).to_string(), "",
             "cSS-status of the one-to-one pairs by the AI meter band of the object (the meter was visible in the redo; if the flips follow the band, the meter may have anchored you):"]
    dirn = pd.Series(["cSS -> not cSS" if x and not y else "not cSS -> cSS" if y and not x else "cSS both" if x else "not cSS both" for x, y in pairs_bin], name="direction")
    text.append(pd.crosstab(dirn, pd.Series(pairs_band, name="AI band (redo)")).to_string())
open(f"{B}/review/compare_reads_summary.txt", "w").write("\n".join(text) + "\n"); print("\n".join(text))
print(f"\nwrote {B}/review/compare_reads.csv and compare_reads_summary.txt")
