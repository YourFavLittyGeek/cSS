"""Previous Processing Manager: synthetic study, real tiny NIfTI / MGZ files, stub FreeSurfer tree, stub pipeline scripts.
No real data. Covers: detection of earlier outputs, the six categories, adoption, plans and dependencies, FreeSurfer reuse,
non-destructive runs, active-run switching, failure restore, interruption recovery, resume, the app routes."""
import os, sys, json, glob, socket, tempfile, hashlib, subprocess, time, urllib.request
import numpy as np, nibabel as nib
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "app"))
import processing_manager as pm
F = []
def ok(c, m): print(("PASS " if c else "FAIL ") + m); c or F.append(m)
def w(p, b=b"x"):
    os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "wb").write(b)
def nii(p, val=1.0, shape=(8, 8, 4), zooms=(0.5, 0.5, 2.0)):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    img = (nib.MGHImage if p.endswith(".mgz") else nib.Nifti1Image)(np.full(shape, val, np.float32), np.diag(list(zooms) + [1]))
    if not p.endswith(".mgz"): img.header.set_zooms(zooms)
    nib.save(img, p)
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()

B = tempfile.mkdtemp(); S = "SYN90"; fs = f"{B}/subjects/{S}"
nii(f"{B}/data/{S}_swi.nii", 1.0); nii(f"{B}/data/{S}_t1.nii.gz", 2.0, (6, 6, 6), (1, 1, 1))
for n in ("aparc.a2009s+aseg", "orig", "brain"): nii(f"{fs}/mri/{n}.mgz", 3.0, (6, 6, 6), (1, 1, 1))
w(f"{fs}/surf/lh.pial", b"surface"); w(f"{fs}/scripts/build-stamp.txt", b"freesurfer-macOS-darwin_arm64-8.2.0-20250101")
w(f"{fs}/scripts/recon-all.cmd", b"recon-all -s SYN90 -all -no-v8")
w(f"{B}/work/{S}_swi2t1.lta", b"type = 1 # LINEAR_RAS_TO_RAS\n1 4 4\n"); w(f"{B}/work/{S}_reg.json", b"{}")
nii(f"{B}/work/{S}_seg_swispace.nii.gz", 4.0)
w(f"{B}/review/{S}_candidates.csv", b"cand_id,score\n1,0.5\n"); nii(f"{B}/review/{S}_candidates.nii.gz", 1.0); w(f"{B}/review/{S}_qc.json", b'{"status":"ok"}')
w(f"{B}/review/{S}_manifest.json", json.dumps({"detect": {"pipeline_version": "v5.11", "inputs": {f"data/{S}_swi.nii": sha(f"{B}/data/{S}_swi.nii")}}}).encode())
w(f"{B}/review/{S}_calls.csv", b"cand_id,call\n1,cSS\n")
reader0 = open(f"{B}/review/{S}_calls.csv", "rb").read(); fsmark = os.stat(f"{fs}/mri/orig.mgz").st_ino

st = pm.Study(B, S); A = st.audit(); a = A["stages"]
ok(pm.studies_on_disk(B) == [S], "study found on disk without any app record (terminal-era layout)")
ok(A["identity"]["swi"]["dims"] == [8, 8, 4] and A["identity"]["swi"]["voxel_mm"] == [0.5, 0.5, 2.0] and A["identity"]["swi"]["orientation"] == "RAS",
   "MRI identity: hash, dimensions, voxel size, orientation")
ok("8.2.0" in A["identity"]["freesurfer"]["version"] and A["identity"]["freesurfer"]["no_v8"] is True, "FreeSurfer version and -no-v8 recorded")
ok(A["identity"]["detection"]["pipeline_version"] == "v5.11", "previous detection version recorded")
ok(a["anatomy"]["kind"] == "freesurfer" and a["anatomy"]["status"] == pm.UNKNOWN, "complete FreeSurfer with no T1 record: 'unknown' (not silently compatible)")
ok(a["detect"]["status"] in (pm.COMPAT, pm.UNKNOWN), "detection outputs found, manifest input hashes match")
ok(st.plan("selective", "detect").get("needs_adopt"), "no run can start before the user confirms (adopts) the earlier outputs")
st.adopt_existing(); a = st.audit()["stages"]
ok(all(a[s]["status"] == pm.COMPAT for s in ("anatomy", "registration", "align", "detect")), "after adoption the present stages are compatible")
ok(a["unified"]["status"] == pm.MISSING, "missing unified output reported as missing")
p = st.plan("selective", "anatomy"); ok(not p["ok"] and p.get("needs_confirm"), "FreeSurfer not re-run when complete and compatible (needs confirmation)")
p = st.plan("selective"); ok(p["ok"] and p["run"] == ["unified"] and "anatomy" in p["reuse"], "selective plan reuses FreeSurfer, runs only the missing stage")
p = st.plan("selective", "detect"); ok(p["run"] == ["detect", "unified"], "fresh detection: detect re-run includes unified (dependency)")
# categories
os.remove(f"{fs}/surf/lh.pial"); ok(st.audit()["stages"]["anatomy"]["status"] == pm.LIMITED, "FreeSurfer without surfaces: compatible with limitations")
w(f"{fs}/surf/lh.pial", b"surface")
w(f"{B}/review/{S}_qc.json", b'{"status":"low_confidence_review"}'); ok(st.audit()["stages"]["detect"]["status"] == pm.LIMITED, "low-confidence QC: detection compatible with limitations")
w(f"{B}/review/{S}_qc.json", b'{"status":"ok"}')
good = open(f"{B}/review/{S}_candidates.nii.gz", "rb").read(); w(f"{B}/review/{S}_candidates.nii.gz", good[:len(good) // 2])
ok(st.audit()["stages"]["detect"]["status"] == pm.CORRUPT, "truncated candidate mask: corrupted")
w(f"{B}/review/{S}_candidates.nii.gz", good)
nii(f"{B}/data/{S}_swi.nii", 9.0); a = st.audit()["stages"]
ok(a["detect"]["status"] == pm.INCOMPAT and a["unified"]["status"] in (pm.MISSING, pm.UPSTREAM), "a different SWI: detection incompatible, later stages not reusable")
ok(not st.plan("reuse")["ok"], "full reuse refused after the MRI changed")
nii(f"{B}/data/{S}_swi.nii", 1.0); os.utime(f"{B}/data/{S}_swi.nii")
w(f"{B}/review/{S}_manifest.json", json.dumps({"detect": {"pipeline_version": "v5.11", "inputs": {f"data/{S}_swi.nii": sha(f"{B}/data/{S}_swi.nii")}}}).encode())
nii(f"{B}/data/{S}_t1.nii.gz", 7.0, (6, 6, 6), (1, 1, 1)); ok(st.audit()["stages"]["anatomy"]["status"] == pm.INCOMPAT, "FreeSurfer from another T1: incompatible")
nii(f"{B}/data/{S}_t1.nii.gz", 2.0, (6, 6, 6), (1, 1, 1))
# the adoption recorded the T1 hash; the rewritten (identical-content) T1 must still match
ok(st.audit()["stages"]["anatomy"]["status"] == pm.COMPAT, "same T1 content: compatible again")
os.rename(f"{fs}/mri/brain.mgz", f"{fs}/mri/brain.bak"); ok(st.audit()["stages"]["anatomy"]["status"] == pm.INCOMPLETE, "unfinished FreeSurfer: incomplete")
os.rename(f"{fs}/mri/brain.bak", f"{fs}/mri/brain.mgz")

# ---- library-level run bookkeeping ----
r1 = st.active_manifest()["run_id"]
m = st.start_run(st.plan("selective", "detect"), "detect rerun"); w(f"{B}/review/{S}_candidates.csv", b"cand_id,score\n1,0.9\n2,0.1\n")
st.stage_done(m["run_id"], "detect"); st.stage_done(m["run_id"], "unified"); st.finish_run(m["run_id"])
ok(open(f"{B}/runs/{S}/{r1}/files/review/{S}_candidates.csv", "rb").read() == b"cand_id,score\n1,0.5\n", "previous candidates preserved in their run archive")
ok(os.stat(f"{fs}/mri/orig.mgz").st_ino == fsmark, "FreeSurfer directory untouched by a new detection run")
ok(st.active_manifest()["run_id"] == m["run_id"], "the new run becomes active")
st.set_active(r1); ok(open(f"{B}/review/{S}_candidates.csv", "rb").read().count(b"\n") == 2, "switching back restores the old outputs")
st.set_active(m["run_id"]); ok(open(f"{B}/review/{S}_candidates.csv", "rb").read().count(b"\n") == 3, "and forward again (nothing lost)")
# failure restores
m2 = st.start_run(st.plan("selective", "detect"), "will fail"); w(f"{B}/review/{S}_candidates.csv", b"half written"); w(f"{B}/review/{S}_excluded.csv", b"new file")
st.finish_run(m2["run_id"], ok=False, msg="detect failed")
ok(open(f"{B}/review/{S}_candidates.csv", "rb").read().count(b"\n") == 3 and not os.path.exists(f"{B}/review/{S}_excluded.csv"),
   "failed run: previous outputs restored, files it created moved aside")
ok(os.path.exists(f"{B}/runs/{S}/{m2['run_id']}/failed_outputs/review/{S}_excluded.csv"), "failed run's own outputs kept for inspection, not deleted")
ok(st.active_manifest()["run_id"] == m["run_id"], "active run unchanged after a failure")
rp = st.resume_plan(m2["run_id"]); ok(rp["ok"] and rp["run"][0] == "detect", "a failed run can be resumed from its first unfinished stage")
# new recon: rename aside, never delete
m3 = st.start_run(st.plan("new", force_anatomy=True), "fresh")
ok(not os.path.exists(fs) and glob.glob(f"{B}/subjects/{S}__run_*"), "new reconstruction: old FreeSurfer renamed aside, not deleted")
ok(pm.recover_all(B) == {S: [m3["run_id"]]}, "interrupted run found at restart")
ok(json.load(open(f"{B}/runs/{S}/{m3['run_id']}/manifest.json"))["status"] == "interrupted", "status interrupted, never left running")
try: st.set_active(m3["run_id"]); ok(False, "interrupted run cannot become active")
except ValueError: ok(True, "interrupted run cannot become active")
os.rename(glob.glob(f"{B}/subjects/{S}__run_*")[0], fs)       # put the recon back for the app tests (as the user would via Make active)
ok(open(f"{B}/review/{S}_calls.csv", "rb").read() == reader0, "reader file unchanged throughout")

# ---- through the real app: routes, executor with stub pipeline scripts, restart recovery ----
os.makedirs(f"{B}/app_data", exist_ok=True); os.makedirs(f"{B}/scripts", exist_ok=True)
open(f"{B}/scripts/detect_css.py", "w").write("import sys,os,time\nB=os.environ['CSS_BASE'];S=sys.argv[1]\n"
    "if os.path.exists(B+'/FAIL_DETECT'): open(B+f'/review/{S}_candidates.csv','w').write('partial'); sys.exit(5)\n"
    "if os.path.exists(B+'/SLOW_DETECT'): time.sleep(60)\n"
    "open(B+f'/review/{S}_candidates.csv','w').write('cand_id,score\\n1,0.7\\n2,0.2\\n3,0.1\\n'); print('stub detect ok')\n")
open(f"{B}/scripts/surface_features.py", "w").write("print('stub surface features')\n")
def free_port():
    s_ = socket.socket(); s_.bind(("127.0.0.1", 0)); p_ = s_.getsockname()[1]; s_.close(); return p_
def start():
    port = free_port(); env = dict(os.environ, HOME=tempfile.mkdtemp(), CSS_BASE=B, CSS_USCORE_FAIL_TEST="1")
    a_ = subprocess.Popen([sys.executable, os.path.join(ROOT, "app", "css_app.py"), "--port", str(port), "--no-window"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    U_ = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try: urllib.request.urlopen(U_ + "/", timeout=2); break
        except Exception: time.sleep(0.2)
    return a_, U_
get = lambda p: json.load(urllib.request.urlopen(U + p, timeout=60))
def post(p, d):
    r = urllib.request.Request(U + p, data=json.dumps(d).encode(), headers={"Content-Type": "application/json", "X-CSS-App": "1"})
    return json.load(urllib.request.urlopen(r, timeout=60))
def wait_idle(limit=60):
    t0 = time.time()
    while time.time() - t0 < limit:
        if not get(f"/api/proc/audit?code={S}").get("busy"): return True
        time.sleep(0.3)
    return False
app, U = start()
try:
    ok(any(x["code"] == S and x["has_fs"] for x in get("/api/proc/studies")["studies"]), "studies route lists the on-disk study with its FreeSurfer")
    a = get(f"/api/proc/audit?code={S}"); ok(a["ok"] and set(a["stages"]) == set(pm.STAGES) and a["identity"]["swi"]["dims"], "audit route: stages + identity")
    before = open(f"{B}/review/{S}_candidates.csv").read()
    r = post("/api/proc/start", dict(code=S, choice="selective", rerun_from="detect")); ok(r["ok"] and r["run"] == ["detect", "unified"], "new detection run started (FreeSurfer, registration, alignment reused)")
    ok(wait_idle(), "run finished")
    h = get(f"/api/proc/history?code={S}"); last = h["runs"][-1]
    ok(last["status"] == "failed" and "unified failed" in last["message"], "unified failure (injected) reported honestly as a failed run")
    ok(open(f"{B}/review/{S}_candidates.csv").read() == before, "failed run: previous candidates restored")
    ok(post("/api/proc/start", dict(code=S, choice="selective", rerun_from="registration"))["ok"] is False, "registration re-run refused here (needs raw series): honest message")
    open(f"{B}/FAIL_DETECT", "w").close()
    post("/api/proc/start", dict(code=S, choice="selective", rerun_from="detect")); wait_idle()
    last = get(f"/api/proc/history?code={S}")["runs"][-1]
    ok(last["status"] == "failed" and "registration gate" in last["message"] and "log tail" in last["message"], "detector exit 5: failed with the reason and the log tail")
    ok(open(f"{B}/review/{S}_candidates.csv").read() == before, "partial candidate file replaced by the previous one")
    lg = get(f"/api/proc/log?code={S}&run_id={last['run_id']}"); ok("$ " in lg["log"], "run log readable from the app")
    os.remove(f"{B}/FAIL_DETECT"); open(f"{B}/SLOW_DETECT", "w").close()
    r = post("/api/proc/start", dict(code=S, choice="selective", rerun_from="detect")); time.sleep(1.5)
    ok(post("/api/proc/start", dict(code=S, choice="selective", rerun_from="detect"))["ok"] is False, "second run refused while one is working")
    ok(post("/api/proc/set_active", dict(code=S, run_id=r1, confirm=True))["ok"] is False, "make-active refused while a run is working")
finally: app.terminate(); app.wait()
os.remove(f"{B}/SLOW_DETECT")
app, U = start()                                               # restart: the cut-off run must be interrupted and restored
try:
    h = get(f"/api/proc/history?code={S}")
    ok(h["recovered"] == {S: [r["run_id"]]}, "app restart: the cut-off run is marked interrupted")
    ok(open(f"{B}/review/{S}_candidates.csv").read() == before, "interrupted run: previous candidates restored")
    rr = post("/api/proc/resume", dict(code=S, run_id=r["run_id"])); ok(rr["ok"] and rr["run"][0] == "detect", "interrupted run resumed as a new run")
    wait_idle(); last = get(f"/api/proc/history?code={S}")["runs"][-1]
    ok(last["stages"]["detect"] == "done", "resumed run: fresh detection done (stub)")
    ok(post("/api/proc/set_active", dict(code=S, run_id=r1))["ok"] is False, "make-active needs explicit confirmation")
    ok(post("/api/proc/set_active", dict(code=S, run_id=r1, confirm=True))["ok"] is True, "make-active with confirmation")
    ok(get("/api/proc/audit?code=../x")["ok"] is False, "path-like codes refused")
    try:
        urllib.request.urlopen(urllib.request.Request(U + "/api/proc/set_active", data=b"{}", headers={"Content-Type": "application/json"}), timeout=10)
        ok(False, "POST without the app header refused")
    except Exception: ok(True, "POST without the app header refused")
finally: app.terminate(); app.wait()
ok(open(f"{B}/review/{S}_calls.csv", "rb").read() == reader0, "reader file unchanged after the app tests")
ok(os.stat(f"{fs}/mri/orig.mgz").st_ino == fsmark, "FreeSurfer files never rewritten")
print("ALL PASS" if not F else f"{len(F)} FAILED"); sys.exit(1 if F else 0)
