#!/usr/bin/env python3
"""review_roles.py - Phase 3A.3: reviewer roles, adjudication permission and documented verification of historical blinding.

Roles: expert | trainee | other | unknown (default for every name; nobody is ever promoted automatically). Three separate permissions:
  role administration  set_role / set_adjudicator: the local administrator (the app user or the command line), typed confirmation + reason;
                       never from a reviewer window
  reviewing            any named reviewer (review_web.py); only EXPERT calls count for consensus
  adjudication         an expert who was separately granted the adjudicator permission
Every change is an event in the append-only, hash-chained journal review/project_roles_events.jsonl (review_io); the current roles are the
replay of that history - nothing is ever overwritten.

Historical blinding: verify_historical() records, per study and reviewer, that an expert review made BEFORE Phase 3A is documented as blind
(typed confirmation, the person, the reason and the evidence) in review/<ID>_events_verification.jsonl. Without it, pre-3A labels stay
'historical_blinding_unknown' (call_ledger) and never become primary training ground truth."""
import os, re
import review_io as RIO

ROLES = ("expert", "trainee", "other", "unknown")
CONFIRM_ROLE = "ASSIGN ROLE"
CONFIRM_ADJUDICATOR = "GRANT ADJUDICATION"
CONFIRM_VERIFY = "VERIFY BLINDING"
VERIFIER = "(verification)"                                     # pseudo-reviewer of a study's verification journal
ADJUDICATION = "(adjudication)"                                 # pseudo-reviewer of a study's adjudication journal
PSEUDO = (VERIFIER, ADJUDICATION, "(app release)")
slug = RIO.slug


def roles_journal(base): return os.path.join(base, "review", "project_roles_events.jsonl")


def _clean(x, n=200): return re.sub(r"[\x00-\x1f]", " ", str(x or "")).strip()[:n]


def _need(confirm, phrase, by, reason):
    if confirm != phrase: raise PermissionError(f"refused: type exactly '{phrase}' to confirm")
    if not _clean(by) or not _clean(reason): raise ValueError("refused: the administrator's name and a reason are required")


def current(base):
    """-> {slug: dict(name, role, adjudicator, since, by)} from the journal (replay)"""
    out = {}
    ev, _ = RIO.read_journal(roles_journal(base))
    for e in ev:
        k = e.get("slug") or slug(e.get("name", ""))
        r = out.setdefault(k, dict(name=e.get("name", ""), role="unknown", adjudicator=False, since="", by=""))
        if e.get("kind") == "role_set": r.update(name=e.get("name", r["name"]), role=e.get("role", "unknown"), since=e.get("time", ""), by=e.get("by", ""))
        elif e.get("kind") == "adjudicator_set": r["adjudicator"] = bool(e.get("allowed"))
    return out


def role_of(base, name, table=None):
    if not _clean(name) or name in PSEUDO: return "unknown"
    return (table if table is not None else current(base)).get(slug(name), {}).get("role", "unknown")


def may_adjudicate(base, name, table=None):
    t = table if table is not None else current(base); r = t.get(slug(name), {})
    return r.get("role") == "expert" and bool(r.get("adjudicator"))


def history(base):
    ev, probs = RIO.read_journal(roles_journal(base)); return dict(events=ev, problems=probs)


def set_role(base, name, role, by, reason, confirm):
    name = _clean(name, 80)
    if not name or name in PSEUDO: raise ValueError("refused: a reviewer name is required")
    if role not in ROLES: raise ValueError(f"refused: role must be one of {', '.join(ROLES)}")
    _need(confirm, CONFIRM_ROLE, by, reason)
    with RIO.project_lock(base, "roles"):
        prev = current(base).get(slug(name), {}).get("role", "unknown")
        e = RIO.journal_append_file(roles_journal(base), "project", "(role administration)", "role_set", name=name, slug=slug(name), role=role,
                                    previous=prev, by=_clean(by, 80), reason=_clean(reason, 500))
    return dict(ok=True, event=e, roles=current(base))


def set_adjudicator(base, name, allowed, by, reason, confirm):
    name = _clean(name, 80)
    _need(confirm, CONFIRM_ADJUDICATOR, by, reason)
    with RIO.project_lock(base, "roles"):
        t = current(base)
        if allowed and t.get(slug(name), {}).get("role") != "expert": raise PermissionError("refused: only an expert can be granted adjudication")
        e = RIO.journal_append_file(roles_journal(base), "project", "(role administration)", "adjudicator_set", name=name, slug=slug(name),
                                    allowed=bool(allowed), by=_clean(by, 80), reason=_clean(reason, 500))
    return dict(ok=True, event=e, roles=current(base))


def verified_reviewers(base, sid):
    """slugs of reviewers whose pre-3A review of this study has a documented blinding verification"""
    ev, _ = RIO.read_journal(RIO.journal_path(base, sid, VERIFIER))
    out = {}
    for e in ev:
        if e.get("kind") == "historical_blinding_verified": out[slug(e.get("reviewer_verified", ""))] = e
        elif e.get("kind") == "historical_verification_withdrawn": out.pop(slug(e.get("reviewer_verified", "")), None)
    return out


def verify_historical(base, sid, reviewer, by, reason, evidence, confirm):
    RIO.check_sid(sid)
    reviewer = _clean(reviewer, 80)
    if not reviewer: raise ValueError("refused: the reviewer whose read is verified is required")
    _need(confirm, CONFIRM_VERIFY, by, reason)
    if not _clean(evidence, 1000): raise ValueError("refused: describe the evidence (how the read was blind)")
    with RIO.study_lock(base, sid):
        recs = {}                                                            # exactly the calls that are verified (a later outside edit is not)
        p = os.path.join(base, "review", f"{sid}_calls_{slug(reviewer)}.csv")
        if os.path.exists(p):
            import pandas as pd
            d = pd.read_csv(p); cols = ["cand_id", "vox_i", "vox_j", "vox_k", "volume_mm3"]
            if "call" in d.columns and all(c in d.columns for c in cols):
                recs = {"|".join(str(r[c]) for c in cols): str(r["call"]) for _, r in d.iterrows() if isinstance(r["call"], str)}
        e = RIO.journal_append(base, sid, VERIFIER, "historical_blinding_verified", reviewer_verified=reviewer, by=_clean(by, 80),
                               reason=_clean(reason, 500), evidence=_clean(evidence, 1000), records=recs,
                               file_sha256=RIO.sha256_file(p) if os.path.exists(p) else "")
    return dict(ok=True, event=e)


if __name__ == "__main__":
    import sys
    sys.exit("use review_admin.py")
