"""check_app_setup.py - v5.17 first-run setup wizard through the real app (temporary HOME, fake FreeSurfer installation, synthetic project):
first run detected and the wizard opens by itself; checklist separates required and optional items; FreeSurfer not assumed at a fixed
location (not found -> explained); folder and licence validation (wrong folder / malformed licence refused); installation test runs the
chosen FreeSurfer; configuration saved locally; readiness report written; finishing ends the first run (persists after a restart);
the licence CONTENT never appears in any response, settings or report.
usage: python tests/check_app_setup.py [--shots DIR]   (exit 1 on any FAIL)"""
import json, os, shutil, socket, subprocess, sys, tempfile, time, urllib.request
H = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(H); PY = sys.executable
F = []
def check(n, ok, info=""): print(f"{'PASS' if ok else 'FAIL'}  {n}  {info}"); (None if ok else F.append(n))
SHOTS = sys.argv[sys.argv.index("--shots") + 1] if "--shots" in sys.argv else None
SECRET = "LICENCE-KEY-MUST-NEVER-APPEAR-91c2"
T = tempfile.mkdtemp(prefix="setup_"); HOME = os.path.join(T, "home"); B = os.path.join(HOME, "syn_project"); FS = os.path.join(T, "Applications", "fs_custom_location")
os.makedirs(os.path.join(B, "app_data")); os.makedirs(os.path.join(FS, "bin")); os.makedirs(os.path.join(T, "notfs"))
with open(os.path.join(FS, "build-stamp.txt"), "w") as f: f.write("freesurfer-macOS-darwin_arm64-8.2.0-SYNTHETIC-TEST\n")
for t in ("mri_synthseg", "mri_synthstrip", "mri_convert", "mri_vol2vol", "mri_coreg", "recon-all", "bbregister", "freeview"):
    p = os.path.join(FS, "bin", t)
    with open(p, "w") as f: f.write("#!/bin/sh\necho 'mri_convert freesurfer 8.2.0 (synthetic test stub)'\nexit 0\n")
    os.chmod(p, 0o755)
LIC = os.path.join(T, "license.txt"); BAD = os.path.join(T, "notes.txt")
with open(LIC, "w") as f: f.write(f"synthetic.user@example.org\n12345\n *{SECRET}\n FSabcdEFGH\n")
with open(BAD, "w") as f: f.write("just a note\n")
SEEN = []
def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
def start():
    port = free_port(); env = {k: v for k, v in os.environ.items() if k not in ("FREESURFER_HOME", "FS_LICENSE", "SUBJECTS_DIR")}
    env.update(HOME=HOME, CSS_BASE=B, CSS_EXPERIMENTAL="1", PYTHONPATH=os.path.join(ROOT, "app", "guard"), PATH="/usr/bin:/bin:" + os.path.dirname(PY),
               CSS_PROTECTED_PATHS=":".join([os.path.expanduser("~/css_project"), os.path.expanduser("~/cSS_experimental")]))
    p = subprocess.Popen([PY, os.path.join(ROOT, "app", "css_app.py"), "--port", str(port), "--no-window"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    U = f"http://127.0.0.1:{port}"
    for _ in range(80):
        try: urllib.request.urlopen(U + "/api/state", timeout=2); return p, U
        except Exception: time.sleep(0.25)
    return p, U
def get(U, p): r = urllib.request.urlopen(U + p, timeout=120).read().decode(); SEEN.append(r); return json.loads(r)
def post(U, p, d):
    rq = urllib.request.Request(U + p, data=json.dumps(d).encode(), headers={"Content-Type": "application/json", "X-CSS-App": "1"})
    r = urllib.request.urlopen(rq, timeout=120).read().decode(); SEEN.append(r); return json.loads(r)
chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
def dom(U, url): return subprocess.run([chrome, "--headless=new", "--disable-gpu", f"--user-data-dir={os.path.join(T, 'chrome')}", "--virtual-time-budget=9000", "--dump-dom", f"{U}/{url}"],
                                       capture_output=True, text=True, timeout=120).stdout if os.path.exists(chrome) else None
app, U = start()
try:
    st = get(U, "/api/setup/state"); it = {i["id"]: i for i in st["items"]}
    check("first run detected", st["first_run"] is True)
    check("checklist: required and optional items, grouped", any(i["required"] for i in st["items"]) and any(not i["required"] for i in st["items"]) and {"System", "FreeSurfer", "Optional"} <= {i["group"] for i in st["items"]})
    check("FreeSurfer not assumed at a fixed location: not found, explained", it["freesurfer"]["ok"] is False and "no FreeSurfer folder" in it["freesurfer"]["detail"])
    check("licence not found, explained", it["license"]["ok"] is False)
    D = dom(U, "")
    if D is not None: check("browser: the wizard opens by itself on the first start", 'data-su="banner"' in D and "first-run setup" in D)
    r = post(U, "/api/setup/validate_fs", dict(path=os.path.join(T, "notfs"))); check("a folder that is not FreeSurfer is refused with the reason", r["ok"] is False and "not a usable FreeSurfer" in r["error"])
    r = post(U, "/api/setup/validate_fs", dict(path=FS)); check("FreeSurfer folder validated (version read)", r["ok"] and "8.2.0" in r["version"] and r["tools"]["mri_synthseg"])
    r = post(U, "/api/setup/validate_license", dict(path=BAD)); check("a malformed licence is refused", r["ok"] is False and "does not look like" in r["error"])
    r = post(U, "/api/setup/validate_license", dict(path=LIC)); check("licence validated without returning its content", r["ok"] and SECRET not in json.dumps(r))
    r = post(U, "/api/setup/test", dict(home=FS, license=LIC)); check("installation test runs the chosen FreeSurfer", r["ok"] and "8.2.0" in r["version_line"], str(r))
    r = post(U, "/api/setup/save", dict(home=os.path.join(T, "notfs"), license=LIC)); check("saving an invalid folder is refused", r["ok"] is False)
    r = post(U, "/api/setup/save", dict(home=FS, license=LIC)); check("configuration saved", r["ok"] and r["saved"]["freesurfer_home"] == FS)
    with open(os.path.join(B, "app_data", "settings.json")) as f: sset = f.read()
    check("settings hold the paths, never the licence content", FS in sset and SECRET not in sset)
    st = get(U, "/api/setup/state"); it = {i["id"]: i for i in st["items"]}
    check("after saving: FreeSurfer and licence ready", it["freesurfer"]["ok"] and it["license"]["ok"] and "contents not shown" in it["license"]["detail"])
    rep = st["report"]; check("readiness report: ready = every required item ok", rep["ready"] == all(i["ok"] for i in st["items"] if i["required"]) and rep["required_total"] >= 8)
    with open(os.path.join(B, "app_data", "setup_report.json")) as f: rp = f.read()
    check("report written locally without the licence content", SECRET not in rp and '"ready"' in rp)
    if SHOTS and os.path.exists(chrome):
        os.makedirs(SHOTS, exist_ok=True)
        for name in ("setup",):
            subprocess.run([chrome, "--headless=new", "--disable-gpu", f"--user-data-dir={os.path.join(T, 'chrome_s')}", "--hide-scrollbars", "--window-size=1500,1500", "--virtual-time-budget=9000",
                            f"--screenshot={os.path.join(SHOTS, 'setup_wizard.png')}", f"{U}/#setup"], capture_output=True, timeout=120)
    r = post(U, "/api/setup/finish", {}); check("finish: setup recorded", r["ok"] and os.path.exists(os.path.join(B, "app_data", "setup_done.json")))
finally:
    app.terminate(); app.wait(timeout=20)
app, U = start()
try:
    check("after a restart the first run is over", get(U, "/api/setup/first_run")["first_run"] is False)
    D = dom(U, "")
    if D is not None: check("browser: the app opens normally (no wizard) after setup", 'data-su="banner"' not in D)
    check("settings screen offers the wizard again", 'data-setup="settings"' in urllib.request.urlopen(U + "/", timeout=30).read().decode())
finally:
    app.terminate(); app.wait(timeout=20)
check("the licence content never appeared in any response", not any(SECRET in s for s in SEEN))
shutil.rmtree(T, ignore_errors=True)
print(("ALL PASS" if not F else f"{len(F)} FAILED: {F}") + f" ({__file__})"); sys.exit(1 if F else 0)
