"""check_app_shadow_engine.py - end-to-end test of the Unified Score engine in SHADOW MODE through the app's own HTTP API and a headless
browser. SYNTHETIC base only (written by unified_engine/run_engine.py demo-base into a temporary folder); the app runs with the write
guard (CSS_EXPERIMENTAL=1) and the real project folders listed as protected.
Checks: GUI contains the Shadow ML screen; shadow mode default OFF; POST needs the app header; shadow run for a study; existing outputs
byte-identical (whole review/ and app_data/patients.json); deterministic values equal the detector's lists; trace / model version present;
non-synthetic study -> ML withheld; engine crash -> deterministic fallback while the app keeps serving; corrupt configured model ->
fallback with reason; enable switch persists; restart; clean shutdown; headless-browser DOM shows the shadow banner and the three outputs.
usage: python tests/check_app_shadow_engine.py [--shots DIR]   (exit 1 on any FAIL)"""
import glob, hashlib, json, os, shutil, socket, subprocess, sys, tempfile, time, urllib.error, urllib.request
H = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(H); PY = sys.executable
FAILS = []
def check(n, ok, info=""):
    print(f"{'PASS' if ok else 'FAIL'}  {n}  {info}"); (None if ok else FAILS.append(n))

SHOTS = sys.argv[sys.argv.index("--shots") + 1] if "--shots" in sys.argv else None
REAL = [os.path.expanduser("~/css_project"), os.path.expanduser("~/cSS_experimental")]
T = tempfile.mkdtemp(prefix="shadow_app_"); HOME = os.path.join(T, "home"); B = os.path.join(HOME, "syn_base"); os.makedirs(HOME)
r = subprocess.run([PY, os.path.join(ROOT, "unified_engine", "run_engine.py"), "demo-base", B, "--n", "6"], capture_output=True, text=True)
check("synthetic demo base written", r.returncode == 0, r.stderr[-300:])
def tree(d, sub=("review",), extra=()):
    out = {}
    for s in sub:
        for f in glob.glob(os.path.join(d, s, "**", "*"), recursive=True):
            if os.path.isfile(f):
                with open(f, "rb") as fh: out[os.path.relpath(f, d)] = hashlib.sha256(fh.read()).hexdigest()
    for e in extra:
        p = os.path.join(d, e)
        if os.path.exists(p):
            with open(p, "rb") as fh: out[e] = hashlib.sha256(fh.read()).hexdigest()
    return out
def diff(a, b):
    return dict(added=sorted(set(b) - set(a)), removed=sorted(set(a) - set(b)), changed=sorted(k for k in set(a) & set(b) if a[k] != b[k]))
def real_mtimes():
    return {d: max((os.path.getmtime(f) for f in glob.glob(os.path.join(d, "review", "*"))), default=0) for d in REAL if os.path.isdir(d)}

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
def start(extra=None):
    port = free_port()
    env = dict(os.environ, HOME=HOME, CSS_BASE=B, CSS_EXPERIMENTAL="1", PYTHONPATH=os.path.join(ROOT, "app", "guard"),
               CSS_PROTECTED_PATHS=":".join(REAL + [os.path.expanduser("~/Projects/cSS")]), CSS_ENGINE_TIMEOUT_S="120", **(extra or {}))
    p = subprocess.Popen([PY, os.path.join(ROOT, "app", "css_app.py"), "--port", str(port), "--no-window"], env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    U = f"http://127.0.0.1:{port}"
    for _ in range(80):
        try: urllib.request.urlopen(U + "/api/state", timeout=2); return p, U
        except Exception: time.sleep(0.25)
    return p, U
def get(U, path): return json.load(urllib.request.urlopen(U + path, timeout=60))
def post(U, path, d, header=True):
    rq = urllib.request.Request(U + path, data=json.dumps(d).encode(), headers={"Content-Type": "application/json", **({"X-CSS-App": "1"} if header else {})})
    try: return json.load(urllib.request.urlopen(rq, timeout=60))
    except urllib.error.HTTPError as e: return dict(http=e.code)
def wait(U, code, limit=180):
    t0 = time.time()
    while time.time() - t0 < limit:
        r = get(U, f"/api/se/result?study={code}")
        if r["job"].get("status") in ("completed", "failed"): return r
        time.sleep(0.5)
    return dict(timeout=True)
def stop(p):
    p.terminate()
    try: p.wait(10); return True
    except subprocess.TimeoutExpired: p.kill(); return False

before = tree(B); real0 = real_mtimes()
with open(os.path.join(B, "app_data", "patients.json")) as _f: PJ0 = {x["code"]: x for x in json.load(_f)}
def pj_fields():
    with open(os.path.join(B, "app_data", "patients.json")) as f: now = {x["code"]: x for x in json.load(f)}
    return {c: {k: (str(PJ0[c].get(k))[:30], str(now[c].get(k))[:30]) for k in set(PJ0[c]) | set(now.get(c, {})) if PJ0[c].get(k) != now.get(c, {}).get(k)} for c in PJ0 if c in now}

app, U = start()
try:
    check("app starts on the synthetic base", app.poll() is None)
    html = urllib.request.urlopen(U + "/", timeout=10).read().decode()
    js = urllib.request.urlopen(U + "/shadow_view.js", timeout=10).read().decode()
    check("GUI has the Shadow ML screen", 'data-v="shadow"' in html and "/shadow_view.js" in html and "SHADOW MODE" in js)
    st = get(U, "/api/se/state")
    check("shadow state: shadow_mode, experimental, synthetic base", st.get("shadow_mode") is True and st.get("experimental") is True and st.get("synthetic_base") is True)
    check("shadow run after each study is OFF by default", st.get("enabled") is False)
    check("active model = bundled synthetic demo model, healthy", (st.get("active_model") or {}).get("name") == "synthetic_demo_offset" and st["active_model"]["status"] == "ok")
    check("existing unified-score switch untouched (still OFF)", get(U, "/api/u/state").get("enabled") is False)
    check("POST without the app header is refused", post(U, "/api/se/run", dict(code="SYN01"), header=False).get("http") == 403)
    check("run refused for an unknown / unfinished study", post(U, "/api/se/run", dict(code="NOPE")).get("ok") is False)
    check("shadow run starts", post(U, "/api/se/run", dict(code="SYN01")).get("ok") is True)
    r1 = wait(U, "SYN01")
    check("shadow run completes", r1.get("job", {}).get("status") == "completed", str(r1.get("job", {}).get("error", ""))[:200])
    check("result: ML applied on the synthetic study, shadow + experimental stamped", r1.get("ml_applied") is True and r1.get("shadow_mode") and r1.get("experimental"))
    check("result: existing outputs verified unchanged by the engine", r1.get("original_outputs_unchanged") is True)
    c = r1.get("candidates", [])
    check("every candidate keeps deterministic / characteristics / ML / unified blocks", c and all({"deterministic", "characteristics", "ml", "unified"} <= set(x) for x in c))
    check("every prediction carries model hash, version and formula", all(x.get("trace", {}).get("model_hash") == r1["model"]["model_hash"] and x["trace"].get("calculation") for x in c))
    import csv
    with open(os.path.join(B, "review", "SYN01_candidates.csv"), newline="") as f: rows = list(csv.DictReader(f))
    det = {x["ref"]: x["deterministic"]["score_v4"] for x in c if x["list"] == "shown"}
    check("deterministic score_v4 identical to the detector list (regression)", all(abs(det[f"c{w['cand_id']}"] - float(w["score_v4"])) < 1e-12 for w in rows), f"{len(rows)} rows")
    check("uncertainty interval reported where ML applied", all(x["unified"]["p_lo"] is not None for x in c if x["unified"]["category"] != "not_scorable"))
    for code in ("SYN02", "SYN03"): post(U, "/api/se/run", dict(code=code))
    for code in ("SYN02", "SYN03"): wait(U, code)
    d1 = diff(before, tree(B)); check("review/ byte-identical after shadow runs", not any(d1.values()), str(d1))
    # patients.json: compared by CONTENT - the unchanged app re-serialises it (indentation) at start-up even with no shadow
    # action (control runs, docs/unified_engine/TEST_REPORT.md); every field of every study record must stay identical
    check("study records in patients.json unchanged (every field)", not any(pj_fields().values()), str({k: v for k, v in pj_fields().items() if v}))
    # non-synthetic study code on the same base -> ML must be withheld
    for k in ("candidates.csv", "excluded.csv", "qc.json", "score.json"):
        src = os.path.join(B, "review", f"SYN04_{k}")
        if os.path.exists(src): shutil.copy(src, os.path.join(B, "review", f"TST01_{k}"))
    with open(os.path.join(B, "app_data", "patients.json")) as f: P = json.load(f)
    P.append(dict(P[0], code="TST01"))
    with open(os.path.join(B, "app_data", "patients.json"), "w") as f: json.dump(P, f)
finally:
    ok_stop = stop(app)
check("clean shutdown", ok_stop)
before2 = tree(B)
app, U = start()
try:
    check("restart works", app.poll() is None and get(U, "/api/se/state").get("shadow_mode") is True)
    check("earlier shadow results survive a restart", get(U, "/api/se/result?study=SYN01").get("available") is True)
    post(U, "/api/se/run", dict(code="TST01")); r = wait(U, "TST01")
    check("non-synthetic study: ML withheld, deterministic fallback", r.get("ml_applied") is False and "never applied to a real study" in r.get("ml_status", "")
          and all(x["unified"]["source"] == "deterministic_fallback" for x in r.get("candidates", [])))
    e = post(U, "/api/se/enable", dict(on=True)); check("enable switch", e.get("enabled") is True and get(U, "/api/se/state")["enabled"] is True)
    post(U, "/api/se/enable", dict(on=False))
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        for k in ("SYN01", "SYN02", "TST01"): post(U, "/api/se/run", dict(code=k)); wait(U, k)
finally:
    stop(app)
# ---- corrupt configured model -> fallback with reason
os.makedirs(os.path.join(B, "unified_engine", "models"), exist_ok=True)
with open(os.path.join(B, "unified_engine", "models", "broken_model.json"), "w") as f: f.write("{broken")
with open(os.path.join(B, "unified_engine", "config.json"), "w") as f: json.dump(dict(active_model="broken_model.json"), f)
app, U = start()
try:
    st = get(U, "/api/se/state")
    check("broken model listed as not usable", any(m.get("status") == "corrupt" for m in st.get("models", [])))
    post(U, "/api/se/run", dict(code="SYN05")); r = wait(U, "SYN05")
    check("configured corrupt model -> ML withheld with reason, deterministic shown", r.get("ml_applied") is False and "corrupt" in r.get("ml_status", ""))
finally:
    stop(app)
os.remove(os.path.join(B, "unified_engine", "config.json"))
# ---- engine crash -> fallback; app unaffected
app, U = start(dict(CSS_ENGINE_FAIL="1"))
try:
    post(U, "/api/se/run", dict(code="SYN06")); r = wait(U, "SYN06")
    check("engine crash -> job failed, no shadow file, deterministic rows served", r.get("job", {}).get("status") == "failed" and r.get("available") is False
          and len(r.get("deterministic_rows", [])) > 0 and "CSS_ENGINE_FAIL" in r.get("error", ""))
    with open(os.path.join(B, "review", "SYN06_candidates.csv"), newline="") as f: n = sum(1 for _ in csv.DictReader(f))
    check("fallback rows = the detector's shown + excluded rows", sum(x["list"] == "shown" for x in r.get("deterministic_rows", [])) == n)
    check("app keeps serving after the engine crash", get(U, "/api/state") is not None and get(U, "/api/se/state").get("shadow_mode") is True)
finally:
    stop(app)
d2 = diff({k: v for k, v in before2.items() if not k.startswith("review/TST01")}, {k: v for k, v in tree(B).items() if not k.startswith("review/TST01")})
check("existing files byte-identical after all runs (incl. the crash)", not any(d2.values()), str(d2))
check("study records unchanged after all runs (every field)", not any(v for c, v in pj_fields().items()), str({k: v for k, v in pj_fields().items() if v}))
check("no write into the real project folders during the test", real_mtimes() == real0)
# ---- headless browser: the screen renders, three outputs and the shadow banner are visible
chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if os.path.exists(chrome):
    app, U = start()
    try:
        prof = os.path.join(T, "chrome")
        dom = subprocess.run([chrome, "--headless=new", "--disable-gpu", f"--user-data-dir={prof}", "--virtual-time-budget=8000", "--dump-dom", f"{U}/#shadow:SYN01"],
                             capture_output=True, text=True, timeout=120).stdout
        check("browser: shadow banner rendered", 'data-se="banner"' in dom and "SHADOW MODE" in dom)
        check("browser: synthetic banner + model version rendered", 'data-se="synthetic"' in dom and "synthetic_demo_offset" in dom)
        check("browser: study detail shows the three outputs separately", all(s in dom for s in ("1 · Existing deterministic", "2 · Experimental ML", "3 · Experimental Unified")))
        if SHOTS:
            for name, url in (("shadow_overview", "#shadow"), ("shadow_study_SYN01", "#shadow:SYN01"), ("shadow_fallback_TST01", "#shadow:TST01")):
                subprocess.run([chrome, "--headless=new", "--disable-gpu", f"--user-data-dir={prof}", "--hide-scrollbars", "--window-size=1600,1500",
                                "--virtual-time-budget=8000", f"--screenshot={os.path.join(SHOTS, name + '.png')}", f"{U}/{url}"], capture_output=True, timeout=120)
            check("screenshots written", all(os.path.exists(os.path.join(SHOTS, n + ".png")) for n in ("shadow_overview", "shadow_study_SYN01", "shadow_fallback_TST01")))
    finally:
        stop(app)
else:
    print("NOTE  Google Chrome not found - browser checks not run")
shutil.rmtree(T, ignore_errors=True)
print(f"\n{'ALL PASS' if not FAILS else f'{len(FAILS)} FAIL'} ({__file__})")
sys.exit(1 if FAILS else 0)
