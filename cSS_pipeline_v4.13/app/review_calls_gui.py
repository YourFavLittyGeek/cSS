"""review_calls_gui.py - the app's side of the reviewer-call ledger (scripts/call_ledger.py): review state per study, which reviewer's calls
are EFFECTIVE (policy: one study > cohort > all studies; default the newest call), the per-reviewer Excel sheet, and the explicit,
confirmed consolidation. Research software.

Nothing here edits a reviewer's own file. Changing the policy re-writes only the EFFECTIVE files (review/ID_calls.csv, ID_score.json,
ID_effective.json) and copies their previous versions to review/call_history/ID/ first. consolidate() is the only destructive operation:
it requires the exact confirmation phrase, archives every affected file first and can be undone with restore()."""
import importlib, os, sys

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)


def _ledger(B):
    """the call_ledger module the reviewer uses: the project's installed scripts/ first, else this package's scripts/"""
    for d in (os.path.join(B, "scripts"), os.path.join(ROOT, "scripts")):
        if os.path.exists(os.path.join(d, "call_ledger.py")):
            if d not in sys.path: sys.path.insert(0, d)
            m = importlib.import_module("call_ledger")
            if os.path.dirname(os.path.abspath(m.__file__)) != d: m = importlib.reload(m)
            return m
    raise ImportError("call_ledger.py not found (scripts/)")


def _studies(B, PAT, scope="all", target=""):
    rows = []
    for p in PAT:
        if not os.path.exists(os.path.join(B, "review", f"{p['code']}_candidates.csv")): continue
        if scope == "study" and p["code"] != target: continue
        if scope == "cohort" and (p.get("cohort") or "") != target: continue
        rows.append((p["code"], p.get("cohort") or ""))
    return rows


_CACHE = {}


def _key(B, code, cohort):
    import glob
    fs = glob.glob(os.path.join(B, "review", f"{code}_*")) + [os.path.join(B, "review", "call_policy.json"), os.path.join(B, "app_data", "patients.json")]
    return (code, cohort) + tuple(sorted((f, os.path.getmtime(f), os.path.getsize(f)) for f in fs if os.path.isfile(f)))


def state(B, code, cohort=""):
    """review state (cached until any review/ID_* file, the policy or the study list changes)"""
    try:
        k = _key(B, code, cohort)
        if _CACHE.get(code, (None,))[0] != k: _CACHE[code] = (k, _ledger(B).review_state(B, code, cohort))
        return _CACHE[code][1]
    except Exception as e: return dict(state="error", label="Review state unavailable", reason=f"{type(e).__name__}: {e}"[-300:])


def policy(B, PAT):
    L = _ledger(B); P = L.load_policy(B)
    st = []
    for code, coh in _studies(B, PAT):
        E = L.effective(B, code, coh)
        st.append(dict(code=code, cohort=coh, rule_text=E["rule_text"], scope=E["scope"], reviewers=E["reviewers"],
                       disagreements=sum(1 for r in E["rows"] if r["disagreement"]), n_effective=sum(1 for r in E["rows"] if r["effective_call"]),
                       n_candidates=len(E["rows"]), from_reviewer={rv: sum(1 for r in E["rows"] if rv in r["source_reviewer"].split(", ")) for rv in E["reviewers"]},
                       status_counts={k: sum(1 for r in E["rows"] if r["status"] == k) for k in L.STATUSES},
                       primary_eligible=sum(1 for r in E["rows"] if r["primary_eligible"]), problems=E["problems"]))
    return dict(policy=P, studies=st, reviewers=sorted({r for s in st for r in s["reviewers"]}), roles=L.RR.current(B), role_names=list(L.RR.ROLES),
                confirm=dict(role=L.RR.CONFIRM_ROLE, adjudicator=L.RR.CONFIRM_ADJUDICATOR, verify=L.RR.CONFIRM_VERIFY),
                cohorts=sorted({c for _, c in _studies(B, PAT) if c}))


# ---------------------------------------------------------------- Phase 3A.3/3A.4 administration (local administrator; typed confirmations)
def roles(B): L = _ledger(B); return dict(roles=L.RR.current(B), history=L.RR.history(B)["events"], role_names=list(L.RR.ROLES))
def set_role(B, name, role, by, reason, confirm): return _ledger(B).RR.set_role(B, name, role, by, reason, confirm)
def set_adjudicator(B, name, allowed, by, reason, confirm): return _ledger(B).RR.set_adjudicator(B, name, allowed, by, reason, confirm)
def verify_historical(B, code, reviewer, by, reason, evidence, confirm): return _ledger(B).RR.verify_historical(B, code, reviewer, by, reason, evidence, confirm)


def adjudicate(B, code, cohort, cand_id, call, by, reason):
    L = _ledger(B); r = L.adjudicate(B, code, int(cand_id), call, by, reason); L.materialize(B, code, cohort, by=by, rescore=True); return r


def withdraw_adjudication(B, code, cohort, cand_id, by, reason):
    L = _ledger(B); r = L.withdraw_adjudication(B, code, int(cand_id), by, reason); L.materialize(B, code, cohort, by=by, rescore=True); return r


def set_policy(B, PAT, scope, target, rule, by=""):
    """set the rule, then re-write the EFFECTIVE calls (and score) of every affected study; reviewers' own files untouched"""
    L = _ledger(B); L.set_policy(B, scope, target, rule, by=by)
    done = []
    for code, coh in _studies(B, PAT, scope, target):
        r = L.materialize(B, code, coh, by=by or "policy change", rescore=True)
        done.append(dict(code=code, changed=r["changed"], score_ok=r.get("score_ok", True), backup=r.get("backup", "")))
    return dict(ok=True, updated=done, policy=L.load_policy(B))


def study_calls(B, code, cohort=""):
    L = _ledger(B); E = L.effective(B, code, cohort)
    return dict(code=code, rule_text=E["rule_text"], scope=E["scope"], reviewers=E["reviewers"], stale=E["stale"], rows=E["rows"],
                state=L.review_state(B, code, cohort))


def calls_sheet(B, PAT, cohort=""):
    """wide table: one row per candidate; for EVERY reviewer a call / date-time / comment column; then the effective call and its source"""
    import pandas as pd
    L = _ledger(B); out = []
    for code, coh in _studies(B, PAT):
        if cohort and cohort != "all" and coh != cohort: continue
        cand = L.candidates(B, code); E = L.effective(B, code, coh, cand=cand); cc = cand.set_index("cand_id") if len(cand) else None
        for r in E["rows"]:
            row = {"Study": code, "Cohort": coh, "Candidate": r["cand_id"]}
            if cc is not None: row.update({k: cc.loc[r["cand_id"], k] for k in ("vox_i", "vox_j", "vox_k", "volume_mm3") if k in cc.columns})
            for e in r["history"]:
                n = e["reviewer"]; row[f"{n} · call"] = e["call"]; row[f"{n} · date and time"] = e["time"]
                if e.get("comment"): row[f"{n} · comment"] = e["comment"]
            for e in r["history"]:
                n = e["reviewer"]; row[f"{n} · role"] = e.get("role", ""); row[f"{n} · provenance"] = e.get("class", "")
                if e.get("prefilled"): row[f"{n} · pre-filled (not independent)"] = "yes"
            row.update({"Effective call": r["effective_call"], "Effective call from": r["source_reviewer"], "Effective call time": r["source_time"],
                        "Rule": E["rule_text"], "Rule set for": E["scope"], "Reviewers disagree": "yes" if r["disagreement"] else "",
                        "Status": r["status"], "Provenance class": r["provenance_class"], "Primary training ground truth": "yes" if r["primary_eligible"] else "",
                        "Adjudicated by": (r.get("adjudication") or {}).get("by", "")})
            out.append(row)
    return pd.DataFrame(out)


def consolidate_plan(B, PAT, scope, target=""):
    L = _ledger(B); codes = [c for c, _ in _studies(B, PAT, scope, target)]
    return dict(plan=L.consolidate_plan(B, codes), removed=True, warning="Consolidation was removed in Phase 3A: reviewers' calls are never deleted. "
                "Disagreements between experts are resolved by adjudication.")


def consolidate(B, PAT, scope, target, confirm, by=""):
    return _ledger(B).consolidate(B, [], confirm, by=by)                     # raises PermissionError (removed in Phase 3A)


def restore(B, code, archive):
    return dict(ok=True, restored=_ledger(B).restore(B, code, archive))
