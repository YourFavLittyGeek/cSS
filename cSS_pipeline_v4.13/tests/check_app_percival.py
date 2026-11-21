"""check_app_percival.py - v5.22 PERCIVAL SCORE through the real app + headless Chrome (SYNTHETIC cohort with known truth; no clinical data).
Checks: switched off until the user switches it on (a synthetic project may still be learned - no real MRI read); a controlled training
cycle runs from the app; the Percival Intelligence screen (tiles, learning curve, locked test, components & agreement, meta-model
discovery with the actual calculation, thresholds, registry); promotion by the user and rollback; every study assessed (ledger); the
ordinary viewer shows ONE primary score - Percival Score 0-100 with its colour band - and no competing scores; controlled cycles (no
cycle after a single review); the training selection.
usage: python tests/check_app_percival.py [--shots DIR]   (exit 1 on any FAIL)"""
import glob, json, os, re, shutil, socket, subprocess, sys, tempfile, time, urllib.error, urllib.request
import numpy as np, pandas as pd
H = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(H); PY = sys.executable
F = []
def check(n, ok, info=""): print(f"{'PASS' if ok else 'FAIL'}  {n}  {info}"); (None if ok else F.append(n))
SHOTS = sys.argv[sys.argv.index("--shots") + 1] if "--shots" in sys.argv else None
T = tempfile.mkdtemp(prefix="apppc_"); HOME = os.path.join(T, "home"); B = os.path.join(HOME, "syn_percival"); os.makedirs(HOME)
r = subprocess.run([PY, os.path.join(ROOT, "unified_engine", "run_imaging.py"), "cohort", B, "--n", "24", "--seed", "8"], capture_output=True, text=True)
check("synthetic cohort generated (24 studies)", r.returncode == 0, (r.stderr or "")[-200:])
rng = np.random.default_rng(2); studies = sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(B, "unified_engine", "image_truth", "SYN*.csv"))); pats = []
for sid in studies:
    t = pd.read_csv(os.path.join(B, "unified_engine", "image_truth", f"{sid}.csv")); t = t[t["list"] == "candidates"]
    c = pd.read_csv(os.path.join(B, "review", f"{sid}_candidates.csv")); y = {int(o): int(k == "definite_css") for o, k in zip(t.obj_id, t.primary_class)}; yy = np.array([y.get(int(i), 0) for i in c.cand_id])
    c["score_v4"] = np.maximum(0, 0.5 * yy + rng.normal(0.5, 0.5, len(c))); c["hemi"] = ["L" if k % 2 else "R" for k in range(len(c))]; c["region"] = "ctx-lh-superiorparietal"
    c["darkness_z"] = rng.normal(-1 - yy, 0.8); c["edge_contrast"] = rng.normal(0.3 + 0.3 * yy, 0.2); c["tube_ratio"] = rng.normal(2 - 0.8 * yy, 0.6)
    c.to_csv(os.path.join(B, "review", f"{sid}_candidates.csv"), index=False)
    recs = [dict(cand_id=int(i), F={k: dict(value=float(v), status="reliable") for k, v in dict(x1_vessel_continuity_mm=rng.normal(6 - 3 * y.get(int(i), 0), 1.8), x2_core_contrast_nu=rng.normal(0.4 + 0.4 * y.get(int(i), 0), 0.3),
            x3_pial_distance_mm=rng.normal(1, 0.6), x4_sulcal_alignment=rng.normal(0.3 + 0.3 * y.get(int(i), 0), 0.3), x5_extracranial_mm=rng.normal(2 - 1.2 * y.get(int(i), 0), 1)).items()}) for i in c.cand_id]
    os.makedirs(os.path.join(B, "uscore", "features"), exist_ok=True); json.dump(dict(study=sid, records=recs), open(os.path.join(B, "uscore", "features", f"{sid}.json"), "w"))
    rows = [dict(cand_id=int(i), call="cSS" if v else "Vessel", comment="", reviewer="Dr Syn", time="2026-11-21 10:00:00") for i, v in zip(c.cand_id, yy)]
    cols = ["cand_id", "call", "comment", "reviewer", "time"]
    pd.DataFrame(rows, columns=cols).to_csv(os.path.join(B, "review", f"{sid}_calls_Dr_Syn.csv"), index=False); pd.DataFrame(rows, columns=cols)[["cand_id", "call"]].to_csv(os.path.join(B, "review", f"{sid}_calls.csv"), index=False)
    json.dump(dict(reviewer="Dr Syn", saved="2026-11-21 10:05:00"), open(os.path.join(B, "review", f"{sid}_final_Dr_Syn.json"), "w"))
    pats.append(dict(code=sid, cohort="SYN", status="done", fingerprint="", series={}, steps_done={}, added=0, mode="semi", anatomy="synthseg", pathway="synthseg"))
os.makedirs(os.path.join(B, "app_data"), exist_ok=True); json.dump(pats, open(os.path.join(B, "app_data", "patients.json"), "w"))
shutil.copytree(os.path.join(ROOT, "scripts"), os.path.join(B, "scripts"), ignore=shutil.ignore_patterns("__pycache__"))
def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
port = free_port(); U = f"http://127.0.0.1:{port}"
env = dict(os.environ, HOME=HOME, CSS_BASE=B, CSS_EXPERIMENTAL="1", CSS_WATCH_S="2", CSS_LEARN_MIN="8,40,6", CSS_PERCIVAL_EPOCHS="12",
           PYTHONPATH=os.pathsep.join([os.path.join(ROOT, "app", "guard")] + ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else [])),
           CSS_PROTECTED_PATHS=":".join([os.path.expanduser("~/css_project"), os.path.expanduser("~/cSS_experimental"), os.path.expanduser("~/Projects/cSS")]))
app = subprocess.Popen([PY, os.path.join(ROOT, "app", "css_app.py"), "--port", str(port), "--no-window"], env=env, stdout=open(os.path.join(T, "app.log"), "w"), stderr=subprocess.STDOUT)
def get(p):
    try: return json.loads(urllib.request.urlopen(U + p, timeout=120).read())
    except urllib.error.HTTPError as e: return json.loads(e.read())
def post(p, d):
    rq = urllib.request.Request(U + p, data=json.dumps(d).encode(), headers={"Content-Type": "application/json", "X-CSS-App": "1"})
    return json.load(urllib.request.urlopen(rq, timeout=300))
def wait_job(limit=900):
    t0 = time.time(); time.sleep(1)
    while time.time() - t0 < limit:
        s = get("/api/percival/state")
        if s["job"].get("state") != "running": return s
        time.sleep(1)
    return get("/api/percival/state")
chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
def dom(url, budget=12000):
    if not os.path.exists(chrome): return ""
    R_ = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--enable-logging=stderr", "--v=0", f"--user-data-dir={os.path.join(T, 'chrome')}", f"--virtual-time-budget={budget}", "--dump-dom", url if url.startswith("http") else f"{U}/{url}"], capture_output=True, text=True, timeout=120)
    D = R_.stdout; errs = [l for l in R_.stderr.splitlines() if ("CONSOLE" in l or "console" in l) and ("Uncaught" in l or "rror" in l)]
    if errs: print("browser console errors:", " | ".join(e[-300:] for e in errs[:5]))
    return re.sub(r"<script\b[^>]*>.*?</script>", "", D, flags=re.S)
def shot(name, url, h=1500, w=1500):
    if SHOTS and os.path.exists(chrome):
        os.makedirs(SHOTS, exist_ok=True)
        subprocess.run([chrome, "--headless=new", "--disable-gpu", f"--user-data-dir={os.path.join(T, 'chrome_s')}", "--hide-scrollbars", f"--window-size={w},{h}", "--virtual-time-budget=15000",
                        f"--screenshot={os.path.join(SHOTS, name + '.png')}", url if url.startswith("http") else f"{U}/{url}"], capture_output=True, timeout=120)
try:
    for _ in range(80):
        try: urllib.request.urlopen(U + "/api/state", timeout=2); break
        except Exception: time.sleep(0.25)
    s = get("/api/percival/state")
    check("local learning switched off at first", s["authorized"] is False and s["active"] is None)
    D = dom("#intel")
    if 'data-pv="switch-on"' not in D: D = dom("#intel", 30000)          # first render right after start-up can exceed the budget on a busy machine
    check("Percival Intelligence offers the switch", 'data-pv="switch-on"' in D and "Percival Intelligence" in D)
    post("/api/percival/settings", dict(percival_test_fraction=0.35))    # the partition hashes random synthetic patient ids: a larger share keeps both classes in the locked test
    check("switch on", post("/api/percival/authorize", dict(on=True)).get("authorized") is True)
    post("/api/percival/train", {}); s = wait_job(); L = s["latest"]
    check("a controlled training cycle ran from the app", s["job"]["state"] == "finished" and L and L["version"] == "v001", f"latest={None if not L else L.get('version')} versions={s.get('versions')} " + str(s["job"]) + " | " + " / ".join(s.get("log", [])[-4:]))
    if L:
        check("locked test cohort used for evaluation only", L["data"]["test_candidates"] > 0 and L["test"].get("percival", {}).get("auc") is not None, json.dumps(L["data"]))
        check("meta-model chosen by the documented rule", L["discovery"]["chosen"] in L["discovery"]["results"] and "1-SE" in L["discovery"]["rule"], L["discovery"]["chosen"])
        acc = L["acceptance"]
        if not s["active"]:
            r = post("/api/percival/promote", dict(version="v001")); s = get("/api/percival/state")
            check("not auto-promoted (acceptance not passed) - promoted by the user instead", r.get("ok") and s["active"]["version"] == "v001" and not acc["passed"], json.dumps(acc))
        else: check("auto-promoted because the acceptance criteria passed", acc["passed"])
    time.sleep(6)
    sc = get(f"/api/percival/score?code={studies[2]}")
    check("every study assessed: Percival Score 0-100, band, status, components", sc.get("candidates") and all((c["percival_score"] is None or 0 <= c["percival_score"] <= 100) for c in sc["candidates"]) and set(sc["candidates"][0]["components"]) == {"math", "unified", "char", "image", "fusion"})
    check("prediction ledger written", bool(get(f"/api/percival/history?code={studies[2]}")["ledger"]))
    for tab, mark in (("overview", 'class="lv-svg"'), ):
        D = dom("#intel"); check("Intelligence screen: tiles, learning curve, locked-test table", 'data-pv="tiles"' in D and mark in D and 'data-pv="test"' in D)
    shot("v522_intelligence_overview", "#intel")
    De = dom("#intel?tab=evidence", 15000)
    check("v5.23 Evidence & reliability tab: model families, fusion benefit, shared inputs, incremental value, disagreement, calibration, review snapshots",
          all(f'data-pv="{k}"' in De for k in ("family-char", "family-image", "family-fusion", "overlap", "ablation", "disagreement", "calibration")) and "Expert-review snapshots" in De and "Does fusion help?" in De)
    shot("v523_intelligence_evidence", "#intel?tab=evidence", 2600)
    Dx = dom("#intel?tab=explore", 15000)
    check("v5.23 candidate explorer lists why a candidate is uncertain", "why uncertain" in Dx)
    # the ordinary viewer: ONE primary score
    r = post("/api/review", dict(codes=[studies[2]])); meta = {}; Dv = ""
    if r.get("url"):
        last = ""
        for _ in range(60):
            try: meta = json.loads(urllib.request.urlopen(r["url"] + f"api/meta?study={studies[2]}", timeout=60).read()); break
            except urllib.error.HTTPError as e: last = f"HTTP {e.code}: {e.read()[:300]!r}"; time.sleep(1)
            except Exception as e: last = f"{type(e).__name__}: {e}"; time.sleep(1)
        if not meta: print("viewer meta not received:", last)
        Dv = dom(r["url"], 15000)
    check("viewer receives the Percival assessment", meta.get("percival") and meta["percival"]["model"] == "v001", str(r)[:150])
    for k_, v_ in (("pscore", 'data-id="percival-score"' in Dv), ("/100", "/ 100" in Dv), ("no Unified card", "Unified score" not in Dv), ("no AI evidence card", "AI evidence for cSS" not in Dv)): print("viewer DOM", k_, v_)
    check("viewer: one primary score - Percival Score with its band, no competing score cards", 'data-id="percival-score"' in Dv and "/ 100" in Dv and "Unified score" not in Dv and "AI evidence for cSS" not in Dv)
    check("v5.23 viewer: the note under the score is Percival's (not the legacy rule-based meter text)", "rule-based evidence" not in Dv.split('id="aisrc"')[1][:300] if 'id="aisrc"' in Dv else False)
    check("v5.23 viewer: 'Why this score' evidence panel under the single score (components, contributions, reliability)", 'id="pwhy"' in Dv and "Why this score" in Dv and "Each source on its own" in Dv)
    check("v5.23 reviewer snapshots: every final review stored with the outputs available at review time", len(get(f"/api/percival/reviews?code={studies[2]}").get("reviews", [])) >= 1)
    if SHOTS and r.get("url"): shot("v522_viewer_percival_score", r["url"], 1100)
    # second cycle, selection, rollback, controlled cycles
    post("/api/percival/select", dict(codes=studies[:2], include=False)); post("/api/percival/train", {}); s = wait_job()
    n1_all = L["data"]["studies"] if L else None                   # cycle 1 learned the studies that have labelled candidates (not every study does)
    check("second cycle on the selection -> v002 in the registry", s["versions"] == ["v001", "v002"] and s["latest"]["data"]["studies"] == n1_all - 2,
          f"versions {s['versions']} studies {(s.get('latest') or {}).get('data', {}).get('studies')} of {len(studies)} job {s['job']}")
    post("/api/percival/promote", dict(version="v002")); r = post("/api/percival/rollback", {})
    check("rollback to the previous model", r.get("version") == "v001" and get("/api/percival/state")["active"]["version"] == "v001")
    n = len(get("/api/percival/state")["versions"]); time.sleep(6)
    check("controlled cycles: no new cycle without N newly finished studies", len(get("/api/percival/state")["versions"]) == n)
finally:
    app.terminate(); app.wait(timeout=20)
    subprocess.run(["pkill", "-f", os.path.join(B, "scripts", "review_web.py")], capture_output=True)      # only this test's own reviewer (temporary project)
if F and os.environ.get("CSS_KEEP_TMP") == "1": print("kept for inspection:", T)
else: shutil.rmtree(T, ignore_errors=True)
print(("ALL PASS" if not F else f"{len(F)} FAILED: {F}") + f" ({__file__})"); sys.exit(1 if F else 0)
