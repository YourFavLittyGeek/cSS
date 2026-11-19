"""rc2b: production confidence + ranking models restored in the experimental project (synthetic data, real detector, real app).
Checks: byte-for-byte copy with sha256 verification; production files untouched; E30 + confidence_pct reproduced; ranking only for
'dev' studies; PARITY: the same study detected the production way (scripts in a copy of the production project) and through the app
gives identical candidate / excluded lists; missing and incompatible models reported (never claimed as parity)."""
import os, sys, json, glob, shutil, socket, hashlib, tempfile, subprocess, time, urllib.request
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..")); sys.path.insert(0, os.path.join(ROOT, "tests")); sys.path.insert(0, os.path.join(ROOT, "scripts"))
import uscore_synthbase as sb, css_confidence as cc
F = []
def ok(c, m): print(("PASS " if c else "FAIL ") + m, flush=True); c or F.append(m)
H = tempfile.mkdtemp(prefix="pm_models_"); P = f"{H}/css_project"; X = f"{H}/cSS_experimental"
sb.write_base(P, n_dev=2, n_ho=1)                                        # SYN01, SYN02 (+ SYN03)
for s in ("SYN01", "SYN02", "SYN03"):
    os.makedirs(f"{P}/synthseg", exist_ok=True); shutil.copy(f"{P}/work/{s}_seg_swispace.nii.gz", f"{P}/synthseg/{s}_seg.nii.gz")
for d in ("scripts", "unified_score"): shutil.copytree(f"{ROOT}/{d}", f"{P}/{d}", ignore=shutil.ignore_patterns("__pycache__", "output"))
# production models (synthetic): confidence model with a lopo_min cut that excludes low-confidence objects; ranking model on 2 detector columns
n = len(cc.FEATURES); w = [0.0] * n; w[cc.FEATURES.index("log_volume")] = 3.0
conf = dict(schema=cc.SCHEMA, features=cc.FEATURES, med=[0.0] * n, mu=[0.0] * n, sd=[1.0] * n, w=w, b=-14.2, l2=1.0, cut_pct=50.0, cut_method="lopo_min", studies=["SYN99"])
rank = dict(features=["score_v4", "css_evidence"], mean=[1.0, 0.5], sd=[1.0, 0.2], weights=[1.0, 0.5], bias=0.0, impute_median=[1.0, 0.5],
            training_studies=["SYN99"], detector_builds=[], fitted_at="synthetic", n_patients=2, lopo_auc=None)
json.dump(conf, open(f"{P}/review/confidence_model.json", "w")); json.dump(rank, open(f"{P}/review/ranker_model.json", "w"))
os.makedirs(f"{P}/labels"); open(f"{P}/labels/study_meta.csv", "w").write("study_id,status,split\nSYN01,pos,dev\nSYN02,neg,test\nSYN03,pos,dev\n")
PENV = dict(os.environ, CSS_V53="1", CSS_ZONE2="1", CSS_CONF="1", NOVIEW="1")
def tree(B): return {p: (hashlib.sha256(open(p, "rb").read()).hexdigest(), os.stat(p).st_mtime) for p in glob.glob(f"{B}/**/*", recursive=True) if os.path.isfile(p) and "__pycache__" not in p}
# reference: the PRODUCTION way, in a copy of the production project (run_css.sh steps [3/4] + [3c] for dev studies)
REF = f"{H}/prod_reference"; shutil.copytree(P, REF)
for s in ("SYN01", "SYN02"):
    subprocess.run([sys.executable, f"{REF}/scripts/detect_css.py", s, "-2.5", "85", "3"], env=dict(PENV, CSS_BASE=REF), capture_output=True, timeout=900)
subprocess.run([sys.executable, f"{REF}/scripts/rank_candidates.py", "SYN01"], env=dict(PENV, CSS_BASE=REF), capture_output=True, timeout=300)   # dev split
before = tree(P)
# RC2: experimental project through the real app
os.makedirs(X); shutil.copytree(f"{ROOT}/scripts", f"{X}/scripts", ignore=shutil.ignore_patterns("__pycache__")); shutil.copytree(f"{ROOT}/unified_score", f"{X}/unified_score", ignore=shutil.ignore_patterns("__pycache__", "output"))
s_ = socket.socket(); s_.bind(("127.0.0.1", 0)); port = s_.getsockname()[1]; s_.close()
app = subprocess.Popen([sys.executable, f"{ROOT}/app/css_app.py", "--port", str(port), "--no-window"],
                       env=dict(os.environ, HOME=H, CSS_BASE=X, CSS_EXPERIMENTAL="1", PYTHONPATH=f"{ROOT}/app/guard"), stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
U = f"http://127.0.0.1:{port}"
get = lambda p: json.load(urllib.request.urlopen(U + p, timeout=60))
def post(p, d):
    rq = urllib.request.Request(U + p, data=json.dumps(d).encode(), headers={"Content-Type": "application/json", "X-CSS-App": "1"})
    return json.load(urllib.request.urlopen(rq, timeout=600))
def run(code):
    post("/api/proc/adopt", dict(code=code)); r = post("/api/proc/start", dict(code=code, choice="selective", rerun_from="detect"))
    for _ in range(1200):
        if not get(f"/api/proc/audit?code={code}").get("busy"): break
        time.sleep(0.5)
    return r, get(f"/api/proc/history?code={code}")["runs"][-1]
try:
    for _ in range(100):
        try: urllib.request.urlopen(U + "/", timeout=2); break
        except Exception: time.sleep(0.2)
    ok(not any(m["present"] for m in get("/api/proc/models")["models"].values()), "before import: no model in the experimental project (reported as not present)")
    r = post("/api/proc/link", dict(source=P, codes=["SYN01", "SYN02"]))
    ok(r["ok"] and all(m["parity"] for m in r["models"].values()), f"import: both models copied and verified ({r['models']})")
    rec = json.load(open(f"{X}/review/production_models.json"))["models"]
    for nm in ("confidence_model.json", "ranker_model.json"):
        ok(rec[nm]["source_sha256"] == rec[nm]["destination_sha256"] == hashlib.sha256(open(f"{P}/review/{nm}", "rb").read()).hexdigest()
           and open(f"{P}/review/{nm}", "rb").read() == open(f"{X}/review/{nm}", "rb").read(), f"{nm}: byte-for-byte identical, source and destination sha256 recorded and equal")
    ms = get("/api/proc/models")["models"]; ok(all(m["compatible"] and m["verified_copy_of_production"] for m in ms.values()), "both models: compatible + verified copy of production")
    imp = json.load(open(f"{X}/runs/SYN01/import.json")); ok(imp["production_split"]["split"] == "dev" and json.load(open(f"{X}/runs/SYN02/import.json"))["production_split"]["split"] == "test",
                                                            "production split recorded at import (SYN01 dev, SYN02 test)")
    for code in ("SYN01", "SYN02"):
        r0, last = run(code); ok(last["status"] == "completed", f"{code}: new detection run completed")
        lg = get(f"/api/proc/log?code={code}&run_id={last['run_id']}")["log"]
        ok("verified copy of the production model, compatible" in lg, f"{code}: run log names the production models in force")
        a = pd.read_csv(f"{X}/review/{code}_candidates.csv"); b = pd.read_csv(f"{REF}/review/{code}_candidates.csv")
        ok(a["confidence_pct"].notna().all() and len(a), f"{code}: confidence_pct computed for every candidate")
        cols = [c for c in b.columns if c in a.columns]
        ok(len(a) == len(b) and a[cols].round(4).equals(b[cols].round(4)), f"{code}: PARITY - candidate list identical to the production-way run ({len(a)} candidates, {len(cols)} columns)")
        xa, xb = f"{X}/review/{code}_excluded.csv", f"{REF}/review/{code}_excluded.csv"
        ea = pd.read_csv(xa) if os.path.exists(xa) else pd.DataFrame(); eb = pd.read_csv(xb) if os.path.exists(xb) else pd.DataFrame()
        ok(len(ea) == len(eb) and (ea.get("reason", pd.Series(dtype=str)).astype(str).tolist() == eb.get("reason", pd.Series(dtype=str)).astype(str).tolist()),
           f"{code}: PARITY - excluded objects and their rules identical ({len(ea)}; E30: {sum(ea.get('rule_version', pd.Series(dtype=str)).astype(str).str.startswith('E30'))})")
        ok(ea.get("rule_version", pd.Series(dtype=str)).astype(str).tolist() == eb.get("rule_version", pd.Series(dtype=str)).astype(str).tolist(), f"{code}: PARITY - exclusion rule ids identical")
        if code == "SYN01": ok("score_model" in a.columns and "[3c] trained ranking model" in lg, "SYN01 (dev): ranking model applied, as in production")
        else: ok("score_model" not in a.columns and "split is 'test'" in lg, "SYN02 (test): ranking model NOT applied, as in production")
    ok(any(str(x).startswith("E30") for x in pd.read_csv(f"{REF}/review/SYN01_excluded.csv")["rule_version"]) and any(str(x).startswith("E30") for x in pd.read_csv(f"{X}/review/SYN01_excluded.csv")["rule_version"]) if os.path.exists(f"{REF}/review/SYN01_excluded.csv") else False,
       "E30 exercised in BOTH runs (production way and RC2): a low-confidence object is excluded")
finally: app.terminate(); app.wait()
ok(tree(P) == before, "production project untouched (models, labels, every file: content + modification time)")
# missing / incompatible models: reported, never claimed as parity
sys.path.insert(0, os.path.join(ROOT, "app")); import processing_manager as pm
P2, X2 = tempfile.mkdtemp(), tempfile.mkdtemp(); os.makedirs(f"{P2}/review"); shutil.copytree(f"{ROOT}/scripts", f"{X2}/scripts", ignore=shutil.ignore_patterns("__pycache__"))
r = pm.import_production_models(P2, X2)
ok(all(v["parity"] is False and "missing" in v["status"] for v in r.values()), "models missing in the source: reported, parity False")
st = pm.models_status(X2); ok(not any(v["present"] for v in st.values()), "missing models shown as not present")
bad = dict(conf, features=cc.FEATURES[:-1]); json.dump(bad, open(f"{P2}/review/confidence_model.json", "w"))
json.dump(dict(rank, weights=[1.0]), open(f"{P2}/review/ranker_model.json", "w"))
r = pm.import_production_models(P2, f"{X2}x") if False else None
X3 = tempfile.mkdtemp(); shutil.copytree(f"{ROOT}/scripts", f"{X3}/scripts", ignore=shutil.ignore_patterns("__pycache__")); r = pm.import_production_models(P2, X3)
ok(r["confidence_model.json"]["parity"] is False and "INCOMPATIBLE" in r["confidence_model.json"]["status"], "confidence model with a different feature list: INCOMPATIBLE, parity False")
ok(r["ranker_model.json"]["parity"] is False and "INCOMPATIBLE" in r["ranker_model.json"]["status"], "ranking model with inconsistent weights: INCOMPATIBLE, parity False")
json.dump(conf, open(f"{P2}/review/confidence_model.json", "w")); r = pm.import_production_models(P2, X3)
ok("CONFLICT" in r["confidence_model.json"]["status"] and r["confidence_model.json"]["parity"] is False, "a changed production model is not overwritten silently: CONFLICT reported")
print("ALL PASS" if not F else f"{len(F)} FAILED"); sys.exit(1 if F else 0)
