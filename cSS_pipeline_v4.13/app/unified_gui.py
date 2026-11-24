"""unified_gui.py - back end of the app's "Unified (experimental)" section (screens A and C).

Everything runs as background jobs (status, progress, log, error) so the GUI never blocks. Heavy steps run the unified CLI in a
SUBPROCESS: a crash there can never take the app or the original pipeline down. Outputs go only to $CSS_BASE/uscore/.
Reader files (review/*_calls*.csv, *_score*.json, viewer settings) are never written here.
Held-out labels: not reachable from the GUI at all. Training never freezes; freezing needs the typed word FREEZE.
Synthetic demo mode (CSS_USCORE_DEMO=1 + CSS_USCORE_MANIFEST): SYN studies only, every screen and file stamped SYNTHETIC."""
import os, sys, json, glob, time, threading, subprocess, hashlib, datetime, re, io

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
B = os.environ.get("CSS_BASE", os.path.expanduser("~/css_project"))
OUT = os.path.join(B, "uscore")
DEMO = os.environ.get("CSS_USCORE_DEMO") == "1"
PKG = os.path.join(ROOT, "unified_score") if os.path.exists(os.path.join(ROOT, "unified_score", "run_unified.py")) else os.path.join(B, "unified_score")
CLI = os.path.join(PKG, "run_unified.py")
sys.path.insert(0, PKG)
TIMEOUT_PATIENT_S = int(os.environ.get("CSS_USCORE_TIMEOUT_S", "900"))   # 15 min per patient (fail-safe); env override for tests only
JOBS = {}; JLOCK = threading.Lock()
PRODUCTION_FILES = ["detect_css.py", "score_css.py", "css_common.py", "css_qc.py", "run_css.sh", "align_seg.py", "cohort.py", "css_confidence.py", "prep_anat.sh"]


def cohort():
    from uscore import common as cm
    if DEMO: return cm.Cohort(os.environ["CSS_USCORE_MANIFEST"], eligible_prefix="SYN", synthetic_test=True)
    if not os.path.exists(cm.DEFAULT_MANIFEST):         # v5.21: the packaged app ships no cohort file (clinical-derived): an empty one
        e = os.path.join(B, "uscore", "cohort_manifest_empty.csv"); os.makedirs(os.path.dirname(e), exist_ok=True)
        if not os.path.exists(e):
            with open(e, "w") as f: f.write("study_id,starts_with_M,decision,role,exclusion_reason,scoreability,source,note,container_name_collision\n")
        return cm.Cohort(e)
    return cm.Cohort()


def env():
    e = dict(os.environ); e["CSS_BASE"] = B; return e


# ------------------------------------------------------------------ jobs
def job(name):
    with JLOCK: return dict(JOBS.get(name) or dict(status="idle"))


def start(name, fn, *a):
    with JLOCK:
        if JOBS.get(name, {}).get("status") == "running": return dict(ok=False, error=f"{name} is already running")
        JOBS[name] = dict(status="running", started=time.time(), progress=0.0, log=[], error="", result=None, stop=False)
    def run():
        try:
            r = fn(*a)
            with JLOCK: JOBS[name].update(status="stopped" if JOBS[name]["stop"] else "completed", result=r, finished=time.time(), progress=1.0)
        except Exception as ex:
            with JLOCK: JOBS[name].update(status="failed", error=str(ex)[-800:], finished=time.time())
    threading.Thread(target=run, daemon=True).start()
    return dict(ok=True)


def _log(name, line, progress=None):
    with JLOCK:
        j = JOBS.get(name)
        if j is None: return
        j["log"] = (j["log"] + [line])[-300:]
        if progress is not None: j["progress"] = progress


def _stopped(name):
    with JLOCK: return JOBS.get(name, {}).get("stop", False)


def stop(name):
    with JLOCK:
        if name in JOBS and JOBS[name]["status"] == "running": JOBS[name]["stop"] = True
    return dict(ok=True)


def _cli(name, args, timeout):
    p = subprocess.Popen([sys.executable, CLI] + args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env())
    t0 = time.time(); out = []
    for line in p.stdout:
        out.append(line.rstrip()); _log(name, line.rstrip())
        if _stopped(name) or time.time() - t0 > timeout: p.kill(); break
    p.wait()
    if time.time() - t0 > timeout: raise TimeoutError(f"{' '.join(args)}: no result after {timeout // 60} min")
    if p.returncode not in (0, None) and not _stopped(name): raise RuntimeError("\n".join(out[-8:]))
    return out


# ------------------------------------------------------------------ 1 cohort audit (in-app, read-only)
def audit():
    C = cohort(); rows = []; problems = []
    for role in ("development", "held-out"):
        for s in C.studies(role):
            r = dict(study=s, role=role)
            for k, f in (("candidates", f"review/{s}_candidates.csv"), ("swi", f"data/{s}_swi.nii"), ("vessels", f"work/{s}_vessels.nii.gz"),
                         ("pial", f"work/{s}_pial_sd.nii.gz"), ("qc", f"review/{s}_qc.json")):
                r[k] = os.path.exists(os.path.join(B, f)) or (k == "swi" and os.path.exists(os.path.join(B, f + ".gz")))
            r["raw_swi"] = bool(glob.glob(f"{B}/raw/{s}/SWI/*.nii*"))
            try: q = json.load(open(f"{B}/review/{s}_qc.json"))
            except Exception: q = {}
            from uscore.common import registration_state
            r["registration"] = registration_state(q); r["label_shift_mm"] = q.get("label_shift_mm")
            r["note"] = C.rows[s].get("scoreability", "")
            r["processed"] = r["candidates"] and r["swi"]
            if not r["processed"]: problems.append(f"{s}: not processed yet (no candidates / SWI) - stays in the manifest")
            if r["registration"] in ("unreliable", "marginal"): problems.append(f"{s}: registration {r['registration']} (shift {r['label_shift_mm']} mm) - surface / sulcal / vessel / extracranial features flagged")
            if r["registration"] == "swi_only": problems.append(f"{s}: SWI-only anatomy - location / sulcal features coarse")
            rows.append(r)
    inc = [r for r in C.rows.values() if r["decision"] == "include"]
    checks = [("only eligible studies included", all(r["study_id"].startswith(C.prefix) for r in inc)),
              ("no study in two roles", len({r["study_id"] for r in inc}) == len(inc)),
              ("every identifier has an inclusion or exclusion reason", all(r["decision"] == "include" or r.get("exclusion_reason") for r in C.rows.values()))]
    hs = {}
    for r in rows:
        f = f"{B}/data/{r['study']}_swi.nii"
        if os.path.exists(f):
            with open(f, "rb") as fh: hs.setdefault(hashlib.sha1(fh.read(1 << 22)).hexdigest(), []).append(r["study"])
    dup = [v for v in hs.values() if len(v) > 1]
    checks.append(("no duplicate SWI content", not dup))
    if dup: problems.append(f"same SWI under several identifiers: {dup}")
    res = dict(time=datetime.datetime.now().isoformat(timespec="seconds"), manifest=os.path.basename(C.manifest), manifest_sha=C.manifest_sha[:12],
               n_identifiers=len(C.rows), n_excluded=sum(r["decision"] != "include" for r in C.rows.values()),
               studies=rows, checks=checks, problems=problems, synthetic=DEMO,
               excluded=[dict(study=i, reason=r.get("exclusion_reason", "")) for i, r in sorted(C.rows.items()) if r["decision"] != "include"])
    os.makedirs(OUT, exist_ok=True); json.dump(res, open(f"{OUT}/gui_audit.json", "w"), indent=1)
    return res


# ------------------------------------------------------------------ 2 features
def _extract_all(studies):
    done = []
    for i, s in enumerate(studies):
        if _stopped("extract"): break
        _log("extract", f"[{i + 1}/{len(studies)}] {s} ...", i / max(len(studies), 1))
        try: _cli("extract", ["extract", s], 7200); done.append(s)
        except Exception as e: _log("extract", f"  {s} FAILED: {e}")
    return dict(extracted=done)


def extract(which="all"):
    C = cohort(); st = C.studies("development") + C.studies("held-out")
    if which not in ("all", "missing"): st = [s for s in st if s == which]
    if which == "missing": st = [s for s in st if not os.path.exists(f"{OUT}/features/{s}.json")]
    return start("extract", _extract_all, st)


def reliability():
    from uscore.common import PREDICTORS
    out = dict(per_study=[], reasons={k: {} for k in PREDICTORS}, flagged=[])
    for f in sorted(glob.glob(f"{OUT}/features/*.json")):
        d = json.load(open(f)); row = dict(study=d["study"], role=d.get("role"), n=d["n"], registration=d.get("registration"), raw=d.get("raw_note"))
        for k in PREDICTORS:
            st = [r["F"][k]["status"] for r in d["records"]]
            row[k] = {s: st.count(s) for s in ("reliable", "unreliable", "unavailable")}
            for r in d["records"]:
                for why in r["F"][k]["reasons"]: out["reasons"][k][why] = out["reasons"][k].get(why, 0) + 1
                if r["F"][k]["status"] != "reliable":
                    out["flagged"].append(dict(study=d["study"], cand=r["cand_id"], feature=k, status=r["F"][k]["status"], why="; ".join(r["F"][k]["reasons"])))
        out["per_study"].append(row)
    out["flagged"] = out["flagged"][:500]
    return out


# ------------------------------------------------------------------ 3 train / validate / freeze
def train():
    """Phase 3D review: uScore training is disabled in the app (no provenance / consensus / patient-split safeguards)"""
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "unified_score"))
    try:
        from uscore.pipeline import TRAINING_DISABLED
    except Exception: TRAINING_DISABLED = "uScore training is disabled (experimental; no provenance safeguards)"
    return dict(ok=False, disabled=True, error=TRAINING_DISABLED)


def validation():
    p = f"{OUT}/development_report.json"
    if not os.path.exists(p): return dict(available=False)
    D = json.load(open(p)); M = model_info()
    keep = ("n_candidates", "n_cSS", "n_patients", "predictors", "fallback_log", "outer_auc_calibrated", "outer_auc_raw", "outer_auc_ci", "outer_brier",
            "outer_brier_ci", "calibration_slope", "calibration_intercept", "reliability_bins", "coefficient_stability", "probability_output", "ordering_cut",
            "candidate_sensitivity", "candidate_specificity", "fp_per_patient", "patient_sensitivity", "cSS_positive_patients", "feature_missingness",
            "penalty_at_grid_boundary", "estimate_type", "v510_auc_same_candidates")
    v = {k: D.get(k) for k in keep}
    st = D.get("coefficient_stability") or {}
    v["gate"] = [dict(rule="coefficient signs agree in >= 80 % of outer folds for every predictor", ok=bool(st.get("min_sign_agreement") is not None and st["min_sign_agreement"] >= 0.8),
                      value=st.get("min_sign_agreement")),
                 dict(rule="calibration slope 0.7 - 1.3", ok=bool(D.get("calibration_slope") is not None and 0.7 <= D["calibration_slope"] <= 1.3), value=D.get("calibration_slope")),
                 dict(rule="no held-out label read during development", ok=heldout_reads() == 0, value=heldout_reads())]
    v["available"] = True; v["model"] = M
    return v


def heldout_reads():
    p = f"{OUT}/label_access_log.csv"
    if not os.path.exists(p): return 0
    return sum(1 for l in open(p).read().splitlines()[1:] if l.split(",")[2] == "held-out" and l.split(",")[4] == "1")


def model_info():
    i = dict(trained=False, frozen=False)
    for k, f in (("trained", "model_trained.json"), ("frozen", "model_frozen.json")):
        if os.path.exists(f"{OUT}/{f}"):
            M = json.load(open(f"{OUT}/{f}"))
            i[k] = True; i[k + "_hash"] = M["model_hash"]; i[k + "_at"] = M.get("frozen_at") or datetime.datetime.fromtimestamp(os.path.getmtime(f"{OUT}/{f}")).isoformat(timespec="seconds")
            i.update(predictors=M["predictors"], beta=M["beta"], lam=M["lam"], edf=M["edf"], probability_output=M["probability_output"], ordering_cut=M["ordering_cut"],
                     synthetic_test=M.get("synthetic_test"), model_version=M["model_version"], feature_version=M["feature_version"])
    i["stale_frozen"] = bool(i.get("frozen") and i.get("trained") and i["frozen_hash"] != i["trained_hash"])
    return i


def freeze(confirm):
    from uscore import pipeline as pl
    return pl.freeze(OUT, confirm)


def heldout_status():
    from uscore import pipeline as pl
    M = model_info()
    if not M.get("frozen"): return dict(locked=True, why="no frozen model")
    ok, why = pl.heldout_authorization(OUT, M["frozen_hash"])
    return dict(locked=True, why=("written authorization present, but held-out evaluation is not available from the GUI in this build" if ok else why),
                gui_available=False)


# ------------------------------------------------------------------ 4 candidates / patient step (fail-safe)
def score_all():
    def run():
        _cli("score", ["score"], 6 * 3600); return dict(scored=True)
    return start("score", run)


def score_patient(code):
    """the per-patient background step (after the patient is 'done'); 15 min limit; never raises"""
    t0 = time.time()
    if os.environ.get("CSS_USCORE_FAIL_TEST") == "1": return dict(status="failed", error="injected failure (test)", seconds=0)
    cmd = [sys.executable, CLI, "app", code]
    if os.environ.get("CSS_USCORE_HANG_TEST") == "1": cmd = [sys.executable, "-c", "import time; time.sleep(3600)"]   # tests only: a hung step
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, env=env(), timeout=TIMEOUT_PATIENT_S)
        if r.returncode != 0: return dict(status="failed", error=(r.stderr or r.stdout)[-400:], seconds=round(time.time() - t0))
        return dict(status="completed", seconds=round(time.time() - t0), **json.loads(r.stdout.strip().splitlines()[-1]))
    except subprocess.TimeoutExpired:
        return dict(status="failed", error=f"no result after {TIMEOUT_PATIENT_S} s (step stopped; original results unaffected)", seconds=TIMEOUT_PATIENT_S)
    except Exception as e:
        return dict(status="failed", error=str(e)[:400], seconds=round(time.time() - t0))


def _safe(o):
    """NaN / inf -> None recursively (NaN is not valid JSON; older report files may contain it)"""
    import math
    if isinstance(o, float): return None if not math.isfinite(o) else o
    if isinstance(o, dict): return {k: _safe(v) for k, v in o.items()}
    if isinstance(o, list): return [_safe(v) for v in o]
    return o


def candidates(study):
    for f in (f"{OUT}/reports/{study}.json",):
        if os.path.exists(f): return _safe(json.load(open(f)).get("reports", []))
    f = f"{OUT}/reports/candidates.json"
    if os.path.exists(f): return _safe([r for r in json.load(open(f)) if r["study"] == study])
    return []


def candidate(study, cid):
    for r in candidates(study):
        if int(r["cand_id"]) == int(cid): return r
    return None


def perturbation(study, cid):
    f = f"{OUT}/features/{study}.json"
    if not os.path.exists(f): return dict(available=False)
    for r in json.load(open(f))["records"]:
        if int(r["cand_id"]) == int(cid):
            return dict(available=True, summary=r["stability"], rows=[{k: v for k, v in row.items() if k != "F"} for row in r["perturbation_rows"]])
    return dict(available=False)


# ------------------------------------------------------------------ 5 robustness (synthetic suite; never in the cohort)
def robustness(seeds=3):
    def run():
        p = subprocess.Popen([sys.executable, os.path.join(ROOT, "tests", "check_uscore_seeds.py"), str(int(seeds))], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, cwd=ROOT)
        rows = []
        for line in p.stdout:
            _log("robustness", line.rstrip())
            if line.strip() and not line.startswith(("seeds:", "\n")) and "{" in line: rows.append(line.rstrip())
        p.wait()
        res = json.load(open(os.path.join(ROOT, "unified_score", "output", "adversarial_seeds.json")))
        res["exit_code"] = p.returncode; res["synthetic"] = True
        os.makedirs(OUT, exist_ok=True); json.dump(res, open(f"{OUT}/gui_robustness.json", "w"), indent=1)
        if res["critical"]: raise RuntimeError(f"CRITICAL: genuine cSS called a high-confidence alternative: {res['critical']}")
        return res
    return start("robustness", run)


# ------------------------------------------------------------------ 6 export
def export_dir():
    d = os.path.join(B, "results"); os.makedirs(d, exist_ok=True); return d


def export():
    import pandas as pd
    rows = []
    studies = sorted({os.path.basename(f)[:-5] for f in glob.glob(f"{OUT}/reports/*.json")} - {"candidates"}
                     | ({r["study"] for r in json.load(open(f"{OUT}/reports/candidates.json"))} if os.path.exists(f"{OUT}/reports/candidates.json") else set()))
    for s_ in studies:
        for r in candidates(s_):
            row = dict(study=r["study"], cand_id=r["cand_id"], category=r["category"], reasons="; ".join(r.get("category_reasons", [])),
                       probability=r.get("probability"), raw_score=r.get("raw_score"), protective="; ".join(r.get("protective_flags", [])))
            for k, v in r["predictors"].items(): row[k] = v["value"]; row[k + "_status"] = v["status"]
            for d in r.get("alternative_detectors", []): row["detector_" + d["detector"]] = d["status"]
            rows.append(row)
    M = model_info(); V = validation()
    fn = os.path.join(export_dir(), f"unified_score_{'SYNTHETIC_' if DEMO else ''}{datetime.datetime.now():%Y%m%d_%H%M}.xlsx")
    with pd.ExcelWriter(fn) as w:
        info = [("WARNING", "EXPERIMENTAL research output; not a diagnosis" + (" - SYNTHETIC DEMO, not a result" if DEMO else "")),
                ("model trained", M.get("trained_hash", "")), ("model frozen", M.get("frozen_hash", "") or "NOT frozen"),
                ("probability output", M.get("probability_output")), ("estimate type", V.get("estimate_type", "")), ("held-out", "not evaluated (locked)")]
        pd.DataFrame(info, columns=["item", "value"]).to_excel(w, sheet_name="about", index=False)
        pd.DataFrame(rows or [dict(note="no unified reports yet")]).to_excel(w, sheet_name="candidates", index=False)
        if V.get("available"):
            st = V["coefficient_stability"]
            pd.DataFrame([dict(predictor=k, coef_mean=st["coef_mean"][k], coef_sd=st["coef_sd"][k], sign_agreement=st["sign_agreement"][k]) for k in V["predictors"]]
                         ).to_excel(w, sheet_name="coefficients (CV)", index=False)
            pd.DataFrame([{k: V[k] for k in ("outer_auc_calibrated", "outer_auc_raw", "outer_brier", "calibration_slope", "calibration_intercept",
                                              "candidate_sensitivity", "candidate_specificity", "patient_sensitivity", "estimate_type") if k in V}]
                         ).to_excel(w, sheet_name="cross-validation", index=False)
        rel = reliability()
        pd.DataFrame(rel["flagged"] or [dict(note="none")]).to_excel(w, sheet_name="unreliable features", index=False)
    if os.path.exists(f"{OUT}/COHORT_REPORT.md"):
        import shutil; shutil.copy2(f"{OUT}/COHORT_REPORT.md", fn.replace(".xlsx", "_COHORT_REPORT.md"))
    return dict(path=fn, n_candidates=len(rows))


# ------------------------------------------------------------------ state for the GUI
def state(pats=None):
    C = cohort()
    feat = {os.path.basename(f)[:-5]: json.load(open(f)).get("n") for f in glob.glob(f"{OUT}/features/*.json")}
    rep = {os.path.basename(f)[:-5] for f in glob.glob(f"{OUT}/reports/*.json")} - {"candidates"}
    if os.path.exists(f"{OUT}/reports/candidates.json"):
        try: rep |= {r["study"] for r in json.load(open(f"{OUT}/reports/candidates.json"))}
        except Exception: pass
    studies = [dict(study=s, role=r, features=s in feat, n=feat.get(s), scored=s in rep) for r in ("development", "held-out") for s in C.studies(r)]
    from uscore.common import SUPPRESSION_ENABLED
    a = json.load(open(f"{OUT}/gui_audit.json")) if os.path.exists(f"{OUT}/gui_audit.json") else None
    rb = json.load(open(f"{OUT}/gui_robustness.json")) if os.path.exists(f"{OUT}/gui_robustness.json") else None
    steps = dict(audit="done" if a else "todo",
                 features="done" if studies and all(x["features"] for x in studies if x["role"] == "development") else ("partial" if feat else "todo"),
                 reliability="review" if feat else "todo",
                 train="done" if os.path.exists(f"{OUT}/development_report.json") else "todo",
                 freeze="done" if model_info().get("frozen") else "todo",
                 candidates="done" if rep else "todo",
                 robustness=("failed" if rb and rb.get("critical") else "done") if rb else "todo",
                 export="todo")
    for k, n in (("audit", "audit"), ("features", "extract"), ("train", "train"), ("candidates", "score"), ("robustness", "robustness")):
        js = job(n)["status"]
        if js in ("running", "failed"): steps[k] = js
    return dict(synthetic=DEMO, studies=studies, audit_summary=(dict(time=a["time"], problems=len(a["problems"]), checks_ok=all(c[1] for c in a["checks"])) if a else None),
                steps=steps, model=model_info(), heldout=heldout_status(), suppression=SUPPRESSION_ENABLED, heldout_reads=heldout_reads(),
                jobs={n: {k: v for k, v in job(n).items() if k != "log"} for n in ("audit", "extract", "train", "score", "robustness", "protocol")},
                package=PKG)


def joblog(name): return dict(log=job(name).get("log", []), **{k: v for k, v in job(name).items() if k != "log"})
