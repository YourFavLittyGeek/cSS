"""blind_gate.py - Phase 3A.2 (main app): per-study AI outputs are withheld in the app until the study's independent blind read is done.

The app has no trustworthy notion of who is using it (the reviewer name lives in the browser), so the rule is per STUDY and decided by the
server from the reviewers' event journals (review_io / review_blind, the same records the reviewer server writes):

  pending   no reviewer has completed a blind initial read of the study, OR some reviewer has started one (blinded ids issued / calls made)
            and not completed it. Withheld: the AI score and its note, the experimental unified-score counts, the "AI only" label (results,
            Studies sheet, study detail, exports built from them), and in PERCIVAL Center the study's Percival score, its prediction ledger,
            on-demand scoring (Percival / unified).
  complete  at least one completed blind initial read and no open one; a review finished before Phase 3A (final record, no journal) also
            counts as complete (it cannot be made blind afterwards).
  released  the user explicitly released the AI results of a study without a blind read (typed confirmation + reason); journaled under
            the pseudo-reviewer "(app release)" so every later read of that study records that AI results were visible in the app.
Fail-closed: if the journal modules cannot be loaded, every study counts as pending."""
import glob, os, sys

RELEASE_REVIEWER = "(app release)"
CONFIRM = "RELEASE AI RESULTS"
HIDDEN = "hidden until the study's blind review is complete"
BLIND_ACTIVITY = ("blind_ids", "call", "comment", "clear", "undo", "revote", "audit_call", "missed_add", "missed_delete", "missed_comment", "finish")


def _mods(B, here):
    for d in (os.path.join(B, "scripts"), os.path.join(os.path.dirname(here), "scripts")):
        if os.path.exists(os.path.join(d, "review_io.py")) and os.path.exists(os.path.join(d, "review_blind.py")):
            if d not in sys.path: sys.path.insert(0, d)
            try:
                import review_io, review_blind
                return review_io, review_blind
            except Exception: return None
    return None


def state(B, code, here=os.path.dirname(os.path.abspath(__file__))):
    """-> dict(pending, status, reason, completed_by, open_reads, released)"""
    m = _mods(B, here)
    if m is None: return dict(pending=True, status="unknown", reason="the review journal could not be read", completed_by=[], open_reads=[], released=None)
    RIO, RB = m
    try: RIO.check_sid(code)
    except ValueError: return dict(pending=True, status="unknown", reason="invalid study key", completed_by=[], open_reads=[], released=None)
    completed, opened, released = [], [], None
    journaled = set()
    for f in sorted(glob.glob(os.path.join(B, "review", f"{code}_events_*.jsonl"))):
        ev, _ = RIO.read_journal(f)
        if not ev: continue
        who = ev[0].get("reviewer", "")
        if who == RELEASE_REVIEWER:
            rel = [e for e in ev if e.get("kind") == "ai_released"]
            if rel: released = dict(by=rel[-1].get("by", ""), reason=rel[-1].get("reason", ""), time=rel[-1].get("time", ""))
            continue
        journaled.add(RIO.slug(who))
        kinds = {e.get("kind") for e in ev}
        if "initial_completed" in kinds: completed.append(who)
        elif kinds & set(BLIND_ACTIVITY): opened.append(who)
    for f in glob.glob(os.path.join(B, "review", f"{code}_final_*.json")):          # a review finished before Phase 3A (no journal)
        slug = os.path.basename(f)[len(code) + len("_final_"):-5]
        if slug not in journaled: completed.append(f"{slug} (before Phase 3A)")
    if released: return dict(pending=False, status="released", reason="AI results released without a blind read", completed_by=completed, open_reads=opened, released=released)
    if opened: return dict(pending=True, status="pending", reason="a blind read of this study is in progress", completed_by=completed, open_reads=opened, released=None)
    if not completed: return dict(pending=True, status="pending", reason="no blind read of this study has been completed yet", completed_by=[], open_reads=[], released=None)
    return dict(pending=False, status="complete", reason="", completed_by=completed, open_reads=[], released=None)


def release(B, code, by, reason, confirm, here=os.path.dirname(os.path.abspath(__file__))):
    if confirm != CONFIRM: return dict(ok=False, error=f"refused: type exactly '{CONFIRM}' to confirm")
    if not str(by or "").strip() or not str(reason or "").strip(): return dict(ok=False, error="a name and a reason are required")
    m = _mods(B, here)
    if m is None: return dict(ok=False, error="the review journal could not be written")
    RIO, _ = m
    RIO.check_sid(code)
    with RIO.study_lock(B, code):
        RIO.journal_append(B, code, RELEASE_REVIEWER, "ai_released", by=str(by).strip()[:80], reason=str(reason).strip()[:500],
                           note="AI results shown in the app without a completed blind read; later reads of this study are not independent of them")
    return dict(ok=True, state=state(B, code, here))


RESULT_AI_KEYS = ("ai_L", "ai_R", "ai_total", "ai_err", "unified_css_compatible", "unified_uncertain", "unified_alternative", "unified_model", "unified_note")


def mask_result(r, st):
    """results row of a pending study: AI-derived fields removed, a neutral note instead"""
    for k in RESULT_AI_KEYS: r.pop(k, None)
    if r.get("unified_status") not in (None, "", "off"): r["unified_status"] = "hidden"
    if r.get("label") == "AI only, not validated": r["label"] = "blind review pending"
    r["ai_hidden"] = st["reason"] or HIDDEN
    return r
