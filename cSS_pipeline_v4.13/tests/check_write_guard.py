"""rc2 attack tests: every attempt to write into the production project (~/css_project) from the experimental app must be refused
or safely isolated, and the production project must stay byte- and mtime-identical. Synthetic sandbox HOME, real app process."""
import os, sys, json, glob, socket, hashlib, tempfile, subprocess, time, urllib.request
import numpy as np, nibabel as nib
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..")); GUARD = os.path.join(ROOT, "app", "guard")
F = []
def ok(c, m): print(("PASS " if c else "FAIL ") + m, flush=True); c or F.append(m)
H = tempfile.mkdtemp(prefix="wg_home_"); P = f"{H}/css_project"; X = f"{H}/cSS_experimental"
for d in ("data", "work", "review", "results", "subjects/M02/mri", "app_data"): os.makedirs(f"{P}/{d}", exist_ok=True)
nib.save(nib.Nifti1Image(np.ones((6, 6, 4), np.float32), np.eye(4)), f"{P}/data/M02_swi.nii")
nib.save(nib.Nifti1Image(np.ones((6, 6, 4), np.float32), np.eye(4)), f"{P}/work/M02_seg_swispace.nii.gz")
for n in ("aparc.a2009s+aseg", "orig", "brain"): nib.save(nib.MGHImage(np.ones((4, 4, 4), np.float32), np.eye(4)), f"{P}/subjects/M02/mri/{n}.mgz")
open(f"{P}/work/M02_swi2t1.lta", "w").write("1 4 4\n"); nib.save(nib.Nifti1Image(np.ones((6, 6, 6), np.float32), np.eye(4)), f"{P}/data/M02_t1.nii.gz")
open(f"{P}/review/M02_candidates.csv", "w").write("cand_id\n1\n"); open(f"{P}/review/M02_calls.csv", "w").write("cand_id,call\n1,cSS\n")
os.makedirs(X); os.symlink(P, f"{H}/prod_link"); os.symlink(f"{P}/results", f"{H}/results_link")
def tree(B): return {p: (hashlib.sha256(open(p, "rb").read()).hexdigest() if os.path.isfile(p) else "dir", os.lstat(p).st_mtime)
                     for p in glob.glob(f"{B}/**/*", recursive=True) + [B]}
before = tree(P)
ENV = dict(os.environ, HOME=H, CSS_EXPERIMENTAL="1", PYTHONPATH=GUARD)
# --- 1 project folder (CSS_BASE / CSS_EXP_BASE) inside, through a symlink into, or containing production: the app refuses to start
for base, m in ((f"{P}/exp", "production subfolder"), (f"{H}/prod_link/exp", "symlink into production"), (P, "production itself"), (H, "folder containing production")):
    r = subprocess.run([sys.executable, f"{ROOT}/app/css_app.py", "--port", "1", "--no-window"], env=dict(ENV, CSS_BASE=base), capture_output=True, text=True, timeout=60)
    ok(r.returncode != 0 and "refused to start" in (r.stderr + r.stdout), f"app refuses project folder = {m}")
L = open(f"{ROOT}/app/mac_experimental/launcher.sh").read(); head = L[:L.index('export CSS_BASE="$BASE_C" CSS_EXPERIMENTAL=1')] + 'export CSS_BASE="$BASE_C"\necho LAUNCH_OK\n'
# the launcher reports a refusal with a modal osascript dialog; in a logged-in macOS session it waits for a click (test timeout).
# Replace ONLY that notification with a stderr echo; the refusal logic and exit codes are unchanged and still asserted below.
assert head.count("/usr/bin/osascript") == 1; head = head.replace('/usr/bin/osascript -e', 'echo DIALOG >&2; : ', 1)
for base, m in ((f"{P}/sub", "CSS_EXP_BASE = production subdirectory"), (f"{H}/prod_link/x", "CSS_EXP_BASE through a symlink into production"), (H, "CSS_EXP_BASE containing production")):
    r = subprocess.run(["bash", "-c", head], env=dict(ENV, CSS_EXP_BASE=base, PATH="/usr/bin:/bin"), capture_output=True, text=True, timeout=60)
    ok("LAUNCH_OK" not in r.stdout and r.returncode != 0 and "DIALOG" in r.stderr, f"launcher refuses {m} (and shows its refusal notice)")
# --- 2 the running app (experimental project X)
s_ = socket.socket(); s_.bind(("127.0.0.1", 0)); port = s_.getsockname()[1]; s_.close()
os.makedirs(f"{X}/scripts"); open(f"{X}/scripts/detect_css.py", "w").write(
    "import os,sys\nH=os.environ['HOME'];S=sys.argv[1]\n"
    "try:\n open(H+'/css_project/review/'+S+'_candidates.csv','w').write('attack')\n print('WROTE INTO PRODUCTION')\nexcept PermissionError as e: print('child refused:',e)\n"
    "open(os.environ['CSS_BASE']+'/review/'+S+'_candidates.csv','w').write('cand_id\\n1\\n2\\n')\n")
app = subprocess.Popen([sys.executable, f"{ROOT}/app/css_app.py", "--port", str(port), "--no-window"], env=dict(ENV, CSS_BASE=X, CSS_USCORE_FAIL_TEST="1"),
                       stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
U = f"http://127.0.0.1:{port}"
def get(p): return json.load(urllib.request.urlopen(U + p, timeout=60))
def post(p, d):
    rq = urllib.request.Request(U + p, data=json.dumps(d).encode(), headers={"Content-Type": "application/json", "X-CSS-App": "1"})
    return json.load(urllib.request.urlopen(rq, timeout=120))
try:
    for _ in range(100):
        try: urllib.request.urlopen(U + "/", timeout=2); break
        except Exception: time.sleep(0.2)
    for k in ("export_dir", "backup_dir"):
        for d, m in ((f"{P}/results", "inside production"), (f"{H}/results_link", "symlink to a production folder"), (P, "production itself")):
            r = post("/api/settings", {k: d}); ok(r.get("ok") is False and "production" in r.get("error", ""), f"settings: {k} {m} refused")
    r = post("/api/queue", dict(patients=[dict(code="T01", chosen=dict(SWI="/tmp/none"))], settings=dict(results_dir=f"{P}/results")))
    ok(r.get("ok") is False and any("results folder refused" in e for e in r.get("errors", [])), "Add patients: results folder inside production refused")
    r = post("/api/queue", dict(patients=[dict(code="T02", chosen=dict(SWI="/tmp/none"))], settings=dict(results_dir=f"{H}/results_link")))
    ok(r.get("ok") is False, "Add patients: results folder = symlink into production refused")
    st = json.load(open(f"{X}/app_data/settings.json")) if os.path.exists(f"{X}/app_data/settings.json") else {}
    # import (read-only) + FreeSurfer isolation
    r = post("/api/proc/link", dict(source=P, codes=["M02"])); ok(r["ok"] and r["results"][0]["fs_method"] in ("copy", "apfs_clone"), "import: FreeSurfer copied (isolated), not linked")
    ok(os.path.isdir(f"{X}/subjects/M02") and not os.path.islink(f"{X}/subjects/M02"), "experimental subjects/M02 is a real folder")
    # processing: a pipeline script (child process) that tries to write into production
    post("/api/proc/adopt", dict(code="M02")); r = post("/api/proc/start", dict(code="M02", choice="selective", rerun_from="detect"))
    ok(r.get("ok"), "processing run started" + ("" if r.get("ok") else f": {r}"))
    for _ in range(100):
        if not get("/api/proc/audit?code=M02").get("busy"): break
        time.sleep(0.3)
    lg = get(f"/api/proc/log?code=M02&run_id={r['run_id']}")["log"]
    ok("child refused" in lg and "WROTE INTO PRODUCTION" not in lg, "pipeline child process: write into production refused by the guard (logged)")
    ok(open(f"{X}/review/M02_candidates.csv").read().count("\n") >= 1, "the pipeline's own outputs went to the experimental project")
finally: app.terminate(); app.wait()
# --- 3 tampered settings / direct calls inside an app-like process
code = f"""
import os, sys, json; sys.path.insert(0, {repr(ROOT + '/app')})
os.environ['CSS_BASE'] = {repr(X)}
import css_app as A
res = {{}}
A.SET['export_dir'] = {repr(P + '/results')}
try: A.export_dest(); res['export'] = 'WROTE?'
except A.ExportRefused as e: res['export'] = 'refused'
A.SET['backup_dir'] = {repr(P + '/results')}; A.SET['features']['backup'] = True
res['backup'] = 'refused' if A.backup() is False else 'WROTE?'
p = dict(code='M02', results_dir={repr(P + '/results')}); A.copy_results(p)
import tempfile
os.environ['TMPDIR'] = {repr(P)}; tempfile.tempdir = None
try: fd, tp = tempfile.mkstemp(); res['tmp'] = 'isolated' if not os.path.realpath(tp).startswith(os.path.realpath({repr(P)})) else 'WROTE?'
except PermissionError: res['tmp'] = 'refused'
try: open({repr(X + '/subjects_attack')}, 'w').close(); os.symlink({repr(P + '/subjects/M02')}, {repr(X + '/fs_link')}); res['symlink'] = 'WROTE?'
except PermissionError: res['symlink'] = 'refused'
try: open({repr(H + '/prod_link/review/M02_candidates.csv')}, 'a').write('x'); res['through_link'] = 'WROTE?'
except PermissionError: res['through_link'] = 'refused'
try: import subprocess; subprocess.run(['cp', {repr(X + '/subjects_attack')}, {repr(P + '/x')}]); res['subprocess'] = 'WROTE?'
except PermissionError: res['subprocess'] = 'refused'
print(json.dumps(res))
"""
r = subprocess.run([sys.executable, "-c", code], env=dict(ENV, CSS_BASE=X), capture_output=True, text=True, timeout=120)
try: res = json.loads(r.stdout.strip().splitlines()[-1])
except Exception: res = {}; print(r.stdout[-800:], r.stderr[-800:])
ok(res.get("tmp") in ("refused", "isolated"), f"temporary file with TMPDIR inside production: {res.get('tmp')} (not written into production)")
for k, m in (("export", "export with a tampered export folder inside production"), ("backup", "backup with a tampered backup folder inside production"),
             ("symlink", "creating a symlink into production"),
             ("through_link", "writing through a symlink into production"), ("subprocess", "starting a program aimed at production")):
    ok(res.get(k) == "refused", f"{m}: refused")
ok(not os.path.exists(f"{P}/results/M02_calls.csv") and not glob.glob(f"{P}/results/*"), "results copy into production refused (nothing copied)")
# --- 4 production untouched
after = tree(P)
ok(after == before, f"production project unchanged: {len(before)} entries, content + modification times identical")
print("ALL PASS" if not F else f"{len(F)} FAILED"); sys.exit(1 if F else 0)
