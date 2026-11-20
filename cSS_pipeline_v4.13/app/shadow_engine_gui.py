"""shadow_engine_gui.py - back end of the app's "Shadow ML" screen (Unified Score engine, SHADOW MODE). EXPERIMENTAL, research only.

Design rules
  - The engine (unified_engine/run_engine.py) always runs in a SUBPROCESS with a time limit: a crash, a hang or a bad model can never
    stop the app, change a patient's status or touch the existing outputs. This module never imports the engine.
  - Outputs are read only from $CSS_BASE/unified_engine/shadow/ID.json (written by the engine). Nothing else is written here except
    the job table in memory.
  - When the engine cannot run (missing, crash, timeout) the screen shows the EXISTING deterministic values read directly from
    review/ID_candidates.csv / ID_excluded.csv with the csv module (no engine logic): the deterministic fallback.
  - Every response carries shadow_mode=True and experimental=True."""
import csv, json, os, subprocess, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
B = os.environ.get("CSS_BASE", os.path.expanduser("~/css_project"))
CLI = os.path.join(ROOT, "unified_engine", "run_engine.py") if os.path.exists(os.path.join(ROOT, "unified_engine", "run_engine.py")) \
    else os.path.join(B, "unified_engine", "run_engine.py")
OUT = os.path.join(B, "unified_engine", "shadow")
TIMEOUT_S = int(os.environ.get("CSS_ENGINE_TIMEOUT_S", "180"))
JOBS = {}; LOCK = threading.Lock(); _MCACHE = dict(t=0, v=None)
DET_COLS = ("hemi", "region", "score_v4", "css_evidence", "vein_evidence", "rule_version", "review_tier", "review_priority_rank")


def _run(args, timeout):
    if not os.path.exists(CLI): return dict(ok=False, error=f"engine not installed ({CLI})")
    try:
        r = subprocess.run([sys.executable, CLI] + args, capture_output=True, text=True, timeout=timeout, env=dict(os.environ, CSS_BASE=B))
    except subprocess.TimeoutExpired: return dict(ok=False, error=f"engine timed out after {timeout} s")
    except Exception as e: return dict(ok=False, error=f"engine could not start: {type(e).__name__}: {e}")
    if r.returncode != 0: return dict(ok=False, error=(r.stderr or r.stdout or f"exit {r.returncode}").strip()[-600:], rc=r.returncode)
    try: return dict(ok=True, **json.loads(r.stdout.strip().splitlines()[-1]))
    except Exception: return dict(ok=True, raw=r.stdout[-600:])


def models(force=False):
    if not force and time.time() - _MCACHE["t"] < 30 and _MCACHE["v"] is not None: return _MCACHE["v"]
    if not os.path.exists(CLI): v = dict(ok=False, error="engine not installed", models=[])
    else:
        try:
            r = subprocess.run([sys.executable, CLI, "models", "--base", B], capture_output=True, text=True, timeout=60, env=dict(os.environ, CSS_BASE=B))
            v = dict(ok=r.returncode == 0, models=json.loads(r.stdout) if r.returncode == 0 else [], error="" if r.returncode == 0 else r.stderr[-400:])
        except Exception as e: v = dict(ok=False, models=[], error=f"{type(e).__name__}: {e}")
    _MCACHE.update(t=time.time(), v=v); return v


def job(code):
    with LOCK: return dict(JOBS.get(code) or dict(status="idle"))


def run(code):
    """background shadow run for one study; returns at once"""
    with LOCK:
        if JOBS.get(code, {}).get("status") == "running": return dict(ok=False, error="already running")
        JOBS[code] = dict(status="running", started=time.time())
    def go():
        r = _run(["shadow", code, "--base", B], TIMEOUT_S)
        with LOCK: JOBS[code] = dict(status="completed" if r.get("ok") else "failed", finished=time.time(), result=r, error=r.get("error", ""))
    threading.Thread(target=go, daemon=True).start()
    return dict(ok=True, shadow_mode=True)


def after_done(code, settings):
    """called by the app after a patient is finished and its original results are saved - only if the user switched it on"""
    if (settings.get("features") or {}).get("shadow_engine"): run(code)


def deterministic_only(code):
    """the existing output exactly as the detector wrote it (csv module; no engine)"""
    rows = []
    for lst, idc in (("candidates", "cand_id"), ("excluded", "excl_id")):
        p = os.path.join(B, "review", f"{code}_{lst}.csv")
        if not os.path.exists(p): continue
        with open(p, newline="") as f:
            for r in csv.DictReader(f):
                rows.append(dict(ref=f"{'c' if lst == 'candidates' else 'x'}{r.get(idc)}", list="shown" if lst == "candidates" else "excluded",
                                 **{k: r.get(k) for k in DET_COLS}))
    return rows


def result(code):
    p = os.path.join(OUT, f"{code}.json"); j = job(code)
    base = dict(study=code, shadow_mode=True, experimental=True, job=j)
    if os.path.exists(p):
        try:
            with open(p) as f: d = json.load(f)
            return dict(base, available=True, **d, stale_job_error=j.get("error", "") if j.get("status") == "failed" else "")
        except Exception as e: base["read_error"] = f"{type(e).__name__}: {e}"
    return dict(base, available=False, fallback="deterministic", deterministic_rows=deterministic_only(code),
                error=j.get("error", "") or base.get("read_error", "") or "no shadow result yet")


def state(pats, settings):
    m = models()
    act = next((x for x in m.get("models", []) if x.get("status") == "ok"), None)
    st = []
    for p in pats:
        f = os.path.join(OUT, f"{p['code']}.json"); s = dict(code=p["code"], status=p.get("status"), shadow=job(p["code"]).get("status"))
        if os.path.exists(f):
            try:
                with open(f) as fh: d = json.load(fh)
                s.update(created=d.get("created"), ml_applied=d.get("ml_applied"), counts=d.get("category_counts"), synthetic=d.get("synthetic"),
                         model=(d.get("model") or {}).get("name"), unchanged=d.get("original_outputs_unchanged"))
            except Exception: s["read_error"] = True
        st.append(s)
    return dict(shadow_mode=True, experimental=True, enabled=bool((settings.get("features") or {}).get("shadow_engine")), engine_installed=os.path.exists(CLI),
                models=m.get("models", []), models_error=m.get("error", ""), active_model=act, synthetic_base=os.path.exists(os.path.join(B, "unified_engine", "SYNTHETIC_BASE")),
                studies=st)
