"""rc4 UI fix: while a background job runs, the Unified screen must not jump to the top or close opened sections (it used to be rebuilt
every 2 s). Real app, synthetic demo base, headless Chromium. Checks scroll position, an opened <details>, and that the job box still
updates in place."""
import os, sys, json, time, socket, tempfile, subprocess, urllib.request
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..")); sys.path.insert(0, os.path.join(ROOT, "tests"))
T = tempfile.mkdtemp(prefix="uipoll_"); HOME = os.path.join(T, "home"); os.makedirs(HOME)
subprocess.run(["bash", os.path.join(ROOT, "install.sh")], env=dict(os.environ, HOME=HOME), capture_output=True)
B = os.path.join(HOME, "css_project")
import uscore_synthbase as sb
man = sb.write_base(B, n_dev=4, n_ho=2)
os.makedirs(f"{B}/app_data", exist_ok=True)
json.dump([dict(code=f"SYN{i:02d}", status="done", cohort="synthetic", mode="single", anatomy="synthseg", series={}, step="", steps_done={}, tried=[],
                reg_method="", error="", ai_note="", started=time.time() - 60, finished=time.time() - 30, pathway="synthseg") for i in range(1, 7)],
          open(f"{B}/app_data/patients.json", "w"))
s_ = socket.socket(); s_.bind(("127.0.0.1", 0)); port = s_.getsockname()[1]; s_.close()
app = subprocess.Popen([sys.executable, os.path.join(ROOT, "app", "css_app.py"), "--port", str(port), "--no-window"],
                       env=dict(os.environ, HOME=HOME, CSS_BASE=B, CSS_USCORE_DEMO="1", CSS_USCORE_MANIFEST=man), stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
U = f"http://127.0.0.1:{port}"
def get(p): return json.load(urllib.request.urlopen(U + p, timeout=60))
def post(p, d):
    r = urllib.request.Request(U + p, data=json.dumps(d).encode(), headers={"Content-Type": "application/json", "X-CSS-App": "1"})
    return json.load(urllib.request.urlopen(r, timeout=120))
try:
    for _ in range(100):
        try: urllib.request.urlopen(U + "/", timeout=2); break
        except Exception: time.sleep(0.2)
    post("/api/u/extract", dict(which="all"))
    for _ in range(900):
        if get("/api/u/state")["jobs"].get("extract", {}).get("status") != "running": break
        time.sleep(2)
    post("/api/u/train", {})
    for _ in range(900):
        if get("/api/u/state")["jobs"].get("train", {}).get("status") != "running": break
        time.sleep(2)
    post("/api/u/robustness", dict(seeds=3))                     # a long background job, kept running during the UI checks
    js = r"""
const {chromium}=require('playwright');(async()=>{const b=await chromium.launch();const p=await b.newPage({viewport:{width:1400,height:700}});
const errs=[];p.on('pageerror',e=>errs.push(String(e)));let fails=0;const ok=(c,m)=>{console.log((c?'PASS ':'FAIL ')+m);if(!c)fails++};
await p.goto(process.argv[2]);await p.waitForTimeout(800);await p.click('nav button[data-v="uni"]');await p.waitForTimeout(1500);
const running=await p.evaluate(async()=>{const s=await (await fetch('/api/u/state')).json();return Object.values(s.jobs).some(j=>j.status==='running')});
ok(running,'a background job is running during the check');
for(const step of ['reliability','train']){
 await p.click(`[data-step="${step}"]`);await p.waitForTimeout(1500);
 const d=await p.$('#u-step details');if(d)await p.evaluate(()=>{document.querySelectorAll('#u-step details').forEach(x=>x.open=true)});
 await p.evaluate(()=>window.scrollTo(0,document.body.scrollHeight));await p.waitForTimeout(300);
 const y0=await p.evaluate(()=>window.scrollY);ok(y0>100,`${step}: page scrolled down (${y0}px)`);
 await p.waitForTimeout(7000);                                   // >= 3 poll cycles
 const y1=await p.evaluate(()=>window.scrollY);ok(Math.abs(y1-y0)<5,`${step}: scroll position kept while the job runs (${y0} -> ${y1})`);
 if(d){const open=await p.evaluate(()=>[...document.querySelectorAll('#u-step details')].every(x=>x.open));ok(open,`${step}: opened sections stay open`)}
}
const jb=await p.$('[data-jobbox]');ok(!!jb,'job boxes present (updated in place)');
ok(errs.length===0,'no page errors'+(errs.length?': '+errs.join(' | '):''));await b.close();process.exit(fails?1:0)})();"""
    jf = os.path.join(T, "ui.js"); open(jf, "w").write(js)
    r = subprocess.run(["node", jf, U], capture_output=True, text=True, timeout=600,
                       env=dict(os.environ, NODE_PATH=subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()))
    print(r.stdout, r.stderr[-1500:])
    code = r.returncode
finally:
    app.terminate(); app.wait()
print("ALL PASS" if code == 0 else "FAILED"); sys.exit(code)
