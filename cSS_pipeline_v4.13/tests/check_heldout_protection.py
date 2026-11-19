"""check_heldout_protection.py - negative tests for held-out label protection (cycle-2 audit). Synthetic SYN base only; the
held-out evaluation itself is exercised only where a refusal is expected, except one authorized synthetic call that proves the
boundary still opens when every condition holds. No real data.
usage: python tests/check_heldout_protection.py   (exit 1 on any FAIL)"""
import os, sys, json, glob, re, shutil, tempfile, csv
H = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(H)
sys.path[:0] = [H, os.path.join(ROOT, "unified_score")]
import numpy as np
from uscore import common as cm, pipeline as pl, model as md
import uscore_synthbase as sb

FAILS = []
def check(n, ok, info=""):
    print(f"{'PASS' if ok else 'FAIL'}  {n}  {info}"); (None if ok else FAILS.append(n))
def raises(fn, exc=cm.HeldOutAccessError):
    try: fn(); return False
    except exc: return True

B = tempfile.mkdtemp(prefix="uscore_ho_"); man = sb.write_base(B, n_dev=5, n_ho=3)
C = cm.Cohort(man, eligible_prefix="SYN", synthetic_test=True); out = os.path.join(B, "uscore"); dev, ho = C.studies("development"), C.studies("held-out")
for s in dev + ho: pl.extract_study(B, s, C, out, do_perturb=False)

# 1 static: the private reader is referenced only by the boundary
refs = []
for f in glob.glob(os.path.join(ROOT, "unified_score", "**", "*.py"), recursive=True) + glob.glob(os.path.join(ROOT, "app", "*.py")):
    t = open(f).read()
    for m in re.finditer(r"_read_calls|load_calls|match_calls", t):
        refs.append((os.path.relpath(f, ROOT), t[:m.start()].count("\n") + 1, m.group(0)))
bad = [r for r in refs if not (r[0].endswith("uscore/common.py"))]
check("static: no code outside uscore/common.py references the label reader (_read_calls / load_calls / match_calls)", not bad, str(bad))
common_src = open(os.path.join(ROOT, "unified_score", "uscore", "common.py")).read()
check("static: _read_calls is called only inside LabelAccess.labels", common_src.count("_read_calls(") == 2, f"{common_src.count('_read_calls(')} occurrences (def + one call)")

# 2 development boundary refuses every held-out study, and logs the refusal
LA = cm.LabelAccess(C, B, mode="development", log_dir=out)
for s in ho: check(f"development boundary refuses held-out {s}", raises(lambda s=s: LA.labels(s, None)))
log = open(f"{out}/label_access_log.csv").read().splitlines()
check("refusals are logged with granted=0", all(l.endswith(",0") for l in log[1:] if l.split(",")[1] in ho) and any(l.split(",")[1] in ho for l in log[1:]))

# 3 training reads development labels only (spy on the private reader)
seen = []; real = cm._read_calls
cm._read_calls = lambda base, sid, tab: (seen.append(sid), real(base, sid, tab))[1]
try: M1, _ = pl.train(B, C, out)
finally: cm._read_calls = real
check("training: labels read for development studies only", set(seen) == set(dev), f"read {sorted(set(seen))}")
check("training refuses a held-out-mode boundary", raises(lambda: pl.train(B, C, out, labels_access=type("X", (), {"mode": "heldout_evaluation"})()), cm.CohortError))

# 4 held-out labels cannot influence development: flip every held-out label, retrain -> identical model
for s in ho:
    p = f"{B}/review/{s}_calls.csv"; rows = list(csv.DictReader(open(p)))
    for r in rows: r["call"] = "Vessel" if r["call"] == "cSS" else "cSS"
    with open(p, "w", newline="") as f: w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
M2, _ = pl.train(B, C, os.path.join(B, "uscore_flip")) if False else (None, None)
out2 = os.path.join(B, "uscore_flip"); shutil.copytree(f"{out}/features", f"{out2}/features")
M2, _ = pl.train(B, C, out2)
check("flipping every held-out label leaves the trained model identical (same hash)", M1["model_hash"] == M2["model_hash"])

# 5 freezing and the held-out boundary
fz = pl.freeze(out, "FREEZE"); mf = f"{out}/model_frozen.json"; Hh = fz["model_hash"]
check("recomputed hash of the frozen model equals the stored hash", md.model_hash(json.load(open(mf))) == Hh)
check("held-out mode without the authorization file is refused (hash alone is not enough)", raises(lambda: cm.LabelAccess(C, B, "heldout_evaluation", mf, Hh, out)))
auth = f"{out}/heldout_authorization.json"
json.dump(dict(model_hash=Hh, authorized_by="test", date="2026-11-19", statement="I agree"), open(auth, "w"))
check("altered authorization statement is refused", raises(lambda: cm.LabelAccess(C, B, "heldout_evaluation", mf, Hh, out)))
json.dump(dict(model_hash="0" * 64, authorized_by="test", date="2026-11-19", statement=cm.HELDOUT_STATEMENT), open(auth, "w"))
check("authorization for another model is refused", raises(lambda: cm.LabelAccess(C, B, "heldout_evaluation", mf, Hh, out)))
json.dump(dict(model_hash=Hh, authorized_by="", date="2026-11-19", statement=cm.HELDOUT_STATEMENT), open(auth, "w"))
check("authorization without a name is refused", raises(lambda: cm.LabelAccess(C, B, "heldout_evaluation", mf, Hh, out)))
json.dump(dict(model_hash=Hh, authorized_by="test", date="2026-11-19", statement=cm.HELDOUT_STATEMENT), open(auth, "w"))
check("wrong hash given by the caller is refused", raises(lambda: cm.LabelAccess(C, B, "heldout_evaluation", mf, "1" * 64, out)))
# tampered model: change a coefficient but keep the stored hash -> the recomputed hash differs
M = json.load(open(mf)); keep = json.dumps(M); M["beta"][1] += 0.5; json.dump(M, open(mf, "w"))
check("edited model file with its old stored hash is refused (hash recomputed from content)", raises(lambda: cm.LabelAccess(C, B, "heldout_evaluation", mf, Hh, out)))
open(mf, "w").write(keep)
# unfrozen model
M = json.loads(keep); M["frozen"] = False; json.dump(M, open(mf, "w"))
check("unfrozen model is refused", raises(lambda: cm.LabelAccess(C, B, "heldout_evaluation", mf, Hh, out)))
open(mf, "w").write(keep)
# model trained on a held-out study
M = json.loads(keep); M["train_studies"] = M["train_studies"] + [ho[0]]; M["model_hash"] = md.model_hash(M); json.dump(M, open(mf, "w"))
check("model trained on a held-out study is refused (even with a consistent hash)", raises(lambda: cm.LabelAccess(C, B, "heldout_evaluation", mf, M["model_hash"], out)))
open(mf, "w").write(keep)
# swapped after authorization
LA_ok = cm.LabelAccess(C, B, "heldout_evaluation", mf, Hh, out)
M = json.loads(keep); M["beta"][2] -= 0.3; M["model_hash"] = md.model_hash(M); json.dump(M, open(mf, "w"))
check("model swapped after authorization: the next label read is refused", raises(lambda: LA_ok.labels(ho[0], None)))
open(mf, "w").write(keep)
# the boundary still opens when everything holds (synthetic): authorized read succeeds
LA_ok = cm.LabelAccess(C, B, "heldout_evaluation", mf, Hh, out)
import pandas as pd
lab, _ = LA_ok.labels(ho[0], pd.read_csv(f"{B}/review/{ho[0]}_candidates.csv"))
check("with every condition met (synthetic), the boundary grants the read and logs it", len(lab) > 0 and open(f"{out}/label_access_log.csv").read().strip().endswith(",1"))
os.remove(auth)

# 6 no label content in the stored features / reports / export inputs
feat = "".join(open(f).read() for f in glob.glob(f"{out}/features/*.json"))
check("feature files contain no reader-call field", '"call"' not in feat and "_calls" not in feat)
pl.score(C, out, dev + ho); rep = open(f"{out}/reports/candidates.json").read()
check("candidate reports contain no reader-call field", '"call"' not in rep)
check("development report OOF table holds development studies only",
      {o["study"] for o in json.load(open(f"{out}/development_report.json"))["oof"]} <= set(dev))
# 7 the GUI back end has no held-out route
src = open(os.path.join(ROOT, "app", "css_app.py")).read().split("def unified_post")[1].split("def last_activity")[0]
check("app: no held-out operation in the Unified routes", "heldout" not in src and "evaluate_heldout" not in open(os.path.join(ROOT, "app", "unified_gui.py")).read())
shutil.rmtree(B, ignore_errors=True)
print(f"\nheld-out protection: {len(FAILS)} FAIL")
sys.exit(1 if FAILS else 0)
