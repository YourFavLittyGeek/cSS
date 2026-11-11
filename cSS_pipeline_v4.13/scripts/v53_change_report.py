#!/usr/bin/env python3
"""What did the v5.3 rules change for a patient? Research software; expert review required.
usage: v53_change_report.py snapshot M02,M03,...     (BEFORE redetect.py --v53: records the current state)
       v53_change_report.py after    M02,M03,...     (AFTER redetect.py --v53: compares with the snapshot)
Snapshot (per study) -> review/changes/ID_before.json + ID_before_candidates.{csv,nii.gz}: candidate list, the
reader's calls (matched by fingerprint), the reader's score, the AI score and the AI-vs-reader agreement.
After -> review/changes/change_report.txt / .csv, per study:
  - candidates before -> after; what happened to each old candidate: kept, merged into another, excluded by rule X, gone
  - the reader's calls: carried over (same object) / need a new read (merged, reshaped, excluded)
  - AI meter bands (green / yellow / red) before and after, and the AI score (R / L / total 0-4, category) before and after
  - the reader's score before and with the carried calls only (a lower bound until the rest is re-read)
  - agreement of the reader's carried calls with the AI before and after
The AI score = the usual scoring applied to the candidates in the rule-based meter's green band (>= 0.66); the meter is
NOT validated. Nothing here changes the reader's calls or score files (score_css.py --accept-ids --tag)."""
import sys, os, json, shutil, subprocess
import numpy as np, nibabel as nib, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from css_common import base as _base, load_calls
from review_web import ai_opinion

B = _base(); S = os.path.dirname(os.path.abspath(__file__)); CH = f"{B}/review/changes"
KEYS = ("L_score", "R_score", "multifocality_0_4", "category", "n_sulci_total", "n_lines_total")


def score_set(sid, ids, tag):
    """score a hypothetical accept set under a tag (reader files untouched) -> dict of the main score fields"""
    r = subprocess.run([sys.executable, f"{S}/score_css.py", sid, "--accept-ids", ",".join(map(str, ids)) or "none", "--tag", tag],
                       capture_output=True, text=True, env=dict(os.environ, CSS_BASE=B, PYTHONWARNINGS="ignore"))
    p = f"{B}/review/{sid}_score_{tag}.json"
    if r.returncode or not os.path.exists(p): return dict(error=(r.stderr or r.stdout)[-200:])
    j = json.load(open(p)); os.remove(p)
    return {k: j.get(k) for k in KEYS}


def table(sid):
    """current candidates with the AI band / meter and the reader's matched call"""
    df = pd.read_csv(f"{B}/review/{sid}_candidates.csv"); calls, _ = load_calls(B, sid, df)
    rows = []
    for _, r in df.iterrows():
        a = ai_opinion(r); rows.append(dict(cand_id=int(r.cand_id), hemi=r.hemi, region=str(r.region), volume_mm3=float(r.volume_mm3),
                                            band=a["band"], meter=a["score"], call=calls.get(int(r.cand_id), "")))
    return pd.DataFrame(rows)


def verdict(call, band):
    if not call: return "not read"
    if call == "Unsure" or band == "yellow": return "neither"
    css = call == "cSS"
    return "agree" if (css and band == "green") or (not css and band == "red") else "differ"


def agreement(t):
    v = [verdict(c, b) for c, b in zip(t.call, t.band)]
    return {k: v.count(k) for k in ("agree", "differ", "neither", "not read")}


def snapshot(sid):
    t = table(sid); os.makedirs(CH, exist_ok=True)
    shutil.copy2(f"{B}/review/{sid}_candidates.csv", f"{CH}/{sid}_before_candidates.csv")
    shutil.copy2(f"{B}/review/{sid}_candidates.nii.gz", f"{CH}/{sid}_before_candidates.nii.gz")
    for f in (f"{B}/review/{sid}_excluded.csv", f"{B}/review/{sid}_calls.csv"):
        if os.path.exists(f): shutil.copy2(f, f"{CH}/{sid}_before_{os.path.basename(f).split('_', 1)[1]}")
    rec = dict(study=sid, n=len(t), bands={k: int((t.band == k).sum()) for k in ("green", "yellow", "red")},
               n_read=int((t.call != "").sum()), css_ids=[int(i) for i in t[t.call == "cSS"].cand_id],
               ai=score_set(sid, [int(i) for i in t[t.band == "green"].cand_id], "chg_ai"),
               reader=score_set(sid, [int(i) for i in t[t.call == "cSS"].cand_id], "chg_reader"),
               agreement=agreement(t), table=t.to_dict("records"))
    json.dump(rec, open(f"{CH}/{sid}_before.json", "w"), indent=1)
    print(f"{sid}: snapshot saved ({len(t)} candidates, {rec['n_read']} read; AI {rec['ai'].get('multifocality_0_4')}/4, "
          f"reader {rec['reader'].get('multifocality_0_4')}/4)")


def sc(d):
    return "n/a" if not d or d.get("multifocality_0_4") is None else f"{d['multifocality_0_4']}/4 (R {d['R_score']}, L {d['L_score']}, {d['category']})"


def after(sid):
    bp = f"{CH}/{sid}_before.json"
    if not os.path.exists(bp): return None, f"{sid}: no snapshot - run: v53_change_report.py snapshot {sid} (before redetect.py --v53)"
    b = json.load(open(bp)); tb = pd.DataFrame(b["table"]); ta = table(sid)
    old = np.asanyarray(nib.load(f"{CH}/{sid}_before_candidates.nii.gz").dataobj).astype(int)
    new = np.asanyarray(nib.load(f"{B}/review/{sid}_candidates.nii.gz").dataobj).astype(int)
    exl = np.asanyarray(nib.load(f"{B}/review/{sid}_excluded.nii.gz").dataobj).astype(int)
    xc = pd.read_csv(f"{B}/review/{sid}_excluded.csv"); why = dict(zip(xc.excl_id, xc.reason)) if len(xc) and "excl_id" in xc.columns else {}
    fate, tgt = {}, {}
    for _, r in tb.iterrows():
        m = old == int(r.cand_id); n = int(m.sum())
        if not n: fate[int(r.cand_id)] = "gone"; continue
        nb, xb = np.bincount(new[m]), np.bincount(exl[m]); n_new, n_x = n - int(nb[0]), n - int(xb[0])
        if n_new >= max(3, 0.1 * n): fate[int(r.cand_id)] = "kept"; tgt[int(r.cand_id)] = int(np.argmax(nb[1:]) + 1)
        elif n_x >= max(3, 0.1 * n): fate[int(r.cand_id)] = "excluded: " + str(why.get(int(np.argmax(xb[1:]) + 1), "?")).split(" (")[0].split(":")[0]
        else: fate[int(r.cand_id)] = "gone"
    tb["fate"] = tb.cand_id.map(fate); tb["new_id"] = tb.cand_id.map(tgt)
    nold = tb[tb.fate == "kept"].groupby("new_id").cand_id.count()
    tb["merged"] = tb.new_id.map(lambda i: bool(i == i and nold.get(i, 0) > 1))
    carried = ta[ta.call != ""]; lost = tb[(tb.call != "") & ~tb.cand_id.isin([])]
    n_lost = int(b["n_read"]) - len(carried)
    css_lost = [(int(r.cand_id), r.region, r.fate) for r in tb.itertuples() if r.call == "cSS" and not (
        r.fate == "kept" and not r.merged)]
    ai_after = score_set(sid, [int(i) for i in ta[ta.band == "green"].cand_id], "chg_ai")
    reader_carried = score_set(sid, [int(i) for i in ta[ta.call == "cSS"].cand_id], "chg_reader")
    ag_b, ag_a = b["agreement"], agreement(ta)
    bands_a = {k: int((ta.band == k).sum()) for k in ("green", "yellow", "red")}
    out = [f"=== {sid} ===",
           f"candidates {b['n']} -> {len(ta)}   (old candidates: kept {int((tb.fate == 'kept').sum())} [{int(tb.merged.sum())} of them merged with another], "
           f"excluded {int(tb.fate.str.startswith('excluded').sum())}, gone {int((tb.fate == 'gone').sum())})",
           "excluded by: " + (", ".join(f"{k} {v}" for k, v in tb[tb.fate.str.startswith('excluded')].fate.str.replace("excluded: ", "").value_counts().items()) or "-"),
           f"reader calls: {b['n_read']} before -> {len(carried)} carried over unchanged, {n_lost} need a new read; {len(ta) - len(carried)} candidates unread now",
           f"  cSS calls needing a new read: " + (", ".join(f"#{i} {r.replace('ctx-', '')} ({f})" for i, r, f in css_lost) or "none"),
           f"AI meter bands green/yellow/red: {b['bands']['green']}/{b['bands']['yellow']}/{b['bands']['red']} -> {bands_a['green']}/{bands_a['yellow']}/{bands_a['red']}",
           f"AI score:     {sc(b['ai'])}  ->  {sc(ai_after)}",
           f"reader score: {sc(b['reader'])}  ->  {sc(reader_carried)} with the carried calls only (lower bound until re-read)",
           f"reader vs AI (read candidates): before agree {ag_b['agree']} / differ {ag_b['differ']}; after (carried) agree {ag_a['agree']} / differ {ag_a['differ']}; unread {ag_a['not read']}"]
    row = dict(study=sid, cand_before=b["n"], cand_after=len(ta), old_kept=int((tb.fate == "kept").sum()), old_excluded=int(tb.fate.str.startswith("excluded").sum()),
               old_gone=int((tb.fate == "gone").sum()), calls_before=b["n_read"], calls_carried=len(carried), calls_need_read=n_lost, unread_now=len(ta) - len(carried),
               css_calls_need_read=len(css_lost), ai_green_before=b["bands"]["green"], ai_green_after=bands_a["green"],
               ai_before=b["ai"].get("multifocality_0_4"), ai_after=ai_after.get("multifocality_0_4"), reader_before=b["reader"].get("multifocality_0_4"),
               reader_carried=reader_carried.get("multifocality_0_4"), agree_before=ag_b["agree"], differ_before=ag_b["differ"],
               agree_after=ag_a["agree"], differ_after=ag_a["differ"])
    tb.to_csv(f"{CH}/{sid}_old_candidates_fate.csv", index=False)
    return row, "\n".join(out)


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) < 2 or a[0] not in ("snapshot", "after"): sys.exit(__doc__)
    ids = [s for s in a[1].split(",") if s]
    if a[0] == "snapshot":
        for sid in ids:
            if not os.path.exists(f"{B}/review/{sid}_candidates.csv"): print(f"{sid}: no candidates"); continue
            snapshot(sid)
        print(f"\nnext: python {S}/redetect.py {a[1]} --v53      then: v53_change_report.py after {a[1]}")
    else:
        rows, txt = [], []
        for sid in ids:
            r, t = after(sid); txt.append(t)
            if r: rows.append(r)
            print(t + "\n")
        if rows:
            d = pd.DataFrame(rows); d.to_csv(f"{CH}/change_report.csv", index=False)
            open(f"{CH}/change_report.txt", "w").write("v5.3 change report (research software; expert review required)\n\n" + "\n\n".join(txt) + "\n")
            print(f"wrote {CH}/change_report.txt and change_report.csv\nnow read what needs a new read: python {S}/review_web.py {a[1]}")
