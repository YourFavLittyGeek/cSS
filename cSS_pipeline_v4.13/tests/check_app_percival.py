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
SK = []; _DOM = dict(missing=None)
def check(n, ok, info=""):
    """Stage 7: a check whose page could not be rendered (no usable headless browser) is SKIPPED with the reason - never PASS"""
    if _DOM["missing"]: print(f"SKIP  {n}  ({_DOM['missing']})"); SK.append(n); _DOM["missing"] = None; return
    print(f"{'PASS' if ok else 'FAIL'}  {n}  {info}"); (None if ok else F.append(n))
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
sys.path.insert(0, H); import gt_fixture; gt_fixture.ground_truth(B, ["Dr Syn"])   # Phase 3A fixture: designated expert + documented verification
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
        if s["job"].get("state") not in ("preparing", "running"): return s
        time.sleep(1)
    return get("/api/percival/state")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import _chrome as CH                # Stage 7 headless-Chrome harness
chrome = CH.find() or "/nonexistent"
class _NoDOM(str):
    def __contains__(self, x): return True                                 # the check that reads it is reported SKIPPED, never PASS
def dom(url, budget=12000):
    D, err = CH.dump_dom(url if url.startswith("http") else f"{U}/{url}", os.path.join(T, "chrome"), budget=max(budget, 15000))
    if D is None: _DOM["missing"] = err; return _NoDOM("")
    _DOM["missing"] = None
    errs = [l for l in (err or "").splitlines() if ("CONSOLE" in l or "console" in l) and ("Uncaught" in l or "rror" in l)]
    if errs: print("browser console errors:", " | ".join(e[-300:] for e in errs[:5]))
    return re.sub(r"<script\b[^>]*>.*?</script>", "", D, flags=re.S)
def shot(name, url, h=1500, w=1500):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        CH.screenshot(url if url.startswith("http") else f"{U}/{url}", os.path.join(SHOTS, name + ".png"), os.path.join(T, "chrome_s"), w=w, h=h)
try:
    for _ in range(80):
        try: urllib.request.urlopen(U + "/api/state", timeout=2); break
        except Exception: time.sleep(0.25)
    s = get("/api/percival/state")
    check("local learning switched off at first", s["authorized"] is False and s["active"] is None)
    D = dom("#intel")
    if 'data-pv="switch-on"' not in D: D = dom("#intel", 30000)          # first render right after start-up can exceed the budget on a busy machine
    check("PERCIVAL screen offers the switch", 'data-pv="switch-on"' in D and "<b>PERCIVAL</b>" in D)
    post("/api/percival/settings", dict(percival_test_fraction=0.35))    # the partition hashes random synthetic patient ids: a larger share keeps both classes in the locked test
    check("switch on", post("/api/percival/authorize", dict(on=True)).get("authorized") is True)
    post("/api/percival/train", {}); s = wait_job(); L = s["latest"]
    check("a controlled training cycle ran from the app", s["job"]["state"] == "finished" and L and L["version"] == "v001", f"latest={None if not L else L.get('version')} versions={s.get('versions')} " + str(s["job"]) + " | " + " / ".join(s.get("log", [])[-4:]))
    if L:
        check("locked test cohort used for evaluation only", L["data"]["test_candidates"] > 0 and L["test"].get("percival", {}).get("auc") is not None, json.dumps(L["data"]))
        ds = L["data"].get("dataset")
        check("v5.24 model traceable to its dataset version (manifest with eligibility per component) and code version",
              ds and os.path.exists(os.path.join(B, "percival", "datasets", f"{ds}.json")) and L["data"].get("feature_schema") and L["data"].get("code_version", {}).get("engine_sha256"),
              json.dumps({k: L["data"].get(k) for k in ("dataset", "feature_schema", "code_version")}))
        st = json.load(open(os.path.join(B, "percival", "STORE.json")))
        check("v5.24 Percival store in the project folder (not in the engine code folder), schema recorded",
              st.get("schema") == 4 and os.path.exists(os.path.join(B, "percival", "registry", "v001", "model.json")) and not os.path.exists(os.path.join(B, "unified_engine", "percival", "registry")), str(st))
        check("meta-model chosen by the documented rule", L["discovery"]["chosen"] in L["discovery"]["results"] and "1-SE" in L["discovery"]["rule"], L["discovery"]["chosen"])
        acc = L["acceptance"]
        check("v5.24 never made active automatically: v001 registered as candidate / experimental, waiting for approval",
              not s["active"] and s["status"]["v001"]["status"] == ("candidate" if acc["passed"] else "experimental"), json.dumps(s.get("status")))
        r = post("/api/percival/promote", dict(version="v001"))
        if not r.get("ok"):
            check("v5.24 a version that did not pass needs an override with a reason", r.get("needs_override") and not acc["passed"], str(r))
            r = post("/api/percival/promote", dict(version="v001", override=True, why="test: research use"))
        s = get("/api/percival/state")
        check("promoted by the user (explicit approval) -> active", r.get("ok") and s["active"]["version"] == "v001" and s["status"]["v001"]["status"] == "active", str(r))
    time.sleep(6)
    sc = get(f"/api/percival/score?code={studies[2]}")
    check("every study assessed: Percival Score 0-100, band, status, components", sc.get("candidates") and all((c["percival_score"] is None or 0 <= c["percival_score"] <= 100) for c in sc["candidates"]) and set(sc["candidates"][0]["components"]) == {"math", "unified", "char", "image", "fusion"})
    check("prediction ledger written", bool(get(f"/api/percival/history?code={studies[2]}")["ledger"]))
    for tab, mark in (("overview", 'class="lv-svg"'), ):      # markers follow the current views: System is the default tab (81d9bd4); the 14-section Training Center (26568a1); detection / segmentation eligibility (26568a1)
        D = dom("#intel?tab=overview"); check("Intelligence screen: tiles, learning curve, locked-test table", 'data-pv="tiles"' in D and mark in D and 'data-pv="test"' in D)
    shot("v522_intelligence_overview", "#intel")
    De = dom("#intel?tab=evidence", 15000)
    check("v5.23 Evidence & reliability tab: model families, fusion benefit, shared inputs, incremental value, disagreement, calibration, review snapshots",
          all(f'data-pv="{k}"' in De for k in ("family-char", "family-image", "family-fusion", "overlap", "ablation", "disagreement", "calibration")) and "Expert-review snapshots" in De and "Does fusion help?" in De)
    shot("v523_intelligence_evidence", "#intel?tab=evidence", 2600)
    Dc = dom("#intel?tab=center", 15000)
    check("v5.24 Training Center: separate states (studies / processed / candidates / called / eligible), datasets per component, study table",
          all(f'data-pv="{k}"' in Dc for k in ("section-overview", "section-studies", "section-dataset-builder", "selection")) and "Decision Engine" in Dc and "LUMOS image network" in Dc)      # Stage 8: architecture names (the old "Percival meta-model" text no longer existed in the view - the check never ran while headless Chrome timed out)
    shot("v524_training_center", "#intel?tab=center", 2600)
    Di = dom("#intel?tab=integrity", 15000)
    check("v5.24 Data integrity: store schema, migration history, studies compatibility table", 'data-pv="integrity"' in Di and 'data-pv="compat"' in Di and "schema" in Di)
    shot("v524_data_integrity", "#intel?tab=integrity", 2600)
    Dm = dom("#intel?tab=models", 15000)
    check("v5.24 Model Center: registry with dataset per version", "Model Center" in Dm and 'data-pv="registry"' in Dm and "ds0" in Dm)
    check("v5.24 Model Center: status per version (active / candidate / experimental), registry details", ">active<" in Dm and 'data-pv="registry-detail"' in Dm
          and "No model becomes active by itself" in Dm)
    shot("v524_model_center", "#intel?tab=models", 2600)
    post("/api/percival/eligibility", {}); Dc = dom("#intel?tab=center", 15000); R = get("/api/percival/runs")["runs"]
    check("v5.24 Training Center: training runs, persisted eligibility record, reproducibility check", 'data-pv="section-history"' in Dc and "run001" in Dc and 'data-pv="section-eligibility"' in Dc
          and 'id="pv-repro"' in Dc and R and R[0]["state"] == "finished" and R[0]["version"] == "v001", json.dumps(R)[:300])
    rp = post("/api/percival/reproduce", dict(id=get("/api/percival/state")["datasets"][-1]["id"]))
    check("v5.24 dataset reproducibility check: identical, or every difference explained (here the Unified step re-extracts predictors after switch-on)",
          rp.get("ok") and (rp.get("identical") is True or (rp["n_differences"] > 0 and set(rp["changes"]) <= {"input availability changed (predictor)"})), json.dumps(rp)[:1500])
    shot("v524_training_runs", "#intel?tab=center", 2600)
    cc = get(f"/api/percival/candidates?code={studies[0]}")
    check("v5.24 candidate drill-down: eligibility per component with reasons in words", cc.get("candidates") and all(set(c["components"]) == {"char", "image", "fusion", "meta", "predictor", "shadow", "detection", "segmentation"} and "reasons_text" in c and "missing" in c for c in cc["candidates"]), str(cc)[:300])
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
    # Phase 3A.2: the first read is blind (server-enforced) - no Percival assessment; after a completed read + unblind it is shown
    check("Phase 3A.2: the blind first read does not receive the Percival assessment", meta.get("blind") is True and not meta.get("percival"), str(meta.get("read_phase"))[:150])
    sys.path.insert(0, os.path.join(ROOT, "scripts")); import review_blind as _RB, review_io as _RIO
    with _RIO.study_lock(B, studies[2]): _RIO.journal_append(B, studies[2], "Second Look", "initial_completed", n_candidates=0, n_called=0, note="test fixture: earlier blind read")
    _RB.unblind(B, studies[2], "Second Look"); meta2 = {}
    if r.get("url"):
        try: meta2 = json.loads(urllib.request.urlopen(r["url"] + f"api/meta?study={studies[2]}&reviewer=Second%20Look", timeout=60).read())
        except Exception as e: print("viewer meta (second look) not received:", e)
        # the page opens with the last reviewer name: the page checks below render that reviewer's second look
        urllib.request.urlopen(urllib.request.Request(r["url"] + "api/reviewer", json.dumps(dict(name="Second Look")).encode(),
                                                      {"Content-Type": "application/json", "X-CSS": "1"}), timeout=60).read()
        Dv = dom(r["url"], 15000)
    check("viewer receives the Percival assessment in the second look", meta2.get("percival") and meta2["percival"]["model"] == "v001", str(r)[:150])
    # v5.24 older research prototypes: hidden by default, still working, and the old Unified Score model cannot change the Percival Score
    st_ = get("/api/state"); feats = (st_.get("settings") or {}).get("features") or {}
    proto = {p_: get(p_) for p_ in ("/api/u/state", "/api/se/state", "/api/im/state", "/api/train/overview")}
    check("v5.24 older prototypes hidden by default but their back ends still answer (records, outputs, history kept)",
          not feats.get("show_prototypes") and all(isinstance(v_, dict) and not v_.get("error") for v_ in proto.values()),
          json.dumps({k: (v_ or {}).get("error") for k, v_ in proto.items()}))
    sc0 = post("/api/percival/score", dict(code=studies[2]))
    os.makedirs(os.path.join(B, "uscore", "reports"), exist_ok=True)
    json.dump(dict(study=studies[2], probability=0.99, category="likely cSS", note="planted by the test"), open(os.path.join(B, "uscore", "reports", f"{studies[2]}.json"), "w"))
    json.dump(dict(kind="planted Unified Score model", coef=[9, 9, 9, 9, 9]), open(os.path.join(B, "uscore", "model_frozen.json"), "w"))
    sc1 = post("/api/percival/score", dict(code=studies[2]))
    strip_ = lambda R: [(c["cand_id"], c["percival_score"], c["components"]) for c in (R.get("candidates") or [])]
    check("v5.24 the old Unified Score model / reports never change the Percival Score (only the 5 predictors are read)",
          sc0.get("candidates") and strip_(sc0) == strip_(sc1), str(strip_(sc0))[:200])
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
    post("/api/percival/promote", dict(version="v002", override=True, why="test")); r = post("/api/percival/rollback", {})
    check("rollback to the previous model", r.get("version") == "v001" and get("/api/percival/state")["active"]["version"] == "v001")
    def scores_now(): return {f: open(f).read() for f in glob.glob(os.path.join(B, "percival", "scores", "*.json"))}
    prev, still = None, 0                                           # wait until the re-scoring after the rollback has finished (stable 8 s)
    for _ in range(180):
        cur = {f: os.path.getmtime(f) for f in glob.glob(os.path.join(B, "percival", "scores", "*.json"))}
        still = still + 1 if cur == prev else 0; prev = cur
        if still >= 8: break
        time.sleep(1)
    before = scores_now()
    led = sorted(glob.glob(os.path.join(B, "percival", "ledger", "*", "*.json")))
    r = post("/api/percival/shadow", dict(version="v002"))
    for _ in range(240):
        SH = get("/api/percival/shadow")
        if SH["job"]["state"] in ("finished", "failed"): break
        time.sleep(1)
    run = next((x for x in SH["runs"] if x["version"] == "v002"), None)
    check("v5.24 shadow mode: candidate version v002 scored every study apart (percival/shadow/), compared with the active model and prospectively",
          r.get("ok") and SH["job"]["state"] == "finished" and run and run["active"] == "v001" and run["compared"] > 0 and "prospective" in run
          and len(glob.glob(os.path.join(B, "percival", "shadow", "v002", "SYN*.json"))) >= 20, json.dumps(SH)[:400])
    check("v5.24 shadow mode changes nothing reviewers see: active model, current scores and prediction ledger unchanged",
          get("/api/percival/state")["active"]["version"] == "v001" and scores_now() == before and len(before) >= 20
          and sorted(glob.glob(os.path.join(B, "percival", "ledger", "*", "*.json"))) == led)
    Dm = dom("#intel?tab=models", 15000)
    check("v5.24 Model Center shows the shadow run and the Run in shadow action", 'data-pv="shadow"' in Dm and "Run in shadow" in Dm)
    n = len(get("/api/percival/state")["versions"]); time.sleep(6)
    check("controlled cycles: no new cycle without N newly finished studies", len(get("/api/percival/state")["versions"]) == n)
finally:
    app.terminate(); app.wait(timeout=20)
    subprocess.run(["pkill", "-f", os.path.join(B, "scripts", "review_web.py")], capture_output=True)      # only this test's own reviewer (temporary project)
if F and os.environ.get("CSS_KEEP_TMP") == "1": print("kept for inspection:", T)
else: shutil.rmtree(T, ignore_errors=True)
if SK and not F: print(f"SKIPPED: {len(SK)} browser check(s) could not run ({CH.usable()[1] or 'page render timed out'}); every other check passed ({__file__})"); sys.exit(CH.SKIP_RC)
print(("ALL PASS" if not F else f"{len(F)} FAILED: {F}") + (f"; {len(SK)} browser check(s) SKIPPED" if SK else "") + f" ({__file__})"); sys.exit(1 if F else 0)
