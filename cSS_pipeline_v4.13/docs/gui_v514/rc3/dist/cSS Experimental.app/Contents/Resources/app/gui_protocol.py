"""gui_protocol.py - screen C: the in-app GUI test protocol. Automatic checks where a check can be automated; manual items the
user ticks while operating the app (3-D viewer, reviewer panel, blind read). State: $CSS_BASE/uscore/gui_protocol.json; the record
is saved as results/test_record_<time>.xlsx + .json. Read-only on the original pipeline: the only writes are under uscore/ and
the results folder. Fail-safe and integrity checks work on a finished patient without touching its original files."""
import os, sys, json, glob, time, hashlib, datetime, platform, importlib

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
B = os.environ.get("CSS_BASE", os.path.expanduser("~/css_project"))
OUT = os.path.join(B, "uscore"); F = os.path.join(OUT, "gui_protocol.json")

ITEMS = [
    ("T1", "Installation and startup", "auto", "versions, packages, installed scripts, build stamp, unified package"),
    ("T2", "Study loading", "auto", "a finished patient has its SWI, candidates and QC files"),
    ("T3", "Processing completed", "auto", "every finished patient: candidates list + QC file written"),
    ("T4", "Original detector unchanged", "auto", "installed detector / scorer / registration files = shipped reference hashes"),
    ("T5", "3-D viewer works (you confirm)", "manual", "open a candidate in 3-D: rotate, isolated / context, layers, click -> MRI slices, core / support layers, resolution classes shown. Only YOU can pass this item - T5a does not test the viewer"),
    ("T5a", "3-D viewer files installed (does NOT test the viewer)", "auto", "css_morph3d, css_morph3d_v2 and morph3d_view.js installed and importable - a prerequisite of T5, not a substitute for it"),
    ("T6", "Unified scoring", "auto", "for scored patients: one unified report per candidate, valid categories, nothing suppressed"),
    ("T7", "Training and validation", "auto", "development report exists, trained on development studies only, no held-out label read"),
    ("T8", "Reports and exports", "auto", "unified Excel export written with its sheets; original results workbook still written"),
    ("T9", "Error handling (fail-safe)", "auto", "an injected unified failure leaves the patient 'done' and the original results intact"),
    ("T10", "Recovery", "auto", "no unified job left 'running' after a restart; interrupted jobs are marked, never silently lost"),
    ("T11", "Data integrity", "auto", "detector outputs byte-identical (hash) and reader files untouched (size + modification time; their content is never opened) before / after a unified run"),
    ("T12", "Synthetic adversarial tests", "auto", "last synthetic robustness run: 0 critical failures (genuine cSS never 'alternative')"),
    ("T13", "Held-out protection", "auto", "held-out labels never read; no GUI route to held-out evaluation; locked without written authorization"),
    ("T14", "Reviewer panel (screen B)", "manual", "unified panel shows category, predictors, detectors, stability; hidden in blind read until the final save"),
    ("T15", "Original workflow end to end", "manual", "add a patient, process it, review it, export: works with the unified feature ON and OFF"),
]


def load():
    st = json.load(open(F)) if os.path.exists(F) else {}
    return dict(items=[dict(id=i, name=n, kind=k, what=w, **st.get(i, dict(result="not run", note="", time=""))) for i, n, k, w in ITEMS])


def _set(i, result, note):
    st = json.load(open(F)) if os.path.exists(F) else {}
    st[i] = dict(result=result, note=str(note)[:600], time=datetime.datetime.now().isoformat(timespec="seconds"))
    os.makedirs(OUT, exist_ok=True); json.dump(st, open(F, "w"), indent=1)


KIND = {i: k for i, _, k, _ in ITEMS}


def mark(i, result, note=""):
    """manual items only: an automatic result can never be overwritten by hand (a failed automatic check cannot be relabelled)."""
    if KIND.get(i) != "manual": raise ValueError(f"{i} is an automatic check: its result comes only from 'Run automatic checks'")
    if result not in ("pass", "fail", "not run", "n/a"): raise ValueError("result must be pass / fail / not run / n/a")
    _set(i, result, note); return dict(ok=True)


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f: h.update(f.read())
    return h.hexdigest()


READER_FILE = ("_calls", "_final", "_score", "_review_log", "_missed", "_excluded_audit", "viewer_settings")


def _snapshot(code):
    """integrity signature of a patient's original files. Reader files (calls, final records, scores, review logs, missed marks,
    viewer settings) are NEVER opened: their signature is (size, modification time in ns), which detects any write without reading
    content - so held-out reader labels are not read even by this check (cycle-2 held-out audit). Detector outputs are hashed."""
    fs = [f for f in glob.glob(f"{B}/review/{code}_*") if os.path.isfile(f)] + [f for f in (f"{B}/review/viewer_settings.json",) if os.path.exists(f)]
    fs += [f for f in glob.glob(f"{B}/work/{code}_*") if os.path.isfile(f) and os.path.getsize(f) < 200e6]
    sig = {}
    for f in sorted(fs):
        if any(k in os.path.basename(f) for k in READER_FILE):
            st = os.stat(f); sig[f] = f"stat:{st.st_size}:{st.st_mtime_ns}"
        else: sig[f] = sha(f)
    return sig


def run_auto(PAT, write_results_file, queue_unified):
    import unified_gui as UG
    res = {}
    done = [p for p in PAT if p.get("status") == "done" and os.path.exists(f"{B}/review/{p['code']}_candidates.csv")]
    # T1
    try:
        mods = {m: importlib.import_module(m).__version__ for m in ("numpy", "scipy", "nibabel", "pandas")}
        build = open(f"{B}/scripts/BUILD").read().strip() if os.path.exists(f"{B}/scripts/BUILD") else "missing"
        ok = os.path.isdir(f"{B}/scripts") and os.path.exists(UG.CLI) and "$Format" not in build
        res["T1"] = ("pass" if ok else "fail", f"python {platform.python_version()}, {mods}, build '{build}', unified package {UG.PKG}")
    except Exception as e: res["T1"] = ("fail", e)
    # T2 / T3
    if not done:
        res["T2"] = res["T3"] = ("not run", "no finished patient yet - process one through Add patients first")
    else:
        p = done[0]["code"]
        have = {k: os.path.exists(f) for k, f in (("swi", f"{B}/data/{p}_swi.nii"), ("candidates", f"{B}/review/{p}_candidates.csv"), ("qc", f"{B}/review/{p}_qc.json"))}
        res["T2"] = ("pass" if have["swi"] and have["candidates"] else "fail", f"{p}: {have}")
        miss = [x["code"] for x in done if not (os.path.exists(f"{B}/review/{x['code']}_candidates.csv") and os.path.exists(f"{B}/review/{x['code']}_qc.json"))]
        res["T3"] = ("pass" if not miss else "fail", f"{len(done)} finished; missing outputs: {miss or 'none'}")
    # T4
    try:
        ref = json.load(open(os.path.join(HERE, "production_reference.json"))); bad = []
        for f, r in ref.items():
            inst = f"{B}/scripts/{f}"
            if not os.path.exists(inst): bad.append(f"{f}: not installed"); continue
            if sha(inst) != r["sha256_v514"]: bad.append(f"{f}: installed copy differs from the shipped reference")
        unchanged = [f for f, r in ref.items() if r["same_as_115721f"]]
        res["T4"] = ("pass" if not bad else "fail", (f"{len(ref)} files verified; identical to 115721f: {len(unchanged)} "
                     "(prep_anat.sh differs only by the opt-in CSS_REG_METHOD switch; " + "; ".join(f"{f}: {r.get('change')}" for f, r in ref.items() if r.get("change")) + ")") if not bad else "; ".join(bad))
    except Exception as e: res["T4"] = ("fail", e)
    # T5a
    try:
        sys.path.insert(0, f"{B}/scripts"); sys.path.insert(0, os.path.join(ROOT, "scripts"))
        importlib.import_module("css_morph3d"); importlib.import_module("css_morph3d_v2")
        js = any(os.path.exists(os.path.join(d, "morph3d_view.js")) for d in (f"{B}/scripts", os.path.join(ROOT, "scripts")))
        res["T5a"] = ("pass" if js else "fail", "modules import; viewer script " + ("found" if js else "MISSING"))
    except Exception as e: res["T5a"] = ("fail", e)
    # T6
    scored = [x["code"] for x in done if UG.candidates(x["code"])]
    if not scored: res["T6"] = ("not run", "no patient scored yet (enable the unified score or press 'Score patient')")
    else:
        import pandas as pd; probs = []
        for c in scored:
            reps = UG.candidates(c); n = len(pd.read_csv(f"{B}/review/{c}_candidates.csv"))
            if len(reps) != n: probs.append(f"{c}: {len(reps)} reports for {n} candidates")
            if any(r["category"] not in ("css_compatible", "uncertain", "alternative_high_confidence") for r in reps): probs.append(f"{c}: invalid category")
        aud = [json.loads(l) for l in open(f"{OUT}/suppression_audit.jsonl")] if os.path.exists(f"{OUT}/suppression_audit.jsonl") else []
        if any(a.get("action") == "applied" for a in aud): probs.append("a suppression was APPLIED")
        res["T6"] = ("pass" if not probs else "fail", f"{len(scored)} patients scored; " + ("; ".join(probs) or "all candidates reported, none suppressed"))
    # T7
    v = UG.validation()
    if not v.get("available"): res["T7"] = ("not run", "no training yet (Unified -> 4 Train & validate)")
    else:
        C = UG.cohort(); m = json.load(open(f"{OUT}/model_trained.json"))
        ok = set(m["train_studies"]) <= set(C.studies("development")) and UG.heldout_reads() == 0
        res["T7"] = ("pass" if ok else "fail", f"trained on {len(m['train_studies'])} development studies; held-out label reads {UG.heldout_reads()}; estimate type: {v.get('estimate_type')}")
    # T8
    try:
        e = UG.export(); import openpyxl
        sheets = openpyxl.load_workbook(e["path"], read_only=True).sheetnames
        wf = write_results_file()
        res["T8"] = ("pass" if "candidates" in sheets and os.path.exists(wf) else "fail", f"{os.path.basename(e['path'])} sheets {sheets}; results workbook {os.path.basename(wf)}")
    except Exception as e: res["T8"] = ("fail", e)
    # T9 + T11 (one finished patient; original files hashed around the runs)
    if not done: res["T9"] = res["T11"] = ("not run", "no finished patient yet")
    else:
        p = done[0]; before = _snapshot(p["code"]); st0 = p["status"]
        os.environ["CSS_USCORE_FAIL_TEST"] = "1"
        try: r = UG.score_patient(p["code"])
        finally: os.environ.pop("CSS_USCORE_FAIL_TEST", None)
        try: write_results_file(); wrote = True
        except Exception: wrote = False
        res["T9"] = ("pass" if r["status"] == "failed" and p["status"] == st0 == "done" and wrote else "fail",
                     f"injected failure -> unified '{r['status']}', patient still '{p['status']}', results workbook written: {wrote}")
        r2 = UG.score_patient(p["code"]); after = _snapshot(p["code"])
        changed = [os.path.basename(f) for f in set(before) | set(after) if before.get(f) != after.get(f)]
        res["T11"] = ("pass" if not changed else "fail", f"{len(before)} files hashed; real unified run '{r2['status']}'; changed: {changed or 'none'}")
    # T10
    stuck = [x["code"] for x in PAT if x.get("uscore_status") == "running" and not UG.job("score")["status"] == "running"]
    res["T10"] = ("pass" if not stuck or all(x.get("uscore_status") != "running" for x in PAT) else "fail", f"unified jobs marked running: {stuck or 'none'}")
    # T12
    rb = f"{OUT}/gui_robustness.json"
    if not os.path.exists(rb): res["T12"] = ("not run", "run 7 Robustness -> synthetic suite first")
    else:
        d = json.load(open(rb)); res["T12"] = ("pass" if not d["critical"] else "fail", f"{d['seeds']} seeds per scene; critical failures {d['critical'] or 0} (synthetic, never in the cohort)")
    # T13
    hs = UG.heldout_status()
    src = open(os.path.join(HERE, "css_app.py")).read()
    no_route = "heldout" not in src.split("def unified_post")[1].split("def last_activity")[0]
    res["T13"] = ("pass" if UG.heldout_reads() == 0 and hs["locked"] and no_route else "fail",
                  f"held-out label reads {UG.heldout_reads()}; locked: {hs['why']}; GUI route to held-out evaluation: {'none' if no_route else 'PRESENT'}")
    for k, (r, n) in res.items():
        if KIND.get(k) == "manual": continue                     # never: an automatic run cannot pass a manual item
        _set(k, r, n)
    return dict(ok=True, **load())


def save_record():
    import pandas as pd, unified_gui as UG
    d = load(); m = UG.model_info()
    fn = os.path.join(UG.export_dir(), f"test_record_{'SYNTHETIC_' if UG.DEMO else ''}{datetime.datetime.now():%Y%m%d_%H%M}.xlsx")
    head = [("app", "cSS Pipeline v5.14-gui (experimental)"), ("time", datetime.datetime.now().isoformat(timespec="seconds")),
            ("build", open(f"{B}/scripts/BUILD").read().strip() if os.path.exists(f"{B}/scripts/BUILD") else "missing"),
            ("model trained", m.get("trained_hash", "")), ("model frozen", m.get("frozen_hash", "") or "not frozen"), ("synthetic demo", UG.DEMO)]
    with pd.ExcelWriter(fn) as w:
        pd.DataFrame(head, columns=["item", "value"]).to_excel(w, sheet_name="about", index=False)
        pd.DataFrame(d["items"]).to_excel(w, sheet_name="protocol", index=False)
    json.dump(dict(header=dict(head), **d), open(fn.replace(".xlsx", ".json"), "w"), indent=1, default=str)
    return dict(path=fn)
