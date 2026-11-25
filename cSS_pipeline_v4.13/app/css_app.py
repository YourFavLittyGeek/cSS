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

def _resolve_project_base():
    if "CSS_BASE" in os.environ and os.environ["CSS_BASE"]:
        return os.path.abspath(os.path.expanduser(os.environ["CSS_BASE"]))
    cfg_p = os.path.expanduser("~/Library/Application Support/Percival Dev/project_path")
    if os.path.isfile(cfg_p):
        try:
            with open(cfg_p, "r") as f:
                cand = f.read().strip()
                if cand and os.path.isdir(os.path.expanduser(cand)):
                    return os.path.abspath(os.path.expanduser(cand))
        except Exception:
            pass
    percival_proj = os.path.expanduser("~/Percival_project")
    if os.path.isdir(percival_proj):
        return os.path.abspath(percival_proj)
    return os.path.abspath(os.path.expanduser("~/css_project"))

B = _resolve_project_base()

# Phase 0 (test isolation): start-up side effects (installing pipeline scripts into the project, crash recovery of runs and
# imports, registering studies found on disk) run only when this file is started as the application. Importing the
# module (unit tests, tools) has no side effects on the project. Start-up order of the application is unchanged.
_APP_STARTUP = __name__ == "__main__" or os.environ.get("PERCIVAL_APP_STARTUP") == "1"

def _refuse_live_binding_under_test(base):
    """an importing test must never bind to the real research project: refuse a base in the real home or under /Volumes"""
    if __name__ == "__main__": return
    if os.environ.get("PERCIVAL_TEST_ISOLATION") != "1" and "unittest" not in sys.modules: return
    try:
        import pwd; real_home = os.path.realpath(pwd.getpwuid(os.getuid()).pw_dir)
    except Exception: real_home = os.path.realpath(os.path.expanduser("~"))
    cb = os.path.realpath(base).lower()
    for bad in (real_home, "/volumes"):
        b = bad.lower().rstrip("/")
        if cb == b or cb.startswith(b + "/"):
            raise RuntimeError(f"css_app imported under a test with project base {base!r} inside {bad!r}: tests must set a temporary "
                               f"HOME and CSS_BASE (tests/_isolation.py) - refusing to bind to the live research project")

_refuse_live_binding_under_test(B)

def _ensure_pipeline_installed(base_dir):
    """Self-healing: ensure pipeline scripts and unified components are present in workspace."""
    rc = os.path.join(base_dir, "scripts", "run_css.sh")
    if not os.path.exists(rc):
        candidates = [
            os.path.join(HERE, "..", "scripts"),
            os.path.join(HERE, "..", "pipeline", "scripts"),
            os.path.expanduser("~/Percival_project/scripts"),
            os.path.expanduser("~/css_project/scripts"),
        ]
        for cand in candidates:
            cand = os.path.abspath(cand)
            if os.path.isdir(cand) and os.path.exists(os.path.join(cand, "run_css.sh")):
                target_scripts = os.path.join(base_dir, "scripts")
                os.makedirs(target_scripts, exist_ok=True)
                for item in os.listdir(cand):
                    if item.startswith(".") or item == "__pycache__": continue
                    sf = os.path.join(cand, item)
                    df = os.path.join(target_scripts, item)
                    if os.path.isfile(sf):
                        shutil.copy2(sf, df)
                        if df.endswith(".sh") or df.endswith(".py"):
                            try: os.chmod(df, 0o755)
                            except Exception: pass
                break

    # Also ensure unified_engine and unified_score directories exist
    for comp in ("unified_engine", "unified_score"):
        comp_dst = os.path.join(base_dir, comp)
        if not os.path.isdir(comp_dst):
            for cand in [os.path.join(HERE, "..", comp), os.path.join(HERE, "..", "pipeline", comp), os.path.expanduser(f"~/Percival_project/{comp}")]:
                if os.path.isdir(cand):
                    shutil.copytree(cand, comp_dst, ignore=shutil.ignore_patterns("__pycache__", ".*"))
                    break

if _APP_STARTUP: _ensure_pipeline_installed(B)
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
                features=dict(unified_score=False, shadow_engine=False, duplicate_check=True, preflight=True, qc_snapshot=True, notify=True, version_stamp=True, share=True, backup=True,
                              name_warning=False)), **jload("settings.json", {}))
import notify_centre as NC, study_split as SS      # v5.14.2-rc4: notification centre + user study selection / training gate
SET.setdefault("notif", dict(NC.DEFAULTS)); [SET["notif"].setdefault(k, v) for k, v in NC.DEFAULTS.items()]
SET.setdefault("autotrain", dict(on=False, threshold=3))
SET["features"].setdefault("experimental_core", False)   # Phase 0: ALBUS/LUMOS/NOX/CORE research layer off by default
SET["features"].setdefault("train_include_archived", True); SET["features"].setdefault("show_prototypes", False)   # v5.24: older ML prototypes hidden from the menu by default      # v5.20: archived studies stay in model training unless switched off
PAT = jload("patients.json", [])
for p in PAT:                                            # resume after a restart: interrupted runs go back to the queue
    if p.get("status") in ("running", "paused"): p.update(status="waiting", step="", note="restarted after the app was closed")
    p.pop("pm_run", None)                                # its history record is marked interrupted by PM.recover_all below
    p.setdefault("pathway", "recon" if p.get("anatomy") == "recon" else (p.get("reg_method") or "synthseg"))
    if p.get("uscore_status") in ("pending", "running"):   # v5.14-gui recovery: an unified job cut off by a restart is marked, never left "running"
        p.update(uscore_status="interrupted", uscore_error="the app was closed during the unified step - press 'Score patient' to run it again")
def save_pat(): jsave("patients.json", PAT)
import processing_manager as PM                       # v5.14-gui Previous Processing Manager
import identity_gui as IDG                            # v5.16 patient / examination identification (Standard / Incognito, encrypted vault)
IDG.init(B, PAT, SET)
SET.setdefault("percival_autocycle", False)   # Stage 6: automatic training cycles OFF by default (pilot)
SET.setdefault("percival_cycle_n", 5); SET.setdefault("percival_test_fraction", 0.2); SET.setdefault("percival_learn_from", "labelled")
import percival_gui as PG                             # v5.22 Percival Score (local)
import blind_gate as BG                               # Phase 3A.2: per-study AI outputs withheld until the study's blind review is complete
try: import openpyxl, openpyxl.workbook, openpyxl.styles, openpyxl.comments   # v5.24: imported once at start-up - a first import from two
except Exception: pass                                                       # server threads at once raised "partially initialized module"
def pname(code): return IDG.ident(code, SET).get("patient_name", "")       # only in Standard mode with the vault unlocked
PM_RECOVERED, PM_IMPORTS_ROLLED_BACK = {}, []
if _APP_STARTUP:
    try: PM_RECOVERED = PM.recover_all(B)                 # runs left "running" by a closed app become "interrupted" (previous outputs restored)
    except Exception as _e: PM_RECOVERED = {"error": str(_e)}
    try: PM_IMPORTS_ROLLED_BACK = PM.recover_imports(B)  # imports cut off by a crash / quit are rolled back (nothing half-imported stays)
    except Exception as _e: PM_IMPORTS_ROLLED_BACK = [f"error: {_e}"]

def reconcile_studies_on_disk():
    """Auto-discover and register any studies physically present in workspace or data folders."""
    existing_codes = set(p["code"] for p in PAT)
    added = 0
    try:
        for code in PM.studies_on_disk(B):
            if code and code not in existing_codes:
                anatomy = "recon" if os.path.isdir(os.path.join(B, "subjects", code, "surf")) else "synthseg"
                PAT.append(dict(
                    code=code,
                    cohort="local_workspace",
                    anatomy=anatomy,
                    mode="semi",
                    pathway=anatomy,
                    series={},
                    step="",
                    steps_done={},
                    added=time.time(),
                    status="done" if os.path.exists(f"{B}/review/{code}_candidates.csv") else "waiting",
                    note="Discovered from workspace"
                ))
                existing_codes.add(code)
                added += 1
        if added > 0:
            save_pat()
            IDG.ensure(PAT)
    except Exception as _err:
        sys.stderr.write(f"[Startup] Reconcile error: {_err}\n")

if _APP_STARTUP: reconcile_studies_on_disk()
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
    if op == "models": return dict(ok=True, models=PM.models_status(B))
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
            if "detect" in plan["run"]: st._upd(rid, production_models=pm_models_note(logf))
            for stage in plan["run"]:
                PM_JOBS[code]["stage"] = stage; st.stage_state(rid, stage, "running")
                if stage in PM_STEP:
                    cmd = [sys.executable, f"{SC}/{PM_STEP[stage]}", code] + (["-2.5", "85", "3"] if stage == "detect" else [])
                    rc = run_logged(cmd, logf, env, code="pm:" + code)
                    if rc != 0:
                        why = {3: "case cannot be scored (QC insufficient quality)", 5: "registration gate: registration not acceptable"}.get(rc, f"exit {rc}")
                        ok, msg = False, f"{stage} failed: {why}"; st.stage_done(rid, stage, False, why); break
                    if stage == "detect" and os.path.exists(f"{st.SD}/{code}/surf/lh.pial") and os.path.exists(f"{st.SD}/{code}/mri/orig.mgz") and os.path.exists(f"{B}/work/{code}_swi2t1.lta"):   # = run_css.sh [3b] condition
                        if run_logged([sys.executable, f"{SC}/surface_features.py", code], logf, env, code="pm:" + code) != 0:
                            open(logf, "a").write("WARNING: surface_features.py failed - detection results are unaffected\n")
                    if stage == "detect":
                        try:                                                 # Stage 5: every detection run is an event with its detector version
                            from uengine.percival import architecture as _AR
                            PG._event("detection_run", "ALBUS", study=code, run=rid, detector=_AR.detector_version(B, code))
                        except Exception: pass
                        pm_rank_like_production(code, env, logf)            # = run_css.sh [3c]: ranking model only for dev-split studies
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
            if ok and "detect" in plan["run"]: after_run_done(code, rid)
            notify_c("done" if ok else "action", "processing", f"Processing run {'finished' if ok else 'FAILED'} · {code}",
                     f"run {rid}: {', '.join(plan['run'])}" + ("" if ok else f" - {msg.splitlines()[0][:200]}; previous outputs restored"), actions=["open_processing"], study=code)
            p = pget(code)
            if ok and p and "detect" in plan["run"]:
                if SET["features"].get("qc_snapshot"): qc_snapshot(code)
                save_pat()
                try: write_results_file()
                except Exception: pass
        finally: PM_JOBS.pop(code, None)
    threading.Thread(target=run, daemon=True).start()
    return rid

def after_run_done(code, rid):
    """v5.17: after a completed run - candidate lineage against the previous run (scripts/candidate_lineage.py) and the model provenance
    of the run (which experimental models were applied or withheld). Never changes candidates, calls or scores."""
    try:
        import review_calls_gui as RCG
        L = RCG._ledger(B)                                   # makes the project's scripts importable
        import candidate_lineage as CLN
        lin = CLN.after_run(B, code, rid)
        st = PM.Study(B, code); p = pget(code) or {}
        mdl = dict(deterministic_math=f"detector {version()}", unified_score=p.get("uscore_status") or ("off" if not SET["features"].get("unified_score") else "pending"),
                   shadow_ml="on (after each finished study)" if SET["features"].get("shadow_engine") else "off",
                   image_ml="withheld: only a SYNTHETIC-trained model exists" if not os.path.exists(f"{B}/unified_engine/SYNTHETIC_BASE") else "synthetic study: Image ML screen")
        st._upd(rid, models=mdl, lineage=(lin or {}).get("summary"), ledger=L.LEDGER_VERSION)
        return lin
    except Exception as e: print("lineage / provenance not recorded:", e, flush=True)
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
        if ok: after_run_done(p["code"], rid)
    except Exception as e: print("processing history not updated:", e, flush=True)
def pm_models_note(logf):
    """written at the start of every detection run: which production models are in force, verified and compatible"""
    ms = PM.models_status(B); lines = []
    for n, m in ms.items():
        if m["present"] and m["compatible"] and m["verified_copy_of_production"]: lines.append(f"{n}: verified copy of the production model, compatible ({'; '.join(m['notes'])})")
        elif not m["present"]: lines.append(f"{n}: NOT PRESENT - production parity NOT met for this model ({m['import_status']})")
        else: lines.append(f"{n}: PRODUCTION PARITY NOT MET - present={m['present']} compatible={m['compatible']} verified={m['verified_copy_of_production']} {'; '.join(m['reasons'])}")
    open(logf, "a").write("\nproduction models:\n  " + "\n  ".join(lines) + "\n")
    return ms
def pm_rank_like_production(code, env, logf):
    """run_css.sh step [3c] reproduced: rank_candidates.py only when review/ranker_model.json exists AND the study's split (production
    labels/study_meta.csv, recorded at import) is 'dev'; otherwise the reason is logged. Nothing broader than production."""
    if not os.path.exists(f"{B}/review/ranker_model.json"):
        open(logf, "a").write("[3c] ranking model not applied: no review/ranker_model.json in this project\n"); return
    imp = PM._jl(f"{B}/runs/{code}/import.json", {}) or {}
    sp = (imp.get("production_split") or {}).get("split", "")
    if not imp:                                                            # a study added in this project: its own labels/study_meta.csv, as run_css.sh
        try:
            import csv
            for row in csv.DictReader(open(f"{B}/labels/study_meta.csv")):
                if row.get("study_id") == code: sp = row.get("split", "") or ""
        except Exception: sp = ""
    if sp != "dev":
        open(logf, "a").write(f"[3c] ranking model not applied: {code} split is '{sp or 'unassigned'}' (only dev studies are ranked automatically - as in production)\n"); return
    if not PM.models_status(B)["ranker_model.json"]["compatible"]:
        open(logf, "a").write("[3c] ranking model NOT applied: incompatible with this pipeline (see production models above) - production parity NOT met\n"); return
    open(logf, "a").write("[3c] trained ranking model (rank_candidates.py; dev split)\n")
    if run_logged([sys.executable, f"{SC}/rank_candidates.py", code], logf, env, code="pm:" + code) != 0:
        open(logf, "a").write(f"      WARNING: rank_candidates.py did not rank {code} - the score_v4 order stands (as in production)\n")
# ------------------------------------------------------------------ v5.14.2-rc4 study selection, training gate, notifications
def study_label(code):
    """v5.20 the study's identifier for display: Standard (vault unlocked) = accession number, otherwise the de-identified code"""
    try:
        i = IDG.ident(code, SET)
        return (i.get("accession") if IDG.mode(SET) == "standard" and not i.get("locked") and i.get("accession") else "") or i.get("deid_code") or code
    except Exception: return code
def os_label(code):
    """macOS banners are stored by macOS outside the app: Incognito shows the code, Standard no identifier at all (open the app to see it)"""
    try: return "A study" if IDG.mode(SET) == "standard" else (IDG.ident(code, SET).get("deid_code") or code)
    except Exception: return "A study"
def notify_c(level, source, title, text="", actions=None, key=None, study=None):
    """one entry point: the local notification centre + (by setting) a macOS banner. Never raises."""
    try:
        NC.add(B, level, source, title, text, actions, key, study)
        bm = SET["notif"].get("banner", "urgent")
        if SET["features"].get("notify") and (bm == "all" or (bm == "urgent" and level == "urgent")):
            t_ = f"{title} {text}"
            if study and IDG.mode(SET) == "standard": t_ = t_.replace(study, "a study")      # macOS keeps banners outside the app: no identifier in Standard
            notify("Percival", t_[:180])
    except Exception as e: print("notification not stored:", e, flush=True)
SEL_PREFIX = "SYN" if os.environ.get("CSS_USCORE_DEMO") == "1" else "M"     # synthetic demo / tests use SYN studies only
def sel_studies():
    ids = set(k for k in SS.manifest_rows(B) if k.startswith(SEL_PREFIX)) | set((SS.current(B) or {}).get("roles", {}).keys())
    ids |= set(c for c in PM.studies_on_disk(B) if c.startswith(SEL_PREFIX))
    ids |= set(p["code"] for p in PAT if p.get("retired"))                                  # v5.20: removed studies kept for ML
    if not SET["features"].get("train_include_archived", True): ids -= set(p["code"] for p in PAT if p.get("archived"))
    return sorted(ids, key=lambda x: (len(x), x))
def sel_get(op, q):
    if op == "status":
        st = SS.status(B, sel_studies(), {p["code"]: p.get("cohort", "") for p in PAT})
        return dict(ok=True, autotrain=SET["autotrain"], pending=SS.pending_training(B, sel_studies()), **st)
    if op == "versions": return dict(ok=True, versions=SS.versions(B), current=(SS.current(B) or {}).get("version"))
    return dict(ok=False, error="unknown")
def sel_post(op, d):
    by = d.get("by") or "user"
    if op == "apply":
        r = SS.apply(B, sel_studies(), d.get("changes") or {}, by, d.get("note", ""), bool(d.get("confirm_spent")))
        if r.get("ok"): notify_c("done", "training", f"Study selection v{r['version']} applied", "; ".join(f"{k} {v}" for k, v in r["changes"].items())[:300])
        return r
    if op == "restore":
        r = SS.restore(B, d.get("version"), by)
        if r.get("ok"): notify_c("done", "training", f"Study selection v{r['version']} (restored from v{d.get('version')})")
        return r
    if op == "gate":
        if any(j.get("status") == "running" for j in [UG_job("train")]) and not d.get("open"):
            return dict(ok=False, error="a training run is in progress; close the gate after it finishes (or stop it in step 4)")
        g = SS.set_gate(B, d.get("open"), by); notify_c("done", "training", f"Training gate {'opened' if g['open'] else 'closed'}", f"by {g['by']}")
        return dict(ok=True, gate=g)
    if op == "autotrain":
        SET["autotrain"] = dict(on=bool(d.get("on")), threshold=max(1, int(d.get("threshold") or 3))); jsave("settings.json", SET)
        return dict(ok=True, autotrain=SET["autotrain"])
    return dict(ok=False, error="unknown")
def UG_job(name):
    try:
        import unified_gui as UG; return UG.job(name)
    except Exception: return dict(status="idle")
def notif_running():
    out = []
    try:
        import progress_jobs as PJ
        for j in PJ.running(): out.append(dict(title=j["title"], text=f"{j['label']} ({min(j['done'], j['total'])}/{j['total']})", progress=j["pct"] / 100.0, job=j["id"]))
    except Exception: pass
    for c, j in list(PM_JOBS.items()): out.append(dict(title=f"Processing run · {c}", text=f"stage {j.get('stage') or 'starting'}", progress=None))
    for p in PAT:
        if p.get("status") == "running": out.append(dict(title=f"Pipeline · {p['code']}", text=f"step {p.get('step', '')}", progress=None))
    try:
        import unified_gui as UG
        for n, j in list(UG.JOBS.items()):
            if j.get("status") == "running": out.append(dict(title=f"Unified · {n}", text=(j.get("log") or [""])[-1][:120], progress=j.get("progress")))
    except Exception: pass
    return out
def notif_get(op, q):
    if op == "list":
        it = NC.visible(B, SET["notif"]); run = notif_running() if SET["notif"]["sections"].get("running", True) else []
        badge = sum(1 for i in it if i["level"] in ("urgent", "action")) if SET["notif"].get("badge") == "action" else sum(1 for i in it if not i.get("read")) + len(run)
        return dict(ok=True, items=it, running=run, badge=badge, urgent=any(i["level"] == "urgent" for i in it), settings=SET["notif"])
    if op == "log": return dict(ok=True, log=NC.log(B)[:500])
    return dict(ok=False, error="unknown")
def notif_post(op, d):
    if op == "act": NC.act(B, d.get("id", ""), d.get("op", "read"), d.get("minutes") or SET["notif"].get("snooze_min", 5)); return dict(ok=True)
    if op == "clear_removed": NC.clear_removed(B); return dict(ok=True)
    if op == "settings":
        for k in NC.DEFAULTS:
            if k in d: SET["notif"][k] = d[k]
        jsave("settings.json", SET); return dict(ok=True, settings=SET["notif"])
    return dict(ok=False, error="unknown")
WATCH = dict(jobs={}, autotrain_last=0)
def storage_autofix():
    """no Terminal needed: (1) FreeSurfer folder searched + validated when the setting is empty (an app opened from Finder has
    no FREESURFER_HOME); (2) the chosen vault = <drive>/PERCIVAL_VAULT, created as soon as that drive is connected (setup_gui.ensure_vault:
    never on an unplugged drive, an existing vault is never changed). Called at start-up and every 30 s by the watcher. -> True if changed"""
    import setup_gui as SG
    ch = False
    if not SET.get("freesurfer_home"):                         # only an EMPTY setting is filled in: a folder somebody chose is never replaced
        f = SG.find_freesurfer(os.environ.get("FREESURFER_HOME", ""))
        if f: SET["freesurfer_home"] = f; ch = True
    vm = SET.get("vault_mount")
    if vm:
        vp = SG.resolve_vault_path(vm)
        ev = dict(ok=True, path=vp) if os.path.exists(os.path.join(vp, "manifest", "vault_manifest.json")) else SG.ensure_vault(vm)
        if ev["ok"] and ev["path"] != vm: SET["vault_mount"] = ev["path"]; ch = True
        if ev.get("created"): print(f"Data Vault created automatically: {ev['path']}", flush=True)
    if ch:
        with LOCK: jsave("settings.json", SET)
    return ch


def watcher():
    """every 30 s: calls-changed / same-patient conditions -> urgent notifications (resolved when they stop holding); unified job ends ->
    notifications; auto-train when switched on, the gate is open and enough train studies have new / changed reads."""
    while True:
        try: storage_autofix()
        except Exception as e: print(f"storage check: {e}", flush=True)
        try:
            st = SS.status(B, sel_studies()); live = set()
            for r in st["rows"]:
                for lb in r["labels"]:
                    if lb["kind"] in ("stale", "conflict"):
                        k = f"{lb['kind']}:{r['study']}"; live.add(k)
                        notify_c("urgent", "training", ("Calls changed after training" if lb["kind"] == "stale" else "Same patient on both sides") + f" · {r['study']}",
                                 lb["text"] + (" - Retrain, Hold, Keep, or move to Test / Exclude" if lb["kind"] == "stale" else " - Apply is blocked until fixed"),
                                 actions=["open_selection"], key=k, study=r["study"])
            for it in NC.log(B):
                if it.get("key") and it["key"].split(":")[0] in ("stale", "conflict") and it["key"] not in live and not it.get("resolved"): NC.resolve(B, it["key"])
            try:
                import unified_gui as UG
                for n, j in list(UG.JOBS.items()):
                    cur = j.get("status"); tag = j.get("started")
                    if cur in ("completed", "failed", "stopped") and WATCH["jobs"].get(n) != tag:   # every finished run, however short
                        WATCH["jobs"][n] = tag
                        if n == "train" and cur == "completed":
                            v = UG.validation() if hasattr(UG, "validation") else {}
                            ci = v.get("outer_auc_ci"); au = v.get("outer_auc_calibrated")
                            txt = f"AUC {au:.2f}" if isinstance(au, (int, float)) else "AUC n/a"
                            txt += (f" ({ci[0]:.2f}–{ci[1]:.2f})" if ci else "") + f" · {v.get('n_patients', '?')} patients, {v.get('n_cSS', '?')} cSS · probability {'allowed' if v.get('probability_output') else 'withheld'} · trained, NOT active"
                            notify_c("action", "training", "Trained model ready", txt, actions=["open_train"])
                        elif cur == "failed":
                            err = [l.strip() for l in (j.get("error") or "").splitlines() if l.strip()]
                            notify_c("action", "training", f"Unified {n} failed", (err[-1] if err else "see the job log")[:240], actions=["open_unified"])
                        else: notify_c("done", "training", f"Unified {n} {cur}")
            except Exception: pass
            A = SET["autotrain"]
            if A.get("on") and SS.gate(B).get("open") and UG_job("train").get("status") != "running" and time.time() - WATCH["autotrain_last"] > float(os.environ.get("CSS_AUTOTRAIN_GAP_S", "300")):
                pend = SS.pending_training(B, sel_studies())
                if len(pend) >= int(A.get("threshold", 3)):
                    import unified_gui as UG
                    WATCH["autotrain_last"] = time.time(); r_ = UG.train() or {}
                    if r_.get("disabled"):                   # I0: uScore training is disabled - say so once, never claim a run started
                        if not WATCH.get("autotrain_disabled_said"):
                            WATCH["autotrain_disabled_said"] = True
                            notify_c("action", "training", "uScore auto-train is disabled", "The separate uScore scorer can no longer train (no expert-provenance "
                                     "safeguards). Train PERCIVAL in PERCIVAL › Training Center instead.")
                    else: notify_c("done", "training", "Auto-train started", f"{len(pend)} train studies with new or changed reads: {', '.join(pend[:8])}")
        except Exception as e: print("watcher:", e, flush=True)
        try: PG.snapshot_reviews()                        # v5.23: immutable expert-review snapshots (labels + outputs shown at review time)
        except Exception as e: print("percival snapshots:", e, flush=True)
        try: PG.maybe_cycle()                             # v5.22: a controlled Percival training cycle once N newly finished studies accumulated
        except Exception as e: print("percival watcher:", e, flush=True)
        time.sleep(float(os.environ.get("CSS_WATCH_S", "30")))        # tests use a shorter interval
def proc_post(op, d):
    if op == "link":
        src = os.path.expanduser(d.get("source", "")); out = []
        try: models = PM.import_production_models(src, B)         # project-level production models, byte-for-byte + verified (rc2b)
        except Exception as e: models = {"error": str(e)[:300]}
        import study_admin as SA
        for c in d.get("codes", []):
            if not _pm_code(c): out.append(dict(code=c, ok=False, error="bad code")); continue
            ck = SA.check_ids(IDG.ID(), [p["code"] for p in PAT], code=c) if not pget(c) else []
            if ck: out.append(dict(code=c, ok=False, error="checkpoint: " + "; ".join(ck))); continue
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
        notify_c("done" if all(x["ok"] for x in out) else "action", "imports", f"Import: {sum(x['ok'] for x in out)} of {len(out)} studies brought in",
                 "; ".join(f"{x['code']}: {'ok' if x['ok'] else x.get('error', '')[:80]}" for x in out)[:300])
        return dict(ok=all(x["ok"] for x in out), results=out, models={k: dict(status=v.get("status"), parity=v.get("parity")) for k, v in models.items()} if isinstance(models, dict) and "error" not in models else models)
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
        r.update(duplicate_check(pick_["SWI"], ser))
    r["warnings"] += r.pop("warnings_dup", [])
    code_owner = next((p["code"] for p in PAT if r.get("code") and p["code"] == r["code"]), "")
    if code_owner and not r.get("duplicate_of"):
        r["warnings"].append(f"the code {r['code']} is already used by another study in this project (a different image, not a duplicate) - type a new code")
    if SET["features"].get("name_warning") and folder_is == "code" and looks_like_name(base):
        r["warnings"].append("the folder name looks like a person's name - it will be used as the study code")
    return r
def upgrade_fingerprint(p):
    """v5.15 additive migration of ONE study: compute the full content fingerprint of the SWI copy the import kept in raw/ID/SWI (the
    NIfTI file whose old 64 KB fingerprint is the stored one, or the copied DICOM series). The old value stays in fingerprint_v1;
    app_data/patients.json is backed up once before the first such change. Returns True when upgraded."""
    old = str(p.get("fingerprint", "")); d = f"{B}/raw/{p['code']}/SWI"; new = ""
    try:
        if os.path.isdir(f"{d}/_dicom") and os.listdir(f"{d}/_dicom"): new = SD.content_fingerprint(f"{d}/_dicom")
        else:
            for f in sorted(glob.glob(f"{d}/*.nii") + glob.glob(f"{d}/*.nii.gz")):
                with open(f, "rb") as fh: h1 = hashlib.sha1(fh.read(1 << 16)).hexdigest()[:16]
                if h1 == old: new = SD.content_fingerprint(f); break
    except Exception: return False
    if not new: return False
    bk = f"{AD}/backups/patients.before_fingerprint_v2.json"
    if not os.path.exists(bk):
        os.makedirs(os.path.dirname(bk), exist_ok=True); shutil.copy2(f"{AD}/patients.json", bk) if os.path.exists(f"{AD}/patients.json") else None
    p.update(fingerprint=new, fingerprint_v1=old, fingerprint_upgraded=time.time()); save_pat(); return True
def duplicate_check(swi_path, ser):
    """v5.15: is this SWI already in the project? exact = the complete image content (or the full DICOM SeriesInstanceUID) is identical;
    possible = only the old weak fingerprint of an earlier study matches (stored before v5.15: first 64 KB of the file). Different
    studies with the same protocol header are no longer duplicates; a renamed or moved folder of the same study still is."""
    v1 = next((x.get("fingerprint", "") for x in ser if x["path"] == swi_path), "")
    try: fp = SD.content_fingerprint(swi_path)
    except Exception as e: fp = ""; err = f"{type(e).__name__}: {e}"
    else: err = ""
    out = dict(fingerprint=fp, fingerprint_v1=v1, duplicate_of=[], duplicate_kind="", warnings_dup=[])
    for p in PAT:                    # a study known only by the old weak fingerprint that matches: settle it from its own raw copy first
        if fp and v1 and not str(p.get("fingerprint", "")).startswith(("c2:", "uid:")) and p.get("fingerprint") == v1: upgrade_fingerprint(p)
    exact = [p["code"] for p in PAT if fp and p.get("fingerprint") == fp]
    weak = [p["code"] for p in PAT if not exact and v1 and not str(p.get("fingerprint", "")).startswith(("c2:", "uid:")) and p.get("fingerprint") == v1]
    if exact:
        out.update(duplicate_of=exact, duplicate_kind="exact")
        out["warnings_dup"].append(f"DUPLICATE: this SWI is identical to the one already imported as {', '.join(exact)} (same "
                                   f"{'DICOM SeriesInstanceUID' if fp.startswith('uid:') else 'complete image content'}; folder name and location do not matter). "
                                   "It is left out; tick Include to import it again anyway.")
    elif weak:
        out.update(duplicate_of=weak, duplicate_kind="possible")
        out["warnings_dup"].append(f"possibly the same SWI as {', '.join(weak)}: only the older, weak fingerprint of that study is stored (first 64 KB of "
                                   "the file: header + empty corner, which different studies with the same protocol can share). Check before including.")
    if err: out["warnings_dup"].append(f"duplicate check not possible: {err}")
    return out
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
            if c in codes_now: errs.append(f"{c}: this code is already used by a study in the project - choose another code")
            elif c in seen: errs.append(f"{c}: this code appears more than once in this batch")
            seen.add(c)
        if not it.get("chosen", {}).get("SWI"): errs.append(f"{it.get('code') or it.get('folder_name')}: no SWI chosen")
    if st.get("results_dir"):
        okd, why = verify_local_dest(st["results_dir"])
        if not okd: errs.append(f"results folder refused: {why}")
    if errs: return dict(ok=False, errors=errs)
    added = []; pending_names = {}
    with LOCK:
        for it in items:
            code = it.get("code") or next_code()
            if st.get("store_names") and it.get("name") and IDG.reveal(SET): pending_names[code] = it["name"]     # v5.16: names go to the vault only
            pw = it.get("pathway") or ("recon" if st.get("anatomy") == "recon" else "synthseg")
            rec = it.get("pathway_rec") or pw
            p = dict(code=code, cohort=st.get("cohort", ""), anatomy="recon" if pw == "recon" else "synthseg", mode=st.get("mode", "semi"), pathway=pw,
                     results_dir=st.get("results_dir", ""), radiologist=it.get("radiologist", ""), grade_R=it.get("grade_R", ""), grade_L=it.get("grade_L", ""),
                     series=it["chosen"], fingerprint=it.get("fingerprint", ""), fingerprint_v1=it.get("fingerprint_v1", ""), step="", steps_done={}, added=time.time(),
                     status="decision" if (rec != (st.get("anatomy") or "synthseg") and not SET.get("auto_path", True) and it.get("decided") is not True) else "waiting",
                     path_note=(it.get("pathway_reason") or "") if rec != (st.get("anatomy") or "synthseg") or it.get("check") in ("changed", "look") else "", path_ack=False,
                     source_folder_hash=hashlib.sha1(it.get("folder", "").encode()).hexdigest()[:12])     # the folder path itself is not stored (may hold a name)
            apply_pathway(p, pw); PAT.append(p); added.append(code)
            coh = jload("cohorts.json", [])
            if p["cohort"] and p["cohort"] not in coh: coh.append(p["cohort"]); jsave("cohorts.json", coh)
        save_pat()
    write_grades_file()
    IDG.ensure(PAT)                                   # v5.16: every new study gets a uuid / patient record (deid code = its code)
    for code, nm in pending_names.items():
        try: IDG.edit(dict(code=code, patient_name=nm, confirm=True, reason="name given at import"), SET, by="add studies")
        except Exception: pass
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
    new = pd.DataFrame([dict(study_id=x["code"], R=x["grade_R"], L=x["grade_L"]) for x in PAT if x.get("grade_R") not in (None, "") and x.get("grade_L") not in (None, "")])
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
                # v5.16: a NIfTI series is staged under a NEUTRAL name (its original file name can contain a patient name, and it would be
                # copied into raw/ and the logs); the dcm2niix sidecar keeps the same base name so cohort.py still pairs them
                ext = ".nii.gz" if src.endswith(".nii.gz") else ".nii"; js = re.sub(r"\.nii(\.gz)?$", ".json", src)
                pairs = [(src, f"{d}/{mod}/{k}_series{ext}")] + ([(js, f"{d}/{mod}/{k}_series.json")] if os.path.exists(js) else [])
                for f, dst in pairs:
                    if not os.path.exists(dst): os.symlink(f, dst)
                continue
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
    p.update(status="done", finished=time.time(), step=""); save_pat(); notify("Percival", f"{os_label(code)} finished")
    try: NC.add(B, "done", "processing", f"Patient {code} finished", "pipeline complete")
    except Exception: pass
    try: write_results_file()
    except Exception as e: open(logf, "a").write(f"\nresults file not updated: {e}\n")
    queue_unified(p)                                # v5.14-gui: AFTER results are saved and the patient is done; background; opt-in
    try:                                            # Unified Score engine, SHADOW MODE: opt-in, subprocess, never changes this patient
        import shadow_engine_gui as SEG; SEG.after_done(p["code"], SET)
    except Exception as e: open(logf, "a").write(f"\nshadow engine not started: {e}\n")
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
        if op == "freeze": return UG.freeze(d.get("confirm", ""))                                    # Stage 1: retired (refuses)
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
# ------------------------------------------------------------------ Unified Score engine (SHADOW MODE) - app/shadow_engine_gui.py
def shadow_get(op, q):
    try:
        import shadow_engine_gui as SEG
        if op == "state": return SEG.state(PAT, SET)
        if op == "result": return SEG.result(q["study"])
        if op == "models": return SEG.models(force=q.get("force") == "1")
        return dict(error=f"unknown {op}")
    except Exception as e:
        return dict(error=f"shadow engine screen unavailable: {type(e).__name__}: {e}"[-400:], shadow_mode=True)
def shadow_post(op, d):
    try:
        import shadow_engine_gui as SEG
        if op == "enable":
            SET["features"]["shadow_engine"] = bool(d.get("on")); jsave("settings.json", SET); return dict(ok=True, enabled=SET["features"]["shadow_engine"])
        if op == "run":
            p = next((x for x in PAT if x["code"] == d.get("code")), None)
            if p is None or p.get("status") != "done": return dict(ok=False, error="study not finished")
            return SEG.run(p["code"])
        if op == "run_all":
            done = [x["code"] for x in PAT if x.get("status") == "done"]
            for c in done: SEG.run(c)
            return dict(ok=True, started=len(done))
        return dict(ok=False, error=f"unknown {op}")
    except Exception as e:
        return dict(ok=False, error=f"{type(e).__name__}: {e}"[-400:])
# ------------------------------------------------------------------ Image ML prototype (SYNTHETIC ONLY) - app/image_ml_gui.py
def image_get(op, q):
    try:
        import image_ml_gui as IMG
        if op == "state": return IMG.state()
        if op == "result": return IMG.result(q.get("study", ""))
        if op == "models": return IMG.models(force=q.get("force") == "1")
        return dict(error=f"unknown {op}")
    except Exception as e:
        return dict(error=f"Image ML screen unavailable: {type(e).__name__}: {e}"[-400:], synthetic_only=True)
def image_post(op, d):
    try:
        import image_ml_gui as IMG
        if op == "run": return IMG.run(str(d.get("code", "")))
        return dict(ok=False, error=f"unknown {op}")
    except Exception as e:
        return dict(ok=False, error=f"{type(e).__name__}: {e}"[-400:])
# ------------------------------------------------------------------ reviewer calls: every reviewer kept, effective call by policy (v5.15)
def calls_get(op, q):
    try:
        import review_calls_gui as RCG
        if op == "policy": return RCG.policy(B, PAT)
        if op == "study":
            p = pget(q.get("code", "")); return RCG.study_calls(B, q["code"], (p or {}).get("cohort", "")) if p else dict(error="unknown study")
        if op == "consolidate_plan": return RCG.consolidate_plan(B, PAT, q.get("scope", "study"), q.get("target", ""))
        if op == "roles": return RCG.roles(B)                                                    # Phase 3A.3
        return dict(error=f"unknown {op}")
    except Exception as e: return dict(error=f"{type(e).__name__}: {e}"[-400:])
def calls_post(op, d):
    try:
        import review_calls_gui as RCG
        by = str(d.get("by") or "").strip()
        if op == "policy": return RCG.set_policy(B, PAT, d.get("scope", "all"), d.get("target", ""), d.get("rule"), by=by)
        if op == "consolidate":
            if d.get("confirm") is None: return dict(ok=False, needs_confirm=True, error="destructive: type the confirmation phrase")
            return RCG.consolidate(B, PAT, d.get("scope", "study"), d.get("target", ""), str(d.get("confirm")), by=by)
        if op == "restore": return RCG.restore(B, d["code"], d["archive"])
        # Phase 3A.3/3A.4 administration (local administrator; typed confirmation + reason; every change journaled)
        if op == "role": return RCG.set_role(B, d.get("name", ""), d.get("role", ""), by, d.get("reason", ""), d.get("confirm", ""))
        if op == "adjudicator": return RCG.set_adjudicator(B, d.get("name", ""), bool(d.get("allowed")), by, d.get("reason", ""), d.get("confirm", ""))
        if op == "verify_historical": return RCG.verify_historical(B, str(d.get("code", "")), d.get("reviewer", ""), by, d.get("reason", ""), d.get("evidence", ""), d.get("confirm", ""))
        if op in ("adjudicate", "withdraw_adjudication"):
            p = pget(str(d.get("code", "")))
            if not p: return dict(ok=False, error="unknown study")
            if op == "adjudicate": return RCG.adjudicate(B, p["code"], p.get("cohort", ""), d.get("cand_id"), d.get("call", ""), str(d.get("adjudicator", "")), d.get("reason", ""))
            return RCG.withdraw_adjudication(B, p["code"], p.get("cohort", ""), d.get("cand_id"), str(d.get("adjudicator", "")), d.get("reason", ""))
        return dict(ok=False, error=f"unknown {op}")
    except PermissionError as e: return dict(ok=False, refused=True, error=str(e))
    except Exception as e: return dict(ok=False, error=f"{type(e).__name__}: {e}"[-400:])
# ------------------------------------------------------------------ Anatomy QC (FreeSurfer / SynthSeg), restored in v5.15 - app/qc_gui.py
def fsqc_get(op, q):
    try:
        import qc_gui as QG
        if op == "state": return QG.state(B, AD, PAT, SET, PM, PM.studies_on_disk(B), find_license)
        if op == "study": return QG.study(B, AD, q.get("code", ""), PM)
        if op == "install": return QG.install(SET, find_license)
        return dict(error=f"unknown {op}")
    except Exception as e: return dict(error=f"Anatomy QC unavailable: {type(e).__name__}: {e}"[-400:])
def fsqc_post(op, d):
    try:
        import qc_gui as QG
        code = str(d.get("code", ""))
        if not re.fullmatch(r"[A-Za-z0-9_\-]{1,32}", code): return dict(ok=False, error="bad study code")
        if op == "snapshot": return QG.make_snapshot(B, AD, code, qc_snapshot)
        if op == "freeview": return QG.freeview(B, code, SET, d.get("what", "swi"), find_license=find_license)
        return dict(ok=False, error=f"unknown {op}")
    except Exception as e: return dict(ok=False, error=f"{type(e).__name__}: {e}"[-400:])
# ------------------------------------------------------------------ identification (v5.16) - app/identity_gui.py
def id_get(op, q):
    try:
        if op == "state": return IDG.state(SET, PAT)
        if op == "study": return IDG.ident(q.get("code", ""), SET)
        if op == "history": return dict(history=IDG.history(q.get("code", ""), SET))
        if op == "import/series": return IDG.IW.series_view(q.get("plan", ""), q.get("eid", ""))
        if op == "library/job":
            import study_library as SLB
            return SLB.job(q.get("id", "")) or dict(error="unknown library job")
        return dict(error=f"unknown {op}")
    except Exception as e: return dict(error=f"{type(e).__name__}: {e}"[-300:])
def id_post(op, d):
    by = str(d.get("by") or "").strip() or "app user"
    try:
        if op == "mode": return IDG.set_mode(SET, d.get("mode"), str(d.get("passphrase", "")), save=lambda: jsave("settings.json", SET))
        if op.startswith("vault/"): return IDG.vault(op[6:], d, SET, names=names, verify_dest=verify_local_dest)
        if op == "edit": return IDG.edit(d, SET, by)
        if op == "template/save":                       # v5.18: the app window (pywebview) does not handle browser downloads - save via a chosen folder
            import manifest as MF
            dest = os.path.realpath(os.path.expanduser(str(d.get("dest", ""))))
            okd, why = verify_local_dest(dest)
            if not okd: return dict(ok=False, error=f"folder refused: {why} (the filled-in template holds patient identifiers - keep it on local, non-synced storage)")
            out = os.path.join(dest, "Percival_Import_Template.xlsx"); n = 2
            while os.path.exists(out): out = os.path.join(dest, f"Percival_Import_Template ({n}).xlsx"); n += 1
            with open(out, "wb") as f_: f_.write(MF.template_bytes())
            if d.get("open") and mac(): subprocess.run(["open", out])
            return dict(ok=True, path=out)
        if op == "import/plan": return IDG.plan(d, SET, [p["code"] for p in PAT], verify_dest=verify_local_dest, hooks=dict(pathway=check_pathway, looks_like_name=(looks_like_name if SET["features"].get("name_warning") else None), describe=describe_study, known_match=known_match))
        if op == "import/update": return IDG.plan_update(d, [p["code"] for p in PAT], verify_dest=verify_local_dest)
        if op in ("import/commit", "import/commit_start"):
            pl = IDG.IW.PLANS.get(str(d.get("plan", ""))); lib = dict(pl["library"]) if pl else {}
            def _do_commit(rep=None):
                try:
                    r = IDG.plan_commit(d, add_to_queue, dict(cohort=d.get("cohort", ""), mode="semi", _resolve=resolve_duplicate, _reuse=reuse_processed,
                                                             _replace_confirm=str(d.get("replace_confirm", "")).strip(), _progress=rep), by, import_src=f"{AD}/import_src")
                except Exception as e:
                    r = dict(ok=False, error=IDG.redact_text(f"{e}", SET, B)[-400:], kind=type(e).__name__)
                if r.get("ok") and lib.get("enabled") and lib.get("root"):              # remember the library place for the next import
                    SET["library_dir"] = lib["root"]; SET["library_whole_exam"] = bool(lib.get("whole_exam")); jsave("settings.json", SET)
                if r.get("ok"):
                    n = len(r.get("imported", [])); r["summary"] = f"{n} examination(s) imported and queued for processing"
                    notify_c("done", "imports", f"Import finished: {n} examination(s) added", "queued for processing" + (" · library copy running" if r.get("library_job") else ""),
                             actions=["open_activity"])
                elif rep is not None:                                                    # background import: the result must not be lost if the window was put away
                    notify_c("action", "imports", "Import needs your attention - nothing was imported", (r.get("error") or "")[:300], actions=["open_add"])
                if r.get("ok") and IDG.mode(SET) == "incognito" and pl and pl["mode"] == "incognito": IDG.ID().lock()      # the key was stored; Incognito keeps the vault locked
                return r
            if op == "import/commit": return _do_commit()
            if d.get("confirm") is not True: return dict(ok=False, needs_confirm=True, error="confirm the validated preview to import")
            import progress_jobs as PJ
            if PJ.running("import"): return dict(ok=False, error="an import is already running - wait for it to finish (see the progress pill, bottom right)")
            n_inc = sum(1 for e in (pl or {}).get("exams", []) if e.get("include"))
            return dict(ok=True, job=PJ.start("import", n_inc + 1, _do_commit, title=f"Importing {n_inc} examination(s)"), n=n_inc)
        return dict(ok=False, error=f"unknown {op}")
    except Exception as e: return dict(ok=False, error=IDG.redact_text(f"{e}", SET, B)[-400:], kind=type(e).__name__)
# ------------------------------------------------------------------ v5.22 PERCIVAL SCORE - app/percival_gui.py, unified_engine/uengine/percival/
def pg_init():
    import review_calls_gui as RCG
    def reviewed(c):
        try: return RCG.state(B, c, (pget(c) or {}).get("cohort", "")).get("state") == "reviewed"
        except Exception: return False
    def patient_of(c):
        """v5.25: the patient record of a study, or None - never the study code (that substitution hid unmapped repeat examinations)"""
        u = IDG.ID().by_file_key(c); return (IDG.ID().R["studies"].get(u) or {}).get("patient_uuid") or None
    def identity_of(c):
        from uengine.imaging.index import is_synthetic_study
        I = IDG.ID(); u = I.by_file_key(c); st = I.identity_status(u)
        if u and u in I.identity_conflicts(): st = dict(st, status="conflict", detail="the same examination fingerprint / DICOM study belongs to another patient record")
        elif is_synthetic_study(B, c) and st.get("status") in ("assumed", "unconfirmed"):
            st = dict(st, status="declared", detail="synthetic development cohort (known truth, no clinical identity)")
        return dict(st, study_uuid=u, patient=(I.R["studies"].get(u) or {}).get("patient_uuid"))
    def fingerprint_of(c):
        u = IDG.ID().by_file_key(c); return (IDG.ID().R["studies"].get(u) or {}).get("fingerprint", "") or (pget(c) or {}).get("fingerprint", "")
    def other_projects():                                  # v5.24 review recovery: enabled earlier projects on this Mac (patients.json only)
        import known_projects as KP
        return [dict(path=c["path"], kind=c["kind"], patients=KP._pats(c["path"])) for c in KP.candidates(B, SET, PM.studies_on_disk) if c["enabled"]]
    PG.init(B=B, SC=SC, SET=SET, patients=lambda: list(PAT), is_reviewed=reviewed, label=study_label, patient_of=patient_of, identity_of=identity_of, fingerprint_of=fingerprint_of,
            save_settings=lambda: jsave("settings.json", SET), notify=lambda t, x: notify_c("done", "training", t, x), other_projects=other_projects)
def pg_get(op, q):
    if op == "state": return PG.state()
    if op in ("score", "history", "contracts", "pensieve_history", "second_review"):          # Phase 3A.2: not before the blind review
        bs = BG.state(B, q.get("code", ""))
        if bs["pending"]: return dict(none=True, hidden=True, reason=bs["reason"]) if op == "score" else dict(ledger=[], hidden=True, reason=bs["reason"])
    if op == "score":
        p = PG.P("scores", f"{q.get('code', '')}.json"); return json.load(open(p)) if os.path.exists(p) else dict(none=True)
    if op == "model":
        m = PG.load(q.get("version", "")) or {}; return {k: v for k, v in m.items() if k not in ("components", "meta_ensemble")}
    if op == "history": return dict(ledger=PG.history_of(q.get("code", "")))
    if op == "reviews": return dict(reviews=PG.reviews_of(q.get("code", "")))
    if op == "candidates": return PG.candidates_of(q.get("code", ""))                        # v5.24 Training Center drill-down
    if op == "compat": return PG.compat_report()                                             # v5.24 Data integrity
    if op == "recoverable": return dict(items=PG.recoverable_reviews())
    if op == "runs": return dict(runs=PG.runs())                                               # v5.24 training runs
    if op == "run": return PG._jl(PG.P("runs", os.path.basename(q.get("id", "")) + ".json"), dict(error="unknown run"))
    if op == "registry": return dict(registry=PG.registry())
    if op == "identity": return PG.identity_report()                                         # v5.25 patient identity per study
    if op == "job": return PG.job_state()                                                    # v5.25 live training job (heartbeat, ETA, resources)
    if op == "eligibility": return PG._jl(PG.P("eligibility", "current.json"), dict(error="not evaluated yet"))
    if op == "readiness": return PG.readiness()                                              # 3D
    if op == "split": return PG.split_state()
    if op == "shadow": return PG.shadow_summaries()                                          # v5.24 Percival shadow mode                        # only on request: reads other projects' patients.json
    if op == "architecture": return PG.architecture_state()                                  # architecture: honest component states
    if op == "contracts": return PG.candidate_contracts(q.get("code", ""))                      # PERCIVAL candidate contracts (no patient ids)
    if op == "components_report": return PG.components_report()
    if op == "pensieve_index": return PG.pensieve_index_state()                                 # PENSIEVE (derived per-project index)
    if op == "pensieve_history": return PG.pensieve_history(q.get("code", ""), q.get("cand", "0"))
    if op == "shadow_gov": return PG.shadow_gov_state()                                         # SHADOW governed discovery
    if op == "albus": return PG.albus_state()                                                   # ALBUS detector evaluation + registry
    if op == "pensieve": return PG.pensieve_state()                                          # v5.25 PENSIEVE Core Memory
    if op == "pensieve_query": return PG.pensieve_query(q.get("component", "albus"))
    if op == "vault": return PG.vault_status()                                               # v5.25 PERCIVAL DATA VAULT status
    if op == "missed_lesions":                                                                # Stage 1: legacy PENSIEVE reader retired
        return dict(ok=False, retired=True, error="retired: missed-cSS marks live in review/ID_missed.csv (reviewer) and in the PENSIEVE index")
    if op == "events":                                                                         # Stage 5: event log integrity + replay check
        from uengine import event_log as EV
        return dict(verify=EV.verify(PG.P()), recent=EV.read(PG.P())[-30:])
    if op == "config": return PG.config_snapshot()                                             # Stage 5: the one versioned configuration
    if op == "evaluation_plan": return dict(plan=PG.evaluation_plan(), template=PG.PLAN_TEMPLATE, consultations=PG.test_consultations(),
                                            confirm_phrase=PG.PLAN_CONFIRM)                       # Stage 6: validation governance
    if op == "reader_agreement": return PG.reader_agreement()
    if op == "drift": return PG.drift_state()
    if op == "analysis": return PG.analysis_state()                                            # Stage 3: small-data honesty analyses
    if op == "study_level": return PG.study_level_state()                                      # Stage 3: study-level 0-4 vs expert grades
    if op == "second_review": return PG.second_review(q.get("code", ""))                       # Stage 3: active learning (after the blind read)
    if op == "shadow_lab": return PG.shadow_lab_state()                                      # v5.25 SHADOW ML Research Lab
    if op == "dataset":
        from uengine.percival import datasets as DS
        return DS.load(PG.P(), q.get("id", "")) or dict(error="unknown dataset")
    return dict(error=f"unknown {op}")
def pg_post(op, d):
    try:
        if op == "authorize":
            r = PG.authorize(bool(d.get("on", True)), by=str(d.get("by") or "app user"))
            if d.get("on", True): SET["features"]["unified_score"] = True; jsave("settings.json", SET)
            return r
        if op == "train": return PG.train_async("started by you")
        if op == "promote": return PG.promote(str(d.get("version", "")), by=str(d.get("by") or "app user"), why=str(d.get("why") or "made active by you"),
                                              override=bool(d.get("override")))
        if op == "status": return PG.set_status(str(d.get("version", "")), str(d.get("status", "")), why=str(d.get("why") or ""))     # v5.24 reject / retire / restore
        if op == "eligibility": return PG.eligibility_record()                                    # v5.24 re-evaluate + record eligibility
        if op == "reproduce": return PG.reproduce_dataset(str(d.get("id", "")))                   # v5.24 dataset reproducibility
        if op == "rollback": return PG.rollback()
        if op == "recover": return PG.recover_reviews()
        if op == "shadow": return PG.shadow_async(str(d.get("version", "")))
        if op == "select": return PG.set_selection(d.get("codes", []), bool(d.get("include", True)))
        if op == "settings":
            if "percival_test_fraction" in d:                                   # 3D: the split is locked once it exists
                from uengine.percival import split as _SP
                if _SP.current(PG.P()): return dict(ok=False, error="the patient-level split is locked: changing the test fraction needs a new split version (Training Center)")
                try: f_ = float(d["percival_test_fraction"])
                except (TypeError, ValueError): return dict(ok=False, error="invalid test fraction")
                if not 0.05 <= f_ <= 0.5: return dict(ok=False, error="test fraction must be between 0.05 and 0.5")
                SET["percival_test_fraction"] = f_
            for k in ("percival_autocycle", "percival_cycle_n"):
                if k in d: SET[k] = d[k]
            if "percival_learn_from" in d: SET["percival_learn_from"] = "finished" if d["percival_learn_from"] == "finished" else "labelled"
            if "percival_conflicts" in d: SET["percival_conflicts"] = "effective" if d["percival_conflicts"] == "effective" else "exclude"
            if "percival_use_historical" in d: SET["percival_use_historical"] = bool(d["percival_use_historical"])
            jsave("settings.json", SET); return dict(ok=True)
        if op in ("score", "score_unified"):                                                  # Phase 3A.2: not before the blind review
            bs = BG.state(B, str(d.get("code") or d.get("study_id") or ""))
            if bs["pending"]: return dict(ok=False, hidden=True, error=BG.HIDDEN + ": " + bs["reason"])
        if op == "score": return PG.score_study(str(d.get("code", ""))) or dict(ok=False, error="no active model or no candidates")
        if op == "confirm_identity":                                                              # v5.25 patient identity (audited, reversible)
            I = IDG.ID(); codes = [str(c) for c in d.get("codes", [])]; us = [I.by_file_key(c) for c in codes]
            if not codes or not all(us): return dict(ok=False, error="unknown study")
            if d.get("undo"): return dict(ok=True, n=I.unconfirm_identity(us, str(d.get("by") or "app user"), str(d.get("why") or "")))
            return dict(ok=True, n=I.confirm_identity(us, str(d.get("by") or "app user"), str(d.get("statement") or "")))
        if op == "job":                                                                           # v5.25 Training Center job control
            a = str(d.get("action", ""))
            if a == "cancel": return PG.cancel_training(by=str(d.get("by") or "app user"))
            if a == "retry": return PG.train_async("retry from the start (previous run " + str(d.get("run", "")) + ")")
            return dict(ok=False, error="unknown job action")
        if op == "vault_connect": return PG.vault_connect(str(d.get("path", "")))
        if op == "vault_create": return PG.vault_create(str(d.get("destination", "")), name=str(d.get("name", "PERCIVAL_VAULT")))
        if op == "vault_eject": return PG.vault_eject()
        if op == "vault_backup": return PG.vault_backup(str(d.get("destination", "")))
        if op == "missed_lesion":                                                             # Phase 3A.5: disabled (it wrote unvalidated rows)
            return dict(ok=False, error="disabled: missed-cSS marks are recorded in the reviewer (validated, one journaled file per reviewer)")
        if op == "component_freeze": return PG.component_freeze(d.get("component", ""), d.get("by", ""), d.get("reason", ""), d.get("confirm", ""))       # Stage 2
        if op == "component_rollback": return PG.component_rollback(d.get("component", ""), d.get("by", ""), d.get("reason", ""), d.get("confirm", ""))
        if op == "evaluation_plan": return PG.evaluation_plan_save(d.get("plan") or {}, d.get("by", ""), d.get("reason", ""), d.get("confirm", ""))   # Stage 6
        if op == "milestone": return PG.milestone_declare(d.get("name", ""), d.get("by", ""), d.get("reason", ""), d.get("confirm", ""), bool(d.get("fresh_test_cohort")))
        if op == "pensieve_rebuild": return PG.pensieve_index_rebuild()
        if op.startswith("shadow_gov_"): return PG.shadow_gov_post(op[len("shadow_gov_"):], d)
        if op == "shadow_run": return PG.shadow_run_trial(str(d.get("target", "ALBUS")), str(d.get("hypothesis", "")), d.get("config", {}))
        if op == "score_unified": return PG.score_study_unified(str(d.get("study_id", "")))
        if op == "split_new_version": return PG.split_new_version(float(d.get("fraction", 0)), d.get("by", ""), d.get("reason", ""), d.get("confirm", ""))   # 3D
        if op == "dataset_export": return PG.export_dataset(str(d.get("id", "")))
        return dict(ok=False, error=f"unknown {op}")
    except Exception as e: return dict(ok=False, error=f"{type(e).__name__}: {e}"[:400])
# ------------------------------------------------------------------ v5.25 Storage, Health, Wizard, Recovery & Migration APIs
def _safe_path_segment(v):
    """Phase 0: a value that is joined into a file path must be one plain path segment (no traversal)"""
    return isinstance(v, str) and v not in ("", ".", "..") and "/" not in v and "\\" not in v and "\x00" not in v and ".." not in v

def _transfer_guard(scope, op, d):
    """Phase 1e.2: migrations are disabled; maintenance that could remove, move or clean data an unfinished transfer
    job still needs (for a resume / discard) is refused. Returns a refusal dict, or None. Read-only journal view."""
    from uengine.transfer import guards as G
    d = d if isinstance(d, dict) else {}
    if (scope, op) in (("storage", "migrate_execute"), ("migration", "execute")):
        return dict(ok=False, error=G.MIGRATIONS_DISABLED, migration_disabled=True)
    try:
        if (scope, op) in (("storage", "prune"), ("storage", "free_space_execute"), ("clean", "execute"), ("clean", "quarantine_purge")):
            jobs = G.unfinished_jobs(B)
            return G.refusal(jobs, f"{scope}/{op}") if jobs else None
        code = {("storage", "delete"): d.get("code"), ("storage", "clean"): d.get("code"),
                ("clean", "delete_study"): d.get("study_code"), ("workspace", "clean"): d.get("study_id")}.get((scope, op))
        if code is not None:
            jobs = G.conflicts_with_study(B, str(code))
            return G.refusal(jobs, f"{scope}/{op} of {code}") if jobs else None
        if scope == "files" and op in ("delete", "move", "rename"):
            p = d.get("path") or d.get("src") or ""
            jobs = G.conflicts_with_paths(B, [os.path.abspath(p)]) if p else []
            return G.refusal(jobs, f"files/{op} of {p}") if jobs else None
    except Exception as e:                                   # cannot tell -> do not allow the destructive operation
        return dict(ok=False, error=f"Refused: unfinished transfers could not be checked ({type(e).__name__}: {e})")
    return None

def files_get(op, q):
    try:
        from uengine.file_manager import FileManager
        fm = FileManager(B, vault_root=SET.get("vault_mount"))
        if op == "categories":
            return dict(ok=True, categories=fm.get_categories())
        if op == "browse":
            cat = q.get("category", "working")
            sub = q.get("subpath", "")
            search = q.get("search", "")
            sort_by = q.get("sort_by", "name")
            sort_dir = q.get("sort_dir", "asc")
            return fm.browse_category_path(cat, sub, search, sort_by, sort_dir)
        if op == "overview":
            return fm.get_storage_overview()
        return dict(ok=False, error=f"unknown {op}")
    except Exception as e:
        return dict(ok=False, error=f"file manager error: {type(e).__name__}: {e}")

def files_post(op, d):
    _g = _transfer_guard("files", op, d)                   # Phase 1e.2
    if _g is not None:
        return _g
    try:
        from uengine.file_manager import FileManager
        fm = FileManager(B, vault_root=SET.get("vault_mount"))
        if op == "copy":
            return fm.copy_item(d.get("src", ""), d.get("dst_dir", ""), d.get("conflict_mode", "keep_both"))
        if op == "move":
            return fm.move_item(d.get("src", ""), d.get("dst_dir", ""), d.get("conflict_mode", "keep_both"))
        if op == "rename":
            return fm.rename_item(d.get("path", ""), d.get("new_name", ""))
        if op == "mkdir":
            return fm.create_directory(d.get("parent_dir", ""), d.get("dir_name", ""))
        if op == "delete":
            return fm.delete_item(d.get("path", ""), bool(d.get("confirm")))
        if op == "archive":
            return fm.archive_entry(d.get("src", ""), d.get("vault_category", "archive"))
        if op == "restore":
            return fm.restore_entry(d.get("vault_path", ""), d.get("dst_dir", ""))
        if op == "verify":
            from uengine.safety import SafetyError
            try: p = fm.policy.check_source(d.get("path", ""))          # Phase 0: only project / Vault files can be hashed
            except SafetyError as e: return dict(ok=False, error=f"Refused: {e}")
            if os.path.isfile(p):
                from uengine.file_manager import compute_hash
                h = compute_hash(p)
                return dict(ok=True, path=p, sha256=h, verified=True)
            return dict(ok=False, error="Not a regular file")
        return dict(ok=False, error=f"unknown {op}")
    except Exception as e:
        return dict(ok=False, error=f"file operation error: {type(e).__name__}: {e}")

def storage_get(op, q):
    try:
        from uengine.file_manager import FileManager
        from uengine.storage_advisor import StorageAdvisor
        from uengine.storage_service import StorageService
        vault_root = SET.get("vault_mount")
        fm = FileManager(B, vault_root=vault_root)
        sa = StorageAdvisor(B, vault_mount=vault_root)
        if op == "overview":
            force = str(q.get("force", "")).lower() in ("1", "true")
            ov = StorageService.get_overview(B, vault_root=vault_root, force_refresh=force)
            ov["fm_overview"] = fm.get_storage_overview()
            try:
                from uengine.storage import StoragePathsService, StorageIntelligence
                si = StorageIntelligence(StoragePathsService(B, vault_root))
                ov["detailed_metrics"] = si.get_detailed_storage_metrics()
            except Exception:
                pass
            return ov
        if op == "detailed_metrics":
            from uengine.storage import StoragePathsService, StorageIntelligence
            si = StorageIntelligence(StoragePathsService(B, vault_root))
            return si.get_detailed_storage_metrics()
        if op == "diagnostics":
            return dict(ok=True, tests=StorageService.run_storage_diagnostics(B, vault_root=vault_root))
        if op == "eject_check":
            from uengine.storage import StoragePathsService, EjectManager
            em = EjectManager(StoragePathsService(B, vault_root))
            return em.check_ejection_safety().to_dict()
        if op == "sync_overview":
            from uengine.storage import StoragePathsService, SyncManager
            sm = SyncManager(StoragePathsService(B, vault_root))
            return sm.get_sync_overview()
        if op == "sync_policy":
            from uengine.storage import StoragePathsService, SyncManager
            sm = SyncManager(StoragePathsService(B, vault_root))
            return dict(ok=True, policy=sm.get_sync_policy())
        if op == "sync_preview":
            from uengine.storage import StoragePathsService, SyncManager
            sm = SyncManager(StoragePathsService(B, vault_root))
            return sm.generate_sync_preview(study_ids=q.get("study_ids"), mode=q.get("mode", "manual")).to_dict()
        if op == "audit":
            from uengine.storage import StoragePathsService, StorageStateService
            ss = StorageStateService(StoragePathsService(B, vault_root))
            return dict(ok=True, events=ss.get_audit_events(limit=int(q.get("limit", 50)), study_id=q.get("study_id")))
        if op == "jobs":
            from uengine.storage import StoragePathsService, StorageStateService
            ss = StorageStateService(StoragePathsService(B, vault_root))
            return dict(ok=True, jobs=ss.get_all_jobs(limit=int(q.get("limit", 50))))
        if op == "studies": return dict(studies=fm.list_studies(filter_status=q.get("status")))
        if op == "tree": return fm.browse_study_tree(q.get("code", ""))
        if op == "advisor": return sa.generate_recommendations()
        if op == "capacity": return sa.evaluate_capacity()
        if op == "free_space_preview":
            from uengine.transfer_manager import TransferManager
            tm = TransferManager(B, vault_root=vault_root)
            return tm.free_up_mac_space_preview()
        return dict(error=f"unknown storage op {op}")
    except Exception as e: return dict(error=f"{type(e).__name__}: {e}")

def storage_post(op, d):
    _g = _transfer_guard("storage", op, d)                   # Phase 1e.2
    if _g is not None:
        return _g
    try:
        from uengine.file_manager import FileManager
        from uengine.storage_advisor import StorageAdvisor
        vault_root = SET.get("vault_mount")
        fm = FileManager(B, vault_root=vault_root)
        sa = StorageAdvisor(B, vault_mount=vault_root)
        if op == "stage": return fm.stage_study(d.get("code", ""))
        if op == "archive": return fm.archive_study(d.get("code", ""))
        if op == "verify": return fm.verify_study_checksums(d.get("code", ""))
        if op == "eject":
            from uengine.storage import StoragePathsService, EjectManager
            em = EjectManager(StoragePathsService(B, vault_root))
            # Phase 0: force is honoured only with the server-issued token AND the volume name the user typed
            return em.eject_vault(emergency=bool(d.get("emergency", False)), force=d.get("force") is True,
                                  force_token=str(d.get("force_token", "") or ""), confirm_volume_name=str(d.get("confirm_volume_name", "") or ""))
        if op == "sync_execute":
            from uengine.storage import StoragePathsService, SyncManager
            sm = SyncManager(StoragePathsService(B, vault_root))
            return sm.execute_sync(d.get("preview", {}))
        if op == "sync_policy":
            from uengine.storage import StoragePathsService, SyncManager
            sm = SyncManager(StoragePathsService(B, vault_root))
            return sm.save_sync_policy(d.get("policy", {}))
        if op == "clean": return fm.clean_staging(d.get("code", ""))
        if op == "prune": return sa.execute_prune(d.get("action", ""), max(1, int(d.get("days", 7))))   # Phase 0: never "everything" (days 0)
        if op == "delete": return fm.delete_study(d.get("code", ""), target=d.get("target", "local"))
        if op == "free_space_execute":
            from uengine.transfer_manager import TransferManager
            tm = TransferManager(B, vault_root=vault_root)
            return tm.execute_free_up_mac_space()
        if op == "migrate_plan":
            from uengine.working_dir_migration import WorkingDirMigrationEngine
            engine = WorkingDirMigrationEngine(B)
            return engine.plan_migration(d.get("target_dir", ""))
        if op == "migrate_execute":
            from uengine.working_dir_migration import WorkingDirMigrationEngine
            engine = WorkingDirMigrationEngine(B)
            res = engine.execute_migration(d.get("target_dir", ""), bool(d.get("verify_checksums", True)))
            if res.get("ok"):
                with LOCK:
                    SET["workspace_dir"] = res["target_dir"]
                    jsave("settings.json", SET)
            return res
        return dict(ok=False, error=f"unknown storage post op {op}")
    except Exception as e: return dict(ok=False, error=f"{type(e).__name__}: {e}")

def workspace_get(op, q):
    try:
        from uengine.study_workspace_manager import StudyWorkspaceManager
        swm = StudyWorkspaceManager(B, vault_root=SET.get("vault_mount"))
        if op == "discover":
            return dict(ok=True, discovered=swm.discover_source_studies())
        if op == "queue":
            return dict(ok=True, queue=swm.get_queue())
        if op == "studies":
            return dict(ok=True, studies=swm.list_studies(q.get("state")))
        if op == "study":
            return dict(ok=True, study=swm.get_study(q.get("study_id", "")))
        if op == "capacity":
            return dict(ok=True, capacity=swm.estimate_capacity(q.get("study_id", "")))
        if op == "reconcile":
            return swm.reconcile_studies()
        return dict(ok=False, error=f"unknown workspace op {op}")
    except Exception as e: return dict(ok=False, error=str(e))

def workspace_post(op, d):
    _g = _transfer_guard("workspace", op, d)                   # Phase 1e.2
    if _g is not None:
        return _g
    try:
        from uengine.study_workspace_manager import StudyWorkspaceManager
        swm = StudyWorkspaceManager(B, vault_root=SET.get("vault_mount"))
        if op == "register":
            rec = swm.register_study(d.get("study_id", ""), d.get("original_mri_location", ""), metadata=d.get("metadata"))
            return dict(ok=True, study=rec)
        if op == "batch_register":
            return swm.batch_register_discovered(d.get("study_ids"))
        if op == "stage":
            ok, msg, rec = swm.stage_study(d.get("study_id", ""), d.get("source_paths"))
            return dict(ok=ok, message=msg, study=rec)
        if op == "archive":
            ok, msg = swm.archive_study(d.get("study_id", ""))
            return dict(ok=ok, message=msg)
        if op == "clean":
            ok, msg = swm.clean_eligible_workspace(d.get("study_id", ""))     # Phase 0: no client-controlled force
            return dict(ok=ok, message=msg)
        if op == "enqueue":
            return swm.enqueue_study(d.get("study_id", ""), priority=int(d.get("priority", 0)))
        if op == "process_next":
            ok, msg, cur = swm.process_next_in_queue()
            return dict(ok=ok, message=msg, current=cur)
        return dict(ok=False, error=f"unknown workspace post op {op}")
    except Exception as e: return dict(ok=False, error=str(e))

def vault_get(op, q):
    try:
        from uengine.vault import get_vault, detect_external_volumes
        v = get_vault(SET.get("vault_mount"))
        if op == "status":
            detected = detect_external_volumes()
            return dict(ok=True, status=v.get_connection_status(), stats=v.get_storage_stats(),
                        integrity=v.verify_integrity() if v.is_connected() else {"ok": False},
                        detected_volumes=detected)
        if op == "detect_volumes":
            return dict(ok=True, volumes=detect_external_volumes())
        if op == "manifest":
            return dict(ok=True, manifest=v._manifest)
        return dict(ok=False, error=f"unknown vault op {op}")
    except Exception as e: return dict(ok=False, error=str(e))

def vault_post(op, d):
    try:
        from uengine.vault import get_vault, PercivalDataVault
        v = get_vault(SET.get("vault_mount"))
        if op == "connect":
            p = str(d.get("path", "")).strip()
            ok, msg = v.connect(p, auto_create_if_drive=True)
            if ok:
                with LOCK:
                    SET["vault_mount"] = v.root_path
                    jsave("settings.json", SET)
            return dict(ok=ok, message=msg, stats=v.get_storage_stats(), root_path=v.root_path)
        if op == "create":
            dest = str(d.get("destination", "")).strip()
            name = str(d.get("name", "PERCIVAL_VAULT")).strip()
            nv = PercivalDataVault.create_vault(dest, name=name)
            with LOCK:
                SET["vault_mount"] = nv.root_path
                jsave("settings.json", SET)
            return dict(ok=True, path=nv.root_path, stats=nv.get_storage_stats())
        if op == "open_finder":
            ok, msg = v.open_in_finder()
            return dict(ok=ok, message=msg)
        if op == "verify":
            return dict(ok=True, integrity=v.verify_integrity())
        if op == "reindex":
            return v.rebuild_index()
        return dict(ok=False, error=f"unknown vault post op {op}")
    except Exception as e: return dict(ok=False, error=str(e))

def app_lifecycle_get(op, q):
    try:
        if op == "shutdown_check":
            running_pts = [p["code"] for p in PAT if p.get("status") in ("running", "starting", "paused")]
            from uengine.transfer_manager import TransferManager
            tm = TransferManager(B, vault_root=SET.get("vault_mount"))
            active_transfers = [it for it in tm.get_queue() if it.get("status") in ("transferring", "pending")]
            from uengine.pensieve import DurableLocalJournal
            jnl = DurableLocalJournal()
            pending_jnl = len(jnl.get_pending_entries())

            can_quit_immediately = (len(running_pts) == 0 and len(active_transfers) == 0)
            return dict(
                ok=True,
                can_quit_immediately=can_quit_immediately,
                running_studies=running_pts,
                active_transfers_count=len(active_transfers),
                pending_journal_count=pending_jnl
            )
        return dict(ok=False, error=f"unknown app op {op}")
    except Exception as e: return dict(ok=False, error=str(e))

def app_lifecycle_post(op, d):
    try:
        if op == "shutdown":
            pause_jobs = bool(d.get("pause_jobs", True))
            threading.Thread(target=_perform_safe_shutdown, args=(pause_jobs,), daemon=False).start()
            return dict(ok=True, message="Safe shutdown initiated.")
        return dict(ok=False, error=f"unknown app post op {op}")
    except Exception as e: return dict(ok=False, error=str(e))

def _perform_safe_shutdown(pause_jobs: bool = True):
    try:
        try:
            transfer_pool_shutdown(timeout=15.0)              # Phase 1d: running transfers pause at a safe boundary
        except Exception:
            pass
        if pause_jobs:
            with LOCK:
                for p in PAT:
                    if p.get("status") in ("running", "starting"):
                        p["status"] = "paused"
                        p["error"] = "Paused for application shutdown"
                save_pat()
        try:
            from uengine.pensieve import get_pensieve
            p_mem = get_pensieve()
            p_mem.flush_and_close()
        except Exception:
            pass
        with LOCK:
            jsave("settings.json", SET)
        if WIN.get("window"):
            try:
                WIN["window"].destroy()
            except Exception:
                pass
        time.sleep(0.4)
    finally:
        os._exit(0)

_TRANSFER_POOL = {"pool": None}
_TRANSFER_POOL_LOCK = threading.Lock()

def transfer_pool():
    """Phase 1d: the background transfer worker pool (journal-backed; created on first use, started once)"""
    with _TRANSFER_POOL_LOCK:
        if _TRANSFER_POOL["pool"] is None:
            from uengine.transfer.workers import TransferWorkerPool
            _TRANSFER_POOL["pool"] = TransferWorkerPool(B, SET.get("vault_mount")).start()
        return _TRANSFER_POOL["pool"]

def transfer_pool_shutdown(timeout=15.0):
    with _TRANSFER_POOL_LOCK:
        pool = _TRANSFER_POOL["pool"]
    if pool is None:
        return None
    try:
        return pool.shutdown(timeout=timeout)
    finally:
        pool.close()
        _TRANSFER_POOL["pool"] = None

def transfer_get(op, q):
    if op in ("jobs", "job", "assess", "workers", "vault_check"):   # Phase 1d/1e endpoints (uengine/transfer/api.py)
        try:
            from uengine.transfer import api as TAPI
            return TAPI.handle_get(op, q, transfer_pool())
        except Exception as e:
            return dict(ok=False, error=dict(code="internal", message=f"{type(e).__name__}: {e}"))
    try:
        from uengine.transfer_manager import TransferManager
        from uengine.unified_transfer_engine import get_transfer_engine
        tm = TransferManager(B, vault_root=SET.get("vault_mount"))
        engine = get_transfer_engine(os.path.join(B, "app_data", "transfers"))
        if op == "queue": return dict(ok=True, queue=tm.get_queue())
        if op == "active": return dict(ok=True, active=engine.get_active_jobs())
        if op == "history": return dict(ok=True, history=engine.list_manifest_jobs(limit=int(q.get("limit", 50))))
        if op == "interrupted": return dict(ok=True, interrupted=engine.scan_interrupted_transfers())
        if op == "summary":
            active = engine.get_active_jobs()
            hist = engine.list_manifest_jobs(limit=100)
            completed_cnt = sum(1 for j in hist if j.get("status") in ("Completed", "completed"))
            failed_cnt = sum(1 for j in hist if j.get("status") in ("Failed", "failed"))
            interrupted_list = engine.scan_interrupted_transfers()
            total_active_bytes = sum(j.get("total_bytes", 0) for j in active)
            return dict(
                ok=True,
                active_count=len(active),
                queued_count=len(tm.get_queue()),
                completed_count=completed_cnt,
                failed_count=failed_cnt,
                interrupted_count=len(interrupted_list),
                total_active_bytes=total_active_bytes,
                active=active
            )
        if op == "policies": return dict(ok=True, policies=tm.get_policies())
        return dict(ok=False, error=f"unknown transfer op {op}")
    except Exception as e: return dict(ok=False, error=str(e))

def transfer_post(op, d):
    if op.startswith("jobs/"):                               # Phase 1d endpoints (uengine/transfer/api.py)
        try:
            from uengine.transfer import api as TAPI
            r = TAPI.handle_post(op, d, transfer_pool())
            return r if r is not None else dict(ok=False, error=dict(code="not_found", message=f"unknown transfer op {op}"))
        except Exception as e:
            return dict(ok=False, error=dict(code="internal", message=f"{type(e).__name__}: {e}"))
    try:
        from uengine.transfer_manager import TransferManager
        from uengine.unified_transfer_engine import get_transfer_engine
        tm = TransferManager(B, vault_root=SET.get("vault_mount"))
        engine = get_transfer_engine(os.path.join(B, "app_data", "transfers"))
        if op == "enqueue":
            return tm.enqueue_study(str(d.get("study_code", "")), action=str(d.get("action", "archive")))
        if op == "process_next":
            return tm.process_next()
        if op == "pause":
            ok = engine.pause_job(str(d.get("job_id", "")))
            return dict(ok=ok)
        if op == "cancel":
            ok = engine.cancel_job(str(d.get("job_id", "")))
            return dict(ok=ok)
        if op == "policies":
            return tm.update_policies(d.get("policies", {}))
        return dict(ok=False, error=f"unknown transfer post op {op}")
    except Exception as e: return dict(ok=False, error=str(e))

def clean_get(op, q):
    try:
        from uengine.cleaning_manager import CleaningManager
        cm = CleaningManager(B, vault_root=SET.get("vault_mount"))
        if op == "dashboard": return cm.get_dashboard()
        if op == "preview": return cm.preview_clean(q.get("categories", "").split(",") if q.get("categories") else None)
        if op == "quarantine": return dict(ok=True, items=cm.list_quarantine())
        if op == "history": return dict(ok=True, history=cm.get_history())
        if op == "policies": return dict(ok=True, policies=cm.get_policies())
        return dict(ok=False, error=f"unknown clean op {op}")
    except Exception as e: return dict(ok=False, error=str(e))

def clean_post(op, d):
    _g = _transfer_guard("clean", op, d)                   # Phase 1e.2
    if _g is not None:
        return _g
    try:
        from uengine.cleaning_manager import CleaningManager
        cm = CleaningManager(B, vault_root=SET.get("vault_mount"))
        if op == "execute":
            return cm.execute_clean(category_ids=d.get("categories"), use_quarantine=True)   # Phase 0: always via quarantine
        if op == "policies":
            return cm.update_policies(d.get("policies", {}))
        if op == "quarantine_restore":
            return cm.restore_quarantine(str(d.get("quarantine_id", "")))
        if op == "quarantine_purge":
            return cm.purge_quarantine(d.get("quarantine_id") or None, purge_all=d.get("purge_all") is True)
        if op == "delete_study":
            return cm.delete_by_study(str(d.get("study_code", "")), target=str(d.get("target", "staging")))
        return dict(ok=False, error=f"unknown clean post op {op}")
    except Exception as e: return dict(ok=False, error=str(e))

def legacy_get(op, q):
    try:
        from uengine.legacy_migration import LegacyMigrationEngine
        lme = LegacyMigrationEngine(B)
        search_dirs = [B, os.path.expanduser("~/cSS_pipeline"), os.path.expanduser("~/cSS_pipeline_v4.13"), os.path.expanduser("~/Percival_demo"), os.path.expanduser("~/css_project")]
        v = SET.get("vault_mount")
        if v and os.path.isdir(v): search_dirs.append(v)
        if os.path.isdir("/Volumes"):
            for ent in os.listdir("/Volumes"):
                vp = os.path.join("/Volumes", ent, "PERCIVAL_VAULT")
                if os.path.isdir(vp) and vp not in search_dirs: search_dirs.append(vp)
        if op == "discover": return lme.discover_legacy_data(search_roots=search_dirs)
        if op == "history": return dict(history=lme.get_migration_history())
        return dict(ok=False, error=f"unknown legacy op {op}")
    except Exception as e: return dict(ok=False, error=str(e))

def legacy_post(op, d):
    try:
        if op == "register":
            codes = d.get("codes", [])
            registered = []
            for code in codes:
                if not pget(code):
                    anatomy = "recon" if os.path.isdir(os.path.join(B, "subjects", code, "surf")) else "synthseg"
                    PAT.append(dict(
                        code=code,
                        cohort=d.get("cohort", "legacy_recovered"),
                        anatomy=anatomy,
                        mode="semi",
                        pathway=anatomy,
                        series={},
                        step="",
                        steps_done={},
                        added=time.time(),
                        status="done" if os.path.exists(f"{B}/review/{code}_candidates.csv") else "waiting",
                        note="Legacy study recovered and registered"
                    ))
                    registered.append(code)
            if registered:
                save_pat()
                IDG.ensure(PAT)
                write_grades_file()
            return dict(ok=True, registered_count=len(registered), registered=registered)
        return dict(ok=False, error=f"unknown legacy post op {op}")
    except Exception as e: return dict(ok=False, error=str(e))

def wizard_get(op, q):
    try:
        from uengine.wizard import SetupWizard
        wiz = SetupWizard(B)
        if op == "state": return wiz.get_state()
        if op == "step1": return wiz.step1_inspect_system()
        if op == "step3": return wiz.step3_detect_volumes()
        if op == "step4": return wiz.step4_scan_legacy_data()
        return dict(error=f"unknown wizard op {op}")
    except Exception as e: return dict(error=f"{type(e).__name__}: {e}")

def wizard_post(op, d):
    try:
        from uengine.wizard import SetupWizard
        wiz = SetupWizard(B)
        if op == "step2": return wiz.step2_configure_storage(local_workspace=d.get("local_workspace"), vault_mount=d.get("vault_mount"), backup_dir=d.get("backup_dir"))
        if op == "step5": return wiz.step5_generate_migration_plan(active_retention_days=int(d.get("retention_days", 30)), target_vault=d.get("target_vault"))
        if op == "finalize":
            r = wiz.step6_finalize(d.get("config", {}))
            if "settings" in r:
                with LOCK:
                    SET.update(r["settings"])
                    jsave("settings.json", SET)
            return r
        if op == "reset": return wiz.reset()
        return dict(ok=False, error=f"unknown wizard post op {op}")
    except Exception as e: return dict(ok=False, error=f"{type(e).__name__}: {e}")

def health_get():
    try:
        from uengine.health import StartupHealthCheck
        hc = StartupHealthCheck(B, SET)
        return hc.run_all(auto_repair=True)
    except Exception as e: return dict(error=f"{type(e).__name__}: {e}")

def recovery_get(op, q):
    try:
        from uengine.recovery import JobRecoveryManager
        from uengine.vault import TransferQueueManager
        jrm = JobRecoveryManager(B)
        tqm = TransferQueueManager(B)
        if op == "summary": return jrm.get_recovery_summary()
        if op == "resumable": return dict(resumable=jrm.get_resumable_jobs())
        if op == "transfers": return dict(transfers=tqm.list_transfers(q.get("status")))
        return dict(error=f"unknown recovery op {op}")
    except Exception as e: return dict(error=f"{type(e).__name__}: {e}")

def recovery_post(op, d):
    try:
        from uengine.recovery import JobRecoveryManager
        from uengine.vault import TransferQueueManager, PercivalDataVault
        jrm = JobRecoveryManager(B)
        tqm = TransferQueueManager(B)
        if op == "rollback":
            jrm.rollback_incomplete_stage(d.get("job_id", ""), d.get("stage", ""))
            return dict(ok=True)
        if op == "resume_transfers":
            v = PercivalDataVault(SET.get("vault_mount"))
            resumed = tqm.resume_transfers(v)
            return dict(ok=True, resumed_count=len(resumed), resumed=resumed)
        return dict(ok=False, error=f"unknown recovery post op {op}")
    except Exception as e: return dict(ok=False, error=f"{type(e).__name__}: {e}")

def migration_get(op, q):
    try:
        from uengine.legacy_migration import LegacyMigrationEngine
        lme = LegacyMigrationEngine(B)
        if op == "discover": return lme.discover_legacy_data()
        if op == "history": return dict(history=lme.get_migration_history())
        return dict(error=f"unknown migration op {op}")
    except Exception as e: return dict(error=f"{type(e).__name__}: {e}")

def migration_post(op, d):
    _g = _transfer_guard("migration", op, d)                   # Phase 1e.2
    if _g is not None:
        return _g
    try:
        from uengine.legacy_migration import LegacyMigrationEngine
        lme = LegacyMigrationEngine(B)
        if op == "plan": return lme.create_migration_plan(d.get("studies", []), default_strategy=d.get("default_strategy", "import_pensieve_only"), custom_strategies=d.get("custom_strategies"))
        if op == "execute": return lme.execute_migration(d.get("plan", {}), vault_dir=SET.get("vault_mount"), dry_run=bool(d.get("dry_run", False)))
        return dict(ok=False, error=f"unknown migration post op {op}")
    except Exception as e: return dict(ok=False, error=f"{type(e).__name__}: {e}")
# ------------------------------------------------------------------ v5.20 study administration - app/study_admin.py
def sa_ctx():
    def drop(c):
        with LOCK:
            PAT[:] = [p for p in PAT if p["code"] != c]; save_pat()
    return dict(ID=IDG.ID, B=B, AD=AD, pget=pget, save_pat=save_pat, file_keys=lambda: [p["code"] for p in PAT], reveal=lambda: IDG.reveal(SET),
                mode=lambda: IDG.mode(SET), drop_pat=drop, after_edit=lambda c: write_grades_file())
def known_match(e):
    import known_projects as KP
    try: return KP.match(e, B, SET, PM.studies_on_disk, SD._v1)
    except Exception: return {}
def reuse_processed(src, code, qs, item):
    """import: bring in the earlier processing of the same examination (verified copy; the other project is only read)"""
    r = PM.import_study(src, B, code)
    with LOCK:
        if not pget(code):
            PAT.append(dict(code=code, cohort=qs.get("cohort", ""), anatomy="recon" if r["freesurfer"] else "synthseg", mode=qs.get("mode", "semi"),
                            pathway="recon" if r["freesurfer"] else "synthseg", series=item.get("chosen", {}), fingerprint=item.get("fingerprint", ""), step="", steps_done={},
                            added=time.time(), status="done", linked=True, radiologist=item.get("radiologist", ""), grade_R=item.get("grade_R", ""), grade_L=item.get("grade_L", ""),
                            note="processed earlier in another project - results brought in (verified copy), not processed again"))
            save_pat()
    write_grades_file()
def kp_get(op, q):
    import known_projects as KP
    if op == "list": return dict(ok=True, projects=KP.candidates(B, SET, PM.studies_on_disk))
    return dict(error=f"unknown {op}")
def kp_post(op, d):
    import known_projects as KP
    path = os.path.expanduser(str(d.get("path", "")))
    if op == "toggle":
        off = set(SET.get("known_projects_off", [])); (off.discard if d.get("on") else off.add)(os.path.realpath(path)); SET["known_projects_off"] = sorted(off)
        jsave("settings.json", SET); return dict(ok=True)
    if op == "add":
        if not os.path.isdir(path) or os.path.realpath(path) == os.path.realpath(B): return dict(ok=False, error="choose another project folder")
        SET["known_projects_extra"] = sorted(set(SET.get("known_projects_extra", [])) | {path}); jsave("settings.json", SET); return dict(ok=True)
    if op == "bring_all":                                   # every processed study of that project that is not here yet
        here = set(PM.studies_on_disk(B)) | {p["code"] for p in PAT}
        codes = [c for c in PM.studies_on_disk(path) if os.path.exists(os.path.join(path, "review", f"{c}_candidates.csv")) and c not in here]
        return proc_post("link", dict(source=path, codes=codes))
    return dict(ok=False, error=f"unknown {op}")
def describe_study(u):
    """the existing examination an import collides with (for the duplicate choice)"""
    s = IDG.ID().R["studies"].get(u) or {}; fk = s.get("file_key", ""); p = pget(fk) or {}
    return dict(label=study_label(fk), status=p.get("status", ""), archived=bool(p.get("archived")), processed=os.path.exists(f"{B}/review/{fk}_candidates.csv"),
                has_calls=bool(glob.glob(f"{B}/review/{fk}_calls*.csv")), cohort=p.get("cohort", ""))
def resolve_duplicate(choice, fk):
    """import duplicate resolution: replace = purge the old study; keep_ml = remove it but keep its results for ML (it gets a RET identifier)"""
    import study_admin as SA
    r = SA.remove(sa_ctx(), [fk], "purge" if choice == "replace" else "remove", by="import (duplicate resolved)")
    if r["refused"]: raise ValueError(f"the existing study could not be {'purged' if choice == 'replace' else 'removed'}: {r['refused'][0]['why']}")
def sa_post(op, d):
    import study_admin as SA
    by = str(d.get("by") or "").strip() or "app user"
    try:
        codes = [c for c in (d.get("codes") or ([d["code"]] if d.get("code") else [])) if pget(c)]
        if op == "edit":
            if d.get("confirm") is not True: return dict(ok=False, needs_confirm=True, error="confirm the change")
            r = SA.edit(sa_ctx(), str(d.get("code", "")), d.get("fields") or {}, by=by, reason=str(d.get("reason", ""))[:300])
            if r.get("ok") and r.get("changes"): notify_c("done", "edits", f"Identifiers edited · {d.get('code')}", ", ".join(r["changes"]), study=d.get("code"))
            return r
        if op == "bulk":                                   # several studies: cohort / display name only (identifiers one at a time)
            if d.get("confirm") is not True: return dict(ok=False, needs_confirm=True, error="confirm the change")
            f = {k: v for k, v in (d.get("fields") or {}).items() if k in ("cohort", "display_name")}
            res = [SA.edit(sa_ctx(), c, f, by=by, reason="bulk edit") for c in codes]
            bad = [(c, r["error"]) for c, r in zip(codes, res) if not r.get("ok")]
            return dict(ok=not bad, n=len(codes) - len(bad), errors=[f"{study_label(c)}: {e}" for c, e in bad])
        if op == "archive": return SA.archive(sa_ctx(), codes, bool(d.get("on", True)), by=by)
        if op == "archive_cohort":
            cs = [p["code"] for p in PAT if p.get("cohort") == d.get("cohort") and not p.get("retired")]
            return SA.archive(sa_ctx(), cs, bool(d.get("on", True)), by=by)
        if op == "plan_remove":
            pl = SA.plan_removal(sa_ctx(), codes, d.get("mode", "remove"))
            return dict(ok=True, mode=d.get("mode"), studies=[dict(code=x["code"], label=study_label(x["code"]), refused=x.get("refused", ""), n_trash=x.get("n_trash", 0), n_keep=x.get("n_keep", 0),
                        bytes_trash=x.get("bytes_trash", 0), bytes_keep=x.get("bytes_keep", 0), library=bool(x.get("library")), library_locked=x.get("library_locked", False),
                        has_calls=x.get("has_calls", False)) for x in pl], vault_needed=d.get("mode") == "remove" and not IDG.ID().unlocked())
        if op == "remove":
            mode_ = d.get("mode", "remove"); phrase = "PURGE" if mode_ == "purge" else "REMOVE"
            if str(d.get("confirm_phrase", "")).strip() != phrase: return dict(ok=False, needs_confirm=True, error=f"type {phrase} to confirm")
            labels = {c: study_label(c) for c in codes}
            r = SA.remove(sa_ctx(), codes, mode_, by=by, delete_library=bool(d.get("delete_library", True)))
            if r["done"]: notify_c("done", "edits", f"{len(r['done'])} studies {'purged' if mode_ == 'purge' else 'removed (results kept for ML)'}", f"moved to {r['trash'] or 'the Trash'}")
            for x in r["done"]: x["label"] = labels.get(x["code"], x["code"])
            return r
        return dict(ok=False, error=f"unknown {op}")
    except Exception as e: return dict(ok=False, error=IDG.redact_text(f"{type(e).__name__}: {e}", SET, B)[-400:])
# ------------------------------------------------------------------ v5.18 export of studies with their files - app/study_export.py
def xs_args(d):
    import study_export as XS
    codes = [c for c in d.get("codes", []) if any(p["code"] == c for p in PAT)]
    parts = dict(XS.DEFAULT); parts.update({k: bool(v) for k, v in (d.get("parts") or {}).items() if k in XS.PARTS}); parts["results"] = True
    return XS, codes, parts, IDG.mode(SET)
def xs_post(op, d):
    try:
        XS, codes, parts, mode = xs_args(d)
        dest = os.path.realpath(os.path.expanduser(str(d.get("dest", "") or SET.get("export_files_dir", "") or SET.get("export_dir", ""))))
        okd, why = verify_local_dest(dest) if d.get("dest") or SET.get("export_files_dir") or SET.get("export_dir") else (False, "choose where to save the export")
        if mode == "standard":
            miss = [c for c in codes if IDG.requires_accession(c, SET)]
            if miss: return dict(ok=False, error=f"Standard mode: {len(miss)} studies need their accession number first (Studies › Edit identifiers) - or export in Incognito")
        P = XS.plan(B, AD, codes, parts, mode, lambda c: IDG.ident(c, SET), IDG.library_of)
        view = dict(n_studies=len(codes), n_files=P["n_files"], bytes=P["bytes"], problems=P["problems"], dest=dest if okd else "", dest_ok=bool(okd), dest_why="" if okd else why,
                    mode=mode, parts=parts, free=shutil.disk_usage(dest).free if okd else 0, warning=EXPORT_WARNING,
                    studies=[dict(study_id=x["study_id"], folder=x["rel"], files=x["n"], bytes=x["bytes"], why=x["why"]) for x in P["studies"]])
        if op == "plan": return dict(ok=True, **view)
        if op == "start":
            if d.get("confirm_clinical") is not True: return dict(ok=False, needs_confirm=True, warning=EXPORT_WARNING, error="confirm the clinical-data warning")
            if not okd: return dict(ok=False, error=f"export folder refused: {why}")
            r = XS.start(B, AD, dest, codes, parts, mode, lambda c: IDG.ident(c, SET), IDG.library_of,
                         results_frame=lambda cs: export_frame([x for x in results() if x["code"] in cs]), redact=lambda t: IDG.redact_text(t, SET, B), version=version())
            if r.get("ok"):
                SET["export_files_dir"] = dest; jsave("settings.json", SET)
                notify_c("done", "exports", f"Export of {len(codes)} studies started", "files are copied and verified in the background")
            return dict(ok=r["ok"], job=r.get("job", ""), folder=r.get("folder", ""), error=r.get("error", ""))
        return dict(ok=False, error=f"unknown {op}")
    except Exception as e: return dict(ok=False, error=IDG.redact_text(f"{type(e).__name__}: {e}", SET, B)[-400:])
def xs_get(op, q):
    import study_export as XS
    if op == "job": return XS.job(q.get("id", "")) or dict(error="unknown export job")
    return dict(error=f"unknown {op}")
# ------------------------------------------------------------------ candidate lineage between runs (v5.17)
def lineage_get(op, q):
    try:
        import review_calls_gui as RCG
        L = RCG._ledger(B); code = q.get("code", "")
        if op == "study":
            p = os.path.join(B, "review", f"{code}_lineage.json"); lin = json.load(open(p)) if os.path.exists(p) else None
            st = PM.Study(B, code); runs = [dict(run_id=m["run_id"], status=m.get("status"), note=m.get("note", ""), created=m.get("created"), parent=m.get("parent"),
                                                 models=m.get("models"), lineage=m.get("lineage"), software=m.get("software")) for m in st.history()]
            pend = L.pending_confirmations(B, code)
            return dict(code=code, lineage=lin, runs=runs, active=(st.active_manifest() or {}).get("run_id"), pending=[{k: e.get(k) for k in
                        ("row_uid", "reviewer", "call", "time", "comment", "suggested_new_cand_id", "lineage_why")} for e in pend], state=L.review_state(B, code))
        return dict(error=f"unknown {op}")
    except Exception as e: return dict(error=f"{type(e).__name__}: {e}"[-300:])
def lineage_post(op, d):
    try:
        import review_calls_gui as RCG
        L = RCG._ledger(B)
        if op == "decide": return L.decide_carry(B, str(d.get("code", "")), str(d.get("row_uid", "")), str(d.get("reviewer", "")), str(d.get("time", "")),
                                                 str(d.get("decision", "")), str(d.get("by", "")))
        return dict(ok=False, error=f"unknown {op}")
    except Exception as e: return dict(ok=False, error=f"{type(e).__name__}: {e}"[-300:])
# ------------------------------------------------------------------ Training screen (v5.17) - app/training_gui.py
def train_get(op, q):
    try:
        import training_gui as TG, shadow_engine_gui as SEG, unified_gui as UG, review_calls_gui as RCG
        if op == "overview": return TG.overview(B, AD, PAT, SET, version, SEG.models, lambda: unified_get("state", {}), UG.validation, lambda: RCG.policy(B, PAT))
        if op == "job": return dict(TG.JOB)
        return dict(error=f"unknown {op}")
    except Exception as e: return dict(error=f"Training screen unavailable: {type(e).__name__}: {e}"[-300:])
def train_post(op, d):
    try:
        import training_gui as TG
        if op == "evaluate": return TG.run_evaluation(AD, n=int(d.get("n", 12)))
        return dict(ok=False, error=f"unknown {op}")
    except Exception as e: return dict(ok=False, error=f"{type(e).__name__}: {e}"[-300:])
# ------------------------------------------------------------------ PERCIVAL Setup Center & Configuration (v5.26)
def _image_model_ok():
    import image_ml_gui as IMG
    return any(m.get("status") == "ok" for m in IMG.models(force=True).get("models", []))

def setup_get(op, q):
    try:
        from uengine.setup import (
            SetupStateManager, InstallationDiscoveryService,
            SystemReadinessService, DiagnosticExportService,
            validate_python, validate_pipeline, validate_freesurfer,
            validate_license, validate_mri_tool, validate_workspace,
            validate_vault, validate_pensieve, CURRENT_APP_VERSION
        )
        sm = SetupStateManager(B)
        disc = InstallationDiscoveryService(B)

        if op == "lifecycle":
            lm = sm.detect_launch_mode(CURRENT_APP_VERSION)
            st = sm.get_state()
            return dict(
                state=st.get("state"),
                mode=st.get("mode"),
                is_first_launch=st.get("is_first_launch"),
                completed=st.get("completed"),
                current_step=st.get("current_step", 1),
                last_completed_step=st.get("last_completed_step", 0),
                allow_dashboard=lm.get("allow_dashboard", False),
                launch_type=lm.get("launch_type"),
                notice=lm.get("notice"),
                app_version=CURRENT_APP_VERSION,
                validated_config=st.get("validated_config", {})
            )

        if op == "discovery":
            cached = sm.get_state().get("discovery_cache")
            force = q.get("force") == "1"
            if not cached or force:
                cached = disc.run_full_discovery()
                sm.cache_discovery(cached)
            return dict(ok=True, discovery=cached)

        if op == "readiness":
            st = sm.get_state()
            disc_data = st.get("discovery_cache") or disc.run_full_discovery()
            cfg = _setup_fill_checks(dict(SET, **st.get("validated_config", {})))   # checks the user did not click through are run now, not reported as missing
            readiness = SystemReadinessService.evaluate_capabilities(cfg, disc_data)
            return dict(ok=True, readiness=readiness, dependencies=SystemReadinessService.get_dependency_map())

        if op == "diagnostics":
            rep = DiagnosticExportService.generate_report(sm, disc, SystemReadinessService)
            md = DiagnosticExportService.format_markdown(rep)
            return dict(ok=True, report=rep, markdown=md)

        if op == "first_run":
            lm = sm.detect_launch_mode(CURRENT_APP_VERSION)
            return dict(first_run=not lm.get("allow_dashboard", False), lifecycle=lm)

        if op == "state":
            import setup_gui as SG
            items = SG.checks(B, AD, SET, fs_env, find_license, which, os.path.join(os.path.dirname(HERE), "unified_engine"), _image_model_ok)
            vols = SG.detected_volumes()
            def_vault = SET.get("vault_mount") or (vols[0]["vault_path"] if vols else "")
            lm = sm.detect_launch_mode(CURRENT_APP_VERSION)
            return dict(
                first_run=not lm.get("allow_dashboard", False),
                lifecycle=lm,
                items=items,
                report=SG.report(items, AD),
                settings=dict(
                    freesurfer_home=SET.get("freesurfer_home", ""),
                    fs_license=SET.get("fs_license", ""),
                    workspace_dir=B,
                    vault_mount=def_vault,
                    candidate_redetection=SET.get("candidate_redetection", True),
                    candidate_calling=SET.get("candidate_calling", True)
                ),
                detected_volumes=vols
            )

        return dict(error=f"unknown {op}")
    except Exception as e:
        return dict(error=f"setup unavailable: {type(e).__name__}: {e}"[-300:])

def setup_post(op, d):
    try:
        from uengine.setup import (
            SetupStateManager, InstallationDiscoveryService,
            SystemReadinessService, DiagnosticExportService,
            validate_python, validate_pipeline, validate_freesurfer,
            validate_license, validate_mri_tool, validate_workspace,
            validate_vault, validate_pensieve, CURRENT_APP_VERSION
        )
        sm = SetupStateManager(B)
        disc = InstallationDiscoveryService(B)

        if op == "step":
            step = int(d.get("step", 1))
            partial = d.get("partial_config", {})
            sm.set_step(step, partial)
            return dict(ok=True, current_step=step, state=sm.get_state())

        if op == "validate_component":
            comp = d.get("component")
            p = d.get("path", "")
            if comp == "python": return validate_python(p)
            if comp == "pipeline": return validate_pipeline(p)
            if comp == "freesurfer": return validate_freesurfer(p)
            if comp == "license": return validate_license(p)
            if comp == "mri_tool": return validate_mri_tool(d.get("tool_name", "dcm2niix"), p)
            if comp == "workspace": return validate_workspace(p)
            if comp == "vault": return validate_vault(p)
            if comp == "pensieve": return validate_pensieve(p)
            return dict(ok=False, error=f"Unknown component: {comp}")

        if op == "validate_fs":
            return validate_freesurfer(d.get("path"))

        if op == "validate_license":
            return validate_license(d.get("path"))

        if op == "test":
            import setup_gui as SG
            return SG.test_fs(d.get("home") or SET.get("freesurfer_home", ""), d.get("license") or find_license(SET.get("freesurfer_home", ""), fs_env()))

        if op in ("save", "save_config"):
            d = dict(d)                                    # the setup wizard sends freesurfer_home / fs_license; Settings sends home / license (both accepted)
            if not d.get("home") and d.get("freesurfer_home"): d["home"] = d["freesurfer_home"]
            if not d.get("license") and d.get("fs_license"): d["license"] = d["fs_license"]
            v_fs = validate_freesurfer(d.get("home")) if d.get("home") else dict(ok=True)
            v_lic = validate_license(d.get("license")) if d.get("license") else dict(ok=True)
            if not v_fs.get("ok"): return dict(ok=False, error=v_fs.get("error"))
            if not v_lic.get("ok"): return dict(ok=False, error=v_lic.get("error"))

            cfg_updates = {}
            with LOCK:
                if d.get("home"):
                    SET["freesurfer_home"] = v_fs.get("home", d.get("home"))
                    cfg_updates["freesurfer_home"] = SET["freesurfer_home"]
                    cfg_updates["freesurfer_valid"] = True
                    cfg_updates["freesurfer_version"] = v_fs.get("version", "v7+")

                if d.get("license"):
                    SET["fs_license"] = v_lic.get("path", d.get("license"))
                    cfg_updates["fs_license"] = SET["fs_license"]
                    cfg_updates["license_valid"] = True

                if d.get("python_executable"):
                    v_py = validate_python(d["python_executable"])
                    if v_py.get("ok"):
                        SET["python_executable"] = d["python_executable"]
                        cfg_updates["python_executable"] = d["python_executable"]
                        cfg_updates["python_valid"] = True
                        cfg_updates["python_version"] = v_py.get("version", "")

                if d.get("pipeline_dir"):
                    v_pipe = validate_pipeline(d["pipeline_dir"])
                    if v_pipe.get("ok"):
                        SET["pipeline_dir"] = d["pipeline_dir"]
                        cfg_updates["pipeline_dir"] = d["pipeline_dir"]
                        cfg_updates["pipeline_valid"] = True
                        cfg_updates["pipeline_version"] = v_pipe.get("version", "")

                if "workspace_dir" in d and d["workspace_dir"].strip():
                    wdir = os.path.abspath(os.path.expanduser(d["workspace_dir"].strip()))
                    cfg_dir = os.path.expanduser("~/Library/Application Support/Percival Dev")
                    os.makedirs(cfg_dir, exist_ok=True)
                    try:
                        with open(os.path.join(cfg_dir, "project_path"), "w") as pf: pf.write(wdir)
                    except Exception: pass
                    SET["workspace_dir"] = wdir
                    cfg_updates["workspace_dir"] = wdir
                    cfg_updates["workspace_valid"] = True

                if "vault_mount" in d and d["vault_mount"].strip():
                    import setup_gui as SG
                    ev = SG.ensure_vault(d["vault_mount"])      # a chosen drive means <drive>/PERCIVAL_VAULT, created automatically when the drive is connected
                    vdir = ev["path"]; cfg_updates["vault_created"] = ev["created"]; cfg_updates["vault_error"] = ev["error"]
                    SET["vault_mount"] = vdir
                    cfg_updates["vault_mount"] = vdir
                    v_res = validate_vault(vdir)
                    cfg_updates["vault_valid"] = v_res.get("ok", False)
                    cfg_updates["vault_connected"] = v_res.get("connected", False)
                    try:
                        vcp = os.path.expanduser("~/.percival_vault_config.json")      # merge: uengine.vault reads active_vault_path / volume_uuid from this file
                        vc = json.load(open(vcp)) if os.path.exists(vcp) else {}
                        vc.update(vault_path=vdir, active_vault_path=vdir, updated_at=datetime.datetime.now().isoformat())
                        with open(vcp, "w") as vf: json.dump(vc, vf, indent=2)
                    except Exception: pass

                if "candidate_redetection" in d:
                    SET["candidate_redetection"] = bool(d["candidate_redetection"])
                    cfg_updates["candidate_redetection"] = SET["candidate_redetection"]
                if "candidate_calling" in d:
                    SET["candidate_calling"] = bool(d["candidate_calling"])
                    cfg_updates["candidate_calling"] = SET["candidate_calling"]

                SET["rerun_mode"] = "auto"
                jsave("settings.json", SET)
                sm.update_validated_config(cfg_updates)

            return dict(ok=True, saved=cfg_updates)

        if op == "revert":
            ok, msg = sm.revert_to_previous_config()
            return dict(ok=ok, message=msg, state=sm.get_state())

        if op == "rescan":
            cached = disc.run_full_discovery()
            sm.cache_discovery(cached)
            return dict(ok=True, discovery=cached)

        if op == "reset":
            sm.reset_to_first_launch()
            return dict(ok=True, message="Reset to first launch.")

        if op == "finish":
            return _setup_finish(sm, disc)

        if op == "finish_start":                   # same work in the background; the wizard shows the progress window (GET /api/job?id=)
            import progress_jobs as PJ
            run = [j for j in PJ.running("setup_finish")]
            if run: return dict(ok=True, job=run[0]["id"])
            return dict(ok=True, job=PJ.start("setup_finish", SETUP_FINISH_STEPS, lambda rep: _setup_finish(sm, disc, rep), title="Finishing setup"))

        if op == "restart":
            return _restart_app()

        return dict(ok=False, error=f"unknown {op}")
    except Exception as e:
        return dict(ok=False, error=f"{type(e).__name__}: {e}"[-300:])
def _setup_fill_checks(cfg, rep=None, k0=0):
    """Setup readiness (Step 6) and Finish: every check the user did not explicitly click through in the wizard is run here, live, instead of
    counting as failed - a missing flag used to show "BLOCKED" for DICOM import / ALBUS / pipeline although dcm2niix was installed.
    rep(k, label) (optional) reports each check as one progress step (6 steps, numbered from k0+1)."""
    from uengine.setup import validate_workspace, validate_pipeline, validate_mri_tool, validate_freesurfer, validate_license, validate_vault
    r = rep or (lambda *a, **k: None)
    r(k0 + 1, "Checking the project folder (write access, free space)")
    if "workspace_valid" not in cfg or not cfg.get("workspace_free_gb"):
        v = validate_workspace(B); cfg.setdefault("workspace_valid", v.get("ok", False)); cfg["workspace_free_gb"] = v.get("free_gb", 0.0)
    cfg.setdefault("python_valid", True)                                   # this process is the Python environment
    r(k0 + 2, "Checking the PERCIVAL pipeline scripts")
    if "pipeline_valid" not in cfg: cfg["pipeline_valid"] = validate_pipeline(B).get("ok", False)
    r(k0 + 3, "Checking the DICOM converter (dcm2niix)")
    if not cfg.get("dcm2niix_valid"): cfg["dcm2niix_valid"] = validate_mri_tool("dcm2niix", cfg.get("dcm2niix_path", "")).get("ok", False)
    r(k0 + 4, "Checking FreeSurfer")
    if not cfg.get("freesurfer_valid"): cfg["freesurfer_valid"] = validate_freesurfer(cfg.get("freesurfer_home") or SET.get("freesurfer_home", "")).get("ok", False)
    r(k0 + 5, "Checking the FreeSurfer licence")
    if not cfg.get("license_valid"):
        cfg["license_valid"] = validate_license(cfg.get("fs_license") or SET.get("fs_license", "") or find_license(SET.get("freesurfer_home", ""), fs_env())).get("ok", False)
    r(k0 + 6, "Checking the external Data Vault")
    if not cfg.get("vault_valid") and (cfg.get("vault_mount") or SET.get("vault_mount")):
        v = validate_vault(cfg.get("vault_mount") or SET.get("vault_mount")); cfg["vault_valid"] = v.get("ok", False); cfg["vault_connected"] = v.get("connected", False)
    return cfg


SETUP_FINISH_STEPS = 13


def _setup_finish(sm, disc, rep=None):
    """the setup wizard's Finish, as numbered steps (rep(k, label)); returns the same dict the synchronous route always returned plus
    restart_required (a different project folder was chosen: the running app is bound to its folder at start-up)"""
    from uengine.setup import SystemReadinessService, validate_vault
    import setup_gui as SG
    r = rep or (lambda *a, **k: None)
    r(0, "Reading the installation scan")
    disc_data = sm.get_state().get("discovery_cache") or disc.run_full_discovery()
    r(1, "Installation scan ready")
    cfg = _setup_fill_checks(dict(SET, **sm.get_state().get("validated_config", {})), r, 1)           # steps 2-7
    r(8, "Creating / opening the Data Vault on the external drive")
    if SET.get("vault_mount"):                     # setup finished: make sure the chosen vault exists (created when its drive is connected)
        ev = SG.ensure_vault(SET["vault_mount"])
        if ev["path"] != SET["vault_mount"]: SET["vault_mount"] = ev["path"]; jsave("settings.json", SET)
        cfg["vault_mount"] = SET["vault_mount"]; cfg.pop("vault_valid", None)
    if "vault_valid" not in cfg:
        v_v = validate_vault(SET.get("vault_mount", "/Volumes/Percival/PERCIVAL_VAULT"))
        cfg["vault_valid"] = v_v.get("ok", False)
        cfg["vault_connected"] = v_v.get("connected", False)
    r(9, "Saving the configuration")
    sm.update_validated_config(cfg)
    r(10, "Evaluating readiness")
    readiness = SystemReadinessService.evaluate_capabilities(cfg, disc_data)
    sm.mark_completed(readiness)
    r(11, "Running the final system checks")
    items = SG.checks(B, AD, SET, fs_env, find_license, which, os.path.join(os.path.dirname(HERE), "unified_engine"), _image_model_ok)
    r(12, "Writing the setup report")
    SG.report(items, AD, done=True)
    wd = SET.get("workspace_dir") or ""
    restart = bool(wd) and os.path.realpath(os.path.expanduser(wd)) != os.path.realpath(B)
    return dict(ok=True, readiness=readiness, state=sm.get_state(), restart_required=restart, project=B, new_project=wd if restart else "",
                summary="Setup complete - Percival is ready" if not restart else "Setup complete - Percival restarts in the new project folder")


def _restart_app():
    """quit this server and open the app again (a new project folder is only picked up at start-up). The launcher is started a moment after
    this process has exited, so its "already running" check does not see us. Needs the app bundle (PERCIVAL_APP_BUNDLE, set by the launcher)."""
    bundle = os.environ.get("PERCIVAL_APP_BUNDLE", "")
    if not bundle or not os.path.isdir(bundle): return dict(ok=False, error="automatic restart is only available in the installed app - quit and open Percival again")
    subprocess.Popen(["/bin/sh", "-c", f'sleep 3; /usr/bin/open -n "{bundle}"'], start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    threading.Thread(target=lambda: (time.sleep(0.8), _perform_safe_shutdown(True)), daemon=True).start()
    return dict(ok=True, restarting=True)


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
                save_pat(); notify("Percival", f"{os_label(p['code'])}: registration retried with {PATHWAYS[nxt]}"); return
        pm_end_full(p, False, msg)                       # previous outputs put back; this attempt stays in the history as failed
        p.update(status="failed", error=msg, finished=time.time()); save_pat()
        if any(k in msg for k in SETUP_ERR): CUR["hold"] = msg
    notify("Percival", f"{os_label(p['code'])} failed: {msg[:60]}")
    try: NC.add(B, "action", "processing", f"Patient {p['code']} failed", msg[:300])
    except Exception: pass
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
    wait = [p for p in PAT if p["status"] == "waiting" and not p.get("archived")]       # v5.20: archived studies wait until restored
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
    rows = []
    for p in PAT:
        c = p["code"]; r = dict(code=c, name=pname(c), ident=IDG.ident(c, SET), archived=bool(p.get("archived")), retired=bool(p.get("retired")), archived_at=(p.get("archived") or {}).get("at", ""), retired_at=(p.get("retired") or {}).get("at", ""), cohort=p.get("cohort", ""), mode=p.get("mode", ""), status=p["status"], version=p.get("version", ""),
                                radiologist=p.get("radiologist", ""), rad_R=p.get("grade_R", ""), rad_L=p.get("grade_L", ""))
        f = f"{B}/review/{c}_candidates.csv"
        if os.path.exists(f): r["candidates"] = int(len(pd.read_csv(f)))
        f = f"{B}/review/{c}_calls.csv"
        if os.path.exists(f):
            k = pd.read_csv(f); r["reviewed"] = int(k.call.notna().sum()) if "call" in k else 0; r["css_called"] = int((k.get("call") == "cSS").sum()) if "call" in k else 0
        if r.get("candidates") is not None:                 # v5.15: review state from EVERY reviewer's calls (call_ledger), not one score file
            import review_calls_gui as RCG
            rs = RCG.state(B, c, p.get("cohort", "")); r["review_state"] = rs.get("state"); r["review_label"] = rs.get("label")
            r["review_reason"] = rs.get("reason", ""); r["reviewers"] = rs.get("reviewers", []); r["calls_rule"] = rs.get("rule_text", "")
            if rs.get("n_called") is not None: r["reviewed"] = rs["n_called"]
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
        r["label"] = ("reviewed" if r.get("review_state", "reviewed" if r.get("score_total") is not None else "") == "reviewed" else
                      ("AI only, not validated" if r.get("ai_total") is not None else (r.get("review_label") or "").lower()))
        bs = BG.state(B, c); r["blind_review"] = bs["status"]                     # Phase 3A.2: AI fields withheld until the blind review
        if bs["pending"]: BG.mask_result(r, bs)
        rows.append(r)
    return rows
def _xlsx_sheets(writer, df, cohort=""):
    """results + v5.15 per-candidate reviewer calls (one call / date-time column per reviewer; nothing removed) + the call policy"""
    import pandas as pd, review_calls_gui as RCG
    df.to_excel(writer, index=False, sheet_name="results")
    try:
        RCG.calls_sheet(B, PAT, cohort).to_excel(writer, index=False, sheet_name="candidate_calls")
        pol = RCG.policy(B, PAT)["policy"]
        rows = [dict(Scope="all studies", Target="", Rule=json.dumps(pol["default"]))] + [dict(Scope="cohort", Target=k, Rule=json.dumps(v)) for k, v in pol["cohorts"].items()] \
            + [dict(Scope="study", Target=k, Rule=json.dumps(v)) for k, v in pol["studies"].items()]
        pd.DataFrame(rows).to_excel(writer, index=False, sheet_name="call_policy")
    except Exception as e: pd.DataFrame([dict(error=f"{type(e).__name__}: {e}")]).to_excel(writer, index=False, sheet_name="candidate_calls")
def export_frame(rows):
    """v5.16: exports carry the study identifier of the ACTIVE mode (accession in Standard, de-identified code in Incognito) and the
    de-identified code; never MRN, patient name or the identity record"""
    import pandas as pd
    df = pd.DataFrame(rows)
    if "ident" in df.columns:
        df.insert(1, "study_id", [i.get("study_id", "") for i in df["ident"]]); df.insert(2, "deid_code", [i.get("deid_code", "") for i in df["ident"]])
        df.insert(3, "study_id_kind", [i.get("id_kind", "") for i in df["ident"]]); df.insert(4, "display_name", [i.get("display_name", "") for i in df["ident"]])
    return df.drop(columns=["name", "ident", "qc_tip", "ai_err", "reviewers"], errors="ignore")
def export_xlsx():
    import pandas as pd
    df = export_frame(results())
    bio = io.BytesIO()
    with pd.ExcelWriter(bio) as w: _xlsx_sheets(w, df)
    return bio.getvalue()
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
    miss = [r["code"] for r in rows if IDG.requires_accession(r["code"], SET)]
    if miss: raise ExportRefused(f"export refused in Standard mode: {len(miss)} studies have no accession number yet ({', '.join(IDG.ident(c, SET).get('deid_code', c) for c in miss[:5])}"
                                 f"{' ...' if len(miss) > 5 else ''}) - enter them (Studies › Edit identifiers) or export in Incognito mode")
    df = export_frame(rows)
    out = os.path.join(export_dest(), f"cSS_results_{(cohort or 'all').replace('/', '_')}_{datetime.datetime.now():%Y%m%d_%H%M}.{fmt}")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if fmt == "xlsx":
        with pd.ExcelWriter(out) as w: _xlsx_sheets(w, df, cohort)
    elif fmt == "csv": df.to_csv(out, index=False)
    elif fmt == "docx": write_docx(out, df, cohort)
    elif fmt == "pdf": write_pdf(out, df, cohort)
    else: raise ValueError(f"unknown format {fmt}")
    return out
COLS_SHORT = [("study_id", "Study"), ("deid_code", "Code"), ("cohort", "Cohort"), ("status", "Status"), ("qc_grade", "QC"), ("candidates", "Candidates"), ("score_L", "Reader L"),
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
WIN = dict(webview=False, port=8800, window=None)
def free_port(start):
    for p in range(start, start + 50):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0: return p
def launch_child(kind, args, port0):
    old = CHILD.get(kind)
    if old and old.poll() is None: old.terminate()
    port = free_port(port0); env = fs_env()
    if kind == "review": cmd = [sys.executable, f"{SC}/review_web.py", ",".join(args["codes"]), "--no-browser", "--port", str(port)]   # Phase 3A.2: no --open (the reviewer's server decides the blind phase)
    else: cmd = [sys.executable, f"{B}/reference_audit/blind_read/blind_read.py", args["packet"], args["reader"], "--port", str(port), "--no-browser"]
    if kind == "review" and args.get("reviewer"): cmd += ["--reviewer", args["reviewer"]]
    if kind == "review": cmd += ["--groups", f"{AD}/review_groups.json", "--start", args.get("start", args["codes"][0])]
    if kind == "review": env["CSS_STUDY_LABELS"] = json.dumps({c: study_label(c) for c in args["codes"]})      # in memory only
    CHILD[kind] = subprocess.Popen(cmd, stdout=open(f"{AD}/logs/{kind}.log", "w"), stderr=subprocess.STDOUT, env=env)
    for _ in range(100):
        time.sleep(0.2)
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0: return dict(ok=True, url=f"http://127.0.0.1:{port}/")
        if CHILD[kind].poll() is not None: return dict(ok=False, error=open(f"{AD}/logs/{kind}.log").read()[-600:])
    return dict(ok=False, error="did not start in 20 s")

# ------------------------------------------------------------------ HTTP
def state():
    out = []
    for p in PAT:
        el, rem = eta(p)
        out.append(dict(code=p["code"], name=pname(p["code"]), ident=IDG.ident(p["code"], SET), archived=bool(p.get("archived")), retired=bool(p.get("retired")), archived_at=(p.get("archived") or {}).get("at", ""), retired_at=(p.get("retired") or {}).get("at", ""), cohort=p.get("cohort", ""), mode=p.get("mode"), anatomy=p.get("anatomy"),
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
                settings=SET, version=version(), project=dict(name=os.path.basename(os.path.normpath(B)), path=B), cohorts=sorted(set(jload("cohorts.json", [])) | {p.get("cohort", "") for p in PAT} - {""}), steps=STEPS)

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, obj, code=200, ctype="application/json", fname=None):
        b = obj if isinstance(obj, bytes) else json.dumps(obj, default=str).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b))); self.send_header("Cache-Control", "no-store")
        if fname: self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
        self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if q.get("code") and not _safe_path_segment(q["code"]):   # Phase 0: ?code= is joined into file paths (logs, QC images)
            return self.send(dict(error="invalid study code"), 400)
        try:
            if u.path == "/": return self.send(open(f"{HERE}/css_app.html", "rb").read(), ctype="text/html; charset=utf-8")
            if u.path == "/api/state": return self.send(state())
            if u.path == "/api/job":                                     # background job progress (setup Finish, study import)
                import progress_jobs as PJ; q_ = {k: v[0] for k, v in parse_qs(u.query).items()}
                return self.send(PJ.get(q_["id"]) if q_.get("id") else dict(running=PJ.running()))
            if u.path == "/api/vset":
                f = f"{B}/review/viewer_settings.json"; return self.send(json.load(open(f)) if os.path.exists(f) else {})
            if u.path in ("/icon_dark.png", "/icon_light.png"): return self.send(open(f"{HERE}{u.path}", "rb").read(), ctype="image/png")
            if re.fullmatch(r"/[A-Za-z0-9_]+\.js", u.path) and os.path.isfile(f"{HERE}{u.path}"): return self.send(open(f"{HERE}{u.path}", "rb").read(), ctype="text/javascript; charset=utf-8")
            if u.path == "/unified_view.js": return self.send(open(f"{HERE}/unified_view.js", "rb").read(), ctype="text/javascript; charset=utf-8")
            if u.path == "/shadow_view.js": return self.send(open(f"{HERE}/shadow_view.js", "rb").read(), ctype="text/javascript; charset=utf-8")
            if u.path in ("/identity_view.js", "/import_wizard_view.js", "/lineage_view.js", "/training_view.js", "/setup_view.js", "/export_view.js", "/study_admin_view.js", "/percival_view.js"): return self.send(open(f"{HERE}{u.path}", "rb").read(), ctype="text/javascript; charset=utf-8")
            if u.path == "/qc_view.js": return self.send(open(f"{HERE}/qc_view.js", "rb").read(), ctype="text/javascript; charset=utf-8")
            if u.path == "/calls_view.js": return self.send(open(f"{HERE}/calls_view.js", "rb").read(), ctype="text/javascript; charset=utf-8")
            if u.path == "/image_ml_view.js": return self.send(open(f"{HERE}/image_ml_view.js", "rb").read(), ctype="text/javascript; charset=utf-8")
            if u.path == "/api/preflight": return self.send(preflight())
            if u.path == "/api/log":
                f = f"{AD}/logs/{q['code']}.log"; t = open(f).read()[-30000:] if os.path.exists(f) else "(no log yet)"
                p = pget(q["code"]); rl = f"{B}/logs/{q['code']}_run.log"
                if p and p["status"] in ("running", "paused") and os.path.exists(rl) and os.path.getmtime(rl) >= p.get("started", 0):
                    t += "\n----- live pipeline log (logs/" + q["code"] + "_run.log) -----\n" + open(rl, errors="replace").read()[-20000:]
                return self.send(dict(text=IDG.redact_text(t, SET, B)))
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
            if u.path.startswith("/api/sel/"): return self.send(sel_get(u.path[9:], {k: v[0] for k, v in parse_qs(u.query).items()}))
            if u.path.startswith("/api/notif/"): return self.send(notif_get(u.path[11:], {k: v[0] for k, v in parse_qs(u.query).items()}))
            if u.path.startswith("/api/proc/"): return self.send(proc_get(u.path[10:], {k: v[0] for k, v in parse_qs(u.query).items()}))
            if u.path.startswith("/api/u/"): return self.send(unified_get(u.path[7:], {k: v[0] for k, v in parse_qs(u.query).items()}))
            if u.path.startswith("/api/se/"): return self.send(shadow_get(u.path[8:], {k: v[0] for k, v in parse_qs(u.query).items()}))
            if u.path.startswith("/api/im/"): return self.send(image_get(u.path[8:], {k: v[0] for k, v in parse_qs(u.query).items()}))
            if u.path.startswith("/api/calls/"): return self.send(calls_get(u.path[11:], {k: v[0] for k, v in parse_qs(u.query).items()}))
            if u.path.startswith("/api/fsqc/"): return self.send(fsqc_get(u.path[10:], {k: v[0] for k, v in parse_qs(u.query).items()}))
            if u.path.startswith("/api/lineage/"): return self.send(lineage_get(u.path[13:], {k: v[0] for k, v in parse_qs(u.query).items()}))
            if u.path.startswith("/api/train/"): return self.send(train_get(u.path[11:], {k: v[0] for k, v in parse_qs(u.query).items()}))
            if u.path.startswith("/api/setup/"): return self.send(setup_get(u.path[11:], {k: v[0] for k, v in parse_qs(u.query).items()}))
            if u.path == "/api/id/import/thumb":
                q_ = {k: v[0] for k, v in parse_qs(u.query).items()}
                try: return self.send(IDG.IW.thumb(q_.get("plan", ""), q_.get("eid", ""), q_.get("i", "0")), ctype="image/png")
                except Exception as e_: return self.send(dict(error=f"{type(e_).__name__}"), 404)
            if u.path.startswith("/api/xs/"): return self.send(xs_get(u.path[8:], {k: v[0] for k, v in parse_qs(u.query).items()}))
            if u.path.startswith("/api/kp/"): return self.send(kp_get(u.path[8:], {k: v[0] for k, v in parse_qs(u.query).items()}))
            if u.path.startswith("/api/percival/"): return self.send(pg_get(u.path[14:], {k: v[0] for k, v in parse_qs(u.query).items()}))
            if u.path.startswith("/api/workspace/"): return self.send(workspace_get(u.path[15:], {k: v[0] for k, v in parse_qs(u.query).items()}))
            if u.path.startswith("/api/storage/"): return self.send(storage_get(u.path[13:], {k: v[0] for k, v in parse_qs(u.query).items()}))
            if u.path.startswith("/api/vault/"): return self.send(vault_get(u.path[11:], {k: v[0] for k, v in parse_qs(u.query).items()}))
            if u.path.startswith("/api/app/"): return self.send(app_lifecycle_get(u.path[9:], {k: v[0] for k, v in parse_qs(u.query).items()}))
            if u.path.startswith("/api/transfer/"): return self.send(transfer_get(u.path[14:], {k: v[0] for k, v in parse_qs(u.query).items()}))
            if u.path.startswith("/api/clean/"): return self.send(clean_get(u.path[11:], {k: v[0] for k, v in parse_qs(u.query).items()}))
            if u.path.startswith("/api/legacy/"): return self.send(legacy_get(u.path[12:], {k: v[0] for k, v in parse_qs(u.query).items()}))
            if u.path.startswith("/api/files/"): return self.send(files_get(u.path[11:], {k: v[0] for k, v in parse_qs(u.query).items()}))
            if u.path.startswith("/api/wizard/"): return self.send(wizard_get(u.path[12:], {k: v[0] for k, v in parse_qs(u.query).items()}))
            if u.path == "/api/health": return self.send(health_get())
            if u.path.startswith("/api/recovery/"): return self.send(recovery_get(u.path[14:], {k: v[0] for k, v in parse_qs(u.query).items()}))
            if u.path.startswith("/api/migration/"): return self.send(migration_get(u.path[15:], {k: v[0] for k, v in parse_qs(u.query).items()}))
            if u.path.startswith("/api/id/") and u.path != "/api/id/template.xlsx": return self.send(id_get(u.path[8:], {k: v[0] for k, v in parse_qs(u.query).items()}))
            if u.path == "/api/id/template.xlsx":
                import manifest as MF
                return self.send(MF.template_bytes(), ctype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", fname="Percival_Import_Template.xlsx")
            if u.path == "/api/results": return self.send(results())
            if u.path == "/api/blind/state": return self.send(BG.state(B, q.get("code", "")))
            if u.path == "/api/export.xlsx" and [p["code"] for p in PAT if IDG.requires_accession(p["code"], SET)]:
                return self.send(dict(error="export refused in Standard mode: some studies have no accession number yet - enter them (Studies › Edit identifiers) or switch to Incognito"), code=409)
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
                for k_ in ("backup_dir", "export_dir", "library_dir"):
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
                elif a in ("retry", "rerun", "swi_only", "recon", "coreg_masked", "synthmorph") and IDG.requires_accession(p["code"], SET):
                    return self.send(dict(ok=False, error=IDG.requires_accession(p["code"], SET)))
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
                if "name" in d:                                # v5.16: names only in the encrypted vault (Standard mode, unlocked)
                    if not IDG.reveal(SET): return self.send(dict(error="switch to Standard mode and unlock the identity vault to edit the patient name"))
                    IDG.edit(dict(code=p["code"], patient_name=d["name"], confirm=True, reason="edited in the study list"), SET, by="app user")
                if d.get("new_code") and d["new_code"] != p["code"]:
                    nc = d["new_code"]
                    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,32}", nc) or pget(nc): return self.send(dict(error="invalid or duplicate code"))
                    if p["status"] not in ("waiting", "decision"): return self.send(dict(error="a code can only be changed before processing starts (results are filed under it)"))
                    nm = names().get(p["code"], ""); set_name(nc, nm, old_code=p["code"]) if nm else None
                    IDG.rekey(p["code"], nc); p["code"] = nc            # before processing only: no file is named after it yet
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
                    import webview; webview.create_window("Percival reviewer", r["url"], width=1500, height=950); r["opened"] = True
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
            if u.path.startswith("/api/sel/"): return self.send(sel_post(u.path[9:], d))
            if u.path.startswith("/api/notif/"): return self.send(notif_post(u.path[11:], d))
            if u.path.startswith("/api/proc/"): return self.send(proc_post(u.path[10:], d))
            if u.path.startswith("/api/u/"): return self.send(unified_post(u.path[7:], d))
            if u.path.startswith("/api/se/"): return self.send(shadow_post(u.path[8:], d))
            if u.path.startswith("/api/im/"): return self.send(image_post(u.path[8:], d))
            if u.path.startswith("/api/calls/"): return self.send(calls_post(u.path[11:], d))
            if u.path.startswith("/api/fsqc/"): return self.send(fsqc_post(u.path[10:], d))
            if u.path.startswith("/api/lineage/"): return self.send(lineage_post(u.path[13:], d))
            if u.path.startswith("/api/train/"): return self.send(train_post(u.path[11:], d))
            if u.path.startswith("/api/setup/"): return self.send(setup_post(u.path[11:], d))
            if u.path.startswith("/api/id/"): return self.send(id_post(u.path[8:], d))
            if u.path.startswith("/api/xs/"): return self.send(xs_post(u.path[8:], d))
            if u.path.startswith("/api/sa/"): return self.send(sa_post(u.path[8:], d))
            if u.path.startswith("/api/kp/"): return self.send(kp_post(u.path[8:], d))
            if u.path.startswith("/api/percival/"): return self.send(pg_post(u.path[14:], d))
            if u.path.startswith("/api/workspace/"): return self.send(workspace_post(u.path[15:], d))
            if u.path.startswith("/api/storage/"): return self.send(storage_post(u.path[13:], d))
            if u.path.startswith("/api/vault/"): return self.send(vault_post(u.path[11:], d))
            if u.path.startswith("/api/app/"): return self.send(app_lifecycle_post(u.path[9:], d))
            if u.path.startswith("/api/transfer/"): return self.send(transfer_post(u.path[14:], d))
            if u.path.startswith("/api/clean/"): return self.send(clean_post(u.path[11:], d))
            if u.path.startswith("/api/legacy/"): return self.send(legacy_post(u.path[12:], d))
            if u.path.startswith("/api/files/"): return self.send(files_post(u.path[11:], d))
            if u.path.startswith("/api/wizard/"): return self.send(wizard_post(u.path[12:], d))
            if u.path.startswith("/api/recovery/"): return self.send(recovery_post(u.path[14:], d))
            if u.path.startswith("/api/migration/"): return self.send(migration_post(u.path[15:], d))
            if u.path in ("/api/share", "/api/export"):           # explicit warning + confirmation, verified local folder only
                if d.get("confirm_clinical") is not True: return self.send(dict(ok=False, needs_confirm=True, warning=EXPORT_WARNING,
                                                                     error="export needs your confirmation of the clinical-data warning (dialog pending design approval)"))
                try: export_dest()
                except ExportRefused as e: return self.send(dict(ok=False, error=str(e)))
            if u.path == "/api/share":
                out_ = share_package(d["codes"]); notify_c("done", "exports", "Share package written", out_); return self.send(dict(ok=True, path=out_))
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
            if u.path == "/api/blind/release":                                          # Phase 3A.2: explicit, journaled release without a blind read
                return self.send(BG.release(B, str(d.get("code", "")), d.get("by", ""), d.get("reason", ""), d.get("confirm", "")))
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
    try: storage_autofix()                                   # FreeSurfer found + vault created without Terminal (see storage_autofix)
    except Exception as _e: print(f"storage check: {_e}", flush=True)
    try: transfer_pool()                                     # Phase 1d: background transfers + interrupted-job detection
    except Exception as _e: print(f"transfer workers not started: {_e}", flush=True)
    threading.Thread(target=ai_backfill, daemon=True).start()
    threading.Thread(target=worker, daemon=True).start()
    pg_init()
    threading.Thread(target=watcher, daemon=True).start()          # v5.14.2-rc4: notifications + auto-train
    def _caff_watch():
        while True: caffeinate(bool(RUNNING)); time.sleep(5)
    threading.Thread(target=_caff_watch, daemon=True).start()
    # audit: SIGTERM (e.g. logout / kill) runs the same safe shutdown as Quit (transfers pause, then the process exits)
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=_perform_safe_shutdown, args=(True,), daemon=False).start())
    srv = ThreadingHTTPServer(("127.0.0.1", port), H); url = f"http://127.0.0.1:{port}/"
    print(f"Percival app: {url}  (CSS_BASE={B})", flush=True)
    how = None if "--no-window" in a else open_window(url)
    WIN["port"] = port
    if how == "webview":
        import webview; WIN["webview"] = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        win = webview.create_window("Percival", url, width=1400, height=900)
        WIN["window"] = win
        def on_closing():
            _perform_safe_shutdown(pause_jobs=True)
            return True
        win.events.closing += on_closing
        webview.start(dock_icon_follow_theme)
    else:
        try: srv.serve_forever()
        except KeyboardInterrupt: pass
        finally:
            try: transfer_pool_shutdown(timeout=15.0)       # audit: running transfers pause at a safe boundary on every exit
            except Exception: pass
