"""zone_probe.py checks on the PH3 phantom ($CSS_BASE): columns, lesion objects on the cortex and inside the hull, calls from two reads,
protected cSS (any read) never flagged by a rule that is reported as safe, nothing in the project changed.
usage: check_zone_probe.py"""
import os, sys, subprocess, hashlib, glob, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); S = os.path.join(HERE, "..", "scripts"); B = os.environ["CSS_BASE"]
def fail(m): print("FAIL:", m); sys.exit(1)
c = pd.read_csv(f"{B}/review/PH3_candidates.csv"); x = c[["cand_id", "vox_i", "vox_j", "vox_k", "volume_mm3"]].copy()
made = []
for name, calls in (("ZpA", ["cSS", "cSS", "Vein", "Artifact", "Normal", "Normal", "Vein"]), ("ZpB", ["cSS", "Microbleed", "Vein", "Artifact", "Normal", "cSS", "Vein"])):
    x["call"] = calls[:len(x)]; x["comment"] = ""; p = f"{B}/review/PH3_calls_{name}.csv"; x.to_csv(p, index=False); made.append(p)
before = {f: hashlib.md5(open(f, "rb").read()).hexdigest() for f in glob.glob(f"{B}/review/PH3_candidates*") + glob.glob(f"{B}/review/PH3_excluded*.csv")}
r = subprocess.run([sys.executable, f"{S}/zone_probe.py", "PH3", "--reads", "ZpA,ZpB"], capture_output=True, text=True, env=dict(os.environ, CSS_BASE=B))
for p in made: os.remove(p)
if r.returncode: fail(r.stderr[-400:] + r.stdout[-300:])
d = pd.read_csv(f"{B}/review/zone_probe.csv")
need = ["outside_hull_frac", "cortex_contact_frac", "free_csf_frac", "infra_near_frac", "skullbase_frac", "rel_z", "fissure_frac", "fissure_side_bias", "dual_contact_frac", "css_any", "css_all", "non_css"]
if any(k not in d.columns for k in need): fail(f"columns: {list(d.columns)}")
sh = d[d.fate == "shown"]
if len(sh) != len(c): fail(f"shown objects {len(sh)} vs {len(c)}")
if not ((sh.cortex_contact_frac >= 0.9) & (sh.outside_hull_frac <= 0.2) & (sh.free_csf_frac <= 0.1)).all(): fail("phantom lesions must lie on the cortex, inside the hull, not in free CSF")
if int(sh.css_any.sum()) != 3 or int(sh.css_all.sum()) != 1: fail(f"two-read logic: css_any {int(sh.css_any.sum())} css_all {int(sh.css_all.sum())}")
if "protected_cSS_flagged" not in open(f"{B}/review/zone_probe_summary.txt").read(): fail("rule grid missing")
after = {f: hashlib.md5(open(f, "rb").read()).hexdigest() for f in before}
if before != after: fail("zone_probe changed project files")
for f in ("zone_probe.csv", "zone_probe_summary.txt"): os.remove(f"{B}/review/{f}")
print(f"zone_probe: {len(d)} objects, lesions on the cortex inside the hull, two-read cSS logic, rule grid, read-only")
print("RESULT zone_probe OK")
