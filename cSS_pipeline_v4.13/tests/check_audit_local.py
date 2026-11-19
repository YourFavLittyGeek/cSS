"""audit_local_dataset.py: read-only, counts only, held-out calls never opened, no network (synthetic copy of a demo base)."""
import os, sys, json, glob, shutil, hashlib, tempfile, subprocess
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."); F = []
def ok(c, m): print(("PASS " if c else "FAIL ") + m); c or F.append(m)
B = tempfile.mkdtemp(); HOME = tempfile.mkdtemp(); ENV = dict(os.environ, HOME=HOME)
if True:                                                  # tiny hand-made synthetic base
    for s, call in (("SYN01", "cSS"), ("SYN02", "Vessel"), ("SYN03", "HELDOUT_MARK"), ("SYN04", "Jane Doe free text")):
        os.makedirs(f"{B}/data", exist_ok=True); os.makedirs(f"{B}/review", exist_ok=True)
        open(f"{B}/data/{s}_swi.nii", "wb").write(b"same" if s in ("SYN01", "SYN03") else s.encode())
        open(f"{B}/review/{s}_candidates.csv", "w").write("cand_id,confidence_pct\n1,50\n2,10\n")
        open(f"{B}/review/{s}_calls.csv", "w").write(f"cand_id,call\n1,{call}\n2,\n")
os.makedirs(f"{B}/labels", exist_ok=True)
open(f"{B}/labels/study_meta.csv", "w").write("study_id,status,split\nSYN01,pos,dev\nSYN02,neg,dev\nSYN03,pos,test\n")
h = lambda: {p: hashlib.sha256(open(p, "rb").read()).hexdigest() for p in glob.glob(f"{B}/**/*", recursive=True) if os.path.isfile(p)}
before = h()
A = os.path.join(ROOT, "scripts", "audit_local_dataset.py")
r = subprocess.run([sys.executable, "-B", A, B], capture_output=True, text=True, env=ENV)
ok(r.returncode == 0, "audit runs: " + r.stderr[-300:])
after = h()
ok(after == before, "nothing created, changed or removed inside the dataset folder")
ok(len(os.listdir(f"{HOME}/cSS_audit_reports")) == 2, "exactly two report files, outside the dataset")
rep = open(glob.glob(f"{HOME}/cSS_audit_reports/*.json")[0]).read(); md = open(glob.glob(f"{HOME}/cSS_audit_reports/*.md")[0]).read()
ok("HELDOUT_MARK" not in rep, "held-out study's calls were not opened")
ok(not any(s in rep + md for s in ("SYN01", "SYN02", "SYN03", "SYN04")), "no study code in the report")
ok("Jane" not in rep + md and "(other free text)" in rep, "free-text call values are bucketed, never copied")
ok("study_meta.csv" not in rep + md and "_swi.nii" not in rep + md and "calls.csv" not in rep + md, "no file names in the report")
ok(B not in rep + md and HOME not in rep + md, "no file path in the report")
for bad, m in ((B + "/x", "inside the dataset"), (HOME + "/Desktop", "~/Desktop"), (HOME + "/Library/Mobile Documents/c", "iCloud")):
    rr = subprocess.run([sys.executable, "-B", A, B, "--out", bad], capture_output=True, text=True, env=ENV)
    ok(rr.returncode != 0 and "refused" in rr.stderr + rr.stdout, f"report folder {m} refused")
ok(not glob.glob(f"{B}/**/__pycache__", recursive=True), "no bytecode cache written")
R = json.loads(rep)
ok(R["candidates"]["calls_files_of_heldout_not_opened"] == 1, "held-out calls file counted as present only")
ok(R["mri"]["identical_swi_duplicate_groups"] == 1, "identical SWI exports found as a duplicate group")
ok(R["mri"]["duplicates_touching_heldout"] == 1, "duplicate spanning dev and held-out flagged")
ok("pseudonymous patient key" in " ".join(R["missing_for_training"]), "missing patient key reported, not invented")
code = "import socket,runpy,sys;sys.argv=['x','%s'];exec(open('%s').read().split('HELDOUT_FIXED =')[0]);s=socket.socket()\ntry: s.connect(('1.1.1.1',80)); print('CONNECTED')\nexcept PermissionError: print('BLOCKED')" % (B, os.path.join(ROOT, "scripts", "audit_local_dataset.py"))
ok(subprocess.run([sys.executable, "-c", code], capture_output=True, text=True).stdout.strip() == "BLOCKED", "non-loopback network connection blocked")
print("ALL PASS" if not F else f"{len(F)} FAILED"); sys.exit(1 if F else 0)
