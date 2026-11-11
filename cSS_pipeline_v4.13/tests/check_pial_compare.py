"""pial_compare.py with a constructed answer (no phantom needed): 40 shown objects, known mesh - mask difference, calls with known AUCs.
usage: check_pial_compare.py"""
import os, sys, subprocess, tempfile, numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); S = os.path.join(HERE, "..", "scripts")
def fail(m): print("FAIL:", m); sys.exit(1)
T = tempfile.mkdtemp(); os.makedirs(f"{T}/review")
rng = np.random.default_rng(5); n = 40
mask = np.r_[rng.normal(-0.8, 0.3, 20), rng.normal(0.6, 0.3, 20)]           # 20 cSS (on the cortex, negative) then 20 others (out in the CSF)
mesh = mask + 0.30 + rng.normal(0, 0.05, n)                                  # mesh = mask + 0.3 mm (constant bias) with tiny noise
c = pd.DataFrame(dict(cand_id=np.arange(1, n + 1), hemi="L", region="ctx-lh-x", volume_mm3=50.0 + np.arange(n), pial_dist_mm=mask,
                      vox_i=np.arange(n) * 5 + 10, vox_j=20, vox_k=30))
c.to_csv(f"{T}/review/PX_candidates.csv", index=False)
pd.DataFrame(dict(list="candidate", obj_id=np.arange(1, n + 1), vox_i=c.vox_i, vox_j=20, vox_k=30, volume_mm3=c.volume_mm3, surf_valid=1,
                  surf_normal_dist_mm=mesh, surf_sulc=np.r_[np.ones(20), -np.ones(20)])).to_csv(f"{T}/review/PX_surface_features.csv", index=False)
calls = c[["cand_id", "vox_i", "vox_j", "vox_k", "volume_mm3"]].copy(); calls["call"] = ["cSS"] * 20 + ["Vein"] * 20; calls["comment"] = ""
calls.to_csv(f"{T}/review/PX_calls_Tst.csv", index=False)
r = subprocess.run([sys.executable, f"{S}/pial_compare.py", "PX", "--reads", "Tst"], capture_output=True, text=True, env=dict(os.environ, CSS_BASE=T))
if r.returncode: fail(r.stderr[-500:] + r.stdout[-300:])
txt = open(f"{T}/review/pial_compare_summary.txt").read()
if "objects with both distances: 40 of 40" not in txt: fail("object count\n" + txt)
if "bias (median mesh - mask) +0.30 mm" not in txt: fail("bias must be +0.30 mm\n" + txt)
if "objects on different sides of the surface: 0 of 40" not in txt: fail("sign disagreement must be 0\n" + txt)
if "mask 1.00   mesh 1.00" not in txt: fail("both distances separate the constructed groups perfectly (AUC 1.00)\n" + txt)
if "F1 not supported" not in txt: fail("verdict for equal AUCs\n" + txt)
d = pd.read_csv(f"{T}/review/pial_compare.csv")
if int(d.css_any.sum()) != 20 or len(d) != n: fail("calls per object")
# a mesh distance with a different (worse) separation must change the verdict logic input: AUC of mesh < mask is reported, not hidden
mesh2 = mask.copy(); mesh2[:10] = 0.9; mesh2[20:30] = -0.9                    # 10 cSS and 10 others get swapped sides in the mesh
pd.DataFrame(dict(list="candidate", obj_id=np.arange(1, n + 1), vox_i=c.vox_i, vox_j=20, vox_k=30, volume_mm3=c.volume_mm3, surf_valid=1,
                  surf_normal_dist_mm=mesh2, surf_sulc=1.0)).to_csv(f"{T}/review/PX_surface_features.csv", index=False)
subprocess.run([sys.executable, f"{S}/pial_compare.py", "PX", "--reads", "Tst"], capture_output=True, text=True, env=dict(os.environ, CSS_BASE=T), check=True)
txt2 = open(f"{T}/review/pial_compare_summary.txt").read()
import re as _re
_m = _re.search(r"different sides of the surface: (\d+) of 40", txt2); _a = _re.search(r"mask 1.00   mesh (\d\.\d+)", txt2)
if not _m or int(_m.group(1)) < 15 or not _a or float(_a.group(1)) > 0.6: fail("a worse mesh must be visible (sign disagreement >= 15 of 40, mesh AUC <= 0.6)\n" + txt2)
print("pial_compare: constructed answer reproduced (bias +0.30 mm, AUC 1.00 / 1.00, sign disagreement 0 and >= 15 of 40)")
print("RESULT pial_compare OK")
