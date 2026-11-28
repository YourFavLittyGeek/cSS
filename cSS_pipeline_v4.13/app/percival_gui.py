"""percival_gui.py - the app side of PERCIVAL SCORE (v5.22). Everything runs on this computer (numpy); nothing is uploaded; no external
model or AI service is used (see docs/percival_app/LOCAL_AI_ARCHITECTURE.md).

  authorize()        the user's one-time switch for LOCAL learning on this project's MRI (app_data/ml_authorization.json, audited);
                     synthetic SYN studies of a synthetic project never need it
  gather(sid)        candidate rows of one study: ALBUS (score_v4), the NOX measurements (detector columns + uScore x1 / x2 / x5 from
                     uscore/features, extracted without perturbations when
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
import glob, hashlib, json, os, re, subprocess, sys, threading, time
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
            st_new = _stage_of(msg, JOB.get("stage", ""))
            if st_new != JOB.get("stage"): JOB.setdefault("stage_times", {}).setdefault(st_new, now)     # when each stage began
            JOB["heartbeat"] = now; JOB["stage"] = st_new; JOB.pop("stall", None)
        cancel = JOB.get("cancel") and JOB.get("state") in ACTIVE_STATES
    if cancel: raise Cancelled("cancelled by " + str(JOB.get("cancel_by", "you")))


# ------------------------------------------------------------------ v5.25 Training Center job monitor
class Cancelled(Exception): pass
ACTIVE_STATES = ("preparing", "running")
TERMINAL_STATES = ("finished", "failed", "cancelled", "interrupted", "insufficient_data")
TRANSITIONS = dict(idle={"preparing"}, preparing={"running", "failed", "cancelled", "insufficient_data"}, running={"finished", "failed", "cancelled"},
                   finished={"preparing"}, failed={"preparing"}, cancelled={"preparing"}, interrupted={"preparing"},
                   insufficient_data={"preparing"})                       # 3D fix: 'not enough expert labels' is a valid end state (was a crash)
STATE_LABEL = dict(idle="Idle", preparing="Preparing dataset", running="Training", finished="Completed", failed="Failed", cancelled="Cancelled",
                   interrupted="Interrupted", insufficient_data="Paused: expert labels needed")
# stage-aware stall limits (seconds without any reported work): dataset gathering reads MRI patches study by study; a training stage
# reports at least once per fold (nested cross-fitting: once per inner step). Overridable for tests: CSS_PERCIVAL_STALL_S
STALL_S = dict(preparing=300, components=600, nested=900, discovery=600, final=600, evaluation=300, registering=120)
# the stages of one cycle in the order they run (meta.train_cycle): shown in the Training Center as done / current / left
STAGES = [("preparing", "Preparing the dataset (every study's expert calls and image patches)"),
          ("components", "Component models: LUMOS images, NOX measurements (cross-validated)"),
          ("discovery", "PERCIVAL meta-model discovery and analyses"),
          ("final", "Final fit on the development cohort"),
          ("nested", "Nested cross-validation of the whole procedure"),
          ("evaluation", "Evaluation on the locked test group"),
          ("registering", "Registering the new model version")]


def _stages(now):
    """done / current / left / skipped for every stage, with how long each took (from the first log line of the stage)"""
    keys = [k for k, _ in STAGES]; cur = JOB.get("stage", ""); state = JOB.get("state", "idle"); T = JOB.get("stage_times", {})
    finished = state == "finished"; seen = [keys.index(x) for x in T if x in keys]
    ci = len(keys) if finished else keys.index(cur) if cur in keys else max(seen) if seen else -1   # failed / cancelled: where it stopped
    out = []
    for i, (k, lab) in enumerate(STAGES):
        st = "done" if (finished or i < ci) else "current" if i == ci and state in ACTIVE_STATES else "stopped" if i == ci else "left"
        if st == "done" and k not in T: st = "skipped"
        t0 = T.get(k); nxt = [T[x] for x in keys[i + 1:] if x in T]
        t1 = min(nxt) if nxt else (JOB.get("ended") or now)
        out.append(dict(key=k, label=lab, status=st, duration_s=round(t1 - t0) if t0 and st in ("done", "current", "stopped") else None))
    return out


def _stage_of(msg, cur):
    """the stage a log line belongs to, from how the engine STARTS its messages (meta.train_cycle / nested_crossfit). 2026-11-26: matching
    words anywhere misread lines - the dataset line names the 'locked test' (-> evaluation during preparation) and the final
    'v001 registered as experimental: ... nested development AUC' line read as 'nested'. Stages only move forward."""
    m = msg.strip().lower(); keys = [k for k, _ in STAGES]
    if m.startswith("nested"): st = "nested"
    elif m.startswith(("meta-model discovery", "percival analyses")): st = "discovery"
    elif m.startswith(("final fit", "calibration:")): st = "final"
    elif m.startswith("evaluation on the locked test"): st = "evaluation"
    elif m.startswith("registering") or re.match(r"v\d+ (registered|made active)", m): st = "registering"
    elif m.startswith(("component", "lumos image models", "nox measurement models", "components fold", "nox feature set", "frozen components")): st = "components"
    elif m.startswith(("cycle started", "dataset ")) or "eligible of" in m: st = "preparing"
    else: return cur or "preparing"
    if cur in keys and keys.index(st) < keys.index(cur): return cur          # never backwards
    return st


def _transition(new, **kw):
    """state machine of the training job: invalid transitions are refused (a completed job can never become running or stalled)"""
    with LOCK:
        old = JOB.get("state", "idle")
        if new not in TRANSITIONS.get(old, set()): raise RuntimeError(f"invalid training-job transition {old} -> {new}")
        JOB.update(state=new, **kw); JOB.setdefault("transitions", []).append(dict(frm=old, to=new, at=time.strftime("%Y-%m-%d %H:%M:%S")))
        if new in ACTIVE_STATES and kw.get("stage"): JOB.setdefault("stage_times", {}).setdefault(kw["stage"], time.time())   # progress card
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
                 retry_note="retry restarts the cycle from the beginning (no partial-result resume: a cycle is a single reproducible computation)",
                 active=JOB.get("state") in ACTIVE_STATES, stages=_stages(now), n_stages=len(STAGES))
        j["stages_left"] = sum(1 for x in j["stages"] if x["status"] == "left")
        j["stage_label"] = next((x["label"] for x in j["stages"] if x["key"] == JOB.get("stage")), JOB.get("stage") or "")
        j.pop("stage_times", None)
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
def readiness():
    """3D: is the project ready for a scientifically defensible training run? Every check is computed from the stored records (read only)."""
    from uengine.percival import split as SP, datasets as DS
    L = _ledger_mod(); roles = L.RR.current(B()); experts = sorted(v["name"] for v in roles.values() if v.get("role") == "expert")
    SL = selection(); n_css = sum(s["n_css"] for s in SL if s["included"]); n_mim = sum(s["n_mimic"] for s in SL if s["included"])
    dev_css = sum(s["css_dev"] for s in SL if s["included"]); dev_mim = sum(s["mimic_dev"] for s in SL if s["included"])
    SPV = SP.current(P()); ds = DS.listing(P()); last = DS.load(P(), ds[-1]["id"]) if ds else None
    ids = [identity(s["code"])["status"] for s in SL if s["included"]]
    checks = [dict(name="designated experts", ok=bool(experts), detail=", ".join(experts) or "none - assign roles (Reviewer calls)"),
              dict(name="local learning switched on", ok=bool(authorized()), detail=""),
              dict(name="eligible expert labels (development: >= 3 cSS, >= 3 not-cSS, >= 10 in all)", ok=dev_css >= 3 and dev_mim >= 3 and dev_css + dev_mim >= 10,
                   detail=f"development {dev_css} cSS / {dev_mim} not-cSS; all {n_css} / {n_mim}"),
              dict(name="patient identities verified for every included study", ok=bool(ids) and all(x in ("verified", "declared") for x in ids),
                   detail=f"{sum(1 for x in ids if x in ('verified', 'declared'))} of {len(ids)}"),
              dict(name="locked patient-level split", ok=bool(SPV and SPV.get("locked")), detail=(f"{SPV['version']} test fraction {SPV['test_fraction']}, "
                   f"{sum(1 for v in SPV['assignment'].values() if v == 'test')} test patients" if SPV else "not created yet (created at first use)")),
              dict(name="last dataset: leakage audit passed and only eligible expert labels", ok=bool(last) and (last.get("leakage_audit") or {}).get("passed") is True
                   and not last.get("readiness_problems"), detail=(f"{last['id']} {last['content_hash']}" if last else "no dataset built yet"))]
    # Stage 8: every prerequisite says what kind it is (real data / expert / approval / setting) - the readiness card lists exactly what is missing
    for c, k in zip(checks, ("expert", "approval", "expert", "real_data", "setting", "real_data")): c["category"] = k
    Pl = evaluation_plan(); ms = (Pl or {}).get("milestones") or []
    n_blind = 0
    try:
        import review_blind as _RB
        n_blind = sum(1 for s_ in SL if any(_RB.phase(B(), s_["code"], e)["completed"] for e in experts))
    except Exception: n_blind = 0
    checks += [dict(name="real MRI studies with a candidate list", category="real_data", ok=any(os.path.exists(os.path.join(B(), "review", f"{s_['code']}_candidates.csv")) for s_ in SL),
                    detail=f"{sum(1 for s_ in SL if os.path.exists(os.path.join(B(), 'review', s_['code'] + '_candidates.csv')))} studies"),
               dict(name="completed blind expert reads", category="expert", ok=n_blind > 0, detail=f"{n_blind} studies"),
               dict(name="pre-registered evaluation plan", category="approval", ok=bool(Pl), detail=f"version {Pl['version']} by {Pl['registered_by']}" if Pl else "not registered (PERCIVAL › System › Evaluation plan)"),
               dict(name="evaluation milestone declared", category="approval", ok=bool(ms), detail=ms[-1]["id"] + " " + ms[-1]["name"] if ms else "none"),
               dict(name="automatic training cycles off for the pilot", category="setting", ok=not CTX["SET"].get("percival_autocycle", False),
                    detail="on - switch off in Training Center" if CTX["SET"].get("percival_autocycle", False) else "off")]
    missing = {k: [c["name"] for c in checks if not c["ok"] and c["category"] == k] for k in ("real_data", "expert", "approval", "setting")}
    # 2026-11-28 (mission 3.4): the training-readiness GATE. These checks BLOCK a training cycle (train_async); the others (evaluation plan,
    # milestone, locked split / dataset created at first use, auto-cycle setting) are needed for acceptance or are created by the first cycle.
    by = {c["name"]: c for c in checks}
    def ok(n): return bool((by.get(n) or {}).get("ok"))
    tp = len([1 for v in ((SPV or {}).get("assignment") or {}).values() if v == "test"])
    stages = [dict(stage="data imported", ok=ok("real MRI studies with a candidate list"), detail=by["real MRI studies with a candidate list"]["detail"], blocks=True),
              dict(stage="expert review completed", ok=ok("completed blind expert reads") and ok("designated experts"),
                   detail=by["completed blind expert reads"]["detail"] + "; experts: " + by["designated experts"]["detail"], blocks=True),
              dict(stage="ground truth available", ok=ok("eligible expert labels (development: >= 3 cSS, >= 3 not-cSS, >= 10 in all)"),
                   detail=by["eligible expert labels (development: >= 3 cSS, >= 3 not-cSS, >= 10 in all)"]["detail"], blocks=True),
              dict(stage="training dataset eligible", ok=ok("eligible expert labels (development: >= 3 cSS, >= 3 not-cSS, >= 10 in all)")
                   and ok("patient identities verified for every included study"), detail=by["patient identities verified for every included study"]["detail"] + " identities verified", blocks=True),
              dict(stage="validation dataset eligible", ok=bool(SPV) and tp > 0,
                   detail=(f"{tp} locked-test patients" if SPV else "the locked split is created at the first cycle") +
                          " - acceptance additionally needs >= 5 test patients with and without cSS", blocks=False),
              dict(stage="model training permitted", ok=False, detail="", blocks=True)]
    gate_ok = all(st["ok"] for st in stages[:4]) and ok("local learning switched on")
    stages[-1].update(ok=gate_ok, detail="all blocking stages passed and local learning is switched on" if gate_ok else
                      "blocked: " + "; ".join([st["stage"] for st in stages[:4] if not st["ok"]] + ([] if ok("local learning switched on") else ["local learning is off"])))
    return dict(ready=all(c["ok"] for c in checks), training_permitted=gate_ok, stages=stages, checks=checks, missing=missing, policy="expert consensus of completed reviews; eligible provenance: "
                "verified_blind_post_3A, historical_blinding_verified; patient-level locked split; leakage audit before training")


def split_state(): from uengine.percival import split as SP; return dict(split=SP.current(P()), audits=sorted(os.path.basename(f) for f in glob.glob(P("split", "audit_*.json"))))


def split_new_version(fraction, by, reason, confirm): from uengine.percival import split as SP; return dict(ok=True, split=SP.new_version(P(), fraction, by, reason, confirm))


def export_dataset(did): from uengine.percival import datasets as DS; return DS.export(P(), did, P("exports", f"{did}_{time.strftime('%Y%m%d_%H%M%S')}"))


def _sources(sid):
    """3C: the exact inputs a study contributes to a dataset: sha256 of the candidate list, the detector manifest (+ its build), every
    reviewer calls file, the head of every review journal, and the derived missed-cSS file"""
    rd = os.path.join(B(), "review"); out = {}
    for n in (f"{sid}_candidates.csv", f"{sid}_manifest.json", f"{sid}_missed.csv"):
        if os.path.exists(os.path.join(rd, n)): out[n] = _sha(os.path.join(rd, n))
    m = _jl(os.path.join(rd, f"{sid}_manifest.json"), {}) or {}
    if m.get("build"): out["detector_build"] = str(m.get("build"))
    for f in sorted(glob.glob(os.path.join(rd, f"{sid}_calls_*.csv"))): out[os.path.basename(f)] = _sha(f)
    for f in sorted(glob.glob(os.path.join(rd, f"{sid}_events_*.jsonl"))):
        lines = [x for x in open(f, "rb").read().split(b"\n") if x.strip()]
        out[os.path.basename(f) + "#head"] = hashlib.sha256(lines[-1]).hexdigest()[:16] if lines else ""
    return out


def IDS():
    """Stage 5: the ONE identity service (patient, identity status, examination fingerprint, split assignment) - gathering, the split, the
    leakage audit and SHADOW all read it (uengine/identity_service.py)"""
    from uengine.identity_service import IdentityService
    return IdentityService(P(), CTX["patient_of"], CTX.get("identity_of"), CTX.get("fingerprint_of"), float(CTX["SET"].get("percival_test_fraction", 0.2)))


def _partition(patient):
    """3D: the ONE patient-level split (uengine/percival/split.py); created on first use with the configured fraction, then locked"""
    return IDS().partition(patient)


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
    files.append(os.path.join(B(), "review", "project_roles_events.jsonl"))   # I0: expert roles / adjudication permission decide eligibility
    import review_calls_gui as RCG
    key = RCG.file_key(files, B())                                           # Phase 3D review: content hashes, not millisecond mtimes
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
        if E.get("problems"):                                                  # Phase 3A.5: a reviewer file does not match its journal
            raise RuntimeError("review files need repair: " + "; ".join(E["problems"])[:300])
        GT = {"no_expert": "NO_EXPERT", "abstained": None, "unrecognised": None, "insufficient": "INSUFFICIENT_QUORUM", "disagreement": None,
              "incomplete": "INCOMPLETE_REVIEW", "pending_review": "REVIEW_NOT_COMPLETED"}
        for r in E["rows"]:                                                    # Phase 3A.3: expert ground truth only
            H = r.get("history") or []
            if not H: continue
            last = {}
            for e in H: last[e["reviewer"]] = e["call"]
            st = r.get("status"); call = r.get("effective_call") or ""
            if st in ("resolved", "adjudicated"):
                k = _kind(call); ok = bool(r.get("primary_eligible"))
                det[int(r["cand_id"])] = dict(kind=k, y=(1 if k == "css" else 0 if k == "mimic" else None) if ok else None, call=call, source="review",
                                              reviewer=r.get("source_reviewer", ""), conflict=False, calls=last, gt_status=st, gt_class=r.get("provenance_class", ""),
                                              gt_block=None if ok or k not in ("css", "mimic") else ("ADJUDICATED_NOT_CONSENSUS" if st == "adjudicated" else "NOT_PRIMARY_GROUND_TRUTH"))
            else:
                lc = H[-1]["call"]; k = "uncertain" if st == "abstained" else ("disputed" if st == "disagreement" else "unrecognised" if st == "unrecognised" else _kind(lc))
                det[int(r["cand_id"])] = dict(kind=k, y=None, call=lc if st == "unrecognised" else "", source="review", reviewer="", conflict=st == "disagreement", calls=last,
                                              gt_status=st, gt_class="", gt_block=GT.get(st, "NO_EXPERT"))
        n_hist = 0
        if use_h:
            for cid, H in _historical(sid, cand).items():
                if cid in det: continue                                     # a current call always wins
                last = {}
                for e in H: last[e["reviewer"]] = e["call"]
                ks = {_kind(x) for x in last.values()} & {"css", "mimic"}; call = H[-1]["call"]; k = _kind(call)
                det[cid] = dict(kind=k, y=None, call=call, source="historical", reviewer=H[-1]["reviewer"], conflict=len(ks) > 1, calls=last,
                                file=H[-1]["file"], gt_status="historical", gt_class="historical_blinding_unknown",
                                gt_block="NOT_PRIMARY_GROUND_TRUTH"); n_hist += 1          # Phase 3A.6: never primary unless adjudicated
        out = {cid: d["y"] for cid, d in det.items() if d["y"] is not None}
        st = L.review_state(B(), sid, "", pol)

        # Phase 3A.3: missed cSS from the reviewer-owned records (the derived review/{sid}_missed.csv); the reviewer's role and the read
        # provenance decide eligibility. Pensieve-only rows have no provenance and are not used.
        missed_detail = {}; roles = L.RR.current(B()); verified = L.RR.verified_reviewers(B(), sid)
        missed_csv = os.path.join(B(), "review", f"{sid}_missed.csv")
        if os.path.exists(missed_csv):
            try:
                import pandas as _mpd
                m_df = _mpd.read_csv(missed_csv, dtype=str).fillna("")
                for _, mr in m_df.iterrows():
                    mid = str(mr.get("missed_id", "")).strip()
                    if not mid: continue
                    rev = str(mr.get("reviewer", "")); role = L.RR.role_of(B(), rev, roles)
                    if mr.get("read_phase") == "initial" and mr.get("ai_visible") == "False": klass = "verified_blind_post_3A"
                    elif mr.get("read_phase"): klass = "not_blind_post_3A"
                    else: klass = "historical_blinding_verified" if L.slug(rev) in verified else "historical_blinding_unknown"
                    blk = "REVIEWER_NOT_EXPERT" if role != "expert" else (None if klass in L.PRIMARY_ELIGIBLE else "NOT_PRIMARY_GROUND_TRUTH")
                    missed_detail[f"missed_{mid}"] = dict(
                        missed_id=mid, reviewer=rev, role=role, time=str(mr.get("time", "")),
                        vox=(int(float(mr["vox_i"])), int(float(mr["vox_j"])), int(float(mr["vox_k"]))) if mr.get("vox_i") else (0, 0, 0),
                        mm=(float(mr["x_mm"]), float(mr["y_mm"]), float(mr["z_mm"])) if mr.get("x_mm") else (0.0, 0.0, 0.0),
                        plane=str(mr.get("plane", "")), slice_idx=int(float(mr["slice"])) if mr.get("slice") else 0,
                        shape=str(mr.get("shape", "point")), points=str(mr.get("points", "[]")), comment=str(mr.get("comment", "")),
                        detector_fate=str(mr.get("detector_fate", "")), context=str(mr.get("context", "")), gt_class=klass, gt_block=blk,
                        albus_detected=False, kind="css", y=1 if blk is None else None)
            except Exception: pass

        res = dict(labels=out, detail=det, css=sum(out.values()), mimic=len(out) - sum(out.values()),
                   missed_detail=missed_detail, n_missed=len(missed_detail), css_with_missed=sum(out.values()) + sum(1 for m_ in missed_detail.values() if m_["y"] == 1),
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
            PL.extract_study(B(), sid, _AppCohort(), os.path.join(B(), "uscore"), do_perturb=False, application=True)   # NOX: values only
        except Exception as e: log(f"{CTX['label'](sid)}: NOX uScore measurements not extracted ({type(e).__name__})")
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


def nox_feature_set():
    """Stage 2: the NOX feature list the Decision Engine trains on = the ACTIVE approved NOX version in the component registry
    (built-in v000 = the 9 detector measurements). -> (columns, version). Only names that are measurement columns are accepted."""
    from uengine.percival.meta import CHAR
    from uengine.percival import component_registry as CR
    try: A = CR.active(P(), "NOX")
    except Exception: A = dict(version="v000", config={})
    cols = [str(c) for c in ((A.get("config") or {}).get("feature_set") or CHAR)]
    from uengine.shadow_governed import is_label_like
    cols = [c for c in cols if not is_label_like(c)]
    return cols, A.get("version", "v000")


def component_configs():
    """Stage 2: what the next training cycle uses from the component registry -> (features or None, frozen families or None).
    NOX: feature_set (+ char_kind when frozen); LUMOS: image_kind when frozen. v000 = built-in, nothing frozen."""
    from uengine.percival import component_registry as CR
    try: A = {c: CR.active(P(), c) for c in CR.COMPONENTS}
    except Exception: return None, None
    cols, nxv = nox_feature_set()
    feats = dict(char=cols, nox_version=nxv, lumos_version=A["LUMOS"].get("version", "v000"), albus_version=A["ALBUS"].get("version", "v000"))
    nc, lc = A["NOX"].get("config") or {}, A["LUMOS"].get("config") or {}
    frozen = {k: v for k, v in dict(char=nc.get("char_kind"), image=lc.get("image_kind")).items() if v}
    changed = any(feats[k] != "v000" for k in ("nox_version", "lumos_version", "albus_version"))
    return (feats if changed else None), (frozen or None)


def component_freeze(comp, by, reason, confirm):
    """Stage 2: freeze ONE component at its configuration in the active (else latest) model: a new registry version that later training
    cycles reuse without re-selecting its family (the meta-model is refitted on top). Named person + typed phrase + reason; rollback with
    component_rollback. Never changes the active PERCIVAL model."""
    from uengine.percival import component_registry as CR
    M = _model_any()
    if not M or not M.get("component_config"): return dict(ok=False, error="no trained model with component configurations yet")
    comp = str(comp).upper()
    if comp not in ("NOX", "LUMOS"): return dict(ok=False, error="only NOX and LUMOS have trainable configurations (ALBUS changes go through SHADOW)")
    mr = ((M.get("modules") or {}).get(comp) or {})                        # 2026-11-25 per-module loop: adopt only an improved version
    if mr.get("verdict") == "not improved":
        return dict(ok=False, error=f"{comp} in model {M.get('version')} did not improve on its previous version (log loss {mr.get('logloss'):.3f} vs "
                                    f"{mr.get('previous_logloss'):.3f}) - not adopted; the active {comp} version stays")
    cc = M["component_config"][comp]; cur = dict(CR.active(P(), comp).get("config") or {})
    cfg = dict(cur, **({"char_kind": cc["char_kind"], "feature_set": cc["feature_set"]} if comp == "NOX" else {"image_kind": cc["image_kind"]}),
               frozen_from_model=M["version"], component_sha256=(M.get("component_versions") or {}).get("char" if comp == "NOX" else "image", {}).get("sha256"))
    try:
        V = CR.approve(P(), comp, cfg, by, reason, confirm, evidence=dict(kind="component_freeze", model=M["version"],
                       component_metrics=(M.get("component_metrics") or {}).get("char" if comp == "NOX" else "image")))
    except CR.RegistryError as e: return dict(ok=False, error=str(e))
    return dict(ok=True, version=V["version"], config=cfg)


def component_rollback(comp, by, reason, confirm):
    from uengine.percival import component_registry as CR
    try: return dict(ok=True, active=CR.rollback(P(), str(comp).upper(), by, reason, confirm))
    except CR.RegistryError as e: return dict(ok=False, error=str(e))


def _gather(sid, labelled=True):
    import pandas as pd
    from uengine.percival.meta import CHAR, PREDICTORS, test_assignment
    cp = os.path.join(B(), "review", f"{sid}_candidates.csv")
    if not os.path.exists(cp): return []
    deps = [cp, os.path.join(B(), "uscore", "features", f"{sid}.json"), os.path.join(B(), "review", f"{sid}_missed.csv")]   # + LUMOS marks
    import review_calls_gui as RCG
    NX, _nv = nox_feature_set(); EXTRA = [c for c in NX if c not in CHAR]   # Stage 2: approved extra NOX measurements are gathered too
    deps.append(os.path.join(B(), "review", f"{sid}_qc.json"))                 # Stage 3: calibration subgroups
    from uengine.imaging import geometry as _G
    key = RCG.file_key(deps, B()) + [int(may_read(sid))] + ([["nox_extra"] + EXTRA] if EXTRA else []) \
          + [["envelope", _G.MAX_INPLANE_MM, _G.MAX_SLICE_MM, _G.VOXEL_TOL_MM]]                  # a new voxel-size limit re-extracts the patches
    cj, cz = P("cache", f"{sid}.json"), P("cache", f"{sid}.npz"); C = _jl(cj, {})
    if C.get("key") != key or C.get("v") != 7 or not os.path.exists(cz):        # v5: NOX set with x1 / x2 / x5; v6: missed-mark patches (LUMOS); v7 (2026-11-28): marks grown to their 3-D extent + current fate
        if CTX.get("ensure_local"):                                         # images moved to Pensieve after the review: bring them back first
            try:
                el = CTX["ensure_local"](sid)
                if el and not el.get("ok", True): log(f"{CTX['label'](sid)}: images not brought back from Pensieve ({el.get('error', '')[:80]})")
            except Exception as e: log(f"{CTX['label'](sid)}: images not brought back from Pensieve ({type(e).__name__})")
        QC = _jl(os.path.join(B(), "review", f"{sid}_qc.json"), {}) or {}; AQ = QC.get("acquisition") or {}
        fs = AQ.get("field_T")
        sub = dict(field_strength=(None if fs in (None, "") else ("1.5T" if float(fs) < 2 else "3T")), sequence=AQ.get("sequence") or None,
                   anatomy=("T1" if str(QC.get("anatomy", "")).startswith("T1") else QC.get("anatomy") or None), qc=QC.get("status") or None)
        cand = pd.read_csv(cp); pred = _predictors(sid); maps = _maps(sid) if may_read(sid) else {}
        rows = []
        for _, r in cand.iterrows():
            cid = int(r["cand_id"]); ch = {}
            _parts = [q for c_ in EXTRA if "*" in c_ for q in c_.split("*", 1)]
            for c in dict.fromkeys(list(CHAR) + [c_ for c_ in EXTRA if "*" not in c_] + _parts):
                src = "volume_mm3" if c == "log_volume_mm3" else c
                v = r.get(src) if src in cand.columns else ((pred.get(cid) or {}).get(c) if c in PREDICTORS else None)
                v = None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)
                ch[c] = (float(np.log(max(v, 1.0))) if c == "log_volume_mm3" and v is not None else v)
            for c in [c_ for c_ in EXTRA if "*" in c_]:                     # Stage 4: approved interaction = product of two measurements
                a_, b_ = c.split("*", 1); ch[c] = None if ch.get(a_) is None or ch.get(b_) is None else float(ch[a_]) * float(ch[b_])
            tier = r.get("review_tier") if "review_tier" in cand.columns else None
            rows.append(dict(study=sid, cand_id=cid, math=float(r["score_v4"]) if "score_v4" in cand.columns and not pd.isna(r["score_v4"]) else 0.0,
                             hemi=str(r["hemi"]) if "hemi" in cand.columns else "", pred=pred.get(cid, {}), char=ch, has_maps=cid in maps,
                             albus=dict(review_tier=None if tier is None or (isinstance(tier, float) and np.isnan(tier)) else str(int(float(tier)))),
                             subgroups=sub))
        marks, mk_maps = _mark_maps(sid) if may_read(sid) else ([], {})          # 2026-11-25: LUMOS learns from expert-marked missed cSS
        os.makedirs(os.path.dirname(cz), exist_ok=True)
        with open(cz + ".tmp", "wb") as f_: np.savez_compressed(f_, **{str(k): v for k, v in maps.items()}, **mk_maps)
        os.replace(cz + ".tmp", cz)                                               # atomic: a reader never sees a half-written cache
        C = dict(key=key, v=7, rows=rows, marks=marks); _js(cj, C)
    with np.load(cz) as Zf: Z = {k: Zf[k] for k in Zf.files}
    rows = []; pat = IDS().patient(sid)
    test = bool(pat) and _partition(pat) == "test"                           # no patient: never trained on (eligibility); 3D split authority
    for r in C["rows"]:
        rows.append(dict(r, patient=pat, test=test, maps=Z.get(str(r["cand_id"]))))
    if labelled:
        L, _ = _labels(sid); rows = [dict(r, y=L[r["cand_id"]]) for r in rows if r["cand_id"] in L]
    return rows


def _lumos_marks(sid, E):
    """the missed-cSS marks of one study that LUMOS learns from: eligible expert truth (cSS), development partition, with an image patch,
    and not lying on a candidate the detector showed (that candidate has its own call)"""
    # 2026-11-28: the fate is the CURRENT detector output against the enclosed area (fate_now, computed at gathering); the fate stored when
    # the mark was drawn (from the drawn line, at that detector version) is only the fallback for marks gathered before this build
    ok = {e["cand_id"] for e in E if str(e["cand_id"]).startswith("missed_") and e["status"] == "eligible" and e["partition"] == "development" and e.get("y") == 1}
    if not ok: return []
    fate0 = {e["cand_id"]: str(e.get("detector_fate") or "") for e in E}
    return [m for m in gather_marks(sid) if m["cand_id"] in ok and not m["test"]
            and not str(m.get("fate_now") or fate0.get(m["cand_id"], "")).startswith("overlaps shown candidate")]


# ------------------------------------------------------------------ balanced locked test group (2026-11-26)
def patient_classes():
    """{patient: 'css' | 'no_css'} from FINISHED expert reviews: cSS = an expert cSS call or an eligible expert-marked missed cSS in any of the
    patient's studies; no_css = finished review(s) without either. Patients without a finished review are not classified."""
    out = {}
    for p_ in _study_list():
        c = p_["code"]; lab = label_summary(c)
        if lab.get("state") != "reviewed": continue
        pat = IDS().patient(c)
        if not pat: continue
        has = lab.get("css", 0) > 0 or any(m.get("y") == 1 for m in (lab.get("missed_detail") or {}).values())
        out[str(pat)] = "css" if has or out.get(str(pat)) == "css" else "no_css"
    return out


def _trained_patients():
    """patients whose studies any registered model was trained on (they can never become test patients)"""
    pats = set()
    for v in versions():
        M = load(v) or {}
        for st in (M.get("data") or {}).get("trained_on") or []:
            p_ = IDS().patient(st)
            if p_: pats.add(str(p_))
    return pats


def test_group_state():
    from uengine.percival import split as SP, meta as MT
    S = SP.current(P()) or {}; cl = patient_classes(); A = S.get("assignment") or {}
    cnt = {c: dict(test=sum(1 for p_, k in cl.items() if k == c and A.get(p_) == "test"),
                   development=sum(1 for p_, k in cl.items() if k == c and A.get(p_) == "development")) for c in ("css", "no_css")}
    plan = SP.balance_plan(P(), cl, _trained_patients(), MT.MIN_TEST_PATIENTS_PER_CLASS)
    return dict(version=S.get("version"), mode=S.get("mode", "hash"), counts=cnt, minimum=MT.MIN_TEST_PATIENTS_PER_CLASS,
                plan=dict(add=len(plan["add"]), by_class={c: sum(1 for k in plan["add"].values() if k == c) for c in ("css", "no_css")},
                          after=plan["after"], short=plan["short"], development_after=plan["development_after"]),
                confirm=SP.CONFIRM_BALANCE, unclassified=sum(1 for p_ in A if p_ not in cl), **_fresh_info())


def _sealed():
    from uengine.percival import split as SP
    try: return SP.sealed(P())
    except Exception: return set()


def _fresh_info():
    from uengine.percival import split as SP
    S = SP.current(P()) or {}; cl = patient_classes(); fr = SP.fresh_state(P(), cl)
    mem = set(map(str, ((S.get("fresh") or {}).get("members") or [])))
    early = {c: sum(1 for p_, k in cl.items() if k == c and (S.get("assignment") or {}).get(p_) == "test" and p_ not in mem) for c in ("css", "no_css")}
    return dict(policy=S.get("policy", "random"), fresh=fr, early_test=early, target=SP.FRESH_TARGET, policy_log=(S.get("policy_log") or [])[-5:],
                confirm_dev_only=SP.CONFIRM_DEV_ONLY, confirm_fresh=SP.CONFIRM_FRESH, confirm_open=SP.CONFIRM_OPEN)


def test_group_policy(policy, by, reason, confirm, target=None):
    from uengine.percival import split as SP
    try: S = SP.set_policy(P(), policy, by, reason, confirm, **({"target": int(target)} if target else {}))
    except (SP.SplitError, PermissionError, ValueError) as e: return dict(ok=False, error=str(e))
    _event("config_changed", by, split=S["version"], policy=policy); _LCACHE.clear()
    return dict(ok=True, policy=S["policy"], version=S["version"])


def test_group_open(by, reason, confirm):
    from uengine.percival import split as SP
    try: S = SP.open_final(P(), by, reason, confirm)
    except (SP.SplitError, PermissionError) as e: return dict(ok=False, error=str(e))
    _event("config_changed", by, split=S["version"], final_test_opened=True); _LCACHE.clear()
    return dict(ok=True, opened=S["fresh"]["opened"])


def test_group_balance(by, reason, confirm):
    from uengine.percival import split as SP, meta as MT
    try:
        S = SP.balance(P(), patient_classes(), by, reason, confirm, frozen=_trained_patients(), min_per_class=MT.MIN_TEST_PATIENTS_PER_CLASS)
    except (SP.SplitError, PermissionError) as e: return dict(ok=False, error=str(e))
    _event("config_changed", by, split=S["version"], balanced=len(S["balance"]["added"])); _LCACHE.clear()
    return dict(ok=True, version=S["version"], added=len(S["balance"]["added"]), after=S["balance"]["after"], short=S["balance"]["short"])


# ------------------------------------------------------------------ ALBUS re-detection of the expert-marked missed cSS (2026-11-25)
AREDO = {"thread": None, "queue": []}


def _marks_input(sid):
    md = label_summary(sid).get("missed_detail") or {}; out = {}
    for k, d in md.items():
        try: strokes = json.loads(d.get("points") or "[]")
        except ValueError: strokes = []
        out[k] = dict(strokes=strokes, shape=d.get("shape", "point"), plane=d.get("plane", ""), fate=d.get("detector_fate", ""))
    return out


def _scripts_dir():
    """the detector the app runs (the installed scripts; the repository's when it has no albus_measure.py yet)"""
    s_ = CTX.get("SC") or os.path.join(B(), "scripts")
    return s_ if os.path.exists(os.path.join(s_, "albus_measure.py")) else os.path.join(os.path.dirname(HERE), "scripts")


def _aredo_worker():
    import albus_redetect as AR_
    while AREDO["queue"]:
        sid = AREDO["queue"].pop(0)
        try:
            if CTX.get("ensure_local"): CTX["ensure_local"](sid)
            AR_.run(B(), sid, _marks_input(sid), P("albus_redetect"), scripts=_scripts_dir(), python=CTX.get("python") or sys.executable, log=log)
        except Exception as e:
            _js(P("albus_redetect", f"{sid}.json"), dict(study=sid, key="failed", error=f"{type(e).__name__}: {str(e)[:200]}", marks={}))
    AREDO["thread"] = None


def albus_marks(sid, start=True):
    """ALBUS's re-detection of every missed-cSS mark of a study + the reviewers' confirmations. Starts the re-detection in the background
    when the marks changed (one study at a time). -> dict(state, marks={key: ...}, confirmations)"""
    import albus_redetect as AR_
    mk = _marks_input(sid)
    if not mk: return dict(state="no_marks", marks={})
    key = AR_.marks_key(mk, _scripts_dir()); R = _jl(P("albus_redetect", f"{sid}.json"), {}) or {}
    conf = _mark_confirmations(sid)
    if R.get("key") == key: return dict(state="done", marks=R.get("marks", {}), at=R.get("at"), confirmations=conf, uscore_note=R.get("uscore_note"))
    if start and may_read(sid):
        if sid not in AREDO["queue"]: AREDO["queue"].append(sid)
        if AREDO["thread"] is None:
            AREDO["thread"] = threading.Thread(target=_aredo_worker, daemon=True); AREDO["thread"].start()
    return dict(state="running" if start else "pending", marks=R.get("marks", {}) if R.get("key") else {}, confirmations=conf,
                note="ALBUS is measuring the marked lesions (a few minutes per study)")


def _mark_confirmations(sid):
    """{mark key: {reviewer: dict(status correct / wrong, object_sha, role)}} from review/ID_missed_confirm_by_<reviewer>.csv"""
    import pandas as pd
    L = _ledger_mod(); roles = L.RR.current(B()); out = {}
    for f in sorted(glob.glob(os.path.join(B(), "review", f"{sid}_missed_confirm_by_*.csv"))):
        try: df = pd.read_csv(f, dtype=str).fillna("")
        except Exception: continue
        for _, r in df.iterrows():
            out.setdefault(f"missed_{r['missed_id']}", {})[r["reviewer"]] = dict(status=r["status"], object_sha=r["object_sha"], time=r["time"],
                                                                                role=L.RR.role_of(B(), r["reviewer"], roles))
    return out


def _confirmed(rec, conf):
    """an ALBUS object teaches NOX / PERCIVAL only when an EXPERT said 'correct' for THIS object and no expert said 'wrong'"""
    if not rec or rec.get("status") != "measured": return False
    ex = [c for c in (conf or {}).values() if c["role"] == "expert" and c["object_sha"] == rec.get("object_sha")]
    return any(c["status"] == "correct" for c in ex) and not any(c["status"] == "wrong" for c in ex)


def _char_from(meas, pred):
    """the NOX measurements of a re-detected object, with the same mapping as gather() uses for candidates"""
    from uengine.percival.meta import CHAR, PREDICTORS
    NX, _nv = nox_feature_set(); EXTRA = [c for c in NX if c not in CHAR]; ch = {}
    parts = [q for c_ in EXTRA if "*" in c_ for q in c_.split("*", 1)]
    for c in dict.fromkeys(list(CHAR) + [c_ for c_ in EXTRA if "*" not in c_] + parts):
        src = "volume_mm3" if c == "log_volume_mm3" else c
        v = meas.get(src) if src in meas else ((pred or {}).get(c) if c in PREDICTORS else None)
        try: v = None if v is None or v == "" else float(v)
        except (TypeError, ValueError): v = None
        if v is not None and not np.isfinite(v): v = None
        ch[c] = float(np.log(max(v, 1.0))) if c == "log_volume_mm3" and v is not None else v
    for c in [c_ for c_ in EXTRA if "*" in c_]:
        a_, b_ = c.split("*", 1); ch[c] = None if ch.get(a_) is None or ch.get(b_) is None else float(ch[a_]) * float(ch[b_])
    return ch


def confirmed_mark_rows(sid, E=None):
    """CONFIRMED ALBUS re-detections of eligible expert marks -> rows for NOX / PERCIVAL (and their patch for LUMOS): dict(study, cand_id,
    patient, test, y=1, math=None, char, maps, origin='mark'). E: the study's eligibility examples (training) or None (scoring: every
    confirmed object)."""
    A = albus_marks(sid, start=False)
    if A.get("state") != "done": return []
    ok = None if E is None else {e["cand_id"] for e in E if str(e["cand_id"]).startswith("missed_") and e["status"] == "eligible" and e.get("y") == 1}
    f0 = {e["cand_id"]: str(e.get("detector_fate") or "") for e in (E or [])}
    # 2026-11-28: a mark whose enclosed area lies on a SHOWN candidate is that candidate (it has its own call): current fate first
    keys = [k for k, r in A["marks"].items() if _confirmed(r, A["confirmations"].get(k)) and (ok is None or k in ok)
            and not str(r.get("fate_now") or f0.get(k, "")).startswith("overlaps shown candidate")]
    if not keys: return []
    zp = P("albus_redetect", f"{sid}.npz")
    if not os.path.exists(zp): return []
    with np.load(zp) as Zf: V = {k: Zf[k] for k in Zf.files if k in keys}
    cache = P("cache", f"{sid}_albus.npz"); C = {}
    if os.path.exists(cache):
        with np.load(cache) as Zc: C = {k: Zc[k] for k in Zc.files}
    import nibabel as nib
    need = {k: v for k, v in V.items() if f"{k}|{A['marks'][k]['object_sha']}" not in C}
    if need and may_read(sid):
        from uengine.imaging import patches as PT
        from uengine.percival.cnn import patch_maps
        shp = nib.load(os.path.join(B(), "data", f"{sid}_swi.nii")).shape[:3]; objs = {}
        for k, v in need.items():
            m = np.zeros(shp, bool); m[tuple(np.asarray(v, int).T)] = True; objs[k] = m
        try:
            E2 = PT.extract_objects(B(), sid, objs)
            for k, a in E2["patches"].items():
                mp = patch_maps(a)
                if mp is not None: C[f"{k}|{A['marks'][k]['object_sha']}"] = mp
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            with open(cache + ".tmp", "wb") as f_: np.savez_compressed(f_, **C)
            os.replace(cache + ".tmp", cache)
        except Exception as e: log(f"{CTX['label'](sid)}: patches of the re-detected marks not made ({type(e).__name__})")
    pat = IDS().patient(sid); test = bool(pat) and _partition(pat) == "test"; out = []
    for k in keys:
        r = A["marks"][k]
        out.append(dict(study=sid, cand_id=k, patient=pat, test=test, y=1, math=None, origin="mark", hemi=str((r.get("measurements") or {}).get("hemi", "")),
                        char=_char_from(r.get("measurements") or {}, r.get("uscore")), maps=C.get(f"{k}|{r['object_sha']}"),
                        how=r.get("source", ""), object_sha=r["object_sha"]))
    return out


def albus_miss_report():
    """step 4: where ALBUS loses the expert-marked cSS, over every study with marks"""
    import albus_redetect as AR_
    studies = [p["code"] for p in _study_list() if os.path.exists(os.path.join(B(), "review", f"{p['code']}_missed.csv"))]
    res = {s_: _jl(P("albus_redetect", f"{s_}.json"), None) for s_ in studies}
    return AR_.fate_report(B(), studies, res)


# ------------------------------------------------------------------ LUMOS second look (2026-11-25; inactive until enough marks)
SLOOK = {}                                     # study -> running thread


def second_look_status():
    from uengine.percival import second_look as SLK
    return SLK.status(active(), CTX["SET"])


def second_look(sid):
    """suggestions of possible missed cSS for the reviewer: only when the active model passes the activation gate. The scan runs in the
    background; the result is kept per model version and candidate list (percival/second_look/ID.json + .npz with the patches)"""
    import review_calls_gui as RCG
    from uengine.percival import second_look as SLK
    st = second_look_status()
    if not st["active"]: return dict(st, suggestions=[])
    if not may_read(sid): return dict(st, active=False, reasons=["study images not readable"], suggestions=[])
    key = [st["model"], SLK.VERSION] + RCG.file_key([os.path.join(B(), "review", f"{sid}_candidates.csv")], B())
    jp, zp = P("second_look", f"{sid}.json"), P("second_look", f"{sid}.npz"); R = _jl(jp, {}) or {}
    if R.get("key") == key: return dict(st, **{k: v for k, v in R.items() if k != "key"}, decided=_sl_decided(sid, st["model"]))
    t = SLOOK.get(sid)
    if t is not None and t.is_alive(): return dict(st, running=True, suggestions=[])
    def run():
        try:
            from uengine.percival import meta as MT
            if CTX.get("ensure_local"): CTX["ensure_local"](sid)
            net = MT.Components.from_json(active()["components"]).image
            r = SLK.scan(B(), sid, net); maps = r.pop("maps", {})
            os.makedirs(os.path.dirname(zp), exist_ok=True)
            with open(zp + ".tmp", "wb") as f_: np.savez_compressed(f_, **maps)
            os.replace(zp + ".tmp", zp); _js(jp, dict(r, key=key, model=st["model"], at=time.strftime("%Y-%m-%d %H:%M:%S")))
            log(f"{CTX['label'](sid)}: LUMOS second look - {len(r['suggestions'])} suggestion(s) from {r.get('n_spots', 0)} dark spots")
        except Exception as e:
            _js(jp, dict(key=key, suggestions=[], error=f"{type(e).__name__}: {str(e)[:120]}"))
    th = threading.Thread(target=run, daemon=True); SLOOK[sid] = th; th.start()
    return dict(st, running=True, suggestions=[])


def _sl_decided(sid, model):
    """suggestions of this model already answered in this study (any reviewer): {key: 'accepted' | 'rejected'}"""
    import pandas as pd
    out = {}
    for f in glob.glob(os.path.join(B(), "review", f"{sid}_lumos_rejects_by_*.csv")):
        try:
            for _, r in pd.read_csv(f, dtype=str).fillna("").iterrows():
                if r.get("model") == model: out[r["key"]] = "rejected"
        except Exception: pass
    mp = os.path.join(B(), "review", f"{sid}_missed.csv")
    if os.path.exists(mp):
        try:
            import re as _re
            for _, r in pd.read_csv(mp, dtype=str).fillna("").iterrows():
                m_ = _re.match(r"LUMOS suggestion (spot_\d+) \(([^)]*)\)", str(r.get("comment", "")))
                if m_ and m_.group(2) == model: out[m_.group(1)] = "accepted"
        except Exception: pass
    return out


def _lumos_rejects(sid, test):
    """the LUMOS suggestions an EXPERT reviewer rejected in this study -> 'not cSS' image examples (y = 0) for LUMOS training. The patch is
    the one LUMOS was shown (kept with the suggestions). A suggestion another expert accepted as a missed cSS is not used."""
    if test: return []
    zp = P("second_look", f"{sid}.npz")
    if not os.path.exists(zp): return []
    import pandas as pd
    L = _ledger_mod(); roles = L.RR.current(B()); pat = IDS().patient(sid); out = {}
    with np.load(zp) as Zf: Z = {k: Zf[k] for k in Zf.files}
    for f in sorted(glob.glob(os.path.join(B(), "review", f"{sid}_lumos_rejects_by_*.csv"))):
        try: df = pd.read_csv(f, dtype=str).fillna("")
        except Exception: continue
        for _, r in df.iterrows():
            if L.RR.role_of(B(), r["reviewer"], roles) != "expert" or r["key"] not in Z: continue
            out[r["key"]] = dict(study=sid, cand_id=f"lumos_reject_{r['key']}", patient=pat, test=False, maps=Z[r["key"]], y=0,
                                 how="LUMOS suggestion rejected by an expert", vox=(r["vox_i"], r["vox_j"], r["vox_k"]))
    return list(out.values())


def _mark_maps(sid):
    """image patches (LUMOS maps) of every active missed-cSS mark of a study, with the candidate patch extractor -> (records, maps)"""
    md = label_summary(sid).get("missed_detail") or {}
    if not md: return [], {}
    from uengine.imaging import patches as PT
    from uengine.percival.cnn import patch_maps
    marks = {}
    for k, d in md.items():
        try: strokes = json.loads(d.get("points") or "[]")
        except ValueError: strokes = []
        marks[k] = dict(strokes=strokes, shape=d.get("shape", "point"), plane=d.get("plane", ""))
    try: E = PT.extract_marks(B(), sid, marks)
    except Exception as e:
        log(f"{CTX['label'](sid)}: missed-cSS patches not made ({type(e).__name__}: {str(e)[:80]})")
        return [dict(cand_id=k, has_maps=False, skip=f"{type(e).__name__}") for k in marks], {}
    out, recs = {}, []
    for k in marks:
        m = patch_maps(E["patches"][k]) if k in E["patches"] else None
        if m is not None: out[k] = m
        recs.append(dict(cand_id=k, has_maps=m is not None, how=E["how"].get(k, ""), skip=E["skipped"].get(k, "" if m is not None else "no valid SWI in the patch"),
                         fate_now=(E.get("fates") or {}).get(k)))
    return recs, out


def gather_marks(sid):
    """expert-marked missed cSS of a study as LUMOS image examples: dict(study, cand_id, patient, test, maps, y=1, how) per mark with a patch.
    Uses the gathered cache (gather() makes it)."""
    gather(sid, labelled=False)
    C = _jl(P("cache", f"{sid}.json"), {}); cz = P("cache", f"{sid}.npz")
    if not C.get("marks") or not os.path.exists(cz): return []
    pat = IDS().patient(sid); test = bool(pat) and _partition(pat) == "test"
    with np.load(cz) as Zf: Z = {k: Zf[k] for k in Zf.files if k.startswith("missed_")}
    return [dict(study=sid, cand_id=m["cand_id"], patient=pat, test=test, maps=Z[m["cand_id"]], y=1, how=m.get("how", ""), fate_now=m.get("fate_now"))
            for m in C["marks"] if m.get("has_maps") and m["cand_id"] in Z]


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
    test = bool(pat) and _partition(pat) == "test"; cache = rows if rows is not None else (_cached_rows(sid) or {})   # 3D split authority
    out = []
    for cid, d in sorted(det.items()):
        r = cache.get(cid)
        has_img = None if r is None else bool(r.get("maps") is not None if rows is not None else r.get("has_maps"))
        n_char = None if r is None else sum(v is not None for v in (r.get("char") or {}).values())
        ev = EL.evaluate(dict(label_kind=d["kind"], conflict=d["conflict"], gt_block=d.get("gt_block"),   # Phase 3A: unresolved never used
                              historical=d["source"] == "historical", study_excluded=meta.get("excluded"), study_archived=meta.get("archived_out"),
                              duplicate=meta.get("duplicate"), authorized=may_read(sid), has_image=has_img is not False, n_char=n_char is None or n_char > 0,
                              test=test, qc=meta.get("qc"), identity=idn["status"]))
        out.append(dict(study=sid, cand_id=cid, patient=pat, identity=idn["status"], y=d["y"], call=d["call"], label_source=d["source"], reviewer=d.get("reviewer", ""),
                        gt_class=d.get("gt_class", ""), gt_status=d.get("gt_status", ""),
                        partition=ev["partition"], status=ev["status"], reasons=ev["reasons"], components={k: v["ok"] for k, v in ev["components"].items()},
                        component_reasons={k: v["reasons"] for k, v in ev["components"].items() if v["reasons"]},
                        missing=sorted({m for v in ev["components"].values() for m in v.get("missing", [])}),
                        rules=EL.RULES_VERSION, evaluated=time.strftime("%Y-%m-%d %H:%M:%S"), checked=r is not None))

    for mid, md in sorted(lab.get("missed_detail", {}).items()):              # Phase 3A.3: through the eligibility engine (was always 'eligible')
        ev = EL.evaluate(dict(label_kind="css", gt_block=md.get("gt_block"), study_excluded=meta.get("excluded"), study_archived=meta.get("archived_out"),
                              duplicate=meta.get("duplicate"), authorized=may_read(sid), has_image=True, n_char=True, test=test, identity=idn["status"]))
        out.append(dict(study=sid, cand_id=mid, patient=pat, identity=idn["status"], y=md.get("y"), call="cSS", label_source="expert_missed_lesion",
                        reviewer=md.get("reviewer", ""), partition=ev["partition"], status=ev["status"], gt_class=md.get("gt_class", ""), gt_status="expert_mark",
                        reasons=ev["reasons"],
                        components=dict(char=False, image=True, meta=True, shadow=True,
                                        detection=True, segmentation=md.get("shape") in ("pen", "rect", "polygon")),
                        component_reasons=dict(char=["NO_MEASUREMENTS"]),
                        missing=[], rules=EL.RULES_VERSION, evaluated=time.strftime("%Y-%m-%d %H:%M:%S"), checked=True,
                        albus_detected=False, coords_vox=md.get("vox"), coords_mm=md.get("mm"),
                        detector_fate=md.get("detector_fate"), comment=md.get("comment", "")))
    return out


def selection():
    """v5.24: every study of the project (and reviewed studies found on disk but missing from the study list) with the separate states
    the Training Center shows: registered / processed (candidate list) / reviewed (state) / labelled candidates / eligible / used.
    Eligibility per candidate comes from the Training Eligibility Engine (uengine/percival/eligibility.py)."""
    S = CTX["SET"]; ex = set(S.get("learner_exclude", []))
    arch_ok = S.get("features", {}).get("train_include_archived", True) if isinstance(S.get("features"), dict) else True
    out = []
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
        elif not lab["detail"] and not lab.get("n_missed"): reason = "no expert call yet" + (f" ({lab['stale']} earlier call(s) need confirmation in Review)" if lab["stale"] else "")
        else:
            from uengine.percival.eligibility import REASONS
            codes = sorted({x for e in E for x in e["reasons"][:1]}); reason = "; ".join(REASONS.get(x, x) for x in codes)[:200]
        out.append(dict(code=c, label=CTX["label"](c) if not p["_orphan"] else c, cohort=p.get("cohort", ""), reviewed=rev,
                        processed=os.path.exists(os.path.join(B(), "review", f"{c}_candidates.csv")), n_candidates=lab.get("n_candidates", 0),
                        review_state=lab.get("state_label") or lab.get("state", ""), n_css=lab["css"], n_mimic=lab["mimic"], n_unused=lab["unused"],
                        n_missed=lab.get("n_missed", 0),
                        n_stale=lab["stale"], n_conflicts=lab.get("conflicts", 0), n_historical=lab.get("historical", 0), label_error=lab.get("error", ""),
                        n_labelled=len(E), n_eligible=len(el), n_eligible_dev=sum(1 for e in el if e["partition"] == "development"),
                        css_dev=sum(1 for e in el if e["partition"] == "development" and e["y"] == 1),
                        mimic_dev=sum(1 for e in el if e["partition"] == "development" and e["y"] == 0),
                        n_adjudication=sum(1 for e in E if e["status"] == "needs_adjudication"), unrecognised=lab.get("unrecognised", []),
                        not_in_study_list=p["_orphan"], archived=bool(p.get("archived")), retired=bool(p.get("retired")),
                        included=bool(el) and not why, excluded_why=why, why=reason,
                        identity=identity(c)["status"],
                        partition=IDS().record(c)["partition"]))
    return out


def candidates_of(sid):
    """Training Center drill-down: every called candidate of one study with its eligibility per component and the reasons in words"""
    from uengine.percival.eligibility import explain
    S = CTX["SET"]; ex = set(S.get("learner_exclude", [])); p = next((x for x in _study_list() if x["code"] == sid), {})
    arch = bool(p.get("archived")) and not (S.get("features", {}).get("train_include_archived", True) if isinstance(S.get("features"), dict) else True)
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
    src = {c: _sources(c) for c in (m.get("sources") or {})}                 # 3C: today's input files, compared with the stored hashes
    R = DS.reproduce(P(), did, exs, EL.RULES_VERSION, sources=src); R["ok"] = True
    R["source_files_changed"] = sorted(c for c in src if src[c] != (m.get("sources") or {}).get(c)); return R


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
        for k, name in (("char", "NOX · measurements"), ("image", "LUMOS · MRI patch")):
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
    _event("rollback" if why == "rollback" else "approval", by, model=v, previous=prev, why=why, override=bool(override),
           acceptance_passed=bool((M.get("acceptance") or {}).get("passed")))
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
    # 2026-11-28 (mission 3.4): the readiness gate BLOCKS training - missing data, reviews or ground truth are never treated as negatives and
    # a cycle cannot start on them. CSS_TRAIN_GATE=off (tests) is honoured only when EVERY study of the project is synthetic.
    def _all_synthetic():
        try: codes = [p["code"] for p in CTX["patients"]()]
        except Exception: return False
        return bool(codes) and all(synthetic(c) for c in codes)
    if not (os.environ.get("CSS_TRAIN_GATE") == "off" and _all_synthetic()):
        try: R = readiness()
        except Exception as e: R = dict(training_permitted=False, stages=[dict(stage="readiness check", ok=False, detail=f"{type(e).__name__}: {e}")])
        if not R.get("training_permitted"):
            why = "; ".join(f"{st['stage']}: {st.get('detail', '')}" for st in R.get("stages", []) if not st.get("ok") and st.get("blocks", True))
            return dict(ok=False, error="training is not permitted yet - " + (why or "readiness check failed"), stage="readiness_gate", readiness=R.get("stages"))
        for k in ("cancel", "cancel_by", "cancel_at", "stall", "ended", "resources_peak", "resources_last", "samples", "transitions"): JOB.pop(k, None)
    _transition("preparing", log=[], progress=0.0, error="", reason=reason, started=time.time(), heartbeat=time.time(), stage="preparing",
                stage_times=dict(preparing=time.time()))
    th = threading.Thread(target=_train, args=(reason,), daemon=True)
    with LOCK: JOB["thread"] = th
    th.start(); return dict(ok=True, started=True)


def _code_version():
    """the engine code that trained a model: BUILD stamp of the installed pipeline + sha256 of the Percival engine sources"""
    d = os.path.join(ROOT, "unified_engine", "uengine", "percival"); h = hashlib.sha256()
    # 2026-11-28 (audit S18): also the calibration / logistic code, the image patch extractor and the detector + call ledger, and the
    # library versions - a model must be traceable to every piece of code that produced its inputs and its fit
    extra = [os.path.join(ROOT, "unified_engine", "uengine", "ml_component.py")] + sorted(glob.glob(os.path.join(ROOT, "unified_engine", "uengine", "imaging", "*.py"))) \
        + [os.path.join(ROOT, "scripts", n) for n in ("detect_css.py", "call_ledger.py", "surface_aligned_patch.py")]
    files = sorted(glob.glob(os.path.join(d, "*.py"))) + [f for f in extra if os.path.exists(f)]
    for f in files:
        h.update(os.path.relpath(f, ROOT).encode())
        with open(f, "rb") as fh: h.update(fh.read())
    b = ""
    for p in (os.path.join(B(), "scripts", "BUILD"), os.path.join(ROOT, "scripts", "BUILD")):
        if os.path.exists(p): b = open(p).read().strip()[:80]; break
    import platform, numpy as _np
    try: import scipy as _sp; spv = _sp.__version__
    except Exception: spv = None
    return dict(build=b, engine_sha256=h.hexdigest()[:16], hashed_files=len(files), python=platform.python_version(), numpy=_np.__version__, scipy=spv)


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
    _event("training_run", RUN.get("reason") or "PERCIVAL", run=RUN["id"], state=state_, dataset=kw.get("dataset"), version=kw.get("version"),
           config=config_snapshot()["sha256"])


def _event(etype, actor, **payload):
    """Stage 5: append to the hash-chained project event log; a failure is logged, never raised into the caller"""
    try:
        from uengine import event_log as EV
        return EV.append(P(), etype, actor, **payload)
    except Exception as e:
        log(f"[event log] {etype} not recorded ({type(e).__name__}: {e})"); return None


CONFIG_KEYS = ("percival_test_fraction", "percival_learn_from", "percival_use_historical", "percival_autocycle", "learner_exclude", "features")


def config_snapshot():
    """Stage 5: ONE versioned configuration record - settings that change learning, feature flags, component versions, engine and rule
    versions. Content-hashed; a changed configuration is stored once (percival/config/<sha>.json) with a config_changed event."""
    from uengine.percival import component_registry as CR, eligibility as EL, meta as MT, split as SP
    S = CTX.get("SET") or {}
    try: comps = {c: CR.active(P(), c)["version"] for c in CR.COMPONENTS}
    except Exception: comps = {}
    sp = SP.current(P()) or {}
    C = dict(settings={k: S.get(k) for k in CONFIG_KEYS if k in S}, components=comps, engine=MT.ENGINE, eligibility_rules=EL.RULES_VERSION,
             split_version=sp.get("version"), active_model=active_version())
    h = hashlib.sha256(json.dumps(C, sort_keys=True, default=str).encode()).hexdigest()[:16]
    p = P("config", f"{h}.json")
    if not os.path.exists(p):
        _js(p, dict(C, sha256=h, first_seen=time.strftime("%Y-%m-%d %H:%M:%S")))
        _event("config_changed", "PERCIVAL", sha256=h, components=comps)
    return dict(C, sha256=h)


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
        _transition("preparing", log=[], progress=0.0, error="", reason=reason, started=time.time(), heartbeat=time.time(), stage="preparing",
                    stage_times=dict(preparing=time.time()))
    _run_start(reason)
    try:
        SL = selection(); sel = [s["code"] for s in SL if s["included"]]
        if not sel:
            msg = ("No studies currently have eligible expert-reviewed labels for supervised learning. "
                   "At least 3 expert-confirmed cSS and 3 rejected candidates (or mimics) across at least 10 candidates "
                   "in the development cohort are required before a valid supervised training cycle can proceed. "
                   "Please open the Review tab to review detected candidates or mark missed cSS lesions in the MRI viewer.")
            log(f"training paused: {msg}", 0.0)
            _transition("insufficient_data", stage="data_needed", error=msg)
            _run_end("insufficient_data", error=msg)
            return dict(ok=False, error=msg, stage="data_needed")

        if not all(may_read(c) for c in sel): raise ValueError("local learning is not switched on (PERCIVAL › Switch on local learning)")
        from uengine.percival import datasets as DS, eligibility as EL
        integ = integrity([x["code"] for x in SL if x["n_labelled"] or x.get("n_missed")])     # v5.24: conflicts / duplicates over EVERY labelled study
        dup = set(integ["duplicates"]) & set(sel); rows, exs = [], []
        log(f"cycle started ({reason}): {len(sel)} studies with eligible labels", 0.01)
        S = CTX["SET"]; ex = set(S.get("learner_exclude", [])); marks = []; cmarks = []
        SEAL = _sealed(); n_seal = 0
        for k, c in enumerate(sel):
            if str(IDS().patient(c) or "") in SEAL:                    # 2026-11-26: fresh test cohort, sealed until opened once
                n_seal += 1; continue
            g = {r["cand_id"]: r for r in gather(c, labelled=False)}
            E = _examples(c, dict(excluded=c in ex, duplicate=c in dup), rows=g); exs += E
            cr = confirmed_mark_rows(c, E) if IDS().patient(c) else []
            if cr: cmarks += cr; log(f"{CTX['label'](c)}: {len(cr)} confirmed ALBUS re-detection(s) of missed cSS (NOX / PERCIVAL)", 0.01 + 0.06 * (k + 1) / len(sel))
            mk = _lumos_marks(c, E)
            if cr:                                       # LUMOS sees ALBUS's confirmed object instead of the drawn region
                best = {r["cand_id"]: r for r in cr if r.get("maps") is not None}
                mk = [dict(m, maps=best[m["cand_id"]]["maps"], how=best[m["cand_id"]]["how"]) if m["cand_id"] in best else m for m in mk]
            if mk: marks += mk; log(f"{CTX['label'](c)}: {len(mk)} expert-marked missed cSS used as LUMOS image examples", 0.01 + 0.06 * (k + 1) / len(sel))
            _pt = bool(IDS().patient(c)) and _partition(IDS().patient(c)) == "test"
            rj = _lumos_rejects(c, _pt) if IDS().patient(c) else []
            if rj: marks += rj; log(f"{CTX['label'](c)}: {len(rj)} rejected LUMOS suggestion(s) used as 'not cSS' image examples", 0.01 + 0.06 * (k + 1) / len(sel))
            for e in E:
                if e["components"]["meta"] and e["cand_id"] in g:
                    r = dict(g[e["cand_id"]], y=e["y"])
                    if not e["components"]["image"]: r["maps"] = None
                    rows.append(r)
            log(f"{CTX['label'](c)}: {sum(1 for e in E if e['components']['meta'])} eligible of {len(E)} called candidates", 0.01 + 0.06 * (k + 1) / len(sel))
        if n_seal: log(f"{n_seal} studies of the sealed fresh test cohort left out (never trained on; evaluated only after the final test is opened)", 0.07)
        for s_ in SL:                                   # labelled studies that are left out: recorded in the manifest with their reasons
            if s_["code"] not in sel and (s_["n_labelled"] or s_.get("n_missed")):
                exs += _examples(s_["code"], dict(excluded=s_["code"] in ex or bool(s_["excluded_why"]), archived_out="archived" in s_["excluded_why"]))
        from uengine.percival import split as SP                                # 3C/3D: sources, split, leakage audit, readiness
        SPV = SP.current(P()) or {}
        audit = SP.leakage_audit(exs, fingerprint_of=IDS().fingerprint, held_out=SP.held_out_elsewhere(B()))
        man = DS.build(exs, EL.RULES_VERSION, P(), sources={c: _sources(c) for c in sorted({e["study"] for e in exs})},
                       split=dict(version=SPV.get("version"), assignment_sha256=SPV.get("assignment_sha256"), test_fraction=SPV.get("test_fraction")),
                       extra=dict(leakage_audit=audit, settings=dict(learn_from=S.get("percival_learn_from", "labelled"),
                       use_historical=S.get("percival_use_historical", True), split_version=SPV.get("version"))))
        _js(P("split", f"audit_{man['id']}.json"), dict(dataset=man["id"], content_hash=man["content_hash"], split=man.get("split"), audit=audit,
                                                         readiness_problems=man.get("readiness_problems")))
        if not audit["passed"] or man.get("readiness_problems"):
            msg = ("training refused before it started: " + "; ".join(audit["errors"] + (man.get("readiness_problems") or [])[:5])
                   + f" (dataset {man['id']}, see percival/split/audit_{man['id']}.json)")
            log(msg, 0.075); _transition("failed", stage="refused", error=msg); _run_end("failed", error=msg, dataset=man["id"])
            return dict(ok=False, error=msg, stage="refused")
        log(f"dataset {man['id']} (content {man['content_hash']}): {man['n_examples']} called candidates, meta-model development "
            f"{man['components']['meta']['development']['n']} / locked test {man['components']['meta']['test']['n']}", 0.075)
        dv = [r for r in rows if not r.get("test")]; tv = [r for r in rows if r.get("test")]
        c1, c0 = sum(r["y"] for r in dv), sum(1 - r["y"] for r in dv); t1, t0 = sum(r["y"] for r in tv), sum(1 - r["y"] for r in tv)
        if min(c1, c0) < 3 or len(dv) < 10:
            msg = (f"Insufficient expert labels for supervised meta-learning. The development cohort currently has {c1} cSS "
                   f"and {c0} not-cSS calls (at least 3 of each and 10 in all are needed); the locked test cohort holds {t1} cSS "
                   f"and {t0} not-cSS. Dataset {man['id']}: see Training Center for every study and candidate that was left out and why. "
                   f"Review more studies that contain cSS (press Y on each cSS candidate, or draw missed cSS in the viewer) and start the cycle again.")
            log(f"training paused: {msg}", 0.075)
            _transition("insufficient_data", stage="data_needed", error=msg)
            _run_end("insufficient_data", error=msg, dataset=man["id"])
            return dict(ok=False, error=msg, stage="data_needed")
        idc = {}
        for c in sel: idc[identity(c)["status"]] = idc.get(identity(c)["status"], 0) + 1
        _transition("running", stage="components")
        v = f"v{len(versions()) + 1:03d}"
        feats, frozen = component_configs()                                   # Stage 2: active approved NOX feature set + frozen families
        if feats: log(f"NOX feature set {feats['nox_version']}: {len(feats['char'])} measurements", 0.08)
        if frozen: log("frozen components (component registry): " + ", ".join(f"{k}={v}" for k, v in frozen.items()), 0.08)
        M = MT.train_cycle(rows, v, cnn_epochs=int(os.environ.get("CSS_PERCIVAL_EPOCHS", "30")), progress=lambda m, p: log(m, p), mins=_env_min(),
                           features=feats, frozen=frozen, previous=_model_any(), image_extra=marks, char_extra=cmarks,
                           test_css_patients={p_ for p_, k in patient_classes().items() if k == "css"})
        M["data"].update(dataset=man["id"], dataset_hash_manifest=man["content_hash"], eligibility_rules=EL.RULES_VERSION,
                         split=man.get("split"), leakage_audit=dict(passed=audit["passed"], checks=audit["checks"]),
                         feature_schema=DS.FEATURE_SCHEMA, patch_spec=DS.PATCH_SPEC, code_version=_code_version())
        from uengine.percival import architecture as AR                       # architecture: component-level version records
        M["component_versions"] = AR.component_versions(M)
        M["config_snapshot"] = config_snapshot(); M["identity_digest"] = IDS().digest(sel)          # Stage 5: configuration + identity record
        M["data"]["identity"] = dict(idc, policy="only verified / declared patient identities are used (v5.25)")
        log("registering", 0.9)                                    # last cancellation point: nothing has been written to the registry yet
        M["integrity"] = integ; M["reason"] = reason; M["run_id"] = RUN.get("id"); M["seed"] = 0; M["cnn_epochs"] = int(os.environ.get("CSS_PERCIVAL_EPOCHS", "30")); act = active(); acc = MT.acceptance(M, act)
        acc = test_reuse_gate(M, acc, sorted({str(r["patient"]) for r in tv})); M["acceptance"] = acc     # Stage 6: no test-set reuse
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
        CTX["notify"](f"PERCIVAL Decision Engine {v} trained", ("made active" if H[-1]["promoted"] else "waiting for your approval" if acc["passed"] else "experimental") + f" · {M['data']['studies']} studies")
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
    if not S.get("percival_autocycle", False) or not authorized() or JOB["state"] in ACTIVE_STATES: return False
    done = {s["code"] for s in selection() if s["included"]}; last = set(_jl(P("last_cycle.json"), {}).get("finished", []))
    if len(done - last) >= int(S.get("percival_cycle_n", 5)): train_async(f"{len(done - last)} newly finished studies"); return True
    return False


# ------------------------------------------------------------------ scoring + prediction ledger
def _run_id(sid):
    a = _jl(os.path.join(B(), "runs", sid, "active.json"), {}); return a.get("run_id") or "initial"


EXPERIMENTAL_LABEL = "EXPERIMENTAL · CORE Fixed-Weight Baseline (comparison only, not validated) - never the PERCIVAL prediction"


def experimental_core_enabled():
    """Phase 0: the ALBUS / LUMOS / NOX / CORE layer runs only when explicitly switched on (default off)"""
    try: return bool(((CTX.get("SET") or {}).get("features") or {}).get("experimental_core", False))
    except Exception: return False


# Stage 1 (retirement): the legacy ALBUS / NOX engines are thin adapters over the REAL detector measurements of the candidate (the NOX
# CHAR columns gathered for the PERCIVAL engine). Before, missing measurements were replaced by invented defaults (darkness -1.5, tube 1.5,
# cortex 0.5 ...) so CORE produced a number for a candidate with no evidence. Now a candidate without the measurements is 'unavailable'.
# The comparison never writes the legacy PENSIEVE and never touches the external Data Vault (legacy_guard null objects).
CORE_INPUTS = dict(pial_distance="pial_dist_mm", darkness_z="darkness_z", tube_ratio="tube_ratio", cortex_frac="cortex_frac", tram_frac="tram_frac")


def _core_inputs(r):
    ch = r.get("char") or {}; out = {}; missing = []
    for k, c in CORE_INPUTS.items():
        v = ch.get(c)
        try: v = float(v)
        except (TypeError, ValueError): v = float("nan")
        if np.isfinite(v): out[k] = v
        else: missing.append(c)
    return (None if missing else out), missing


def _core_engines():
    from uengine.percival_core import PercivalCoreIntelligence
    from uengine.albus import AlbusDiscoveryEngine
    from uengine.lumos import LumosImageIntelligence
    from uengine.nox import NoxCharacteristicsEngine
    from uengine.legacy_guard import NullPensieve, NullVault
    _p, _v = NullPensieve(), NullVault()
    return (PercivalCoreIntelligence(pensieve=_p, vault=_v), AlbusDiscoveryEngine(pensieve=_p),
            LumosImageIntelligence.from_percival_model(active(), pensieve=_p, vault=_v), NoxCharacteristicsEngine(pensieve=_p))


def _core_assess(sid, r, engines):
    """one candidate through the CORE comparison baseline -> dict (score None + reason when its real inputs are missing)"""
    _core, _albus, _lumos, _nox = engines
    raw, missing = _core_inputs(r)
    if raw is None:
        return dict(label=EXPERIMENTAL_LABEL, score=None, band=None, status="unavailable", reason="missing NOX measurements: " + ", ".join(missing))
    cid = int(r.get("cand_id", 0)); h = str(r.get("hemi", "U") or "U")
    cand_a = _albus.discover_candidate(sid, cid, h, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), 0, 0.0, (0, 0, 0, 0, 0, 0), raw)
    cand_n = _nox.measure_candidate(sid, cid, raw)
    cand_l = _lumos.analyze_patch(sid, cid, r.get("patch") if isinstance(r.get("patch"), dict) else None)
    asmt = _core.evaluate_candidate(cand_a, cand_l, cand_n)
    return dict(label=EXPERIMENTAL_LABEL, score=asmt.percival_score, band=asmt.band,
                status=asmt.status if asmt.percival_score is not None else "unavailable", uncertainty=asmt.uncertainty, inputs=raw,
                lumos="trained" if getattr(_lumos, "trained", False) else "untrained")


def _experimental_core(sid, S, rows):
    """evaluate the experimental layer for each scored candidate; results go to s['experimental_core'] only"""
    try:
        engines = _core_engines(); by = {int(r.get("cand_id", 0)): r for r in rows}
        for s in S:
            try: s["experimental_core"] = _core_assess(sid, by.get(int(s.get("cand_id", 0)), {}), engines)
            except Exception as e:
                s["experimental_core"] = dict(label=EXPERIMENTAL_LABEL, score=None, band=None, status="unavailable", error=type(e).__name__)
    except Exception as e:
        log(f"[experimental core] {sid}: not evaluated ({type(e).__name__}: {e})")



def score_study(sid, M=None):
    from uengine.percival import meta as MT
    M = M or active()
    if not M: return None
    rows = gather(sid, labelled=False)
    if not rows: return None
    S = MT.score_rows(M, rows); hemi = {r["cand_id"]: r.get("hemi", "") for r in rows}
    for s in S: s["hemi"] = hemi.get(s["cand_id"], "")

    # Phase 0 (scientific integrity): the ALBUS / LUMOS / NOX / CORE layer is an unvalidated EXPERIMENTAL research layer.
    # It runs only when Settings features.experimental_core is on (default off), and its output is stored ONLY under
    # s["experimental_core"] - it never writes percival_score / band / status, so a missing CORE result can never
    # replace the trained Percival Score.
    if experimental_core_enabled():
        _experimental_core(sid, S, rows)

    # Study score with the reader's own scoring method, on the candidates Percival calls. 2026-11-26 (audit A1): the candidates are chosen
    # with the MODEL'S OWN calibrated cuts (its bands), not a fixed 50: 'total' = green candidates (likely cSS, specificity-first cut),
    # 'total_upper' = green + yellow (sensitivity-first cut, red_below), so the grade is shown as a range when they differ. Candidates
    # PERCIVAL holds back for expert review (no score) are counted: the study is 'needs_review' and its grade is a lower bound - never a
    # silent negative. A study in which NO candidate has a valid score is UNASSESSABLE (score_css is not run).
    valid = [s for s in S if s.get("percival_score") is not None]
    held = [s["cand_id"] for s in S if s.get("percival_score") is None and s.get("status") in ("review", "insufficient")]
    ids = [s["cand_id"] for s in valid if s.get("band") == "green"]
    ids_up = [s["cand_id"] for s in valid if s.get("band") in ("green", "yellow")]
    th = M.get("thresholds") or {}
    study = dict(n_called=len(ids), called_ids=ids, n_called_upper=len(ids_up), called_ids_upper=ids_up, n_review=len(held), review_ids=held,
                 L_score=None, R_score=None, total=None, total_upper=None, error="", n_scored=len(valid), n_candidates=len(S),
                 cuts=dict(green_from=th.get("green_from"), red_below=th.get("red_below"),
                           basis="the model's calibrated cuts: green = likely cSS (total), green + yellow = possible cSS (total_upper)"))
    def _grade(sel, tag):
        r = subprocess.run([sys.executable, os.path.join(CTX["SC"], "score_css.py"), sid, "--accept-ids", ",".join(map(str, sel)) or "none", "--tag", tag],
                           capture_output=True, text=True, timeout=600, env=dict(os.environ, CSS_BASE=B(), PYTHONWARNINGS="ignore"))
        J = _jl(os.path.join(B(), "review", f"{sid}_score_{tag}.json"), {})
        return J, ("" if r.returncode == 0 else (r.stderr or r.stdout)[-160:])
    if not valid:
        study.update(status="unassessable", reason="no candidate has a valid PERCIVAL score (insufficient or unavailable evidence) - "
                                                   "this is not a negative result")
    else:
        study["status"] = "needs_review" if held else "scored"
        if held: study["reason"] = f"{len(held)} candidate(s) need expert review (PERCIVAL abstained): the grade is a lower bound"
        try:
            J, err = _grade(ids, "percival")
            study.update(L_score=J.get("L_score"), R_score=J.get("R_score"), total=J.get("multifocality_0_4"), error=err)
            if ids_up != ids:
                J2, err2 = _grade(ids_up, "percival_upper")
                study.update(L_upper=J2.get("L_score"), R_upper=J2.get("R_score"), total_upper=J2.get("multifocality_0_4"), error=err or err2)
            else: study.update(L_upper=study["L_score"], R_upper=study["R_score"], total_upper=study["total"])
        except Exception as e: study["error"] = type(e).__name__
    in_tr = sid in set((M.get("data") or {}).get("trained_on") or [])
    rec = dict(study=sid, model=M["version"], run=_run_id(sid), created=time.strftime("%Y-%m-%d %H:%M:%S"), ready=M["ready"], thresholds=M["thresholds"],
               in_training=in_tr, in_training_note="this study's expert labels were used to train this model: its scores are in-sample (optimistic)" if in_tr else "",
               candidates=S, study_score=study, note=M["note"], kind="AI prediction (PERCIVAL score) - not a human review",
               provenance=dict(model=M["version"], engine=M.get("engine", ""), dataset=(M.get("data") or {}).get("dataset", "(trained before v5.24 - no manifest)"),
                               feature_schema=(M.get("data") or {}).get("feature_schema", ""), code=(M.get("data") or {}).get("code_version", {}),
                               processing_run=_run_id(sid)))
    try:                                                         # 2026-11-25 PERCIVAL scores the confirmed re-detected missed cSS (NOX + LUMOS)
        rec["missed_marks"] = MT.score_marks(M, confirmed_mark_rows(sid))
        if rec["missed_marks"]: rec["missed_marks_note"] = "expert-marked missed cSS, re-detected by ALBUS and confirmed: PERCIVAL without ALBUS (NOX + LUMOS); not part of the 0-4 score"
    except Exception as e: rec["missed_marks_error"] = type(e).__name__
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
    """v5.25: Evaluate candidate rows using the reconstructed PercivalCoreIntelligence pipeline.
    Phase 0: EXPERIMENTAL and off by default (Settings features.experimental_core); read-only, never a Percival Score."""
    if not experimental_core_enabled():
        return dict(ok=False, experimental=True, error="The CORE fixed-weight baseline is experimental and switched off "
                                                       "(Settings › features.experimental_core). It is never the PERCIVAL score.")
    rows = gather(sid, labelled=False)
    if not rows:
        return dict(ok=False, error=f"No candidates found for study {sid}")
    engines = _core_engines(); assessments = []
    for r in rows:
        try: a = _core_assess(sid, r, engines)
        except Exception as e: a = dict(label=EXPERIMENTAL_LABEL, score=None, status="unavailable", error=type(e).__name__)
        assessments.append(dict(a, cand_id=int(r.get("cand_id", 0))))
    return dict(ok=True, study=sid, count=len(assessments), assessments=assessments, experimental=True, label=EXPERIMENTAL_LABEL)


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
        SEAL = _sealed(); pats = [c for c in pats if str(IDS().patient(c) or "") not in SEAL]        # 2026-11-26: the sealed final test
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
                    ys.append(lab[cid]); ps.append(x["percival_score"] / 100); gs.append(IDS().patient(sid))
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
        if not mri:                                                   # 2026-11-25: moved to Pensieve after review = MRI available
            try:
                import pensieve_move as _PMV
                mri = _PMV.in_pensieve(B(), c)
            except ImportError: pass
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
                   percival_note="no PERCIVAL score existed for this study when the review was saved" if shown is None else "the newest prediction created before the save",
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
    job = job_state(); job.pop("log", None)                                                     # stages, elapsed, ETA (v5.25 progress card)
    with LOCK: jlog = JOB["log"][-60:]                                                          # job FIRST (v5.23): a cycle finishing while
    vs = versions(); latest = load(vs[-1]) if vs else None; M = active(); sel = selection()      # this runs must not look finished with old versions
    strip = lambda m: None if not m else {k: v for k, v in m.items() if k not in ("components", "meta_ensemble")}
    return dict(authorized=authorized(), autocycle=CTX["SET"].get("percival_autocycle", False), cycle_n=int(CTX["SET"].get("percival_cycle_n", 5)),
                test_fraction=CTX["SET"].get("percival_test_fraction", 0.2), learn_from=CTX["SET"].get("percival_learn_from", "labelled"), job=job, log=jlog,
                active=strip(M), latest=strip(latest), versions=vs, history=_jl(P("history.json"), []), promotions=_jl(P("registry", "promotions.json"), []),
                selection=sel, n_selected=sum(1 for s in sel if s["included"]),
                labels=dict(css=sum(s["n_css"] for s in sel if s["included"]), mimic=sum(s["n_mimic"] for s in sel if s["included"]),
                            css_dev=sum(s["css_dev"] for s in sel if s["included"]), mimic_dev=sum(s["mimic_dev"] for s in sel if s["included"]),
                            missed=sum(s.get("n_missed", 0) for s in sel), css_with_missed=sum(s["n_css"] + s.get("n_missed", 0) for s in sel if s["included"]),
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
                              missed_lesions=sum(s.get("n_missed", 0) for s in sel),
                              valid_mri=sum(1 for x in sel if x["processed"] or not x.get("not_in_study_list")),
                              awaiting_review=sum(1 for x in sel if x["processed"] and not x["reviewed"]),
                              eligible_candidate_classification=sum(x["n_eligible"] for x in sel),
                              eligible_detection=sum(x["n_eligible"] + x.get("n_missed", 0) for x in sel),
                              excluded=sum(x["n_labelled"] - x["n_eligible"] - x["n_adjudication"] for x in sel)))


# -------------------------------------------------------------
# PERCIVAL DATA VAULT, PENSIEVE & SHADOW ML BACKEND SERVICES
# -------------------------------------------------------------
PENSIEVE_RETIRED = ("the legacy PENSIEVE sqlite memory is retired (docs/engineering/DEPRECATIONS.md); PENSIEVE is the per-project index "
                    "rebuilt from the authoritative records: /api/percival/pensieve_index")


def pensieve_state():
    """retired legacy tile: answers with the per-project PENSIEVE index summary instead of the global legacy database"""
    return dict(ok=True, retired=True, message=PENSIEVE_RETIRED, index=pensieve_index_state())


def pensieve_query(component):
    return dict(ok=False, retired=True, error=PENSIEVE_RETIRED, component=str(component))


def vault_status(root=None):
    from uengine.vault import get_vault
    v = get_vault(root)                     # the CURRENT configured path (a bare get_vault() kept the first one)
    stats = v.get_storage_stats()
    integrity = v.verify_integrity() if v.is_connected() else {"ok": False}
    return {"stats": stats, "integrity": integrity}


def vault_connect(path, root=None):
    from uengine.vault import get_vault
    v = get_vault(root)                     # the CURRENT configured path (a bare get_vault() kept the first one)
    ok, msg = v.connect(path)
    return {"ok": ok, "message": msg, "stats": v.get_storage_stats()}


def vault_create(destination, name="PERCIVAL_VAULT"):
    from uengine.vault import PercivalDataVault
    try:
        v = PercivalDataVault.create_vault(destination, name=name)
        return {"ok": True, "message": f"Vault created at {v.root_path}", "stats": v.get_storage_stats()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def vault_eject(root=None):
    from uengine.vault import get_vault
    v = get_vault(root)                     # the CURRENT configured path (a bare get_vault() kept the first one)
    ok, msg = v.safe_eject()
    return {"ok": ok, "message": msg}


def vault_backup(destination, root=None):
    from uengine.vault import get_vault
    v = get_vault(root)                     # the CURRENT configured path (a bare get_vault() kept the first one)
    ok, msg = v.create_backup(destination)
    return {"ok": ok, "message": msg}


SHADOW_DEMO_LABEL = ("SYNTHETIC DEMONSTRATION (retired Shadow Lab fixed trials): synthetic benchmark only, never evidence, never "
                     "promoted, never written to project memory. Governed discovery: SHADOW tab.")


def _legacy_lab():
    from uengine.shadow_lab import ShadowMLLaboratory
    from uengine.governance import PercivalGovernance
    from uengine.legacy_guard import NullPensieve, NullVault
    _p, _v = NullPensieve(), NullVault()
    return ShadowMLLaboratory(pensieve=_p, vault=_v), PercivalGovernance(pensieve=_p, vault=_v)


def shadow_lab_state():
    lab, gov = _legacy_lab()
    return {"label": SHADOW_DEMO_LABEL, "retired": True,
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
    lab, gov = _legacy_lab()
    exp = lab.formulate_hypothesis(target, hypothesis, config or {})
    ok, prop = lab.run_experiment(exp)
    eval_res = gov.evaluate_proposal(prop) if prop else {}
    return {
        "ok": ok,
        "experiment_id": exp.experiment_id,
        "metrics_baseline": exp.metrics_baseline,
        "metrics_experimental": exp.metrics_experimental,
        "proposal": prop.__dict__ if prop else None,
        "governance_evaluation": eval_res,
        "label": SHADOW_DEMO_LABEL, "synthetic": True, "promoted": False
    }



# ------------------------------------------------------------------ PERCIVAL architecture (ALBUS / NOX / LUMOS / PERCIVAL / CORE / PENSIEVE / SHADOW)
def _model_any():
    """the active model, else the latest trained version (for reports); None when nothing was trained"""
    M = active()
    if M: return M
    vs = versions()
    return load(vs[-1]) if vs else None


def architecture_state():
    """honest operational state of every component, from what exists in this project (no module counts as active because it exists)"""
    from uengine.percival import architecture as AR, component_registry as CR
    from uengine import pensieve_index as PI
    M = active(); X = _model_any(); SL = selection(); codes = [s["code"] for s in SL]
    det = [c for c in codes if os.path.exists(os.path.join(B(), "review", f"{c}_candidates.csv"))]
    vers = {}
    for c in det: vers.setdefault(AR.detector_version(B(), c).get("version") or "unversioned", []).append(c)
    feats = sum(os.path.exists(os.path.join(B(), "uscore", "features", f"{c}.json")) for c in det)
    reg = CR.overview(P()); ps = PI.summary(B())
    comps = [
            dict(key="ALBUS", name=AR.NAMES["ALBUS"], implementation="scripts/detect_css.py (candidate generation, rules E1–E30, score_v4)",
                 state="active" if det else "awaiting_data", detail=f"{len(det)} studies with a candidate list; detector versions: {len(vers)}",
                 versions={k: len(v) for k, v in vers.items()}, registry=reg["ALBUS"]["active"]["version"],
                 validation="sensitivity / missed-lesion recall needs eligible expert reviews" ),
            dict(key="NOX", name=AR.NAMES["NOX"], implementation="the candidate's measurements: 27 detector measurements + uScore x1 / x2 / x5",
                 state="active" if det else "awaiting_data", detail=f"measurements for {len(det)} studies; uScore x1 / x2 / x5 extracted for {feats}",
                 registry=reg["NOX"]["active"]["version"], feature_set=(reg["NOX"]["active"].get("config") or {}).get("feature_set"),
                 validation="trained inside PERCIVAL" if X else "untrained (no PERCIVAL model yet)"),
            dict(key="LUMOS", name=AR.NAMES["LUMOS"], implementation="PERCIVAL SmallCNN on MRI patches (the same trained weights)",
                 state=AR.lumos_state(M)["state"] if M else "untrained", detail=AR.lumos_state(M).get("reason") or AR.lumos_state(M).get("source"),
                 calibrated=False, validation="component logit; calibrated only within the PERCIVAL decision"),
            dict(key="PERCIVAL", name=AR.NAMES["ENGINE"], implementation="trainable meta-model + calibration + OOD + thresholds (uengine/percival)",
                 state=("active" if M else "trained_not_active" if X else "untrained"), model=(M or X or {}).get("version"),
                 accepted=((M or X or {}).get("acceptance") or {}).get("passed"), ready=(M or X or {}).get("ready"),
                 detail="no model trained yet" if not X else ("active model " + M["version"] if M else f"{X['version']} trained, not made active (Model Center)"),
                 validation="locked-test evaluation once per model; acceptance needs approval in Model Center"),
            dict(key="CORE", name=AR.NAMES["CORE"], implementation="uengine/percival_core.py (fixed weights)",
                 state="enabled_comparison" if experimental_core_enabled() else "off", detail="comparison only - never the PERCIVAL prediction",
                 validation="not validated (fixed hand-set weights)"),
            dict(key="PENSIEVE", name=AR.NAMES["PENSIEVE"], implementation="per-project index rebuilt from journals, call ledger, missed marks, prediction ledger",
                 state="built" if ps.get("built") else "not_built", detail=(f"{ps['counts']['studies']} studies, {ps['counts']['expert_calls']} expert calls, "
                                                                           f"{ps['counts']['predictions']} predictions") if ps.get("built") else "press Rebuild",
                 separation_ok=ps.get("separation_ok"), validation="reproducible: same sources -> same digest"),
            dict(key="SHADOW", name=AR.NAMES["SHADOW"], implementation="governed discovery: discovery / confirmation patients, PERCIVAL confirmation, human approval",
                 state="awaiting_data" if not X else "available", detail=f"{len(_shadow_listing())} hypotheses registered",
                 validation="no discovery claimed without confirmation on separate patients")]
    for c in comps: c["status"] = _status_of(c)                                       # Stage 8: one validation-status vocabulary
    return dict(
        names=AR.NAMES,
        components=comps,
        flow=["MRI ingestion", "study registration + identity", "preprocessing", "ALBUS detection", "NOX quantitative analysis", "LUMOS visual analysis",
              "PERCIVAL integrated inference", "blinded expert review", "adjudication + eligible ground truth", "PENSIEVE history", "curated dataset",
              "training + evaluation", "model registry", "SHADOW discovery", "PERCIVAL confirmation", "human-approved component change"],
        registry={k: dict(active=v["active"]["version"], versions=v["versions"], signature_ok=v["active"].get("signature_ok")) for k, v in reg.items()},
        described=_describe_components(M, X, det, reg), readiness=readiness(), retired=_retired(), config=config_snapshot(), events=_events_summary())


# Stage 8: purpose / inputs / outputs / version / validation status of every component, read from this project
COMPONENT_INFO = dict(
    ALBUS=dict(purpose="find every candidate cSS focus on the SWI (mathematical detection: rules E1–E30, score_v4)",
               inputs="skull-stripped SWI, anatomy labels (T1 or SWI SynthSeg), optional FLAIR / phase", outputs="ranked candidate list + exclusions (review/ID_candidates.csv)"),
    NOX=dict(purpose="measure each candidate quantitatively (shape, darkness, position, continuity) for the learned decision",
             inputs="the candidate mask and the MRI", outputs="the approved NOX measurement set + uScore x1–x5 (per candidate)"),
    LUMOS=dict(purpose="read the candidate's surface-aligned MRI patch (visual intelligence)", inputs="3 patch maps (SWI minIP, mean, footprint)",
               outputs="image log-odds + test-time-augmentation spread (uncertainty)"),
    PERCIVAL=dict(purpose="combine ALBUS, NOX and LUMOS into one calibrated PERCIVAL score with reliability, disagreement and abstention",
                  inputs="component log-odds, missing indicators, reliability signals, pairwise disagreement", outputs="PERCIVAL score 0–100, band, status, reasons"),
    CORE=dict(purpose="fixed-weight comparison baseline", inputs="real NOX measurements of the candidate", outputs="comparison score (never the PERCIVAL prediction)"),
    PENSIEVE=dict(purpose="per-project memory of expert decisions, missed lesions and predictions (derived, rebuildable)",
                  inputs="reviewer journals, call ledger, missed-cSS marks, prediction ledger", outputs="history per candidate, attribution of errors to detector versions"),
    SHADOW=dict(purpose="test proposed improvements on discovery patients; PERCIVAL confirms on unseen patients; a person approves",
                inputs="eligible development labels + recorded measurements / patch statistics", outputs="hypotheses, discovery and confirmation records, approved component versions"))


def _status_of(c):
    s = c.get("state")
    return {"active": "active", "built": "active", "available": "experimental", "enabled_comparison": "experimental", "off": "unavailable",
            "trained_not_active": "experimental", "valid": "active", "untrained": "untrained", "not_built": "unavailable"}.get(s, "awaiting_data")


def _describe_components(M, X, det, reg):
    from uengine.percival import component_api as CI
    iface = CI.describe(M or X)
    out = {}
    for k, info in COMPONENT_INFO.items():
        v = dict(info)
        if k in ("ALBUS", "NOX", "LUMOS"):
            a = reg[k]["active"]; v.update(version=iface[k]["version"], registry_version=a["version"], signature_ok=a.get("signature_ok"), interface=iface[k]["interface"])
        elif k == "PERCIVAL": v.update(version=(M or X or {}).get("version"), model_hash=(M or X or {}).get("model_hash"))
        out[k] = v
    return out


def _retired():
    from uengine.legacy_guard import RETIRED
    return RETIRED


def _events_summary():
    try:
        from uengine import event_log as EV
        V = EV.verify(P()); return dict(events=V["events"], chain_ok=V["chain"]["ok"], registry_matches_events=V["registry_matches_events"])
    except Exception as e: return dict(error=type(e).__name__)


def _shadow_listing():
    from uengine import shadow_governed as SG
    try: return SG.listing(P())
    except Exception: return []


def candidate_contracts(sid):
    """one PERCIVAL candidate contract per scored candidate (AI predictions; no patient identifier)"""
    from uengine.percival import architecture as AR
    rec = _jl(P("scores", f"{sid}.json"), None)
    if not rec: return dict(ok=False, error="study not scored by PERCIVAL yet")
    M = load(rec["model"]) if rec.get("model") in versions() else None
    rows = {r["cand_id"]: r for r in gather(sid, labelled=False)}
    import pandas as pd
    cp = os.path.join(B(), "review", f"{sid}_candidates.csv"); fp = {}
    if os.path.exists(cp):
        for r in pd.read_csv(cp).itertuples(): fp[int(r.cand_id)] = {k: float(getattr(r, k)) for k in ("vox_i", "vox_j", "vox_k", "volume_mm3") if hasattr(r, k)}
    alb = AR.detector_version(B(), sid); out = []
    for c in rec.get("candidates") or []:
        row = dict(rows.get(c["cand_id"]) or {}, **fp.get(c["cand_id"], {})); row.pop("patient", None)
        out.append(AR.candidate_contract(sid, c, row, M, alb))
    return dict(ok=True, study=sid, model=rec.get("model"), contracts=out)


def components_report():
    from uengine.percival import architecture as AR
    return AR.component_report(_model_any())


def pensieve_index_state():
    from uengine import pensieve_index as PI
    return PI.summary(B())


def pensieve_index_rebuild():
    from uengine import pensieve_index as PI
    r = PI.rebuild(B(), patient_of=lambda c: (identity(c) or {}).get("patient"))
    log(f"PENSIEVE rebuilt: digest {r['digest']}, {r['counts']}" + (f", {len(r['errors'])} studies not readable" if r["errors"] else ""))
    return r


def pensieve_history(sid, cand_id):
    from uengine import pensieve_index as PI
    return PI.history(B(), sid, cand_id)


_EXT_CACHE = {}
def _extent_measures(sid):
    """{cand_id: measures} of the CURRENT candidate extent (uengine/imaging/refine.py), {} when not made yet or stale. Read only: the extent is
    made by the reviewer when a study is opened (or refine.run). These are SHADOW candidate variables - NOX uses them only after a SHADOW
    hypothesis is confirmed and approved (no silent change of the NOX feature set)."""
    from uengine.imaging import refine as RF
    try: rec = RF.current(B(), sid)
    except Exception: rec = None
    if not rec: return {}
    k = (sid, json.dumps(rec.get("inputs"), sort_keys=True))
    if k not in _EXT_CACHE: _EXT_CACHE[k] = {int(c): v for c, v in (rec.get("measures") or {}).items()}
    return _EXT_CACHE[k]


def _shadow_rows():
    """SHADOW's data: eligible expert labels of DEVELOPMENT patients from the latest dataset manifest + every recorded numeric measurement
    of the candidate (review/ID_candidates.csv). Locked-test patients are never included."""
    from uengine.percival import datasets as DS
    import pandas as pd, numpy as np
    L = DS.listing(P())
    if not L: return [], "no dataset yet - train PERCIVAL once (the dataset records the eligible labels)"
    man = DS.load(P(), L[-1]["id"]); rows = []; cache = {}
    for e in man["examples"]:
        # 2026-11-28 (audit S15): the dataset manifest has no 'status' key, so the old filter (status == "eligible") returned ZERO rows on
        # every real project. Eligibility is recorded per component: components.shadow (eligibility.py)
        if e.get("partition") != "development" or not (e.get("components") or {}).get("shadow") or e.get("status", "eligible") != "eligible" \
                or e.get("y") not in (0, 1) or str(e["cand_id"]).startswith("missed"): continue
        sid = e["study"]
        if sid not in cache:
            cp = os.path.join(B(), "review", f"{sid}_candidates.csv")
            cache[sid] = pd.read_csv(cp).set_index("cand_id") if os.path.exists(cp) else None
        t = cache[sid]
        if t is None or int(e["cand_id"]) not in t.index: continue
        r = t.loc[int(e["cand_id"])]
        feats = {k: (float(r[k]) if isinstance(r[k], (int, float, np.integer, np.floating)) and np.isfinite(r[k]) else None) for k in t.columns
                 if pd.api.types.is_numeric_dtype(t[k])}
        if "volume_mm3" in feats and feats["volume_mm3"]: feats["log_volume_mm3"] = float(np.log(max(feats["volume_mm3"], 1e-3)))
        ex_ = _extent_measures(sid).get(int(e["cand_id"]))                  # 2026-11-28: ALBUS outline refinement measures (when current)
        if ex_: feats.update({f"extent_{k}": (float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None) for k, v in ex_.items() if k != "leak_warning"})
        rows.append(dict(study=sid, cand_id=e["cand_id"], patient=e.get("patient"), partition="development", y=int(e["y"]), features=feats))
    bad = {b_["study"] for b_ in IDS().check_rows(rows)}                       # Stage 5: a stale manifest identity is never used by SHADOW
    rows = [r for r in rows if r["study"] not in bad and IDS().partition(r["patient"]) == "development"]
    # Stage 4: LUMOS pattern variables = statistics of the candidate's patch maps (per channel mean / SD / mean |gradient| along u and v)
    from uengine.percival.meta import patch_stats
    from uengine.percival.cnn import CHANNELS
    names = [f"patch_{c}_{st}" for st in ("mean", "sd", "grad_u", "grad_v") for c in ("minip", "mean", "footprint")]
    for sid in {r["study"] for r in rows}:
        mp = {g_["cand_id"]: g_.get("maps") for g_ in gather(sid, labelled=False)}
        for r in rows:
            if r["study"] == sid and mp.get(r["cand_id"]) is not None:
                v = patch_stats(np.asarray(mp[r["cand_id"]], np.float32))[0]; r["features"].update({n: float(x) for n, x in zip(names, v)})
    return rows, f"dataset {man['id']}"


def shadow_gov_state():
    from uengine import shadow_governed as SG
    from uengine.percival import component_registry as CR
    rows, src = _shadow_rows()
    cols = sorted({k for r in rows for k, v in r["features"].items() if v is not None})
    S = SG.split_of(P(), [r["patient"] for r in rows]) if rows else None
    return dict(hypotheses=SG.listing(P()), source=src, n_examples=len(rows), measurements=cols,
                split=None if not S else dict(discovery=sum(1 for v in S["assignment"].values() if v == "discovery"),
                                              confirmation=sum(1 for v in S["assignment"].values() if v == "confirmation")),
                nox=CR.active(P(), "NOX"), registry=CR.overview(P()), implemented=list(SG.IMPLEMENTED), kinds=list(SG.KINDS),
                legacy_note="The older Shadow Lab trials run on a random SYNTHETIC cohort and are demonstrations only - never evidence.")


def shadow_gov_post(op, d):
    from uengine import shadow_governed as SG
    from uengine.percival import component_registry as CR
    try:
        if op == "register":
            kind = d.get("kind", "nox_measurement")
            return dict(ok=True, hypothesis=SG.register(P(), d.get("target") or SG.TARGET.get(kind, "NOX"), kind, d.get("variables") or [],
                                                         d.get("rationale", ""), created_by="SHADOW (proposed by " + str(d.get("by") or "user") + ")",
                                                         params=d.get("params")))
        rows, _ = _shadow_rows()
        base = (CR.active(P(), "NOX").get("config") or {}).get("feature_set") or CR.BASELINES["NOX"]["feature_set"]
        if op == "suggest":                                                 # Stage 3: stability selection -> registered hypotheses only
            cols = sorted({k for r in rows for k, v in r["features"].items() if v is not None and not k.startswith("patch_")})
            return SG.suggest_nox(P(), rows, base, cols)
        if op == "discovery": return dict(ok=True, hypothesis=SG.run_discovery(P(), d["id"], rows, base))
        if op == "confirm": return dict(ok=True, hypothesis=SG.confirm(P(), d["id"], rows, actor="PERCIVAL"))
        if op == "approve":
            H, V = SG.approve(P(), d["id"], d.get("by", ""), d.get("reason", ""), d.get("confirm", ""), override=bool(d.get("override")))
            return dict(ok=True, hypothesis=H, version=V)
        if op == "rollback":
            return dict(ok=True, active=CR.rollback(P(), d.get("component", "NOX"), d.get("by", ""), d.get("reason", ""), d.get("confirm", "")))
        return dict(ok=False, error=f"unknown op {op}")
    except (SG.ShadowError, CR.RegistryError, KeyError) as e: return dict(ok=False, error=str(e))


def albus_state():
    from uengine import albus_detection as AD
    from uengine.percival import component_registry as CR
    codes = [s["code"] for s in selection() if os.path.exists(os.path.join(B(), "review", f"{s['code']}_candidates.csv"))]
    ev = AD.evaluate(B(), codes)
    for v in ev.values(): v.pop("per_study", None)
    return dict(evaluation=ev, registry=CR.overview(P())["ALBUS"],
                note="Sensitivity counts only lesions experts found (detected + expert-marked missed); an approved detector version is recorded, "
                     "never applied automatically.")


# ------------------------------------------------------------------ Stage 3: analyses, study-level model, second-review priority
def analysis_state():
    """the small-data honesty records of the active (else latest) model: missing data, learning curve, subgroup calibration, abstention,
    reproducibility hash, feature list, component configuration and interface. Development cohort only (the locked test is separate)."""
    M = _model_any()
    if not M: return dict(available=False, reason="no PERCIVAL model has been trained in this project yet")
    keys = ("missing_data", "learning_curve", "subgroup_calibration", "abstention", "model_hash", "model_hash_basis", "features", "component_config",
            "component_interface", "reproducibility")
    return dict(available=True, version=M.get("version"), **{k: M.get(k) for k in keys},
                note="trained before Stage 3: no analyses recorded" if not M.get("model_hash") else "development cohort analyses; not a validation")


def _expert_grades():
    """expert patient-level grades: <project>/labels/expert_grades.csv (columns study, total 0-4) - entered by the experts, never derived"""
    import csv
    p = os.path.join(B(), "labels", "expert_grades.csv"); out = {}
    if not os.path.exists(p): return out
    with open(p) as f:
        for r in csv.DictReader(f):
            try: out[str(r["study"]).strip()] = int(float(r["total"]))
            except (KeyError, TypeError, ValueError): pass
    return out


def study_level_state():
    """explicit study-level model: candidates with PERCIVAL score >= 50 -> score_css.py (the reader's own 0-4 method) -> multifocality;
    validated against expert patient grades (quadratic weighted kappa, exact agreement, Bland-Altman). Withheld studies are not counted."""
    from uengine.percival import analysis as AN
    pred = {}
    for f in sorted(glob.glob(P("scores", "*.json"))):
        sid = os.path.basename(f)[:-5]
        if not may_read(sid): continue
        t = ((_jl(f, {}) or {}).get("study_score") or {}).get("total")
        if t is not None: pred[sid] = int(t)
    E = _expert_grades()
    return dict(mapping="candidates with PERCIVAL score >= 50 are accepted; score_css.py computes the 0-4 multifocality from them (unassessable "
                        "studies, with no valid candidate score, are never counted as 0)",
                n_scored=len(pred), n_expert=len(E), agreement=AN.study_agreement(pred, E),
                expert_source="labels/expert_grades.csv (study, total) - expert-entered patient grades")


def second_review(sid):
    """Stage 3 active learning: second-review priority for ONE study whose blind read is complete (the route is blind-gated) - uncertain and
    disagreeing candidates first. Never used to order or select the blind first read."""
    from uengine.percival import analysis as AN
    rec = _jl(P("scores", f"{sid}.json"), {}) or {}
    if not rec.get("candidates"): return dict(ok=False, error="no PERCIVAL scores for this study")
    return dict(ok=True, study=sid, model=rec.get("model"), queue=AN.prioritise(rec["candidates"]),
                note="second-review priority only (after the blind first read); never applied to the blind first read")


# ------------------------------------------------------------------ Stage 6: validation governance
PLAN_CONFIRM = "REGISTER EVALUATION PLAN"
PLAN_TEMPLATE = dict(
    schema="percival-evaluation-plan/1.0",
    test_size=dict(min_test_patients_per_class=5, target_test_patients_per_class=None, note="pre-register the locked-test size BEFORE looking at it"),
    primary_metric="candidate-level AUC of the PERCIVAL score on the locked test cohort (patient bootstrap 95 % CI)",
    secondary_metrics=["sensitivity at the red threshold", "specificity at the green threshold", "calibration slope / intercept", "Brier score",
                       "study-level quadratic weighted kappa vs expert 0-4 grades", "missed-lesion recall (ALBUS)"],
    acceptance=dict(auc_not_below_math=True, auc_not_below_active_minus=0.01, brier_not_above_active_plus=0.01, calibration_slope=[0.6, 1.6]),
    reference="inter-reader agreement baseline (Cohen kappa, PENSIEVE) on the same cases",
    external_validation=dict(planned=None, kind="temporal or multi-site cohort, separate from this project's locked test", note="required before any claim of generalisation"),
    milestones=[])


def evaluation_plan():
    return _jl(P("evaluation_plan.json"), None)


def evaluation_plan_save(plan, by, reason, confirm):
    """pre-register (or amend - a new version, the old one kept) the evaluation plan: named person, typed phrase, reason"""
    from uengine.percival import component_registry as CR
    if confirm != PLAN_CONFIRM: return dict(ok=False, error=f"type exactly '{PLAN_CONFIRM}'")
    if str(by or "").strip().lower() in CR.AUTOMATED or not str(reason or "").strip(): return dict(ok=False, error="a named person and a reason are required")
    cur = evaluation_plan(); P_ = dict(PLAN_TEMPLATE, **{k: v for k, v in (plan or {}).items() if k in PLAN_TEMPLATE and k != "milestones"})
    P_["milestones"] = (cur or {}).get("milestones", []); P_["version"] = ((cur or {}).get("version") or 0) + 1
    P_.update(registered_by=str(by).strip(), reason=str(reason).strip(), at=time.strftime("%Y-%m-%d %H:%M:%S"))
    if int((P_["test_size"] or {}).get("min_test_patients_per_class") or 0) < 5: return dict(ok=False, error="the test size cannot be below 5 patients per class")
    if cur: _js(P("evaluation_plan_history", f"v{cur.get('version', 0):03d}.json"), cur)
    _js(P("evaluation_plan.json"), P_); _event("config_changed", by, evaluation_plan=P_["version"]); return dict(ok=True, plan=P_)


def milestone_declare(name, by, reason, confirm, fresh_test_cohort=False):
    """declare the next evaluation milestone (each milestone may consult the locked test cohort ONCE for acceptance)"""
    from uengine.percival import component_registry as CR
    Pl = evaluation_plan()
    if not Pl: return dict(ok=False, error="register the evaluation plan first")
    if confirm != PLAN_CONFIRM or str(by or "").strip().lower() in CR.AUTOMATED or not str(reason or "").strip():
        return dict(ok=False, error=f"a named person, a reason and the typed phrase '{PLAN_CONFIRM}' are required")
    m = dict(id=f"M{len(Pl['milestones']) + 1}", name=str(name or "").strip() or f"milestone {len(Pl['milestones']) + 1}", by=str(by).strip(),
             reason=str(reason).strip(), at=time.strftime("%Y-%m-%d %H:%M:%S"), fresh_test_cohort=bool(fresh_test_cohort))
    Pl["milestones"].append(m); _js(P("evaluation_plan.json"), Pl); _event("config_changed", by, milestone=m["id"]); return dict(ok=True, milestone=m)


def test_consultations():
    p = P("split", "test_consultations.jsonl")
    if not os.path.exists(p): return []
    with open(p) as f: return [json.loads(x) for x in f if x.strip()]


def test_reuse_gate(M, acc, test_patients):
    """Stage 6: the locked test cohort supports ACCEPTANCE once per pre-registered milestone. Every consultation is recorded; a model
    evaluated on a test set already used for acceptance at the current milestone stays experimental (the result is still reported)."""
    acc = dict(acc, reasons=list(acc.get("reasons") or []))
    if not test_patients or not (M.get("test") or {}).get("n"): return acc
    dig = hashlib.sha256(json.dumps(test_patients).encode()).hexdigest()[:16]; Pl = evaluation_plan()
    ms = (Pl or {}).get("milestones") or []; cur = ms[-1]["id"] if ms else None
    # 2026-11-28 (audit S5): EVERY consultation uses the milestone - pass or fail. Before, a failing model left the milestone unused, so the
    # same test patients could be looked at again and again (and code changed in between) before one model passed.
    used = [c for c in test_consultations() if c.get("milestone") == cur and c.get("test_digest") == dig]
    if not Pl: acc["reasons"].append("no pre-registered evaluation plan: the locked test result is reported but cannot support acceptance")
    elif not cur: acc["reasons"].append("no evaluation milestone declared: declare one before the locked test cohort can support acceptance")
    elif used: acc["reasons"].append(f"the locked test cohort was already consulted at milestone {cur} (model {used[0]['version']}): every "
                                     "consultation uses the milestone, whether the model passed or not - declare the next milestone (with what "
                                     "changed) or open the fresh test cohort; test-set reuse is refused")
    use = bool(Pl and cur and not used and not acc["reasons"])
    rec = dict(version=M.get("version"), at=time.strftime("%Y-%m-%d %H:%M:%S"), milestone=cur, test_digest=dig, n_patients=len(test_patients),
               used_for_acceptance=use, consumed=True, rule="every consultation uses the milestone (2026-11-28)",
               auc=((M.get("test") or {}).get("percival") or {}).get("auc"))
    os.makedirs(P("split"), exist_ok=True)
    with open(P("split", "test_consultations.jsonl"), "a") as f: f.write(json.dumps(rec, default=str) + "\n")
    acc["passed"] = not acc["reasons"]; acc["test_consultation"] = rec
    acc["criteria"] = (acc.get("criteria") or "") + " Stage 6: the locked test cohort supports acceptance once per pre-registered milestone."
    return acc


def reader_agreement():
    from uengine import pensieve_index as PI
    return PI.reader_agreement(B())


def drift_state():
    """Stage 6: calibration / drift monitoring by scanner, field strength and sequence: per subgroup the scored studies, the share of
    candidates out of the training distribution and the mean PERCIVAL score; subgroups the active model never saw are flagged."""
    M = active() or {}; seen = {}
    for k, lv in ((M.get("subgroup_calibration") or {}).get("subgroups") or {}).items(): seen[k] = set(lv)
    agg = {}; flagged = []
    for f in sorted(glob.glob(P("scores", "*.json"))):
        sid = os.path.basename(f)[:-5]
        if not may_read(sid): continue
        rec = _jl(f, {}) or {}; C = rec.get("candidates") or []
        rows = list((_cached_rows(sid) or {}).values())
        sub = ((rows or [{}])[0] or {}).get("subgroups") or {}
        ood = sum(1 for c in C if any("out-of-distribution" in r_ for r_ in (c.get("reasons") or []))); n = len(C)
        for k in ("field_strength", "sequence", "anatomy"):
            lv = str(sub.get(k) or "unknown"); a = agg.setdefault(k, {}).setdefault(lv, dict(studies=0, candidates=0, ood=0, score_sum=0.0, scored=0))
            a["studies"] += 1; a["candidates"] += n; a["ood"] += ood
            for c in C:
                if c.get("percival_score") is not None: a["score_sum"] += c["percival_score"]; a["scored"] += 1
            if seen.get(k) and lv not in seen[k]: flagged.append(dict(study=sid, reason=f"{k} '{lv}' was not in the training data"))
        if n and ood / n > 0.5: flagged.append(dict(study=sid, reason=f"{ood} of {n} candidates out of the training distribution"))
    for k, lv in agg.items():
        for v in lv.values(): v["ood_fraction"] = round(v["ood"] / v["candidates"], 3) if v["candidates"] else None; v["mean_score"] = round(v["score_sum"] / v["scored"], 1) if v["scored"] else None
    return dict(by_subgroup=agg, flagged=flagged, model=M.get("version"),
                note="monitoring only: a flagged study is reviewed by an expert; no recalibration is applied automatically")
