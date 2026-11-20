"""check_uscore_pipeline.py - guards, model mechanics, leakage, and end-to-end pipeline on a SYNTHETIC base (SYN studies).
Synthetic mechanics only; no number here is a performance result. usage: python tests/check_uscore_pipeline.py (exit 1 on FAIL)"""
import os, sys, json, glob, hashlib, tempfile, shutil
H = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(H)
sys.path[:0] = [H, os.path.join(ROOT, "unified_score")]
import numpy as np
from uscore import common as cm, model as md, pipeline as pl, decision as dc

FAILS = []
def check(name, ok, info=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {info}"); (None if ok else FAILS.append(name))
def raises(fn, exc):
    try: fn(); return False
    except exc: return True

# ---------- 1 cohort guards on the REAL reconciled manifest
C = cm.Cohort()
check("1 real manifest (2026-11-20 split): 26 development M01-M26, 10 held-out M27-M36, only M", len(C.studies("development")) == 26 and len(C.studies("held-out")) == 10
      and all(s.startswith("M") for s in C.studies("development") + C.studies("held-out")))
check("1 P006 refused", raises(lambda: C.role("P006"), cm.CohortError))
check("1 PH6 refused", raises(lambda: C.role("PH6"), cm.CohortError))
check("1 T05 refused", raises(lambda: C.role("T05"), cm.CohortError))
check("1 M27 / M31 / M36 listed as held-out; M18 / M23 now development (2026-11-20 split)", all(C.role(s) == "held-out" for s in ("M27", "M31", "M36")) and all(C.role(s) == "development" for s in ("M18", "M23")))
check("1 fitting on a held-out study refused", raises(lambda: C.check_fit_set(["M02", "M27"]), cm.CohortError))
check("1 non-M prefix refused outside synthetic test mode", raises(lambda: cm.Cohort(eligible_prefix="SYN"), cm.CohortError))
check("1 synthetic mode may not use M", raises(lambda: cm.Cohort(eligible_prefix="M", synthetic_test=True), cm.CohortError))
tmp = tempfile.mkdtemp(); bad = os.path.join(tmp, "bad.csv")
open(bad, "w").write("study_id,starts_with_M,decision,role,exclusion_reason\nP006,no,include,development,\n")
check("1 manifest including a non-M study refused", raises(lambda: cm.Cohort(bad), cm.CohortError))

# ---------- 2 label access
LA = cm.LabelAccess(C, tmp, mode="development", log_dir=tmp)
check("2 held-out labels refused in development mode", raises(lambda: LA.labels("M27", None), cm.HeldOutAccessError))
log = open(os.path.join(tmp, "label_access_log.csv")).read()
check("2 refused access is logged", "M27" in log and log.strip().endswith(",0"))
check("2 held-out mode without frozen model refused", raises(lambda: cm.LabelAccess(C, tmp, mode="heldout_evaluation"), cm.HeldOutAccessError))

# ---------- 3 model mechanics
rng = np.random.default_rng(1)
def rows_from(X): return [dict(F={k: dict(value=float(v), status="reliable") for k, v in zip(cm.PREDICTORS, x)}) for x in X]
X = rng.normal(size=(300, 5)); yv = (rng.random(300) < md.sigmoid(2 * X[:, 0] - 1.5 * X[:, 1])).astype(float)
R = rows_from(X); pid = np.repeat([f"P{i}" for i in range(10)], 30)
e1 = md.fit(R, yv, cm.PREDICTORS, 0.01).edf; e2 = md.fit(R, yv, cm.PREDICTORS, 100.0).edf
check("3 effective df <= 6 and decreases with the penalty", e1 <= 6 + 1e-6 and e2 < e1, f"edf {e1:.2f} -> {e2:.2f}")
m = md.fit(R, yv, cm.PREDICTORS, 0.1)
check("3 coefficient directions recovered", m.beta[1] > 0 and m.beta[2] < 0, f"beta {np.round(m.beta, 2)}")
Ru = [dict(F={k: (dict(value=None, status="unavailable") if k == "x1_vessel_continuity_mm" else v) for k, v in r["F"].items()}) for r in R[:5]]
con = m.contributions(Ru[0])
check("3 unavailable predictor contributes exactly 0 (never evidence)", con["x1_vessel_continuity_mm"]["contribution"] == 0 and con["x1_vessel_continuity_mm"]["imputed"])
Rr = [dict(F={k: (dict(value=-50.0, status="unreliable") if k == "x1_vessel_continuity_mm" else v) for k, v in r["F"].items()}) for r in R[:5]]
check("3 unreliable predictor value ignored (same score as unavailable)", np.allclose(m.p_raw(Rr), m.p_raw(Ru)))
check("3 AUC of a perfect score = 1, inverted = 0", md.auc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]) == 1.0 and md.auc([0, 0, 1, 1], [0.9, 0.8, 0.2, 0.1]) == 0.0)
lg = []; p = md.choose_predictors(np.r_[np.ones(30), np.zeros(200)], lg)
check("3 fallback: 30 events -> x4 dropped (30/4 < 10 -> x5 too)", p == cm.PREDICTORS[:3], f"{p} {lg}")
check("3 fallback: 61 events keeps all five", md.choose_predictors(np.r_[np.ones(61), np.zeros(200)], []) == cm.PREDICTORS)

# ---------- 4 nested LOPO leakage: the outer patient's labels must not change its own predictions
yv2 = yv.copy(); k = pid == "P3"; yv2[k] = 1 - yv2[k]
a = md.nested_lopo(R, yv, pid, cm.PREDICTORS); b = md.nested_lopo(R, yv2, pid, cm.PREDICTORS)
check("4 no leakage: flipping patient P3's labels leaves P3's calibrated predictions unchanged", np.allclose(a[1][k], b[1][k]))
check("4 ...and changes other patients' predictions (labels are used for training)", not np.allclose(a[1][~k], b[1][~k]))
check("4 penalty chosen per outer fold from training patients", len(a[2]) == 10 and all("lam" in f for f in a[2]))

# ---------- 5 end-to-end on a synthetic base
import uscore_synthbase as sb
B = tempfile.mkdtemp(prefix="uscore_synbase_"); man = sb.write_base(B)
S = cm.Cohort(man, eligible_prefix="SYN", synthetic_test=True); out = os.path.join(B, "uscore")
def tree_hash(d):
    h = hashlib.sha256()
    for f in sorted(glob.glob(f"{d}/**/*", recursive=True)):
        if os.path.isfile(f): h.update(f.encode()); h.update(open(f, "rb").read())
    return h.hexdigest()
before = {d: tree_hash(f"{B}/{d}") for d in ("review", "data", "work", "raw")}
for s in S.studies("development") + S.studies("held-out"): pl.extract_study(B, s, S, out)
check("5 refuses an excluded / real study id", raises(lambda: pl.extract_study(B, "M02", S, out), cm.CohortError))
M, rep = pl.train(B, S, out)
check("5 training does NOT freeze", not M["frozen"] and not os.path.exists(f"{out}/model_frozen.json"))
check("5 freeze refused without the confirmation text", raises(lambda: pl.freeze(out, "yes"), ValueError))
fz = pl.freeze(out, "FREEZE"); M = json.load(open(f"{out}/model_frozen.json"))
check("5 model trained on development studies only", set(M["train_studies"]) == set(S.studies("development")))
log = open(f"{out}/label_access_log.csv").read()
check("5 development training read no held-out label", not any(h in log for h in S.studies("held-out")))
check("5 model frozen with a hash", M["frozen"] and len(M["model_hash"]) == 64 and fz["model_hash"] == M["model_hash"])
reps = pl.score(S, out, S.studies("development") + S.studies("held-out"))
n_cand = sum(len(json.load(open(f"{out}/features/{s}.json"))["records"]) for s in S.studies("development") + S.studies("held-out"))
check("5 every candidate has a report (none dropped)", len(reps) == n_cand == 4 * 9, f"{len(reps)} / {n_cand}")
check("5 every report is stamped synthetic", all(r["synthetic_test"] for r in reps))
cats = {r["category"] for r in reps}; print("INFO  5 categories:", {c: sum(r["category"] == c for r in reps) for c in cats})
need = ("predictors", "contributions", "positive_evidence", "negative_evidence", "alternative_detectors", "stability", "category",
        "category_reasons", "model_version", "feature_version", "model_hash")
check("5 report fields complete", all(all(k in r for k in need) for r in reps))
check("5 probability withheld when not justified", all((r["probability"] is None) == (not M["probability_output"]) for r in reps))
aud = dc.suppressed_view(f"{out}/suppression_audit.jsonl")
check("5 suppression never applied", all(a["action"].startswith("not_applied") for a in aud), f"{len(aud)} audit records")
check("5 audit records carry model hash, input hash, reliability", all(a["model_hash"] == M["model_hash"] and a["input_hash"] and a["feature_reliability"] for a in aud))
check("5 production-layout inputs unchanged (review/ data/ work/ raw/)", all(tree_hash(f"{B}/{d}") == before[d] for d in before))
check("5 held-out evaluation refused with a wrong hash", raises(lambda: pl.evaluate_heldout(B, S, out, "0" * 64), cm.HeldOutAccessError))
check("5 held-out refused with the right hash but NO written authorization", raises(lambda: pl.evaluate_heldout(B, S, out, M["model_hash"]), cm.HeldOutAccessError))
json.dump(dict(model_hash=M["model_hash"], authorized_by="test", date="2026-11-19", statement="ok"), open(f"{out}/heldout_authorization.json", "w"))
check("5 held-out refused with an altered authorization statement", raises(lambda: pl.evaluate_heldout(B, S, out, M["model_hash"]), cm.HeldOutAccessError))
json.dump(dict(model_hash=M["model_hash"], authorized_by="test", date="2026-11-19", statement=pl.HELDOUT_STATEMENT), open(f"{out}/heldout_authorization.json", "w"))
ho = pl.evaluate_heldout(B, S, out, M["model_hash"])
check("5 held-out evaluation runs with the frozen hash and is labelled independent", ho["estimate_type"].startswith("INDEPENDENT"), f"n {ho['n']}")
check("5 held-out access logged as granted only in held-out mode",
      all(l.split(",")[3] == "heldout_evaluation" for l in open(f"{out}/label_access_log.csv").read().splitlines()[1:] if l.split(",")[2] == "held-out"))
# reproducibility
out2 = os.path.join(B, "uscore2")
for s in S.studies("development") + S.studies("held-out"): pl.extract_study(B, s, S, out2)
M2, _ = pl.train(B, S, out2)
check("5 reproducible: same model hash on a second run", M2["model_hash"] == M["model_hash"])
real = cm.Cohort()
check("5 synthetic model refused for real scoring", raises(lambda: pl.score(real, out, ["M02"]), cm.CohortError))
import csv
from uscore import report as rp
lab = {(r["study"], r["cand_id"]): None for r in reps}
for sid in S.studies("development") + S.studies("held-out"):
    for c in csv.DictReader(open(f"{B}/review/{sid}_calls.csv")): lab[(sid, int(c["cand_id"]))] = c["call"]
bad = [k for r in reps for k in [(r["study"], r["cand_id"])] if lab.get(k) == "cSS" and r["category"] == "alternative_high_confidence"]
check("5 CRITICAL: no reader-cSS candidate is a high-confidence alternative", not bad, str(bad))
rpt = rp.cohort_report(out); txt = open(rpt).read()
check("5 cohort report written, marked synthetic, development and held-out sections separate",
      "SYNTHETIC TEST" in txt and "Development estimates" in txt and "Independent held-out" in txt)
shutil.copy(rpt, os.path.join(ROOT, "unified_score", "output", "COHORT_REPORT_SYNTHETIC_TEST.md"))
json.dump(reps[:3], open(os.path.join(ROOT, "unified_score", "output", "example_candidate_reports_SYNTHETIC.json"), "w"), indent=1, default=str)
n_log0 = len(open(f"{out}/label_access_log.csv").read().splitlines())
ap = pl.score_application(B, "SYN01", real, out)
check("6 app step: patient outside the study cohort scored for display", ap["n"] == 4 and ap["study"] == "SYN01", str(ap))
check("6 app step: a synthetic model is never used to score a real cohort", ap["model"] is False)
check("6 app step: no label read", len(open(f"{out}/label_access_log.csv").read().splitlines()) == n_log0)
check("6 app step: report file written", os.path.exists(f"{out}/reports/SYN01.json"))
check("6 app step: training still refuses non-cohort studies", raises(lambda: real.check_fit_set(["SYN01"]), cm.CohortError))
shutil.rmtree(B); shutil.rmtree(tmp)
print(f"\nuscore pipeline: {len(FAILS)} FAIL")
sys.exit(1 if FAILS else 0)
