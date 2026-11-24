"""pensieve_index.py - PENSIEVE · AI Memory and History, rebuilt from the AUTHORITATIVE records (architecture integration).

PENSIEVE is a per-project, derived and reproducible memory: it is never written by hand and never a second source of truth. Every row comes
from one authoritative record, which it names (source file + kind):
  studies / candidates   review/ID_candidates.csv + review/ID_manifest.json (ALBUS detector version)        source_kind = detector_output
  expert_calls           call ledger (scripts/call_ledger.effective): every reviewer's call with role, read phase, AI visibility and
                         provenance class from the reviewer journals                                       source_kind = expert_human
  consensus              call ledger per-candidate status / effective call / primary eligibility (Phase 3A rules)
  missed_lesions         review/ID_missed.csv (derived from the reviewers' journaled files), reviewer role + read provenance
  predictions            Percival prediction ledger percival/ledger/ID/*.json (immutable)                  source_kind = model_prediction
  corrections            derived: an expert-resolved not-cSS candidate = false positive of the ALBUS detector VERSION that proposed it;
                         a missed-lesion mark = a candidate-generation miss of that version (never attributed to a component that did not
                         produce the candidate)
Expert calls and predictions are separate tables; no code path copies a prediction into an expert table.
Location: <project>/percival/pensieve/pensieve_index.db (one per project; never a shared or hard-coded path).
rebuild() builds into a temporary file and replaces the index atomically; the same sources always give the same content digest.
update_study() replaces one study's rows in one transaction (used by the reviewer after a save). Failures are returned and recorded in
percival/pensieve/status.json - never swallowed."""
import glob
import hashlib
import json
import os
import sqlite3
import sys
import time

SCHEMA_VERSION = "pensieve-index/1.0"
TABLES = ("studies", "candidates", "expert_calls", "consensus", "missed_lesions", "predictions", "corrections")
DDL = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS studies (study_id TEXT PRIMARY KEY, patient_ref TEXT, detector_version TEXT, n_candidates INTEGER, source TEXT);
CREATE TABLE IF NOT EXISTS candidates (candidate_uid TEXT PRIMARY KEY, study_id TEXT NOT NULL REFERENCES studies(study_id) ON DELETE CASCADE,
  cand_id INTEGER, hemi TEXT, vox_i REAL, vox_j REAL, vox_k REAL, volume_mm3 REAL, detector_version TEXT, source TEXT, source_kind TEXT,
  UNIQUE(study_id, cand_id));
CREATE TABLE IF NOT EXISTS expert_calls (event_key TEXT PRIMARY KEY, study_id TEXT NOT NULL REFERENCES studies(study_id) ON DELETE CASCADE,
  candidate_uid TEXT, cand_id INTEGER, reviewer TEXT, role TEXT, call TEXT, read_phase TEXT, ai_visible TEXT, provenance_class TEXT,
  attached_by TEXT, time TEXT, source TEXT, source_kind TEXT CHECK (source_kind = 'expert_human'));
CREATE TABLE IF NOT EXISTS consensus (study_id TEXT NOT NULL REFERENCES studies(study_id) ON DELETE CASCADE, cand_id INTEGER, candidate_uid TEXT,
  status TEXT, effective_call TEXT, provenance_class TEXT, primary_eligible INTEGER, rule TEXT, n_expert_calls INTEGER, n_abstentions INTEGER,
  adjudicated_by TEXT, PRIMARY KEY (study_id, cand_id));
CREATE TABLE IF NOT EXISTS missed_lesions (study_id TEXT NOT NULL REFERENCES studies(study_id) ON DELETE CASCADE, missed_id TEXT, reviewer TEXT,
  role TEXT, provenance_class TEXT, eligible INTEGER, vox_i REAL, vox_j REAL, vox_k REAL, detector_fate TEXT, context TEXT, time TEXT, source TEXT,
  PRIMARY KEY (study_id, missed_id));
CREATE TABLE IF NOT EXISTS predictions (study_id TEXT NOT NULL REFERENCES studies(study_id) ON DELETE CASCADE, model_version TEXT, run TEXT,
  cand_id INTEGER, candidate_uid TEXT, score REAL, band TEXT, status TEXT, components TEXT, created TEXT, source TEXT,
  source_kind TEXT CHECK (source_kind = 'model_prediction'), PRIMARY KEY (study_id, model_version, run, cand_id));
CREATE TABLE IF NOT EXISTS corrections (correction_key TEXT PRIMARY KEY, study_id TEXT NOT NULL REFERENCES studies(study_id) ON DELETE CASCADE,
  candidate_uid TEXT, event_type TEXT, responsible_component TEXT, responsible_version TEXT, expert_basis TEXT, eligible INTEGER, source TEXT);
"""


class PensieveError(RuntimeError):
    pass


def _scripts():
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (os.path.join(os.path.dirname(os.path.dirname(here)), "scripts"),):
        if os.path.isdir(d) and d not in sys.path: sys.path.insert(0, d)


def path(base): return os.path.join(base, "percival", "pensieve", "pensieve_index.db")
def status_path(base): return os.path.join(base, "percival", "pensieve", "status.json")


def _uid(sid, hemi, i, j, k, v):
    """stable candidate identity: study + hemisphere + rounded voxel centroid + volume (the reviewer's fingerprint). The same lesion found
    again with the same fingerprint keeps its id; re-attached calls are recorded with attached_by (ledger matching decision)."""
    key = f"{sid}|{hemi or ''}|{round(float(i))}|{round(float(j))}|{round(float(k))}|{round(float(v), 1)}"
    return f"{sid}:{hashlib.sha256(key.encode()).hexdigest()[:12]}"


def _rel(base, p): return os.path.relpath(p, base)


def _study_rows(base, sid, patient_ref=None):
    """every row PENSIEVE holds for one study, from the authoritative records (read only)"""
    _scripts()
    import pandas as pd
    import call_ledger as CL
    import review_roles as RR
    from uengine.percival.architecture import detector_version
    rd = os.path.join(base, "review"); cp = os.path.join(rd, f"{sid}_candidates.csv")
    if not os.path.exists(cp): raise PensieveError(f"{sid}: no candidate list (review/{sid}_candidates.csv)")
    cand = pd.read_csv(cp); dv = detector_version(base, sid); ver = dv.get("version") or "albus:unversioned"
    R = {t: [] for t in TABLES}
    R["studies"].append(dict(study_id=sid, patient_ref=patient_ref, detector_version=ver, n_candidates=int(len(cand)), source=_rel(base, cp)))
    uid = {}
    for r in cand.itertuples():
        g = lambda c, d=None: getattr(r, c) if hasattr(r, c) else d
        u = _uid(sid, g("hemi", ""), g("vox_i", 0), g("vox_j", 0), g("vox_k", 0), g("volume_mm3", 0)); uid[int(r.cand_id)] = u
        R["candidates"].append(dict(candidate_uid=u, study_id=sid, cand_id=int(r.cand_id), hemi=str(g("hemi", "") or ""), vox_i=float(g("vox_i", 0)),
                                    vox_j=float(g("vox_j", 0)), vox_k=float(g("vox_k", 0)), volume_mm3=float(g("volume_mm3", 0)), detector_version=ver,
                                    source=_rel(base, cp), source_kind="detector_output"))
    E = CL.effective(base, sid); roles = RR.current(base)
    for row in E.get("rows", []):
        cid = int(row["cand_id"]); u = uid.get(cid)
        for e in row.get("history") or []:
            ev = e.get("evidence") or {}
            key = hashlib.sha256(json.dumps([sid, e.get("reviewer"), e.get("file"), e.get("row_key"), e.get("time"), e.get("call"), cid],
                                            default=str).encode()).hexdigest()[:20]
            att = "carried (lineage)" if e.get("carried") else "re-attached (fingerprint)" if e.get("matched") else "same candidate"
            R["expert_calls"].append(dict(event_key=key, study_id=sid, candidate_uid=u, cand_id=cid, reviewer=e.get("reviewer"),
                                          role=e.get("role") or RR.role_of(base, e.get("reviewer", ""), roles), call=e.get("call"),
                                          read_phase=ev.get("read_phase"), ai_visible=None if ev.get("ai_visible") is None else str(ev.get("ai_visible")),
                                          provenance_class=e.get("class"), attached_by=att, time=e.get("time"), source=e.get("file"),
                                          source_kind="expert_human"))
        a = row.get("adjudication") or {}
        R["consensus"].append(dict(study_id=sid, cand_id=cid, candidate_uid=u, status=row.get("status"), effective_call=row.get("effective_call") or "",
                                   provenance_class=row.get("provenance_class") or "", primary_eligible=int(bool(row.get("primary_eligible"))),
                                   rule=row.get("source_rule") or "", n_expert_calls=int(row.get("n_expert_calls") or 0),
                                   n_abstentions=int(row.get("n_abstentions") or 0), adjudicated_by=a.get("by")))
        if row.get("status") in ("resolved", "adjudicated") and CL.call_class(row.get("effective_call") or "") == "negative" and u:
            R["corrections"].append(dict(correction_key=f"fp|{u}", study_id=sid, candidate_uid=u, event_type="false_positive_candidate",
                                         responsible_component="ALBUS", responsible_version=ver,
                                         expert_basis=f"{row.get('status')} {row.get('effective_call')} ({row.get('provenance_class') or 'no class'})",
                                         eligible=int(bool(row.get("primary_eligible"))), source="call_ledger"))
    mp = os.path.join(rd, f"{sid}_missed.csv")
    if os.path.exists(mp):
        m = pd.read_csv(mp, dtype=str).fillna("")
        verified = RR.verified_reviewers(base, sid)
        for mr in m.to_dict("records"):
            mid = str(mr.get("missed_id", "")).strip()
            if not mid: continue
            rev = mr.get("reviewer", ""); role = RR.role_of(base, rev, roles)
            # the same rule as percival_gui.label_summary (Phase 3A.3)
            klass = ("verified_blind_post_3A" if mr.get("read_phase") == "initial" and mr.get("ai_visible") == "False" else
                     "not_blind_post_3A" if mr.get("read_phase") else
                     "historical_blinding_verified" if CL.slug(rev) in verified else "historical_blinding_unknown")
            elig = int(role == "expert" and klass in CL.PRIMARY_ELIGIBLE)
            f = lambda c: float(mr[c]) if str(mr.get(c, "")).strip() else None
            R["missed_lesions"].append(dict(study_id=sid, missed_id=mid, reviewer=rev, role=role, provenance_class=klass, eligible=elig,
                                            vox_i=f("vox_i"), vox_j=f("vox_j"), vox_k=f("vox_k"), detector_fate=mr.get("detector_fate", ""),
                                            context=mr.get("context", ""), time=mr.get("time", ""), source=_rel(base, mp)))
            R["corrections"].append(dict(correction_key=f"miss|{sid}|{mid}", study_id=sid, candidate_uid=None, event_type="missed_lesion",
                                         responsible_component="ALBUS", responsible_version=ver,
                                         expert_basis=f"missed-cSS mark by {rev} ({role}, {klass}); detector fate: {mr.get('detector_fate') or 'not recorded'}",
                                         eligible=elig, source=_rel(base, mp)))
    for lp in sorted(glob.glob(os.path.join(base, "percival", "ledger", sid, "*.json"))):
        try:
            with open(lp) as fh: L = json.load(fh)
        except Exception as e: raise PensieveError(f"{sid}: unreadable prediction ledger {_rel(base, lp)} ({type(e).__name__})")
        for c in L.get("candidates") or []:
            cid = int(c["cand_id"])
            R["predictions"].append(dict(study_id=sid, model_version=str(L.get("model")), run=str(L.get("run")), cand_id=cid, candidate_uid=uid.get(cid),
                                         score=c.get("percival_score"), band=c.get("band"), status=c.get("status"),
                                         components=json.dumps(c.get("components") or {}, sort_keys=True), created=L.get("created"),
                                         source=_rel(base, lp), source_kind="model_prediction"))
    return R


def _connect(p):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    con = sqlite3.connect(p, timeout=30.0); con.execute("PRAGMA foreign_keys = ON;"); con.executescript(DDL); return con


def _insert(con, R):
    for t in TABLES:
        for r in R[t]:
            cols = sorted(r); con.execute(f"INSERT INTO {t} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", [r[c] for c in cols])


def digest(con):
    """content digest of every memory table (order-independent) - equal digests = identical memory"""
    h = hashlib.sha256()
    for t in TABLES:
        rows = sorted(json.dumps(list(r), default=str) for r in con.execute(f"SELECT * FROM {t}"))
        h.update(t.encode()); [h.update(x.encode()) for x in rows]
    return h.hexdigest()[:20]


def _status(base, **kw):
    p = status_path(base); os.makedirs(os.path.dirname(p), exist_ok=True)
    try:
        with open(p) as f: S = json.load(f)
    except Exception: S = {}
    S.update(kw, at=time.strftime("%Y-%m-%d %H:%M:%S"))
    with open(p + ".tmp", "w") as f: json.dump(S, f, indent=1, sort_keys=True, default=str)
    os.replace(p + ".tmp", p); return S


def studies_on_disk(base):
    return sorted(os.path.basename(p)[:-len("_candidates.csv")] for p in glob.glob(os.path.join(base, "review", "*_candidates.csv")))


def rebuild(base, studies=None, patient_of=None):
    """rebuild the whole index from the authoritative records into a temporary file, then replace it atomically.
    -> dict(ok, digest, counts, errors). A study that cannot be read is reported (and left out), never silently dropped."""
    studies = studies_on_disk(base) if studies is None else list(studies)
    p = path(base); tmp = p + ".rebuild"
    for x in (tmp, tmp + "-wal", tmp + "-shm"):
        if os.path.exists(x): os.remove(x)
    errors = []
    con = _connect(tmp)
    try:
        for sid in sorted(studies):
            try:
                R = _study_rows(base, sid, patient_of(sid) if patient_of else None)
                with con: _insert(con, R)
            except Exception as e: errors.append(f"{sid}: {type(e).__name__}: {str(e)[:200]}")
        d = digest(con)
        counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
        with con:
            con.execute("INSERT OR REPLACE INTO meta VALUES ('schema', ?)", (SCHEMA_VERSION,))
            con.execute("INSERT OR REPLACE INTO meta VALUES ('digest', ?)", (d,))
    finally: con.close()
    os.replace(tmp, p)
    S = _status(base, last_rebuild=dict(ok=not errors, digest=d, counts=counts, errors=errors, studies=len(studies)))
    return dict(ok=not errors, digest=d, counts=counts, errors=errors, path=p, status=S)


def update_study(base, sid, patient_of=None):
    """replace one study's memory in one transaction (after a review save). -> dict(ok, error). Never raises; failures recorded."""
    try:
        old_ref = None
        con = _connect(path(base))
        try:
            r = con.execute("SELECT patient_ref FROM studies WHERE study_id=?", (sid,)).fetchone(); old_ref = r[0] if r else None
            R = _study_rows(base, sid, patient_of(sid) if patient_of else old_ref)
            with con:
                con.execute("DELETE FROM studies WHERE study_id=?", (sid,))     # cascades to every table of the study
                _insert(con, R)
            d = digest(con)
        finally: con.close()
        _status(base, last_update=dict(ok=True, study=sid, digest=d))
        return dict(ok=True, study=sid, digest=d, counts={t: len(R[t]) for t in TABLES})
    except Exception as e:
        msg = f"{type(e).__name__}: {str(e)[:300]}"
        try: _status(base, last_update=dict(ok=False, study=sid, error=msg))
        except Exception: pass
        return dict(ok=False, study=sid, error=msg)


def summary(base):
    """what the GUI shows: counts per table, separation check, status (read only; no index -> 'not built')"""
    p = path(base); st = {}
    try:
        with open(status_path(base)) as f: st = json.load(f)
    except Exception: pass
    if not os.path.exists(p): return dict(built=False, status=st, path=p)
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
        sep = con.execute("SELECT COUNT(*) FROM expert_calls WHERE source_kind != 'expert_human'").fetchone()[0] + \
              con.execute("SELECT COUNT(*) FROM predictions WHERE source_kind != 'model_prediction'").fetchone()[0]
        corr = [dict(zip(("study_id", "candidate_uid", "event_type", "responsible_component", "responsible_version", "expert_basis", "eligible"), r))
                for r in con.execute("SELECT study_id, candidate_uid, event_type, responsible_component, responsible_version, expert_basis, eligible "
                                     "FROM corrections ORDER BY study_id, correction_key LIMIT 200")]
        studies = [dict(zip(("study_id", "detector_version", "n_candidates"), r)) for r in
                   con.execute("SELECT study_id, detector_version, n_candidates FROM studies ORDER BY study_id")]
        dg = digest(con)
    finally: con.close()
    return dict(built=True, path=p, counts=counts, separation_ok=sep == 0, digest=dg, corrections=corr, studies=studies, status=st,
                schema=SCHEMA_VERSION)


def history(base, sid, cand_id):
    """one candidate's memory: identity, every expert call (with provenance), consensus, predictions of every model"""
    p = path(base)
    if not os.path.exists(p): return dict(built=False)
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True); con.row_factory = sqlite3.Row
    try:
        c = con.execute("SELECT * FROM candidates WHERE study_id=? AND cand_id=?", (sid, int(cand_id))).fetchone()
        q = lambda t, extra="": [dict(r) for r in con.execute(f"SELECT * FROM {t} WHERE study_id=? AND cand_id=? {extra}", (sid, int(cand_id)))]
        return dict(built=True, candidate=dict(c) if c else None, expert_calls=q("expert_calls", "ORDER BY time"), consensus=q("consensus"),
                    predictions=q("predictions", "ORDER BY created"))
    finally: con.close()


def reader_agreement(base, blind_only=True):
    """Stage 6 inter-reader agreement baseline: Cohen's kappa (cSS vs not cSS; Unsure = abstention, excluded) between every pair of EXPERT
    readers on the candidates both called - each reader's LAST call, by default only blind initial reads. Patient-level variability is not
    modelled here (candidate-level kappa); CI by bootstrap over studies."""
    import numpy as _np
    p = path(base)
    if not os.path.exists(p): return dict(available=False, reason="PENSIEVE index not built yet")
    con = _connect(p)
    try:
        q = "SELECT study_id, candidate_uid, reviewer, call, read_phase, time FROM expert_calls WHERE role='expert'"
        rows = con.execute(q).fetchall()
    finally: con.close()
    last = {}
    for sid, uid, rev, call, phase, t in sorted(rows, key=lambda r: str(r[5])):
        if blind_only and phase not in ("initial", None, ""): continue
        c = str(call or "")
        if c in ("cSS", "Vessel", "Vein", "Normal", "Artifact", "Microbleed", "Near ICH"): last[(sid, uid, rev)] = (1 if c == "cSS" else 0)
    revs = sorted({k[2] for k in last}); out = []
    for i, a in enumerate(revs):
        for b in revs[i + 1:]:
            shared = [(k[0], last[k], last[(k[0], k[1], b)]) for k in last if k[2] == a and (k[0], k[1], b) in last]
            if len(shared) < 5: out.append(dict(a=a, b=b, n=len(shared), kappa=None, note="fewer than 5 shared calls")); continue
            S = _np.array([s for s, _, _ in shared]); A = _np.array([x for _, x, _ in shared]); Bv = _np.array([y for _, _, y in shared])
            def kap(x, y):
                po = float(_np.mean(x == y)); pe = float(x.mean() * y.mean() + (1 - x.mean()) * (1 - y.mean()))
                return None if pe >= 1 else (po - pe) / (1 - pe)
            r = _np.random.default_rng(0); us = _np.unique(S); bs = []
            for _ in range(300):
                m = _np.concatenate([_np.where(S == u)[0] for u in r.choice(us, len(us))]); k_ = kap(A[m], Bv[m])
                if k_ is not None: bs.append(k_)
            out.append(dict(a=a, b=b, n=len(shared), studies=int(len(us)), kappa=kap(A, Bv), agreement=float(_np.mean(A == Bv)),
                            kappa_ci=[float(_np.percentile(bs, 2.5)), float(_np.percentile(bs, 97.5))] if len(bs) > 50 else None))
    return dict(available=bool(out), pairs=out, readers=revs, basis="expert readers' last " + ("blind initial " if blind_only else "") +
                "calls on the same candidates; cSS vs not cSS, Unsure excluded; bootstrap over studies")
