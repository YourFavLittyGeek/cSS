"""check_app_image_ml.py - end-to-end test of the Image ML prototype through the app's own HTTP API and a headless browser.
SYNTHETIC cohort only (unified_engine/run_imaging.py cohort, temporary folder); the app runs with the write guard (CSS_EXPERIMENTAL=1) and the
real project folders listed as protected.
Checks: the Image ML screen is in the GUI; synthetic-only flags and warning; POST needs the app header; unknown / non-SYN study refused;
inference for a study (predictions, coordinates, provenance, previews); existing inputs byte-identical; invalid image study -> not scorable;
model failure -> job failed, fallback rows, the app keeps serving, the previous result kept; corrupt model listed and never selected;
Image ML, Characteristic ML and MATH returned in separate blocks; the Shadow ML screen still works; a NON-synthetic base lists and reads
nothing; browser DOM: synthetic banner, three separate streams, patch canvases, provenance; clean shutdown; real folders untouched.
usage: python tests/check_app_image_ml.py [--shots DIR]   (exit 1 on any FAIL)"""
import glob, hashlib, json, os, shutil, socket, subprocess, sys, tempfile, time, urllib.error, urllib.request
H = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(H); PY = sys.executable
CLI = os.path.join(ROOT, "unified_engine", "run_imaging.py")
FAILS = []
def check(n, ok, info=""):
    print(f"{'PASS' if ok else 'FAIL'}  {n}  {info}"); (None if ok else FAILS.append(n))

SHOTS = sys.argv[sys.argv.index("--shots") + 1] if "--shots" in sys.argv else None
REAL = [os.path.expanduser("~/css_project"), os.path.expanduser("~/cSS_experimental")]
T = tempfile.mkdtemp(prefix="imageml_app_"); HOME = os.path.join(T, "home"); B = os.path.join(HOME, "syn_images"); os.makedirs(HOME)
NB = os.path.join(HOME, "not_synthetic"); os.makedirs(os.path.join(NB, "review")); os.makedirs(os.path.join(NB, "data"))
for f in ("review/SYN001_candidates.csv", "data/SYN001_swi.nii"):                 # looks like a study, but the base has no synthetic marker
    with open(os.path.join(NB, f), "w") as fh: fh.write("placeholder - must never be listed or read by Image ML\n")
r = subprocess.run([PY, CLI, "cohort", B, "--n", "4", "--seed", "42"], capture_output=True, text=True)
check("synthetic cohort written", r.returncode == 0, r.stderr[-300:])


def tree(d, subs=("review", "data", "work", "raw")):
    out = {}
    for s in subs:
        for f in glob.glob(os.path.join(d, s, "**", "*"), recursive=True):
            if os.path.isfile(f):
                with open(f, "rb") as fh: out[os.path.relpath(f, d)] = hashlib.sha256(fh.read()).hexdigest()
    return out
def real_mtimes():
    return {d: max((os.path.getmtime(f) for f in glob.glob(os.path.join(d, "review", "*"))), default=0) for d in REAL if os.path.isdir(d)}
def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
def start(base, extra=None):
    port = free_port()
    env = dict(os.environ, HOME=HOME, CSS_BASE=base, CSS_EXPERIMENTAL="1", PYTHONPATH=os.path.join(ROOT, "app", "guard"),
               CSS_PROTECTED_PATHS=":".join(REAL + [os.path.expanduser("~/Projects/cSS")]), CSS_IMAGE_ENGINE_TIMEOUT_S="240", **(extra or {}))
    env.pop("CSS_IMAGE_ENGINE_FAIL", None); env.update(extra or {})
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
def wait(U, code, limit=300):
    t0 = time.time()
    while time.time() - t0 < limit:
        r = get(U, f"/api/im/result?study={code}")
        if r["job"].get("status") in ("completed", "failed"): return r
        time.sleep(0.5)
    return dict(timeout=True, job={})
def stop(p):
    p.terminate()
    try: p.wait(timeout=20); return True
    except subprocess.TimeoutExpired: p.kill(); return False


real0 = real_mtimes(); before = tree(B)
app, U = start(B)
try:
    html = urllib.request.urlopen(U + "/", timeout=30).read().decode()
    check("Image ML screen in the GUI", 'data-v="imageml"' in html and "/image_ml_view.js" in html)
    js = urllib.request.urlopen(U + "/image_ml_view.js", timeout=30).read().decode()
    check("Image ML view served", "function imageMlView" in js and "SYNTHETIC DATA ONLY" in js)
    st = get(U, "/api/im/state")
    check("synthetic-only flags and warning", st.get("synthetic_only") is True and st.get("experimental") is True and "not clinical results" in st.get("warning", ""))
    check("synthetic studies listed", [s["code"] for s in st["studies"]] == ["SYN001", "SYN002", "SYN003", "SYN004"], str([s["code"] for s in st["studies"]]))
    am = st.get("active_model") or {}
    check("healthy synthetic image model active", am.get("status") == "ok" and am.get("data_kind") == "synthetic", str(am.get("name")))
    check("POST without app header refused", post(U, "/api/im/run", dict(code="SYN001"), header=False).get("http") == 403)
    check("unknown / non-SYN study refused", not post(U, "/api/im/run", dict(code="M01")).get("ok") and not post(U, "/api/im/run", dict(code="SYN999")).get("ok"))
    check("run starts", post(U, "/api/im/run", dict(code="SYN001")).get("ok") is True)
    r1 = wait(U, "SYN001"); d = r1.get("image_ml") or {}
    check("inference completed", r1["job"].get("status") == "completed" and r1.get("available"), r1["job"].get("error", ""))
    ok = [c for c in d.get("candidates", []) if c["status"] == "ok"]
    check("predictions for scorable candidates", len(ok) >= 3, f"{len(ok)} scored")
    check("prediction fields (class, p(cSS) + interval, confidence, category)", all({"predicted_class", "p_css", "p_css_interval", "confidence", "category"} <= set(c) for c in ok))
    check("candidate coordinates (voxel + world)", all(len(c.get("vox_ijk", [])) == 3 and len(c.get("world_centre_mm", [])) == 3 for c in ok))
    check("patch previews", all({"surface_uv", "surface_vn", "native_centre"} <= set(c.get("previews", {})) for c in ok))
    m = d.get("model", {})
    check("model provenance (hash, version, data kind, training, evaluation)", m.get("applied") and len(m.get("model_hash") or "") == 64 and m.get("data_kind") == "synthetic"
          and m.get("training", {}).get("data_kind") == "synthetic" and "negative_control_independent" in (m.get("evaluation") or {}))
    check("result stamped synthetic", d.get("synthetic") is True and "SYNTHETIC" in d.get("stamp", ""))
    check("three streams in separate blocks", "image_ml" in r1 and "characteristics" in r1 and "math" in r1 and r1["characteristics"].get("available") is False
          and r1["math"].get("available") is False and "not available" in r1["math"].get("reason", ""))
    check("engine-verified inputs unchanged", d.get("original_inputs_unchanged") is True)
    post(U, "/api/im/run", dict(code="SYN002")); r2 = wait(U, "SYN002")
    st2 = {c["status"] for c in (r2.get("image_ml") or {}).get("candidates", [])}
    check("invalid image study (3 mm slices) -> not scorable", st2 == {"not_scorable"} and "quality_refused" in ((r2.get("image_ml") or {}).get("study") or {}).get("blocked", ""), str(st2))
    os.makedirs(os.path.join(B, "unified_engine", "models", "image"), exist_ok=True)
    with open(os.path.join(B, "unified_engine", "models", "image", "zz_corrupt.json"), "w") as fh: fh.write("{broken")
    ms = get(U, "/api/im/models?force=1").get("models", [])
    check("corrupt model listed as unusable", any(x.get("status") == "corrupt" for x in ms))
    check("corrupt model never selected", (get(U, "/api/im/state").get("active_model") or {}).get("status") == "ok")
    check("Shadow ML screen still works", "studies" in get(U, "/api/se/state"))
    check("existing inputs byte-identical after runs", tree(B) == before)
    shots = []
    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if os.path.exists(chrome):
        prof = os.path.join(T, "chrome")
        def dom(url):
            return subprocess.run([chrome, "--headless=new", "--disable-gpu", f"--user-data-dir={prof}", "--virtual-time-budget=9000", "--dump-dom", f"{U}/{url}"],
                                  capture_output=True, text=True, timeout=120).stdout
        D = dom(f"#imageml:SYN001:{ok[0]['ref']}")
        check("browser: synthetic banner", 'data-im="banner"' in D and "SYNTHETIC DATA ONLY" in D)
        check("browser: Image ML / Characteristic ML / MATH shown separately", all(f'data-im="stream-{s}"' in D for s in ("image", "characteristics", "math")))
        check("browser: candidate table with coordinates and classes", 'data-im="cands"' in D and "p(cSS)" in D and "world centre" in D)
        check("browser: patch canvases", all(f'id="imp{i}"' in D for i in (1, 2, 3)) and 'data-im="patches"' in D)
        check("browser: model provenance", 'data-im="provenance"' in D and m.get("model_hash", "x") in D)
        if SHOTS:
            os.makedirs(SHOTS, exist_ok=True)
            for name, url in (("imageml_overview", "#imageml"), ("imageml_candidate", f"#imageml:SYN001:{ok[0]['ref']}"), ("imageml_not_scorable", "#imageml:SYN002")):
                subprocess.run([chrome, "--headless=new", "--disable-gpu", f"--user-data-dir={prof}", "--hide-scrollbars", "--window-size=1500,1900",
                                "--virtual-time-budget=9000", f"--screenshot={os.path.join(SHOTS, name + '.png')}", f"{U}/{url}"], capture_output=True, timeout=120)
                shots.append(name)
    else: print("NOTE  Google Chrome not found - browser checks not run")
finally:
    check("clean shutdown", stop(app))

prev = tree(B, ("unified_engine/image_ml",))
app, U = start(B, dict(CSS_IMAGE_ENGINE_FAIL="1"))
try:
    post(U, "/api/im/run", dict(code="SYN003")); rf = wait(U, "SYN003")
    check("model failure -> job failed with reason", rf["job"].get("status") == "failed" and "simulated image model failure" in rf["job"].get("error", ""))
    check("model failure -> no result, detector rows as fallback", rf.get("available") is False and len(rf.get("detector_rows", [])) > 0)
    check("app keeps serving after the failure", "studies" in get(U, "/api/im/state") and isinstance(get(U, "/api/state"), dict))
    post(U, "/api/im/run", dict(code="SYN001")); rk = wait(U, "SYN001")
    check("failed re-run keeps the previous result", rk.get("available") is True and rk.get("stale_job_error", "").startswith("inference failed"))
    check("failed runs wrote nothing", tree(B, ("unified_engine/image_ml",)) == prev)
    if os.path.exists("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"):
        D = subprocess.run(["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "--headless=new", "--disable-gpu", f"--user-data-dir={os.path.join(T, 'chrome2')}",
                            "--virtual-time-budget=9000", "--dump-dom", f"{U}/#imageml:SYN003"], capture_output=True, text=True, timeout=120).stdout
        check("browser: failure shown with fallback", 'data-im="failed"' in D and 'data-im="no-result"' in D)
finally:
    check("clean shutdown (failure app)", stop(app))

app, U = start(NB)
try:
    s = get(U, "/api/im/state")
    check("non-synthetic base: nothing listed", s.get("synthetic_base") is False and s.get("studies") == [])
    check("non-synthetic base: run refused", post(U, "/api/im/run", dict(code="SYN001")).get("ok") is False)
    check("non-synthetic base: result refused", get(U, "/api/im/result?study=SYN001").get("available") is False)
    check("non-synthetic base: nothing written", not os.path.exists(os.path.join(NB, "unified_engine", "image_ml")))
finally:
    check("clean shutdown (non-synthetic app)", stop(app))
check("no write into the real project folders", real_mtimes() == real0)
if SHOTS: check("screenshots written", all(os.path.exists(os.path.join(SHOTS, n + ".png")) for n in ("imageml_overview", "imageml_candidate", "imageml_not_scorable")))
shutil.rmtree(T, ignore_errors=True)
print(("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}") + f" ({__file__})"); sys.exit(1 if FAILS else 0)
