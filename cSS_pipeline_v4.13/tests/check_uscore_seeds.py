"""check_uscore_seeds.py - every adversarial scene under N noise seeds (default 5; seeds 8001+): CRITICAL failures (genuine cSS
-> alternative_high_confidence) must be 0; detector sensitivity on the artifact scenes is reported. Synthetic, mechanics only.
usage: python tests/check_uscore_seeds.py [N]"""
import os, sys, json, collections
H = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, H); sys.path.insert(0, os.path.join(os.path.dirname(H), "unified_score"))
import numpy as np, uscore_synth as sy
from uscore import features as fe, detectors as dt, perturb as pt, decision as dc
N = int(sys.argv[1]) if len(sys.argv) > 1 else 5
crit = []; tab = collections.defaultdict(collections.Counter)
for k, (name, sc) in enumerate(sy.scenes().items()):
    for s in range(N):
        b = sy.build(name, sc, 8001 + 100 * k + s)
        if not b["cand"].any(): tab[name]["no candidate"] += 1; continue
        edge = np.pad(np.zeros(np.array(b["cand"].shape) - 2, bool), 1, constant_values=True)
        F, D = fe.extract(b["cand"], b["img"], sy.VOX, raw=b["raw"], ves=b["ves"], psd=b["psd"], brain=b["brain"], reg=b["reg"], crop_edge=edge)
        st, _ = pt.stability(b["cand"], b["img"], sy.VOX, b["raw"], b["ves"], b["psd"], b["brain"], b["reg"], edge, F, D)
        det = dt.run_all(F, D, b["cand"], b["ves"], b["raw"], b["brain"], sy.VOX, st)
        cat = dc.decide(F, D, det, st, b["reg"], None, None)["category"]; tab[name][cat] += 1
        if sc["is_css"] and cat == "alternative_high_confidence": crit.append((name, s, [d["detector"] for d in det if d["status"] == "confirmed"]))
for name, c in tab.items(): print(f"{name:30s} {'cSS' if sy.scenes()[name]['is_css'] else 'non-cSS':7s} {dict(c)}")
print(f"\nseeds: {N} per scene; CRITICAL failures {len(crit)} {crit}")
json.dump(dict(seeds=N, table={k: dict(v) for k, v in tab.items()}, critical=crit), open(os.path.join(H, "..", "unified_score", "output", "adversarial_seeds.json"), "w"), indent=1)
sys.exit(1 if crit else 0)
