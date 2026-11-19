"""cSS Pipeline app - local, button-driven front end for the installed pipeline (no Terminal needed).
Started by 'cSS Pipeline.app' (or: python app/css_app.py [--port 8800] [--no-window]). Serves http://127.0.0.1:<port>/ on this Mac only.
It never changes the detector, its thresholds or rules: it imports MRI folders (scripts/cohort.py), runs scripts/cohort.py run /
run_css.sh one patient at a time, and opens the existing reviewer / blind viewer. Patient names (optional) are stored only in
$CSS_BASE/private/names.csv and never written to results, logs or exports.
App data: $CSS_BASE/app_data/ (patients.json, cohorts.json, settings.json, timings.json, staging/, qc/, logs/)."""
import sys, os, io, re, json, time, glob, shutil, signal, zipfile, threading, subprocess, webbrowser, datetime, hashlib, platform, socket
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import series_detect as SD

B = os.environ.get("CSS_BASE", os.path.expanduser("~/css_project"))
SC = os.path.join(B, "scripts"); AD = os.path.join(B, "app_data"); PRIV = os.path.join(B, "private")
for d in (AD, f"{AD}/staging", f"{AD}/qc", f"{AD}/logs", PRIV): os.makedirs(d, exist_ok=True)
FAKE = os.environ.get("CSS_APP_FAKE_RUN") == "1"            # tests only: simulate the pipeline steps
LOCK = threading.RLock()
STEPS = ["import", "anatomy", "align", "detect", "qc"]
DEFAULT_MIN = {"synthseg": dict(import_=2, anatomy=12, align=1, detect=6, qc=1), "recon": dict(import_=2, anatomy=150, align=1, detect=6, qc=1)}
PIPE_ENV = dict(CSS_V53="1", CSS_ZONE2="1", CSS_CONF="1", NOVIEW="1")          # the flags the current production lists use

# ------------------------------------------------------------------ persistence
def jload(name, default):
    p = f"{AD}/{name}"
    try: return json.load(open(p))
    except Exception: return default
def jsave(name, obj):
    p = f"{AD}/{name}"; json.dump(obj, open(p + ".tmp", "w"), indent=1, default=str); os.replace(p + ".tmp", p)
SET = dict(dict(awake=True, theme="dark", backup_dir="", freesurfer_home=os.environ.get("FREESURFER_HOME", ""), threads=4,
                features=dict(duplicate_check=True, preflight=True, qc_snapshot=True, notify=True, version_stamp=True, share=True, backup=True,
                              name_warning=False)), **jload("settings.json", {}))
PAT = jload("patients.json", [])
for p in PAT:                                            # resume after a restart: interrupted runs go back to the queue
    if p.get("status") in ("running", "paused"): p.update(status="waiting", step="", note="restarted after the app was closed")
def save_pat(): jsave("patients.json", PAT)
def names():
    import csv
    p = f"{PRIV}/names.csv"
    if not os.path.exists(p): return {}
    return {r["code"]: r["name"] for r in csv.DictReader(open(p)) if r.get("code")}
def set_name(code, name, old_code=None):
    import csv
    n = names(); n.pop(old_code or code, None)
    if name: n[code] = name
    with open(f"{PRIV}/names.csv.tmp", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["code", "name"]); [w.writerow([k, v]) for k, v in sorted(n.items())]
    os.replace(f"{PRIV}/names.csv.tmp", f"{PRIV}/names.csv")
def version():
    try: return open(f"{SC}/VERSION").read().strip()
    except Exception: return "not installed"
def pget(code): return next((p for p in PAT if p["code"] == code), None)

# ------------------------------------------------------------------ helpers
def mac(): return platform.system() == "Darwin"
def notify(title, text):
    if SET["features"].get("notify") and mac():
        subprocess.run(["osascript", "-e", f'display notification "{text}" with title "{title}"'], capture_output=True)
def pick(kind, prompt):
    if not mac(): return None, "the folder / file picker needs macOS - type the path instead"
    script = {"folder": f'POSIX path of (choose folder with prompt "{prompt}")', "file": f'POSIX path of (choose file with prompt "{prompt}")',
              "save": f'POSIX path of (choose folder with prompt "{prompt}")'}[kind]
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return (r.stdout.strip(), "") if r.returncode == 0 else (None, "cancelled")
def fs_env():
    e = dict(os.environ); fh = SET.get("freesurfer_home") or e.get("FREESURFER_HOME", "")
    if fh:
        e["FREESURFER_HOME"] = fh; e["PATH"] = f"{fh}/bin:{fh}/python/bin:" + e.get("PATH", "")
        e.setdefault("FS_LICENSE", f"{fh}/license.txt"); e.setdefault("SUBJECTS_DIR", f"{B}/subjects")
    e["CSS_BASE"] = B; e["CSS_THREADS"] = str(SET.get("threads", 4)); e.update(PIPE_ENV)
    return e
def which(x, env): return shutil.which(x, path=env.get("PATH"))

def preflight():
    env = fs_env(); out = []
    du = shutil.disk_usage(B); free = du.free / 1e9
    out.append(dict(item="Disk space", ok=free > 15, detail=f"{free:.0f} GB free" + ("" if free > 15 else " - at least 15 GB recommended")))
    out.append(dict(item="Pipeline", ok=os.path.exists(f"{SC}/run_css.sh"), detail=version()))
    fh = env.get("FREESURFER_HOME", "")
    out.append(dict(item="FreeSurfer", ok=bool(fh) and os.path.isdir(fh), detail=fh or "not found - choose its folder in Setup"))
    lic = env.get("FS_LICENSE", "")
    out.append(dict(item="FreeSurfer licence", ok=bool(lic) and os.path.exists(lic), detail=lic or "license.txt not found"))
    for tool in ("mri_synthseg", "mri_convert", "dcm2niix"):
        w = which(tool, env); out.append(dict(item=tool, ok=bool(w), detail=w or "not on the FreeSurfer path"))
    try:
        import numpy, scipy, nibabel, pandas, skimage  # noqa
        out.append(dict(item="Python packages", ok=True, detail=f"python {platform.python_version()}"))
    except ImportError as e: out.append(dict(item="Python packages", ok=False, detail=str(e)))
    if mac():
        r = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True)
        gb = int(r.stdout.strip() or 0) / 1e9; out.append(dict(item="Memory", ok=gb >= 16, detail=f"{gb:.0f} GB"))
    return out

# ------------------------------------------------------------------ scanning folders
def code_from(folder, rule):
    b = os.path.basename(os.path.normpath(folder))
    if rule == "before_underscore": return re.split(r"[_ ]", b)[0]
    if rule == "digits": return "".join(re.findall(r"\d+", b)) or b
    return b
def looks_like_name(s): return bool(re.fullmatch(r"[A-Za-z][A-Za-z'\-]+[ _,]+[A-Za-z][A-Za-z'\- ]*", s.strip()))
def scan_patient(folder, folder_is, rule):
    ser = SD.scan(folder); pick_, alt = SD.choose(ser); base = os.path.basename(os.path.normpath(folder))
    r = dict(folder=folder, folder_name=base, series=ser, chosen=pick_, alternatives=alt, warnings=[])
    if folder_is == "code": r["code"] = code_from(folder, rule); r["name"] = ""
    elif folder_is == "name": r["code"] = ""; r["name"] = base.replace("_", " ")
    else: r["code"] = ""; r["name"] = ""
    if "SWI" not in pick_: r["warnings"].append("no SWI found - choose one")
    if "T1" not in pick_: r["warnings"].append("no T1 - SWI-only route (less accurate)")
    t1 = next((x for x in ser if x["path"] == pick_.get("T1")), None)
    if t1 and max([v for v in (t1.get("voxel") or []) if v] or [0]) > 1.5:
        r["warnings"].append(f"T1 is 2-D ({max(v for v in t1['voxel'] if v):g} mm slices) - anatomy will be less accurate than with a 3-D T1")
    if any(re.search(r"angio|tof|mra", (x.get("name", "") + " " + x.get("description", "")), re.I) for x in ser) and not pick_.get("SWI"):
        r["warnings"].append("this folder looks like an angiogram study - check that it is the brain MRI")
    if alt.get("SWI"): r["warnings"].append(f"{len(alt['SWI']) + 1} SWI series - the highest resolution was chosen")
    if SET["features"].get("duplicate_check") and "SWI" in pick_:
        fp = next((s["fingerprint"] for s in ser if s["path"] == pick_["SWI"]), "")
        r["fingerprint"] = fp
        dup = [p["code"] for p in PAT if fp and p.get("fingerprint") == fp]
        if dup: r["warnings"].append(f"this SWI is already in the project as {', '.join(dup)}")
    if SET["features"].get("name_warning") and folder_is == "code" and looks_like_name(base):
        r["warnings"].append("the folder name looks like a person's name - it will be used as the study code")
    return r
def scan(path, mode, folder_is, rule):
    if mode == "single": return [scan_patient(path, folder_is, rule)]
    subs = sorted(d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d)) and not d.startswith("."))
    return [scan_patient(os.path.join(path, d), folder_is, rule) for d in subs]

# ------------------------------------------------------------------ grades from Excel / CSV
HDR = dict(code=["study_code", "code", "study id", "study_id", "id", "patient id", "subject"], name=["patient name", "name", "patient"],
           radiologist=["radiologist", "reader"], R=["r_grade", "r", "r css", "right", "r_css", "r grade"], L=["l_grade", "l", "l css", "left", "l_css", "l grade"],
           total=["total", "css score", "cSS score (0-4)", "score", "total (0-4)"])
def read_grades(path):
    import pandas as pd
    df = pd.read_excel(path, dtype=str) if path.lower().endswith((".xlsx", ".xls")) else pd.read_csv(path, dtype=str)
    df = df.fillna(""); cols = {c.strip().lower(): c for c in df.columns}; m = {}
    for k, alts in HDR.items():
        for a in alts:
            c = next((cols[x] for x in cols if x == a.lower() or x.startswith(a.lower() + " ") or x.startswith(a.lower() + "(")), None)
            if c: m[k] = c; break
    rows = []
    for _, r in df.iterrows():
        g = {k: str(r[c]).strip() for k, c in m.items()}
        if not (g.get("code") or g.get("name")): continue
        for s in ("R", "L"):
            v = re.sub(r"\.0$", "", g.get(s, "")); g[s] = v if v in ("0", "1", "2") else ""
        rows.append(g)
    return dict(columns_found=m, rows=rows)
def grades_template():
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active; ws.title = "grades"
    ws.append(["study_code", "patient_name (optional)", "radiologist", "R_grade (0-2)", "L_grade (0-2)", "total (0-4)", "date_read", "comment"])
    ws.append(["P016", "", "Dr. A", 1, 0, 1, "2026-11-20", "example row - delete"])
    for c in "ABCDEFGH": ws.column_dimensions[c].width = 18
    bio = io.BytesIO(); wb.save(bio); return bio.getvalue()

# ------------------------------------------------------------------ queue
def next_code():
    used = {p["code"] for p in PAT} | {os.path.basename(d) for d in glob.glob(f"{B}/raw/*")}
    n = 1
    while f"P{n:03d}" in used: n += 1
    return f"P{n:03d}"
def add_to_queue(items, st):
    errs = []; codes_now = {p["code"] for p in PAT}; seen = set()
    for it in items:
        if not (it.get("code") or it.get("name")): errs.append(f"{it.get('folder_name')}: needs a code or a name")
        if it.get("code"):
            c = it["code"]
            if not re.fullmatch(r"[A-Za-z0-9_\-]{1,32}", c): errs.append(f"{c}: codes may use letters, digits, - and _ only")
            if c in codes_now or c in seen: errs.append(f"{c}: duplicate code")
            seen.add(c)
        if not it.get("chosen", {}).get("SWI"): errs.append(f"{it.get('code') or it.get('folder_name')}: no SWI chosen")
    if errs: return dict(ok=False, errors=errs)
    added = []
    with LOCK:
        for it in items:
            code = it.get("code") or next_code()
            if st.get("store_names") and it.get("name"): set_name(code, it["name"])
            p = dict(code=code, cohort=st.get("cohort", ""), anatomy=st.get("anatomy", "synthseg"), mode=st.get("mode", "semi"),
                     results_dir=st.get("results_dir", ""), radiologist=it.get("radiologist", ""), grade_R=it.get("grade_R", ""), grade_L=it.get("grade_L", ""),
                     series=it["chosen"], fingerprint=it.get("fingerprint", ""), status="waiting", step="", steps_done={}, added=time.time(),
                     source_folder_hash=hashlib.sha1(it.get("folder", "").encode()).hexdigest()[:12])     # the folder path itself is not stored (may hold a name)
            PAT.append(p); added.append(code)
            coh = jload("cohorts.json", [])
            if p["cohort"] and p["cohort"] not in coh: coh.append(p["cohort"]); jsave("cohorts.json", coh)
        save_pat()
    write_grades_file()
    return dict(ok=True, added=added)
def write_grades_file():
    """review/radiologist_grades.csv (study_id,R,L) for the pipeline's own comparison tools; only rows with both grades; existing rows kept"""
    import pandas as pd
    p = f"{B}/review/radiologist_grades.csv"; os.makedirs(f"{B}/review", exist_ok=True)
    old = pd.read_csv(p, dtype=str) if os.path.exists(p) else pd.DataFrame(columns=["study_id", "R", "L"])
    new = pd.DataFrame([dict(study_id=x["code"], R=x["grade_R"], L=x["grade_L"]) for x in PAT if x.get("grade_R") != "" and x.get("grade_L") != ""])
    if len(new):
        old = old[~old.study_id.isin(new.study_id)]; pd.concat([old, new]).to_csv(p, index=False)

def stage(p):
    """staging/<code>/<SWI|T1|FLAIR>/ = links to the chosen series (cohort.py's expected layout); phase files go with the SWI"""
    d = f"{AD}/staging/{p['code']}"; shutil.rmtree(d, ignore_errors=True)
    for mod, keys in (("SWI", ["SWI", "PHASE"]), ("T1", ["T1"]), ("FLAIR", ["FLAIR"])):
        for k in keys:
            src = p["series"].get(k)
            if not src: continue
            os.makedirs(f"{d}/{mod}", exist_ok=True)
            files = [src] if os.path.isfile(src) else [os.path.join(src, f) for f in os.listdir(src) if not f.startswith(".")]
            if os.path.isfile(src) and src.endswith((".nii", ".nii.gz")):
                js = re.sub(r"\.nii(\.gz)?$", ".json", src)
                if os.path.exists(js): files.append(js)
            for f in files:
                if os.path.isfile(f):
                    dst = f"{d}/{mod}/{k}_{os.path.basename(f)}"
                    if not os.path.exists(dst): os.symlink(f, dst)
    return d

CUR = dict(proc=None, code=None, caff=None)
def caffeinate(on):
    if not mac(): return
    if on and SET.get("awake") and CUR["caff"] is None:
        CUR["caff"] = subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])
    if (not on or not SET.get("awake")) and CUR["caff"] is not None:
        CUR["caff"].terminate(); CUR["caff"] = None

def run_logged(cmd, logf, env, on_line=None):
    with open(logf, "a") as lf:
        lf.write(f"\n$ {' '.join(cmd)}\n"); lf.flush()
        pr = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, text=True, start_new_session=True, bufsize=1)
        CUR["proc"] = pr
        for line in pr.stdout:
            lf.write(line); lf.flush()
            if on_line: on_line(line)
        rc = pr.wait(); CUR["proc"] = None
    return rc

def step_begin(p, s):
    with LOCK: p["step"] = s; p.setdefault("step_start", {})[s] = time.time(); save_pat()
def step_end(p, s):
    with LOCK:
        dt = time.time() - p["step_start"][s]; p["steps_done"][s] = dt
        tm = jload("timings.json", {}); k = f"{p['anatomy']}:{s}"; old = tm.get(k)
        tm[k] = dt if old is None else 0.7 * old + 0.3 * dt; jsave("timings.json", tm); save_pat()

def process(p):
    env = fs_env(); code = p["code"]; logf = f"{AD}/logs/{code}.log"
    p.update(status="running", started=time.time(), error="", steps_done={}, version=version() if SET["features"].get("version_stamp") else "")
    save_pat(); caffeinate(True)
    if FAKE:
        for s in STEPS:
            step_begin(p, s); time.sleep(float(os.environ.get("CSS_APP_FAKE_STEP_S", "0.3")))
            while p["status"] == "paused": time.sleep(0.2)
            if p["status"] == "stopped": return
            step_end(p, s)
        p.update(status="done", finished=time.time(), step=""); save_pat(); return
    # 1 import (cohort.py import, merged into review/cohort_import.csv instead of replacing it)
    step_begin(p, "import")
    st = stage(p); tab = f"{B}/review/cohort_import.csv"; bak = None
    if os.path.exists(tab): bak = open(tab).read()
    rc = run_logged([sys.executable, f"{SC}/cohort.py", "import", os.path.dirname(st), "--ids", code], logf, env)
    if bak is not None and os.path.exists(tab):
        import pandas as pd
        new = pd.read_csv(tab, dtype=str); old = pd.read_csv(io.StringIO(bak), dtype=str)
        pd.concat([old[~old.study_id.isin(new.study_id)], new]).to_csv(tab, index=False)
    if rc != 0: return fail(p, f"import failed (exit {rc}) - see the log")
    step_end(p, "import")
    # 2-4 anatomy, alignment, detection: cohort.py run (run_css.sh), progress from its step lines
    step_begin(p, "anatomy")
    def on_line(line):
        if line.startswith("[2/4]") and p["step"] == "anatomy": step_end(p, "anatomy"); step_begin(p, "align")
        if line.startswith("[3/4]") and p["step"] in ("anatomy", "align"):
            if p["step"] == "anatomy": step_end(p, "anatomy"); step_begin(p, "align")
            step_end(p, "align"); step_begin(p, "detect")
    cmd = [sys.executable, f"{SC}/cohort.py", "run", "--ids", code, "--redo", "--allow-no-t1"] + (["--no-recon"] if p["anatomy"] == "synthseg" else [])
    rc = run_logged(cmd, logf, env, on_line)
    if p["status"] == "stopped": return
    runlog = f"{B}/logs/{code}_run.log"
    if os.path.exists(runlog):
        open(logf, "a").write(open(runlog).read()[-20000:]); txt = open(runlog).read()
        for ln in txt.splitlines(): on_line(ln + "\n")
    res = _cohort_status(code)
    if rc != 0 or res != "ok": return fail(p, explain(code, res))
    if p["step"] != "detect": step_begin(p, "detect")
    step_end(p, "detect")
    # 5 QC snapshot, AI score (automatic mode), version stamp
    step_begin(p, "qc")
    if SET["features"].get("qc_snapshot"): qc_snapshot(code)
    if p["mode"] == "auto":
        r = subprocess.run([sys.executable, f"{HERE}/ai_score_cli.py", code], capture_output=True, text=True, env=env)
        p["ai_note"] = "" if r.returncode == 0 else (r.stderr or r.stdout)[-300:]
    copy_results(p); step_end(p, "qc")
    p.update(status="done", finished=time.time(), step=""); save_pat(); notify("cSS Pipeline", f"{code} finished")
def _cohort_status(code):
    import pandas as pd
    p = f"{B}/review/cohort_run.csv"
    if not os.path.exists(p): return "unknown"
    t = pd.read_csv(p, dtype=str); t = t[t.study_id == code]
    return t.status.iloc[-1] if len(t) else "unknown"
def explain(code, status):
    log = open(f"{B}/logs/{code}_run.log").read()[-6000:] if os.path.exists(f"{B}/logs/{code}_run.log") else ""
    for pat, msg in ((r"exit 5|registration", "the T1 and SWI do not line up (registration check failed) - check the T1 / SWI pair"),
                     (r"insufficient_quality|exit 3", "image quality too low for scoring (QC: insufficient quality)"),
                     (r"mri_convert could not read", "the SWI file could not be read"), (r"no SWI chosen", "no SWI series was chosen"),
                     (r"license|licence", "FreeSurfer licence not found - choose it in Setup"), (r"No space left", "the disk is full"),
                     (r"command not found|not found: mri_", "FreeSurfer tools not found - choose the FreeSurfer folder in Setup")):
        if re.search(pat, log, re.I): return msg
    app = open(f"{AD}/logs/{code}.log").read()[-4000:] if os.path.exists(f"{AD}/logs/{code}.log") else ""
    if "Traceback" in app:
        last = [l for l in app.strip().splitlines() if l.strip()][-1][:200]
        return f"the pipeline stopped with an error: {last} - open the log for details"
    return f"processing failed ({status}) - open the log for details"
def fail(p, msg):
    with LOCK: p.update(status="failed", error=msg, finished=time.time()); save_pat()
    notify("cSS Pipeline", f"{p['code']} failed: {msg[:60]}")
def copy_results(p):
    """codes-only copy of the patient's result files into the chosen results folder"""
    d = p.get("results_dir")
    if not d: return
    d = os.path.expanduser(d); os.makedirs(d, exist_ok=True)
    for f in glob.glob(f"{B}/review/{p['code']}_*"):
        if f.endswith((".csv", ".json")) and "manifest" not in f: shutil.copy2(f, d)
    q = f"{AD}/qc/{p['code']}.png"
    if os.path.exists(q): shutil.copy2(q, os.path.join(d, f"{p['code']}_qc.png"))
def qc_snapshot(code):
    try:
        import numpy as np, nibabel as nib, matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
        swi = f"{B}/data/{code}_swi.nii"; swi = swi if os.path.exists(swi) else swi + ".gz"
        I = np.asarray(nib.load(swi).dataobj, np.float32); S = np.asarray(nib.load(f"{B}/work/{code}_seg_swispace.nii.gz").dataobj)
        ks = [int(I.shape[2] * f) for f in (0.35, 0.55, 0.75)]; vmin, vmax = np.percentile(I[I > 0], [1, 99])
        fig, ax = plt.subplots(1, 3, figsize=(10, 3.6), facecolor="#111")
        for a, k in zip(ax, ks):
            a.imshow(I[:, :, k].T, cmap="gray", origin="lower", vmin=vmin, vmax=vmax)
            a.contour((S[:, :, k] >= 1000).T.astype(float), levels=[0.5], colors="#00d0ff", linewidths=0.6)
            a.contour((S[:, :, k] > 0).T.astype(float), levels=[0.5], colors="#f2c94c", linewidths=0.6); a.axis("off")
        fig.suptitle(f"{code}: cortex labels (cyan) and brain mask (yellow) on the SWI - they should follow the anatomy", color="w", fontsize=9)
        fig.tight_layout(); fig.savefig(f"{AD}/qc/{code}.png", dpi=110, facecolor="#111"); plt.close(fig)
    except Exception as e: open(f"{AD}/logs/{code}.log", "a").write(f"\nQC snapshot not made: {e}\n")

def worker():
    last_backup = ""
    while True:
        with LOCK: nxt = next((p for p in PAT if p["status"] == "waiting"), None)
        if nxt is None:
            caffeinate(False)
            day = datetime.date.today().isoformat()
            if SET["features"].get("backup") and SET.get("backup_dir") and day != last_backup: backup(); last_backup = day
            time.sleep(1); continue
        CUR["code"] = nxt["code"]
        try: process(nxt)
        except Exception as e: fail(nxt, f"app error: {type(e).__name__}: {e}")
        CUR["code"] = None
def backup():
    d = os.path.join(os.path.expanduser(SET["backup_dir"]), datetime.date.today().isoformat()); os.makedirs(d, exist_ok=True)
    for f in glob.glob(f"{B}/review/*.csv") + glob.glob(f"{B}/review/*.json") + glob.glob(f"{AD}/*.json"):
        shutil.copy2(f, d)
    if os.path.exists(f"{PRIV}/names.csv"): shutil.copy2(f"{PRIV}/names.csv", os.path.join(d, "names_PRIVATE.csv"))

def eta(p):
    tm = jload("timings.json", {}); dflt = DEFAULT_MIN["recon" if p["anatomy"] == "recon" else "synthseg"]
    est = {s: tm.get(f"{p['anatomy']}:{s}", dflt["import_" if s == "import" else s] * 60) for s in STEPS}
    if p["status"] == "waiting": return 0, sum(est.values())
    if p["status"] != "running" and p["status"] != "paused": return (p.get("finished", 0) - p.get("started", 0)) if p.get("started") else 0, 0
    el = time.time() - p.get("started", time.time()); rem = 0
    for s in STEPS:
        if s in p["steps_done"]: continue
        if s == p["step"]: rem += max(est[s] - (time.time() - p["step_start"][s]), 0.1 * est[s])
        else: rem += est[s]
    return el, rem

# ------------------------------------------------------------------ results
def results():
    import pandas as pd
    rows = []; nm = names()
    for p in PAT:
        c = p["code"]; r = dict(code=c, name=nm.get(c, ""), cohort=p.get("cohort", ""), mode=p.get("mode", ""), status=p["status"], version=p.get("version", ""),
                                radiologist=p.get("radiologist", ""), rad_R=p.get("grade_R", ""), rad_L=p.get("grade_L", ""))
        f = f"{B}/review/{c}_candidates.csv"
        if os.path.exists(f): r["candidates"] = int(len(pd.read_csv(f)))
        f = f"{B}/review/{c}_calls.csv"
        if os.path.exists(f):
            k = pd.read_csv(f); r["reviewed"] = int(k.call.notna().sum()) if "call" in k else 0; r["css_called"] = int((k.get("call") == "cSS").sum()) if "call" in k else 0
        for tag, key in (("score", ""), ("ai", "_ai")):
            f = f"{B}/review/{c}_score{key}.json"
            if os.path.exists(f):
                j = json.load(open(f)); r[f"{tag}_L"] = j.get("L_score"); r[f"{tag}_R"] = j.get("R_score"); r[f"{tag}_total"] = j.get("multifocality_0_4")
        r["label"] = "reviewed" if r.get("score_total") is not None else ("AI only, not validated" if r.get("ai_total") is not None else "")
        rows.append(r)
    return rows
def export_xlsx():
    import pandas as pd
    df = pd.DataFrame(results()).drop(columns=["name"], errors="ignore")
    bio = io.BytesIO(); df.to_excel(bio, index=False, sheet_name="results"); return bio.getvalue()
def share_package(codes):
    out = os.path.expanduser(f"~/Desktop/cSS_share_{datetime.datetime.now():%Y%m%d_%H%M}.zip")
    import pandas as pd
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for c in codes:
            for f in glob.glob(f"{B}/review/{c}_*"):
                if f.endswith((".csv", ".json")) and "manifest" not in f: z.write(f, f"review/{os.path.basename(f)}")
            q = f"{AD}/qc/{c}.png"
            if os.path.exists(q): z.write(q, f"qc/{c}.png")
        z.writestr("results.csv", pd.DataFrame([r for r in results() if r["code"] in codes]).drop(columns=["name"], errors="ignore").to_csv(index=False))
        z.writestr("README.txt", f"cSS results, codes only (no names, no images, no DICOM headers). Pipeline {version()}. Made {datetime.datetime.now():%Y-%m-%d %H:%M}.")
    return out

# ------------------------------------------------------------------ pipeline install / rollback
def install_zip(path):
    if CUR["code"]: return dict(ok=False, error="a patient is processing - wait or stop it first")
    z = zipfile.ZipFile(path); names_ = z.namelist()
    ver = [n for n in names_ if n.endswith("scripts/VERSION")]
    if not ver: return dict(ok=False, error="this zip does not contain a cSS pipeline (no scripts/VERSION)")
    prefix = ver[0][:-len("scripts/VERSION")]
    newv = z.read(ver[0]).decode().strip()
    bk = f"{AD}/pipeline_backups/{datetime.datetime.now():%Y%m%d_%H%M%S}_{version()}"
    os.makedirs(bk, exist_ok=True)
    for d in ("scripts", "app", "reference_audit", "experimental", "tests", "tools", "docs"):
        if os.path.isdir(f"{B}/{d}"): shutil.copytree(f"{B}/{d}", f"{bk}/{d}", symlinks=True)
    n = 0
    for m in names_:
        if not m.startswith(prefix) or m.endswith("/"): continue
        rel = m[len(prefix):]
        if not rel or rel.split("/")[0] not in ("scripts", "app", "reference_audit", "experimental", "tests", "tools", "docs") and "/" in rel: continue
        dst = os.path.join(B, rel); os.makedirs(os.path.dirname(dst), exist_ok=True)
        with z.open(m) as src, open(dst, "wb") as out: shutil.copyfileobj(src, out)
        if rel.endswith((".sh", ".command")) or "/MacOS/" in rel: os.chmod(dst, 0o755)
        n += 1
    return dict(ok=True, version=newv, files=n, backup=bk)
def rollback():
    bks = sorted(glob.glob(f"{AD}/pipeline_backups/*"))
    if not bks: return dict(ok=False, error="no backup")
    b = bks[-1]
    for d in os.listdir(b):
        shutil.rmtree(f"{B}/{d}", ignore_errors=True); shutil.copytree(f"{b}/{d}", f"{B}/{d}", symlinks=True)
    shutil.move(b, b + "_restored")
    return dict(ok=True, version=version())

# ------------------------------------------------------------------ child apps (reviewer / blind viewer)
CHILD = {}
def free_port(start):
    for p in range(start, start + 50):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0: return p
def launch_child(kind, args, port0):
    old = CHILD.get(kind)
    if old and old.poll() is None: old.terminate()
    port = free_port(port0); env = fs_env()
    if kind == "review": cmd = [sys.executable, f"{SC}/review_web.py", ",".join(args["codes"]), "--open", "--no-browser", "--port", str(port)]
    else: cmd = [sys.executable, f"{B}/reference_audit/blind_read/blind_read.py", args["packet"], args["reader"], "--port", str(port), "--no-browser"]
    if kind == "review" and args.get("reviewer"): cmd += ["--reviewer", args["reviewer"]]
    CHILD[kind] = subprocess.Popen(cmd, stdout=open(f"{AD}/logs/{kind}.log", "w"), stderr=subprocess.STDOUT, env=env)
    for _ in range(100):
        time.sleep(0.2)
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0: return dict(ok=True, url=f"http://127.0.0.1:{port}/")
        if CHILD[kind].poll() is not None: return dict(ok=False, error=open(f"{AD}/logs/{kind}.log").read()[-600:])
    return dict(ok=False, error="did not start in 20 s")

# ------------------------------------------------------------------ HTTP
def state():
    nm = names(); out = []
    for p in PAT:
        el, rem = eta(p)
        out.append(dict(code=p["code"], name=nm.get(p["code"], ""), cohort=p.get("cohort", ""), mode=p.get("mode"), anatomy=p.get("anatomy"),
                        status=p["status"], step=p.get("step", ""), steps_done=list(p.get("steps_done", {}).keys()), error=p.get("error", ""),
                        elapsed=el, remaining=rem, has_qc=os.path.exists(f"{AD}/qc/{p['code']}.png"), version=p.get("version", ""),
                        radiologist=p.get("radiologist", ""), grade_R=p.get("grade_R", ""), grade_L=p.get("grade_L", ""),
                        step_times={k: round(v) for k, v in p.get("steps_done", {}).items()}))
    q = [x for x in out if x["status"] in ("waiting", "running", "paused")]
    return dict(patients=out, queue=dict(n=len(q), remaining=sum(x["remaining"] for x in q), running=CUR["code"]),
                settings=SET, version=version(), cohorts=sorted(set(jload("cohorts.json", [])) | {p.get("cohort", "") for p in PAT} - {""}), steps=STEPS)

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, obj, code=200, ctype="application/json", fname=None):
        b = obj if isinstance(obj, bytes) else json.dumps(obj, default=str).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b))); self.send_header("Cache-Control", "no-store")
        if fname: self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
        self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/": return self.send(open(f"{HERE}/css_app.html", "rb").read(), ctype="text/html; charset=utf-8")
            if u.path == "/api/state": return self.send(state())
            if u.path == "/api/preflight": return self.send(preflight())
            if u.path == "/api/log":
                f = f"{AD}/logs/{q['code']}.log"; return self.send(dict(text=open(f).read()[-30000:] if os.path.exists(f) else "(no log yet)"))
            if u.path == "/api/qc":
                f = f"{AD}/qc/{q['code']}.png"; return self.send(open(f, "rb").read(), ctype="image/png")
            if u.path == "/api/results": return self.send(results())
            if u.path == "/api/export.xlsx": return self.send(export_xlsx(), ctype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", fname="cSS_results.xlsx")
            if u.path == "/api/grades_template.xlsx": return self.send(grades_template(), ctype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", fname="grades_template.xlsx")
            if u.path == "/api/packets":
                return self.send(sorted(os.path.basename(d) for d in glob.glob(f"{B}/reference_audit/whole_scan/*") if os.path.isdir(d)))
            return self.send(dict(error="not found"), 404)
        except Exception as e: return self.send(dict(error=f"{type(e).__name__}: {e}"), 500)
    def do_POST(self):
        if self.headers.get("X-CSS-App") != "1": return self.send(dict(error="forbidden"), 403)
        u = urlparse(self.path); d = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        try:
            if u.path == "/api/pick": path, err = pick(d.get("kind", "folder"), d.get("prompt", "Choose")); return self.send(dict(path=path, error=err))
            if u.path == "/api/scan":
                if not os.path.isdir(d["path"]): return self.send(dict(error=f"not a folder: {d['path']}"))
                return self.send(dict(patients=scan(d["path"], d.get("mode", "single"), d.get("folder_is", "code"), d.get("rule", "whole"))))
            if u.path == "/api/grades": return self.send(read_grades(d["path"]))
            if u.path == "/api/queue": return self.send(add_to_queue(d["patients"], d["settings"]))
            if u.path == "/api/settings":
                with LOCK:
                    for k, v in d.items():
                        if k == "features": SET["features"].update(v)
                        else: SET[k] = v
                    jsave("settings.json", SET)
                caffeinate(bool(CUR["code"])); return self.send(dict(ok=True))
            if u.path == "/api/control":
                p = pget(d["code"]); a = d["action"]
                if not p: return self.send(dict(error="unknown code"))
                pr = CUR["proc"] if CUR["code"] == p["code"] else None
                if a == "pause" and p["status"] == "running":
                    p["status"] = "paused"
                    if pr: os.killpg(pr.pid, signal.SIGSTOP)
                elif a == "resume" and p["status"] == "paused":
                    p["status"] = "running"
                    if pr: os.killpg(pr.pid, signal.SIGCONT)
                elif a == "stop" and p["status"] in ("running", "paused"):
                    p.update(status="stopped", error="stopped by you")
                    if pr: os.killpg(pr.pid, signal.SIGCONT); os.killpg(pr.pid, signal.SIGTERM)
                elif a in ("retry", "rerun") and p["status"] in ("failed", "stopped", "done"): p.update(status="waiting", error="", steps_done={})
                elif a == "remove" and p["status"] in ("waiting", "failed", "stopped"): PAT.remove(p)
                else: return self.send(dict(error=f"cannot {a} while {p['status']}"))
                save_pat(); return self.send(dict(ok=True))
            if u.path == "/api/edit":
                p = pget(d["code"])
                if not p: return self.send(dict(error="unknown code"))
                if "name" in d: set_name(p["code"], d["name"])
                if d.get("new_code") and d["new_code"] != p["code"]:
                    nc = d["new_code"]
                    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,32}", nc) or pget(nc): return self.send(dict(error="invalid or duplicate code"))
                    if p["status"] != "waiting": return self.send(dict(error="a code can only be changed before processing starts (results are filed under it)"))
                    nm = names().get(p["code"], ""); set_name(nc, nm, old_code=p["code"]); p["code"] = nc
                for k in ("radiologist", "grade_R", "grade_L"):
                    if k in d: p[k] = d[k]
                save_pat(); write_grades_file(); return self.send(dict(ok=True))
            if u.path == "/api/install": return self.send(install_zip(d["path"]))
            if u.path == "/api/rollback": return self.send(rollback())
            if u.path == "/api/review": return self.send(launch_child("review", d, 8765))
            if u.path == "/api/blind":
                if d.get("new_packet"):
                    r = subprocess.run([sys.executable, f"{B}/reference_audit/ws_prepare.py", d["packet"], "--studies", ",".join(d["codes"]), "--readers", d["reader"]],
                                       capture_output=True, text=True, env=fs_env())
                    if r.returncode: return self.send(dict(ok=False, error=(r.stderr or r.stdout)[-400:]))
                return self.send(launch_child("blind", d, 8790))
            if u.path == "/api/share": return self.send(dict(ok=True, path=share_package(d["codes"])))
            if u.path == "/api/quit":
                if CUR["code"] and not d.get("force"): return self.send(dict(ok=False, error="a patient is processing - stop it first, or quit anyway (it restarts from the beginning next time)"))
                self.send(dict(ok=True)); threading.Timer(0.5, lambda: os._exit(0)).start(); return
            if u.path == "/api/open":
                if mac(): subprocess.run(["open", d["path"]])
                return self.send(dict(ok=True))
            return self.send(dict(error="not found"), 404)
        except Exception as e: return self.send(dict(error=f"{type(e).__name__}: {e}"), 500)

def open_window(url):
    """own window if pywebview is installed; else Chrome / Edge in app mode; else the default browser"""
    try:
        import webview  # noqa
        return "webview"
    except ImportError: pass
    if mac():
        for app in ("Google Chrome", "Microsoft Edge", "Brave Browser"):
            if os.path.exists(f"/Applications/{app}.app"):
                subprocess.Popen(["open", "-na", app, "--args", f"--app={url}", "--window-size=1400,900"]); return app
    webbrowser.open(url); return "browser"

if __name__ == "__main__":
    a = sys.argv[1:]; port = int(a[a.index("--port") + 1]) if "--port" in a else 8800
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", port)) == 0:             # already running: just show it
            if "--no-window" not in a: open_window(f"http://127.0.0.1:{port}/")
            sys.exit(0)
    threading.Thread(target=worker, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", port), H); url = f"http://127.0.0.1:{port}/"
    print(f"cSS Pipeline app: {url}  (CSS_BASE={B})", flush=True)
    how = None if "--no-window" in a else open_window(url)
    if how == "webview":
        import webview
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        webview.create_window("cSS Pipeline", url, width=1400, height=900); webview.start()
    else:
        try: srv.serve_forever()
        except KeyboardInterrupt: pass
