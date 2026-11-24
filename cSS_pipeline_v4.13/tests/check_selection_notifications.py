"""rc4: user study selection, training gate, calls-changed detection, recommendations, auto-train, notification centre.
Real app, synthetic demo base (SYN studies), real training code. Writes GUI screenshots to SHOTS if given."""
import os, sys, json, time, glob, socket, tempfile, subprocess, urllib.request
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..")); sys.path.insert(0, os.path.join(ROOT, "tests"))
SHOTS = sys.argv[1] if len(sys.argv) > 1 else ""
F = []
def ok(c, m): print(("PASS " if c else "FAIL ") + m, flush=True); c or F.append(m)
T = tempfile.mkdtemp(prefix="selnot_"); HOME = os.path.join(T, "home"); os.makedirs(HOME)
subprocess.run(["bash", os.path.join(ROOT, "install.sh")], env=dict(os.environ, HOME=HOME), capture_output=True)
B = os.path.join(HOME, "css_project")
import uscore_synthbase as sb
man = sb.write_base(B, n_dev=5, n_ho=2)
os.makedirs(f"{B}/app_data", exist_ok=True)
json.dump([dict(code=f"SYN{i:02d}", status="done", cohort="synthetic-a" if i <= 4 else "synthetic-b", mode="single", anatomy="synthseg", series={}, step="",
                steps_done={}, tried=[], reg_method="", error="", ai_note="", started=time.time() - 60, finished=time.time() - 30, pathway="synthseg") for i in range(1, 8)],
          open(f"{B}/app_data/patients.json", "w"))
s_ = socket.socket(); s_.bind(("127.0.0.1", 0)); port = s_.getsockname()[1]; s_.close()
app = subprocess.Popen([sys.executable, os.path.join(ROOT, "app", "css_app.py"), "--port", str(port), "--no-window"],
                       env=dict(os.environ, HOME=HOME, CSS_BASE=B, CSS_USCORE_DEMO="1", CSS_USCORE_MANIFEST=man, CSS_WATCH_S="2", CSS_AUTOTRAIN_GAP_S="0"),
                       stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
U = f"http://127.0.0.1:{port}"
def get(p): return json.load(urllib.request.urlopen(U + p, timeout=120))
def post(p, d):
    r = urllib.request.Request(U + p, data=json.dumps(d).encode(), headers={"Content-Type": "application/json", "X-CSS-App": "1"})
    return json.load(urllib.request.urlopen(r, timeout=300))
def wait_job(name, limit=1800):
    for _ in range(limit // 2):
        j = get("/api/u/state")["jobs"].get(name, {})
        if j.get("status") not in ("running",): return j
        time.sleep(2)
    return {}
def notifs(): return get("/api/notif/list")
def until(fn, limit=60):
    t0 = time.time()
    while time.time() - t0 < limit:
        r = fn()
        if r: return r
        time.sleep(1)
    return None
try:
    for _ in range(100):
        try: urllib.request.urlopen(U + "/", timeout=2); break
        except Exception: time.sleep(0.2)
    st = get("/api/sel/status"); roles = {r["study"]: r["role"] for r in st["rows"]}
    ok(len(st["rows"]) == 7 and list(roles.values()).count("train") == 5 and list(roles.values()).count("test") == 2, f"status lists the studies with manifest roles ({roles})")
    ok(st["gate"].get("configured") is False and st["gate"]["open"], "gate not configured yet: shown as open (legacy), not silently closed")
    # gate closed -> training refused (central check in the training code)
    ok(post("/api/sel/gate", dict(open=False, by="tester"))["gate"]["open"] is False, "gate closed")
    post("/api/u/extract", dict(which="all")); wait_job("extract")
    r = post("/api/u/train", {})                                    # I0: in-app uScore training is disabled (no provenance safeguards)
    ok(r.get("ok") is False and r.get("disabled") is True, "uScore training refused in the app while the gate is closed (training disabled)")
    # apply validation
    r = post("/api/sel/apply", dict(changes={"SYN03": {"role": "exclude"}})); ok(not r["ok"] and any("reason" in e for e in r["errors"]), "exclude without a reason refused")
    r = post("/api/sel/apply", dict(changes={"SYN02": {"patient": "PT-1"}, "SYN06": {"patient": "PT-1"}}))
    ok(not r["ok"] and any("both sides" in e for e in r["errors"]), "same patient on Train and Test refused")
    ok(not os.path.exists(f"{B}/app_data/split/current.json"), "refused applies write nothing")
    r = post("/api/sel/apply", dict(changes={"SYN05": {"role": "hold", "reason": "reads unfinished"}, "SYN02": {"patient": "PT-1"}, "SYN06": {"patient": "PT-2"}}, note="test v1"))
    ok(r["ok"] and r["version"] == 1, "valid selection applied as version 1")
    r2 = post("/api/sel/apply", dict(changes={"SYN05": {"role": "train"}})); ok(r2["ok"] and r2["version"] == 2, "second change = version 2 (v1 kept)")
    ok(os.path.exists(f"{B}/app_data/split/v1.json") and os.path.exists(f"{B}/app_data/split/v2.json"), "every version kept on disk")
    rr = post("/api/sel/restore", dict(version=1)); ok(rr["ok"] and rr["version"] == 3 and json.load(open(f"{B}/app_data/split/current.json"))["roles"]["SYN05"] == "hold", "restore v1 creates v3 with v1's roles")
    # training with the gate open uses the user's selection
    post("/api/sel/gate", dict(open=True, by="tester")); r = post("/api/u/train", {})
    ok(r.get("ok") is False and r.get("disabled") is True and not os.path.exists(f"{B}/uscore/model_trained.json"),
       "gate open: in-app uScore training still refused, nothing written")
    # the calls-changed flow below needs a trained model: explicit, stamped SYNTHETIC research run through the CLI (never from the app)
    p_ = subprocess.run([sys.executable, os.path.join(ROOT, "unified_score", "run_unified.py"), "train", "--research-unverified"], capture_output=True, text=True,
                        env=dict(os.environ, HOME=HOME, CSS_BASE=B, CSS_USCORE_DEMO="1", CSS_USCORE_MANIFEST=man), timeout=1800)
    M = json.load(open(f"{B}/uscore/model_trained.json")) if os.path.exists(f"{B}/uscore/model_trained.json") else {}
    ok(p_.returncode == 0 and M.get("research_only_unverified") is True and set(M.get("label_fingerprints", {})) == set(M.get("train_studies", [])),
       "research run (CLI, flagged): model stamped research_only_unverified; fingerprints recorded for every training study")
    ok(not [i for i in notifs()["items"] if i["title"] == "Trained model ready"], "no 'trained model ready' notification from the app (it trained nothing)")
    # calls changed after training -> label + urgent notification; hold resolves it
    cf = f"{B}/review/SYN01_calls.csv"; open(cf, "a").write(open(cf).read().splitlines()[-1] + "\n")
    st = get("/api/sel/status"); r1 = next(r for r in st["rows"] if r["study"] == "SYN01")
    ok(any(l["kind"] == "stale" for l in r1["labels"]), "calls changed after training: study labelled")
    n = until(lambda: [i for i in notifs()["items"] if i.get("key") == "stale:SYN01" and i["level"] == "urgent"], 30)
    ok(bool(n), "urgent notification: calls changed after training")
    nid = n[0]["id"] if n else ""
    post("/api/notif/act", dict(id=nid, op="snooze", minutes=0.05)); ok(not any(i["id"] == nid for i in notifs()["items"]), "snoozed item hidden")
    ok(bool(until(lambda: any(i["id"] == nid for i in notifs()["items"]), 20)), "snoozed item returns after its time")
    post("/api/sel/apply", dict(changes={"SYN01": {"role": "hold", "reason": "calls changed after training"}}))
    ok(bool(until(lambda: not any(i.get("key") == "stale:SYN01" for i in notifs()["items"]), 30)), "putting the study on hold resolves the urgent notification")
    # recommendations
    q = f"{B}/review/SYN03_qc.json"; d = json.load(open(q)) if os.path.exists(q) else {}; d["registration_ok"] = False; json.dump(d, open(q, "w"))
    r3 = next(r for r in get("/api/sel/status")["rows"] if r["study"] == "SYN03")
    ok(r3["recommendation"] and r3["recommendation"]["kind"] == "exclude" and "registration" in r3["recommendation"]["why"] and r3["role"] == "train",
       "registration rejected: Exclude recommended, NOT applied by itself")
    # remove
    it = notifs()["items"][0]; post("/api/notif/act", dict(id=it["id"], op="remove")); ok(not any(i["id"] == it["id"] for i in notifs()["items"]), "removed item leaves the centre")
    ok(any(i["id"] == it["id"] and i["removed"] for i in get("/api/notif/log")["log"]), "removed item kept in the log")
    # settings
    post("/api/notif/settings", dict(snooze_min=15, banner="off")); ok(notifs()["settings"]["snooze_min"] == 15, "notification settings saved (snooze 15 min)")
    # auto-train
    post("/api/sel/autotrain", dict(on=True, threshold=1)); time.sleep(1)
    cf = f"{B}/review/SYN02_calls.csv"; open(cf, "a").write(open(cf).read().splitlines()[-1] + "\n")
    ok(bool(until(lambda: [i for i in notifs()["items"] + get("/api/notif/log")["log"] if i["title"] == "uScore auto-train is disabled"], 40))
       and not [i for i in notifs()["items"] + get("/api/notif/log")["log"] if i["title"] == "Auto-train started"],
       "auto-train trigger: reports that uScore training is disabled, never 'Auto-train started'")
    post("/api/sel/autotrain", dict(on=False, threshold=3))
    if SHOTS:
        js = r"""const {chromium}=require('playwright');const [U,O]=process.argv.slice(2);(async()=>{const b=await chromium.launch();const errs=[];
const p=await b.newPage({viewport:{width:1440,height:900},deviceScaleFactor:1});p.on('pageerror',e=>errs.push(String(e)));
await p.goto(U);await p.waitForTimeout(1500);await p.screenshot({path:O+'/S01_header.png',clip:{x:0,y:0,width:1440,height:120}});
await p.click('nav button[data-v="uni"]');await p.waitForTimeout(2500);await p.screenshot({path:O+'/S02_study_selection.png',fullPage:true});
await p.click('#bell');await p.waitForTimeout(800);await p.screenshot({path:O+'/S03_notification_centre.png'});await p.click('#nclose');
await p.click('nav button[data-v="set"]');await p.waitForTimeout(1200);await p.screenshot({path:O+'/S04_settings.png',fullPage:true});
const w=await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth);console.log(errs.length?'FAIL page errors: '+errs.join('|'):'PASS no page errors');console.log(w?'PASS no horizontal overflow':'FAIL horizontal overflow');
for(const vw of [1024,1280]){const q=await b.newPage({viewport:{width:vw,height:800}});await q.goto(U);await q.waitForTimeout(1200);await q.click('nav button[data-v="uni"]');await q.waitForTimeout(2000);
 const f=await q.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1);console.log((f?'PASS':'FAIL')+' study selection fits at '+vw+' px');await q.close()}
await b.close()})();"""
        jf = os.path.join(T, "s.js"); open(jf, "w").write(js)
        r = subprocess.run(["node", jf, U, SHOTS], capture_output=True, text=True, timeout=300,
                           env=dict(os.environ, NODE_PATH=subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()))
        for ln in r.stdout.splitlines():
            if ln.startswith(("PASS", "FAIL")): ok(ln.startswith("PASS"), ln[5:])
        if r.returncode: print(r.stderr[-800:])
finally: app.terminate(); app.wait()
print("ALL PASS" if not F else f"{len(F)} FAILED"); sys.exit(1 if F else 0)
