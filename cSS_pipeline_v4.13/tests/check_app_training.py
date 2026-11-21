"""check_app_training.py - v5.17 Training screen through the real app (SYNTHETIC project): four sections reachable; the image model's card
(architecture, version, training data, weights + hash) labelled synthetic; MATH / shadow / uscore listed; labels in css-labels/2.0;
synthetic and clinical evaluation in separate blocks (no clinical result invented); a new synthetic evaluation runs in the background,
writes a report with sensitivity / specificity / ROC / PR / calibration / confusion matrix / errors and leaves the model file unchanged;
browser DOM shows the synthetic badges.
usage: python tests/check_app_training.py [--shots DIR]   (exit 1 on any FAIL)"""
import glob, hashlib, json, os, shutil, socket, subprocess, sys, tempfile, time, urllib.request
H = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(H); PY = sys.executable
F = []
def check(n, ok, info=""): print(f"{'PASS' if ok else 'FAIL'}  {n}  {info}"); (None if ok else F.append(n))
SHOTS = sys.argv[sys.argv.index("--shots") + 1] if "--shots" in sys.argv else None
def sha(p):
    with open(p, "rb") as f: return hashlib.sha256(f.read()).hexdigest()
T = tempfile.mkdtemp(prefix="train_app_"); HOME = os.path.join(T, "home"); B = os.path.join(HOME, "syn_project"); os.makedirs(HOME)
r = subprocess.run([PY, os.path.join(ROOT, "unified_engine", "run_imaging.py"), "cohort", B, "--n", "2", "--seed", "42"], capture_output=True, text=True)
check("synthetic project written", r.returncode == 0, r.stderr[-200:])
MODEL = os.path.join(ROOT, "unified_engine", "models", "image", "synthetic_image_softmax_v1.0.0.json"); m0 = sha(MODEL)
s_ = socket.socket(); s_.bind(("127.0.0.1", 0)); port = s_.getsockname()[1]; s_.close(); U = f"http://127.0.0.1:{port}"
app = subprocess.Popen([PY, os.path.join(ROOT, "app", "css_app.py"), "--port", str(port), "--no-window"], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
                       env=dict(os.environ, HOME=HOME, CSS_BASE=B, CSS_EXPERIMENTAL="1", PYTHONPATH=os.path.join(ROOT, "app", "guard"),
                                CSS_PROTECTED_PATHS=":".join([os.path.expanduser("~/css_project"), os.path.expanduser("~/cSS_experimental")])))
def get(p): return json.load(urllib.request.urlopen(U + p, timeout=120))
def post(p, d):
    rq = urllib.request.Request(U + p, data=json.dumps(d).encode(), headers={"Content-Type": "application/json", "X-CSS-App": "1"})
    return json.load(urllib.request.urlopen(rq, timeout=120))
try:
    for _ in range(80):
        try: urllib.request.urlopen(U + "/api/state", timeout=2); break
        except Exception: time.sleep(0.25)
    html = urllib.request.urlopen(U + "/", timeout=30).read().decode()
    check("Training screen in the navigation and routed", 'data-v="train"' in html and 'if(V==="train")' in html and "/training_view.js" in html)
    o = get("/api/train/overview")
    m = (o["A"]["models"] or [{}])[0]; c = m.get("card") or {}
    check("A: image model card (architecture, version, training data, weights + hash) labelled synthetic", m.get("status") == "ok" and m.get("data_kind") == "synthetic"
          and c.get("method") and c.get("version") == "1.0.0" and (c.get("training") or {}).get("data_kind") == "synthetic" and len(m.get("model_hash", "")) == 64 and m.get("file_size", 0) > 1000)
    check("B: MATH, shadow models and the project's Unified Score listed", o["B"]["math"]["detector"] and isinstance(o["B"]["shadow"]["models"], list) and "uscore" in o["B"])
    check("C: labels summarised in css-labels/2.0", o["C"]["labels"].get("schema") == "css-labels/2.0" and "by_class" in o["C"]["labels"])
    check("D: clinical block holds no invented result", o["D"]["clinical"]["image_ml"] is None and "no clinical evaluation" in o["D"]["clinical"]["note"])
    check("D: no synthetic evaluation before one is run", o["D"]["synthetic"]["image_ml"] == [])
    r = post("/api/train/evaluate", dict(n=3)); check("synthetic evaluation starts", r.get("ok") is True)
    t0 = time.time()
    while time.time() - t0 < 600 and get("/api/train/job").get("status") == "running": time.sleep(2)
    j = get("/api/train/job"); check("synthetic evaluation completed", j.get("status") == "completed", j.get("error", ""))
    o = get("/api/train/overview"); ev = (o["D"]["synthetic"]["image_ml"] or [{}])[0]
    check("report: data kind synthetic, sensitivity / specificity, ROC, PR, calibration, confusion matrix, errors", ev.get("data_kind") == "synthetic"
          and 0 <= ev.get("sensitivity", -1) <= 1 and 0 <= ev.get("specificity", -1) <= 1 and len(ev.get("roc", [])) > 2 and len(ev.get("pr", [])) > 1
          and ev.get("calibration") and ev.get("confusion_kinds", {}).get("matrix") and "errors" in ev)
    check("evaluation only read the model file", sha(MODEL) == m0)
    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if os.path.exists(chrome):
        dom = lambda url: subprocess.run([chrome, "--headless=new", "--disable-gpu", f"--user-data-dir={os.path.join(T, 'chrome')}", "--virtual-time-budget=9000", "--dump-dom", f"{U}/{url}"],
                                         capture_output=True, text=True, timeout=120).stdout
        D = dom("#train:A"); check("browser A: model card with SYNTHETIC badge", 'data-tv="image-model"' in D and 'data-tv="synthetic"' in D)
        D = dom("#train:D"); check("browser D: synthetic and clinical evaluations separate", 'data-tv="eval-synthetic"' in D and 'data-tv="eval-clinical"' in D and "Sensitivity / specificity" in D)
        D = dom("#train:C"); check("browser C: labels section", 'data-tv="labels"' in D)
        if SHOTS:
            os.makedirs(SHOTS, exist_ok=True)
            for t in "ABCD":
                subprocess.run([chrome, "--headless=new", "--disable-gpu", f"--user-data-dir={os.path.join(T, 'chrome')}", "--hide-scrollbars", "--window-size=1500,1400", "--virtual-time-budget=9000",
                                f"--screenshot={os.path.join(SHOTS, f'training_{t}.png')}", f"{U}/#train:{t}"], capture_output=True, timeout=120)
finally:
    app.terminate(); app.wait(timeout=20)
shutil.rmtree(T, ignore_errors=True)
print(("ALL PASS" if not F else f"{len(F)} FAILED: {F}") + f" ({__file__})"); sys.exit(1 if F else 0)
