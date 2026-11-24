#!/usr/bin/env python3
"""call_ledger.py - every reviewer's calls are kept; the EFFECTIVE call of each candidate follows a policy.
Phase 3A.3/3A.4: call-policy/2.0 - consensus of explicitly designated EXPERTS (review_roles.py) with a quorum, or one reference expert;
newest-wins and the automatic primary reviewer are gone. Per candidate: resolved / adjudicated / disagreement / abstained / insufficient /
no_expert / missing; only resolved or adjudicated candidates get an effective call. Imported / inherited / carried calls never count as
independent reviews. Each counted call has a provenance class from the reviewer journals (verified_blind_post_3A, historical_blinding_verified,
historical_blinding_unknown, historical_adjudicated, not_blind_post_3A); only verified / adjudicated classes are primary training ground truth.
The text below describes the v5.15 design (sources, re-attachment, lineage) that is unchanged.
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
from css_common import FP, match_calls, match_one_to_one, norm_call
import review_io as RIO       # Phase 3A.1: crash-safe writes, cross-process study locks, append-only reviewer event journals
import review_roles as RR     # Phase 3A.3: roles, adjudication permission, documented historical verification

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


def match_one(cand, row):
    """v5.24: attach ONE call row (from any calls file, e.g. a review made by an earlier version / project) to the current candidates by
    fingerprint (centroid within 2 voxels, volume within 15 %) - never by number. -> cand_id or None. The single place outside this module's
    own readers where calls are matched (Percival's earlier-version reviews use it)."""
    if not len(cand) or not all(c in row for c in FP): return None
    try: d = match_one_to_one(cand, [row])[0]
    except Exception: return None
    return d["cand_id"] if d["status"] == "matched" else None


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
        has_fp = all(c in s["rows"].columns for c in FP)
        mdec = match_one_to_one(cand, s["rows"]) if has_fp and len(cand) else None           # Phase 3B: whole file, one-to-one
        for ri, (_, r) in enumerate(s["rows"].iterrows()):
            call = norm_call(r.get("call")); call = call if isinstance(call, str) and call.strip() else ""
            if not call: continue
            t = str(r.get("time")) if isinstance(r.get("time"), str) and str(r.get("time")).strip() else fmt
            ent = dict(reviewer=s["reviewer"], call=call, comment=str(r.get("comment")) if isinstance(r.get("comment"), str) else "", time=t,
                       file=s["file"])
            if s["origin"] == "reviewer file":                                 # Phase 3A.3: where to find this record's journal evidence
                ent["file_slug"] = os.path.basename(s["file"])[len(f"{sid}_calls_"):-4]
                if all(c in s["rows"].columns for c in ["cand_id"] + FP): ent["row_key"] = "|".join(str(r[c]) for c in ["cand_id"] + FP)
            cid = None
            if mdec is not None:
                dx = mdec[ri]; ent["match"] = {k: v for k, v in dx.items() if k != "row"}
                if dx["status"] == "matched": cid = dx["cand_id"]
            elif len(cand) and "cand_id" in s["rows"].columns:                   # file without fingerprint: trust only if not re-detected
                nii = os.path.join(base, "review", f"{sid}_candidates.nii.gz"); fpath = os.path.join(base, s["file"])
                if not (os.path.exists(nii) and os.path.getmtime(nii) > os.path.getmtime(fpath)) and int(r["cand_id"]) in set(cand.cand_id.astype(int)):
                    cid = int(r["cand_id"])
            if cid is not None and all(c in s["rows"].columns for c in FP):
                cur = cand.set_index("cand_id").loc[cid]
                if any(abs(float(cur[f]) - float(r[f])) > 1e-6 for f in FP):     # same lesion by the strict fingerprint rule, but re-detected
                    ent["matched"] = "re-attached by fingerprint after re-detection (centroid within 2 voxels, volume within 15 %)"
            if cid is None:
                ru = f"{sid}:{int(r['vox_i'])}:{int(r['vox_j'])}:{int(r['vox_k'])}:{float(r['volume_mm3']):g}" if all(c in s["rows"].columns for c in FP) else ""
                stale.append(dict(ent, cand_id=int(r["cand_id"]) if "cand_id" in r else None, row_uid=ru))
            else: hist.setdefault(cid, []).append(ent)
    # v5.17 candidate lineage (re-processing): a call made on an earlier run's candidate follows it ONLY through a confident match;
    # possible matches stay out of the effective calls and are listed for confirmation (never silently transferred)
    lin = lineage(base, sid); dec = decisions(base, sid); keep = []
    for e in stale:
        r = e.get("row_uid") and lin.get(e["row_uid"])
        if r and r["status"] == "confident" and r.get("new_cand_id") is not None and len(cand) and int(r["new_cand_id"]) in set(cand.cand_id.astype(int)):
            hist.setdefault(int(r["new_cand_id"]), []).append(dict(e, carried=dict(from_run=lin.get("_run_old", ""), old_cand_id=r["old_cand_id"], iou=r.get("iou"), why=r["why"])))
        else:
            if r and r["status"] == "possible":
                k = f"{e['row_uid']}|{e['reviewer']}|{e['time']}"
                e = dict(e, possible=True, suggested_new_cand_id=r.get("new_cand_id"), lineage_why=r["why"], decision=dec.get(k, ""))
            keep.append(e)
    stale = keep
    for v in hist.values(): v.sort(key=lambda e: (e["time"], e["reviewer"]))
    return hist, stale, names


def lineage(base, sid):
    """review/ID_lineage.json (candidate_lineage.py) as {old candidate uid: record}, plus _run_old"""
    p = os.path.join(base, "review", f"{sid}_lineage.json")
    try:
        with open(p) as f: L = json.load(f)
    except Exception: return {}
    out = {r["old_uid"]: r for r in L.get("old", []) if r.get("old_uid")}; out["_run_old"] = L.get("run_old", ""); return out


def decisions(base, sid):
    p = os.path.join(base, "review", f"{sid}_lineage_decisions.json")
    try:
        with open(p) as f: return json.load(f)
    except Exception: return {}


def pending_confirmations(base, sid):
    """earlier calls whose candidate has only a POSSIBLE match in the current run and no decision yet"""
    _, stale, _ = ledger(base, sid)
    return [e for e in stale if e.get("possible") and not e.get("decision")]


def decide_carry(base, sid, row_uid, reviewer_of_call, time_of_call, decision, by):
    """decision 'confirm': the confirming reviewer's OWN new call on the suggested current candidate (their file; comment records what
    was confirmed). 'reject': recorded, the earlier call stays historical only. The earlier call itself is never changed."""
    if decision not in ("confirm", "reject"): raise ValueError("decision must be confirm or reject")
    if not str(by or "").strip(): raise ValueError("a reviewer name is required")
    e = next((x for x in pending_confirmations(base, sid) if x["row_uid"] == row_uid and x["reviewer"] == reviewer_of_call and x["time"] == time_of_call), None)
    if e is None: raise ValueError("no pending confirmation for that call")
    k = f"{row_uid}|{reviewer_of_call}|{time_of_call}"
    with RIO.study_lock(base, sid):                                        # Phase 3A.1: journal first, files atomic, one writer per study
        D = decisions(base, sid)
        if decision == "confirm":
            cand = candidates(base, sid).set_index("cand_id"); nc = int(e["suggested_new_cand_id"])
            p = os.path.join(base, "review", f"{sid}_calls_{slug(by)}.csv")
            RIO.ensure_table(base, sid, by, "calls", p)
            d = _read(p) if os.path.exists(p) else pd.DataFrame(columns=["cand_id", "call", "comment", "reviewer", "time"] + FP)
            d = d[d.cand_id != nc] if len(d) else d
            row = dict(cand_id=nc, call=e["call"], comment=f"[confirmed carry-over of {reviewer_of_call}'s '{e['call']}' ({time_of_call}) from an earlier run: {e['lineage_why']}]",
                       reviewer=by.strip(), time=_now(), **{f: cand.loc[nc, f] for f in FP})
            RIO.write_table(base, sid, by, "calls", p, pd.concat([d, pd.DataFrame([row])], ignore_index=True), ["cand_id"] + FP, "carry_confirm",
                            cand_id=nc, call=e["call"], carried_from=dict(reviewer=reviewer_of_call, time=time_of_call, row_uid=row_uid))
        else:
            RIO.journal_append(base, sid, by, "carry_reject", row_uid=row_uid, reviewer_of_call=reviewer_of_call, time_of_call=time_of_call)
        D[k] = dict(decision=decision, by=by, time=_now()); dp = os.path.join(base, "review", f"{sid}_lineage_decisions.json")
        RIO.atomic_write_json(dp, D)
    return dict(ok=True, decision=decision)


# ---------------------------------------------------------------- policy (Phase 3A.3: call-policy/2.0 - expert consensus; newest-wins removed)
POLICY_V2 = "call-policy/2.0"
DEFAULT_RULE = dict(mode="consensus", quorum=1)


def policy_path(base): return os.path.join(base, "review", "call_policy.json")


def _upgrade_rule(r):
    """a stored call-policy/1.0 rule read under 2.0: 'newest' -> consensus, 'reviewer' -> reference with no fallback (noted)"""
    if not isinstance(r, dict): return dict(DEFAULT_RULE)
    if r.get("mode") == "newest": return dict(DEFAULT_RULE, upgraded_from="newest")
    if r.get("mode") == "reviewer": return dict(mode="reference", reviewer=str(r.get("reviewer", "")).strip(), fallback="none", upgraded_from="reviewer")
    return r


def load_policy(base):
    p = policy_path(base); P = None
    if os.path.exists(p):
        try:
            with open(p) as f: P = json.load(f)
        except Exception: P = None
    if not isinstance(P, dict): return dict(schema=POLICY_V2, default=dict(DEFAULT_RULE), cohorts={}, studies={}, history=[])
    if P.get("schema") != POLICY_V2:                                       # 1.0 file: read as 2.0 (the file itself is migrated by review_migrate)
        P = dict(schema=POLICY_V2, legacy_schema=P.get("schema"), default=_upgrade_rule(P.get("default")),
                 cohorts={k: _upgrade_rule(v) for k, v in (P.get("cohorts") or {}).items()},
                 studies={k: _upgrade_rule(v) for k, v in (P.get("studies") or {}).items()}, history=list(P.get("history") or []))
    return P


def _valid_rule(rule, base=None):
    if not isinstance(rule, dict): raise ValueError("a rule is required")
    m = rule.get("mode")
    if m in ("newest", "reviewer"): raise ValueError("refused: 'newest' / 'reviewer with newest fallback' were removed in Phase 3A - use 'consensus' or 'reference'")
    if m == "consensus":
        q = int(rule.get("quorum", 1))
        if q < 1 or q > 9: raise ValueError("quorum must be 1-9 expert calls")
        return dict(mode="consensus", quorum=q)
    if m == "reference":
        name = str(rule.get("reviewer", "")).strip()
        if not name: raise ValueError("a reference expert is required")
        if base is not None and RR.role_of(base, name) != "expert": raise PermissionError(f"refused: {name} is not an expert (assign the role first)")
        fb = rule.get("fallback", "none")
        if fb not in ("none", "consensus"): raise ValueError("fallback must be 'none' or 'consensus'")
        return dict(mode="reference", reviewer=name, fallback=fb)
    raise ValueError("rule mode must be 'consensus' or 'reference'")


def set_policy(base, scope, target, rule, by=""):
    """scope 'all' | 'cohort' | 'study'; rule None removes a cohort / study override. Appends to the history; returns the policy."""
    with RIO.project_lock(base, "call_policy"):                            # Phase 3A.1: read-modify-write under a cross-process lock
        return _set_policy(base, scope, target, rule, by)


def _set_policy(base, scope, target, rule, by=""):
    P = load_policy(base); rule = None if rule is None else _valid_rule(rule, base)
    if scope == "all": P["default"] = rule or dict(DEFAULT_RULE)
    elif scope in ("cohort", "study"):
        key = "cohorts" if scope == "cohort" else "studies"
        if not str(target or "").strip(): raise ValueError(f"{scope} scope needs a target")
        if rule is None: P[key].pop(target, None)
        else: P[key][target] = rule
    else: raise ValueError("scope must be all, cohort or study")
    P["schema"] = POLICY_V2
    P["history"].append(dict(time=_now(), scope=scope, target=target or "", rule=rule, by=by or ""))
    RIO.atomic_write_json(policy_path(base), P); return P


def cohort_of(base, sid):
    """the study's cohort from the app's study list (app_data/patients.json), '' when unknown"""
    try:
        with open(os.path.join(base, "app_data", "patients.json")) as f: return next((str(p.get("cohort") or "") for p in json.load(f) if p.get("code") == sid), "")
    except Exception: return ""


def resolve(P, sid, cohort=""):
    if sid in P.get("studies", {}): return _upgrade_rule(P["studies"][sid]), "study"
    if cohort and cohort in P.get("cohorts", {}): return _upgrade_rule(P["cohorts"][cohort]), "cohort"
    return _upgrade_rule(P.get("default") or dict(DEFAULT_RULE)), "all studies"


def describe_rule(rule):
    if rule.get("mode") == "reference":
        return f"calls of the reference expert {rule['reviewer']}" + (" (expert consensus where they did not call)" if rule.get("fallback") == "consensus" else " only")
    q = int(rule.get("quorum", 1))
    return f"consensus of designated experts (at least {q} definite expert call{'s' if q > 1 else ''}, all agreeing)"


# ---------------------------------------------------------------- provenance (Phase 3A.3 / 3A.6)
CLASSES = ("verified_blind_post_3A", "historical_blinding_verified", "historical_blinding_unknown", "historical_adjudicated", "adjudicated_post_3A", "not_blind_post_3A")
PRIMARY_ELIGIBLE = ("verified_blind_post_3A", "historical_blinding_verified")   # 3B policy: an adjudicated label is NOT automatically eligible
_RANK = {"verified_blind_post_3A": 3, "historical_blinding_verified": 2, "adjudicated_post_3A": 1, "historical_adjudicated": 1, "historical_blinding_unknown": 1, "not_blind_post_3A": 0}
PREFILL = ("[imported", "[inherited", "[old calls", "[confirmed carry-over")
NOT_INDEPENDENT_KINDS = ("import", "inherit", "carry_confirm", "consolidate", "restore")


def call_class(call):
    c = norm_call(call) if isinstance(call, str) else ""
    if c == "cSS": return "positive"
    if c in ("Vessel", "Normal", "Artifact", "Microbleed"): return "negative"
    if c == "Near ICH": return "out_of_scope"
    if c == "Unsure": return "abstain"
    return "unrecognised" if c else ""


def evidence(base, sid, file_slug):
    """journal evidence per record of a reviewer's calls file: {record key: dict(kind, read_phase, ai_visible, released)}. A record that only
    came from a snapshot (written before journaling, external change, restore) has no evidence."""
    ev, _ = RIO.read_journal(RIO.journal_path(base, sid, file_slug))
    ev = [e for e in ev if e.get("table") == "calls"]
    out = {}; prev_lines = {}
    for e, _txt, _h, _order, lines in RIO.table_states(ev):
        if "snapshot" in e: out = {}; prev_lines = lines; continue
        by_text = {}
        for k, ln in prev_lines.items(): by_text.setdefault(ln, out.get(k))
        info = dict(kind=e.get("kind"), read_phase=e.get("read_phase"), ai_visible=e.get("ai_visible"), released=bool(e.get("ai_released_in_app")))
        new = {}
        for k, ln in lines.items():
            if k in (e.get("upserts") or {}): new[k] = by_text.get(ln) if ln in by_text else info     # unchanged text re-keyed: keep its evidence
            else: new[k] = out.get(k)
        out = {k: v for k, v in new.items() if v is not None}; prev_lines = lines
    return out


def _klass(ent, verified):
    ev = ent.get("evidence")
    if ev:
        if ev.get("kind") in NOT_INDEPENDENT_KINDS: return "not_blind_post_3A"
        if ev.get("read_phase") == "initial" and ev.get("ai_visible") is False and not ev.get("released"): return "verified_blind_post_3A"
        if ev.get("read_phase") in ("initial", "second_look", "unblinded_legacy") or ev.get("ai_visible") is not None: return "not_blind_post_3A"
    v = verified.get(ent.get("slug"))
    if v and (not v.get("records") or v["records"].get(ent.get("row_key", "")) == ent.get("call") or
              norm_call(v["records"].get(ent.get("row_key", ""), "")) == ent.get("call")):      # only the calls that were verified
        return "historical_blinding_verified"
    return "historical_blinding_unknown"


def completed_reviewers(base, sid):
    """slugs of reviewers who COMPLETED their review of the study: a blind initial read completed (journal 'initial_completed'), a final
    record (reviews before Phase 3A), or a documented historical verification. Only completed EXPERT reviews take part in consensus."""
    out = set(RR.verified_reviewers(base, sid))
    for p in glob.glob(os.path.join(base, "review", f"{sid}_final_*.json")):
        try:
            with open(p) as f: j = json.load(f)
        except Exception: j = {}
        out.add(slug(j.get("reviewer") or os.path.basename(p)[len(sid) + 7:-5]))
    for p in glob.glob(os.path.join(base, "review", f"{sid}_events_*.jsonl")):
        ev, _ = RIO.read_journal(p)
        if any(e.get("kind") in ("initial_completed", "review_completed") for e in ev): out.add(slug(ev[0].get("reviewer", "")))
    return out


# ---------------------------------------------------------------- integrity (Phase 3A.5: reads verify the journals; unsafe rebuilds refused)
def integrity(base, sid):
    """READ-ONLY: every reviewer calls file against its journal -> [problem text] (empty = consistent)"""
    out = []; pre = os.path.join(base, "review", f"{sid}_calls_")
    for p in sorted(glob.glob(pre + "*.csv")):
        st = RIO.check_table(base, sid, p[len(pre):-4], "calls", p)
        if st["status"] not in ("ok", "no_journal"): out.append(f"{os.path.basename(p)}: {st['status']} - {st['detail']}")
    return out


# ---------------------------------------------------------------- adjudication (Phase 3A.4)
def adjudications(base, sid, cand=None):
    """current adjudication per current candidate {cand_id: event} (latest per fingerprint; withdrawals honoured; fingerprint-matched)"""
    ev, _ = RIO.read_journal(RIO.journal_path(base, sid, RR.ADJUDICATION))
    cur = {}
    for e in ev:
        k = e.get("fp_key")
        if e.get("kind") == "adjudicate": cur[k] = e
        elif e.get("kind") == "adjudication_withdrawn": cur.pop(k, None)
    cand = candidates(base, sid) if cand is None else cand; out = {}
    for e in cur.values():
        cid = match_one(cand, dict({f: e["fp"][f] for f in FP}, call=e.get("call", ""))) if e.get("fp") else None
        if cid is not None: out[int(cid)] = e
    return out


def adjudicate(base, sid, cand_id, call, by, reason):
    """an expert with the adjudication permission decides an unresolved candidate; the reviewers' calls are kept unchanged"""
    if not str(reason or "").strip(): raise ValueError("refused: a reason is required")
    if not RR.may_adjudicate(base, by): raise PermissionError(f"refused: {by} is not an expert with the adjudication permission")
    c = norm_call(call)
    if call_class(c) not in ("positive", "negative", "out_of_scope"): raise ValueError("an adjudicated call must be definite (not Unsure)")
    with RIO.study_lock(base, sid):
        cand = candidates(base, sid); E = effective(base, sid, cand=cand)
        row = next((r for r in E["rows"] if r["cand_id"] == int(cand_id)), None)
        if row is None: raise ValueError("unknown candidate")
        if not row["history"]: raise ValueError("refused: nothing to adjudicate - no reviewer called this candidate")
        r = cand.set_index("cand_id").loc[int(cand_id)]; fp = {f: (float(r[f]) if f == "volume_mm3" else int(r[f])) for f in FP}
        e = RIO.journal_append(base, sid, RR.ADJUDICATION, "adjudicate", cand_id=int(cand_id), fp=fp, fp_key="|".join(str(fp[f]) for f in FP), call=c,
                               by=str(by).strip(), reason=str(reason).strip()[:500], status_before=row["status"],
                               calls_seen=[dict(reviewer=x["reviewer"], call=x["call"], role=x.get("role"), prefilled=x.get("prefilled", False)) for x in row["history"]])
    return dict(ok=True, event=e)


def withdraw_adjudication(base, sid, cand_id, by, reason):
    if not RR.may_adjudicate(base, by): raise PermissionError(f"refused: {by} is not an expert with the adjudication permission")
    with RIO.study_lock(base, sid):
        a = adjudications(base, sid).get(int(cand_id))
        if not a: raise ValueError("no adjudication for this candidate")
        return dict(ok=True, event=RIO.journal_append(base, sid, RR.ADJUDICATION, "adjudication_withdrawn", cand_id=int(cand_id), fp_key=a["fp_key"],
                                                     by=str(by).strip(), reason=str(reason or "").strip()[:500]))


# ---------------------------------------------------------------- effective calls
STATUSES = ("resolved", "adjudicated", "disagreement", "abstained", "unrecognised", "insufficient", "incomplete", "pending_review", "no_expert", "missing")


def effective(base, sid, cohort="", policy=None, cand=None):
    """-> dict(rule, scope, rows [per current candidate], stale, reviewers, problems). Per candidate: status (resolved / adjudicated /
    disagreement / abstained / insufficient / no_expert / missing), effective_call (resolved or adjudicated only), provenance class,
    primary_eligible, and every reviewer's call with role / prefilled / evidence (nothing is dropped)."""
    cand = candidates(base, sid) if cand is None else cand
    P = load_policy(base) if policy is None else policy; rule, scope = resolve(P, sid, cohort or cohort_of(base, sid))
    roles = RR.current(base); verified = RR.verified_reviewers(base, sid)
    hist, stale, names = ledger(base, sid, cand)
    ev_cache = {}
    for H in hist.values():
        for e in H:
            e["slug"] = slug(e["reviewer"]) if e["reviewer"] != LEGACY else ""
            e["role"] = RR.role_of(base, e["reviewer"], roles) if e["reviewer"] != LEGACY else "unknown"
            e["prefilled"] = str(e.get("comment", "")).startswith(PREFILL)        # imported / inherited / another reviewer's call confirmed
            #   (a confident lineage carry-over or a fingerprint re-attachment is the SAME reviewer's own call on the same lesion: counted)
            fs = e.get("file_slug")
            if fs:
                if fs not in ev_cache: ev_cache[fs] = evidence(base, sid, fs)
                e["evidence"] = ev_cache[fs].get(e.get("row_key", ""))
            e["class"] = _klass(e, verified)
    adj = adjudications(base, sid, cand); done = completed_reviewers(base, sid)
    participants = sorted({e["reviewer"] for H in hist.values() for e in H if e["role"] == "expert" and slug(e["reviewer"]) in done})
    rows = []
    for cid in [int(x) for x in cand.cand_id] if len(cand) else []:
        H = hist.get(cid, []); latest = {}
        for e in H: latest[e["reviewer"]] = e                                  # oldest first -> each reviewer's latest call
        all_experts = [e for e in latest.values() if e["role"] == "expert" and not e["prefilled"]]
        experts = [e for e in all_experts if slug(e["reviewer"]) in done]             # 3B: completed expert reviews only
        missing_resp = [x for x in participants if x not in latest]                     # a completed expert without a call here
        votes = [e for e in experts if call_class(e["call"]) in ("positive", "negative", "out_of_scope")]
        pick, status, how = [], "missing", ""
        if rule["mode"] == "reference":
            ref = [e for e in experts if slug(e["reviewer"]) == slug(rule["reviewer"]) and call_class(e["call"]) != "abstain"]
            if ref and slug(rule["reviewer"]) not in done: status = "pending_review"
            elif ref: pick, status, how = ref, "resolved", "reference expert"
            elif rule.get("fallback") != "consensus": status = "missing" if not H else ("abstained" if any(slug(e["reviewer"]) == slug(rule["reviewer"]) for e in experts) else "no_expert")
        if not pick and status == "missing" and (rule["mode"] == "consensus" or rule.get("fallback") == "consensus"):
            q = int(rule.get("quorum", 1)) if rule["mode"] == "consensus" else 1
            if not H: status = "missing"
            elif not experts: status = "pending_review" if all_experts else "no_expert"
            elif missing_resp: status = "incomplete"                                      # never resolved by the experts who happened to call
            elif not votes: status = "unrecognised" if any(call_class(e["call"]) == "unrecognised" for e in experts) else "abstained"
            elif len({call_class(e["call"]) for e in votes}) > 1: status = "disagreement"
            elif len(votes) < q: status = "insufficient"
            else: pick, status, how = votes, "resolved", "expert consensus"
        a = adj.get(cid); call = ""
        if a:
            status, how, call = "adjudicated", f"adjudicated by {a.get('by')}", a["call"]
            klass = "historical_adjudicated" if not votes or any(e["class"] != "verified_blind_post_3A" for e in votes) else "adjudicated_post_3A"
        elif status == "resolved":
            if any(e.get("carried") for e in pick): how += " · carried over from the earlier run (confident match)"
            elif any(e.get("matched") for e in pick): how += " · re-attached after re-detection (fingerprint)"
            cnt = {}
            for e in pick: cnt[norm_call(e["call"])] = cnt.get(norm_call(e["call"]), 0) + 1
            call = sorted(cnt, key=lambda c_: (-cnt[c_], c_))[0]
            klass = min((e["class"] for e in pick), key=lambda k_: _RANK[k_])
        else: klass = ""
        rows.append(dict(cand_id=cid, status=status, effective_call=call, provenance_class=klass,
                         primary_eligible=bool(call) and klass in PRIMARY_ELIGIBLE and call_class(call) in ("positive", "negative"),
                         source_reviewer=", ".join(sorted(e["reviewer"] for e in pick)) if pick else (a.get("by", "") if a else ""),
                         source_time=max((e["time"] for e in pick), default=a.get("time", "") if a else ""), source_rule=how,
                         n_reviewers=len(latest), n_expert_calls=len(experts), n_abstentions=sum(1 for e in experts if call_class(e["call"]) == "abstain"),
                         experts_missing=missing_resp, experts_pending=sorted(e["reviewer"] for e in all_experts if slug(e["reviewer"]) not in done),
                         subtype_mixed=status == "resolved" and len({norm_call(e["call"]) for e in pick}) > 1,
                         disagreement=status == "disagreement" or len({call_class(e["call"]) for e in latest.values() if call_class(e["call"]) not in ("abstain", "")}) > 1,
                         adjudication=a, history=H))
    matching = {}
    for H in list(hist.values()) + [[e] for e in stale]:
        for e in H: st_ = (e.get("match") or {}).get("status", "by_number" if e in stale else "matched"); matching[st_] = matching.get(st_, 0) + 1
    return dict(rule=rule, scope=scope, rule_text=describe_rule(rule), rows=rows, stale=stale, reviewers=sorted(set(names)), ledger_version=LEDGER_VERSION,
                problems=integrity(base, sid), roles={k: v["role"] for k, v in roles.items()}, matching=matching, participants=participants)


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
    """Not started / In progress / Reviewed / Needs re-review = REVIEW PROGRESS (any reviewer's calls), read only; ground-truth resolution is
    reported separately (n_resolved / n_unresolved)"""
    cand = candidates(base, sid); E = effective(base, sid, cohort, policy, cand)
    n = len(E["rows"]); called = sum(1 for r in E["rows"] if r["history"]); comp = completions(base, sid)
    any_calls = called or E["stale"]
    last = comp[-1] if comp else None
    cpath = os.path.join(base, "review", f"{sid}_candidates.nii.gz")
    cand_time = _mtime_str(cpath) if os.path.exists(cpath) else ""
    if not any_calls and not comp: st, why = "not_started", "no reviewer call yet"
    elif last and called == n and (n > 0 or comp): st, why = "reviewed", f"all {n} candidates called; {last['kind']} by {last['reviewer']} {last['time']}"
    elif last and (E["stale"] or (cand_time and cand_time > last["time"])) and called < n:
        pend = sum(1 for e in E["stale"] if e.get("possible") and not e.get("decision"))
        st, why = "needs_rereview", f"candidates changed after the review ({n - called} without a call, {len(E['stale'])} earlier call(s) no longer match" + (
            f", {pend} of them need your confirmation)" if pend else ")")
    elif called < n: st, why = "in_progress", f"{called} of {n} candidates called" + ("" if last else "; not finished")
    else: st, why = "in_progress", f"all {n} called but the review was not finished (no finish / final save)"
    res = sum(1 for r in E["rows"] if r["status"] in ("resolved", "adjudicated"))
    return dict(state=st, label=STATE_LABEL[st], reason=why, n_candidates=n, n_called=called, n_stale=len(E["stale"]), completions=comp,
                n_carried=sum(1 for r in E["rows"] if any(e.get("carried") for e in r["history"])), n_pending_confirmation=sum(1 for e in E["stale"] if e.get("possible") and not e.get("decision")),
                reviewers=E["reviewers"], rule_text=E["rule_text"], scope=E["scope"], n_resolved=res, n_unresolved=n - res,
                n_disagreement=sum(1 for r in E["rows"] if r["status"] == "disagreement"), problems=E["problems"])


def _sha(p):
    if not os.path.exists(p): return ""
    with open(p, "rb") as f: return hashlib.sha256(f.read()).hexdigest()


def materialize(base, sid, cohort="", by="", scripts=HERE, rescore=True):
    """write the RESOLVED effective calls (expert consensus / reference expert / adjudication) into review/ID_calls.csv (legacy format) and
    (rescore=True) re-score with mark_css.py; the earlier ID_calls.csv / ID_score.json are copied to review/call_history/ID/ first. The shared
    file is DERIVED from the reviewer files and their journals; it is never an authoritative source. Phase 3A.5: refused (nothing written,
    the previous derived files kept) when a reviewer file does not match its journal."""
    with RIO.study_lock(base, sid):                                        # Phase 3A.1: one writer per study across processes
        return _materialize(base, sid, cohort, by, scripts, rescore)


def _materialize(base, sid, cohort="", by="", scripts=HERE, rescore=True):
    cand = candidates(base, sid); E = effective(base, sid, cohort, cand=cand)
    if E["problems"]:
        return dict(study=sid, time=_now(), by=by, refused=True, problems=E["problems"], changed=False, score_ok=None,
                    score_note="shared calls not rebuilt: " + "; ".join(E["problems"])[:500])
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
    rec = dict(study=sid, time=_now(), by=by, rule=E["rule"], scope=E["scope"], rule_text=E["rule_text"], n_effective=len(eff), policy_schema=POLICY_V2,
               n_unresolved=sum(1 for r in E["rows"] if not r["effective_call"]), status_counts={k: sum(1 for r in E["rows"] if r["status"] == k) for k in STATUSES},
               sources={r: sum(1 for x in E["rows"] if r in x["source_reviewer"].split(", ")) for r in E["reviewers"]}, ledger_version=LEDGER_VERSION,
               changed=old_txt != new_txt, backup="")
    if old_txt != new_txt:
        hd = os.path.join(base, "review", "call_history", sid); os.makedirs(hd, exist_ok=True); ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        for src in (p, sp):
            if os.path.exists(src): shutil.copy2(src, os.path.join(hd, f"{ts}_{os.path.basename(src)}"))
        rec["backup"] = os.path.relpath(hd, base) + f"/{ts}_*"
        RIO.atomic_write_text(p, new_txt)
    cur_sha = hashlib.sha256(new_txt.encode()).hexdigest(); rec["scored_calls_sha256"] = prev.get("scored_calls_sha256", "")
    if rescore and (rec["scored_calls_sha256"] != cur_sha or not os.path.exists(sp)):
        acc = sorted(k for k, v in eff.items() if v == "cSS"); ich = sorted(k for k, v in eff.items() if v == "Near ICH")
        cmd = [sys.executable, os.path.join(scripts, "mark_css.py"), sid, ",".join(map(str, acc)) or "none", "--reviewed", ",".join(map(str, sorted(eff))) or "none"]
        if ich: cmd += ["--ich", ",".join(map(str, ich))]
        r = subprocess.run(cmd, capture_output=True, text=True, env=dict(os.environ, CSS_BASE=base, PYTHONWARNINGS="ignore"))
        rec.update(score_ok=r.returncode == 0, score_note=(r.stdout + r.stderr).strip()[-600:])
        if r.returncode == 0: rec["scored_calls_sha256"] = cur_sha
    rec["calls_sha256"] = _sha(p); rec["score_current"] = rec["scored_calls_sha256"] == cur_sha
    RIO.atomic_write_json(ep, rec)
    RIO.atomic_write_json(os.path.join(base, "review", f"{sid}_matching.json"), dict(       # Phase 3B: audit of every matching decision (derived)
        study=sid, time=_now(), matcher="css_common.match_one_to_one (centroid <= 2 voxels, volume within 15 %, same hemisphere, ambiguity margin 0.5 voxel, contested -> unresolved)",
        summary=E["matching"], unresolved=[dict(reviewer=e["reviewer"], call=e["call"], time=e["time"], row_uid=e.get("row_uid"), match=e.get("match"),
                                                carry=e.get("possible") and "possible lineage match - needs confirmation") for e in E["stale"]]))
    return rec


# ---------------------------------------------------------------- consolidation REMOVED (Phase 3A.4): it deleted other reviewers' calls
CONFIRM = "REWRITE OLD CALLS"


def consolidate_plan(base, sids):
    return [dict(study=sid, removed_feature=True, note="consolidation was removed in Phase 3A: reviewers' calls are never deleted; resolve disagreements by adjudication")
            for sid in sids]


def consolidate(base, sids, confirm, by=""):
    raise PermissionError("refused: consolidation was removed in Phase 3A (it deleted reviewers' calls) - disagreements are resolved by adjudication")


def restore(base, sid, archive_rel):
    arch = os.path.join(base, archive_rel)
    if not os.path.isdir(arch) or os.path.dirname(os.path.relpath(arch, os.path.join(base, "review", "call_history"))) != sid:
        raise ValueError("not a consolidation archive of this study")
    with RIO.study_lock(base, sid):                                        # Phase 3A.1: restored reviewer files become the journal head
        for f in os.listdir(arch):
            src, dst = os.path.join(arch, f), os.path.join(base, "review", f)
            m = re.match(rf"^{re.escape(sid)}_(calls|excluded_audit)_(.+)\.csv$", f)
            if m:
                with open(src, encoding="utf-8") as fh: txt = fh.read()
                RIO.write_table_text(base, sid, m.group(2), "calls" if m.group(1) == "calls" else "audit", dst, txt, "restore",
                                     archive=os.path.relpath(arch, base))
            else: RIO.atomic_copy(src, dst)
    return sorted(os.listdir(arch))
