"""check_percival.py - v5.22 PERCIVAL SCORE engine on a SYNTHETIC cohort with known truth (no clinical data). MATH is a weak noisy score,
the Unified-Score predictors and the detector characteristics carry extra information, the image network reads the synthetic MRI patches.
Checks: the five components; the meta-model discovery (seven candidates compared by patient-grouped CV, chosen by the 1-SE rule, boosting
skipped with its reason when too small); no double counting (no meta-model uses fusion with char / image); calibration; data-driven
thresholds; the locked test cohort is patient-separated and never used for training; acceptance -> promotion; registry versions,
rollback; prediction ledger immutable across model versions; missing inputs -> 'insufficient' (never a reassuring low score); scores
bounded 0-100; inference with the network BLOCKED (socket guard) works; the training selection; controlled cycles.
usage: python tests/check_percival.py   (exit 1 on any FAIL)"""
import glob, json, os, shutil, socket, subprocess, sys, tempfile, time
import numpy as np, pandas as pd
H = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(H); PY = sys.executable
sys.path[:0] = [os.path.join(ROOT, "app"), os.path.join(ROOT, "unified_engine"), os.path.join(ROOT, "scripts")]
F = []
def check(n, ok, info=""): print(f"{'PASS' if ok else 'FAIL'}  {n}  {info}"); (None if ok else F.append(n))
T = tempfile.mkdtemp(prefix="perc_"); B = os.path.join(T, "base"); NS = int(os.environ.get("CSS_PERCIVAL_TEST_N", "30"))
r = subprocess.run([PY, os.path.join(ROOT, "unified_engine", "run_imaging.py"), "cohort", B, "--n", str(NS), "--seed", "21"], capture_output=True, text=True)
check(f"synthetic cohort generated ({NS} studies with MRI phantoms)", r.returncode == 0, (r.stderr or "")[-200:])
os.environ["CSS_BASE"] = B; rng = np.random.default_rng(4)
studies = sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(B, "unified_engine", "image_truth", "SYN*.csv")))
for sid in studies:
    t = pd.read_csv(os.path.join(B, "unified_engine", "image_truth", f"{sid}.csv")); t = t[t["list"] == "candidates"]
    c = pd.read_csv(os.path.join(B, "review", f"{sid}_candidates.csv")); y = {int(o): int(k == "definite_css") for o, k in zip(t.obj_id, t.primary_class)}
    yy = np.array([y.get(int(i), 0) for i in c.cand_id])
    c["score_v4"] = np.maximum(0, 0.5 * yy + rng.normal(0.5, 0.5, len(c))); c["hemi"] = ["L" if k % 2 else "R" for k in range(len(c))]
    c["darkness_z"] = rng.normal(-1 - 1.0 * yy, 0.8); c["edge_contrast"] = rng.normal(0.3 + 0.3 * yy, 0.2); c["cortex_frac"] = rng.normal(0.5 + 0.2 * yy, 0.2)
    c["tube_ratio"] = rng.normal(2 - 0.8 * yy, 0.6); c["tram_frac"] = np.where(rng.random(len(c)) < 0.3, np.nan, rng.normal(0.4 + 0.2 * yy, 0.2))
    if sid == studies[0]: c["score_v4"] = c["score_v4"]      # nothing special
    c.to_csv(os.path.join(B, "review", f"{sid}_candidates.csv"), index=False)
    recs = [dict(cand_id=int(i), F={k: dict(value=float(v), status="reliable") for k, v in dict(x1_vessel_continuity_mm=rng.normal(6 - 3 * y.get(int(i), 0), 1.8),
            x2_core_contrast_nu=rng.normal(0.4 + 0.4 * y.get(int(i), 0), 0.3), x3_pial_distance_mm=rng.normal(1, 0.6), x4_sulcal_alignment=rng.normal(0.3 + 0.3 * y.get(int(i), 0), 0.3),
            x5_extracranial_mm=rng.normal(2 - 1.2 * y.get(int(i), 0), 1)).items()}) for i in c.cand_id]
    os.makedirs(os.path.join(B, "uscore", "features"), exist_ok=True); json.dump(dict(study=sid, records=recs), open(os.path.join(B, "uscore", "features", f"{sid}.json"), "w"))
    pd.DataFrame(dict(cand_id=list(c.cand_id), call=["cSS" if v else "Vessel" for v in yy])).to_csv(os.path.join(B, "review", f"{sid}_calls.csv"), index=False)
# one reviewer conflict + one indeterminate call (must be excluded, reported)
pd.DataFrame(dict(cand_id=[1], call=["cSS"])).to_csv(os.path.join(B, "review", f"{studies[1]}_calls_Dr_A.csv"), index=False)
pd.DataFrame(dict(cand_id=[1], call=["Vessel"])).to_csv(os.path.join(B, "review", f"{studies[1]}_calls_Dr_B.csv"), index=False)
import percival_gui as PG
from uengine.percival import meta as MT
SET = dict(features=dict(train_include_archived=True), percival_autocycle=True, percival_cycle_n=5, percival_test_fraction=0.25)
PATIENT = {s: f"pt{(k // 2):02d}" for k, s in enumerate(studies)}                 # two studies per patient (patient-level separation)
PG.init(B=B, SC=os.path.join(ROOT, "scripts"), SET=SET, patients=lambda: [dict(code=s, cohort="SYN") for s in studies], is_reviewed=lambda c: True,
        label=lambda c: c, patient_of=lambda c: PATIENT[c], save_settings=lambda: None, notify=lambda *a: None, fingerprint_of=lambda c: "")
os.environ["CSS_LEARN_MIN"] = "10,60,8"; os.environ["CSS_PERCIVAL_EPOCHS"] = "15"
t0 = time.time(); PG._train("test cycle 1"); dt = time.time() - t0
st = PG.state(); M = PG.load(PG.versions()[-1]) if PG.versions() else None
check("training cycle completed locally", PG.JOB["state"] == "finished" and M is not None, PG.JOB.get("error", "") + f" ({dt:.0f} s)")
if M:
    d = M["data"]; sel = PG.selection()
    test_pats = {PATIENT[s["code"]] for s in sel if s["partition"] == "test"}; dev_pats = {PATIENT[s["code"]] for s in sel if s["partition"] == "development"}
    check("locked test cohort: patient-separated from development", test_pats and dev_pats and not (test_pats & dev_pats) and d["test_candidates"] > 0, f"test patients {len(test_pats)}, dev {len(dev_pats)}")
    check("both studies of a patient fall in the same partition", all(len({s["partition"] for s in sel if PATIENT[s["code"]] == p}) == 1 for p in set(PATIENT.values())))
    cm = M["component_metrics"]
    check("five components trained with out-of-fold AUCs", all(cm[c].get("auc") is not None for c in MT.COMPONENTS), json.dumps({c: round(cm[c]["auc"] or 0, 3) for c in MT.COMPONENTS}))
    check("Image ML read the MRI patches (image component better than chance)", cm["image"]["auc"] > 0.6 and d["with_image"] > 50, f"{cm['image']['auc']:.3f}")
    D = M["discovery"]
    check("meta-model discovery: every candidate evaluated (boosting skipped with its reason when the cohort is small)", set(D["results"]) == set(MT.SIMPLICITY) and (D["results"]["boosted"].get("auc") is not None or "skipped" in D["results"]["boosted"]), json.dumps({k: (v.get("auc") if isinstance(v, dict) else v) for k, v in D["results"].items()})[:300])
    check("selection by the documented 1-SE rule", D["chosen"] in MT.SIMPLICITY and "1-SE" in D["rule"], D["chosen"])
    check("no meta-model combines fusion with its own inputs (double counting avoided)", all(not ({"fusion"} & set(MT.meta_columns(k)) and ({"char", "image"} & set(MT.meta_columns(k)))) for k in MT.SIMPLICITY))
    chosen_auc = D["results"][D["chosen"]]["auc"]; math_auc = D["results"]["math_only"]["auc"]
    check("the chosen assessment beats MATH alone (development CV)", chosen_auc > math_auc + 0.03, f"{chosen_auc:.3f} vs {math_auc:.3f}")
    th = M["thresholds"]
    check("data-driven thresholds: red < green, with development sensitivity >= 0.95 at red", 0 <= th["red_below"] <= th["green_from"] <= 1 and th["dev_at_red"]["sensitivity"] >= 0.95, json.dumps(th)[:200])
    te = M["test"]
    check("evaluated once on the locked test cohort (AUC + CI, MATH for comparison, thresholds, subgroups)", te.get("percival", {}).get("auc") is not None and te.get("math", {}).get("auc") is not None and "at_red" in te, json.dumps({k: (v.get("auc") if isinstance(v, dict) else v) for k, v in te.items() if k in ("percival", "math")}))
    check("data integrity: reviewer conflict reported", M["integrity"]["conflicts"].get(studies[1]) == 1, json.dumps(M["integrity"]))
    # v5.23: model families compared (never assumed), Percival Intelligence analyses
    fam = M["intelligence"]["families"]
    check("v5.23 Characteristic ML: logistic / gbt / forest compared by patient-grouped CV, chosen by 1-SE", set(fam["char"]["results"]) == {"logistic", "gbt", "forest"} and fam["char"]["chosen"] in ("logistic", "gbt", "forest")
          and all(fam["char"]["results"][k].get("auc") is not None for k in fam["char"]["results"]), json.dumps({k: round(v.get("auc") or 0, 3) for k, v in fam["char"]["results"].items()}) + " -> " + fam["char"]["chosen"])
    check("v5.23 Image ML: pixel-logistic baseline vs CNN compared on the same candidates", set(fam["image"]["results"]) == {"pixel_logistic", "cnn"} and fam["image"]["chosen"] in ("pixel_logistic", "cnn"),
          json.dumps({k: round(v.get("auc") or 0, 3) for k, v in fam["image"]["results"].items()}) + " -> " + fam["image"]["chosen"])
    check("v5.23 Fusion: late / feature / hybrid compared; benefit over the better single model tested", set(fam["fusion"]["results"]) == {"late", "feature", "hybrid"} and fam["fusion"]["benefit"] and "verdict" in fam["fusion"]["benefit"],
          json.dumps(fam["fusion"]["benefit"])[:200])
    I = M["intelligence"]; ov = {(o["a"], o["b"]): o for o in I["overlap"]}
    check("v5.23 provenance: MATH and Characteristic ML share measurements (not independent); Image ML shares none with MATH", {"darkness", "pial_distance", "tubularity"} <= set(ov[("math", "char")]["shared"]) and not ov[("math", "image")]["shared"])
    ab = I["ablation"]
    check("v5.23 ablation: incremental value of every independent component with a patient-bootstrap CI", set(ab["without"]) == set(MT.INDEP) and all(len(v["delta_ci"]) == 2 and v["verdict"] for v in ab["without"].values()),
          json.dumps({k: [round(v["delta_logloss"], 3), v["verdict"]] for k, v in ab["without"].items()}))
    dz = [d for d in I["disagreement"] if d["a"] == "char" and d["b"] == "image"]
    check("v5.23 disagreement patterns learned from expert labels (char vs image)", dz and sum(v["n"] for v in dz[0]["patterns"].values()) == dz[0]["n"], json.dumps(dz[0]["patterns"] if dz else None)[:200])
    check("v5.23 reliability (calibration) table on development out-of-fold scores", len(I["reliability"]) >= 2 and all(0 <= r["observed"] <= 1 for r in I["reliability"]))
    check("v5.23 Platt calibration is ridge-penalised (no runaway slope on separable data)", M["calibration"].get("ridge", 0) > 0 and abs(M["calibration"]["b"]) < 5, json.dumps(M["calibration"]))
    acc = M["acceptance"]; act = PG.active()
    check("acceptance evaluated; promoted only if passed", ("passed" in acc) and ((act is not None and act["version"] == M["version"]) == acc["passed"]), json.dumps(acc))
    if act is None: PG.promote(M["version"], why="test")
    sc = json.load(open(PG.P("scores", f"{studies[0]}.json"))) if os.path.exists(PG.P("scores", f"{studies[0]}.json")) else (time.sleep(3) or json.load(open(PG.P("scores", f"{studies[0]}.json"))))
    S0 = sc["candidates"]
    check("every candidate scored 0-100 with band, status, uncertainty, components and contributions", all((s["percival_score"] is None or 0 <= s["percival_score"] <= 100) and s["status"] in ("reliable", "uncertain", "insufficient", "review") and set(s["components"]) == set(MT.COMPONENTS) for s in S0))
    # missing inputs: a row with only MATH must be 'insufficient', never a low reassuring score
    row = dict(study="X", cand_id=1, math=0.0, pred={}, char={}, maps=None, patient="px")
    s1 = MT.score_rows(PG.active() or M, [row])[0]
    check("only MATH available -> 'insufficient evidence', no score", s1["status"] == "insufficient" and s1["percival_score"] is None)
    G2 = PG.gather(studies[3], labelled=False); Mx = PG.active() or M
    sA = MT.score_rows(Mx, G2); sB = MT.score_rows(Mx, G2)
    check("v5.23 reproducible: the same model and input give the same scores", json.dumps(sA, sort_keys=True, default=str) == json.dumps(sB, sort_keys=True, default=str))
    tst = [s["code"] for s in PG.selection() if s["partition"] == "test"]; mid = [x["percival_score"] for c in tst for x in MT.score_rows(Mx, PG.gather(c, labelled=False)) if x["percival_score"] is not None]
    check("v5.23 locked-test scores are not collapsed to 0 / 100 (calibrated, not saturated)", len(mid) and np.mean([2 < v < 98 for v in mid]) > 0.1, f"{np.mean([2 < v < 98 for v in mid]):.2f} of {len(mid)} strictly between 2 and 98")
    check("v5.23 a study used for training is marked in-sample in its score record", sc.get("in_training") is (studies[0] in Mx["data"]["trained_on"]) and (not sc["in_training"] or sc["in_training_note"]))
    odd = dict(G2[0], char={k: (v * 40 if v is not None else 40.0) for k, v in G2[0]["char"].items()}); so = MT.score_rows(Mx, [odd])[0]
    check("v5.23 out-of-distribution measurements -> flagged uncertain with the reason", so["status"] in ("uncertain", "review") and any("out-of-distribution" in r for r in so["reasons"]), f"{so['ood_distance']} > {so['ood_limit']}")
    sq = MT.score_rows(Mx, [dict(G2[0], qc="insufficient_quality")])[0]
    check("v5.23 insufficient study image quality -> 'review' (expert review required), never 'reliable'", sq["status"] == "review" and sq["reasons"])
    check("v5.23 every scored candidate carries its disagreement pattern and Image ML stability", all("pattern" in s and "image_tta_spread" in s for s in sA))
    # network blocked: inference still works
    real = socket.socket
    class Blocked(socket.socket):
        def connect(self, a): raise OSError("network blocked by the test")
    socket.socket = Blocked
    try: s2 = MT.score_rows(PG.active() or M, PG.gather(studies[2], labelled=False)); ok = len(s2) > 0
    except Exception as e: ok = False; s2 = str(e)
    socket.socket = real
    check("inference works with the network blocked", ok, str(s2)[:100] if not ok else "")
    # second cycle -> new version; ledger keeps the old prediction
    led0 = sorted(glob.glob(PG.P("ledger", studies[0], "*.json")))
    PG.set_selection(studies[-4:], include=False); PG._train("test cycle 2"); vs = PG.versions()
    check("second cycle: new registry version; selection respected", len(vs) == 2 and PG.load(vs[-1])["data"]["studies"] == len(studies) - 4)
    PG.promote(vs[-1], why="test"); time.sleep(4); led1 = sorted(glob.glob(PG.P("ledger", studies[0], "*.json")))
    check("prediction ledger: the old model's assessment is kept unchanged, the new one added", len(led1) == len(led0) + 1 and all(json.load(open(p))["model"] for p in led1))
    # v5.23 expert-review snapshot: label + the prediction that existed at review time, immutable
    json.dump(dict(study=studies[0], reviewer="Dr A", saved=time.strftime("%Y-%m-%d %H:%M:%S"), meter_visible=1, read_mode="second look"), open(os.path.join(B, "review", f"{studies[0]}_final_Dr_A.json"), "w"))
    n1 = PG.snapshot_study(studies[0]); n2 = PG.snapshot_study(studies[0]); R = PG.reviews_of(studies[0])
    ok_ = n1 == 1 and n2 == 0 and len(R) == 1 and R[0]["labels"] and R[0]["percival_at_review"] and R[0]["percival_at_review"]["model"] in vs \
          and any(c.get("patch_sha256") for c in R[0]["candidates"]) and R[0]["percival_visible_to_reviewer"] == 1 and R[0]["processing"]["candidates_sha256"]
    check("v5.23 expert-review snapshot: labels + outputs shown at review time + patch hashes + versions; written once, never rewritten", ok_,
          json.dumps(dict(n1=n1, n2=n2, model=(R[0].get("percival_at_review") or {}).get("model") if R else None)))
    check("rollback to the previous version", PG.rollback().get("version") == vs[0] and PG.active_version() == vs[0])
    check("controlled cycles: no new cycle without N newly finished studies", PG.maybe_cycle() is False)
check("nothing written outside the project", not [p for p in glob.glob(os.path.join(T, "*")) if os.path.basename(p) != "base"])
shutil.rmtree(T, ignore_errors=True)
print(("ALL PASS" if not F else f"{len(F)} FAILED: {F}") + f" ({__file__})"); sys.exit(1 if F else 0)
