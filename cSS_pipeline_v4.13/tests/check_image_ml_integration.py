"""check_image_ml_integration.py (v5.24) - does Percival's Image ML really learn from expert-reviewed MRI patches, and do Fusion, the
meta-model and the Percival Score consume it? SYNTHETIC phantoms only (run_imaging cohort: real SWI-like volumes with lesions and mimics);
the 'expert' calls are the generator's truth written in the reviewer's file format. Not a clinical result.

  1 inputs     the training rows carry the MRI patch of every candidate that has one (model.data.with_image = manifest image examples)
  2 learning   image component out-of-fold AUC (patient-grouped CV, development) clearly above chance; the SAME pipeline with the expert
               labels shuffled stays near chance (so it learns from the labels, not from leakage)
  3 consumed   altering one candidate's patch changes its Image ML value, its Fusion value and its Percival Score; the other sources stay equal
  4 missing    no patch -> Image ML and Fusion not computed for it, reason 'missing: image', the score still produced from the other sources
  5 stored     ledger entry per study and model version with every component value; Intelligence reports the image TTA spread"""
import glob, json, os, shutil, subprocess, sys, tempfile
import numpy as np, pandas as pd
H = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(H); PY = sys.executable
sys.path[:0] = [os.path.join(ROOT, "app"), os.path.join(ROOT, "scripts"), os.path.join(ROOT, "unified_engine"), os.path.join(ROOT, "unified_score")]
FAIL = []
def check(ok, name, info=""):
    print(("PASS  " if ok else "FAIL  ") + name + (f"  {info}" if info else ""), flush=True); ok or FAIL.append(name)

T = tempfile.mkdtemp(prefix="imgml_"); B = os.path.join(T, "proj")
r = subprocess.run([PY, os.path.join(ROOT, "unified_engine", "run_imaging.py"), "cohort", B, "--n", "24", "--seed", "21"], capture_output=True, text=True)
r2 = subprocess.run([PY, os.path.join(ROOT, "app", "mac_percival", "make_demo.py"), B, os.path.join(ROOT, "unified_engine", "run_imaging.py")], capture_output=True, text=True)
assert r.returncode == 0 and r2.returncode == 0, (r.stderr + r2.stderr)[-500:]
shutil.copytree(os.path.join(ROOT, "scripts"), os.path.join(B, "scripts"), ignore=shutil.ignore_patterns("__pycache__"))
for p in glob.glob(os.path.join(B, "unified_engine", "image_truth", "SYN*.csv")):
    sid = os.path.basename(p)[:-4]; t = pd.read_csv(p); t = t[t["list"] == "candidates"]
    c = pd.read_csv(os.path.join(B, "review", f"{sid}_candidates.csv")); y = {int(o): k for o, k in zip(t.obj_id, t.primary_class)}
    pd.DataFrame([dict(cand_id=int(x.cand_id), call="cSS" if y.get(int(x.cand_id)) == "definite_css" else "Vessel", comment="", reviewer="Dr Img",
                       time="2026-11-21 10:00:00") for x in c.itertuples()]).to_csv(os.path.join(B, "review", f"{sid}_calls_Dr_Img.csv"), index=False)
    json.dump(dict(reviewer="Dr Img", saved="2026-11-21 10:05:00"), open(os.path.join(B, "review", f"{sid}_final_Dr_Img.json"), "w"))
import percival_gui as PG
from uengine.percival import meta as MT, datasets as DS
PAT = json.load(open(os.path.join(B, "app_data", "patients.json")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import gt_fixture; gt_fixture.ground_truth(B)   # Phase 3A fixture: experts + documented verification
PG.init(B=B, SC=os.path.join(B, "scripts"), SET=dict(features={}, percival_test_fraction=0.2), patients=lambda: list(PAT), is_reviewed=lambda c: True,
        label=lambda c: c, patient_of=lambda c: c, fingerprint_of=lambda c: "", save_settings=lambda: None, notify=lambda *a: None)
PG.authorize(True); os.environ["CSS_PERCIVAL_EPOCHS"] = "10"
PG._train("image ML integration test")
assert PG.JOB["state"] == "finished", PG.JOB.get("error")
v = PG.versions()[-1]; M = PG.load(v); man = DS.load(PG.P(), M["data"]["dataset"])
n_img = sum(1 for e in man["examples"] if e["partition"] and e["components"]["image"])
check(M["data"]["with_image"] == n_img and n_img > 0.8 * sum(1 for e in man["examples"] if e["partition"]),
      f"1 training used the MRI patch of every candidate that has one ({M['data']['with_image']} rows with a patch = {n_img} image examples in {man['id']})")
cm = M["component_metrics"]; fam = M["intelligence"]["families"]["image"]
auc_img = cm["image"]["auc"]
# control: the same rows, labels shuffled within the development cohort
rows = [r_ for c in sorted({e["study"] for e in man["examples"] if e["partition"]}) for r_ in PG.gather(c)]
dev = [r_ for r_ in rows if not r_["test"]]; rng = np.random.default_rng(7); ys = rng.permutation([r_["y"] for r_ in dev])
Zs, _ = MT.component_oof([dict(r_, y=int(y_)) for r_, y_ in zip(dev, ys)], cnn_epochs=10, image_kinds=[fam["chosen"]], char_kinds=["logistic"], fusion_kinds=["late"])
mk = np.isfinite(Zs["image"]); auc_shuf = MT.auc(np.asarray(ys)[mk], MT.sigmoid(Zs["image"][mk]))
check(auc_img >= 0.7 and auc_shuf <= 0.65 and auc_img - auc_shuf >= 0.15,
      f"2 Image ML learns from the expert-labelled patches: out-of-fold AUC {auc_img:.3f} ({fam['chosen']}), shuffled-label control {auc_shuf:.3f}")
print(f"   families compared: " + ", ".join(f"{k} {((x or {}).get('auc') or 0):.3f}" for k, x in (fam.get("results") or {}).items()) + f" -> chosen {fam['chosen']}")
if not PG.active(): PG.promote(v, why="image ML integration test (synthetic)", override=True)
sid = man["examples"][0]["study"]; G = PG.gather(sid, labelled=False); r0 = next(x for x in G if x.get("maps") is not None)
a = MT.score_rows(M, [dict(r0)])[0]
alt = dict(r0, maps=np.flip(np.asarray(r0["maps"]), axis=-1).copy() * 0 + np.asarray(r0["maps"]).mean())     # flattened patch: same mean, no structure
b = MT.score_rows(M, [alt])[0]
same_other = all(a["components"][k] == b["components"][k] for k in ("math", "unified", "char"))
check(a["components"]["image"] != b["components"]["image"] and a["components"]["fusion"] != b["components"]["fusion"] and same_other
      and (a["percival_score"] != b["percival_score"] or M["discovery"]["chosen"] in ("math_only",)),
      f"3 patch consumed: image {a['components']['image']} -> {b['components']['image']}, fusion {a['components']['fusion']} -> {b['components']['fusion']}, "
      f"Percival {a['percival_score']} -> {b['percival_score']} (meta-model {M['discovery']['chosen']}); MATH / Unified / Characteristic unchanged")
check(b["status"] == "uncertain" and any("image out-of-distribution" in x for x in b["reasons"]) and a["image_ood_distance"] is not None
      and a["image_ood_distance"] <= a["image_ood_limit"] and not any("image out-of-distribution" in x for x in a["reasons"]),
      f"3b a patch unlike the training patches is flagged (status {b['status']}, distance {b.get('image_ood_distance')} > limit {b.get('image_ood_limit')}); "
      f"the real patch is not (distance {a.get('image_ood_distance')})", json.dumps(b.get("reasons")))
c_ = MT.score_rows(M, [dict(r0, maps=None)])[0]
check(c_["components"]["image"] is None and any("image" in x for x in c_.get("reasons", [])) and c_["percival_score"] is not None,
      f"4 no patch: Image ML not computed, flagged ({'; '.join(c_.get('reasons', []))}), score from the other sources {c_['percival_score']}")
rec = PG.score_study(sid); L = PG.history_of(sid)
led = [x for x in L if x.get("model") == PG.active_version()]
check(led and all(k in rec["candidates"][0]["components"] for k in ("math", "unified", "char", "image", "fusion")) and rec["provenance"]["dataset"] == man["id"]
      and "image_tta_spread" in rec["candidates"][0], "5 stored: ledger entry with model version, dataset and every component value; image TTA spread reported",
      json.dumps(rec.get("provenance"))[:200])
shutil.rmtree(T, ignore_errors=True)
print("ALL PASS" if not FAIL else f"{len(FAIL)} FAILED: {FAIL}")
sys.exit(1 if FAIL else 0)
