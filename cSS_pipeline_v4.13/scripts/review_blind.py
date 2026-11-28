#!/usr/bin/env python3
"""review_blind.py - Phase 3A.2: server-enforced blinded initial read for the browser reviewer (review_web.py). Research software.

Read phase (per study and reviewer) - decided by the SERVER from the reviewer's event journal (review_io), never by the browser:
  initial      the first read. No AI content is sent: no meter / band / suspicion / confidence / evidence scores / Percival or AI score /
               shape interpretation / unified-score report / detector fate of missed marks / excluded-object rule; other reviewers' calls,
               marks and call-file listings are not sent either. Candidates are shown under BLINDED identifiers (see below).
  second_look  only after the reviewer completed the initial read (final save with every shown candidate called) AND asked to unblind
               (POST /api/unblind). Both steps are journaled ('initial_completed', 'unblind'); calls made after are recorded as second-look calls.
  --open no longer changes the phase (it only tells the page that a second look may start opened).

Blinded candidate identifiers: every candidate (and excluded-audit object) of a study gets, per reviewer, a stable integer 1..N drawn as a
random permutation (secrets.SystemRandom) - unrelated to the detector rank (cand_id = rank) and to the excluded-object number. The mapping
(candidate fingerprint -> blinded id) is kept in the reviewer's append-only journal ('blind_ids' events); new objects after a re-detection get
new ids above the existing ones. Requests carry blinded ids and are translated on the server; responses never contain the original ids.
A reviewer without a name gets a mapping held in memory only (nothing written)."""
import os, re, secrets, threading
import review_io as RIO

INITIAL, SECOND = "initial", "second_look"
AUDIT_OFFSET = 10000
BLIND_AI = dict(score=0.0, band="hidden", suspect="", reason="", source="hidden during the blind initial read", tier=0)
VISIBLE_FEAT = ("extent_mm", "n_slices")                       # image measurements only; every evidence / score feature is withheld
HIDDEN_MSG = "hidden during the blind initial read - finish your read (final save) and choose 'second look' to see it"


class BlindError(Exception):
    """a request the blind read refuses; the message is safe to show (no identifiers, no AI content)"""
    def __init__(self, msg, code=403):
        super().__init__(msg); self.code = code


def _rng(): return secrets.SystemRandom()


# ------------------------------------------------------------------ phase
def phase(base, sid, reviewer):
    """-> dict(phase, completed, completed_at, unblinded_at). No reviewer name -> initial."""
    out = dict(phase=INITIAL, completed=False, completed_at="", unblinded_at="")
    if not str(reviewer or "").strip(): return out
    ev, _ = RIO.read_journal(RIO.journal_path(base, sid, reviewer))
    for e in ev:
        if e.get("kind") == "initial_completed": out.update(completed=True, completed_at=e.get("time", ""))
        elif e.get("kind") == "unblind" and out["completed"]: out.update(phase=SECOND, unblinded_at=e.get("time", ""))
    return out


def is_blind(base, sid, reviewer): return phase(base, sid, reviewer)["phase"] == INITIAL


def record_completed(base, sid, reviewer, n_candidates, n_called):
    with RIO.study_lock(base, sid):
        if phase(base, sid, reviewer)["completed"]: return False
        RIO.journal_append(base, sid, reviewer, "initial_completed", n_candidates=int(n_candidates), n_called=int(n_called))
        return True


def unblind(base, sid, reviewer):
    if not str(reviewer or "").strip(): raise BlindError("enter your reviewer name first", 400)
    with RIO.study_lock(base, sid):
        p = phase(base, sid, reviewer)
        if p["phase"] == SECOND: return p
        if not p["completed"]:
            raise BlindError("the second look opens after your initial read is complete: call every candidate (Unsure is a call), then save the final result", 409)
        RIO.journal_append(base, sid, reviewer, "unblind")
        return phase(base, sid, reviewer)


# ------------------------------------------------------------------ blinded identifiers
_EPHEMERAL = {}
_EPH_LOCK = threading.Lock()


def cand_key(r): return "c|%d|%d|%d|%g" % (int(r["vox_i"]), int(r["vox_j"]), int(r["vox_k"]), float(r["volume_mm3"]))
def excl_key(excl_id, volume): return "x|%d|%g" % (int(excl_id), float(volume))


def _assign(existing, keys):
    new = [k for k in dict.fromkeys(keys) if k not in existing]
    if not new: return {}
    start = max(existing.values(), default=0) + 1
    ids = list(range(start, start + len(new))); _rng().shuffle(ids)
    return dict(zip(new, ids))


def mapping(base, sid, reviewer, keys):
    """-> {fingerprint key: blinded id} covering every key (new keys are assigned and journaled)"""
    if not str(reviewer or "").strip():
        with _EPH_LOCK:
            m = _EPHEMERAL.setdefault(sid, {}); m.update(_assign(m, keys)); return dict(m)
    with RIO.study_lock(base, sid):
        m = stored_mapping(base, sid, reviewer)
        add = _assign(m, keys)
        if add:
            RIO.journal_append(base, sid, reviewer, "blind_ids", assign=add, note="blinded candidate identifiers (fingerprint -> id)")
            m.update(add)
        return m


def stored_mapping(base, sid, reviewer):
    """the journaled mapping (internal; never sent to the browser)"""
    m = {}
    ev, _ = RIO.read_journal(RIO.journal_path(base, sid, reviewer))
    for e in ev:
        if e.get("kind") == "blind_ids": m.update({k: int(v) for k, v in e.get("assign", {}).items()})
    return m


APP_RELEASE = "(app release)"                                   # pseudo-reviewer of app/blind_gate.py release events


def released_in_app(base, sid):
    ev, _ = RIO.read_journal(RIO.journal_path(base, sid, APP_RELEASE))
    return any(e.get("kind") == "ai_released" for e in ev)


class Ctx:
    """per request: whether this reviewer is blind for this study, and the id translation both ways"""
    def __init__(self, base, s, reviewer, audit_rows=()):
        self.reviewer = str(reviewer or "").strip(); self.ph = phase(base, s.sid, self.reviewer); self.blind = self.ph["phase"] == INITIAL
        self.released = released_in_app(base, s.sid)                    # the app showed this study's AI results without a blind read
        self.t2b, self.b2t = {}, {}
        if not self.blind: return
        keys, true = [], []
        for _, r in s.df.iterrows(): keys.append(cand_key(r)); true.append(int(r.cand_id))
        for excl_id, vol in audit_rows: keys.append(excl_key(excl_id, vol)); true.append(AUDIT_OFFSET + int(excl_id))
        m = mapping(base, s.sid, self.reviewer, keys)
        self.t2b = {t: m[k] for k, t in zip(keys, true)}; self.b2t = {b: t for t, b in self.t2b.items()}

    def to_true(self, cid):
        if not self.blind: return int(cid)
        try: return self.b2t[int(cid)]
        except (KeyError, TypeError, ValueError): raise BlindError("unknown candidate", 400)

    def to_blind(self, cid): return self.t2b.get(int(cid), 0) if self.blind else int(cid)


# ------------------------------------------------------------------ redaction (applied only when ctx.blind)
def redact_cand(c, ctx):
    out = dict(id=ctx.to_blind(c["id"]), hemi=c.get("hemi", ""), region=c.get("region", ""), volume=c.get("volume"), centre=c.get("centre"),
               ext_volume=c.get("ext_volume"), ext_leak=c.get("ext_leak", False),            # 2026-11-28: detector geometry (extent), not an AI opinion
               vox=c.get("vox"), ai=dict(BLIND_AI), conf=None, conf_why="", feat={k: (c.get("feat") or {}).get(k) for k in VISIBLE_FEAT})
    return out


def redact_calls(calls, ctx):
    return {ctx.to_blind(k): {f: v.get(f, "") for f in ("call", "comment", "time", "fine")} for k, v in calls.items() if ctx.to_blind(k)}


MISSED_KEEP = ("missed_id", "reviewer", "time", "vox_i", "vox_j", "vox_k", "x_mm", "y_mm", "z_mm", "can_i", "can_j", "can_k", "comment", "plane",
               "slice", "shape", "points")


def redact_missed(rows, ctx):
    """own marks only, without the detector's fate (which names candidate numbers and exclusion rules)"""
    return [{k: r.get(k, "") for k in MISSED_KEEP} for r in rows if str(r.get("reviewer", "")).strip() == ctx.reviewer]


SCORE_KEEP = ("L_score", "R_score", "multifocality_0_4", "category", "n_sulci_total", "L_sulci", "R_sulci", "L_lines", "R_lines", "n_lines_total",
              "scoring_method", "n_unreviewed")
FINAL_KEEP = ("study", "reviewer", "saved", "n_candidates", "n_read", "n_css", "n_missed", "n_microbleed", "read_mode")


def redact_score(sc):
    return None if sc is None else {k: sc[k] for k in SCORE_KEEP if k in sc}


def redact_final(f):
    if not f: return f
    out = {k: f[k] for k in FINAL_KEEP if k in f}
    if f.get("reviewer_score") is not None: out["reviewer_score"] = redact_score(f["reviewer_score"])
    return out


def remap_labels(L, ctx):
    """label volume values (candidate ids / 10000 + excluded id) -> blinded ids"""
    import numpy as np
    if not ctx.blind: return L
    if not ctx.t2b: return np.zeros_like(L)
    lut = np.zeros(max(int(L.max()), max(ctx.t2b)) + 1, np.uint32)
    for t, b in ctx.t2b.items():
        if t < len(lut): lut[t] = b
    return lut[L.astype(np.int64)].astype(L.dtype)


_DIGITS = re.compile(r"\d+")


def safe_log_text(s): return _DIGITS.sub("#", str(s))
