"""trace_candidate.py (v5.24) - follow ONE synthetic candidate through every ML component of Percival by EXECUTING the real code paths, and
record what each step produced (or why it could not). Synthetic data only, in a temporary project. Writes a JSON trace and prints a table.
usage: python tests/trace_candidate.py [out.json]

Steps: synthetic MRI + candidates (stand-in for import + detection; the real detector is exercised by tests/run_tests.sh on phantoms)
-> MATH -> Unified Score predictors (real extraction) -> Image ML prototype -> Stage-1 shadow engine -> Unified Score model (Predictor model)
-> expert review (reviewer file format) -> eligibility -> dataset -> Percival training (characteristic ML, image ML, fusion, meta-model,
calibration, Intelligence) -> Percival Score -> Percival shadow mode -> acceptance / promotion -> provenance."""
import glob, json, os, shutil, subprocess, sys, tempfile, time, traceback
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE); PY = sys.executable
OUT = sys.argv[1] if len(sys.argv) > 1 else None
T = tempfile.mkdtemp(prefix="trace_"); B = os.path.join(T, "proj"); TR = []
def step(n, name, fn):
    t0 = time.time()
    try: r = fn(); st = r.pop("_status", "functional")
    except Exception as e: r = dict(error=f"{type(e).__name__}: {e}"[:400], tb=traceback.format_exc()[-600:]); st = "broken"
    TR.append(dict(step=n, name=name, status=st, seconds=round(time.time() - t0, 1), result=r)); print(f"{n:>2} {st:<13} {name}: {json.dumps({k: v for k, v in r.items() if k != 'tb'}, default=str)[:260]}", flush=True)
    return r
def sh(*a, **k):
    r = subprocess.run([PY, *a], capture_output=True, text=True, timeout=k.get("timeout", 1800), env=dict(os.environ, CSS_BASE=B, PYTHONWARNINGS="ignore"))
    return r.returncode, (r.stdout or "")[-1500:], (r.stderr or "")[-800:]

# 1-2 synthetic MRI + candidate list (generator), measurements as the demo app adds them
def s1():
    c, o, e = sh(os.path.join(ROOT, "unified_engine", "run_imaging.py"), "cohort", B, "--n", "16", "--seed", "11")
    if c: raise RuntimeError(e or o)
    c, o, e = sh(os.path.join(ROOT, "app", "mac_percival", "make_demo.py"), B, os.path.join(ROOT, "unified_engine", "run_imaging.py"))
    if c: raise RuntimeError(e or o)
    S = sorted(os.path.basename(p)[:-15] for p in glob.glob(os.path.join(B, "review", "SYN*_candidates.csv")))
    d = pd.read_csv(os.path.join(B, "review", f"{S[0]}_candidates.csv"))
    return dict(studies=len(S), study=S[0], candidate=int(d.cand_id.iloc[0]), columns=list(d.columns), note="synthetic phantoms (run_imaging cohort) + make_demo measurements; "
                "real import / FreeSurfer / detect_css are not part of this trace (tests/run_tests.sh covers the detector on phantoms)", _status="functional")
r1 = step(1, "MRI + candidate detection (synthetic stand-in)", s1); SID, CID = r1.get("study"), r1.get("candidate")
shutil.copytree(os.path.join(ROOT, "scripts"), os.path.join(B, "scripts"), ignore=shutil.ignore_patterns("__pycache__"))
def s3():
    d = pd.read_csv(os.path.join(B, "review", f"{SID}_candidates.csv")).set_index("cand_id")
    return dict(score_v4=float(d.loc[CID, "score_v4"]), source="review/ID_candidates.csv column score_v4 (detect_css.py; demo: darkness term only)")
step(3, "MATH", s3)
sys.path[:0] = [os.path.join(ROOT, "unified_score"), os.path.join(ROOT, "unified_engine"), os.path.join(ROOT, "app"), os.path.join(ROOT, "scripts")]
def s3b():
    from uscore import pipeline as PL, common as CM
    class AppCohort:
        synthetic = False
        def role(self, s): raise CM.CohortError("application")
    PL.extract_study(B, SID, AppCohort(), os.path.join(B, "uscore"), application=True)
    F = json.load(open(os.path.join(B, "uscore", "features", f"{SID}.json")))
    rec = next(r for r in F["records"] if int(r["cand_id"]) == CID)
    st = {k: v.get("status") for k, v in rec["F"].items() if isinstance(v, dict) and "status" in v}
    rel = sum(1 for v in st.values() if v == "reliable")
    return dict(predictors=st, reliable=rel, _status="functional" if rel else "partial",
                note="extracted exactly as Percival does on demand (percival_gui._predictors)")
step(4, "Unified Score predictors (real extraction)", s3b)
def s5():
    c, o, e = sh(os.path.join(ROOT, "unified_engine", "run_imaging.py"), "infer", SID, "--base", B, "--write")
    p = os.path.join(B, "unified_engine", "image_ml", f"{SID}.json")
    if not os.path.exists(p): return dict(rc=c, out=(e or o)[-300:], consumed_by="nothing", _status="experimental")
    J = json.load(open(p))
    return dict(rc=c, model=J.get("model", {}).get("name") if isinstance(J.get("model"), dict) else J.get("model"), synthetic_only=True,
                consumed_by="nothing (not read by Percival, Training shows a card)", _status="disconnected")
step(5, "Image ML prototype (Image ML tab)", s5)
def s6():
    c, o, e = sh(os.path.join(ROOT, "unified_engine", "run_engine.py"), "shadow", SID, "--base", B)
    J = json.loads(o.strip().splitlines()[-1]) if c == 0 and o.strip() else {}
    return dict(rc=c, ml_applied=J.get("ml_applied"), ml_status=J.get("ml_status"), out=(e or o)[-200:] if c else "",
                consumed_by="nothing (output unified_engine/shadow/ID.json read only by its own screen)", _status="disconnected")
step(6, "Stage-1 engine (Shadow ML tab)", s6)
def s8():
    c, o, e = sh(os.path.join(ROOT, "unified_score", "run_unified.py"), "train", timeout=600)
    return dict(rc=c, out=(e or o)[-400:], note="its cohort = fixed manifest unified_score/cohort_manifest_RECONCILED.csv (M01-M26); its model is not an input of the Percival Score",
                _status="disconnected" if c else "experimental")
step(8, "Unified Score model (Predictor model tab) - train", s8)
# expert review in the reviewer's file format (synthetic truth = the "expert")
def s10():
    n = 0
    for p in glob.glob(os.path.join(B, "unified_engine", "image_truth", "SYN*.csv")):
        sid = os.path.basename(p)[:-4]; t = pd.read_csv(p); t = t[t["list"] == "candidates"]
        c = pd.read_csv(os.path.join(B, "review", f"{sid}_candidates.csv")); y = {int(o): k for o, k in zip(t.obj_id, t.primary_class)}
        rows = [dict(cand_id=int(r.cand_id), call="cSS" if y.get(int(r.cand_id)) == "definite_css" else "Vessel", comment="", reviewer="Dr Trace",
                     time="2026-11-21 10:00:00", vox_i=r.vox_i, vox_j=r.vox_j, vox_k=r.vox_k, volume_mm3=r.volume_mm3) for r in c.itertuples()]
        pd.DataFrame(rows).to_csv(os.path.join(B, "review", f"{sid}_calls_Dr_Trace.csv"), index=False); n += len(rows)
        json.dump(dict(reviewer="Dr Trace", saved="2026-11-21 10:05:00"), open(os.path.join(B, "review", f"{sid}_final_Dr_Trace.json"), "w"))
    call = pd.read_csv(os.path.join(B, "review", f"{SID}_calls_Dr_Trace.csv")).set_index("cand_id").loc[CID, "call"]
    return dict(calls_written=n, candidate_call=call, file=f"review/{SID}_calls_Dr_Trace.csv (+ final save)")
step(10, "Expert review (reviewer file format)", s10)
import percival_gui as PG
P_ = json.load(open(os.path.join(B, "app_data", "patients.json")))
SET = dict(features={}, percival_test_fraction=0.25)
PG.init(B=B, SC=os.path.join(B, "scripts"), SET=SET, patients=lambda: list(P_), is_reviewed=lambda c: True, label=lambda c: c, patient_of=lambda c: c,
        fingerprint_of=lambda c: "", save_settings=lambda: None, notify=lambda *a: None)
PG.authorize(True)
def s11():
    C = {c["cand_id"]: c for c in PG.candidates_of(SID)["candidates"]}[CID]
    return dict(status=C["status"], components=C["components"], partition=C["partition"], reasons=C["reasons"])
step(11, "Training eligibility (per component)", s11)
os.environ.update(CSS_PERCIVAL_EPOCHS="8")
def s13():
    PG._train("trace"); j = dict(PG.JOB)
    if j["state"] != "finished": raise RuntimeError(j.get("error"))
    M = PG.load(PG.versions()[-1]); fam = M["intelligence"]["families"]
    return dict(version=M["version"], dataset=M["data"]["dataset"], chosen=dict(char=fam["char"]["chosen"], image=fam["image"]["chosen"], fusion=fam["fusion"]["chosen"],
                meta=M["discovery"]["chosen"]), acceptance=M["acceptance"], test_auc=(M["test"].get("percival") or {}).get("auc"), math_auc=(M["test"].get("math") or {}).get("auc"))
r13 = step(13, "Percival training cycle (char + image + fusion + meta + calibration + Intelligence)", s13)
def s12():
    from uengine.percival import datasets as DS
    m = DS.load(PG.P(), r13["dataset"]); e = next(x for x in m["examples"] if x["study"] == SID and x["cand_id"] == CID)
    return dict(dataset=m["id"], content_hash=m["content_hash"], example=e)
step(12, "Dataset inclusion (manifest)", s12)
def s9():
    v = r13["version"]
    st0 = PG.status_all()[v]["status"]
    if not PG.active():
        r = PG.promote(v, by="trace")
        if not r["ok"]: r = PG.promote(v, by="trace", why="trace: research use (synthetic), to follow scoring", override=True)
    assert st0 in ("candidate", "experimental") and PG.status_all()[v]["status"] == "active"
    rec = PG.score_study(SID); c = next(x for x in rec["candidates"] if x["cand_id"] == CID)
    return dict(model=rec["model"], percival_score=c["percival_score"], band=c["band"], status=c["status"], components=c["components"],
                reasons=c.get("reasons"), provenance=rec.get("provenance"), ledger=os.path.relpath(glob.glob(PG.P("ledger", SID, "*.json"))[0], B))
step(9, "Percival Score (+ component predictions, provenance, ledger)", s9)
def s14():
    PG.CTX["SET"]["percival_test_fraction"] = 0.25; PG._train("trace second cycle"); v2 = PG.versions()[-1]
    PG._shadow(v2); S = json.load(open(PG.P("shadow", v2, "summary.json")))
    return dict(shadow_version=v2, active=PG.active_version(), compared=S["compared"], band_agreement=S["band_agreement"], prospective_n=S["prospective"]["n"],
                active_unchanged=PG.active_version() != v2)
step(14, "Percival shadow mode (candidate model, never deployed)", s14)
def s15():
    v2 = PG.versions()[-1]; M = PG.load(v2); st = PG.status_all()
    r = PG.promote(v2, by="trace", why="trace: research use (synthetic)", override=True); rb = PG.rollback(by="trace"); st2 = PG.status_all()
    reg = {x["version"]: x for x in PG.registry()}; runs = PG.runs()
    ok = r["ok"] and rb["ok"] and st2["v001"]["status"] == "active" and st2[v2]["status"] == "retired" and len(runs) == 2 and all(x["state"] == "finished" for x in runs)
    return dict(version=v2, status_after_training=st[v2]["status"], acceptance=M["acceptance"], promoted_then_rolled_back=bool(r["ok"] and rb["ok"]),
                status_now={k: x["status"] for k, x in st2.items()}, registry_entry={k: reg[v2][k] for k in ("id", "dataset", "feature_schema", "artifact", "run")},
                runs=[(x["id"], x["state"], x.get("version"), x.get("dataset")) for x in runs], _status="functional" if ok else "broken")
step(15, "Validation / registry status / explicit promotion / rollback / run records", s15)
if OUT: json.dump(dict(project=B, trace=TR), open(OUT, "w"), indent=1, default=str)
shutil.rmtree(T, ignore_errors=True)
nb = sum(1 for t in TR if t["status"] == "broken"); print("trace done:", nb, "broken steps")
sys.exit(1 if nb else 0)
