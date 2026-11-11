"""probe_common.py with a snapshot of an older detection (review/changes) and an adjudication file: old calls are mapped onto the new objects by overlap,
a non-3-D / wrong-grid label array never crashes, the adjudication works with the compare_pipelines column names. usage: check_probe_common.py"""
import os, sys, tempfile, numpy as np, pandas as pd, nibabel as nib
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
os.environ["CSS_BASE"] = T = tempfile.mkdtemp(); os.makedirs(f"{T}/review/changes")
import probe_common as pc
def fail(m): print("FAIL:", m); sys.exit(1)
aff = np.eye(4); old = np.zeros((12, 12, 12), np.int32); old[2:5, 2:5, 2:5] = 1; old[7:10, 7:10, 7:10] = 2        # two old objects
new = np.zeros_like(old); new[2:5, 2:5, 2:5] = 1; new[7:10, 7:10, 7:10] = 2                                          # same objects in the new list (ids 1, 2)
nib.save(nib.Nifti1Image(old, aff), f"{T}/review/changes/PX_before_candidates.nii.gz")
oc = pd.DataFrame(dict(cand_id=[1, 2], vox_i=[3, 8], vox_j=[3, 8], vox_k=[3, 8], volume_mm3=[27.0, 27.0])); oc.to_csv(f"{T}/review/changes/PX_before_candidates.csv", index=False)
oc.assign(call=["cSS", "Vein"]).to_csv(f"{T}/review/changes/PX_before_calls.csv", index=False)
got = pc.old_calls_onto(T, "PX", new)
if got != {1: ["first:cSS"], 2: ["first:Vein"]}: fail(f"old calls mapped onto the new objects: {got}")
if pc.old_calls_onto(T, "PX", np.zeros(1, np.int32)) != {} or pc.old_calls_onto(T, "PX", np.zeros((1, 1, 1), np.int32)) != {}: fail("a non-3-D or wrong-grid label array must give {} (no crash)")
cand = pd.DataFrame(dict(cand_id=[1, 2], vox_i=[3, 8], vox_j=[3, 8], vox_k=[3, 8], volume_mm3=[27.0, 27.0]))
oc_ = pc.object_calls(T, "PX", "shown", np.zeros(1, np.int32), ["nobody"], cand)          # the exact call pial_compare used to crash on
if not isinstance(oc_, dict): fail("object_calls with a dummy label array")
pd.DataFrame([dict(study_id="PX", fate="shown", obj_id=1, call="not cSS", note="t")]).to_csv(f"{T}/review/adjudication.csv", index=False)
d = pd.DataFrame([dict(study_id="PX", A_fate="shown", A_id=1, calls="x", n_calls=1, n_css=1, css_any=1, css_all=1, non_css=0),
                  dict(study_id="PX", A_fate="shown", A_id=2, calls="y", n_calls=1, n_css=0, css_any=0, css_all=0, non_css=1)])
r = pc.apply_adjudication(d, T, fate_col="A_fate", id_col="A_id")
if r.loc[0, "calls"] != "ADJ:not cSS" or r.loc[0, "css_any"] != 0 or r.loc[0, "non_css"] != 1 or r.loc[1, "calls"] != "y": fail(f"adjudication on A columns:\n{r}")
d2 = pd.DataFrame([dict(study_id="PX", fate="shown", obj_id=1, calls="x", css_any=1, non_css=0, css_all=1, n_css=1, n_calls=1)])
if pc.apply_adjudication(d2, T).loc[0, "css_any"] != 0: fail("adjudication on the default columns")
print("probe_common: snapshot calls mapped by overlap, non-3-D label arrays harmless, adjudication on both column conventions")
print("RESULT probe_common OK")
