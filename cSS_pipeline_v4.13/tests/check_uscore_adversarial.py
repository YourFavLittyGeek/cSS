"""check_uscore_adversarial.py - adversarial scenes through features + perturbation + detectors + decision (no model: p=None,
so a category can only come from the detectors and protective rules). Synthetic, mechanics only.
CRITICAL failure = a genuine cSS scene reaching 'alternative_high_confidence' or producing a suppression proposal.
Detector sensitivity on the artifact scenes is REPORTED (non-confirmation is conservative, not a failure).
usage: python tests/check_uscore_adversarial.py [--quick]   (exit 1 on any FAIL)"""
import os, sys, json, tempfile
H = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, H); sys.path.insert(0, os.path.join(os.path.dirname(H), "unified_score"))
import numpy as np
import uscore_synth as sy
from uscore import features as fe, detectors as dt, perturb as pt, decision as dc

FAILS = []
def check(name, ok, info=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {info}"); (None if ok else FAILS.append(name))

log = os.path.join(tempfile.mkdtemp(), "audit.jsonl"); results = {}
for k, (name, sc) in enumerate(sy.scenes().items()):
    b = sy.build(name, sc, 7001 + k); cand0 = b["cand"].copy()
    if not b["cand"].any():
        check(f"{name}: candidate generated", False, "empty candidate"); continue
    F, D = fe.extract(b["cand"], b["img"], sy.VOX, raw=b["raw"], ves=b["ves"], psd=b["psd"], brain=b["brain"], reg=b["reg"],
                      crop_edge=np.pad(np.zeros(np.array(b["cand"].shape) - 2, bool), 1, constant_values=True))
    edge = np.pad(np.zeros(np.array(b["cand"].shape) - 2, bool), 1, constant_values=True)
    st, _ = pt.stability(b["cand"], b["img"], sy.VOX, b["raw"], b["ves"], b["psd"], b["brain"], b["reg"], edge, F, D)
    det = dt.run_all(F, D, b["cand"], b["ves"], b["raw"], b["brain"], sy.VOX, st)
    dec = dc.decide(F, D, det, st, b["reg"], None, None)
    sup = dc.propose_suppression(name, 1, dec, None, det, F, "test", "test", log)
    results[name] = dict(category=dec["category"], detectors={d["detector"]: d["status"] for d in det},
                         features={kk: (None if F[kk]["value"] is None else round(F[kk]["value"], 2), F[kk]["status"]) for kk in fe.FEATURE_SPEC},
                         flags=dec["protective_flags"], unstable=st["unstable"])
    print(f"\n== {name}: category {dec['category']}  detectors {results[name]['detectors']}")
    for kk, v in results[name]["features"].items(): print(f"     {kk:26s} {v}")
    print(f"     protective: {dec['protective_flags']}")
    check(f"{name}: original candidate preserved", np.array_equal(b["cand"], cand0))
    if sc["is_css"]:
        check(f"{name}: CRITICAL genuine cSS not called a high-confidence alternative", dec["category"] != "alternative_high_confidence")
        check(f"{name}: CRITICAL no suppression proposal for genuine cSS", sup is None)
    if sup is not None:
        check(f"{name}: suppression record says not applied", sup["action"].startswith("not_applied"))
    if name == "missing_vessel_map":
        check("missing vessel map: x1 unavailable", F["x1_vessel_continuity_mm"]["status"] == "unavailable")
        check("missing vessel map: vein detector unresolved", results[name]["detectors"]["surface_vein"] == "unresolved")
    if name == "misregistration":
        check("misregistration: x3 and x4 unreliable", F["x3_pial_distance_mm"]["status"] == "unreliable" and F["x4_sulcal_alignment"]["status"] == "unreliable")
        check("misregistration: protective registration flag", any("registration" in f for f in dec["protective_flags"]))
    if sc.get("alternative"):
        st_ = results[name]["detectors"][sc["alternative"]]
        print(f"DETECTOR  {name}: {sc['alternative']} -> {st_}  (category {dec['category']})")

check("suppression disabled (constant)", dc.SUPPRESSION_ENABLED is False)
os.makedirs(os.path.join(H, "..", "unified_score", "output"), exist_ok=True)
json.dump(results, open(os.path.join(H, "..", "unified_score", "output", "adversarial_results.json"), "w"), indent=1, default=str)
print(f"\nadversarial: {len(FAILS)} FAIL over {len(results)} scenes")
sys.exit(1 if FAILS else 0)
