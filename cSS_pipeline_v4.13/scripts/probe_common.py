"""Shared helpers of the read-only probes (zone_probe.py, shape_probe.py): calls per object from several reads, the adjudication file.
Research software; expert review required.

object_calls(B, sid, fate, tab, L, reads, cand)  -> {object id: ["read:call", ...]}
    shown objects: ID_calls_<read>.csv matched by fingerprint (studies with none of the named reads: the shared ID_calls.csv of the first
    read); excluded objects: ID_excluded_audit_<read>.csv; both: the pre-redetect snapshot (review/changes, old calls mapped by overlap)
summarize(list) -> dict(calls, n_calls, n_css, css_any, css_all, non_css)
apply_adjudication(df, B) -> df with the final decisions of review/adjudication.csv applied (columns study_id, fate, obj_id, call [, note]);
    an adjudicated object has calls "ADJ:<call>" and ONLY that decision counts (it replaces the individual reads)
"""
import os, re
import numpy as np, pandas as pd, nibabel as nib
from css_common import match_calls

slug = lambda s: re.sub(r"[^A-Za-z0-9]+", "_", s.strip()).strip("_") or "reviewer"


def lab(p): return np.asanyarray(nib.load(p).dataobj).astype(np.int32)


def old_calls_onto(B, sid, new_lab):
    CH = f"{B}/review/changes"
    pc, pl, pk = f"{CH}/{sid}_before_candidates.csv", f"{CH}/{sid}_before_candidates.nii.gz", f"{CH}/{sid}_before_calls.csv"
    pk = pk if os.path.exists(pk) else f"{B}/review/old_calls_before_redo/{sid}_calls.csv"
    if not (os.path.exists(pc) and os.path.exists(pl) and os.path.exists(pk)): return {}
    oc, calls = pd.read_csv(pc), pd.read_csv(pk); m, _ = match_calls(oc, calls)
    if not m: return {}
    old = lab(pl); out = {}
    for cid, call in m.items():
        if not isinstance(call, str) or not call: continue
        v = new_lab[old == cid]; v = v[v > 0]
        for l in np.unique(v):
            if (v == l).sum() >= max(3, 0.1 * (old == cid).sum()): out.setdefault(int(l), []).append("first:" + call)
    return out


def object_calls(B, sid, fate, L, reads, cand=None):
    out = {}
    if fate == "shown":
        have = False
        for rd in reads:
            f = f"{B}/review/{sid}_calls_{slug(rd)}.csv"
            if os.path.exists(f):
                have = True; m, _ = match_calls(cand, pd.read_csv(f))
                for k, v in (m or {}).items():
                    if isinstance(v, str) and v: out.setdefault(int(k), []).append(f"{rd}:{v}")
        if not have:
            for f in (f"{B}/review/{sid}_calls.csv", f"{B}/review/old_calls_before_redo/{sid}_calls.csv"):
                if os.path.exists(f):
                    m, _ = match_calls(cand, pd.read_csv(f))
                    for k, v in (m or {}).items():
                        if isinstance(v, str) and v: out.setdefault(int(k), []).append(f"shared:{v}")
                    break
    else:
        for rd in reads:
            f = f"{B}/review/{sid}_excluded_audit_{slug(rd)}.csv"
            if os.path.exists(f):
                for _, r in pd.read_csv(f).iterrows():
                    if isinstance(r.call, str) and r.call: out.setdefault(int(r.excl_id), []).append(f"{rd}:{r.call}")
    for k, v in old_calls_onto(B, sid, L).items(): out.setdefault(k, []).extend(v)
    return out


def summarize(cl):
    names = [c.split(":", 1)[1] for c in cl]; n_css = sum(1 for c in names if c == "cSS")
    return dict(calls=" | ".join(cl), n_calls=len(names), n_css=n_css, css_any=int(n_css > 0),
                css_all=int(len(names) > 0 and n_css == len(names)), non_css=int(len(names) > 0 and n_css == 0))


def apply_adjudication(df, B):
    p = f"{B}/review/adjudication.csv"
    if not os.path.exists(p): return df
    a = pd.read_csv(p); df = df.copy(); n = 0
    for _, r in a.iterrows():
        m = (df.study_id == r.study_id) & (df.fate == r.fate) & (df.obj_id == int(r.obj_id))
        if not m.any(): continue
        css = str(r.call).strip() == "cSS"
        df.loc[m, "calls"] = f"ADJ:{r.call}"; df.loc[m, "n_calls"] = 1; df.loc[m, "n_css"] = int(css)
        df.loc[m, "css_any"] = int(css); df.loc[m, "css_all"] = int(css); df.loc[m, "non_css"] = int(not css); n += 1
    print(f"adjudication: {n} of {len(a)} decisions applied ({p})")
    return df
