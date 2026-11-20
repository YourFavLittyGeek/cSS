"""image_ml_gui.py - back end of the app's "Image ML" screen (Stage 2 prototype). SYNTHETIC DATA ONLY; experimental; research only.

Design rules (same as shadow_engine_gui.py)
  - The image engine (unified_engine/run_imaging.py) runs in a SUBPROCESS with a time limit; this module never imports it. A crash, hang
    or bad model cannot stop the app or touch any existing output.
  - The screen works only on a base carrying the synthetic marker (unified_engine/SYNTHETIC_BASE). On any other base it lists nothing and
    reads nothing: no image, table or file name of a real project is opened by this module.
  - Results are read only from $CSS_BASE/unified_engine/image_ml/ID.json. The deterministic MATH and Characteristic ML panels are read
    from the detector table and the Stage 1 shadow result when they exist; the three streams are returned in SEPARATE blocks.
  - Every response carries synthetic_only=True and experimental=True."""
import csv, json, os, subprocess, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
B = os.environ.get("CSS_BASE", os.path.expanduser("~/css_project"))
CLI = os.path.join(ROOT, "unified_engine", "run_imaging.py")
OUT = os.path.join(B, "unified_engine", "image_ml")
MARKER = os.path.join(B, "unified_engine", "SYNTHETIC_BASE")
TIMEOUT_S = int(os.environ.get("CSS_IMAGE_ENGINE_TIMEOUT_S", "300"))
JOBS = {}; LOCK = threading.Lock(); _MC = dict(t=0, v=None)
MATH_COLS = ("score_v4", "review_tier", "css_evidence", "vein_evidence", "rule_version")
WARNING = ("experimental research prototype. The image model was trained on invented phantom images; its outputs "
           "are not clinical results, not validated and must not be used for any decision.")


def synthetic_base(): return os.path.exists(MARKER)


def _hdr(**kw): return dict(synthetic_only=True, experimental=True, warning=WARNING, **kw)


def _ok_code(code): return isinstance(code, str) and code.startswith("SYN") and code.isalnum() and len(code) <= 16


def studies():
    if not synthetic_base(): return []
    d = os.path.join(B, "review"); out = []
    if not os.path.isdir(d): return []
    for f in sorted(os.listdir(d)):
        if f.endswith("_candidates.csv") and f.startswith("SYN"):
            sid = f[:-len("_candidates.csv")]
            if _ok_code(sid) and os.path.exists(os.path.join(B, "data", f"{sid}_swi.nii")): out.append(sid)
    return out


def models(force=False):
    if not force and time.time() - _MC["t"] < 30 and _MC["v"] is not None: return _MC["v"]
    try:
        r = subprocess.run([sys.executable, CLI, "models", "--base", B], capture_output=True, text=True, timeout=60, env=dict(os.environ, CSS_BASE=B))
        v = dict(ok=r.returncode == 0, models=json.loads(r.stdout) if r.returncode == 0 else [], error="" if r.returncode == 0 else r.stderr[-400:])
    except Exception as e: v = dict(ok=False, models=[], error=f"{type(e).__name__}: {e}")
    _MC.update(t=time.time(), v=v); return v


def job(code):
    with LOCK: return dict(JOBS.get(code) or dict(status="idle"))


def run(code):
    if not synthetic_base(): return _hdr(ok=False, error="Image ML runs on a SYNTHETIC base only (no synthetic marker in this project)")
    if code not in studies(): return _hdr(ok=False, error=f"unknown synthetic study {code!r}")
    with LOCK:
        if JOBS.get(code, {}).get("status") == "running": return _hdr(ok=False, error="already running")
        JOBS[code] = dict(status="running", started=time.time())

    def go():
        try:
            r = subprocess.run([sys.executable, CLI, "infer", code, "--base", B, "--write"], capture_output=True, text=True, timeout=TIMEOUT_S,
                               env=dict(os.environ, CSS_BASE=B))
            ok = r.returncode == 0; err = "" if ok else (r.stderr or r.stdout or f"exit {r.returncode}").strip()[-600:]
        except subprocess.TimeoutExpired: ok, err = False, f"image engine timed out after {TIMEOUT_S} s"
        except Exception as e: ok, err = False, f"image engine could not start: {type(e).__name__}: {e}"
        with LOCK: JOBS[code] = dict(status="completed" if ok else "failed", finished=time.time(), error=err)
    threading.Thread(target=go, daemon=True).start()
    return _hdr(ok=True, started=code)


def _rows(code):
    rows = []
    for lst, idc in (("candidates", "cand_id"), ("excluded", "excl_id")):
        p = os.path.join(B, "review", f"{code}_{lst}.csv")
        if not os.path.exists(p): continue
        with open(p, newline="") as f:
            for r in csv.DictReader(f):
                rows.append(dict(ref=f"{'c' if lst == 'candidates' else 'x'}{r.get(idc)}", list=lst, obj_id=r.get(idc),
                                 vox_ijk=[r.get("vox_i"), r.get("vox_j"), r.get("vox_k")], volume_mm3=r.get("volume_mm3"),
                                 math={k: r.get(k) for k in MATH_COLS if r.get(k) not in (None, "")}))
    return rows


def _characteristics(code):
    p = os.path.join(B, "unified_engine", "shadow", f"{code}.json")
    if not os.path.exists(p): return dict(available=False, reason="no Stage 1 shadow result for this study (Characteristic ML not run)")
    try:
        with open(p) as f: d = json.load(f)
    except Exception as e: return dict(available=False, reason=f"shadow result unreadable: {type(e).__name__}")
    rows = {}
    for c in d.get("candidates", []):
        ml = c.get("ml") or {}; rows[c.get("ref")] = {k: v for k, v in ml.items() if not isinstance(v, (dict, list))}
    return dict(available=True, model=(d.get("model") or {}).get("name"), rows=rows)


def result(code):
    if not synthetic_base(): return _hdr(available=False, error="not a synthetic base")
    if not _ok_code(code) or code not in studies(): return _hdr(available=False, error=f"unknown synthetic study {code!r}")
    j = job(code); det = _rows(code)
    has = any(r["math"].get("score_v4") not in (None, "") for r in det)          # MATH = the detector's score, not just its version tag
    math = dict(available=has, reason="" if has else
                "this synthetic image study has no detector measurements (score_v4 etc.): deterministic MATH not available",
                rows={r["ref"]: r["math"] for r in det})
    base = _hdr(study=code, job=j, math=math, characteristics=_characteristics(code), detector_rows=det)
    p = os.path.join(OUT, f"{code}.json")
    if os.path.exists(p):
        try:
            with open(p) as f: d = json.load(f)
            return dict(base, available=True, image_ml=d, stale_job_error=j.get("error", "") if j.get("status") == "failed" else "")
        except Exception as e: return dict(base, available=False, error=f"result unreadable: {type(e).__name__}: {e}")
    return dict(base, available=False, error=j.get("error", "") or "no Image ML result yet - press Run inference")


def state():
    m = models(); act = next((x for x in m.get("models", []) if x.get("status") == "ok"), None); st = []
    for sid in studies():
        s = dict(code=sid, job=job(sid).get("status")); p = os.path.join(OUT, f"{sid}.json")
        if os.path.exists(p):
            try:
                with open(p) as f: d = json.load(f)
                s.update(created=d.get("created"), applied=(d.get("model") or {}).get("applied"), counts=d.get("category_counts"),
                         unchanged=d.get("original_inputs_unchanged"))
            except Exception: s["read_error"] = True
        st.append(s)
    return _hdr(synthetic_base=synthetic_base(), engine_installed=os.path.exists(CLI), models=m.get("models", []), models_error=m.get("error", ""),
                active_model=act, studies=st)
