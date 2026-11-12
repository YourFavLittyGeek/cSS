"""shape_probe.py on the PH3 phantom ($CSS_BASE): columns, adjudication replaces the reads, microbleed calls listed, read-only. usage: check_shape_probe.py"""
import os, sys, subprocess, hashlib, glob, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); S = os.path.join(HERE, "..", "scripts"); B = os.environ["CSS_BASE"]
def fail(m): print("FAIL:", m); sys.exit(1)
c = pd.read_csv(f"{B}/review/PH3_candidates.csv"); x = c[["cand_id", "vox_i", "vox_j", "vox_k", "volume_mm3"]].copy(); made = []
for name, calls in (("SpA", ["cSS", "cSS", "Vessel", "Artifact", "Normal", "Normal", "Vessel"]), ("SpB", ["cSS", "Microbleed", "Vessel", "Artifact", "Normal", "cSS", "Vessel"])):
    x["call"] = calls[:len(x)]; x["comment"] = ""; p = f"{B}/review/PH3_calls_{name}.csv"; x.to_csv(p, index=False); made.append(p)
adj = f"{B}/review/adjudication.csv"; had = os.path.exists(adj)
if not had: pd.DataFrame([dict(study_id="PH3", fate="shown", obj_id=6, call="not cSS", note="t")]).to_csv(adj, index=False); made.append(adj)
before = {f: hashlib.md5(open(f, "rb").read()).hexdigest() for f in glob.glob(f"{B}/review/PH3_candidates*") + glob.glob(f"{B}/review/PH3_excluded*.csv")}
r = subprocess.run([sys.executable, f"{S}/shape_probe.py", "PH3", "--reads", "SpA,SpB"], capture_output=True, text=True, env=dict(os.environ, CSS_BASE=B))
for p in made: os.remove(p)
if r.returncode: fail(r.stderr[-500:] + r.stdout[-300:])
d = pd.read_csv(f"{B}/review/shape_probe.csv")
need = ["l_over_m", "m_over_s", "fill", "support_over_obj", "bend_ratio", "depth_range", "crown_frac", "deep_frac", "n_labels", "label_spread", "microbleed_called", "css_any"]
if any(k not in d.columns for k in need): fail(f"columns {list(d.columns)}")
sh = d[d.fate == "shown"]
if len(sh) != len(c): fail("shown objects")
if int(d.microbleed_called.sum()) != 1: fail(f"microbleed calls listed: {int(d.microbleed_called.sum())}")
o6 = sh[sh.obj_id == 6].iloc[0]
if not had and (o6.calls != "ADJ:not cSS" or o6.css_any != 0 or o6.non_css != 1): fail(f"adjudication must replace the reads: {o6.calls}")
if "Rule grid" not in open(f"{B}/review/shape_probe_summary.txt").read(): fail("rule grid")
if before != {f: hashlib.md5(open(f, "rb").read()).hexdigest() for f in before}: fail("shape_probe changed project files")
for f in ("shape_probe.csv", "shape_probe_summary.txt"): os.remove(f"{B}/review/{f}")
print(f"shape_probe: {len(d)} objects, blob / sulcus measures, adjudication replaces the reads, microbleed call listed, read-only")
print("RESULT shape_probe OK")
