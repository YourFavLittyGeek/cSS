#!/usr/bin/env python3
"""call_ledger.py - every reviewer's calls are kept; the EFFECTIVE call of each candidate follows a policy (default: newest).
Research software. Shared by the reviewer (review_web.py) and the app (css_app.py).

Sources (never rewritten here, except by the explicit, confirmed consolidate()):
  review/ID_calls_<reviewer>.csv   one file per reviewer (review_web.py): cand_id, call, comment, reviewer, time, vox_i/j/k, volume_mm3
  review/ID_calls.csv              only when NO per-reviewer file exists (calls made before v5.4): reviewer "(unnamed, before v5.4)"
Calls are attached to the CURRENT candidates by fingerprint (css_common.match_calls), so a detector re-run never moves a call onto a
different lesion; calls that match no current candidate are counted as stale.

Policy (review/call_policy.json, schema call-policy/1.0): rule = {"mode": "newest"} or {"mode": "reviewer", "reviewer": NAME,
"fallback": "newest" | "none"}; scopes: one study > its cohort > all studies (default). Every change is appended to its history.
materialize() writes the effective calls into review/ID_calls.csv (unchanged legacy format, so scoring and training read them) and
re-scores with mark_css.py; the previous ID_calls.csv / ID_score.json are first copied to review/call_history/ID/.
review_state() derives Not started / In progress / Reviewed / Needs re-review from the files (read only)."""
import datetime, glob, hashlib, json, os, re, shutil, subprocess, sys
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from css_common import FP, match_calls, norm_call

LEDGER_VERSION = "call-ledger/1.0"
POLICY_SCHEMA = "call-policy/1.0"
LEGACY = "(unnamed, before v5.4)"
STATES = ("not_started", "in_progress", "reviewed", "needs_rereview")
STATE_LABEL = {"not_started": "Not started", "in_progress": "In progress", "reviewed": "Reviewed", "needs_rereview": "Needs re-review"}
HERE = os.path.dirname(os.path.abspath(__file__))
slug = lambda s: re.sub(r"[^A-Za-z0-9]+", "_", s.strip()).strip("_") or "reviewer"      # the same as review_web.py


def _now(): return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
def _mtime_str(p): return datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M:%S")


def _read(p):
    try: return pd.read_csv(p)
    except Exception: return pd.DataFrame()


def candidates(base, sid):
    p = os.path.join(base, "review", f"{sid}_candidates.csv")
    return _read(p) if os.path.exists(p) else pd.DataFrame(columns=["cand_id"] + FP)


def sources(base, sid):
    """-> [dict(reviewer, file, origin, rows DataFrame)] (per-reviewer files; the legacy shared file only when none exist)"""
    out = []
    pre = os.path.join(base, "review", f"{sid}_calls_")
    for p in sorted(glob.glob(pre + "*.csv")):
        d = _read(p)
        if not len(d) or "call" not in d.columns: continue
        name = next((str(x) for x in d.get("reviewer", pd.Series(dtype=str)).dropna() if str(x).strip()), "") or p[len(pre):-4]
        out.append(dict(reviewer=name, file=os.path.relpath(p, base), origin="reviewer file", rows=d))
    if not out:
        p = os.path.join(base, "review", f"{sid}_calls.csv")
        if os.path.exists(p):
            d = _read(p)
            if len(d) and "call" in d.columns:
                d = d.assign(reviewer=LEGACY, time=_mtime_str(p)); out.append(dict(reviewer=LEGACY, file=os.path.relpath(p, base), origin="legacy shared file", rows=d))
    return out


def ledger(base, sid, cand=None):
    """-> (per-candidate call history {cand_id: [dict(reviewer, call, comment, time)] oldest first}, stale [dict], reviewers [names])"""
    cand = candidates(base, sid) if cand is None else cand
    hist, stale, names = {}, [], []
    for s in sources(base, sid):
        names.append(s["reviewer"]); fmt = _mtime_str(os.path.join(base, s["file"]))
        for _, r in s["rows"].iterrows():
            call = norm_call(r.get("call")); call = call if isinstance(call, str) and call.strip() else ""
            if not call: continue
            t = str(r.get("time")) if isinstance(r.get("time"), str) and str(r.get("time")).strip() else fmt
            ent = dict(reviewer=s["reviewer"], call=call, comment=str(r.get("comment")) if isinstance(r.get("comment"), str) else "", time=t,
                       file=s["file"])
            cid = None
            if all(c in s["rows"].columns for c in FP) and len(cand):
                m, _ = match_calls(cand, pd.DataFrame([r]))
                if m: cid = next(iter(m))
            elif len(cand) and "cand_id" in s["rows"].columns:                   # file without fingerprint: trust only if not re-detected
                nii = os.path.join(base, "review", f"{sid}_candidates.nii.gz"); fpath = os.path.join(base, s["file"])
                if not (os.path.exists(nii) and os.path.getmtime(nii) > os.path.getmtime(fpath)) and int(r["cand_id"]) in set(cand.cand_id.astype(int)):
                    cid = int(r["cand_id"])
            if cid is None: stale.append(dict(ent, cand_id=int(r["cand_id"]) if "cand_id" in r else None))
            else: hist.setdefault(cid, []).append(ent)
    for v in hist.values(): v.sort(key=lambda e: (e["time"], e["reviewer"]))
    return hist, stale, names


# ---------------------------------------------------------------- policy
def policy_path(base): return os.path.join(base, "review", "call_policy.json")


def load_policy(base):
    p = policy_path(base)
    if os.path.exists(p):
        try:
            with open(p) as f: P = json.load(f)
            if P.get("schema") == POLICY_SCHEMA: return P
        except Exception: pass
    return dict(schema=POLICY_SCHEMA, default=dict(mode="newest"), cohorts={}, studies={}, history=[])


def _valid_rule(rule):
    if not isinstance(rule, dict) or rule.get("mode") not in ("newest", "reviewer"): raise ValueError("rule mode must be 'newest' or 'reviewer'")
    if rule["mode"] == "reviewer":
        if not str(rule.get("reviewer", "")).strip(): raise ValueError("a reviewer rule needs the reviewer's name")
        if rule.get("fallback", "newest") not in ("newest", "none"): raise ValueError("fallback must be 'newest' or 'none'")
        return dict(mode="reviewer", reviewer=str(rule["reviewer"]).strip(), fallback=rule.get("fallback", "newest"))
    return dict(mode="newest")


def set_policy(base, scope, target, rule, by=""):
    """scope 'all' | 'cohort' | 'study'; rule None removes a cohort / study override. Appends to the history; returns the policy."""
    P = load_policy(base); rule = None if rule is None else _valid_rule(rule)
    if scope == "all": P["default"] = rule or dict(mode="newest")
    elif scope in ("cohort", "study"):
        key = "cohorts" if scope == "cohort" else "studies"
        if not str(target or "").strip(): raise ValueError(f"{scope} scope needs a target")
        if rule is None: P[key].pop(target, None)
        else: P[key][target] = rule
    else: raise ValueError("scope must be all, cohort or study")
    P["history"].append(dict(time=_now(), scope=scope, target=target or "", rule=rule, by=by or ""))
    os.makedirs(os.path.dirname(policy_path(base)), exist_ok=True)
    tmp = policy_path(base) + ".tmp"
    with open(tmp, "w") as f: json.dump(P, f, indent=1)
    os.replace(tmp, policy_path(base)); return P


def cohort_of(base, sid):
    """the study's cohort from the app's study list (app_data/patients.json), '' when unknown"""
    try:
        with open(os.path.join(base, "app_data", "patients.json")) as f: return next((str(p.get("cohort") or "") for p in json.load(f) if p.get("code") == sid), "")
    except Exception: return ""


def resolve(P, sid, cohort=""):
    if sid in P.get("studies", {}): return P["studies"][sid], "study"
    if cohort and cohort in P.get("cohorts", {}): return P["cohorts"][cohort], "cohort"
    return P.get("default") or dict(mode="newest"), "all studies"


def describe_rule(rule):
    if rule.get("mode") == "reviewer":
        return f"calls of {rule['reviewer']}" + (" (newest call where they did not call)" if rule.get("fallback", "newest") == "newest" else " only")
    return "newest call of any reviewer"


# ---------------------------------------------------------------- effective calls
def effective(base, sid, cohort="", policy=None, cand=None):
    """-> dict(rule, scope, rows [per current candidate], stale, reviewers)"""
    cand = candidates(base, sid) if cand is None else cand
    P = load_policy(base) if policy is None else policy; rule, scope = resolve(P, sid, cohort or cohort_of(base, sid))
    hist, stale, names = ledger(base, sid, cand); rows = []
    for cid in [int(x) for x in cand.cand_id] if len(cand) else []:
        H = hist.get(cid, []); pick, how = None, ""
        if rule["mode"] == "reviewer":
            own = [e for e in H if e["reviewer"].strip() == rule["reviewer"]]
            if own: pick, how = own[-1], "chosen reviewer"
            elif rule.get("fallback", "newest") == "newest" and H: pick, how = H[-1], "newest (chosen reviewer did not call it)"
        elif H: pick, how = H[-1], "newest"
        rows.append(dict(cand_id=cid, effective_call=pick["call"] if pick else "", source_reviewer=pick["reviewer"] if pick else "",
                         source_time=pick["time"] if pick else "", source_rule=how, n_reviewers=len({e["reviewer"] for e in H}),
                         disagreement=len({e["call"] for e in H}) > 1, history=H))
    return dict(rule=rule, scope=scope, rule_text=describe_rule(rule), rows=rows, stale=stale, reviewers=sorted(set(names)), ledger_version=LEDGER_VERSION)


def completions(base, sid):
    """finish / final records of every reviewer: [dict(reviewer, kind, time)]"""
    out = []
    for p in glob.glob(os.path.join(base, "review", f"{sid}_final_*.json")):
        try:
            with open(p) as f: j = json.load(f)
            out.append(dict(reviewer=j.get("reviewer") or p.rsplit("_final_", 1)[1][:-5], kind="final save", time=j.get("saved") or _mtime_str(p)))
        except Exception: pass
    for p in [os.path.join(base, "review", f"{sid}_score.json")] + glob.glob(os.path.join(base, "review", f"{sid}_score_rev_*.json")):
        if os.path.exists(p): out.append(dict(reviewer=p.rsplit("_score_rev_", 1)[1][:-5] if "_score_rev_" in p else "(shared score)", kind="finish",
                                              time=_mtime_str(p)))
    return sorted(out, key=lambda x: x["time"])


def review_state(base, sid, cohort="", policy=None):
    """Not started / In progress / Reviewed / Needs re-review, with the reason (read only)"""
    cand = candidates(base, sid); E = effective(base, sid, cohort, policy, cand)
    n = len(E["rows"]); called = sum(1 for r in E["rows"] if r["effective_call"]); comp = completions(base, sid)
    any_calls = called or E["stale"]
    last = comp[-1] if comp else None
    cpath = os.path.join(base, "review", f"{sid}_candidates.nii.gz")
    cand_time = _mtime_str(cpath) if os.path.exists(cpath) else ""
    if not any_calls and not comp: st, why = "not_started", "no reviewer call yet"
    elif last and called == n and (n > 0 or comp): st, why = "reviewed", f"all {n} candidates called; {last['kind']} by {last['reviewer']} {last['time']}"
    elif last and (E["stale"] or (cand_time and cand_time > last["time"])) and called < n:
        st, why = "needs_rereview", f"candidates changed after the review ({n - called} without a call, {len(E['stale'])} earlier call(s) no longer match)"
    elif called < n: st, why = "in_progress", f"{called} of {n} candidates called" + ("" if last else "; not finished")
    else: st, why = "in_progress", f"all {n} called but the review was not finished (no finish / final save)"
    return dict(state=st, label=STATE_LABEL[st], reason=why, n_candidates=n, n_called=called, n_stale=len(E["stale"]), completions=comp,
                reviewers=E["reviewers"], rule_text=E["rule_text"], scope=E["scope"])


def _sha(p):
    if not os.path.exists(p): return ""
    with open(p, "rb") as f: return hashlib.sha256(f.read()).hexdigest()


def materialize(base, sid, cohort="", by="", scripts=HERE, rescore=True):
    """write the effective calls into review/ID_calls.csv (legacy format) and (rescore=True) re-score with mark_css.py; the earlier
    ID_calls.csv / ID_score.json are copied to review/call_history/ID/ first"""
    cand = candidates(base, sid); E = effective(base, sid, cohort, cand=cand)
    eff = {r["cand_id"]: r["effective_call"] for r in E["rows"] if r["effective_call"]}
    c = cand.set_index("cand_id") if len(cand) else None
    rows = [dict(cand_id=k, call=v, **{f: c.loc[k, f] for f in FP}) for k, v in sorted(eff.items())]
    new = pd.DataFrame(rows, columns=["cand_id", "call"] + FP)
    p = os.path.join(base, "review", f"{sid}_calls.csv"); sp = os.path.join(base, "review", f"{sid}_score.json")
    old_txt = None
    if os.path.exists(p):
        with open(p) as f: old_txt = f.read()
    new_txt = new.to_csv(index=False)
    ep = os.path.join(base, "review", f"{sid}_effective.json"); prev = {}
    if os.path.exists(ep):
        try:
            with open(ep) as f: prev = json.load(f)
        except Exception: prev = {}
    rec = dict(study=sid, time=_now(), by=by, rule=E["rule"], scope=E["scope"], rule_text=E["rule_text"], n_effective=len(eff),
               sources={r: sum(1 for x in E["rows"] if x["source_reviewer"] == r) for r in E["reviewers"]}, ledger_version=LEDGER_VERSION,
               changed=old_txt != new_txt, backup="")
    if old_txt != new_txt:
        hd = os.path.join(base, "review", "call_history", sid); os.makedirs(hd, exist_ok=True); ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        for src in (p, sp):
            if os.path.exists(src): shutil.copy2(src, os.path.join(hd, f"{ts}_{os.path.basename(src)}"))
        rec["backup"] = os.path.relpath(hd, base) + f"/{ts}_*"
        with open(p + ".tmp", "w") as f: f.write(new_txt)
        os.replace(p + ".tmp", p)
    cur_sha = hashlib.sha256(new_txt.encode()).hexdigest(); rec["scored_calls_sha256"] = prev.get("scored_calls_sha256", "")
    if rescore and (rec["scored_calls_sha256"] != cur_sha or not os.path.exists(sp)):
        acc = sorted(k for k, v in eff.items() if v == "cSS"); ich = sorted(k for k, v in eff.items() if v == "Near ICH")
        cmd = [sys.executable, os.path.join(scripts, "mark_css.py"), sid, ",".join(map(str, acc)) or "none", "--reviewed", ",".join(map(str, sorted(eff))) or "none"]
        if ich: cmd += ["--ich", ",".join(map(str, ich))]
        r = subprocess.run(cmd, capture_output=True, text=True, env=dict(os.environ, CSS_BASE=base, PYTHONWARNINGS="ignore"))
        rec.update(score_ok=r.returncode == 0, score_note=(r.stdout + r.stderr).strip()[-600:])
        if r.returncode == 0: rec["scored_calls_sha256"] = cur_sha
    rec["calls_sha256"] = _sha(p); rec["score_current"] = rec["scored_calls_sha256"] == cur_sha
    with open(ep + ".tmp", "w") as f: json.dump(rec, f, indent=1)
    os.replace(ep + ".tmp", ep)
    return rec


# ---------------------------------------------------------------- explicit, confirmed consolidation (destructive, archived first)
CONFIRM = "REWRITE OLD CALLS"


def consolidate_plan(base, sids):
    out = []
    for sid in sids:
        hist, _, _ = ledger(base, sid); drop = sum(len(v) - 1 for v in hist.values() if len(v) > 1)
        out.append(dict(study=sid, candidates_with_history=sum(len(v) > 1 for v in hist.values()), calls_to_remove=drop))
    return out


def consolidate(base, sids, confirm, by=""):
    """keep only the newest call of each candidate in the reviewer files (other reviewers' older calls removed). Refused unless confirm
    equals CONFIRM. Every affected file is copied to review/call_history/ID/consolidate_<time>/ first; restore() undoes it."""
    if confirm != CONFIRM: raise PermissionError(f"refused: type exactly '{CONFIRM}' to confirm")
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f"); done = []
    for sid in sids:
        cand = candidates(base, sid); hist, _, _ = ledger(base, sid, cand)
        newest = {cid: (v[-1]["reviewer"], v[-1]["time"]) for cid, v in hist.items()}
        arch = os.path.join(base, "review", "call_history", sid, f"consolidate_{ts}"); os.makedirs(arch, exist_ok=True)
        for f in glob.glob(os.path.join(base, "review", f"{sid}_calls*.csv")) + glob.glob(os.path.join(base, "review", f"{sid}_final_*.json")) \
                + glob.glob(os.path.join(base, "review", f"{sid}_score*.json")) + glob.glob(os.path.join(base, "review", f"{sid}_review_log.csv")):
            shutil.copy2(f, arch)
        removed = 0
        for s in sources(base, sid):
            if s["origin"] != "reviewer file": continue
            d = s["rows"]; keep = []
            for _, r in d.iterrows():
                m, _ = match_calls(cand, pd.DataFrame([r])) if len(cand) and all(c in d.columns for c in FP) else ({}, 0)
                cid = next(iter(m)) if m else None
                t = str(r.get("time")) if isinstance(r.get("time"), str) and str(r.get("time")).strip() else _mtime_str(os.path.join(base, s["file"]))
                ok = cid is None or not isinstance(r.get("call"), str) or newest.get(cid) == (s["reviewer"], t)
                keep.append(ok); removed += 0 if ok else 1
            d[keep].to_csv(os.path.join(base, s["file"]), index=False)
        set_policy(base, "study", sid, dict(mode="newest"), by=by or "consolidate")
        done.append(dict(study=sid, removed=removed, archive=os.path.relpath(arch, base)))
    return done


def restore(base, sid, archive_rel):
    arch = os.path.join(base, archive_rel)
    if not os.path.isdir(arch) or os.path.dirname(os.path.relpath(arch, os.path.join(base, "review", "call_history"))) != sid:
        raise ValueError("not a consolidation archive of this study")
    for f in os.listdir(arch): shutil.copy2(os.path.join(arch, f), os.path.join(base, "review", f))
    return sorted(os.listdir(arch))
