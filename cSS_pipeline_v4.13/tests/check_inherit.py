"""v5.5.2 checks: v53_change_report (snapshot / after) and inherit_calls on the PH3 phantom, own temporary $CSS_BASE.
1. snapshot -> redetect --v53 -> after: change_report.csv has the study, the before/after counts add up.
2. inherit_calls: an old call on a kept, un-merged object is written with the "[inherited" marker; conflicting old calls give a
   hint and NO call; calls already present on the new list are never overwritten; the legacy ID_calls.csv holds only calls;
   the current files are backed up first.
3. review_web: an explicit call on an inherited candidate removes the marker (= confirmation) and keeps the call.
usage: check_inherit.py   (no patient data)"""
import os, sys, json, glob, time, subprocess, tempfile, shutil, urllib.request, numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); S = os.path.join(HERE, "..", "scripts"); py = sys.executable
def fail(m): print("FAIL:", m); sys.exit(1)
T = tempfile.mkdtemp(); env = dict(os.environ, CSS_BASE=T, FREESURFER_HOME=T + "/fs", CSS_REVIEW_TEST="1", PYTHONWARNINGS="ignore")
for d in ("data", "synthseg", "work", "review", "results", "fs"): os.makedirs(f"{T}/{d}")
open(T + "/fs/FreeSurferColorLUT.txt", "w").write(
    "0 Unknown 0 0 0 0\n2 Left-Cerebral-White-Matter 245 245 245 0\n24 CSF 60 60 60 0\n41 Right-Cerebral-White-Matter 245 245 245 0\n"
    "1022 ctx-lh-postcentral 220 20 20 0\n1028 ctx-lh-superiorfrontal 20 220 160 0\n2022 ctx-rh-postcentral 220 20 20 0\n2028 ctx-rh-superiorfrontal 20 220 160 0\n")
def run(*a):
    r = subprocess.run([py] + list(a), env=env, capture_output=True, text=True)
    if r.returncode: fail(f"{' '.join(a[-3:])} exit {r.returncode}\n{r.stdout[-600:]}\n{r.stderr[-600:]}")
    return r.stdout
run(f"{HERE}/phantom_v4.py", "PH3", "1"); run(f"{S}/align_seg.py", "PH3")
shutil.copy(f"{T}/work/PH3_seg_swispace.nii.gz", f"{T}/work/PH3_t1seg_swispace.nii.gz")
run(f"{S}/detect_css.py", "PH3"); run(f"{S}/review_css.py", "PH3", "--redo")          # test mode: calls cycle cSS / Vein / Near ICH / Normal
json.dump(dict(names=["Tester"], last="Tester"), open(f"{T}/review/reviewers.json", "w"))
n0 = len(pd.read_csv(f"{T}/review/PH3_candidates.csv"))
run(f"{S}/v53_change_report.py", "snapshot", "PH3"); run(f"{S}/redetect.py", "PH3", "--v53")
out = run(f"{S}/v53_change_report.py", "after", "PH3")
rep = pd.read_csv(f"{T}/review/changes/change_report.csv")
if list(rep.study) != ["PH3"] or int(rep.cand_before[0]) != n0 or int(rep.old_kept[0]) + int(rep.old_excluded[0]) + int(rep.old_gone[0]) != n0:
    fail(f"change report counts: {rep.T}")
fate = pd.read_csv(f"{T}/review/changes/PH3_old_candidates_fate.csv"); new = pd.read_csv(f"{T}/review/PH3_candidates.csv")
print(f"change report: {n0} -> {len(new)} candidates; kept {int(rep.old_kept[0])}, excluded {int(rep.old_excluded[0])}")
# make a deterministic situation: give the first two kept, un-merged old candidates the same call, and two merged ones conflicting calls
kept = fate[fate.fate == "kept"].copy()
if len(kept) < 2: fail("phantom gave fewer than 2 kept objects")
kept["call"] = ["cSS"] * len(kept)
by_new = kept.groupby("new_id").cand_id.apply(list)
conflict_nid = next((int(n) for n, ids in by_new.items() if len(ids) > 1), None)
if conflict_nid is not None:
    ids = by_new[conflict_nid]; kept.loc[kept.cand_id == ids[0], "call"] = "Vein"
kept_all = fate.copy(); kept_all.loc[kept.index, "call"] = kept.call; kept_all.to_csv(f"{T}/review/changes/PH3_old_candidates_fate.csv", index=False)
open(f"{T}/pre.txt", "w").write("x")
out = run(f"{S}/inherit_calls.py", "PH3", "--reviewer", "Tester"); print("  " + out.strip().splitlines()[1])
c = pd.read_csv(f"{T}/review/PH3_calls_Tester.csv").fillna("")
inh = c[c.comment.str.startswith("[inherited")]
if not len(inh) or not (inh.call == "cSS").all(): fail(f"inherited calls: {c}")
if conflict_nid is not None:
    row = c[c.cand_id == conflict_nid]
    if not len(row) or row.call.iloc[0] != "" or not row.comment.iloc[0].startswith("[old calls"): fail(f"conflict must give a hint and no call: {row}")
leg = pd.read_csv(f"{T}/review/PH3_calls.csv")
if (leg.call == "").any() or set(leg.cand_id) != set(inh.cand_id): fail(f"legacy calls file: {leg}")
if not glob.glob(f"{T}/review/changes/PH3_precalls_*"): fail("current call files must be backed up first")
# existing calls are never overwritten: change one inherited call by hand, run again
c.loc[c.cand_id == inh.cand_id.iloc[0], ["call", "comment"]] = ["Artifact", "mine"]; c.to_csv(f"{T}/review/PH3_calls_Tester.csv", index=False)
run(f"{S}/inherit_calls.py", "PH3", "--reviewer", "Tester")
c2 = pd.read_csv(f"{T}/review/PH3_calls_Tester.csv").fillna("")
r2 = c2[c2.cand_id == inh.cand_id.iloc[0]].iloc[0]
if r2.call != "Artifact" or r2.comment != "mine": fail(f"existing call overwritten: {r2}")
print("inherit_calls: unanimous -> inherited + marker, conflict -> hint only, existing calls kept, backups written")
# 3. confirmation through the reviewer server
srv = subprocess.Popen([py, f"{S}/review_web.py", "PH3", "--no-browser", "--port", "8941"], env=env, stdout=subprocess.PIPE, text=True)
U = "http://" + srv.stdout.readline().split("http://")[1].split()[0].rstrip("/")
def post(p, d):
    r = urllib.request.Request(U + p, json.dumps(d).encode(), {"Content-Type": "application/json"}); return json.load(urllib.request.urlopen(r, timeout=120))
for _ in range(60):
    try: urllib.request.urlopen(U + "/api/meta?study=PH3&reviewer=Tester", timeout=60); break
    except OSError: time.sleep(0.5)
tgt = int(inh.cand_id.iloc[1]); res = post("/api/call", dict(study="PH3", reviewer="Tester", cand_id=tgt, call="cSS", action="call"))
srv.kill()
got = res["calls"][str(tgt)]
if got["call"] != "cSS" or got["comment"].startswith("[inherited"): fail(f"confirmation did not remove the marker: {got}")
print("reviewer: pressing the call on an inherited candidate removes the marker and keeps the call")
shutil.rmtree(T); print("RESULT inherit OK")
