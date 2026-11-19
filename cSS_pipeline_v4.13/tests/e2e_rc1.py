"""End-to-end check of the experimental app bundle on SYNTHETIC data (Linux stand-in for the Mac; no real data, no network).
1. builds the bundle (tools/build_experimental_app.sh) and unzips it into a sandbox HOME/Applications
2. makes a fake "production" project HOME/css_project (synthetic SYN studies: one with T1 + FreeSurfer-like recon, two SWI-only,
   earlier candidates + reader calls), fake conda, then starts the app with the bundle's OWN launcher (HOME/cSS_experimental, port 8810)
3. drives the GUI with Playwright (tests/e2e_rc1_gui.js): Processing tab, bring studies in, confirm, new detection run with the REAL
   detector, history, Results, reviewer + 3-D panel, export refusal / dialog; screenshots -> docs/gui_v514/rc1/
4. restart during a run -> interrupted + restored; checks: source project unchanged, linked FreeSurfer unwritten, no network attempts.
usage: python3 tests/e2e_rc1.py [SHOT_DIR]"""
import os, sys, json, glob, time, shutil, hashlib, socket, subprocess, tempfile, urllib.request, zipfile
import numpy as np, nibabel as nib
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..")); sys.path.insert(0, os.path.join(ROOT, "tests"))
SHOTS = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs", "gui_v514", "rc1"))
os.makedirs(SHOTS, exist_ok=True); F = []; LOG = []
def ok(c, m):
    line = ("PASS " if c else "FAIL ") + m; print(line, flush=True); LOG.append(line); c or F.append(m)
subprocess.run(["pkill", "-f", "cSS_experimental/app/css_app.py"]); subprocess.run(["pkill", "-f", "cSS_experimental/scripts/review_web.py"]); time.sleep(1)
H = tempfile.mkdtemp(prefix="rc1home_"); DIST = os.path.join(H, "dist"); PROD = os.path.join(H, "css_project"); EXP = os.path.join(H, "cSS_experimental")
# 1 build + "install" (unzip into Applications)
r = subprocess.run(["bash", os.path.join(ROOT, "tools", "build_experimental_app.sh"), DIST], capture_output=True, text=True)
ok(r.returncode == 0, "bundle built: " + r.stdout.strip().splitlines()[0] if r.stdout else r.stderr[-300:])
zp = glob.glob(f"{DIST}/cSS_Experimental_*.zip")[0]; os.makedirs(f"{H}/Applications")
with zipfile.ZipFile(zp) as z: z.extractall(f"{H}/Applications")
L = f"{H}/Applications/cSS Experimental.app/Contents/MacOS/cSS Experimental"; os.chmod(L, 0o755)
ok(os.path.exists(L), "app unzipped into Applications")
# 2 fake production project
import uscore_synthbase as sb
sb.write_base(PROD, n_dev=2, n_ho=1)
for s in ("SYN02", "SYN03"):
    os.makedirs(f"{PROD}/synthseg", exist_ok=True); shutil.copy(f"{PROD}/work/{s}_seg_swispace.nii.gz", f"{PROD}/synthseg/{s}_seg.nii.gz")
# SYN04 = SYN02 at 2.4 mm slices (thick-slice acquisition: thin structures become acquisition-limited in the 3-D view)
for src, dst, interp in ((f"data/SYN02_swi.nii", "data/SYN04_swi.nii", 1), ("work/SYN02_seg_swispace.nii.gz", "work/SYN04_seg_swispace.nii.gz", 0), ("synthseg/SYN02_seg.nii.gz", "synthseg/SYN04_seg.nii.gz", 0)):
    im = nib.load(f"{PROD}/{src}"); a = np.asarray(im.dataobj); n = a.shape[2] // 4 * 4; a = a[:, :, :n]
    b = a.reshape(a.shape[0], a.shape[1], -1, 4).mean(3).astype(a.dtype) if interp else a[:, :, 1::4]
    A = im.affine.copy(); A[:, 2] *= 4; nib.save(nib.Nifti1Image(b, A), f"{PROD}/{dst}")
swi = nib.load(f"{PROD}/data/SYN01_swi.nii")
nib.save(nib.Nifti1Image(np.asarray(swi.dataobj, np.float32), swi.affine), f"{PROD}/data/SYN01_t1.nii.gz")
fs = f"{PROD}/subjects/SYN01"
for n in ("aparc.a2009s+aseg", "orig", "brain"):
    os.makedirs(f"{fs}/mri", exist_ok=True); nib.save(nib.MGHImage(np.ones((8, 8, 8), np.float32), np.eye(4)), f"{fs}/mri/{n}.mgz")
os.makedirs(f"{fs}/scripts"); open(f"{fs}/scripts/build-stamp.txt", "w").write("freesurfer-macOS-darwin_arm64-8.2.0 (synthetic stand-in)\n")
open(f"{fs}/scripts/recon-all.cmd", "w").write("recon-all -s SYN01 -all -no-v8\n")
open(f"{PROD}/work/SYN01_swi2t1.lta", "w").write("type = 1 # LINEAR_RAS_TO_RAS\n1 4 4\n1 0 0 0\n0 1 0 0\n0 0 1 0\n0 0 0 1\n")
json.dump({"method": "bbregister", "status": "ok"}, open(f"{PROD}/work/SYN01_reg.json", "w"))
open(f"{PROD}/review/SYN01_review_log.csv", "w").write("time,reader,cand_id,call\n")
def tree(B): return {p: (hashlib.sha256(open(p, "rb").read()).hexdigest(), os.stat(p).st_mtime) for p in glob.glob(f"{B}/**/*", recursive=True) if os.path.isfile(p)}
prod_before = tree(PROD)
# fake conda (the real one lives on the Mac); network guard for every Python process the app starts
os.makedirs(f"{H}/miniforge3/etc/profile.d"); open(f"{H}/miniforge3/etc/profile.d/conda.sh", "w").write("conda(){ return 0; }\n")
NETLOG = os.path.join(H, "netguard.log")
ENV = dict(os.environ, HOME=H, PYTHONPATH=os.path.join(ROOT, "tests", "netguard"), CSS_NETGUARD_LOG=NETLOG, PATH=os.environ["PATH"])
ENV.pop("CSS_BASE", None)
def launch():
    subprocess.run(["bash", L], env=ENV, timeout=120)
    for _ in range(150):
        try: urllib.request.urlopen("http://127.0.0.1:8810/", timeout=2); return True
        except Exception: time.sleep(0.2)
    return False
def kill():
    subprocess.run(["pkill", "-f", f"{EXP}/app/css_app.py"]); time.sleep(1.5)
ok(launch(), "launcher started the app on port 8810 (separate from production 8800)")
pid = subprocess.run(["pgrep", "-f", f"{EXP}/app/css_app.py"], capture_output=True, text=True).stdout.split()
envs = open(f"/proc/{pid[0]}/environ", "rb").read().decode(errors="replace").split("\0") if pid else []
ok("CSS_EXPERIMENTAL=1" in envs and any(e.startswith("PYTHONPATH=") and "/app/guard" in e for e in envs), "running app has the production write guard active (CSS_EXPERIMENTAL=1, guard on PYTHONPATH)")
ok(os.path.exists(f"{EXP}/scripts/detect_css.py") and "experimental app build" in open(f"{EXP}/scripts/BUILD").read(), "launcher installed the bundled pipeline into ~/cSS_experimental with its build stamp")
ok(not os.path.exists(f"{PROD}/app") and not os.path.exists(f"{PROD}/app_data"), "production project folder not used by the experimental app")
# production-folder guard
r = subprocess.run(["bash", L], env=dict(ENV, CSS_EXP_BASE=PROD), timeout=60)
ok(r.returncode != 0, "launcher refuses the production project folder as its project")
# 3 GUI
g = subprocess.run(["node", os.path.join(ROOT, "tests", "e2e_rc1_gui.js"), PROD, SHOTS], env=dict(os.environ, NODE_PATH=subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()),
                   capture_output=True, text=True, timeout=1800)
print(g.stdout[-4000:], g.stderr[-2000:])
for ln in g.stdout.splitlines():
    if ln.startswith(("PASS ", "FAIL ")): (LOG.append(ln), F.append(ln[5:])) if ln.startswith("FAIL") else LOG.append(ln)
ok(g.returncode == 0, "GUI walkthrough finished")
U = "http://127.0.0.1:8810"; get = lambda p: json.load(urllib.request.urlopen(U + p, timeout=60))
h = get("/api/proc/history?code=SYN02")["runs"]
ok(any(m["status"] == "completed" and "detect" in m.get("run", []) for m in h), "SYN02: completed new detection run recorded")
ok(len(glob.glob(f"{EXP}/runs/SYN02/*/files/review/SYN02_candidates.csv")) >= 2, "old and new candidate lists both archived")
aj = json.load(open(f"{EXP}/review/SYN02_score_ai.json")); ok("error" not in aj and aj.get("multifocality_0_4") is not None, "AI score of the new candidates written without error")
uj = json.load(open(f"{EXP}/uscore/reports/SYN02.json")); ok(os.path.getmtime(f"{EXP}/uscore/reports/SYN02.json") >= os.path.getmtime(f"{EXP}/review/SYN02_candidates.csv"), "unified report regenerated after the new detection")
# 4 restart during a run
def post(p, d):
    rq = urllib.request.Request(U + p, data=json.dumps(d).encode(), headers={"Content-Type": "application/json", "X-CSS-App": "1"})
    return json.load(urllib.request.urlopen(rq, timeout=60))
before = open(f"{EXP}/review/SYN03_candidates.csv").read()
post("/api/proc/adopt", dict(code="SYN03"))
r = post("/api/proc/start", dict(code="SYN03", choice="selective", rerun_from="detect")); time.sleep(2.5)
ok(r.get("ok"), "SYN03 run started for the restart test" + ("" if r.get("ok") else ": " + str(r.get("error"))))
kill(); ok(launch(), "app restarted after being closed mid-run")
h = get("/api/proc/history?code=SYN03")
ok(h["runs"][-1]["status"] == "interrupted", "cut-off run marked interrupted (never left running)")
ok(open(f"{EXP}/review/SYN03_candidates.csv").read() == before, "previous SYN03 candidates restored after the interruption")
kill(); subprocess.run(["pkill", "-f", f"{EXP}/scripts/review_web.py"])
# integrity + network
ok(tree(PROD) == prod_before, "production project unchanged: every file (content and modification time), FreeSurfer included")
ok(os.path.isdir(f"{EXP}/subjects/SYN01") and not os.path.islink(f"{EXP}/subjects/SYN01") and not os.path.exists(f"{fs}/.css_input.json"), "FreeSurfer imported as an isolated copy (rc2), nothing written into the original")
ok(json.load(open(f"{EXP}/runs/SYN01/import.json"))["verified"] is True, "import verified (sha256, source unchanged)")
net = open(NETLOG).read().strip() if os.path.exists(NETLOG) else ""
ok(net == "", "no process attempted a non-loopback network connection" + (f": {net[:200]}" if net else ""))
open(os.path.join(SHOTS, "E2E_RC1_RESULT.txt"), "w").write("\n".join(LOG) + f"\n\n{'ALL PASS' if not F else str(len(F)) + ' FAILED'}\nsandbox: {H}\n")
print("ALL PASS" if not F else f"{len(F)} FAILED: {F}"); sys.exit(1 if F else 0)
