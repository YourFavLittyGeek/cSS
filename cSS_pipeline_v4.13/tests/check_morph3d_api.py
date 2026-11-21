"""check_morph3d_api.py - the reviewer's /api/morph3d on the PH6 phantom ($CSS_BASE with PH6 detected): known cSS candidates are
sheet-like, the known tubular vein is tube-like, the candidate label image and the work/review files are not modified.
usage: python tests/check_morph3d_api.py"""
import sys, os, glob, hashlib
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts")); sys.argv = sys.argv[:1]
import numpy as np, review_web as rw
B = rw.B
if not os.path.exists(f"{B}/review/PH6_candidates.csv"): print("SKIP morph3d api (PH6 not detected)"); print("RESULT morph3d_api OK"); sys.exit(0)
h = lambda: {f: hashlib.md5(open(f, "rb").read()).hexdigest() for f in glob.glob(f"{B}/review/PH6_*") + glob.glob(f"{B}/work/PH6_*")}
before = h(); rw.IDS[:] = ["PH6"]; s = rw.study("PH6"); lab0 = s.lab.copy()
tr = s._grid(f"{B}/work/PH6_truth.nii.gz", 0); ve = s._grid(f"{B}/work/PH6_veins.nii.gz", 0); fails = []
for c in range(1, len(s.df) + 1):
    o = s.morph3d(c); m = o["measures"]; obj = s.lab == c; t, v = (tr[obj] > 0).mean(), (ve[obj] > 0).mean()
    sh = m["local_share"]; kind = "cSS" if t >= 0.3 else ("vein" if v >= 0.3 else "other")
    # v5.14-gui EXPECTATION CHANGE for the vein (#6), docs/INVESTIGATION_morph3d_cylinder.md: the detected vein object is 0.8 mm thick
    # and spans ~1.8 x 1.2 samples across (0.8 x 0.8 x 1.2 mm voxels) - below the two-sample limit, so round vs flat cannot be
    # decided. Required: tube-like OR not resolvable >= 0.6, and NEVER sheet-like. (Before: tube >= 0.6.) cSS sheets unchanged.
    ind = sh.get("unresolved", 0) + sh.get("acquisition_limited", 0)
    ok = (kind != "cSS" or sh["sheet"] >= 0.8) and (kind != "vein" or c != 6 or (sh["tube"] + ind >= 0.6 and sh["sheet"] <= 0.1))
    print(("ok    " if ok else "FAIL  ") + f"PH6 #{c} ({kind}): tube {sh['tube']} sheet {sh['sheet']} blob {sh['blob']} | {m['summary'][:70]}")
    if not ok: fails.append(c)
    assert len(o["voxels"]["p"]) == int(obj.sum()), "every candidate voxel is sent (no subsampling)"
# v5.15: with FreeSurfer's mri_vol2vol on the PATH the reviewer writes ONE display cache, work/PH6_t1_swispace.nii.gz (review_web._make_t1,
# by design, once). Every file that existed before must still be byte-identical; that cache is the only new file allowed.
after = h(); cache = f"{B}/work/PH6_t1_swispace.nii.gz"
check = np.array_equal(lab0, s.lab) and all(after.get(f) == v for f, v in before.items()) and set(after) - set(before) <= {cache}
print(("ok    " if check else "FAIL  ") + "candidate labels and every PH6 review / work file unchanged")
print(f"RESULT morph3d_api {'OK' if not fails and check else 'FAILED'}"); sys.exit(0 if not fails and check else 1)
