"""POST-HOC (after the held-out run; not a pre-specified test): does approach A1 (in-plane width / length) or thickness of the
core vs the candidate separate single bands from single veins in the held-out phantoms? AUC only, no threshold."""
import sys, os; H = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(H), "scripts")); sys.path.insert(0, H)
import numpy as np, css_morph3d_v2 as v2, bloom_phantoms as bp, csv
def auc(pos, neg):
    pos, neg = np.asarray(pos), np.asarray(neg); return float(((pos[:, None] > neg[None]).mean() + 0.5 * (pos[:, None] == neg[None]).mean()))
rows = []
for sd in range(1000, 1200):
    sp = bp.random_spec(sd)
    if sp["kind"] not in ("band", "vein"): continue
    C = bp.make_case(sp)
    if C["candidate"].sum() < 4: continue
    D = v2.decompose(C["candidate"], C["img"], C["vox"])
    r = dict(seed=sd, kind=sp["kind"], vox=C["vox"])
    for nm, m in (("cand", C["candidate"]), ("core", D["core"] if "core" in D else None)):
        if m is None or m.sum() < 2: continue
        ip, nsl = v2.inplane(m, C["vox"]); w = np.median([o["width_mm"] for o in ip]); L = max(o["length_mm"] for o in ip)
        r[f"{nm}_width"] = w; r[f"{nm}_wl"] = w / max(L, 1e-6); r[f"{nm}_slices"] = nsl; r[f"{nm}_thick"] = float(np.median(v2.thickness(m, C["vox"])[m]))
    rows.append(r)
for k in ("cand_width", "core_width", "cand_wl", "core_wl", "cand_thick", "core_thick", "cand_slices", "core_slices"):
    b = [r[k] for r in rows if r["kind"] == "band" and k in r]; v = [r[k] for r in rows if r["kind"] == "vein" and k in r]
    print(f"{k:12} AUC(band > vein) {auc(b, v):.2f}   band median {np.median(b):.2f}  vein median {np.median(v):.2f}  (n {len(b)} / {len(v)})")
