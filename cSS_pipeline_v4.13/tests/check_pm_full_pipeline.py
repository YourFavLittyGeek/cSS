"""The normal pipeline (Add patients / Re-run) is recorded in the processing history: previous outputs archived before, restored
on failure, recorded on success; FreeSurfer never renamed. Uses the app module's own hooks on a synthetic study (no FreeSurfer run)."""
import os, sys, json, tempfile, importlib
B = tempfile.mkdtemp(); os.environ["CSS_BASE"] = B; os.environ["HOME"] = tempfile.mkdtemp()
for d in ("app_data/logs", "review", "data", "work", "subjects/SYN50/mri"): os.makedirs(f"{B}/{d}", exist_ok=True)
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..")); sys.path.insert(0, os.path.join(ROOT, "app"))
import numpy as np, nibabel as nib
nib.save(nib.Nifti1Image(np.ones((4, 4, 4), np.float32), np.eye(4)), f"{B}/data/SYN50_swi.nii")
for n in ("aparc.a2009s+aseg", "orig", "brain"): nib.save(nib.MGHImage(np.ones((4, 4, 4), np.float32), np.eye(4)), f"{B}/subjects/SYN50/mri/{n}.mgz")
open(f"{B}/review/SYN50_candidates.csv", "w").write("cand_id\n1\n"); open(f"{B}/review/SYN50_calls.csv", "w").write("cand_id,call\n1,cSS\n")
A = importlib.import_module("css_app"); F = []
def ok(c, m): print(("PASS " if c else "FAIL ") + m); c or F.append(m)
fsino = os.stat(f"{B}/subjects/SYN50").st_ino
p = dict(code="SYN50", status="running", series={}, pathway="recon")
A.pm_begin_full(p); rid = p["pm_run"]; ok(bool(rid), "full pipeline run recorded at start")
open(f"{B}/review/SYN50_candidates.csv", "w").write("half")
A.pm_end_full(p, False, "detect failed (test)")
st = A.PM.Study(B, "SYN50"); h = st.history()
ok(h[-1]["status"] == "failed" and open(f"{B}/review/SYN50_candidates.csv").read() == "cand_id\n1\n", "failed pipeline: recorded as failed, previous candidates restored")
p = dict(code="SYN50", status="running", series={}, pathway="recon"); A.pm_begin_full(p)
open(f"{B}/review/SYN50_candidates.csv", "w").write("cand_id\n1\n2\n"); A.pm_end_full(p, True)
h = st.history(); ok(h[-1]["status"] == "completed" and st.active_manifest()["run_id"] == h[-1]["run_id"], "successful pipeline: completed and active")
ok(len(h) == 3 and h[0]["status"] == "adopted", "history: earlier outputs (adopted), failed attempt, completed run")
ok(os.path.isdir(f"{B}/subjects/SYN50") and os.stat(f"{B}/subjects/SYN50").st_ino == fsino, "FreeSurfer folder never renamed by the full pipeline")
ok(open(f"{B}/review/SYN50_calls.csv").read() == "cand_id,call\n1,cSS\n", "reader file untouched")
p = dict(code="NEW01", status="running", series={}, pathway="synthseg"); A.pm_begin_full(p); A.pm_end_full(p, True)
ok(A.PM.Study(B, "NEW01").history()[0]["status"] == "completed" and len(A.PM.Study(B, "NEW01").history()) == 1, "new patient: one completed run, no empty 'adopted' record")
print("ALL PASS" if not F else f"{len(F)} FAILED"); sys.exit(1 if F else 0)
