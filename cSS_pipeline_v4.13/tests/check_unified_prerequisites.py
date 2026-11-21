"""check_unified_prerequisites.py (v5.24) - why Unified Score predictors are reliable / unreliable / unavailable, and that Percival never
turns an unusable predictor into evidence. SYNTHETIC studies only (tests/uscore_synthbase.py: the same file layout the real pipeline writes:
data/ID_swi.nii, review/ID_candidates.*, work/ID_vessels.nii.gz, work/ID_pial_sd.nii.gz (from the anatomy labels), raw/ID/SWI, review/ID_qc.json).

Scenarios (each a copy of the same study, through Percival's own extraction path percival_gui._predictors -> uscore.pipeline.extract_study):
  full         T1 anatomy, registration verified (label shift 0.1 mm), vessel map, pial distance, unmasked SWI -> reliable predictors
  no_qc        QC file missing -> registration 'unverified' -> every anatomy-dependent predictor unreliable (value kept, never
               evidence); x2 (core contrast) is measured from the image alone and keeps its own reliability rule
  bad_reg      registration_ok false -> 'unreliable'
  swi_only     anatomy from SWI only (no T1) -> 'swi_only' -> unreliable
  no_anatomy   no pial distance map (no labels) -> pial / sulcal predictors unavailable
  no_vessels   no vessel map -> vessel continuity unavailable
  no_raw       no unmasked SWI -> extracranial unavailable
  no_swi       SWI missing (invalid input) -> extraction fails -> Percival logs it and treats the source as missing
Percival: a predictor counts only when 'reliable'; missing ones are flagged ('missing: unified'), the candidate is not eligible for the
predictor component (NO_PREDICTORS with the missing requirement in words), and the Percival Score does not change when an unreliable
value is altered (it is not read)."""
import copy, glob, json, os, shutil, sys, tempfile
H = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(H)
sys.path[:0] = [H, os.path.join(ROOT, "app"), os.path.join(ROOT, "scripts"), os.path.join(ROOT, "unified_score"), os.path.join(ROOT, "unified_engine")]
import numpy as np
import uscore_synthbase as sb
import percival_gui as PG
from uengine.percival import meta as MT, eligibility as EL

FAIL = []
def check(ok, name, info=""):
    print(("PASS  " if ok else "FAIL  ") + name + (f"  {info}" if info and not ok else "")); ok or FAIL.append(name)

T = tempfile.mkdtemp(prefix="uprereq_"); SRC = os.path.join(T, "src"); sb.write_base(SRC, n_dev=1, n_ho=0)
SID = sorted(os.path.basename(p)[:-15] for p in glob.glob(os.path.join(SRC, "review", "*_candidates.csv")))[0]


def scenario(name, edit):
    B = os.path.join(T, name); shutil.copytree(SRC, B); edit(B)
    for f in glob.glob(os.path.join(B, "uscore", "features", "*.json")): os.remove(f)          # always extract fresh
    PG.STORE.update(ok=True, error="", migration=None)
    PG.init(B=B, SC=os.path.join(ROOT, "scripts"), SET=dict(features={}, percival_test_fraction=0.2), patients=lambda: [dict(code=SID)],
            is_reviewed=lambda c: True, label=lambda c: c, patient_of=lambda c: c, fingerprint_of=lambda c: "", save_settings=lambda: None,
            notify=lambda *a: None)
    with PG.LOCK: PG.JOB["log"] = []
    pred = PG._predictors(SID)
    F = PG._jl(os.path.join(B, "uscore", "features", f"{SID}.json"), {}) or {}
    st = {}
    for r in F.get("records", []):
        for k in MT.PREDICTORS:
            f = r["F"].get(k) or {}; st.setdefault(k, []).append((f.get("status"), "; ".join(f.get("reasons") or [])))
    reliable = sum(1 for v in pred.values() for x in v.values() if x is not None)
    return dict(pred=pred, status=st, reliable=reliable, reg=F.get("registration"), log=list(PG.JOB["log"]))


def rm(*parts): return lambda B: [os.remove(p) for p in glob.glob(os.path.join(B, *parts))]
def qc(**kw):
    def f(B):
        p = os.path.join(B, "review", f"{SID}_qc.json"); q = json.load(open(p)); q.update(kw); json.dump(q, open(p, "w"))
    return f


S = {}
S["full"] = scenario("full", lambda B: None)
S["no_qc"] = scenario("no_qc", rm("review", f"{SID}_qc.json"))
S["bad_reg"] = scenario("bad_reg", qc(registration_ok=False))
S["swi_only"] = scenario("swi_only", qc(anatomy="SWI SynthSeg"))
S["no_anatomy"] = scenario("no_anatomy", rm("work", f"{SID}_pial_sd.nii.gz"))
S["no_vessels"] = scenario("no_vessels", rm("work", f"{SID}_vessels.nii.gz"))
S["no_raw"] = scenario("no_raw", rm("raw", SID, "SWI", "*"))
S["no_swi"] = scenario("no_swi", rm("data", f"{SID}_swi.nii*"))
for k, v in S.items():
    print(f"   {k:<11} registration={v['reg']!s:<11} reliable values={v['reliable']:>2}  " +
          "  ".join(f"{p[:2]}:{','.join(sorted({s for s, _ in v['status'].get(p, [])}) or ['-'])}" for p in MT.PREDICTORS))

st = lambda sc, p: {s for s, _ in S[sc]["status"].get(p, [])}
why = lambda sc, p: " | ".join(sorted({r for _, r in S[sc]["status"].get(p, []) if r}))
check(S["full"]["reg"] == "ok" and S["full"]["reliable"] > 0 and all("reliable" in st("full", p) for p in ("x2_core_contrast_nu", "x3_pial_distance_mm")),
      "1 full prerequisites (T1 anatomy, verified registration, vessel + pial maps, raw SWI): predictors are reliable and reach Percival",
      json.dumps({p: sorted(st("full", p)) for p in MT.PREDICTORS}))
ANAT = ("x1_vessel_continuity_mm", "x3_pial_distance_mm", "x4_sulcal_alignment", "x5_extracranial_mm")      # need labels / registration
x2 = lambda sc: [s for s, _ in S[sc]["status"].get("x2_core_contrast_nu", [])]
for sc, reg, n in (("no_qc", "unverified", "2 no QC file (the synthetic-cohort case)"), ("bad_reg", "unreliable", "3 failed registration"),
                   ("swi_only", "swi_only", "4 SWI-only anatomy (no T1)")):
    check(S[sc]["reg"] == reg and all(st(sc, p) <= {"unreliable", "unavailable"} for p in ANAT) and f"registration {reg}" in why(sc, "x3_pial_distance_mm")
          and all(S[sc]["pred"][c][p] is None for c in S[sc]["pred"] for p in ANAT) and x2(sc) == x2("full"),
          f"{n} -> registration '{reg}': every anatomy-dependent predictor unreliable with the reason, never passed to Percival; "
          "x2 (core contrast, image only) unchanged by design", json.dumps({p: sorted(st(sc, p)) for p in MT.PREDICTORS}))
check(st("no_anatomy", "x3_pial_distance_mm") == {"unavailable"} and st("no_anatomy", "x4_sulcal_alignment") == {"unavailable"}
      and "no pial distance map" in why("no_anatomy", "x3_pial_distance_mm") and all(S["no_anatomy"]["pred"][c]["x3_pial_distance_mm"] is None for c in S["no_anatomy"]["pred"]),
      "5 no anatomy (no pial distance map) -> pial / sulcal predictors unavailable with the reason; others still measured")
check(st("no_vessels", "x1_vessel_continuity_mm") == {"unavailable"} and "no vessel map" in why("no_vessels", "x1_vessel_continuity_mm"), "6 no vessel map -> vessel continuity unavailable")
check(st("no_raw", "x5_extracranial_mm") == {"unavailable"} and "unmasked" in why("no_raw", "x5_extracranial_mm"), "7 no unmasked SWI -> extracranial unavailable")
check(S["no_swi"]["pred"] == {} and any("predictors not extracted" in l for l in S["no_swi"]["log"]), "8 SWI missing (invalid input) -> extraction refused, logged; no predictor values", str(S["no_swi"]["log"]))

# Percival: unreliable predictors are not evidence
from uengine.percival import meta as M_
row = dict(study=SID, cand_id=1, math=1.2, hemi="L", pred={k: None for k in MT.PREDICTORS}, char={c: 0.5 for c in M_.CHAR}, maps=None, patient=SID, test=False)
E1 = EL.evaluate(dict(label_kind="css", authorized=True, has_image=True, n_char=True, has_predictors=False))
check(not E1["components"]["predictor"]["ok"] and "NO_PREDICTORS" in E1["components"]["predictor"]["reasons"] and "FreeSurfer" in " ".join(E1["components"]["predictor"]["missing"]),
      "9 eligibility: no reliable predictor -> not usable for the predictor component, missing requirement in words")
# a trained model: score of a candidate with no reliable predictor vs the same candidate with a different (unreliable -> None) value
import random
rng = np.random.default_rng(3); rows = []
for i in range(40):
    y = i % 2; pat = f"P{i // 2}"
    rows.append(dict(study=f"S{i // 2}", cand_id=i, math=float(rng.normal(1 + y, 0.5)), hemi="L", patient=pat, test=False, y=y, maps=None,
                     pred={k: float(rng.normal(y, 1)) for k in MT.PREDICTORS}, char={c: float(rng.normal(y, 1)) for c in M_.CHAR}))
Mdl = MT.train_cycle(rows, "vtest", cnn_epochs=1, mins=dict(studies=3, candidates=10, per_class=3))
a = MT.score_rows(Mdl, [dict(row)])[0]
b = MT.score_rows(Mdl, [dict(row, pred={k: None for k in MT.PREDICTORS})])[0]
check(a["components"].get("unified") is None and any("unified" in r for r in a.get("reasons", [])) and a["percival_score"] == b["percival_score"],
      "10 Percival Score with no reliable predictor: the Unified source is flagged missing ('missing: unified'), not scored as zero evidence",
      json.dumps(dict(components=a["components"], reasons=a.get("reasons")))[:300])
full = MT.score_rows(Mdl, [dict(row, pred={k: 0.8 for k in MT.PREDICTORS})])[0]
check(full["components"].get("unified") is not None, "11 with reliable predictors the Unified source is used (component value present)")
shutil.rmtree(T, ignore_errors=True)
print("ALL PASS" if not FAIL else f"{len(FAIL)} FAILED: {FAIL}")
sys.exit(1 if FAIL else 0)
