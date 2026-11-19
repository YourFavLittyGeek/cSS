"""check_app_unified.py - end-to-end test of the app's Unified (experimental) section through the app's own HTTP API (the calls
the buttons make). Starts css_app.py on a temporary SYNTHETIC base (SYN studies, demo mode), never a real base.
Checks: opt-in default, cohort audit, extraction, training does not freeze, freeze needs FREEZE, scoring, per-patient background
step after 'done', fail-safe, original files unchanged, export, test protocol, no held-out route, reviewer endpoint read-only.
usage: python tests/check_app_unified.py   (exit 1 on any FAIL)"""
import os, sys, json, time, glob, socket, hashlib, shutil, tempfile, subprocess, urllib.request
H = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(H); sys.path.insert(0, H)
FAILS = []
def check(n, ok, info=""):
    print(f"{'PASS' if ok else 'FAIL'}  {n}  {info}"); (None if ok else FAILS.append(n))

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

T = tempfile.mkdtemp(prefix="uscore_app_"); HOME = os.path.join(T, "home"); os.makedirs(HOME)
subprocess.run(["bash", os.path.join(ROOT, "install.sh")], env=dict(os.environ, HOME=HOME), capture_output=True)
B = os.path.join(HOME, "css_project")
import uscore_synthbase as sb
man = sb.write_base(B, n_dev=4, n_ho=2)
os.makedirs(f"{B}/app_data", exist_ok=True)
json.dump([dict(code=f"SYN{i:02d}", status="done", cohort="synthetic", mode="single", anatomy="synthseg", series={}, step="", steps_done={}, tried=[],
                reg_method="", error="", ai_note="", started=time.time() - 60, finished=time.time() - 30, pathway="synthseg") for i in range(1, 7)],
          open(f"{B}/app_data/patients.json", "w"))
def hashes():
    fs = [f for d in ("review", "data", "work", "raw") for f in glob.glob(f"{B}/{d}/**/*", recursive=True) if os.path.isfile(f)]
    return {f: hashlib.sha256(open(f, "rb").read()).hexdigest() for f in fs}
before = hashes()
port = free_port()
env = dict(os.environ, HOME=HOME, CSS_BASE=B, CSS_USCORE_DEMO="1", CSS_USCORE_MANIFEST=man)
app = subprocess.Popen([sys.executable, os.path.join(ROOT, "app", "css_app.py"), "--port", str(port), "--no-window"], env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
U = f"http://127.0.0.1:{port}"
def get(p): return json.load(urllib.request.urlopen(U + p, timeout=60))
def post(p, d):
    r = urllib.request.Request(U + p, data=json.dumps(d).encode(), headers={"Content-Type": "application/json", "X-CSS-App": "1"})
    return json.load(urllib.request.urlopen(r, timeout=120))
def wait(job, limit=900):
    t0 = time.time()
    while time.time() - t0 < limit:
        j = get(f"/api/u/log?job={job}")
        if j["status"] != "running": return j
        time.sleep(2)
    return dict(status="timeout")
try:
    for _ in range(50):
        try: get("/api/state"); break
        except Exception: time.sleep(0.3)
    st = get("/api/u/state")
    check("unified score is OFF by default (opt-in)", st["enabled"] is False)
    check("demo mode is stamped synthetic", st["synthetic"] is True)
    check("suppression disabled", st["suppression"] is False)
    post("/api/u/audit", {}); wait("audit"); a = get("/api/u/audit")
    check("cohort audit: all checks pass, 6 studies", all(c[1] for c in a["checks"]) and len(a["studies"]) == 6)
    post("/api/u/extract", {"which": "all"}); j = wait("extract")
    check("feature extraction completes for every study", j["status"] == "completed" and len(glob.glob(f"{B}/uscore/features/*.json")) == 6, j.get("error", ""))
    r = get("/api/u/reliability"); check("reliability table per study", len(r["per_study"]) == 6)
    post("/api/u/train", {}); j = wait("train")
    check("training completes", j["status"] == "completed", j.get("error", ""))
    m = get("/api/u/state")["model"]
    check("training does NOT freeze", m["trained"] and not m["frozen"])
    v = get("/api/u/validation")
    check("validation labelled CROSS-VALIDATION, gate shown, no held-out read", v["estimate_type"].startswith("CROSS-VALIDATION") and len(v["gate"]) == 3 and v["gate"][2]["ok"])
    check("freeze refused without the typed word FREEZE", post("/api/u/freeze", {"confirm": "yes"}).get("ok") is False)
    check("freeze with FREEZE", post("/api/u/freeze", {"confirm": "FREEZE"}).get("ok") is True)
    post("/api/u/score", {}); j = wait("score"); check("score all extracted studies", j["status"] == "completed", j.get("error", ""))
    c = get("/api/u/candidates?study=SYN01")["candidates"]
    check("candidate list for a study (4 candidates, valid categories)", len(c) == 4 and all(x["category"] in ("css_compatible", "uncertain", "alternative_high_confidence") for x in c))
    post("/api/u/enable", {"on": True}); post("/api/u/score_patient", {"code": "SYN02"})
    for _ in range(120):
        p = next(x for x in get("/api/u/state")["patients"] if x["code"] == "SYN02")
        if p["unified"] in ("completed", "failed"): break
        time.sleep(1)
    check("per-patient background step: status completed, patient still done", p["unified"] == "completed" and p["status"] == "done", p.get("error", ""))
    res = get("/api/results"); r2 = next(x for x in res if x["code"] == "SYN02")
    check("results table shows unified status and counts", r2.get("unified_status") == "completed" and r2.get("unified_uncertain") is not None)
    e = post("/api/u/export", {}); check("unified Excel export written", e.get("ok") and os.path.exists(e["path"]) and e["n_candidates"] == 24, e.get("error", ""))
    pr = post("/api/u/protocol_run", {})
    auto = {i["id"]: i["result"] for i in pr["items"] if i["kind"] == "auto"}
    bad = {k: v for k, v in auto.items() if v not in ("pass",) and k not in ("T12",)}
    check("test protocol: every automatic check passes (T12 needs a robustness run)", not bad, str(bad))
    check("test protocol: fail-safe T9 and data integrity T11 pass", auto.get("T9") == "pass" and auto.get("T11") == "pass")
    check("test protocol: held-out protection T13 passes", auto.get("T13") == "pass")
    man_items = {i["id"]: i["result"] for i in pr["items"] if i["kind"] == "manual"}
    check("test protocol: manual items (T5, T14, T15) stay 'not run' after the automatic run", all(v == "not run" for v in man_items.values()), str(man_items))
    check("test protocol: an automatic result cannot be overwritten by hand", post("/api/u/protocol_mark", {"id": "T9", "result": "pass"}).get("ok") is False)
    check("test protocol: T5a is the automatic install check and T5 the separate manual viewer check",
          any(i["id"] == "T5a" and i["kind"] == "auto" and "does NOT test the viewer" in i["name"] for i in pr["items"]) and any(i["id"] == "T5" and i["kind"] == "manual" for i in pr["items"]))
    sv = post("/api/u/protocol_save", {}); check("test record saved", sv.get("ok") and os.path.exists(sv["path"]))
    check("no held-out evaluation route in the GUI", post("/api/u/heldout", {}).get("ok") is False)
    after = hashes(); changed = [os.path.relpath(f, B) for f in set(before) | set(after) if before.get(f) != after.get(f)]
    ai = [c for c in changed if c.endswith("_score_ai.json")]       # written by the app's EXISTING AI-score backfill at start (v5.14, not unified)
    other = [c for c in changed if c not in ai]
    check("original inputs and detector / reader files unchanged (review/ data/ work/ raw/; only the existing AI-score files *_score_ai.json may appear)",
          not other, f"other changes: {other[:5]}; AI-score files written by the existing backfill: {len(ai)}")
    # reviewer endpoint (read-only), started the way the app starts it
    rv = post("/api/review", {"codes": ["SYN01"], "reviewer": "Test"})
    if rv.get("ok"):
        rr = json.load(urllib.request.urlopen(rv["url"] + "api/uscore?study=SYN01&cand=1", timeout=60))
        check("reviewer serves the unified report read-only", rr.get("category") in ("css_compatible", "uncertain", "alternative_high_confidence"))
        html = urllib.request.urlopen(rv["url"], timeout=60).read().decode()
        check("reviewer: unified card is hidden in a validation read (code path present)", "hidden in a validation read 🔒 (shown after your final save)" in html)
    else: check("reviewer started by the app", False, str(rv))
    # ---- background failure modes, each with the real app restarted under a test-only setting
    before2 = hashes()       # fresh baseline: opening the reviewer above records the reviewer name in review/reviewers.json (by design)
    def restart(extra):
        global app
        try: post("/api/quit", {})
        except Exception: pass
        app.terminate(); app.wait(timeout=20)
        app = subprocess.Popen([sys.executable, os.path.join(ROOT, "app", "css_app.py"), "--port", str(port), "--no-window"], env=dict(env, **extra),
                               stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        for _ in range(60):
            try: get("/api/state"); return
            except Exception: time.sleep(0.3)
    def pstate(code): return next(x for x in get("/api/u/state")["patients"] if x["code"] == code)
    res_file = lambda: glob.glob(f"{B}/results/cSS_results.xlsx")
    # (a) injected failure
    restart({"CSS_USCORE_FAIL_TEST": "1"}); post("/api/u/score_patient", {"code": "SYN03"})
    for _ in range(60):
        p = pstate("SYN03")
        if p["unified"] in ("completed", "failed"): break
        time.sleep(0.5)
    check("background failure: unified status 'failed', patient still 'done', results workbook present", p["unified"] == "failed" and p["status"] == "done" and res_file(), p.get("error", ""))
    # (b) timeout: a hung step is stopped at the limit
    restart({"CSS_USCORE_HANG_TEST": "1", "CSS_USCORE_TIMEOUT_S": "4"}); t0 = time.time(); post("/api/u/score_patient", {"code": "SYN04"})
    for _ in range(80):
        p = pstate("SYN04")
        if p["unified"] in ("completed", "failed"): break
        time.sleep(0.5)
    check("timeout: hung unified step stopped at the limit -> 'failed' with the timeout reason; patient still 'done'",
          p["unified"] == "failed" and "no result after 4 s" in p.get("error", "") and p["status"] == "done" and time.time() - t0 < 30, f"{p.get('error', '')} ({time.time() - t0:.0f} s)")
    # (c) restart during a running unified step -> 'interrupted', never left 'running'
    post("/api/u/enable", {"on": False})   # so the start-up backfill does not queue other patients ahead: SYN05 really reaches 'running'
    restart({"CSS_USCORE_HANG_TEST": "1", "CSS_USCORE_TIMEOUT_S": "300"}); post("/api/u/score_patient", {"code": "SYN05"})
    for _ in range(40):                    # at start the app's backfill may queue other unscored patients first -> SYN05 can be 'pending'
        if pstate("SYN05")["unified"] in ("pending", "running"): break
        time.sleep(0.3)
    was = pstate("SYN05")["unified"]
    app.kill(); app.wait(timeout=20)                              # the app dies mid-step (no clean shutdown)
    subprocess.run(["pkill", "-f", "time.sleep(3600)"], capture_output=True)
    restart({}); p = pstate("SYN05")
    check("restart while a unified step is queued / running: marked 'interrupted' (never left pending / running), patient still 'done'",
          was == "running" and p["unified"] == "interrupted" and p["status"] == "done", f"before kill: {was}; after restart: {p['unified']} - {p.get('error', '')}")
    after2 = hashes(); changed2 = [os.path.relpath(f, B) for f in set(before2) | set(after2) if before2.get(f) != after2.get(f) and not f.endswith("_score_ai.json")]
    check("after failure / timeout / restart: original inputs and reader files still unchanged", not changed2, str(changed2[:5]))
finally:
    try: post("/api/quit", {})
    except Exception: pass
    app.terminate(); subprocess.run(["pkill", "-f", f"review_web.py SYN01"], capture_output=True)
    subprocess.run(["pkill", "-f", "time.sleep(3600)"], capture_output=True)
    shutil.rmtree(T, ignore_errors=True)
print(f"\napp unified: {len(FAILS)} FAIL")
sys.exit(1 if FAILS else 0)
