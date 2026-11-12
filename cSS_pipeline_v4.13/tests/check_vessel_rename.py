"""v5.9: the call class 'Vein' is now 'Vessel'. Old files that say 'Vein' are read as Vessel (and never rewritten); new files say Vessel. No patient data."""
import os, sys, tempfile, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
from css_common import norm_call, match_calls, FP
def fail(m): print("FAIL:", m); sys.exit(1)
if norm_call("Vein") != "Vessel" or norm_call("Vessel") != "Vessel" or norm_call("cSS") != "cSS" or norm_call(float("nan")) == "Vessel": fail("norm_call")
cand = pd.DataFrame(dict(cand_id=[1, 2], vox_i=[10, 20], vox_j=[10, 20], vox_k=[5, 6], volume_mm3=[100.0, 50.0]))
old = cand.copy(); old["call"] = ["Vein", "cSS"]
m, _ = match_calls(cand, old)
if m != {1: "Vessel", 2: "cSS"}: fail(f"legacy Vein must read as Vessel: {m}")
import review_web
if "Vessel" not in review_web.CALLS or "Vein" in review_web.CALLS: fail(f"CALLS {review_web.CALLS}")
print("vessel rename: old 'Vein' calls read as Vessel, the reviewer offers Vessel only")
print("RESULT vessel_rename OK")
