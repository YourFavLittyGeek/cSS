"""Evaluate v5.12 vs v5.13 on blooming phantoms. usage: python evaluate_bloom.py dev|heldout
dev = seeds 0-29 (development; may be looked at), heldout = seeds 1000-1199 (only after FREEZE.json exists)."""
import sys, os, json, csv, hashlib, time
H = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(H)
sys.path.insert(0, os.path.join(ROOT, "scripts")); sys.path.insert(0, H)
import numpy as np
from scipy import ndimage as ndi
import css_morph3d as v512, css_morph3d_v2 as v2, bloom_phantoms as bp

which = sys.argv[1]
if which == "heldout":
    fz = json.load(open(f"{H}/FREEZE.json"))
    for f, hsh in fz["sha256"].items():
        assert hashlib.sha256(open(os.path.join(ROOT, f), "rb").read()).hexdigest() == hsh, f"{f} changed after the freeze"
seeds = range(0, 30) if which == "dev" else range(1000, 1200)
CL = {"sheet": 1, "tube": 0}; rows = []
def dice(a, b): return 2 * (a & b).sum() / max(a.sum() + b.sum(), 1)
for sd in seeds:
    t0 = time.time(); sp = bp.random_spec(sd); C = bp.make_case(sp); cand, lab, vox = C["candidate"], C["labels"], np.array(C["vox"])
    row = dict(seed=sd, kind=sp["kind"], vox="x".join(f"{v:g}" for v in vox), sigma_b=round(sp["sigma_b"], 2), contrast_units=round(sp["a"] * 100 / sp["noise"], 1),
               true_thick=round(C["true_thick"], 2), n_truth=int((lab > 0).sum()), n_cand=int(cand.sum()), n_bloom=int(C["bloom"].sum()))
    if cand.sum() < 4 or (lab > 0).sum() < 2: row["note"] = "structure not detectable at this resolution / contrast"; rows.append(row); continue
    truth = lab > 0; row["cand_dice"] = round(dice(cand, truth), 2); row["cand_vol_ratio"] = round(cand.sum() / truth.sum(), 2)
    # v5.12 on the candidate
    r1, a1 = v512.analyse(cand, vox); P = a1["P_idx"]; gl = lab[tuple(P.T)]
    row["v512_thick"] = r1["thickness_mm"]["median"]
    for j, kind in enumerate(C["kinds"], 1):
        sel = gl == j
        if sel.any(): row[f"v512_s{j}_{kind}_correct"] = round(float((a1["gcls"][sel] == CL[kind]).mean()), 2)
    # v5.13
    out = v2.analyse(cand, vox, img=C["img"]); D = out.get("_D")
    for rep in ("candidate", "core"):
        d = out.get(rep)
        if not d: continue
        row[f"{rep}_label"] = d["label"]; row[f"{rep}_level"] = d["level"]; row[f"{rep}_thick"] = d["thickness_mm"]["median"]
        row[f"{rep}_resolvable"] = d["resolvable_frac"]; row[f"{rep}_stability"] = d["stability"]
        m = cand if rep == "candidate" else D["core"]; Pm = np.argwhere(m); glm = lab[tuple(Pm.T)]
        for j, kind in enumerate(C["kinds"], 1):
            sel = glm == j
            if sel.any() and "_labels2" in d:
                ok = (d["_labels2"][sel] == kind) & (d["_labels4"][sel] == kind) & d["_res"][sel]
                row[f"{rep}_s{j}_{kind}_correct"] = round(float(ok.mean()), 2); row[f"{rep}_s{j}_{kind}_notres"] = round(float((~d["_res"][sel]).mean()), 2)
    if D is not None:
        core = D["core"]; row["core_dice"] = round(dice(core, truth), 2); row["core_vol_ratio"] = round(core.sum() / truth.sum(), 2)
        row["core_unstable"] = out["decomposition"]["core_unstable_frac"]; row["bloom_in_core"] = round(float((core & C["bloom"]).sum() / max(C["bloom"].sum(), 1)), 2)
        row["core_pieces_vs_truth"] = f"{ndi.label(core, v2.S26)[1]}/{ndi.label(truth, v2.S26)[1]}"
    row["secs"] = round(time.time() - t0, 1); rows.append(row); print(sd, sp["kind"], row.get("candidate_label"), row.get("core_label"), row["secs"], flush=True)
os.makedirs(f"{H}/results", exist_ok=True)
keys = list(dict.fromkeys(k for r in rows for k in r))
with open(f"{H}/results/bloom_{which}.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=keys, restval=""); w.writeheader(); w.writerows(rows)
print("written", len(rows))
