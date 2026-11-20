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
sys.path.insert(0, os.path.join(HERE, "guard")); import css_writeguard as WG      # v5.14.2-rc2: central production write guard
EXPERIMENTAL = os.environ.get("CSS_EXPERIMENTAL") == "1"
if EXPERIMENTAL:
    _okb, _why = WG.check_base(B)
    if not _okb: sys.exit(f"cSS experimental app refused to start: project folder {_why}")
    WG.install()                                     # every write in this process (and, via PYTHONPATH, in every Python child) is checked
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
SET = dict(dict(awake=True, theme="dark", backup_dir="", freesurfer_home=os.environ.get("FREESURFER_HOME", ""), threads=4, parallel=1, auto_path=True, auto_retry=True, rerun_mode="choose",
                features=dict(unified_score=False, duplicate_check=True, preflight=True, qc_snapshot=True, notify=True, version_stamp=True, share=True, backup=True,
                              name_warning=False)), **jload("settings.json", {}))
PAT = jload("patients.json", [])
for p in PAT:                                            # resume after a restart: interrupted runs go back to the queue
    if p.get("status") in ("running", "paused"): p.update(status="waiting", step="", note="restarted after the app was closed")
    p.pop("pm_run", None)                                # its history record is marked interrupted by PM.recover_all below
    p.setdefault("pathway", "recon" if p.get("anatomy") == "recon" else (p.get("reg_method") or "synthseg"))
    if p.get("uscore_status") in ("pending", "running"):   # v5.14-gui recovery: an unified job cut off by a restart is marked, never left "running"
        p.update(uscore_status="interrupted", uscore_error="the app was closed during the unified step - press 'Score patient' to run it again")
def save_pat(): jsave("patients.json", PAT)
import processing_manager as PM                       # v5.14-gui Previous Processing Manager
try: PM_RECOVERED = PM.recover_all(B)                 # runs left "running" by a closed app become "interrupted" (previous outputs restored)
except Exception as _e: PM_RECOVERED = {"error": str(_e)}
try: PM_IMPORTS_ROLLED_BACK = PM.recover_imports(B)  # imports cut off by a crash / quit are rolled back (nothing half-imported stays)
except Exception as _e: PM_IMPORTS_ROLLED_BACK = [f"error: {_e}"]
PM_JOBS = {}                                          # code -> {"run_id", "stage", "started"} while a Processing Manager run works
def _pm_code(c): return c if re.fullmatch(r"[A-Za-z0-9_\-]{1,32}", c or "") else None
def proc_get(op, q):
    if op == "studies":
        out = []
        for c in PM.studies_on_disk(B):
            st = PM.Study(B, c); act = st.active_manifest() or {}; h = st.history()
            out.append(dict(code=c, in_app=pget(c) is not None, runs=len(h), active=act.get("run_id"), last_status=(h[-1]["status"] if h else None),
                            has_fs=os.path.isdir(os.path.join(st.SD, c)), has_candidates=os.path.exists(f"{B}/review/{c}_candidates.csv"), busy=c in PM_JOBS))
        return dict(ok=True, studies=out, recovered=PM_RECOVERED, imports_rolled_back=PM_IMPORTS_ROLLED_BACK)
    if op == "scan_source":
        src = os.path.expanduser(q.get("path", ""))
        if not os.path.isdir(src) or os.path.realpath(src) == os.path.realpath(B): return dict(ok=False, error="choose another project folder (not this one)")
        here = set(PM.studies_on_disk(B))
        return dict(ok=True, studies=[dict(code=c, has_fs=os.path.isdir(f"{src}/subjects/{c}"), has_candidates=os.path.exists(f"{src}/review/{c}_candidates.csv"),
                                         here=c in here) for c in PM.studies_on_disk(src)])
    code = _pm_code(q.get("code"))
    if not code: return dict(ok=False, error="bad code")
    st = PM.Study(B, code)
    if op == "audit": return dict(ok=True, busy=PM_JOBS.get(code), **st.audit())
    if op == "history": return dict(ok=True, runs=st.history(), active=(st.active_manifest() or {}).get("run_id"), recovered=PM_RECOVERED, busy=PM_JOBS.get(code))
    if op == "log":
        rid = q.get("run_id", "")
        if not re.fullmatch(r"r[0-9\-x]+", rid): return dict(ok=False, error="bad run id")
        f = os.path.join(B, "runs", code, rid, "run.log")
        return dict(ok=True, log=open(f, errors="replace").read()[-6000:] if os.path.exists(f) else "")
    return dict(ok=False, error="unknown")

PM_STEP = {"align": "align_seg.py", "detect": "detect_css.py"}
def pm_execute(code, plan, note):
    """runs plan['run'] for an existing study in the background: align / detect (+ surface features) / unified.
    Anatomy and registration are NOT run here: they need the raw series and run_css.sh (Patients -> Re-run, which reuses a
    finished FreeSurfer automatically)."""
    st = PM.Study(B, code); env = fs_env(); sw = dict(pipeline=version(), python=platform.python_version())
    man = st.start_run(plan, note, software=sw); rid = man["run_id"]; logf = os.path.join(B, man["log"])
    PM_JOBS[code] = dict(run_id=rid, stage="", started=time.time())
    def run():
        ok, msg = True, ""
        try:
            for stage in plan["run"]:
                PM_JOBS[code]["stage"] = stage; st.stage_state(rid, stage, "running")
                if stage in PM_STEP:
                    cmd = [sys.executable, f"{SC}/{PM_STEP[stage]}", code] + (["-2.5", "85", "3"] if stage == "detect" else [])
                    rc = run_logged(cmd, logf, env, code="pm:" + code)
                    if rc != 0:
                        why = {3: "case cannot be scored (QC insufficient quality)", 5: "registration gate: registration not acceptable"}.get(rc, f"exit {rc}")
                        ok, msg = False, f"{stage} failed: {why}"; st.stage_done(rid, stage, False, why); break
                    if stage == "detect" and os.path.exists(f"{st.SD}/{code}/surf/lh.pial") and os.path.exists(f"{B}/work/{code}_swi2t1.lta"):
                        if run_logged([sys.executable, f"{SC}/surface_features.py", code], logf, env, code="pm:" + code) != 0:
                            open(logf, "a").write("WARNING: surface_features.py failed - detection results are unaffected\n")
                    if stage == "detect":
                        e_ = ai_score(code, env); open(logf, "a").write("AI score (green-band candidates, not validated): " + ("written\n" if not e_ else "not available: " + e_ + "\n"))
                elif stage == "unified":
                    import unified_gui as UG
                    r = UG.score_patient(code); open(logf, "a").write(f"\nunified: {json.dumps(r, default=str)[:600]}\n")
                    if pget(code): pget(code).update(uscore=r, uscore_status=r.get("status", "failed"), uscore_error=r.get("error", "")); save_pat()
                    if r.get("status") != "completed": ok, msg = False, "unified failed: " + str(r.get("error", ""))[:300]; st.stage_done(rid, stage, False, msg); break
                else:
                    ok, msg = False, f"{stage} cannot run from the Processing Manager (needs the raw series): use Patients -> Re-run"; st.stage_done(rid, stage, False, msg); break
                st.stage_done(rid, stage)
        except Exception as e:
            ok, msg = False, f"error: {str(e)[:300]}"
        try:
            if not ok: msg += "\nlog tail:\n" + (open(logf, errors="replace").read()[-1500:] if os.path.exists(logf) else "")
            st.finish_run(rid, ok, msg)
            p = pget(code)
            if ok and p and "detect" in plan["run"]:
                if SET["features"].get("qc_snapshot"): qc_snapshot(code)
                save_pat()
                try: write_results_file()
                except Exception: pass
        finally: PM_JOBS.pop(code, None)
    threading.Thread(target=run, daemon=True).start()
    return rid

def pm_begin_full(p):
    """the normal pipeline (Add patients / Re-run) is recorded as a run too: the current outputs are archived first and put back if
    it fails. FreeSurfer is NOT renamed (prep_anat reuses a finished recon itself). Never blocks processing."""
    if FAKE: return
    try:
        st = PM.Study(B, p["code"])
        m = st.start_run(dict(run=list(PM.STAGES), reuse=[]), "full pipeline (" + ("re-run" if st.history() else "first processing") + ")",
                         software=dict(pipeline=version(), pathway=p.get("pathway", "")), rename_fs=False)
        p["pm_run"] = m["run_id"]
    except Exception as e: p["pm_run"] = ""; print("processing history not recorded:", e, flush=True)
def pm_end_full(p, ok, msg=""):
    rid = p.pop("pm_run", "")
    if not rid: return
    try:
        st = PM.Study(B, p["code"])
        for s_ in ("anatomy", "registration", "align", "detect"): st.stage_state(rid, s_, "done" if ok else "not completed")
        st.stage_state(rid, "unified", "runs separately after 'done' (opt-in)" if ok else "not run")
        st.finish_run(rid, ok, msg)
    except Exception as e: print("processing history not updated:", e, flush=True)
def proc_post(op, d):
    if op == "link":
        src = os.path.expanduser(d.get("source", "")); out = []
        for c in d.get("codes", []):
            if not _pm_code(c): out.append(dict(code=c, ok=False, error="bad code")); continue
            try:
                r = PM.import_study(src, B, c); fsr = r["freesurfer"] or {}
                out.append(dict(code=c, ok=True, copied=len(r["copied"]), historical=len(r["historical"]), freesurfer=bool(fsr),
                                fs_method=fsr.get("method", ""), fs_files=fsr.get("files", 0), verified=r["verified"]))
                with LOCK:
                    if not pget(c):                      # visible in Results / reviewer; processing of a linked study goes through the Processing tab
                        PAT.append(dict(code=c, cohort="linked", anatomy="recon" if r["freesurfer"] else "synthseg", mode="semi", pathway="recon" if r["freesurfer"] else "synthseg",
                                        series={}, step="", steps_done={}, added=time.time(), status="done", linked=True,
                                        note="imported from another project (verified copy, FreeSurfer included); new runs: Processing tab (raw series not copied)"))
                        save_pat()
            except Exception as e: out.append(dict(code=c, ok=False, error=str(e)[:200]))
        return dict(ok=all(x["ok"] for x in out), results=out)
    code = _pm_code(d.get("code"))
    if not code: return dict(ok=False, error="bad code")
    st = PM.Study(B, code)
    try:
        if op == "plan": return st.plan(d.get("choice", "selective"), d.get("rerun_from"), bool(d.get("force_anatomy")))
        if op == "adopt": return dict(ok=True, run=st.adopt_existing(d.get("note", "confirmed by the user")))
        if code in PM_JOBS or any(p.get("code") == code and p.get("status") == "running" for p in PAT):
            return dict(ok=False, error="this study is being processed; wait until it finishes")
        if op == "set_active":
            if d.get("confirm") is not True: return dict(ok=False, needs_confirm=True, error="making another run active replaces the current outputs (they stay archived): confirm")
            st.set_active(d["run_id"]); return dict(ok=True)
        if op in ("start", "resume"):
            pl = st.resume_plan(d["run_id"]) if op == "resume" else st.plan(d.get("choice", "selective"), d.get("rerun_from"), bool(d.get("force_anatomy")))
            if not pl.get("ok"): return pl
            if not pl["run"]: return dict(ok=False, error=pl.get("note") or "nothing to run")
            early = [s for s in pl["run"] if s in ("anatomy", "registration")]
            if early: return dict(ok=False, error=f"{', '.join(early)} must be re-run from the raw series: Patients -> Re-run (a finished compatible FreeSurfer is reused automatically)")
            return dict(ok=True, run_id=pm_execute(code, pl, d.get("note", op)), run=pl["run"], reuse=pl["reuse"])
    except (ValueError, KeyError) as e: return dict(ok=False, error=str(e))
    return dict(ok=False, error="unknown")
def reread_failures():
    """failures written by an older app version ('processing failed') are explained again from the run log"""
    for p in PAT:
        if p.get("status") == "failed" and "processing failed" in p.get("error", ""):
            try:
                e = explain(p["code"], "failed")
                if e != p["error"]:
                    p["error"] = e
                    if "do not line up" in e and not p.get("tried"):
                        m = re.search(r"shift ([\d.?]+) mm", e); p["tried"] = [dict(pathway=p.get("pathway", "synthseg"), shift=m.group(1) if m else "?")]
            except Exception: pass
    save_pat()
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
        e.setdefault("SUBJECTS_DIR", f"{B}/subjects")
    lic = find_license(fh, e)
    if lic: e["FS_LICENSE"] = lic
    extra = [os.path.join(sys.prefix, "bin"), "/opt/homebrew/bin", "/usr/local/bin", os.path.expanduser("~/bin"),
             os.path.expanduser("~/.local/bin"), "/Applications/MRIcroGL.app/Contents/Resources", "/Applications/MRIcroGL.app/Contents/MacOS"]
    have = e.get("PATH", "").split(":")
    e["PATH"] = ":".join([p for p in extra if os.path.isdir(p) and p not in have] + have)
    e["CSS_BASE"] = B; e["CSS_THREADS"] = str(SET.get("threads", 4)); e.update(PIPE_ENV)
    return e
def which(x, env): return shutil.which(x, path=env.get("PATH"))
def license_candidates(fh, e=None):
    e = e or os.environ; h = os.path.expanduser("~")
    c = [SET.get("fs_license", ""), e.get("FS_LICENSE", ""), f"{h}/license.txt", f"{h}/.license", f"{h}/freesurfer_license.txt", f"{h}/freesurfer/license.txt",
         f"{h}/css_project/license.txt", f"{h}/Documents/license.txt", f"{h}/Downloads/license.txt", f"{fh}/license.txt" if fh else "", f"{fh}/.license" if fh else ""]
    if os.path.exists(f"{h}/.zshrc"):
        import re as _re
        for m in _re.finditer(r"FS_LICENSE=[\"']?([^\"'\s]+)", open(f"{h}/.zshrc", errors="ignore").read()): c.insert(2, os.path.expandvars(os.path.expanduser(m.group(1))))
    return [x for x in dict.fromkeys(c) if x]
def find_license(fh, e=None):
    for x in license_candidates(fh, e):
        if os.path.isfile(x) and os.access(x, os.R_OK): return x
    return ""

def sysinfo():
    """chip, cores, memory total / used (GB), free disk; recommended number of patients at the same time"""
    total = used = 0.0; chip = platform.processor() or platform.machine()
    try:
        if mac():
            total = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout.strip() or 0) / 1e9
            chip = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True).stdout.strip() or chip
            vm = subprocess.run(["vm_stat"], capture_output=True, text=True).stdout
            ps = int(re.search(r"page size of (\d+)", vm).group(1)) if re.search(r"page size of (\d+)", vm) else 16384
            pg = lambda k: int(re.search(rf"{k}:\s+(\d+)", vm).group(1)) if re.search(rf"{k}:\s+(\d+)", vm) else 0
            used = (pg("Pages active") + pg("Pages wired down") + pg("Pages occupied by compressor")) * ps / 1e9
        else:
            m = {l.split(":")[0]: int(l.split()[1]) for l in open("/proc/meminfo") if len(l.split()) > 1}
            total = m["MemTotal"] / 1e6; used = (m["MemTotal"] - m.get("MemAvailable", m.get("MemFree", 0))) / 1e6
    except Exception: pass
    cores = os.cpu_count() or 1; disk = shutil.disk_usage(B).free / 1e9
    try: load = os.getloadavg()[0] / cores * 100
    except Exception: load = 0
    rec = max(1, min(4, cores // 4, int((total - 6) // 12) if total else 1))      # base: SynthSeg patients only
    return dict(chip=chip, cores=cores, mem_total=round(total, 1), mem_used=round(used, 1), mem_pct=round(100 * used / total) if total else 0,
                cpu_pct=round(min(load, 100)), disk_free=round(disk), recommended=rec, per_patient_gb=12)
MEM_YELLOW, MEM_RED = 70, 85        # % of memory: yellow = no new patient starts; red = warning + "Stop newest patient"

def recommend(si):
    """recommended patients at the same time for the pathways actually waiting / running (memory budget = total - 6 GB)"""
    q = [p for p in PAT if p["status"] in ("waiting", "running", "paused", "starting") and p.get("pathway") not in SOLO]
    if not q or not si["mem_total"]: return si["recommended"], "", {}
    q.sort(key=lambda p: (p["status"] == "waiting", p.get("added", 0)))
    budget, cores, n = si["mem_total"] - 6, si["cores"], 0
    for p in q:
        m, c = PW_MEM.get(p.get("pathway"), 12), PW_CORES.get(p.get("pathway"), 4)
        if m > budget or (n and c > cores): break
        budget -= m; cores -= c; n += 1
    n = max(1, min(4, n))
    mix = {}
    for p in q: mix[PATHWAYS.get(p.get("pathway"), "SynthSeg")] = mix.get(PATHWAYS.get(p.get("pathway"), "SynthSeg"), 0) + 1
    why = ", ".join(f"{v} {k}" for k, v in mix.items())
    return n, why, mix

def preflight():
    env = fs_env(); out = []
    du = shutil.disk_usage(B); free = du.free / 1e9
    out.append(dict(item="Disk space", ok=free > 15, detail=f"{free:.0f} GB free" + ("" if free > 15 else " - at least 15 GB recommended")))
    out.append(dict(item="Pipeline", ok=os.path.exists(f"{SC}/run_css.sh"), detail=version()))
    fh = env.get("FREESURFER_HOME", "")
    out.append(dict(item="FreeSurfer", ok=bool(fh) and os.path.isdir(fh), detail=fh or "not found - choose its folder in Setup"))
    lic = env.get("FS_LICENSE", "")
    if lic: out.append(dict(item="FreeSurfer licence", ok=True, detail=f"{lic} (readable)"))
    else:
        unreadable = [x for x in license_candidates(fh, env) if os.path.isfile(x)]
        out.append(dict(item="FreeSurfer licence", ok=False, fix="licence", fix_path=unreadable[0] if unreadable else "",
                        detail=(f"{unreadable[0]} exists but this user cannot read it" if unreadable else "license.txt not found")))
    for tool in ("mri_synthseg", "mri_convert", "dcm2niix"):
        w = which(tool, env)
        out.append(dict(item=tool, ok=bool(w), detail=w or ("not found - press Install" if tool == "dcm2niix" else "not on the FreeSurfer path"),
                        fix="dcm2niix" if tool == "dcm2niix" and not w else ""))
    try:
        import numpy, scipy, nibabel, pandas, skimage  # noqa
        out.append(dict(item="Python packages", ok=True, detail=f"python {platform.python_version()}"))
    except ImportError as e: out.append(dict(item="Python packages", ok=False, detail=str(e)))
    try:
        import webview  # noqa
        out.append(dict(item="Own app window (Dock icon)", ok=True, detail="pywebview installed - the app opens in its own window with the cSS icon"))
    except ImportError:
        out.append(dict(item="Own app window (Dock icon)", ok=False, fix="pywebview",
                        detail="optional - without it the app opens in Chrome and the Dock shows Chrome. Install, then quit and reopen the app"))
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
    t1, t1why, skipped = SD.choose_t1(ser)                  # best usable T1 (3-D, <= 1.2 mm, whole brain); neck / partial series skipped
    if t1: pick_["T1"] = t1
    else: pick_.pop("T1", None)
    r["t1_desc"] = t1why; r["t1_skipped"] = skipped
    check_pathway(r, ser)
    if "SWI" not in pick_: r["warnings"].append("no SWI found - choose one")
    t1 = next((x for x in ser if x["path"] == pick_.get("T1")), None)
    if t1 and t1.get("voxel") and SD._res(t1) <= 1.5: t1 = None          # 3-D T1: no 2-D warning
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
PATHWAYS = {"synthseg": "SynthSeg", "coreg_masked": "Fast re-registration", "synthmorph": "SynthMorph", "recon": "recon-all", "swi_only": "SWI-only"}
SOLO = ("swi_only", "synthmorph")       # high / unknown memory: always run alone
PW_TIME = {"synthseg": "~4 min", "coreg_masked": "~4 min", "synthmorph": "~5 min", "recon": "~2-3 h", "swi_only": "~30 min"}
PW_MEM = {"synthseg": 12, "coreg_masked": 12, "recon": 5}          # GB per patient (estimates; SOLO pathways run alone)
PW_CORES = {"synthseg": 4, "coreg_masked": 4, "recon": 2}
RETRY_ORDER = ["coreg_masked", "synthmorph", "recon", "swi_only"]
def next_rec(p):
    """recommended next pathway after a failed registration: first in RETRY_ORDER not tried yet"""
    tried = {t["pathway"] for t in p.get("tried", [])} | {p.get("pathway")}
    return next((x for x in RETRY_ORDER if x not in tried), "recon")
def check_pathway(r, ser):
    """recommended pathway + check result for one scanned patient (header only, nothing is converted)"""
    pk = r["chosen"]; sw = next((x for x in ser if x["path"] == pk.get("SWI")), {}); t1 = next((x for x in ser if x["path"] == pk.get("T1")), {})
    r["overlap"] = ""
    if not pk.get("SWI"):
        r.update(check="cannot", pathway="", pathway_reason="needs an SWI - will not be queued"); return
    if not pk.get("T1"):
        why = "no T1 found" if not r["t1_skipped"] else "no usable T1 (" + "; ".join(f"{x['name']}: {x['reason']}" for x in r["t1_skipped"][:2]) + ")"
        r.update(check="changed", pathway="swi_only", pathway_reason=f"{why} -> SWI-only, runs last, alone"); return
    a, b = sw.get("study_uid") or sw.get("study_date"), t1.get("study_uid") or t1.get("study_date")
    if sw.get("study_date") and t1.get("study_date") and sw["study_date"] != t1["study_date"]:
        r["overlap"] = f"different date ({t1['study_date'][:4]} vs {sw['study_date'][:4]})" if t1["study_date"][:4] != sw["study_date"][:4] else "different date"
        r.update(check="look", pathway="synthseg", pathway_reason="check the T1 is from the same study as the SWI"); return
    r["overlap"] = "same visit" if (a and b and a == b) else ""
    if r["t1_skipped"]:
        r.update(check="changed", pathway="synthseg", pathway_reason="other T1 chosen automatically (" + "; ".join(f"skipped {x['name']}: {x['reason']}" for x in r["t1_skipped"][:2]) + ")"); return
    r.update(check="ok", pathway="synthseg", pathway_reason="")

def patient_like_subfolders(path):
    """sub-folders that each hold their own MRI series - a sign the chosen folder is a COHORT, not one patient"""
    subs = [os.path.join(path, d) for d in sorted(os.listdir(path)) if os.path.isdir(os.path.join(path, d)) and not d.startswith(".")]
    hits = []
    for d in subs[:60]:
        ser = SD.scan(d, max_depth=3)
        if any(x.get("type") == "SWI" for x in ser) or len(ser) >= 3: hits.append(os.path.basename(d))
    return hits
def scan(path, mode, folder_is, rule):
    if mode == "single":
        many = patient_like_subfolders(path)
        r = scan_patient(path, folder_is, rule)
        if len(many) >= 2:
            r["multi_patient"] = many
            r["warnings"].insert(0, f"this folder holds {len(many)} patient folders - use Batch")
        return [r]
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
    if st.get("results_dir"):
        okd, why = verify_local_dest(st["results_dir"])
        if not okd: errs.append(f"results folder refused: {why}")
    if errs: return dict(ok=False, errors=errs)
    added = []
    with LOCK:
        for it in items:
            code = it.get("code") or next_code()
            if st.get("store_names") and it.get("name"): set_name(code, it["name"])
            pw = it.get("pathway") or ("recon" if st.get("anatomy") == "recon" else "synthseg")
            rec = it.get("pathway_rec") or pw
            p = dict(code=code, cohort=st.get("cohort", ""), anatomy="recon" if pw == "recon" else "synthseg", mode=st.get("mode", "semi"), pathway=pw,
                     results_dir=st.get("results_dir", ""), radiologist=it.get("radiologist", ""), grade_R=it.get("grade_R", ""), grade_L=it.get("grade_L", ""),
                     series=it["chosen"], fingerprint=it.get("fingerprint", ""), step="", steps_done={}, added=time.time(),
                     status="decision" if (rec != (st.get("anatomy") or "synthseg") and not SET.get("auto_path", True) and it.get("decided") is not True) else "waiting",
                     path_note=(it.get("pathway_reason") or "") if rec != (st.get("anatomy") or "synthseg") or it.get("check") in ("changed", "look") else "", path_ack=False,
                     source_folder_hash=hashlib.sha1(it.get("folder", "").encode()).hexdigest()[:12])     # the folder path itself is not stored (may hold a name)
            apply_pathway(p, pw); PAT.append(p); added.append(code)
            coh = jload("cohorts.json", [])
            if p["cohort"] and p["cohort"] not in coh: coh.append(p["cohort"]); jsave("cohorts.json", coh)
        save_pat()
    write_grades_file()
    return dict(ok=True, added=added)
def apply_pathway(p, pw):
    """set the run options for a pathway (SWI-only drops the T1 / FLAIR; registration methods go to prep_anat.sh)"""
    p["pathway"] = pw; p["anatomy"] = "recon" if pw == "recon" else "synthseg"; p.pop("reg_method", None)
    if pw in ("coreg_masked", "synthmorph"): p["reg_method"] = pw
    if pw == "swi_only":
        p.setdefault("series_t1", {k: v for k, v in p["series"].items() if k in ("T1", "FLAIR")})
        p["series"] = {k: v for k, v in p["series"].items() if k not in ("T1", "FLAIR")}
    elif p.get("series_t1"): p["series"].update(p.pop("series_t1"))
def move_bad_registration(p):
    """a misregistered T1 must not be reused: its labels are moved aside (kept, renamed), never deleted"""
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    for f in (f"{B}/work/{p['code']}_t1seg_swispace.nii.gz", f"{B}/work/{p['code']}_swi2t1.lta", f"{B}/work/{p['code']}_brainmask.nii.gz"):
        if os.path.exists(f): os.replace(f, f"{f}.bad_registration_{stamp}")

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

CUR = dict(caff=None, hold="", mem_wait=False)      # hold: queue paused because of a setup problem (licence, FreeSurfer, disk)
PROCS = {}            # code -> running subprocess (several patients can run at the same time)
RUNNING = {}          # code -> worker thread
IMPORT_LOCK = threading.Lock()   # cohort.py import rewrites review/cohort_import.csv: one import (and one run start) at a time
def caffeinate(on):
    if not mac(): return
    if on and SET.get("awake") and CUR["caff"] is None:
        CUR["caff"] = subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])
    if (not on or not SET.get("awake")) and CUR["caff"] is not None:
        CUR["caff"].terminate(); CUR["caff"] = None

def run_logged(cmd, logf, env, on_line=None, code=None):
    with open(logf, "a") as lf:
        lf.write(f"\n$ {' '.join(cmd)}\n"); lf.flush()
        pr = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, text=True, start_new_session=True, bufsize=1)
        PROCS[code] = pr
        for line in pr.stdout:
            lf.write(line); lf.flush()
            if on_line: on_line(line)
        rc = pr.wait(); PROCS.pop(code, None)
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
    if p.get("reg_method"): env["CSS_REG_METHOD"] = p["reg_method"]          # prep_anat.sh registration method (default mri_coreg)
    p.update(status="running", started=time.time(), error="", steps_done={}, version=version() if SET["features"].get("version_stamp") else "")
    pm_begin_full(p)
    env["CSS_THREADS"] = str(max(2, int(SET.get("threads", 4)) // max(1, min(int(SET.get("parallel", 1)), 4)) if int(SET.get("parallel", 1)) > 1 else int(SET.get("threads", 4))))
    save_pat()
    if FAKE:
        for s in STEPS:
            step_begin(p, s); time.sleep(float(os.environ.get("CSS_APP_FAKE_STEP_S", "0.3")))
            while p["status"] == "paused": time.sleep(0.2)
            if p["status"] in ("stopped", "waiting"): return
            step_end(p, s)
        if os.environ.get("CSS_APP_FAKE_FAIL") == code and not p.get("reg_method"):
            return fail(p, explain_reg(4.3))
        p.update(status="done", finished=time.time(), step=""); save_pat(); return
    # 1 import (cohort.py import, merged into review/cohort_import.csv instead of replacing it)
    step_begin(p, "import")
    d2n = which("dcm2niix", env)
    if not d2n and any(os.path.isdir(v) for v in p["series"].values()):
        return fail(p, "dcm2niix (the DICOM converter) is not installed - Home -> Setup check -> Install dcm2niix, then Retry")
    with IMPORT_LOCK:
        st = stage(p); tab = f"{B}/review/cohort_import.csv"; bak = None
        if os.path.exists(tab): bak = open(tab).read()
        cmd = [sys.executable, f"{SC}/cohort.py", "import", os.path.dirname(st), "--ids", code] + (["--dcm2niix", d2n] if d2n else [])
        dj = which("dcmdjpeg", env)
        if dj: cmd += ["--dcmdjpeg", dj]
        rc = run_logged(cmd, logf, env, code=code)
        if bak is not None and os.path.exists(tab):
            import pandas as pd
            new = pd.read_csv(tab, dtype=str); old = pd.read_csv(io.StringIO(bak), dtype=str)
            pd.concat([old[~old.study_id.isin(new.study_id)], new]).to_csv(tab + ".tmp", index=False); os.replace(tab + ".tmp", tab)
    if p["status"] in ("stopped", "waiting"): return
    if rc != 0: return fail(p, f"import failed (exit {rc}) - see the log")
    step_end(p, "import")
    # 2-4 anatomy, alignment, detection: cohort.py run (run_css.sh), progress from its step lines
    step_begin(p, "anatomy")
    IMPORT_LOCK.acquire(); held = [True]          # held until cohort.py run has read cohort_import.csv (its first output line)
    def on_line(line):
        if held[0]: held[0] = False; IMPORT_LOCK.release()
        if line.startswith("[2/4]") and p["step"] == "anatomy": step_end(p, "anatomy"); step_begin(p, "align")
        if line.startswith("[3/4]") and p["step"] in ("anatomy", "align"):
            if p["step"] == "anatomy": step_end(p, "anatomy"); step_begin(p, "align")
            step_end(p, "align"); step_begin(p, "detect")
    cmd = [sys.executable, f"{SC}/cohort.py", "run", "--ids", code, "--redo", "--allow-no-t1"] + (["--no-recon"] if p["anatomy"] == "synthseg" else [])
    try: rc = run_logged(cmd, logf, env, on_line, code=code)
    finally:
        if held[0]: held[0] = False; IMPORT_LOCK.release()
    if p["status"] in ("stopped", "waiting"): return
    runlog = f"{B}/logs/{code}_run.log"
    if os.path.exists(runlog):
        open(logf, "a").write(open(runlog).read()[-20000:]); txt = open(runlog).read()
        for ln in txt.splitlines(): on_line(ln + "\n")
    res = _cohort_status(code)
    if res == "unknown" and os.path.exists(f"{B}/review/{code}_candidates.csv") and os.path.getmtime(f"{B}/review/{code}_candidates.csv") > p["started"]: res = "ok"
    if rc != 0 or res != "ok": return fail(p, explain(code, res))
    if p["step"] != "detect": step_begin(p, "detect")
    step_end(p, "detect")
    # 5 QC snapshot, AI score (automatic mode), version stamp
    step_begin(p, "qc")
    if SET["features"].get("qc_snapshot"): qc_snapshot(code)
    p["ai_note"] = ai_score(code, env)              # AI score computed for every patient (labelled "AI only, not validated")
    copy_results(p); step_end(p, "qc")
    pm_end_full(p, True)
    p.update(status="done", finished=time.time(), step=""); save_pat(); notify("cSS Pipeline", f"{code} finished")
    try: write_results_file()
    except Exception as e: open(logf, "a").write(f"\nresults file not updated: {e}\n")
    queue_unified(p)                                # v5.14-gui: AFTER results are saved and the patient is done; background; opt-in
def _cohort_status(code):
    import pandas as pd
    p = f"{B}/review/cohort_run.csv"
    if not os.path.exists(p): return "unknown"
    t = pd.read_csv(p, dtype=str); t = t[t.study_id == code]
    return t.status.iloc[-1] if len(t) else "unknown"
def explain(code, status):
    log = open(f"{B}/logs/{code}_run.log").read()[-6000:] if os.path.exists(f"{B}/logs/{code}_run.log") else ""
    for pat, msg in ((r"license file .* do not have read permission|licen[cs]e.*permission", "FreeSurfer cannot read its licence file - Home -> Setup check -> fix the licence, then Retry all failed"),
                     (r"licen[cs]e file .*(not found|does not exist)|FS_LICENSE", "FreeSurfer licence not found - Home -> Setup check -> Choose licence file"),
                     (r"No space left", "the disk is full"),
                     (r"registration not acceptable|registration check|registration_ok|label shift .* > |exit 5\b", "REGISTRATION"),
                     (r"insufficient_quality|exit 3\b", "image quality too low for scoring (QC: insufficient quality)"),
                     (r"mri_convert could not read", "the SWI file could not be read by FreeSurfer (see the lines just above it in the log)"), (r"no SWI chosen", "no SWI series was chosen"),
                     (r"command not found|not found: mri_", "FreeSurfer tools not found - choose the FreeSurfer folder in Setup")):
        if re.search(pat, log, re.I):
            if msg == "REGISTRATION":
                m = re.search(r"label shift ([\d.]+) mm", log)
                return explain_reg(m.group(1) if m else "?")
            return msg
    app = open(f"{AD}/logs/{code}.log").read()[-4000:] if os.path.exists(f"{AD}/logs/{code}.log") else ""
    if "Traceback" in app:
        last = [l for l in app.strip().splitlines() if l.strip()][-1][:200]
        return f"the pipeline stopped with an error: {last} - open the log for details"
    return f"processing failed ({status}) - open the log for details"
GRADES = [(0.5, "A+"), (0.8, "A"), (1.0, "B+"), (1.5, "B"), (2.5, "C"), (1e9, "F")]
def qc_grade(p):
    """grade from the label shift (mm): A+ <= 0.5, A <= 0.8, B+ <= 1.0, B <= 1.5 (pass), C <= 2.5, F; one step lower when the QC
    status is low_confidence. -> (grade, tooltip) or ("", "")"""
    sh, st = None, ""
    try:
        j = json.load(open(f"{B}/review/{p['code']}_qc.json")); sh = j.get("label_shift_mm"); st = j.get("status", "")
        if j.get("registration_ok") is False and p["status"] != "done": sh = None
    except Exception: pass
    if p["status"] == "failed" and p.get("tried"):
        try: sh = float(p["tried"][-1]["shift"])
        except Exception: pass
    if sh is None: return "", ""
    sh = float(sh); i = next(k for k, (lim, _) in enumerate(GRADES) if sh <= lim)
    if st == "low_confidence_review" and i < len(GRADES) - 1 and (sh > 1.5 or i < 3): i += 1      # a passed registration stays >= B
    return GRADES[i][1], f"label shift {sh:.2f} mm" + (" · QC status low confidence (one grade lower)" if st == "low_confidence_review" else "") + \
        " · A+ <= 0.5 · A <= 0.8 · B+ <= 1.0 · B <= 1.5 (pass) · C <= 2.5 · F > 2.5 mm"
# ------------------------------------------------------------------ v5.14-gui: Unified (experimental) section (screens A and C)
def unified_get(op, q):
    import unified_gui as UG, gui_protocol as GP
    try:
        if op == "state":
            st = UG.state()
            st["enabled"] = bool(SET["features"].get("unified_score"))
            st["patients"] = [dict(code=p["code"], status=p["status"], unified=p.get("uscore_status", ""), error=p.get("uscore_error", ""),
                                   counts={k: (p.get("uscore") or {}).get(k) for k in ("css_compatible", "uncertain", "alternative_high_confidence")}) for p in PAT]
            return st
        if op == "audit": return json.load(open(f"{UG.OUT}/gui_audit.json")) if os.path.exists(f"{UG.OUT}/gui_audit.json") else dict(available=False)
        if op == "reliability": return UG.reliability()
        if op == "validation": return UG.validation()
        if op == "candidates": return dict(study=q["study"], candidates=UG.candidates(q["study"]))
        if op == "candidate": return UG.candidate(q["study"], int(q["cand"])) or dict(available=False)
        if op == "perturb": return UG.perturbation(q["study"], int(q["cand"]))
        if op == "log": return UG.joblog(q.get("job", ""))
        if op == "protocol": return GP.load()
        if op == "robustness": return json.load(open(f"{UG.OUT}/gui_robustness.json")) if os.path.exists(f"{UG.OUT}/gui_robustness.json") else dict(available=False)
        return dict(error=f"unknown {op}")
    except Exception as e:
        return dict(error=str(e)[-400:])
def unified_post(op, d):
    import unified_gui as UG, gui_protocol as GP
    try:
        if op == "enable":
            SET["features"]["unified_score"] = bool(d.get("on")); jsave("settings.json", SET); return dict(ok=True, enabled=SET["features"]["unified_score"])
        if op == "audit": return UG.start("audit", UG.audit)
        if op == "extract": return UG.extract(d.get("which", "all"))
        if op == "train": return UG.train()
        if op == "freeze": return dict(ok=True, **UG.freeze(d.get("confirm", "")))
        if op == "score": return UG.score_all()
        if op == "score_patient":
            p = next((x for x in PAT if x["code"] == d["code"]), None)
            if p is None or p["status"] != "done": return dict(ok=False, error="patient not finished")
            queue_unified(p, force=True); return dict(ok=True)
        if op == "robustness": return UG.robustness(int(d.get("seeds", 3)))
        if op == "export": return dict(ok=True, **UG.export())
        if op == "stop": return UG.stop(d.get("job", ""))
        if op == "protocol_run": return GP.run_auto(PAT, write_results_file, queue_unified)
        if op == "protocol_mark": return GP.mark(d["id"], d["result"], d.get("note", ""))
        if op == "protocol_save": return dict(ok=True, **GP.save_record())
        return dict(ok=False, error=f"unknown {op}")
    except Exception as e:
        return dict(ok=False, error=str(e)[-400:])
def last_activity(code):
    m = [os.path.getmtime(f) for f in (f"{AD}/logs/{code}.log", f"{B}/logs/{code}_run.log") if os.path.exists(f)]
    return max(m) if m else 0
def ai_score(code, env=None):
    """AI score (green-band candidates, not validated) -> review/ID_score_ai.json; never touches the reader's files"""
    r = subprocess.run([sys.executable, f"{HERE}/ai_score_cli.py", code], capture_output=True, text=True, env=env or fs_env())
    return "" if r.returncode == 0 else (r.stderr or r.stdout)[-300:]
UQ_LOCK = threading.Lock()                          # unified jobs run one at a time, in the background
def queue_unified(p, force=False):
    """v5.14-gui fail-safe: the experimental unified score runs only when enabled (Unified tab), only for a finished patient,
    after its original results were saved; status pending -> running -> completed / failed; 15-minute limit. It can never change
    the patient's status, its detector files, reader files or the original exports."""
    if not (SET["features"].get("unified_score") or force) or p.get("status") != "done": return
    p["uscore_status"] = "pending"; p["uscore_error"] = ""; save_pat()
    def run():
        with UQ_LOCK:
            p["uscore_status"] = "running"; p["uscore_started"] = time.time(); save_pat()
            try:
                import unified_gui as UG
                r = UG.score_patient(p["code"])
            except Exception as e:
                r = dict(status="failed", error=str(e)[:400])
            p["uscore"] = r; p["uscore_status"] = r.get("status", "failed"); p["uscore_error"] = r.get("error", ""); save_pat()
            try: write_results_file()
            except Exception: pass
    threading.Thread(target=run, daemon=True).start()
def ai_backfill():
    """finished patients without an AI score get one (in the background, at start and after each finished patient)"""
    for p in list(PAT):
        if p["status"] == "done" and os.path.exists(f"{B}/review/{p['code']}_candidates.csv") and not os.path.exists(f"{B}/review/{p['code']}_score_ai.json"):
            p["ai_note"] = ai_score(p["code"])
        if p["status"] == "done" and SET["features"].get("unified_score") and os.path.exists(f"{B}/review/{p['code']}_candidates.csv") \
                and not os.path.exists(f"{B}/uscore/reports/{p['code']}.json") and p.get("uscore_status") not in ("pending", "running"):
            queue_unified(p)
    try: write_results_file()
    except Exception as e: print("results file not written:", e, flush=True)
def results_file():
    d = next((p.get("results_dir") for p in PAT if p.get("results_dir")), "")
    d = os.path.expanduser(d) if d and verify_local_dest(d)[0] else f"{B}/results"       # outside the base only when verified local
    os.makedirs(d, exist_ok=True); return f"{d}/cSS_results.xlsx"
def write_results_file():
    f = results_file(); open(f + ".tmp", "wb").write(export_xlsx()); os.replace(f + ".tmp", f); return f

def explain_reg(shift):
    return (f"the T1 labels do not line up with the SWI (shift {shift} mm, limit 1.5 mm) - nothing was written. "
            "choose a retry: fast masked registration (minutes), SynthMorph (minutes) or recon-all (most accurate, ~2-3 h)")
NEXT_REG = {None: "coreg_masked", "": "coreg_masked", "coreg_masked": "synthmorph"}     # automatic order after a failed registration
SETUP_ERR = ("licence", "FreeSurfer", "disk is full", "dcm2niix")
def fail(p, msg):
    with LOCK:
        if "do not line up" in msg:
            m = re.search(r"shift ([\d.?]+) mm", msg)
            p.setdefault("tried", []).append(dict(pathway=p.get("pathway", "synthseg"), shift=m.group(1) if m else "?"))
            move_bad_registration(p)
            pm_end_full(p, False, msg)                   # bad registration renamed aside first, then the previous outputs are put back
            nxt = next_rec(p)
            if SET.get("auto_retry", True) and nxt in ("coreg_masked", "synthmorph") and p["series"].get("T1"):
                apply_pathway(p, nxt)
                p.update(status="waiting", error="", steps_done={}, path_ack=False,
                         path_note=f"{msg.split(' - ')[0]} -> retrying automatically with {PATHWAYS[nxt]} ({PW_TIME[nxt]})")
                save_pat(); notify("cSS Pipeline", f"{p['code']}: registration retried with {PATHWAYS[nxt]}"); return
        pm_end_full(p, False, msg)                       # previous outputs put back; this attempt stays in the history as failed
        p.update(status="failed", error=msg, finished=time.time()); save_pat()
        if any(k in msg for k in SETUP_ERR): CUR["hold"] = msg
    notify("cSS Pipeline", f"{p['code']} failed: {msg[:60]}")
def copy_results(p):
    """codes-only copy of the patient's result files into the chosen results folder"""
    d = p.get("results_dir")
    if not d: return
    okd, why = verify_local_dest(d)
    if not okd: print(f"results copy for {p['code']} refused: {why}", flush=True); return
    d = os.path.expanduser(d)
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

def run_one(p):
    try: process(p)
    except Exception as e: fail(p, f"app error: {type(e).__name__}: {e}")
    finally:
        if p.get("pm_run"): pm_end_full(p, False, f"stopped ({p.get('status')}) before the pipeline finished")   # stop / pause-stop: recorded, outputs restored
        RUNNING.pop(p["code"], None)
def solo(p): return p.get("pathway") in SOLO
def next_to_start():
    """the next waiting patient that may start now, or None. Rules: at most SET['parallel'] at once; SWI-only / SynthMorph run alone
    (and wait until the normal patients are done); no new start while memory is in the yellow / red zone"""
    if CUR["hold"]: return None
    wait = [p for p in PAT if p["status"] == "waiting"]
    if not wait: return None
    run = [pget(c) for c in list(RUNNING)]; run = [p for p in run if p]
    if any(solo(p) for p in run): return None
    if len(run) >= max(1, int(SET.get("parallel", 1))): return None
    normal = [p for p in wait if not solo(p)]
    if run and not normal: return None                    # a solo patient waits until everything else has finished
    if run and not FAKE:
        CUR["mem_wait"] = sysinfo()["mem_pct"] >= MEM_YELLOW
        if CUR["mem_wait"]: return None
    CUR["mem_wait"] = False
    return normal[0] if normal else wait[0]
def worker():
    last_backup = ""
    while True:
        with LOCK:
            nxt = next_to_start()
            if nxt: nxt["status"] = "starting"; RUNNING[nxt["code"]] = threading.Thread(target=run_one, args=(nxt,), daemon=True)
        if nxt is None:
            if not RUNNING:
                caffeinate(False)
                day = datetime.date.today().isoformat()
                if SET["features"].get("backup") and SET.get("backup_dir") and day != last_backup: backup(); last_backup = day
            time.sleep(1); continue
        RUNNING[nxt["code"]].start(); time.sleep(2 if not FAKE else 0.1)
CLOUD_MARKERS = ("/Library/Mobile Documents/", "/Library/CloudStorage/", "/Dropbox", "/Google Drive", "/OneDrive", "/iCloud", "/Box/", "/pCloud")
def cloud_synced(path):
    """local-only rule: clinical-derived data must not go to a cloud-synced folder"""
    p = os.path.realpath(os.path.expanduser(path)) + "/"
    return any(m.lower() in p.lower() for m in CLOUD_MARKERS)
def verify_local_dest(path):
    """(ok, reason): one rule set for every user-chosen destination (export, share, backup, results) - css_writeguard.check_dest:
    refuses the production project and anything inside it or resolving into it, cloud-synced folders, ~/Desktop, ~/Documents,
    missing and read-only folders"""
    return WG.check_dest(path)
def backup():
    okd, why = verify_local_dest(SET["backup_dir"])
    if not okd:
        open(f"{AD}/logs/backup.log", "a").write(f"{datetime.datetime.now():%Y-%m-%d %H:%M} backup refused: {why} (local-only rule)\n"); return False
    d = os.path.join(os.path.expanduser(SET["backup_dir"]), datetime.date.today().isoformat()); os.makedirs(d, exist_ok=True)
    for f in glob.glob(f"{B}/review/*.csv") + glob.glob(f"{B}/review/*.json") + glob.glob(f"{AD}/*.json"):
        shutil.copy2(f, d)
    if os.path.exists(f"{PRIV}/names.csv"): shutil.copy2(f"{PRIV}/names.csv", os.path.join(d, "names_PRIVATE.csv"))

def eta(p):
    tm = jload("timings.json", {}); dflt = DEFAULT_MIN["recon" if p["anatomy"] == "recon" else "synthseg"]
    est = {s: tm.get(f"{p['anatomy']}:{s}", dflt["import_" if s == "import" else s] * 60) for s in STEPS}
    if p["status"] in ("waiting", "decision", "starting"): return 0, sum(est.values())
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
        r["qc_grade"], r["qc_tip"] = qc_grade(p); r["ai_err"] = p.get("ai_note", "")
        u = p.get("uscore") or {}                   # v5.14 experimental unified score (counts of candidates per category; none hidden)
        r["unified_status"] = p.get("uscore_status") or ("off" if not SET["features"].get("unified_score") else "")
        if u and not u.get("error"):
            r.update(unified_css_compatible=u.get("css_compatible"), unified_uncertain=u.get("uncertain"),
                     unified_alternative=u.get("alternative_high_confidence"), unified_model="fitted" if u.get("model") else "no model yet (detectors only)")
        elif u: r["unified_note"] = u.get("error", "")[:200]
        r["label"] = "reviewed" if r.get("score_total") is not None else ("AI only, not validated" if r.get("ai_total") is not None else "")
        rows.append(r)
    return rows
def export_xlsx():
    import pandas as pd
    df = pd.DataFrame(results()).drop(columns=["name", "qc_tip", "ai_err"], errors="ignore")
    bio = io.BytesIO(); df.to_excel(bio, index=False, sheet_name="results"); return bio.getvalue()
class ExportRefused(Exception): pass
EXPORT_WARNING = ("This file holds clinical-derived research data (study codes, candidate calls, grades, scores). "
                  "It is written only to your chosen local folder and is never uploaded. Do not move it to cloud storage, e-mail or chat.")
def export_dest():
    okd, why = verify_local_dest(SET.get("export_dir", ""))
    if not okd: raise ExportRefused(f"export refused: {why}. Choose a verified local export folder in Settings (not Desktop / Documents / cloud).")
    return os.path.realpath(os.path.expanduser(SET["export_dir"]))
def export_as(fmt, cohort=""):
    """results (codes only) -> <verified export folder>/cSS_results_<cohort>_<time>.<fmt>; fmt xlsx / csv / docx / pdf"""
    import pandas as pd
    rows = [r for r in results() if not cohort or cohort == "all" or r["cohort"] == cohort]
    df = pd.DataFrame(rows).drop(columns=["name", "qc_tip", "ai_err"], errors="ignore")
    out = os.path.join(export_dest(), f"cSS_results_{(cohort or 'all').replace('/', '_')}_{datetime.datetime.now():%Y%m%d_%H%M}.{fmt}")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if fmt == "xlsx": df.to_excel(out, index=False, sheet_name="results")
    elif fmt == "csv": df.to_csv(out, index=False)
    elif fmt == "docx": write_docx(out, df, cohort)
    elif fmt == "pdf": write_pdf(out, df, cohort)
    else: raise ValueError(f"unknown format {fmt}")
    return out
COLS_SHORT = [("code", "Code"), ("cohort", "Cohort"), ("status", "Status"), ("qc_grade", "QC"), ("candidates", "Candidates"), ("score_L", "Reader L"),
              ("score_R", "Reader R"), ("score_total", "Reader total"), ("ai_total", "AI total*"), ("rad_R", "Radiologist R"), ("rad_L", "Radiologist L")]
def _cells(df):
    cols = [(k, h) for k, h in COLS_SHORT if k in df.columns]
    rows = [[("" if (v is None or (isinstance(v, float) and v != v)) else (str(int(v)) if isinstance(v, float) and v == int(v) else str(v))) for v in (r[k] for k, _ in cols)] for _, r in df.iterrows()]
    return [h for _, h in cols], rows
def write_docx(out, df, cohort):
    """minimal Word file (no extra package): title + table + note"""
    from xml.sax.saxutils import escape as x
    head, rows = _cells(df)
    cell = lambda t, b=False: f'<w:tc><w:p><w:r>{"<w:rPr><w:b/></w:rPr>" if b else ""}<w:t xml:space="preserve">{x(t)}</w:t></w:r></w:p></w:tc>'
    tbl = ('<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblW w:w="0" w:type="auto"/><w:tblBorders>' + "".join(f'<w:{e} w:val="single" w:sz="4" w:color="999999"/>' for e in ("top", "left", "bottom", "right", "insideH", "insideV")) +
           '</w:tblBorders></w:tblPr>' + "<w:tr>" + "".join(cell(h, True) for h in head) + "</w:tr>" + "".join("<w:tr>" + "".join(cell(c) for c in r) + "</w:tr>" for r in rows) + "</w:tbl>")
    para = lambda t, b=False, sz=22: f'<w:p><w:r><w:rPr>{"<w:b/>" if b else ""}<w:sz w:val="{sz}"/></w:rPr><w:t xml:space="preserve">{x(t)}</w:t></w:r></w:p>'
    body = (para(f"cSS results{' - cohort ' + cohort if cohort and cohort != 'all' else ''}", True, 32) + para(f"Pipeline {version()} · {datetime.datetime.now():%Y-%m-%d %H:%M} · codes only") + tbl +
            para("* AI score = detector's green-band candidates, AI only, not validated. QC grade from the label shift (A+ <= 0.5 mm ... F > 2.5 mm).", False, 18))
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' + body +
           '<w:sectPr><w:pgSz w:w="16838" w:h="11906" w:orient="landscape"/><w:pgMar w:top="720" w:right="720" w:bottom="720" w:left="720"/></w:sectPr></w:body></w:document>')
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr("word/document.xml", doc)
def write_pdf(out, df, cohort):
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    head, rows = _cells(df); per = 28
    with PdfPages(out) as pdf:
        for k in range(0, max(1, len(rows)), per):
            fig = plt.figure(figsize=(11.69, 8.27)); fig.text(0.04, 0.95, f"cSS results{' - cohort ' + cohort if cohort and cohort != 'all' else ''}", fontsize=15, weight="bold")
            fig.text(0.04, 0.92, f"Pipeline {version()} · {datetime.datetime.now():%Y-%m-%d %H:%M} · codes only · * AI only, not validated", fontsize=9, color="#555")
            ax = fig.add_axes([0.04, 0.06, 0.92, 0.83]); ax.axis("off")
            part = rows[k:k + per] or [[""] * len(head)]
            t = ax.table(cellText=part, colLabels=head, loc="upper center", cellLoc="center"); t.auto_set_font_size(False); t.set_fontsize(8.5); t.scale(1, 1.25)
            for (r, c), cl in t.get_celld().items():
                if r == 0: cl.set_facecolor("#e8ecf2"); cl.set_text_props(weight="bold")
            pdf.savefig(fig); plt.close(fig)

def share_package(codes):
    out = os.path.join(export_dest(), f"cSS_share_{datetime.datetime.now():%Y%m%d_%H%M}.zip")
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
    if RUNNING: return dict(ok=False, error="a patient is processing - wait or stop it first")
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
WIN = dict(webview=False, port=8800)
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
    if kind == "review": cmd += ["--groups", f"{AD}/review_groups.json", "--start", args.get("start", args["codes"][0])]
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
                        elapsed=el, remaining=rem, reg_method=p.get("reg_method", ""), pathway=p.get("pathway", "synthseg"),
                        path_note=p.get("path_note", ""), path_ack=p.get("path_ack", True), solo=solo(p), started=p.get("started", 0),
                        tried=p.get("tried", []), next_rec=next_rec(p) if p["status"] == "failed" else "", qc=qc_grade(p)[0], qc_tip=qc_grade(p)[1],
                        stalled=round((time.time() - last_activity(p["code"])) / 60) if p["status"] == "running" and last_activity(p["code"]) and time.time() - last_activity(p["code"]) > 1200 else 0, has_qc=os.path.exists(f"{AD}/qc/{p['code']}.png"), version=p.get("version", ""),
                        radiologist=p.get("radiologist", ""), grade_R=p.get("grade_R", ""), grade_L=p.get("grade_L", ""),
                        step_times={k: round(v) for k, v in p.get("steps_done", {}).items()}))
    q = [x for x in out if x["status"] in ("waiting", "running", "paused", "starting")]
    si = sysinfo(); rec, rec_why, _ = recommend(si)
    par = max(1, int(SET.get("parallel", 1)))
    rem = sum(x["remaining"] for x in q) / min(par, max(1, len([x for x in q if not x["solo"]]) or 1))
    return dict(patients=out, queue=dict(n=len(q), remaining=rem, running=",".join(RUNNING), hold=CUR["hold"], mem_wait=CUR["mem_wait"]),
                sys=si, rec=rec, rec_why=rec_why, pw_time=PW_TIME, pw_mem=PW_MEM, pathways=PATHWAYS, mem_zones=[MEM_YELLOW, MEM_RED],
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
            if u.path == "/api/vset":
                f = f"{B}/review/viewer_settings.json"; return self.send(json.load(open(f)) if os.path.exists(f) else {})
            if u.path in ("/icon_dark.png", "/icon_light.png"): return self.send(open(f"{HERE}{u.path}", "rb").read(), ctype="image/png")
            if u.path == "/unified_view.js": return self.send(open(f"{HERE}/unified_view.js", "rb").read(), ctype="text/javascript; charset=utf-8")
            if u.path == "/api/preflight": return self.send(preflight())
            if u.path == "/api/log":
                f = f"{AD}/logs/{q['code']}.log"; t = open(f).read()[-30000:] if os.path.exists(f) else "(no log yet)"
                p = pget(q["code"]); rl = f"{B}/logs/{q['code']}_run.log"
                if p and p["status"] in ("running", "paused") and os.path.exists(rl) and os.path.getmtime(rl) >= p.get("started", 0):
                    t += "\n----- live pipeline log (logs/" + q["code"] + "_run.log) -----\n" + open(rl, errors="replace").read()[-20000:]
                return self.send(dict(text=t))
            if u.path == "/qc":
                done = [p["code"] for p in PAT if os.path.exists(f"{AD}/qc/{p['code']}.png")]; c = q.get("code", done[0] if done else "")
                i = done.index(c) if c in done else 0; th = SET.get("theme", "dark")
                info = ""
                try:
                    j = json.load(open(f"{B}/review/{c}_qc.json")); sh = j.get("label_shift_mm")
                    if sh is not None: info = f"label shift {float(sh):.2f} mm " + ("✓" if float(sh) <= 1.5 else "✗ above 1.5 mm")
                except Exception: pass
                nav = lambda k, t: f'<a href="/qc?code={done[k]}">{t}</a>' if 0 <= k < len(done) else f'<span style="opacity:.3">{t}</span>'
                bg, fg = ("#111418", "#e6e8eb") if th != "light" else ("#f4f5f7", "#16181b")
                html = (f'<!doctype html><html><head><meta charset="utf-8"><title>QC - {c}</title><link rel="icon" href="/icon_{"light" if th == "light" else "dark"}.png">'
                        f'<style>body{{margin:0;background:{bg};color:{fg};font:14px -apple-system,sans-serif;padding:14px}}a{{color:#3987e5;text-decoration:none;font-size:15px}}'
                        f'img{{max-width:100%;border-radius:8px;margin-top:10px}}.r{{display:flex;gap:16px;align-items:center}}.m{{opacity:.7;font-size:13px}}</style></head><body>'
                        f'<div class="r"><b style="font-size:17px">QC - {c}</b><span class="m">{info}</span><span style="flex:1"></span>{nav(i - 1, "◂ previous")} {i + 1} / {len(done)} {nav(i + 1, "next ▸")}</div>'
                        f'<img src="/api/qc?code={c}&t={time.time():.0f}"><p class="m">Cyan = cortex labels, yellow = brain mask. They should follow the anatomy on every panel; '
                        f'a shift or a cut-off part of the brain means the registration or the mask is wrong.</p>'
                        f'<script>document.onkeydown=e=>{{const a=[...document.querySelectorAll("a")];if(e.key=="ArrowLeft"&&a[0]&&a[0].textContent.includes("prev"))a[0].click();'
                        f'if(e.key=="ArrowRight")a.find(x=>x.textContent.includes("next"))?.click()}}</script></body></html>')
                return self.send(html.encode(), ctype="text/html; charset=utf-8")
            if u.path == "/api/qc":
                f = f"{AD}/qc/{q['code']}.png"; return self.send(open(f, "rb").read(), ctype="image/png")
            if u.path.startswith("/api/proc/"): return self.send(proc_get(u.path[10:], {k: v[0] for k, v in parse_qs(u.query).items()}))
            if u.path.startswith("/api/u/"): return self.send(unified_get(u.path[7:], {k: v[0] for k, v in parse_qs(u.query).items()}))
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
                for k_ in ("backup_dir", "export_dir"):
                    if d.get(k_):
                        okd, why = verify_local_dest(d[k_])
                        if not okd: return self.send(dict(ok=False, error=f"{k_.replace('_dir', '')} folder refused: {why}. Clinical-derived data stays on this Mac - choose a local or external-disk folder."))
                with LOCK:
                    for k, v in d.items():
                        if k == "features": SET["features"].update(v)
                        else: SET[k] = v
                    jsave("settings.json", SET)
                caffeinate(bool(RUNNING)); return self.send(dict(ok=True))
            if u.path == "/api/control":
                p = pget(d["code"]); a = d["action"]
                if not p: return self.send(dict(error="unknown code"))
                pr = PROCS.get(p["code"])
                if a == "pause" and p["status"] == "running":
                    p["status"] = "paused"
                    if pr: os.killpg(pr.pid, signal.SIGSTOP)
                elif a == "resume" and p["status"] == "paused":
                    p["status"] = "running"
                    if pr: os.killpg(pr.pid, signal.SIGCONT)
                elif a == "stop" and p["status"] in ("running", "paused"):
                    p.update(status="stopped", error="stopped by you")
                    if pr: os.killpg(pr.pid, signal.SIGCONT); os.killpg(pr.pid, signal.SIGTERM)
                elif a in ("retry", "rerun") and p.get("linked"):
                    return self.send(dict(ok=False, error="this study was brought in from another project without its raw series: use the Processing tab (new detection run; anatomy is reused)"))
                elif a in ("retry", "rerun") and p["status"] in ("failed", "stopped", "done"):
                    if d.get("pathway") in PATHWAYS and d["pathway"] != p.get("pathway"): apply_pathway(p, d["pathway"])
                    p.update(status="waiting", error="", steps_done={}); CUR["hold"] = ""
                elif a in ("swi_only", "recon", "coreg_masked", "synthmorph") and p["status"] in ("failed", "stopped", "done"):
                    if "do not line up" in p.get("error", ""): move_bad_registration(p)
                    apply_pathway(p, a); p["note"] = f"retried with {PATHWAYS[a]}"
                    p.update(status="waiting", error="", steps_done={}); CUR["hold"] = ""
                elif a == "pathway" and p["status"] in ("waiting", "decision"):          # change the pathway before it runs
                    apply_pathway(p, d["pathway"]); p.update(status="waiting", path_ack=True)
                elif a == "accept" : p.update(path_ack=True, status="waiting" if p["status"] == "decision" else p["status"])
                elif a == "requeue" and p["status"] in ("running", "paused", "starting"):   # memory red zone: stop and put back in the queue
                    p.update(status="waiting", error="", step="", note="stopped to free memory - starts again from the beginning")
                    if pr: os.killpg(pr.pid, signal.SIGCONT); os.killpg(pr.pid, signal.SIGTERM)
                elif a == "remove" and p["status"] in ("waiting", "failed", "stopped", "decision"): PAT.remove(p)
                else: return self.send(dict(error=f"cannot {a} while {p['status']}"))
                save_pat(); return self.send(dict(ok=True))
            if u.path == "/api/edit":
                p = pget(d["code"])
                if not p: return self.send(dict(error="unknown code"))
                if "name" in d: set_name(p["code"], d["name"])
                if d.get("new_code") and d["new_code"] != p["code"]:
                    nc = d["new_code"]
                    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,32}", nc) or pget(nc): return self.send(dict(error="invalid or duplicate code"))
                    if p["status"] not in ("waiting", "decision"): return self.send(dict(error="a code can only be changed before processing starts (results are filed under it)"))
                    nm = names().get(p["code"], ""); set_name(nc, nm, old_code=p["code"]); p["code"] = nc
                for k in ("radiologist", "grade_R", "grade_L"):
                    if k in d: p[k] = d[k]
                save_pat(); write_grades_file(); return self.send(dict(ok=True))
            if u.path == "/api/fix":
                if d.get("what") == "pywebview":
                    r = subprocess.run([sys.executable, "-m", "pip", "install", "pywebview"], capture_output=True, text=True)
                    return self.send(dict(ok=r.returncode == 0, error="" if r.returncode == 0 else (r.stderr or r.stdout)[-500:]))
                if d.get("what") == "dcm2niix":
                    r = subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "dcm2niix"], capture_output=True, text=True)
                    ok = r.returncode == 0 and bool(which("dcm2niix", fs_env()))
                    return self.send(dict(ok=ok, error="" if ok else (r.stderr or r.stdout)[-500:]))
                if d.get("what") == "licence_choose":
                    path, err = pick("file", "Choose your FreeSurfer license.txt")
                    if not path: return self.send(dict(ok=False, error=err or "cancelled"))
                    if not os.access(path, os.R_OK): return self.send(dict(ok=False, error="that file cannot be read either"))
                    with LOCK: SET["fs_license"] = path; jsave("settings.json", SET)
                    return self.send(dict(ok=True))
                if d.get("what") == "licence_permission" and mac():
                    p = d.get("path", "")
                    if not p or not os.path.isfile(p): return self.send(dict(ok=False, error="no licence file to fix"))
                    r = subprocess.run(["osascript", "-e", f'do shell script "chmod a+r " & quoted form of "{p}" with administrator privileges'], capture_output=True, text=True)
                    ok = r.returncode == 0 and os.access(p, os.R_OK)
                    if ok:
                        with LOCK: SET["fs_license"] = p; jsave("settings.json", SET)
                    return self.send(dict(ok=ok, error="" if ok else (r.stderr or "not changed")[-300:]))
                return self.send(dict(ok=False, error="unknown fix"))
            if u.path == "/api/retry_failed":
                n = 0
                with LOCK:
                    for p in PAT:
                        if p["status"] in ("failed", "stopped"): p.update(status="waiting", error="", steps_done={}); n += 1
                    save_pat(); CUR["hold"] = ""
                return self.send(dict(ok=True, n=n))
            if u.path == "/api/install": return self.send(install_zip(d["path"]))
            if u.path == "/api/rollback": return self.send(rollback())
            if u.path == "/api/review":
                done = [p for p in PAT if p["status"] == "done" and os.path.exists(f"{B}/review/{p['code']}_candidates.csv")]
                groups = {}
                for p in done: groups.setdefault(p.get("cohort") or "-", []).append(p["code"])
                start = d["codes"][0]
                if d.get("cohort"): d["codes"] = groups.get(d["cohort"], d["codes"]); start = d["codes"][0] if d["codes"] else start
                else: d["codes"] = [p["code"] for p in done] + [c for c in d["codes"] if c not in {p["code"] for p in done}]   # studies found on disk (Processing tab) too
                json.dump(groups, open(f"{AD}/review_groups.json", "w")); d["start"] = start
                r = launch_child("review", d, 8765)
                if r.get("ok") and WIN["webview"]:
                    import webview; webview.create_window("cSS reviewer", r["url"], width=1500, height=950); r["opened"] = True
                return self.send(r)
            if u.path == "/api/blind":
                if d.get("new_packet"):
                    r = subprocess.run([sys.executable, f"{B}/reference_audit/ws_prepare.py", d["packet"], "--studies", ",".join(d["codes"]), "--readers", d["reader"]],
                                       capture_output=True, text=True, env=fs_env())
                    if r.returncode: return self.send(dict(ok=False, error=(r.stderr or r.stdout)[-400:]))
                return self.send(launch_child("blind", d, 8790))
            if u.path == "/api/window":                 # QC etc.: own window (pywebview) or the browser opens one
                if WIN["webview"]:
                    import webview; webview.create_window(d.get("title", "cSS"), f"http://127.0.0.1:{WIN['port']}{d['url']}", width=1150, height=560)
                    return self.send(dict(open=False))
                return self.send(dict(open=True))
            if u.path.startswith("/api/proc/"): return self.send(proc_post(u.path[10:], d))
            if u.path.startswith("/api/u/"): return self.send(unified_post(u.path[7:], d))
            if u.path in ("/api/share", "/api/export"):           # explicit warning + confirmation, verified local folder only
                if d.get("confirm_clinical") is not True: return self.send(dict(ok=False, needs_confirm=True, warning=EXPORT_WARNING,
                                                                     error="export needs your confirmation of the clinical-data warning (dialog pending design approval)"))
                try: export_dest()
                except ExportRefused as e: return self.send(dict(ok=False, error=str(e)))
            if u.path == "/api/share": return self.send(dict(ok=True, path=share_package(d["codes"])))
            if u.path == "/api/vset":                  # reviewer settings (same file the reviewer reads at start)
                f = f"{B}/review/viewer_settings.json"; os.makedirs(os.path.dirname(f), exist_ok=True)
                cur = json.load(open(f)) if os.path.exists(f) else {}; cur.update(d)
                json.dump(cur, open(f + ".tmp", "w"), indent=1); os.replace(f + ".tmp", f); return self.send(dict(ok=True))
            if u.path == "/api/export":
                out = export_as(d.get("fmt", "xlsx"), d.get("cohort", ""))
                if mac(): subprocess.run(["open", out])
                return self.send(dict(ok=True, path=out))
            if u.path == "/api/open_results":
                f = write_results_file()
                if mac(): subprocess.run(["open", f])
                return self.send(dict(ok=True, path=f))
            if u.path == "/api/ai_scores":
                threading.Thread(target=ai_backfill, daemon=True).start(); return self.send(dict(ok=True))
            if u.path == "/api/quit":
                if RUNNING and not d.get("force"): return self.send(dict(ok=False, error="a patient is processing - stop it first, or quit anyway (it restarts from the beginning next time)"))
                self.send(dict(ok=True)); threading.Timer(0.5, lambda: os._exit(0)).start(); return
            if u.path == "/api/open":
                if mac(): subprocess.run(["open", d["path"]])
                return self.send(dict(ok=True))
            return self.send(dict(error="not found"), 404)
        except Exception as e: return self.send(dict(error=f"{type(e).__name__}: {e}"), 500)

def mac_dark():
    r = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"], capture_output=True, text=True)
    return "dark" in r.stdout.lower()
def dock_icon_follow_theme():
    """own window only: Dock icon = dark or white brain icon following the Mac appearance (checked every 5 s)"""
    if not mac(): return
    try:
        from AppKit import NSApplication, NSImage
        from PyObjCTools import AppHelper
    except ImportError: return
    last = None
    while True:
        cur = "dark" if mac_dark() else "light"
        if cur != last:
            img = NSImage.alloc().initWithContentsOfFile_(f"{HERE}/icon_{cur}.png")
            AppHelper.callAfter(lambda i=img: NSApplication.sharedApplication().setApplicationIconImage_(i)); last = cur
        time.sleep(5)

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
    reread_failures()
    threading.Thread(target=ai_backfill, daemon=True).start()
    threading.Thread(target=worker, daemon=True).start()
    def _caff_watch():
        while True: caffeinate(bool(RUNNING)); time.sleep(5)
    threading.Thread(target=_caff_watch, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", port), H); url = f"http://127.0.0.1:{port}/"
    print(f"cSS Pipeline app: {url}  (CSS_BASE={B})", flush=True)
    how = None if "--no-window" in a else open_window(url)
    WIN["port"] = port
    if how == "webview":
        import webview; WIN["webview"] = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        webview.create_window("cSS Pipeline", url, width=1400, height=900); webview.start(dock_icon_follow_theme)
    else:
        try: srv.serve_forever()
        except KeyboardInterrupt: pass
