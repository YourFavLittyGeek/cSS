"""run_experiment.py + compare_pipelines.py on the PH3 phantom ($CSS_BASE): experiment A = CSS_V53, experiment B = CSS_V53 + CSS_SOFT_GATES + CSS_3D_SEEDS.
Expected: the project is untouched; A vs A = everything 'same'; A vs B = every A shown object still shown (same), the gate-failing objects appear as only_B with a
gate id, no cSS lost, the 3-D files exist in B only. usage: check_compare_pipelines.py"""
import os, sys, subprocess, hashlib, glob, shutil, json, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); S = os.path.join(HERE, "..", "scripts"); B = os.environ["CSS_BASE"]
def fail(m): print("FAIL:", m); sys.exit(1)
env = dict(os.environ, CSS_BASE=B)
def run(args):
    r = subprocess.run([sys.executable] + args, capture_output=True, text=True, env=env)
    if r.returncode: fail(" ".join(args[-3:]) + f" exit {r.returncode}\n{r.stdout[-600:]}\n{r.stderr[-600:]}")
    return r.stdout
before = {f: hashlib.md5(open(f, "rb").read()).hexdigest() for f in glob.glob(f"{B}/review/PH3_*") + glob.glob(f"{B}/work/PH3_*") + glob.glob(f"{B}/data/PH3_*") if os.path.isfile(f)}
cand = pd.read_csv(f"{B}/review/PH3_candidates.csv"); x = cand[["cand_id", "vox_i", "vox_j", "vox_k", "volume_mm3"]].copy()
x["call"] = (["cSS", "cSS", "Vein", "Artifact", "Normal", "Normal", "Vein"] * 8)[:len(x)]; x["comment"] = ""; cf = f"{B}/review/PH3_calls_CpT.csv"; x.to_csv(cf, index=False)
adj = f"{B}/review/adjudication.csv"; had_adj = os.path.exists(adj)
if not had_adj: pd.DataFrame([dict(study_id="PH3", fate="shown", obj_id=2, call="not cSS", note="t")]).to_csv(adj, index=False)   # exercises the A_fate / A_id adjudication path
try:
    run([f"{S}/run_experiment.py", "PH3", "--name", "cpA", "--flags", "CSS_V53=1"])
    run([f"{S}/run_experiment.py", "PH3", "--name", "cpB", "--flags", "CSS_V53=1,CSS_SOFT_GATES=1,CSS_3D_SEEDS=1"])
    for n in ("cpA", "cpB"):
        if not os.path.exists(f"{B}/experiments/{n}/EXPERIMENT.json"): fail(f"{n}: EXPERIMENT.json missing")
    ej = json.load(open(f"{B}/experiments/cpB/EXPERIMENT.json"))
    if ej["switches"].get("CSS_SOFT_GATES") != "1" or "PH3" not in ej["studies"]: fail(f"experiment record {ej}")
    if os.path.exists(f"{B}/experiments/cpA/work/PH3_gen_3d.nii.gz") or not os.path.exists(f"{B}/experiments/cpB/work/PH3_gen_3d.nii.gz"): fail("the 3-D files must exist in B only")
    run([f"{S}/compare_pipelines.py", "cpA", "cpA", "PH3", "--reads", "CpT"])
    same = pd.read_csv(f"{B}/review/compare_pipelines_cpA_vs_cpA.csv")
    if not (same.transition == "same").where(same.A_fate == "shown", True).all() or (same.transition == "only_B").any() or (same.transition == "lost").any(): fail(f"A vs A must be all same:\n{same[['A_fate', 'transition']]}")
    run([f"{S}/compare_pipelines.py", "cpA", "cpB", "PH3", "--reads", "CpT"])
    d = pd.read_csv(f"{B}/review/compare_pipelines_cpA_vs_cpB.csv")
    nA = int((d.A_fate == "shown").sum()); sh = d[d.A_fate == "shown"]
    if not (sh.transition == "same").all(): fail(f"every A shown object must stay shown in B:\n{sh[['A_id', 'transition', 'B_fate', 'B_rule']]}")
    ob = d[(d.transition == "gained") & (d.A_fate == "dropped")]
    if not len(ob) or not (ob.B_soft_gate_fail.fillna("") != "").all(): fail(f"gate-dropped objects of A must be shown in B with a soft gate id: {len(ob)}")
    if int(((d.transition == "lost") & (d.css_any == 1)).sum()) != 0: fail("no cSS may be lost")
    if int(sh.css_any.sum()) < 1: fail("the calls must be attached to the A objects")
    if not had_adj and not (d.calls.astype(str) == "ADJ:not cSS").any(): fail("the adjudication must be applied to the A objects")
    sm = open(f"{B}/review/compare_pipelines_cpA_vs_cpB_summary.txt").read()
    if "objects you called cSS LOST in B: 0" not in sm or "gate-dropped in A, shown in B (soft gates)" not in sm: fail("summary text\n" + sm)
finally:
    os.remove(cf)
    if not had_adj: os.remove(adj)
    shutil.rmtree(f"{B}/experiments", ignore_errors=True)
    for f in glob.glob(f"{B}/review/compare_pipelines_*"): os.remove(f)
after = {f: hashlib.md5(open(f, "rb").read()).hexdigest() for f in before}
if before != after: fail("the project changed: " + ", ".join(sorted(f for f in before if before[f] != after[f]))[:300])
print(f"experiments + comparison: A vs A all same; A vs B: {nA} shown objects unchanged, {len(ob)} gate-dropped objects of A shown in B as soft-gate objects, 0 cSS lost; project untouched")
print("RESULT compare_pipelines OK")
