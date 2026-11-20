#!/usr/bin/env python3
"""Carry the reader's earlier calls over to the candidates of a new detection. Research software; expert review required.
usage: inherit_calls.py M02,M03,... [--reviewer "NAME"] [--dry-run]
Run AFTER  v53_change_report.py snapshot ...  +  redetect.py ... --v53  +  v53_change_report.py after ...
For every new candidate it looks at the OLD candidates that became it (same dark object; review/changes/ID_old_candidates_fate.csv):
  - all old calls on it are the same            -> that call is written, marked  "[inherited from old #7,#8: cSS - press the key to confirm]"
  - the old calls disagree (e.g. cSS + Near ICH)-> NO call; a hint "[old calls: cSS #2, cSS #5, Near ICH #11 - please read]" is written
  - no old call (new object)                    -> nothing
Calls you already made on the new list are never overwritten. In the reviewer, inherited calls are drawn dashed and count as
"not yet confirmed": pressing the same decision key confirms (removes the marker), another key changes it; J / auto-next stop on
them; the final window warns about unconfirmed ones. The detector's own AI meter is not involved. Files written: review/ID_calls_<reviewer>.csv
(+ the old-format ID_calls.csv and a log line per inherited call). Before it writes, the current files are copied to review/changes/."""
import sys, os, shutil, numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from css_common import base as _base, save_calls, FP
from review_web import slug, now, reviewers

B = _base(); CH = f"{B}/review/changes"


def existing(sid, rev, new):
    """calls already on the new list (reviewer file), matched by fingerprint -> {cand_id: (call, comment)}"""
    p = f"{B}/review/{sid}_calls_{slug(rev)}.csv"
    if not os.path.exists(p): return {}
    c = pd.read_csv(p)
    if not len(c) or not all(k in c.columns for k in FP): return {}
    C = new[["cand_id"] + FP].to_numpy(float); out = {}
    for _, r in c.iterrows():
        d = np.sqrt(((C[:, 1:4] - r[FP[:3]].to_numpy(float)) ** 2).sum(1)); dv = np.abs(C[:, 4] - float(r.volume_mm3)) / max(float(r.volume_mm3), 1.0)
        ok = np.where((d <= 2.0) & (dv <= 0.15))[0]
        if len(ok):
            cm = r.get("comment", ""); cl = r.get("call", "")
            out[int(C[ok[d[ok].argmin()], 0])] = (cl if isinstance(cl, str) else "", cm if isinstance(cm, str) else "")
    return out


def run(sid, rev, dry):
    fp = f"{CH}/{sid}_old_candidates_fate.csv"
    if not os.path.exists(fp): return f"{sid}: no change report - run v53_change_report.py after {sid} first", None
    old = pd.read_csv(fp); new = pd.read_csv(f"{B}/review/{sid}_candidates.csv"); ex = existing(sid, rev, new)
    rows, inh, mixed, keep = {}, 0, 0, 0
    for nid, g in old[old.fate == "kept"].groupby("new_id"):
        nid = int(nid)
        if nid in ex and (ex[nid][0] or ex[nid][1]): continue                       # already handled on the new list
        g = g[g.call.fillna("") != ""]
        if not len(g): continue
        calls = sorted(set(g.call))
        if len(calls) == 1:
            ids = ",".join(f"#{int(i)}" for i in g.cand_id)
            rows[nid] = (calls[0], f"[inherited from old {ids}: {calls[0]} - press the key to confirm]"); inh += 1
        else:
            rows[nid] = ("", "[old calls: " + ", ".join(f"{r.call} #{int(r.cand_id)}" for r in g.itertuples()) + " - please read]"); mixed += 1
    for nid, (cl, cm) in ex.items():
        if cl or cm: rows[nid] = (cl, cm); keep += 1                               # keep what is already there
    msg = f"{sid}: {inh} calls inherited, {mixed} candidates with conflicting old calls (hint only), {keep} existing calls kept, {len(new) - len(rows)} candidates without any old call"
    if dry: return msg + " [dry run]", None
    os.makedirs(CH, exist_ok=True)
    for f in (f"{B}/review/{sid}_calls_{slug(rev)}.csv", f"{B}/review/{sid}_calls.csv"):
        if os.path.exists(f): shutil.copy2(f, f"{CH}/{sid}_precalls_{os.path.basename(f)}")
    c = new.set_index("cand_id"); t = now()
    out = [dict(cand_id=k, call=v[0], comment=v[1], reviewer=rev, time=t if v[0] else "", **{f: c.loc[k, f] for f in FP}) for k, v in sorted(rows.items())]
    pd.DataFrame(out, columns=["cand_id", "call", "comment", "reviewer", "time"] + FP).to_csv(f"{B}/review/{sid}_calls_{slug(rev)}.csv", index=False)
    save_calls(B, sid, new, {k: v[0] for k, v in rows.items() if v[0]})
    lp = f"{B}/review/{sid}_review_log.csv"; newlog = not os.path.exists(lp); q = lambda s: '"' + str(s).replace('"', "'") + '"'
    with open(lp, "a") as f:
        if newlog: f.write("time,reviewer,action,cand_id,call,comment,meter_shown,vox_i,vox_j,vox_k,volume_mm3\n")
        for k, v in sorted(rows.items()):
            if v[1].startswith("[inherited") or v[1].startswith("[old calls"):
                f.write(",".join([t, q(rev), "inherit", str(k), q(v[0]), q(v[1]), ""] + [str(c.loc[k, x]) for x in FP]) + "\n")
    return msg, dict(study=sid, inherited=inh, conflicts=mixed, kept=keep)


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0].startswith("-"): sys.exit(__doc__)
    rev = a[a.index("--reviewer") + 1] if "--reviewer" in a else reviewers().get("last", "")
    if not rev: sys.exit("no reviewer name: use --reviewer \"NAME\" (the name you type in the reviewer's upper right box)")
    print(f"reviewer: {rev}")
    for sid in [s for s in a[0].split(",") if s]:
        print(run(sid, rev, "--dry-run" in a)[0])
    print("\nnow: review_web.py " + a[0] + "   (inherited calls are dashed; J jumps to the next unconfirmed one)")
