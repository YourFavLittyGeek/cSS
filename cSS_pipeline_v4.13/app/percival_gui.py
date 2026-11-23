"""percival_gui.py - the app side of PERCIVAL SCORE (v5.22). Everything runs on this computer (numpy); nothing is uploaded; no external
model or AI service is used (see docs/percival_app/LOCAL_AI_ARCHITECTURE.md).

  authorize()        the user's one-time switch for LOCAL learning on this project's MRI (app_data/ml_authorization.json, audited);
                     synthetic SYN studies of a synthetic project never need it
  gather(sid)        candidate rows of one study: MATH (score_v4), the 5 Unified-Score predictors (uscore/features, extracted when
                     missing), the 9 detector characteristics, the image maps of the candidate's MRI patch, the expert label (effective
                     reviewer call: definite cSS = 1, definite mimic = 0; indeterminate / out of scope are not used), the locked-test flag
  integrity()        data checks before a cycle: uncertain labels excluded, reviewer conflicts flagged, duplicate studies (same images)
                     counted once, per-patient weighting inside the models
  train_async()      ONE controlled training cycle (meta.train_cycle): components, meta-model discovery, calibration, thresholds, locked-test
                     evaluation, acceptance; promoted only when it passes; every version kept in the registry (registry/vNNN/)
  maybe_cycle()      the watcher starts a cycle when N newly finished studies have accumulated (setting percival_cycle_n, default 5) -
                     the active model is never changed after a single review
  score_study()      Percival Score 0-100 + band + status per candidate with the active model; written to the PREDICTION LEDGER
                     ledger/ID/<model>__<run>.json (immutable - a new model never rewrites an old assessment) and scores/ID.json (current)
  promote / rollback any registry version can be made active; the previous one is kept.
  snapshot_reviews() v5.23: one immutable record per final expert review (reviews/ID/<reviewer>__<saved>.json): the labels, whether the
                     Percival Score was visible to the reviewer, the prediction that existed when the review was saved, coordinates,
                     measurements, patch hashes, processing / model versions - the provenance of the local learning dataset.
Files name studies by their internal key; no identifier is written here."""
import glob, hashlib, json, os, subprocess, sys, threading, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "unified_engine"), os.path.join(ROOT, "unified_score")):
    if p not in sys.path: sys.path.insert(0, p)
CTX = {}; LOCK = threading.Lock(); GLOCK = threading.RLock(); JOB = dict(state="idle", log=[], progress=0.0, error="")


STORE = dict(ok=True, error="", migration=None)
def init(**ctx):
    """v5.24: the Percival store is checked and, when needed, migrated (backup first) before anything reads it"""
    CTX.update(ctx); _LCACHE.clear()
    if ctx.get("SC") and ctx["SC"] not in sys.path: sys.path.insert(0, ctx["SC"])
    from uengine.percival import store as ST
    try: STORE.update(ok=True, error="", migration=ST.migrate(B())); _interrupted_runs()
    except Exception as e: STORE.update(ok=False, error=str(e), migration=None)
def identity(sid):
    """v5.25: patient identity of a study -> dict(status, patient, detail). The app passes identity_of (identity registry: verified /
    declared / assumed / unconfirmed / missing / conflict). Harnesses that pass only patient_of declare their mapping in code."""
    if CTX.get("identity_of"): return CTX["identity_of"](sid)
    p = CTX["patient_of"](sid)
    return dict(status="declared" if p else "missing", patient=p or None, detail="mapping supplied by the caller" if p else "no patient")
def identity_ok(sid): return identity(sid)["status"] in ("verified", "declared")
def B(): return CTX["B"]
def P(*a):
    if not STORE["ok"]: raise RuntimeError("Percival data store unavailable: " + STORE["error"])
    return os.path.join(B(), "percival", *a)
def _jl(p, d):
    try:
        with open(p) as f: return json.load(f)
    except Exception: return d
def _js(p, o):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = f"{p}.{os.getpid()}.{threading.get_ident()}.tmp"           # v5.24: unique per writer (re-scoring after a promotion and a
    with open(tmp, "w") as f: json.dump(o, f, default=float)          # reviewer's score request may write the same file at once)
    os.replace(tmp, p)
def log(msg, prog=None):
    """every log line of a running cycle is real work reported by the engine: it also beats the heartbeat and records the stage. A
    requested cancellation is honoured here (cooperative: the engine stops at its next progress report, before any artifact is written)."""
    with LOCK:
        now = time.time()
        JOB["log"] = (JOB["log"] + [f"{time.strftime('%H:%M:%S')} {msg}"])[-300:]
        if prog is not None:
            JOB["progress"] = max(float(prog), JOB.get("progress", 0.0))           # never backwards
            JOB.setdefault("samples", []).append((now, JOB["progress"])); JOB["samples"] = JOB["samples"][-60:]
        if JOB.get("state") in ACTIVE_STATES:
            JOB["heartbeat"] = now; JOB["stage"] = _stage_of(msg, JOB.get("stage", "")); JOB.pop("stall", None)
        cancel = JOB.get("cancel") and JOB.get("state") in ACTIVE_STATES
    if cancel: raise Cancelled("cancelled by " + str(JOB.get("cancel_by", "you")))


# ------------------------------------------------------------------ v5.25 Training Center job monitor
class Cancelled(Exception): pass
ACTIVE_STATES = ("preparing", "running")
TERMINAL_STATES = ("finished", "failed", "cancelled", "interrupted")
TRANSITIONS = dict(idle={"preparing"}, preparing={"running", "failed", "cancelled"}, running={"finished", "failed", "cancelled"},
                   finished={"preparing"}, failed={"preparing"}, cancelled={"preparing"}, interrupted={"preparing"})
STATE_LABEL = dict(idle="Idle", preparing="Preparing dataset", running="Training", finished="Completed", failed="Failed", cancelled="Cancelled",
                   interrupted="Interrupted")
# stage-aware stall limits (seconds without any reported work): dataset gathering reads MRI patches study by study; a training stage
# reports at least once per fold (nested cross-fitting: once per inner step). Overridable for tests: CSS_PERCIVAL_STALL_S
STALL_S = dict(preparing=300, components=600, nested=900, discovery=600, final=600, evaluation=300, registering=120)
def _stage_of(msg, cur):
    m = msg.lower()
    for key, st in (("nested", "nested"), ("meta-model discovery", "discovery"), ("final fit", "final"), ("locked test", "evaluation"),
                    ("component", "components"), ("image models", "components"), ("characteristic models", "components"),
                    ("dataset", "preparing"), ("eligible of", "preparing"), ("registered", "registering"), ("cycle started", "preparing")):
        if key in m: return st
    return cur or "preparing"


def _transition(new, **kw):
    """state machine of the training job: invalid transitions are refused (a completed job can never become running or stalled)"""
    with LOCK:
        old = JOB.get("state", "idle")
        if new not in TRANSITIONS.get(old, set()): raise RuntimeError(f"invalid training-job transition {old} -> {new}")
        JOB.update(state=new, **kw); JOB.setdefault("transitions", []).append(dict(frm=old, to=new, at=time.strftime("%Y-%m-%d %H:%M:%S")))
        if new in TERMINAL_STATES: JOB["ended"] = time.time(); JOB.pop("stall", None)


def _proc_resources():
    """this app's process: CPU % since the previous sample, current resident memory (ps) and peak resident memory (ru_maxrss);
    system CPU / RAM from the app's sysinfo. GPU: the Percival engine is numpy on the CPU - no GPU is used, so none is monitored
    (reported as such, never invented). Distinguishes peak RAM from current measured RAM."""
    import resource, subprocess
    out = dict(gpu="not used (CPU engine)")
    try:
        ru = resource.getrusage(resource.RUSAGE_SELF); cpu_t = ru.ru_utime + ru.ru_stime; now = time.time()
        prev = JOB.get("_cpu_prev")
        if prev and now > prev[1]: out["process_cpu_pct"] = round(100 * (cpu_t - prev[0]) / (now - prev[1]), 1)
        JOB["_cpu_prev"] = (cpu_t, now)
        peak_bytes = ru.ru_maxrss if sys.platform == "darwin" else ru.ru_maxrss * 1024
        out["process_ram_peak_gb"] = round(peak_bytes / 1e9, 2)
        rss = subprocess.run(["ps", "-o", "rss=", "-p", str(os.getpid())], capture_output=True, text=True, timeout=5).stdout.strip()
        if rss:
            curr_gb = round(int(rss) / 1e6, 2)
            out["process_ram_current_gb"] = curr_gb
            out["process_ram_gb"] = curr_gb
    except Exception: pass
    try:
        si = CTX["sysinfo"]() if CTX.get("sysinfo") else None
        if si: out.update(system_cpu_pct=si.get("cpu_pct"), system_ram_pct=si.get("mem_pct"), system_ram_used_gb=si.get("mem_used"),
                          system_ram_total_gb=si.get("mem_total"), disk_free_gb=si.get("disk_free"))
    except Exception: pass
    return out


def _eta(now):
    """remaining time from the progress actually reported: rate over the recent samples; range from the spread of recent rates. Marked
    unreliable early (< 10 % done or < 3 samples) - the cycle's stages do not take equal time."""
    p = JOB.get("progress", 0.0); st = JOB.get("started") or now; el = now - st; smp = JOB.get("samples", [])
    if p <= 0 or p >= 1 or len(smp) < 2: return dict(eta_s=None, eta_range_s=None, reliable=False, note="estimating")
    rem = el * (1 - p) / p
    rates = [(b[1] - a[1]) / (b[0] - a[0]) for a, b in zip(smp[-10:], smp[-9:]) if b[0] > a[0] and b[1] > a[1]]
    if len(rates) >= 3:
        lo_r, hi_r = np.percentile(rates, 25), np.percentile(rates, 75)
        rng = [(1 - p) / hi_r if hi_r > 0 else None, (1 - p) / lo_r if lo_r > 0 else None]
    else: rng = [rem * 0.6, rem * 1.8]
    rel = p >= 0.1 and len(smp) >= 3
    return dict(eta_s=round(rem), eta_range_s=[None if x is None else round(min(x, 86400 * 3)) for x in rng], reliable=rel,
                note="" if rel else "early estimate - stages differ in length")


def _stall_check(now):
    """a warning, never a kill: no reported work for longer than the current stage's limit while the job is active"""
    if JOB.get("state") not in ACTIVE_STATES: JOB.pop("stall", None); return None
    lim = float(os.environ.get("CSS_PERCIVAL_STALL_S") or STALL_S.get(JOB.get("stage", ""), 600)); age = now - JOB.get("heartbeat", now)
    th = JOB.get("thread")
    if th is not None and not th.is_alive():
        JOB["stall"] = dict(reason="the training thread has stopped without reporting an end (dead worker)", since=time.strftime("%H:%M:%S", time.localtime(JOB.get("heartbeat", now))), age_s=round(age))
    elif age > lim:
        JOB["stall"] = dict(reason=f"no progress reported for {age:.0f} s in stage '{JOB.get('stage')}' (limit {lim:.0f} s) - the job is still alive and is not stopped; "
                                   "cancel it if it does not recover", since=time.strftime("%H:%M:%S", time.localtime(JOB.get("heartbeat", now))), age_s=round(age))
    else: JOB.pop("stall", None)
    return JOB.get("stall")


def job_state():
    """live training job for the Training Center: state, stage, progress, elapsed, ETA (+ range, reliability), heartbeat age, stall warning,
    resources, log tail, run id"""
    now = time.time()
    with LOCK:
        st = _stall_check(now); j = {k: v for k, v in JOB.items() if k not in ("thread", "_cpu_prev", "samples")}
        start = JOB.get("started"); end = JOB.get("ended") if JOB.get("state") in TERMINAL_STATES else None
        j.update(state_label=STATE_LABEL.get(JOB.get("state", "idle"), JOB.get("state")), stalled=bool(st),
                 elapsed_s=round((end or now) - start) if start else None, heartbeat_age_s=round(now - JOB["heartbeat"]) if JOB.get("heartbeat") else None,
                 run=RUN.get("id"), log=JOB.get("log", [])[-40:], resume_supported=False,
                 retry_note="retry restarts the cycle from the beginning (no partial-result resume: a cycle is a single reproducible computation)")
        if JOB.get("state") in ACTIVE_STATES: j.update(eta=_eta(now))
    j["resources"] = _proc_resources() if j.get("state") in ACTIVE_STATES else JOB.get("resources_last")
    if j.get("state") in ACTIVE_STATES:
        with LOCK:
            JOB["resources_last"] = j["resources"]; pk = JOB.setdefault("resources_peak", {})
            for k in ("process_cpu_pct", "process_ram_gb", "system_ram_pct"):
                if isinstance(j["resources"].get(k), (int, float)): pk[k] = max(pk.get(k, 0), j["resources"][k])
            j["resources_peak"] = dict(pk)
    return j


def cancel_training(by="app user"):
    with LOCK:
        if JOB.get("state") not in ACTIVE_STATES: return dict(ok=False, error="no training cycle is running")
        JOB.update(cancel=True, cancel_by=by, cancel_at=time.strftime("%Y-%m-%d %H:%M:%S"))
        JOB["log"] = (JOB["log"] + [f"{time.strftime('%H:%M:%S')} cancellation requested by {by} - stopping at the next step; nothing is registered"])[-300:]
    return dict(ok=True, note="the cycle stops at its next progress report; no model is registered")


# ------------------------------------------------------------------ authorisation
def auth_path(): return os.path.join(B(), "app_data", "ml_authorization.json")
def authorized(): return bool(_jl(auth_path(), {}).get("local_learning"))
def authorize(on, by="app user"):
    d = _jl(auth_path(), {"history": []}); d["local_learning"] = bool(on)
    d.setdefault("history", []).append(dict(at=time.strftime("%Y-%m-%d %H:%M:%S"), by=by, on=bool(on)))
    d["scope"] = "local learning on this project's MRI and expert reviews, on this computer only; no upload; no external AI service"
    _js(auth_path(), d); return dict(ok=True, authorized=bool(on))
def synthetic(sid):
    from uengine.imaging.index import is_synthetic_study
    return is_synthetic_study(B(), sid)
def may_read(sid): return authorized() or synthetic(sid)


# ------------------------------------------------------------------ one study's candidates
_LCACHE = {}
def _ledger_mod():
    import review_calls_gui as RCG
    return RCG._ledger(B())


def _kind(call):
    import label_schema as LS
    if not isinstance(call, str) or not call.strip(): return None
    try: cls, _, _ = LS.from_call(call.strip())
    except Exception: return "unrecognised"                           # v5.24: never silently dropped - reported (Data integrity)
    return {"definite_css": "css", "definite_mimic": "mimic", "indeterminate": "uncertain", "out_of_scope": "out_of_scope"}.get(cls)


def _historical(sid, cand):
    """v5.24: expert calls of an EARLIER version / project for this examination (historical/ID/review/, written by 'bring in earlier
    processing' and by the review recovery). Matched to the current candidates by fingerprint (centroid within 2 voxels, volume within
    15 %), never by number. Per-reviewer files when present, else the shared calls file. -> {cand_id: [dict(call, reviewer, time, file)]}"""
    import pandas as pd
    from css_common import FP, norm_call
    L = _ledger_mod()                                                   # fingerprint matching lives in the call ledger (one boundary)
    if not hasattr(L, "match_one"):                                     # project scripts older than v5.24: use this package's ledger
        import importlib.util
        sp = importlib.util.spec_from_file_location("call_ledger_v524", os.path.join(ROOT, "scripts", "call_ledger.py"))
        L = importlib.util.module_from_spec(sp); sp.loader.exec_module(L)
    d = os.path.join(B(), "historical", sid, "review")
    files = sorted(glob.glob(os.path.join(d, "*_calls_*.csv"))) or sorted(glob.glob(os.path.join(d, "*_calls.csv")))
    out = {}
    for f in files:
        try: t = pd.read_csv(f, dtype=str)
        except Exception: continue
        if "call" not in t.columns or not all(c in t.columns for c in FP) or not len(cand): continue
        rev = os.path.basename(f).split("_calls_", 1)[1][:-4] if "_calls_" in os.path.basename(f) else "earlier version"
        for _, r in t.iterrows():
            call = norm_call(r.get("call"))
            if not isinstance(call, str) or not call.strip(): continue
            cid = L.match_one(cand, r)
            if cid is not None: out.setdefault(cid, []).append(dict(call=call.strip(), reviewer=str(r.get("reviewer")) if isinstance(r.get("reviewer"), str) else rev,
                                                                    time=str(r.get("time", "")), file=os.path.relpath(f, B())))
    return out


def label_summary(sid):
    """v5.24: the expert labels of one study.
    Source 1 (current reviews): the reviewer's CALL LEDGER (scripts/call_ledger.py) - the effective calls the Review screen shows: every
      reviewer file (or the legacy shared ID_calls.csv of older versions), old call names ('Vein' -> Vessel), calls re-attached by
      fingerprint after re-detection, calls carried over through a confident lineage match, and the effective-call policy.
    Source 2 (historical reviews, Settings percival_use_historical, default on): calls from an earlier version / project of the same
      examination (historical/ID/review/), matched by fingerprint - used only for candidates without a current call.
    Before v5.24 only review/ID_calls.csv was read by candidate NUMBER: 'Vein' calls were dropped, a re-detected study could attach a call
    to the wrong lesion, and reviews brought in from an earlier project were never used.
    -> dict(labels {cand_id: 1/0}, detail {cand_id: dict(kind, y, call, source, reviewer, conflict, calls)}, css, mimic, unused, stale,
            conflicts, historical, state, state_label)"""
    import label_schema as LS
    files = sorted(glob.glob(os.path.join(B(), "review", f"{sid}_*"))) + sorted(glob.glob(os.path.join(B(), "historical", sid, "review", "*")))
    key = [(os.path.relpath(f, B()), round(os.path.getmtime(f), 3)) for f in files if os.path.isfile(f)]
    try: L = _ledger_mod(); pol = L.load_policy(B())
    except Exception as e: return dict(labels={}, detail={}, css=0, mimic=0, unused=0, stale=0, conflicts=0, historical=0, state="error",
                                       state_label="labels unavailable", error=f"{type(e).__name__}: {e}"[:200])
    use_h = CTX["SET"].get("percival_use_historical", True)
    key += [json.dumps(pol, sort_keys=True, default=str), use_h]
    c = _LCACHE.get(sid)
    if c and c[0] == key: return c[1]
    det = {}
    try:
        cand = L.candidates(B(), sid); E = L.effective(B(), sid, "", pol, cand)
        for r in E["rows"]:
            call = r.get("effective_call") or ""
            if not call: continue
            last = {}
            for e in r.get("history") or []: last[e["reviewer"]] = e["call"]
            ks = {_kind(x) for x in last.values()} & {"css", "mimic"}
            k = _kind(call)
            det[int(r["cand_id"])] = dict(kind=k, y=1 if k == "css" else 0 if k == "mimic" else None, call=call, source="review",
                                          reviewer=r.get("source_reviewer", ""), conflict=len(ks) > 1, calls=last)
        n_hist = 0
        if use_h:
            for cid, H in _historical(sid, cand).items():
                if cid in det: continue                                     # a current call always wins
                last = {}
                for e in H: last[e["reviewer"]] = e["call"]
                ks = {_kind(x) for x in last.values()} & {"css", "mimic"}; call = H[-1]["call"]; k = _kind(call)
                det[cid] = dict(kind=k, y=1 if k == "css" else 0 if k == "mimic" else None, call=call, source="historical",
                                reviewer=H[-1]["reviewer"], conflict=len(ks) > 1, calls=last, file=H[-1]["file"]); n_hist += 1
        out = {cid: d["y"] for cid, d in det.items() if d["y"] is not None}
        st = L.review_state(B(), sid, "", pol)
        res = dict(labels=out, detail=det, css=sum(out.values()), mimic=len(out) - sum(out.values()),
                   unused=sum(1 for d in det.values() if d["y"] is None), stale=len(E.get("stale") or []),
                   unrecognised=sorted({d["call"] for d in det.values() if d["kind"] == "unrecognised"}),
                   conflicts=sum(1 for d in det.values() if d["conflict"]), historical=n_hist,
                   state=st.get("state", ""), state_label=st.get("label", ""), reviewers=E.get("reviewers", []), n_candidates=len(cand))
    except Exception as e:
        res = dict(labels={}, detail={}, css=0, mimic=0, unused=0, stale=0, conflicts=0, historical=0, state="error",
                   state_label="labels unavailable", error=f"{type(e).__name__}: {e}"[:200])
    _LCACHE[sid] = (key, res); return res


def _labels(sid):
    S = label_summary(sid); return S["labels"], S["unused"]


def _conflicts(sid):
    """candidates on which reviewers disagree (any two reviewer files with different calls) - reported; the effective call is used"""
    import pandas as pd
    calls = {}
    for f in glob.glob(os.path.join(B(), "review", f"{sid}_calls_*.csv")):
        try:
            d = pd.read_csv(f, dtype=str).fillna("")
            for _, r in d.iterrows(): calls.setdefault(str(r["cand_id"]), set()).add(r.get("call", ""))
        except Exception: pass
    return sorted(c for c, v in calls.items() if len(v - {""}) > 1)


def _predictors(sid):
    p = os.path.join(B(), "uscore", "features", f"{sid}.json")
    if not os.path.exists(p):
        try:
            from uscore import pipeline as PL, common as CM
            class _AppCohort:
                synthetic = False
                def role(self, s): raise CM.CohortError("application")
            PL.extract_study(B(), sid, _AppCohort(), os.path.join(B(), "uscore"), application=True)
        except Exception as e: log(f"{CTX['label'](sid)}: predictors not extracted ({type(e).__name__})")
    d = _jl(p, None) or {}; from uengine.percival.meta import PREDICTORS; out = {}
    for r in d.get("records", []):
        F = r.get("F", {}); out[int(r["cand_id"])] = {k: (float(F[k]["value"]) if F.get(k, {}).get("status") == "reliable" and F[k].get("value") is not None else None) for k in PREDICTORS}
    return out


def _maps(sid):
    from uengine.imaging import patches as PT
    from uengine.percival.cnn import patch_maps
    try: E = PT.extract_study(B(), sid)
    except Exception as e: log(f"{CTX['label'](sid)}: image patches not made ({type(e).__name__}: {str(e)[:80]})"); return {}
    if E.get("blocked"): log(f"{CTX['label'](sid)}: image patches not made ({E['blocked'][:80]})"); return {}
    out = {}
    for k, a in E["patches"].items():
        if k[0] == "candidates":
            m = patch_maps(a)
            if m is not None: out[int(k[1])] = m
    return out


def gather(sid, labelled=True):
    """thread-safe (v5.23): the watcher's review snapshots and a training cycle may gather the same study at the same time"""
    with GLOCK: return _gather(sid, labelled)


def _gather(sid, labelled=True):
    import pandas as pd
    from uengine.percival.meta import CHAR, test_assignment
    cp = os.path.join(B(), "review", f"{sid}_candidates.csv")
    if not os.path.exists(cp): return []
    deps = [cp, os.path.join(B(), "uscore", "features", f"{sid}.json")]
    key = [round(os.path.getmtime(p), 3) if os.path.exists(p) else 0 for p in deps] + [int(may_read(sid))]
    cj, cz = P("cache", f"{sid}.json"), P("cache", f"{sid}.npz"); C = _jl(cj, {})
    if C.get("key") != key or C.get("v") != 3 or not os.path.exists(cz):
        cand = pd.read_csv(cp); pred = _predictors(sid); maps = _maps(sid) if may_read(sid) else {}
        rows = []
        for _, r in cand.iterrows():
            cid = int(r["cand_id"]); ch = {}
            for c in CHAR:
                src = "volume_mm3" if c == "log_volume_mm3" else c
                v = r.get(src) if src in cand.columns else None
                v = None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)
                ch[c] = (float(np.log(max(v, 1.0))) if c == "log_volume_mm3" and v is not None else v)
            rows.append(dict(study=sid, cand_id=cid, math=float(r["score_v4"]) if "score_v4" in cand.columns and not pd.isna(r["score_v4"]) else 0.0,
                             hemi=str(r["hemi"]) if "hemi" in cand.columns else "", pred=pred.get(cid, {}), char=ch, has_maps=cid in maps))
        os.makedirs(os.path.dirname(cz), exist_ok=True)
        with open(cz + ".tmp", "wb") as f_: np.savez_compressed(f_, **{str(k): v for k, v in maps.items()})
        os.replace(cz + ".tmp", cz)                                               # atomic: a reader never sees a half-written cache
        C = dict(key=key, v=3, rows=rows); _js(cj, C)
    with np.load(cz) as Zf: Z = {k: Zf[k] for k in Zf.files}
    rows = []; pat = CTX["patient_of"](sid) or None
    test = bool(pat) and test_assignment(pat, CTX["SET"].get("percival_test_fraction", 0.2))   # no patient: never trained on (eligibility)
    for r in C["rows"]:
        rows.append(dict(r, patient=pat, test=test, maps=Z.get(str(r["cand_id"]))))
    if labelled:
        L, _ = _labels(sid); rows = [dict(r, y=L[r["cand_id"]]) for r in rows if r["cand_id"] in L]
    return rows


# ------------------------------------------------------------------ selection + integrity
def _orphans(known):
    """studies with a candidate list AND reviewer calls in review/ that are not in the app's study list (e.g. reviewed with an older
    version and copied into this project) - listed so their labels are not silently ignored"""
    out = []
    for p in sorted(glob.glob(os.path.join(B(), "review", "*_candidates.csv"))):
        c = os.path.basename(p)[:-len("_candidates.csv")]
        if c in known or not c: continue
        if glob.glob(os.path.join(B(), "review", f"{c}_calls*.csv")): out.append(c)
    return out


def _study_list():
    pats = [dict(p, _orphan=False) for p in CTX["patients"]()]
    return pats + [dict(code=c, cohort="", _orphan=True) for c in _orphans({p["code"] for p in pats})]


def _cached_rows(sid):
    """feature / patch cache of a study when it exists (the screen never extracts; training does) -> {cand_id: row} or None"""
    C = _jl(P("cache", f"{sid}.json"), None)
    return None if not C else {int(r["cand_id"]): r for r in C.get("rows", [])}


def _examples(sid, meta, rows=None):
    """every CALLED candidate of one study with its eligibility (eligibility.py). rows: gathered rows (training) or None (screen: cache)"""
    from uengine.percival import eligibility as EL
    from uengine.percival.meta import test_assignment
    S = CTX["SET"]; lab = label_summary(sid); det = lab.get("detail", {}); idn = identity(sid); pat = idn.get("patient") or None
    test = bool(pat) and test_assignment(pat, S.get("percival_test_fraction", 0.2)); cache = rows if rows is not None else (_cached_rows(sid) or {})
    out = []
    for cid, d in sorted(det.items()):
        r = cache.get(cid)
        has_img = None if r is None else bool(r.get("maps") is not None if rows is not None else r.get("has_maps"))
        n_char = None if r is None else sum(v is not None for v in (r.get("char") or {}).values())
        has_pred = None if r is None else any(v is not None for v in (r.get("pred") or {}).values())
        ev = EL.evaluate(dict(label_kind=d["kind"], conflict=d["conflict"] and S.get("percival_conflicts", "exclude") == "exclude",
                              historical=d["source"] == "historical", study_excluded=meta.get("excluded"), study_archived=meta.get("archived_out"),
                              duplicate=meta.get("duplicate"), authorized=may_read(sid), has_image=has_img is not False, n_char=n_char is None or n_char > 0,
                              has_predictors=has_pred is not False, test=test, qc=meta.get("qc"), identity=idn["status"]))
        out.append(dict(study=sid, cand_id=cid, patient=pat, identity=idn["status"], y=d["y"], call=d["call"], label_source=d["source"], reviewer=d.get("reviewer", ""),
                        partition=ev["partition"], status=ev["status"], reasons=ev["reasons"], components={k: v["ok"] for k, v in ev["components"].items()},
                        component_reasons={k: v["reasons"] for k, v in ev["components"].items() if v["reasons"]},
                        missing=sorted({m for v in ev["components"].values() for m in v.get("missing", [])}),
                        rules=EL.RULES_VERSION, evaluated=time.strftime("%Y-%m-%d %H:%M:%S"), checked=r is not None))
    return out


def selection():
    """v5.24: every study of the project (and reviewed studies found on disk but missing from the study list) with the separate states
    the Training Center shows: registered / processed (candidate list) / reviewed (state) / labelled candidates / eligible / used.
    Eligibility per candidate comes from the Training Eligibility Engine (uengine/percival/eligibility.py)."""
    S = CTX["SET"]; ex = set(S.get("learner_exclude", [])); arch_ok = S["features"].get("train_include_archived", True); out = []
    mode = S.get("percival_learn_from", "labelled")
    from uengine.percival.meta import test_assignment
    for p in _study_list():
        c = p["code"]; lab = label_summary(c); rev = lab.get("state") == "reviewed"
        meta = dict(excluded=c in ex or (mode == "finished" and not rev), archived_out=bool(p.get("archived")) and not arch_ok)
        E = _examples(c, meta); el = [e for e in E if e["status"] == "eligible"]
        why = "excluded by you" if c in ex else ("archived (excluded in Settings)" if meta["archived_out"] else "")
        if el: reason = ""
        elif mode == "finished" and not rev and lab["css"] + lab["mimic"]: reason = "review not finished (Settings: learn from finished reviews only)"
        elif not os.path.exists(os.path.join(B(), "review", f"{c}_candidates.csv")): reason = "not processed yet (no candidate list)"
        elif not lab["detail"]: reason = "no expert call yet" + (f" ({lab['stale']} earlier call(s) need confirmation in Review)" if lab["stale"] else "")
        else:
            from uengine.percival.eligibility import REASONS
            codes = sorted({x for e in E for x in e["reasons"][:1]}); reason = "; ".join(REASONS.get(x, x) for x in codes)[:200]
        out.append(dict(code=c, label=CTX["label"](c) if not p["_orphan"] else c, cohort=p.get("cohort", ""), reviewed=rev,
                        processed=os.path.exists(os.path.join(B(), "review", f"{c}_candidates.csv")), n_candidates=lab.get("n_candidates", 0),
                        review_state=lab.get("state_label") or lab.get("state", ""), n_css=lab["css"], n_mimic=lab["mimic"], n_unused=lab["unused"],
                        n_stale=lab["stale"], n_conflicts=lab.get("conflicts", 0), n_historical=lab.get("historical", 0), label_error=lab.get("error", ""),
                        n_labelled=len(E), n_eligible=len(el), n_eligible_dev=sum(1 for e in el if e["partition"] == "development"),
                        css_dev=sum(1 for e in el if e["partition"] == "development" and e["y"] == 1),
                        mimic_dev=sum(1 for e in el if e["partition"] == "development" and e["y"] == 0),
                        n_adjudication=sum(1 for e in E if e["status"] == "needs_adjudication"), unrecognised=lab.get("unrecognised", []),
                        not_in_study_list=p["_orphan"], archived=bool(p.get("archived")), retired=bool(p.get("retired")),
                        included=bool(el) and not why, excluded_why=why, why=reason,
                        identity=identity(c)["status"],
                        partition=None if not CTX["patient_of"](c) else "test" if test_assignment(CTX["patient_of"](c), S.get("percival_test_fraction", 0.2)) else "development"))
    return out


def candidates_of(sid):
    """Training Center drill-down: every called candidate of one study with its eligibility per component and the reasons in words"""
    from uengine.percival.eligibility import explain
    S = CTX["SET"]; ex = set(S.get("learner_exclude", [])); p = next((x for x in _study_list() if x["code"] == sid), {})
    arch = bool(p.get("archived")) and not S["features"].get("train_include_archived", True)
    E = _examples(sid, dict(excluded=sid in ex, archived_out=arch))
    for e in E: e["reasons_text"] = explain(e["reasons"]); e["component_reasons_text"] = {k: explain(v) for k, v in e["component_reasons"].items()}
    lab = label_summary(sid)
    return dict(code=sid, candidates=E, stale=lab["stale"], rules="see uengine/percival/eligibility.py", checked=all(e["checked"] for e in E))


def eligibility_record():
    """v5.24: persist the eligibility of EVERY called candidate (all components, reasons, missing requirements, partition, dataset
    membership, rules version, evaluation time) -> percival/eligibility/current.json; the previous one is kept as eligibility/<time>.json"""
    from uengine.percival import eligibility as EL, datasets as DS
    S = CTX["SET"]; ex = set(S.get("learner_exclude", [])); mem = {}
    for d in DS.listing(P()):
        m = DS.load(P(), d["id"]) or {}
        for e in m.get("examples", []):
            if e.get("partition"): mem.setdefault(f"{e['study']}#{e['cand_id']}", []).append(d["id"])
    rec = []
    for s_ in selection():
        if not s_["n_labelled"]: continue
        for e in candidates_of(s_["code"])["candidates"]:
            rec.append(dict(study=e["study"], cand_id=e["cand_id"], patient=e["patient"], call=e["call"], y=e["y"], label_source=e["label_source"],
                            status=e["status"], partition=e["partition"], components=e["components"], reasons=e["reasons"],
                            component_reasons=e["component_reasons"], missing=e["missing"], datasets=mem.get(f"{e['study']}#{e['cand_id']}", []),
                            evaluated=e["evaluated"]))
    out = dict(schema="percival-eligibility-record/1.0", rules=EL.RULES_VERSION, evaluated=time.strftime("%Y-%m-%d %H:%M:%S"), n=len(rec),
               by_component={k: sum(1 for r in rec if r["components"].get(k)) for k in EL.COMPONENTS},
               by_status={k: sum(1 for r in rec if r["status"] == k) for k in sorted({r["status"] for r in rec})}, candidates=rec)
    cur = P("eligibility", "current.json")
    if os.path.exists(cur):
        old = _jl(cur, {}) or {}; os.replace(cur, P("eligibility", f"{_slug(old.get('evaluated', 'earlier'))}.json"))
    _js(cur, out); return {k: v for k, v in out.items() if k != "candidates"}


def reproduce_dataset(did):
    """rebuild dataset did from today's reviews and compare (dataset reproducibility)"""
    from uengine.percival import datasets as DS, eligibility as EL
    m = DS.load(P(), did)
    if not m: return dict(ok=False, error="unknown dataset")
    S = CTX["SET"]; ex = set(S.get("learner_exclude", [])); exs = []
    for s_ in selection():
        if s_["n_labelled"]:
            exs += _examples(s_["code"], dict(excluded=s_["code"] in ex or bool(s_["excluded_why"]), archived_out="archived" in s_["excluded_why"]),
                             rows={r["cand_id"]: r for r in gather(s_["code"], labelled=False)} if s_["included"] else None)
    R = DS.reproduce(P(), did, exs, EL.RULES_VERSION); R["ok"] = True; return R


def set_selection(codes, include):
    S = CTX["SET"]; ex = set(S.get("learner_exclude", []))
    for c in codes: (ex.discard if include else ex.add)(c)
    S["learner_exclude"] = sorted(ex); CTX["save_settings"](); return dict(ok=True, excluded=len(ex))


def integrity(sel):
    rep = dict(studies=len(sel), unused_labels=0, conflicts={}, duplicates=[])
    fps = {}
    for c in sel:
        _, u = _labels(c); rep["unused_labels"] += u
        k = _conflicts(c)
        if k: rep["conflicts"][CTX["label"](c)] = len(k)
        fp = CTX["fingerprint_of"](c)
        if fp:
            if fp in fps: rep["duplicates"].append(c)
            else: fps[fp] = c
    return rep


# ------------------------------------------------------------------ registry
def versions(): return sorted(os.path.basename(d) for d in glob.glob(P("registry", "v*")) if os.path.isdir(d))
_MCACHE = {}
def load(v):
    """registry model (cached by file mtime: the screen polls every few seconds and models with tree ensembles are large)"""
    p = P("registry", v, "model.json")
    try: mt = os.path.getmtime(p)
    except OSError: return None
    c = _MCACHE.get(p)
    if c and c[0] == mt: return c[1]
    m = _jl(p, None)
    if m is not None: _MCACHE[p] = (mt, m)
    return m
def active_version(): return _jl(P("active.json"), {}).get("version")
def active():
    v = active_version(); return load(v) if v else None


STATUSES = ("experimental", "candidate", "active", "retired", "rejected")


def status_all():
    """v5.24 model status register (registry/status.json): experimental (did not pass the acceptance criteria / research),
    candidate (passed, waiting for your approval), active (deployed), retired (was active, replaced), rejected (by you; cannot be made
    active until restored). The active model is always the one in active.json."""
    S = _jl(P("registry", "status.json"), {}) or {}; act = active_version(); out = {}
    for v in versions():
        e = dict(S.get(v) or {})
        if v == act: e["status"] = "active"
        elif e.get("status") in (None, "active"):
            M = load(v) or {}; e["status"] = "retired" if e.get("status") == "active" else ("candidate" if (M.get("acceptance") or {}).get("passed") else "experimental")
        out[v] = e
    return out


def _set_status(v, status, by, why):
    S = _jl(P("registry", "status.json"), {}) or {}; e = S.get(v) or dict(history=[])
    e.update(status=status, at=time.strftime("%Y-%m-%d %H:%M:%S"), by=by, why=why)
    e.setdefault("history", []).append(dict(status=status, at=e["at"], by=by, why=why)); S[v] = e; _js(P("registry", "status.json"), S)


def set_status(v, status, by="app user", why=""):
    """reject / retire / restore a version (never the active one: roll back or make another version active first)"""
    if v not in versions(): return dict(ok=False, error="unknown version")
    if v == active_version(): return dict(ok=False, error="this is the active model - make another version active (or roll back) first")
    if status == "restore":
        M = load(v) or {}; status = "candidate" if (M.get("acceptance") or {}).get("passed") else "experimental"
    if status not in ("rejected", "retired", "candidate", "experimental"): return dict(ok=False, error="unknown status")
    if status in ("rejected", "retired") and not why.strip(): return dict(ok=False, error="give a reason")
    _set_status(v, status, by, why or "restored"); return dict(ok=True, version=v, status=status)


def registry():
    """one entry per model version and per component inside it (identity, component, version, architecture, dataset, configuration,
    feature schema, metrics, validation report, artifact location, status)"""
    st = status_all(); out = []
    for v in versions():
        M = load(v) or {}; D = M.get("data") or {}; fam = (M.get("intelligence") or {}).get("families") or {}; t = M.get("test") or {}
        comps = []
        for k, name in (("char", "Characteristic ML"), ("image", "Image ML"), ("fusion", "Fusion")):
            f = fam.get(k) or {}
            comps.append(dict(component=k, name=name, architecture=f.get("chosen"), compared=sorted((f.get("results") or {}).keys()),
                              cv=(f.get("results") or {}).get(f.get("chosen")) if isinstance(f.get("results"), dict) else None))
        comps.append(dict(component="meta", name="Meta-model + calibration", architecture=(M.get("discovery") or {}).get("chosen"),
                          compared=sorted(((M.get("discovery") or {}).get("results") or {}).keys())))
        out.append(dict(id=f"percival-score/{v}", version=v, status=st[v]["status"], status_detail=st[v], created=M.get("created"), engine=M.get("engine"),
                        dataset=D.get("dataset"), dataset_hash=D.get("dataset_hash_manifest"), eligibility_rules=D.get("eligibility_rules"),
                        feature_schema=D.get("feature_schema"), patch_spec=D.get("patch_spec"), code_version=D.get("code_version"),
                        configuration=dict(seed=M.get("seed", 0), cnn_epochs=M.get("cnn_epochs"), minimum=M.get("minimum"), reason=M.get("reason")),
                        metrics=dict(test_auc=(t.get("percival") or {}).get("auc"), test_brier=(t.get("percival") or {}).get("brier"),
                                     test_math_auc=(t.get("math") or {}).get("auc"), dev=(M.get("discovery") or {}).get("results", {}).get((M.get("discovery") or {}).get("chosen"))),
                        validation=M.get("acceptance"), artifact=os.path.relpath(P("registry", v, "model.json"), B()), components=comps,
                        run=M.get("run_id")))
    return out


def promote(v, by="app user", why="made active by you", override=False):
    """EXPLICIT approval only (v5.24: no model becomes active automatically). A version that did not pass the acceptance criteria needs
    override=True and a reason; a rejected version must be restored first."""
    if not os.path.exists(P("registry", v, "model.json")): return dict(ok=False, error="unknown version")
    stv = status_all().get(v, {}).get("status")
    if stv == "rejected": return dict(ok=False, error=f"{v} was rejected - restore it first (Model Center)")
    M = load(v) or {}
    if why != "rollback" and not (M.get("acceptance") or {}).get("passed") and not override:
        return dict(ok=False, needs_override=True, error=f"{v} did not pass the acceptance criteria ({'; '.join((M.get('acceptance') or {}).get('reasons', []))}). "
                    "Make it active anyway only with a reason (research use).")
    if override and not (M.get("acceptance") or {}).get("passed") and (not why or why == "made active by you"):
        return dict(ok=False, needs_override=True, error="give the reason for activating a model that did not pass")
    cur = _jl(P("active.json"), {}); prev = cur.get("version")
    if prev == v: prev = cur.get("previous")                 # re-promoting the active version keeps its rollback target (v5.23 fix)
    _js(P("active.json"), dict(version=v, previous=prev, at=time.strftime("%Y-%m-%d %H:%M:%S"), by=by, why=why))
    _set_status(v, "active", by, why)
    if cur.get("version") and cur["version"] != v: _set_status(cur["version"], "retired", by, f"replaced by {v}")
    R = _jl(P("registry", "promotions.json"), []); R.append(dict(version=v, previous=prev, at=time.strftime("%Y-%m-%d %H:%M:%S"), by=by, why=why)); _js(P("registry", "promotions.json"), R)
    threading.Thread(target=score_all, daemon=True).start(); return dict(ok=True, version=v, previous=prev)


def rollback(by="app user"):
    a = _jl(P("active.json"), {})
    if not a.get("previous"): return dict(ok=False, error="no previous version to roll back to")
    if status_all().get(a["previous"], {}).get("status") == "rejected": return dict(ok=False, error=f"the previous version {a['previous']} was rejected")
    return promote(a["previous"], by, "rollback")


# ------------------------------------------------------------------ training cycle
def _env_min():
    v = os.environ.get("CSS_LEARN_MIN", "")
    try: a, b, c = (int(x) for x in v.split(",")); return dict(studies=a, candidates=b, per_class=c)
    except Exception: return None


def train_async(reason="manual"):
    with LOCK:
        if JOB["state"] in ACTIVE_STATES: return dict(ok=True, already_running=True)
        for k in ("cancel", "cancel_by", "cancel_at", "stall", "ended", "resources_peak", "resources_last", "samples", "transitions"): JOB.pop(k, None)
    _transition("preparing", log=[], progress=0.0, error="", reason=reason, started=time.time(), heartbeat=time.time(), stage="preparing")
    th = threading.Thread(target=_train, args=(reason,), daemon=True)
    with LOCK: JOB["thread"] = th
    th.start(); return dict(ok=True, started=True)


def _code_version():
    """the engine code that trained a model: BUILD stamp of the installed pipeline + sha256 of the Percival engine sources"""
    d = os.path.join(ROOT, "unified_engine", "uengine", "percival"); h = hashlib.sha256()
    for f in sorted(glob.glob(os.path.join(d, "*.py"))):
        with open(f, "rb") as fh: h.update(fh.read())
    b = ""
    for p in (os.path.join(B(), "scripts", "BUILD"), os.path.join(ROOT, "scripts", "BUILD")):
        if os.path.exists(p): b = open(p).read().strip()[:80]; break
    return dict(build=b, engine_sha256=h.hexdigest()[:16])


RUN = {}
def _run_start(reason):
    os.makedirs(P("runs"), exist_ok=True)
    rid = f"run{len(glob.glob(P('runs', 'run*.json'))) + 1:03d}"
    RUN.clear(); RUN.update(id=rid, kind="training cycle", state="running", reason=reason, started=time.strftime("%Y-%m-%d %H:%M:%S"),
                            code_version=_code_version(), settings={k: CTX["SET"].get(k) for k in ("percival_learn_from", "percival_conflicts",
                            "percival_use_historical", "percival_test_fraction")}, epochs=int(os.environ.get("CSS_PERCIVAL_EPOCHS", "30")))
    _js(P("runs", rid + ".json"), RUN)


def _run_end(state_, **kw):
    if not RUN: return
    with LOCK: lg = list(JOB.get("log", []))
    RUN.update(state=state_, finished=time.strftime("%Y-%m-%d %H:%M:%S"), log=lg[-200:], **kw); _js(P("runs", RUN["id"] + ".json"), RUN)


def runs():
    return [{k: v for k, v in (_jl(f, {}) or {}).items() if k != "log"} for f in sorted(glob.glob(P("runs", "run*.json")))]


def _interrupted_runs():
    """a run still 'running' on disk when the app starts was interrupted (app closed / crash): recorded as such, never left running"""
    for f in glob.glob(P("runs", "run*.json")):
        R = _jl(f, {}) or {}
        if R.get("state") == "running": R.update(state="interrupted", finished=time.strftime("%Y-%m-%d %H:%M:%S"), note="the app stopped during this run"); _js(f, R)


def _train(reason):
    from uengine.percival import meta as MT
    if JOB.get("state") != "preparing":
        with LOCK:
            for k in ("cancel", "cancel_by", "cancel_at", "stall", "ended", "resources_peak", "resources_last", "samples"): JOB.pop(k, None)
        _transition("preparing", log=[], progress=0.0, error="", reason=reason, started=time.time(), heartbeat=time.time(), stage="preparing")
    _run_start(reason)
    try:
        SL = selection(); sel = [s["code"] for s in SL if s["included"]]
        if not sel: raise ValueError("no study has an eligible expert label yet - Training Center lists every study and the reason it is not used")
        if not all(may_read(c) for c in sel): raise ValueError("local learning is not switched on (Percival Intelligence › Switch on)")
        from uengine.percival import datasets as DS, eligibility as EL
        integ = integrity([x["code"] for x in SL if x["n_labelled"]])     # v5.24: conflicts / duplicates over EVERY labelled study
        dup = set(integ["duplicates"]) & set(sel); rows, exs = [], []
        log(f"cycle started ({reason}): {len(sel)} studies with eligible labels", 0.01)
        S = CTX["SET"]; ex = set(S.get("learner_exclude", []))
        for k, c in enumerate(sel):
            g = {r["cand_id"]: r for r in gather(c, labelled=False)}
            E = _examples(c, dict(excluded=c in ex, duplicate=c in dup), rows=g); exs += E
            for e in E:
                if e["components"]["meta"]:
                    r = dict(g[e["cand_id"]], y=e["y"])
                    if not e["components"]["image"]: r["maps"] = None
                    rows.append(r)
            log(f"{CTX['label'](c)}: {sum(1 for e in E if e['components']['meta'])} eligible of {len(E)} called candidates", 0.01 + 0.06 * (k + 1) / len(sel))
        for s_ in SL:                                   # labelled studies that are left out: recorded in the manifest with their reasons
            if s_["code"] not in sel and s_["n_labelled"]:
                exs += _examples(s_["code"], dict(excluded=s_["code"] in ex or bool(s_["excluded_why"]), archived_out="archived" in s_["excluded_why"]))
        man = DS.build(exs, EL.RULES_VERSION, P(), extra=dict(settings=dict(learn_from=S.get("percival_learn_from", "labelled"),
                       conflicts=S.get("percival_conflicts", "exclude"), use_historical=S.get("percival_use_historical", True),
                       test_fraction=S.get("percival_test_fraction", 0.2))))
        log(f"dataset {man['id']} (content {man['content_hash']}): {man['n_examples']} called candidates, meta-model development "
            f"{man['components']['meta']['development']['n']} / locked test {man['components']['meta']['test']['n']}", 0.075)
        dv = [r for r in rows if not r.get("test")]; tv = [r for r in rows if r.get("test")]
        c1, c0 = sum(r["y"] for r in dv), sum(1 - r["y"] for r in dv); t1, t0 = sum(r["y"] for r in tv), sum(1 - r["y"] for r in tv)
        if min(c1, c0) < 3 or len(dv) < 10:
            raise ValueError(f"not enough expert labels to learn yet. The development cohort has {c1} cSS and {c0} not-cSS calls "
                             f"(at least 3 of each and 10 in all are needed); the locked test cohort (patients set aside for testing, never "
                             f"used to learn) holds {t1} cSS and {t0} not-cSS. Dataset {man['id']}: see Training Center for every study and "
                             f"candidate that was left out and why. Review more studies that contain cSS (press Y on each cSS candidate) "
                             f"and start the cycle again.")
        idc = {}
        for c in sel: idc[identity(c)["status"]] = idc.get(identity(c)["status"], 0) + 1
        _transition("running", stage="components")
        v = f"v{len(versions()) + 1:03d}"
        M = MT.train_cycle(rows, v, cnn_epochs=int(os.environ.get("CSS_PERCIVAL_EPOCHS", "30")), progress=lambda m, p: log(m, p), mins=_env_min())
        M["data"].update(dataset=man["id"], dataset_hash_manifest=man["content_hash"], eligibility_rules=EL.RULES_VERSION,
                         feature_schema=DS.FEATURE_SCHEMA, patch_spec=DS.PATCH_SPEC, code_version=_code_version())
        M["data"]["identity"] = dict(idc, policy="only verified / declared patient identities are used (v5.25)")
        log("registering", 0.9)                                    # last cancellation point: nothing has been written to the registry yet
        M["integrity"] = integ; M["reason"] = reason; M["run_id"] = RUN.get("id"); M["seed"] = 0; M["cnn_epochs"] = int(os.environ.get("CSS_PERCIVAL_EPOCHS", "30")); act = active(); acc = MT.acceptance(M, act); M["acceptance"] = acc
        M["previous_active"] = act["version"] if act else None
        _js(P("registry", v, "model.json"), M)
        H = _jl(P("history.json"), []); t = M["test"]
        H.append(dict(version=v, at=M["created"], reason=reason, studies=M["data"]["studies"], candidates=M["data"]["dev_candidates"] + M["data"]["test_candidates"],
                      css=M["data"]["css"], chosen=M["discovery"]["chosen"], dev={k: (x or {}).get("auc") for k, x in M["discovery"]["results"].items()},
                      test_auc=(t.get("percival") or {}).get("auc"), test_ci=(t.get("percival") or {}).get("auc_ci"), test_math_auc=(t.get("math") or {}).get("auc"),
                      passed=acc["passed"], promoted=False, dataset=man["id"]))
        _set_status(v, "candidate" if acc["passed"] else "experimental", f"training run {RUN.get('id')}",
                    "passed the acceptance criteria - waiting for your approval" if acc["passed"] else "; ".join(acc["reasons"]))
        if act is None and os.environ.get("CSS_PERCIVAL_FIRST_ACTIVE") == "1":          # TEST HOOK only (synthetic tests / update test)
            promote(v, by=f"test setting ({reason})", why="first model (CSS_PERCIVAL_FIRST_ACTIVE=1, tests only)", override=True); H[-1]["promoted"] = True
            log(f"{v} made active (test setting)", 0.95)
        else: log(f"{v} registered as {'a candidate (passed the acceptance criteria) - make it active in Model Center' if acc['passed'] else 'experimental: ' + '; '.join(acc['reasons'])}", 0.95)
        _js(P("history.json"), H); _js(P("last_cycle.json"), dict(at=time.strftime("%Y-%m-%d %H:%M:%S"), finished=sorted(sel)))
        CTX["notify"](f"Percival Score model {v} trained", ("made active" if H[-1]["promoted"] else "waiting for your approval" if acc["passed"] else "experimental") + f" · {M['data']['studies']} studies")
        _transition("finished", progress=1.0, stage="completed")
        _run_end("finished", version=v, dataset=man["id"], acceptance=acc, status=status_all().get(v, {}).get("status"))
        try: eligibility_record()
        except Exception as e_: log(f"eligibility record not written ({type(e_).__name__})")
    except Cancelled as e:
        _transition("cancelled", error=str(e), stage="cancelled"); log(f"cycle cancelled ({e}); no model was registered")
        _run_end("cancelled", error=str(e))
    except Exception as e:
        try: _transition("failed", error=f"{type(e).__name__}: {str(e)[:300]}", stage="failed")
        except RuntimeError: pass
        log(f"failed: {e}"); _run_end("failed", error=f"{type(e).__name__}: {str(e)[:500]}", dataset=locals().get("man", {}).get("id") if isinstance(locals().get("man"), dict) else None)


def maybe_cycle():
    """controlled cycles: a new training cycle when N newly finished studies have accumulated since the last cycle"""
    S = CTX["SET"]
    if not S.get("percival_autocycle", True) or not authorized() or JOB["state"] in ACTIVE_STATES: return False
    done = {s["code"] for s in selection() if s["included"]}; last = set(_jl(P("last_cycle.json"), {}).get("finished", []))
    if len(done - last) >= int(S.get("percival_cycle_n", 5)): train_async(f"{len(done - last)} newly finished studies"); return True
    return False


# ------------------------------------------------------------------ scoring + prediction ledger
def _run_id(sid):
    a = _jl(os.path.join(B(), "runs", sid, "active.json"), {}); return a.get("run_id") or "initial"


def score_study(sid, M=None):
    from uengine.percival import meta as MT
    M = M or active()
    if not M: return None
    rows = gather(sid, labelled=False)
    if not rows: return None
    S = MT.score_rows(M, rows); hemi = {r["cand_id"]: r.get("hemi", "") for r in rows}
    for s in S: s["hemi"] = hemi.get(s["cand_id"], "")

    # v5.25 Unified Percival Core Evaluation & PENSIEVE Persistence
    try:
        from uengine.percival_core import PercivalCoreIntelligence
        from uengine.albus import AlbusDiscoveryEngine
        from uengine.lumos import LumosImageIntelligence
        from uengine.nox import NoxCharacteristicsEngine
        from uengine.pensieve import get_pensieve
        from uengine.vault import get_vault

        _p = get_pensieve()
        _v = get_vault()
        _core = PercivalCoreIntelligence(pensieve=_p, vault=_v)
        _albus = AlbusDiscoveryEngine(pensieve=_p)
        _lumos = LumosImageIntelligence(pensieve=_p, vault=_v)
        _nox = NoxCharacteristicsEngine(pensieve=_p)

        for s in S:
            cid = int(s.get("cand_id", 0))
            h = str(s.get("hemi", "U"))
            row_match = next((r for r in rows if int(r.get("cand_id", 0)) == cid), {})
            vox = (float(row_match.get("ci", 0)), float(row_match.get("cj", 0)), float(row_match.get("ck", 0)))
            mm = (float(row_match.get("cx", 0)), float(row_match.get("cy", 0)), float(row_match.get("cz", 0)))
            raw_f = {
                "pial_distance": float(row_match.get("pdist", 1.0)),
                "darkness_z": float(row_match.get("darkness_z", -1.5)),
                "tube_ratio": float(row_match.get("tube_ratio", 1.5)),
                "cortex_frac": float(row_match.get("cortex_frac", 0.5)),
                "tram_frac": float(row_match.get("tram_frac", 0.0))
            }
            cand_a = _albus.discover_candidate(sid, cid, h, vox, mm, int(row_match.get("vol_vox", 10)), float(row_match.get("vol_mm3", 5.0)), (0,0,0,0,0,0), raw_f)
            cand_n = _nox.measure_candidate(sid, cid, raw_f)
            cand_l = _lumos.analyze_patch(sid, cid, row_match.get("patch"))
            asmt = _core.evaluate_candidate(cand_a, cand_l, cand_n)
            if asmt.percival_score is not None:
                s["percival_score"] = asmt.percival_score
                s["band"] = asmt.band
                s["status"] = asmt.status
                s["uncertainty"] = asmt.uncertainty
            else:
                s["percival_score"] = None
                s["band"] = asmt.band
                s["status"] = asmt.status if asmt.status in ("reliable", "uncertain", "insufficient", "review") else "insufficient"
                s["uncertainty"] = asmt.uncertainty
            s["core_percival_score"] = asmt.percival_score
            s["core_band"] = asmt.band
            s["core_status"] = asmt.status
            s["core_uncertainty"] = asmt.uncertainty
    except Exception as e:
        log(f"[PercivalCore] Warning: Candidate evaluation note for {sid}: {e}")
    ids = [s["cand_id"] for s in S if s["percival_score"] is not None and s["percival_score"] >= 50]
    study = dict(n_called=len(ids), called_ids=ids, L_score=None, R_score=None, total=None, error="")
    try:                                                   # the study score with the reader's own scoring method, on the candidates Percival calls
        r = subprocess.run([sys.executable, os.path.join(CTX["SC"], "score_css.py"), sid, "--accept-ids", ",".join(map(str, ids)) or "none", "--tag", "percival"],
                           capture_output=True, text=True, timeout=600, env=dict(os.environ, CSS_BASE=B(), PYTHONWARNINGS="ignore"))
        J = _jl(os.path.join(B(), "review", f"{sid}_score_percival.json"), {})
        study.update(L_score=J.get("L_score"), R_score=J.get("R_score"), total=J.get("multifocality_0_4"), error="" if r.returncode == 0 else (r.stderr or r.stdout)[-160:])
    except Exception as e: study["error"] = type(e).__name__
    in_tr = sid in set((M.get("data") or {}).get("trained_on") or [])
    rec = dict(study=sid, model=M["version"], run=_run_id(sid), created=time.strftime("%Y-%m-%d %H:%M:%S"), ready=M["ready"], thresholds=M["thresholds"],
               in_training=in_tr, in_training_note="this study's expert labels were used to train this model: its scores are in-sample (optimistic)" if in_tr else "",
               candidates=S, study_score=study, note=M["note"], kind="AI prediction (Percival Score) - not a human review",
               provenance=dict(model=M["version"], engine=M.get("engine", ""), dataset=(M.get("data") or {}).get("dataset", "(trained before v5.24 - no manifest)"),
                               feature_schema=(M.get("data") or {}).get("feature_schema", ""), code=(M.get("data") or {}).get("code_version", {}),
                               processing_run=_run_id(sid)))
    lp = P("ledger", sid, f"{M['version']}__{rec['run']}.json")
    if not os.path.exists(lp): _js(lp, rec)                     # immutable: a later model writes a NEW file
    _js(P("scores", f"{sid}.json"), rec); return rec


def score_all():
    M = active()
    if not M: return
    for p in CTX["patients"]():
        if not p.get("retired") and os.path.exists(os.path.join(B(), "review", f"{p['code']}_candidates.csv")) and may_read(p["code"]):
            try: score_study(p["code"], M)
            except Exception as e: log(f"{CTX['label'](p['code'])}: not scored ({type(e).__name__})")


def history_of(sid):
    """every prediction ever made for this study (immutable ledger), each marked: current (active model on the current processing run),
    historical (an earlier model) or earlier processing (made on a previous run of the pipeline)"""
    a = active_version(); run = _run_id(sid); out = []
    for f in sorted(glob.glob(P("ledger", sid, "*.json"))):
        L = _jl(f, {})
        L["status"] = ("earlier processing" if L.get("run") and L.get("run") != run else "current" if L.get("model") == a else "historical")
        out.append(L)
    return out


def score_study_unified(sid):
    """v5.25: Evaluate candidate rows using the reconstructed PercivalCoreIntelligence pipeline."""
    from uengine.albus import AlbusDiscoveryEngine
    from uengine.lumos import LumosImageIntelligence
    from uengine.nox import NoxCharacteristicsEngine
    from uengine.percival_core import PercivalCoreIntelligence
    from uengine.pensieve import get_pensieve
    from uengine.vault import get_vault

    pensieve = get_pensieve()
    vault = get_vault()
    core = PercivalCoreIntelligence(pensieve=pensieve, vault=vault)
    albus = AlbusDiscoveryEngine(pensieve=pensieve)
    lumos = LumosImageIntelligence(pensieve=pensieve, vault=vault)
    nox = NoxCharacteristicsEngine(pensieve=pensieve)

    rows = gather(sid, labelled=False)
    if not rows:
        return dict(ok=False, error=f"No candidates found for study {sid}")

    assessments = []
    for r in rows:
        cid = int(r.get("cand_id", 0))
        hemi = str(r.get("hemi", "U"))
        raw_feats = {
            "pial_distance": float(r.get("pdist", r.get("pial_distance", 1.0))),
            "darkness_z": float(r.get("darkness_z", -1.5)),
            "tube_ratio": float(r.get("tube_ratio", 1.5)),
            "cortex_frac": float(r.get("cortex_frac", 0.5)),
            "tram_frac": float(r.get("tram_frac", 0.0)),
            "skeleton_length": float(r.get("skeleton_length", 4.0))
        }
        vox = (float(r.get("ci", 0)), float(r.get("cj", 0)), float(r.get("ck", 0)))
        mm = (float(r.get("cx", 0)), float(r.get("cy", 0)), float(r.get("cz", 0)))

        cand_albus = albus.discover_candidate(
            study_id=sid, cand_id=cid, hemi=hemi,
            centroid_vox=vox, centroid_mm=mm,
            volume_vox=int(r.get("vol_vox", 10)),
            volume_mm3=float(r.get("vol_mm3", 5.0)),
            bbox=(0, 0, 0, 0, 0, 0),
            raw_features=raw_feats
        )
        cand_nox = nox.measure_candidate(sid, cid, raw_feats)

        # Check patch availability
        patch_data = None
        if "patch" in r and isinstance(r["patch"], dict):
            patch_data = r["patch"]
        cand_lumos = lumos.analyze_patch(sid, cid, patch_data)

        assessment = core.evaluate_candidate(cand_albus, cand_lumos, cand_nox)
        assessments.append(assessment.__dict__)

    return dict(ok=True, study=sid, count=len(assessments), assessments=assessments)


# ------------------------------------------------------------------ v5.24 shadow mode (controlled experimental environment)
SJOB = dict(state="idle", version="", progress=0.0, error="")


def shadow_async(version):
    """run a registry version IN SHADOW on every study: its predictions go to percival/shadow/<version>/ only - never to scores/ (what
    reviewers see), never to the prediction ledger, never to active.json. Compared with the active model and, prospectively, with expert
    calls the version never learned from. A shadow model replaces the active one only through Model Center › Make active."""
    if not load(version): return dict(ok=False, error="unknown version")
    with LOCK:
        if SJOB["state"] == "running": return dict(ok=False, error=f"shadow run of {SJOB['version']} already running")
        SJOB.update(state="running", version=version, progress=0.0, error="")
    threading.Thread(target=_shadow, args=(version,), daemon=True).start(); return dict(ok=True, started=True)


def _learned(M):
    """(study, cand_id) a model learned from: its dataset manifest's development examples; models before v5.24: (study, None) per study"""
    from uengine.percival import datasets as DS
    if not M: return set()
    man = DS.load(P(), (M.get("data") or {}).get("dataset", "")) if (M.get("data") or {}).get("dataset") else None
    if man: return {(e["study"], int(e["cand_id"])) for e in man["examples"] if e.get("partition") == "development"}
    return {(s, None) for s in (M.get("data") or {}).get("trained_on", [])}


def _shadow(version):
    from uengine.percival import meta as MT
    try:
        M = load(version); A = active(); learned = _learned(M)
        learned_a = _learned(A) if A and A["version"] != version else set()
        pats = [p["code"] for p in _study_list() if os.path.exists(os.path.join(B(), "review", f"{p['code']}_candidates.csv")) and may_read(p["code"])]
        ys, ps, pa, gs, agree, diffs, n = [], [], [], [], 0, [], 0; fair = []
        for k, sid in enumerate(pats):
            rows = gather(sid, labelled=False)
            if not rows: continue
            S = MT.score_rows(M, rows); SA = {x["cand_id"]: x for x in MT.score_rows(A, rows)} if A and A["version"] != version else {}
            _js(P("shadow", version, f"{sid}.json"), dict(study=sid, model=version, created=time.strftime("%Y-%m-%d %H:%M:%S"), candidates=S,
                kind="SHADOW prediction - experimental; not shown to reviewers, not used for any result", active_model=A["version"] if A else None))
            lab = label_summary(sid)["labels"]
            for x in S:
                a = SA.get(x["cand_id"])
                if a and x["percival_score"] is not None and a["percival_score"] is not None:
                    n += 1; diffs.append(abs(x["percival_score"] - a["percival_score"])); agree += int(x["band"] == a["band"])
                cid = x["cand_id"]
                if cid in lab and (sid, cid) not in learned and (sid, None) not in learned and x["percival_score"] is not None:
                    ys.append(lab[cid]); ps.append(x["percival_score"] / 100); gs.append(CTX["patient_of"](sid))
                    pa.append(a["percival_score"] / 100 if a and a["percival_score"] is not None else np.nan)
                    fair.append((sid, cid) not in learned_a and (sid, None) not in learned_a)      # the ACTIVE model did not learn it either
            with LOCK: SJOB["progress"] = (k + 1) / max(1, len(pats))
        y, p = np.array(ys, float), np.array(ps, float); pa_ = np.array(pa, float); g_ = np.array(gs); f_ = np.array(fair, bool) if fair else np.zeros(0, bool)
        ok_ = lambda yy: len(yy) >= 10 and 0 < yy.sum() < len(yy)
        h = f_ & np.isfinite(pa_) if len(f_) else f_                    # head-to-head: calls NEITHER model learned from
        pros = dict(n=len(y), css=int(y.sum()) if len(y) else 0,
                    shadow=MT.metrics(y, p, g_) if ok_(y) else None,
                    n_fair=int(h.sum()), css_fair=int(y[h].sum()) if h.any() else 0,
                    fair_shadow=MT.metrics(y[h], p[h], g_[h]) if ok_(y[h]) else None,
                    active=MT.metrics(y[h], pa_[h], g_[h]) if ok_(y[h]) else None,
                    note="shadow: expert calls this version never learned from (prospective). Head-to-head (fair_shadow vs active): only calls "
                         "that NEITHER model learned from - the active model's metrics on calls it was trained on would be in-sample and are not reported.")
        _js(P("shadow", version, "summary.json"), dict(version=version, at=time.strftime("%Y-%m-%d %H:%M:%S"), studies=len(pats),
            active=A["version"] if A else None, compared=n, band_agreement=agree / n if n else None,
            mean_abs_difference=float(np.mean(diffs)) if diffs else None, prospective=pros,
            rule="shadow predictions never change what reviewers see; Make active (Model Center) is the only way to deploy"))
        with LOCK: SJOB.update(state="finished", progress=1.0)
    except Exception as e:
        with LOCK: SJOB.update(state="failed", error=f"{type(e).__name__}: {str(e)[:300]}")


def shadow_summaries():
    out = [_jl(f, {}) for f in sorted(glob.glob(P("shadow", "*", "summary.json")))]
    with LOCK: j = dict(SJOB)
    return dict(job=j, runs=out)


# ------------------------------------------------------------------ v5.24 compatibility audit + review recovery
def compat_report():
    """read-only audit of this project for the Data integrity screen: store schema + migrations + backups, studies registered vs on disk,
    processed / MRI present, reviews (current, legacy shared file, historical from earlier versions), calls that no longer match,
    model versions and their engines, prediction ledger. Nothing is changed."""
    from uengine.percival import store as ST
    D = ST.detect(B()); pats = CTX["patients"](); codes = {p["code"] for p in pats}; rows = []
    for p in _study_list():
        c = p["code"]; lab = label_summary(c)
        legacy = os.path.exists(os.path.join(B(), "review", f"{c}_calls.csv")) and not glob.glob(os.path.join(B(), "review", f"{c}_calls_*.csv"))
        hist = glob.glob(os.path.join(B(), "historical", c, "review", "*_calls*.csv"))
        mri = bool(glob.glob(os.path.join(B(), "data", f"{c}_swi.nii*")))
        cand = os.path.exists(os.path.join(B(), "review", f"{c}_candidates.csv"))
        issues = []
        if p["_orphan"]: issues.append("reviewed study not in the study list (from an older version?) - its calls are used for learning")
        if cand and not mri: issues.append("MRI (data/ID_swi.nii) missing - Image ML cannot use this study")
        if not cand and p.get("status") == "done": issues.append("marked processed but the candidate list is missing")
        if lab["stale"]: issues.append(f"{lab['stale']} earlier call(s) no longer match a current candidate - confirm them in Review")
        if lab.get("error"): issues.append("labels unreadable: " + lab["error"])
        rows.append(dict(code=c, label=CTX["label"](c) if not p["_orphan"] else c, registered=not p["_orphan"], processed=cand, mri=mri,
                         review_format="per-reviewer files" if glob.glob(os.path.join(B(), "review", f"{c}_calls_*.csv")) else ("legacy shared file (before v5.7)" if legacy else "none"),
                         historical_reviews=len(hist), labels_current=sum(1 for d in lab["detail"].values() if d["source"] == "review"),
                         labels_historical=lab.get("historical", 0), stale=lab["stale"], predictions=len(glob.glob(P("ledger", c, "*.json"))) if STORE["ok"] else 0,
                         issues=issues))
    models = []
    if STORE["ok"]:
        for v in versions():
            m = load(v) or {}
            models.append(dict(version=v, engine=m.get("engine", "percival-engine/5.22"), created=m.get("created"), dataset=(m.get("data") or {}).get("dataset"),
                               readable=bool(m.get("meta"))))
    return dict(store=dict(D, ok=STORE["ok"], error=STORE["error"], last_migration=STORE["migration"], backups=ST.backups(B()), schema_supported=ST.SCHEMA,
                           path=ST.root(B())),
                studies=rows, n_registered=len(codes), n_orphans=sum(1 for r in rows if not r["registered"]),
                n_with_issues=sum(1 for r in rows if r["issues"]), models=models)


def recoverable_reviews():
    """studies of THIS project whose examination (same image fingerprint) was reviewed in another project on this Mac (an earlier
    Percival / production project) and whose reviews are not here yet. Only the other project's patients.json + file names are read."""
    out = []
    try: others = CTX["other_projects"]()
    except Exception: return out
    for p in CTX["patients"]():
        c = p["code"]; fp = CTX["fingerprint_of"](c)
        if not fp: continue
        for o in others:
            for q in o["patients"]:
                if fp in {str(q.get("fingerprint", "")), str(q.get("fingerprint_v1", ""))} and q.get("code"):
                    src = glob.glob(os.path.join(o["path"], "review", f"{q['code']}_calls*.csv"))
                    have = {os.path.basename(x) for x in glob.glob(os.path.join(B(), "historical", c, "review", "*"))}
                    new = [x for x in src if os.path.basename(x) not in have]
                    if new: out.append(dict(code=c, label=CTX["label"](c), project=o["path"], kind=o["kind"], source_code=q["code"], files=len(new)))
    return out


def recover_reviews(by="app user"):
    """copy the reviewer files of the matched examinations (calls, final saves, scores) into historical/ID/review/ - verified by sha256;
    the other project is only read. They become a HISTORICAL label source (matched to the current candidates by fingerprint)."""
    import shutil
    done = []
    for r in recoverable_reviews():
        d = os.path.join(B(), "historical", r["code"], "review"); os.makedirs(d, exist_ok=True); n = 0
        for f in glob.glob(os.path.join(r["project"], "review", f"{r['source_code']}_calls*.csv")) + glob.glob(os.path.join(r["project"], "review", f"{r['source_code']}_final*.json")):
            t = os.path.join(d, os.path.basename(f))
            if os.path.exists(t): continue
            shutil.copy2(f, t + ".tmp")
            if _sha(t + ".tmp") != _sha(f): os.remove(t + ".tmp"); continue
            os.replace(t + ".tmp", t); n += 1
        S = _jl(os.path.join(d, "SOURCE.json"), {"copies": []})
        S["copies"].append(dict(project=r["project"], kind=r["kind"], source_code=r["source_code"], files=n, at=time.strftime("%Y-%m-%d %H:%M:%S"), by=by,
                                match="same image fingerprint", verified="sha256"))
        _js(os.path.join(d, "SOURCE.json"), S); done.append(dict(code=r["code"], files=n)); _LCACHE.pop(r["code"], None)
    return dict(ok=True, recovered=done)


# ------------------------------------------------------------------ v5.23 expert-review snapshots (the local learning dataset)
def _slug(x):
    import re
    return re.sub(r"[^A-Za-z0-9]+", "_", str(x).strip()).strip("_") or "reviewer"


def _sha(p):
    try:
        with open(p, "rb") as f: return hashlib.sha256(f.read()).hexdigest()
    except Exception: return None


def snapshot_study(sid):
    """one IMMUTABLE record per final expert review: labels + exactly what the models said when the review was saved. -> n new"""
    import pandas as pd
    finals = sorted(set(glob.glob(os.path.join(B(), "review", f"{sid}_final_*.json"))) | set(glob.glob(os.path.join(B(), "review", f"{sid}_final.json"))))
    new = 0; cand = None
    for fp in finals:
        F = _jl(fp, {}); rev, saved = F.get("reviewer"), F.get("saved")
        if not rev or not saved: continue
        out = P("reviews", sid, f"{_slug(rev)}__{_slug(saved)}.json")
        if os.path.exists(out): continue                                     # immutable: never rewritten
        cp = os.path.join(B(), "review", f"{sid}_calls_{_slug(rev)}.csv")
        if not os.path.exists(cp): cp = os.path.join(B(), "review", f"{sid}_calls.csv")
        labels = pd.read_csv(cp, dtype=str).fillna("").to_dict("records") if os.path.exists(cp) else []
        shown = None                                                          # the newest Percival prediction that existed when the review was saved
        for L in history_of(sid):
            if L.get("created") and L["created"] <= saved and (shown is None or L["created"] >= shown["created"]): shown = L
        if cand is None:
            from uengine.percival.meta import CHAR
            cand = []; rows = {}
            try: rows = {r["cand_id"]: r for r in gather(sid, labelled=False)}
            except Exception as e: log(f"{CTX['label'](sid)}: review snapshot without measurements ({type(e).__name__})")
            cpath = os.path.join(B(), "review", f"{sid}_candidates.csv")
            if os.path.exists(cpath):
                d = pd.read_csv(cpath)
                for _, r in d.iterrows():
                    cid = int(r["cand_id"]); g = rows.get(cid, {}); mp = g.get("maps")
                    cand.append(dict(cand_id=cid, hemi=str(r.get("hemi", "")), region=str(r.get("region", "")),
                                     vox=[int(r[k]) for k in ("vox_i", "vox_j", "vox_k") if k in d.columns and not pd.isna(r[k])],
                                     volume_mm3=None if pd.isna(r.get("volume_mm3", np.nan)) else float(r["volume_mm3"]), math=g.get("math"), char=g.get("char"), predictors=g.get("pred"),
                                     patch_sha256=None if mp is None else hashlib.sha256(np.ascontiguousarray(mp, np.float32).tobytes()).hexdigest()[:16],
                                     patch_reference=f"percival/cache/{sid}.npz#{cid}" if mp is not None else None,
                                     image_reference=dict(swi=f"data/{sid}_swi.nii", candidates=f"review/{sid}_candidates.nii.gz", voxel=[int(r[k]) for k in ("vox_i", "vox_j", "vox_k") if k in d.columns and not pd.isna(r[k])])))
        prior = sorted(glob.glob(P("reviews", sid, f"{_slug(rev)}__*.json")))
        notes = [dict(cand_id=x.get("cand_id"), comment=x.get("comment")) for x in labels if str(x.get("comment", "")).strip()]
        rec = dict(schema="percival-review-snapshot/1.1", revision=len(prior) + 1, revises=os.path.basename(prior[-1]) if prior else None,
                   annotations=notes, missed_marks=os.path.exists(os.path.join(B(), "review", f"{sid}_missed.csv")),
                   versions=_versions_now(), kind="expert review (human) - original label, never overwritten", study=sid, reviewer=rev, saved=saved,
                   read_mode=F.get("read_mode", ""), percival_visible_to_reviewer=F.get("meter_visible", ""), labels=labels,
                   percival_at_review=None if shown is None else dict(model=shown.get("model"), created=shown.get("created"), run=shown.get("run"),
                                                                      candidates=shown.get("candidates"), thresholds=shown.get("thresholds")),
                   percival_note="no Percival Score existed for this study when the review was saved" if shown is None else "the newest prediction created before the save",
                   candidates=cand, processing=dict(run=_run_id(sid), manifest_sha256=_sha(os.path.join(B(), "review", f"{sid}_manifest.json")),
                                                    candidates_sha256=_sha(os.path.join(B(), "review", f"{sid}_candidates.csv"))),
                   active_model_at_snapshot=active_version(), snapshot_created=time.strftime("%Y-%m-%d %H:%M:%S"),
                   identifiers="none - the study is named by its internal key")
        _js(out, rec); new += 1
    return new


def _versions_now():
    from uengine.percival.meta import ENGINE
    from uengine.percival.eligibility import RULES_VERSION
    return dict(engine=ENGINE, code=_code_version(), active_model=active_version(), eligibility_rules=RULES_VERSION)


def snapshot_reviews():
    n = 0
    for p in CTX["patients"]():
        try: n += snapshot_study(p["code"])
        except Exception as e: log(f"{CTX['label'](p['code'])}: review snapshot failed ({type(e).__name__})")
    return n


def reviews_of(sid): return [_jl(f, {}) for f in sorted(glob.glob(P("reviews", sid, "*.json")))]


# ------------------------------------------------------------------ the Percival Intelligence screen
def inputs(sel):
    """v5.24: what each part of the Percival Score receives in this project (for the 'How Percival works' panel) - read-only counts of
    files; nothing is computed here. Studies = the studies the cycle learns from."""
    codes = [s["code"] for s in sel if s["included"]]; n = len(codes)
    has = lambda f: sum(1 for c in codes if os.path.exists(f(c)))
    img = 0
    for c in codes:
        C = _jl(P("cache", f"{c}.json"), {})
        if any(r.get("has_maps") for r in C.get("rows", [])): img += 1
    pc = pr = 0                                                     # candidates with >= 1 RELIABLE Unified predictor (unreliable = missing for Percival)
    from uengine.percival.meta import PREDICTORS
    for c in codes:
        for r in (_jl(os.path.join(B(), "uscore", "features", f"{c}.json"), {}) or {}).get("records", []):
            pc += 1; pr += int(any((r.get("F", {}).get(k) or {}).get("status") == "reliable" for k in PREDICTORS))
    return dict(studies=n, candidates=has(lambda c: os.path.join(B(), "review", f"{c}_candidates.csv")),
                predictors=has(lambda c: os.path.join(B(), "uscore", "features", f"{c}.json")), image=img,
                predictor_candidates=pc, predictor_reliable=pr,
                gathered=has(lambda c: P("cache", f"{c}.json")))


def state():
    from uengine.percival import meta as MT, datasets as DS
    if not STORE["ok"]: return dict(store=STORE, authorized=authorized(), job=dict(state="idle"), selection=[], versions=[], history=[], log=[])
    with LOCK: job = {k: v for k, v in JOB.items() if k != "log"}; jlog = JOB["log"][-60:]      # job FIRST (v5.23): a cycle finishing while
    vs = versions(); latest = load(vs[-1]) if vs else None; M = active(); sel = selection()      # this runs must not look finished with old versions
    strip = lambda m: None if not m else {k: v for k, v in m.items() if k not in ("components", "meta_ensemble")}
    return dict(authorized=authorized(), autocycle=CTX["SET"].get("percival_autocycle", True), cycle_n=int(CTX["SET"].get("percival_cycle_n", 5)),
                test_fraction=CTX["SET"].get("percival_test_fraction", 0.2), learn_from=CTX["SET"].get("percival_learn_from", "labelled"), job=job, log=jlog,
                active=strip(M), latest=strip(latest), versions=vs, history=_jl(P("history.json"), []), promotions=_jl(P("registry", "promotions.json"), []),
                selection=sel, n_selected=sum(1 for s in sel if s["included"]),
                labels=dict(css=sum(s["n_css"] for s in sel if s["included"]), mimic=sum(s["n_mimic"] for s in sel if s["included"]),
                            css_dev=sum(s["css_dev"] for s in sel if s["included"]), mimic_dev=sum(s["mimic_dev"] for s in sel if s["included"]),
                            stale=sum(s["n_stale"] for s in sel), not_in_study_list=sum(1 for s in sel if s["not_in_study_list"])),
                minimum=dict(studies=MT.MIN_STUDIES, candidates=MT.MIN_CANDIDATES, per_class=MT.MIN_PER_CLASS),
                since_last=len({s["code"] for s in sel if s["included"]} - set(_jl(P("last_cycle.json"), {}).get("finished", []))),
                n_review_snapshots=len(glob.glob(P("reviews", "*", "*.json"))), inputs=inputs(sel), store=STORE,
                runs=runs()[-30:], registry=registry(), status=status_all(),
                eligibility_record={k: v for k, v in (_jl(P("eligibility", "current.json"), {}) or {}).items() if k != "candidates"},
                unrecognised=sorted({c for x in sel for c in x.get("unrecognised", [])}),
                datasets=DS.listing(P()), learn_settings=dict(learn_from=CTX["SET"].get("percival_learn_from", "labelled"),
                    conflicts=CTX["SET"].get("percival_conflicts", "exclude"), use_historical=CTX["SET"].get("percival_use_historical", True)),
                overview=dict(registered=sum(1 for x in sel if not x["not_in_study_list"]), on_disk_only=sum(1 for x in sel if x["not_in_study_list"]),
                              processed=sum(1 for x in sel if x["processed"]), candidates=sum(x["n_candidates"] for x in sel),
                              reviewed_studies=sum(1 for x in sel if x["reviewed"]), called=sum(x["n_labelled"] for x in sel),
                              eligible=sum(x["n_eligible"] for x in sel), eligible_dev=sum(x["n_eligible_dev"] for x in sel),
                              adjudication=sum(x["n_adjudication"] for x in sel), historical=sum(x["n_historical"] for x in sel),
                              excluded=sum(x["n_labelled"] - x["n_eligible"] - x["n_adjudication"] for x in sel)))


# -------------------------------------------------------------
# PERCIVAL DATA VAULT, PENSIEVE & SHADOW ML BACKEND SERVICES
# -------------------------------------------------------------
def pensieve_state():
    from uengine.pensieve import get_pensieve
    from uengine.vault import get_vault
    p = get_pensieve()
    v = get_vault()
    return {
        "ok": True,
        "vault_connected": v.is_connected(),
        "vault_path": v.root_path,
        "studies": p.get_all_studies()[:50],
        "corrections": p.get_all_corrections()[:50],
        "findings": p.get_all_findings()[:50],
        "summary": {
            "albus": p.ask_albus_memory(limit=10),
            "lumos": p.ask_lumos_memory(limit=10),
            "nox": p.ask_nox_memory(),
            "core": p.ask_core_memory(),
            "shadow": p.ask_shadow_memory()
        }
    }


def pensieve_query(component):
    from uengine.pensieve import get_pensieve
    p = get_pensieve()
    comp = str(component).lower()
    if comp == "albus": return p.ask_albus_memory()
    if comp == "lumos": return p.ask_lumos_memory()
    if comp == "nox": return p.ask_nox_memory()
    if comp == "core": return p.ask_core_memory()
    if comp == "shadow": return p.ask_shadow_memory()
    return {"error": f"unknown component {component}"}


def vault_status():
    from uengine.vault import get_vault
    v = get_vault()
    stats = v.get_storage_stats()
    integrity = v.verify_integrity() if v.is_connected() else {"ok": False}
    return {"stats": stats, "integrity": integrity}


def vault_connect(path):
    from uengine.vault import get_vault
    v = get_vault()
    ok, msg = v.connect(path)
    return {"ok": ok, "message": msg, "stats": v.get_storage_stats()}


def vault_create(destination, name="PERCIVAL_VAULT"):
    from uengine.vault import PercivalDataVault
    try:
        v = PercivalDataVault.create_vault(destination, name=name)
        return {"ok": True, "message": f"Vault created at {v.root_path}", "stats": v.get_storage_stats()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def vault_eject():
    from uengine.vault import get_vault
    v = get_vault()
    ok, msg = v.safe_eject()
    return {"ok": ok, "message": msg}


def vault_backup(destination):
    from uengine.vault import get_vault
    v = get_vault()
    ok, msg = v.create_backup(destination)
    return {"ok": ok, "message": msg}


def shadow_lab_state():
    from uengine.shadow_lab import ShadowMLLaboratory
    from uengine.governance import PercivalGovernance
    lab = ShadowMLLaboratory()
    gov = PercivalGovernance()
    return {
        "experiments": [
            {
                "id": e.experiment_id,
                "hypothesis": e.hypothesis,
                "target_component": e.target_component,
                "status": e.status,
                "baseline": e.metrics_baseline,
                "experimental": e.metrics_experimental,
                "runtime_s": e.runtime_s,
                "artifact": e.data_vault_artifact_path
            }
            for e in lab.list_experiments()
        ],
        "proposals": [
            {
                "proposal_id": p.proposal_id,
                "experiment_id": p.experiment_id,
                "target_component": p.target_component,
                "hypothesis": p.hypothesis,
                "rationale": p.rationale,
                "verdict": p.verdict,
                "sensitivity_loss": p.sensitivity_loss,
                "false_positive_reduction": p.false_positive_reduction,
                "promoted_version": p.promoted_version
            }
            for p in lab.list_proposals()
        ],
        "audit_trail": gov.get_audit_trail()
    }


def shadow_run_trial(target, hypothesis, config):
    from uengine.shadow_lab import ShadowMLLaboratory
    from uengine.governance import PercivalGovernance
    lab = ShadowMLLaboratory()
    gov = PercivalGovernance()
    exp = lab.formulate_hypothesis(target, hypothesis, config or {})
    ok, prop = lab.run_experiment(exp)
    eval_res = gov.evaluate_proposal(prop) if prop else {}
    return {
        "ok": ok,
        "experiment_id": exp.experiment_id,
        "metrics_baseline": exp.metrics_baseline,
        "metrics_experimental": exp.metrics_experimental,
        "proposal": prop.__dict__ if prop else None,
        "governance_evaluation": eval_res
    }

