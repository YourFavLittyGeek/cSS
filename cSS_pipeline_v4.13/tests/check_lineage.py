"""check_lineage.py - v5.17 re-processing with candidate lineage (synthetic label maps, real Process Manager runs, the real app API):
the previous run is archived, not replaced; lineage classifies confident / possible (split, shrink) / no longer detected / newly detected;
an earlier human call moves ONLY through a confident match (with provenance); possible matches wait for confirmation; confirming writes
the confirming reviewer's own new call (the earlier call file is unchanged); rejecting keeps it as history; review state Needs re-review;
fingerprint fall-back without label maps; the app's Compare-runs API and the decision endpoint.
usage: python tests/check_lineage.py   (exit 1 on any FAIL)"""
import hashlib, json, os, shutil, socket, subprocess, sys, tempfile, time, urllib.request
import numpy as np, nibabel as nib, pandas as pd
H = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(H); PY = sys.executable
sys.path.insert(0, os.path.join(ROOT, "scripts")); sys.path.insert(0, os.path.join(ROOT, "app"))
import call_ledger as CL, candidate_lineage as CLN, processing_manager as PM   # noqa: E402
FPC = ["vox_i", "vox_j", "vox_k", "volume_mm3"]
F = []
def check(n, ok, info=""): print(f"{'PASS' if ok else 'FAIL'}  {n}  {info}"); (None if ok else F.append(n))
def sha(p):
    with open(p, "rb") as f: return hashlib.sha256(f.read()).hexdigest()

T = tempfile.mkdtemp(prefix="lineage_"); HOME = os.path.join(T, "home"); B = os.path.join(HOME, "syn_project"); SID = "SYN1"
for d in ("review", "data", "app_data"): os.makedirs(os.path.join(B, d))
A = np.diag([0.8, 0.8, 1.2, 1.0]); SH = (80, 80, 30)
nib.save(nib.Nifti1Image(np.ones(SH, np.float32), A), os.path.join(B, "data", f"{SID}_swi.nii"))
def write_run(blobs):
    lab = np.zeros(SH, np.int16); rows = []
    for cid, (sl, extra) in enumerate(blobs, 1):
        lab[sl] = cid; ijk = np.argwhere(lab == cid); c = ijk[np.argmin(np.linalg.norm(ijk - ijk.mean(0), axis=1))]
        rows.append(dict(cand_id=cid, vox_i=int(c[0]), vox_j=int(c[1]), vox_k=int(c[2]), volume_mm3=round(float(len(ijk) * 0.768), 3), score_v4=extra))
    nib.save(nib.Nifti1Image(lab, A), os.path.join(B, "review", f"{SID}_candidates.nii.gz")); pd.DataFrame(rows).to_csv(os.path.join(B, "review", f"{SID}_candidates.csv"), index=False)
    return pd.DataFrame(rows)
blk = lambda i, j, k, n=6, d=4: (slice(i, i + n), slice(j, j + n), slice(k, k + d))
old = write_run([(blk(5, 5, 5), 0.9), (blk(25, 5, 5), 0.8), (blk(45, 5, 5, 8), 0.7), (blk(5, 40, 5), 0.6), (blk(25, 40, 5, 8), 0.5)])   # A B C D E
calls = pd.DataFrame([dict(cand_id=r.cand_id, call=c, comment="", reviewer="Dr A", time="2026-01-01 10:00:00", vox_i=r.vox_i, vox_j=r.vox_j, vox_k=r.vox_k, volume_mm3=r.volume_mm3)
                      for r, c in zip(old.itertuples(), ["cSS", "Vessel", "cSS", "Artifact", "cSS"])])
pa = os.path.join(B, "review", f"{SID}_calls_Dr_A.csv"); calls.to_csv(pa, index=False)
with open(os.path.join(B, "review", f"{SID}_final_Dr_A.json"), "w") as f: json.dump(dict(reviewer="Dr A", saved="2026-01-01 10:05:00"), f)
check("before re-processing: Reviewed", CL.review_state(B, SID)["state"] == "reviewed")
st = PM.Study(B, SID); old_run = st.adopt_existing("synthetic first run")["run_id"]
old_csv = sha(os.path.join(B, "review", f"{SID}_candidates.csv"))
time.sleep(1.1); man = st.start_run(dict(run=["detect"], reuse=["anatomy", "registration", "align"]), "re-processing (synthetic)")
write_run([(blk(5, 5, 5), 0.91), (blk(26, 5, 5), 0.81), ((slice(45, 53), slice(5, 9), slice(5, 9)), 0.7), ((slice(45, 53), slice(9, 13), slice(5, 9)), 0.65),   # A same, B shifted 1, C split
           (blk(25, 40, 5, 4, 2), 0.4), (blk(60, 60, 10), 0.3)])                                                                                 # E shrunk, F new; D gone
time.sleep(1.1); m = st.finish_run(man["run_id"], True)
arch = os.path.join(B, "runs", SID, old_run, "files", "review", f"{SID}_candidates.csv")
check("previous run archived, not replaced", os.path.exists(arch) and sha(arch) == old_csv and st.active_manifest()["run_id"] == man["run_id"])
L = CLN.after_run(B, SID, man["run_id"]); byo = {r["old_cand_id"]: r for r in L["old"]}
check("lineage: A confident (identical), B confident (shifted)", byo[1]["status"] == "confident" and byo[1]["new_cand_id"] == 1 and byo[2]["status"] == "confident" and byo[2]["new_cand_id"] == 2,
      str((byo[1]["iou"], byo[2]["iou"])))
check("lineage: C split -> possible (needs confirmation)", byo[3]["status"] == "possible" and "split" in byo[3]["why"], byo[3]["why"])
check("lineage: D -> no longer detected", byo[4]["status"] == "no_match")
check("lineage: E shrunk -> possible", byo[5]["status"] == "possible", byo[5]["why"])
check("lineage: F newly detected; both halves of C 'possible', not new", {x["new_cand_id"]: x["status"] for x in L["new"]} == {1: "matched", 2: "matched", 3: "possible", 4: "possible", 5: "possible", 6: "new"}
      and L["summary"] == dict(confident=2, possible=2, no_match=1, new=1, n_old=5, n_new=6))
check("lineage written for the run and as the active comparison", os.path.exists(os.path.join(B, "runs", SID, man["run_id"], "lineage.json")) and os.path.exists(os.path.join(B, "review", f"{SID}_lineage.json")))
import review_roles as RR                                                     # Phase 3A.3: only designated experts decide (fixture)
for n_ in ("Dr A", "Dr B"): RR.set_role(B, n_, "expert", "test admin", "fixture", RR.CONFIRM_ROLE)
E = CL.effective(B, SID); ef = {r["cand_id"]: r for r in E["rows"]}
check("identical candidate keeps its call (same object)", ef[1]["effective_call"] == "cSS" and ef[1]["source_rule"].startswith("expert consensus"))
check("re-detected (shifted) candidate keeps its call, with provenance", ef[2]["effective_call"] == "Vessel" and ("re-attached" in ef[2]["source_rule"] or "carried over" in ef[2]["source_rule"]), ef[2]["source_rule"])
check("possible matches and new candidates get NO call automatically", all(ef[c]["effective_call"] == "" for c in (3, 4, 5, 6)))
pend = CL.pending_confirmations(B, SID)
check("two earlier calls wait for confirmation (split C, shrunk E)", len(pend) == 2 and {p["call"] for p in pend} == {"cSS"})
rs = CL.review_state(B, SID); check("review state: Needs re-review, with the reason", rs["state"] == "needs_rereview" and "confirmation" in rs["reason"], rs["reason"])
before = sha(pa)
try: CL.decide_carry(B, SID, pend[0]["row_uid"], "Dr A", pend[0]["time"], "confirm", ""); noname = False
except ValueError: noname = True
check("a confirmation needs a reviewer name", noname)
pc = next(p for p in pend if p["suggested_new_cand_id"] in (3, 4))
CL.decide_carry(B, SID, pc["row_uid"], "Dr A", pc["time"], "confirm", "Dr B")
pb = pd.read_csv(os.path.join(B, "review", f"{SID}_calls_Dr_B.csv"))
check("confirming writes the confirming reviewer's own call with what was confirmed", len(pb) == 1 and pb.call[0] == "cSS" and "confirmed carry-over of Dr A" in pb.comment[0])
check("the earlier reviewer's file is unchanged", sha(pa) == before)
pe = next(p for p in CL.pending_confirmations(B, SID))
CL.decide_carry(B, SID, pe["row_uid"], "Dr A", pe["time"], "reject", "Dr B")
check("rejecting keeps the call as history only; nothing pending", CL.pending_confirmations(B, SID) == [] and CL.effective(B, SID)["rows"][4]["effective_call"] == "")
check("decisions recorded", len(json.load(open(os.path.join(B, "review", f"{SID}_lineage_decisions.json")))) == 2)
# a confident lineage match the strict fingerprint rule does NOT re-attach (same lesion, delineated 25 % larger): lineage carries the call
SID2 = "SYN2"; nib.save(nib.Nifti1Image(np.ones(SH, np.float32), A), os.path.join(B, "data", f"{SID2}_swi.nii"))
def run2(sl):
    lab = np.zeros(SH, np.int16); lab[sl] = 1; ijk = np.argwhere(lab == 1); c = ijk[np.argmin(np.linalg.norm(ijk - ijk.mean(0), axis=1))]
    nib.save(nib.Nifti1Image(lab, A), os.path.join(B, "review", f"{SID2}_candidates.nii.gz"))
    d = pd.DataFrame([dict(cand_id=1, vox_i=int(c[0]), vox_j=int(c[1]), vox_k=int(c[2]), volume_mm3=round(float(len(ijk) * 0.768), 3))]); d.to_csv(os.path.join(B, "review", f"{SID2}_candidates.csv"), index=False); return d
o2 = run2(blk(10, 10, 5, 6, 4)); pd.DataFrame([dict(cand_id=1, call="cSS", comment="", reviewer="Dr A", time="2026-01-01 10:00:00", **o2.iloc[0][FPC].to_dict())]).to_csv(
    os.path.join(B, "review", f"{SID2}_calls_Dr_A.csv"), index=False)
with open(os.path.join(B, "review", f"{SID2}_final_Dr_A.json"), "w") as f: json.dump(dict(reviewer="Dr A", saved="2026-01-01 10:05:00"), f)   # 3B: a completed review
s2 = PM.Study(B, SID2); s2.adopt_existing("first"); time.sleep(1.1); m2 = s2.start_run(dict(run=["detect"], reuse=[]), "re-processing")
run2(blk(10, 10, 5, 6, 5)); time.sleep(1.1); s2.finish_run(m2["run_id"], True); L2 = CLN.after_run(B, SID2, m2["run_id"])
r2 = CL.effective(B, SID2)["rows"][0]
check("confident lineage beyond the fingerprint rule: call carried over, labelled", L2["old"][0]["status"] == "confident" and r2["effective_call"] == "cSS" and "carried over" in r2["source_rule"]
      and r2["history"][0]["carried"]["iou"] >= 0.5, r2["source_rule"])
# fingerprint fall-back (no label maps)
fb = CLN.compute(SID, arch, "", os.path.join(B, "review", f"{SID}_candidates.csv"), "")
check("without label maps: identical candidate confident by fingerprint, shifted one only possible", next(r for r in fb["old"] if r["old_cand_id"] == 1)["status"] == "confident"
      and fb["method"] == "fingerprint")
# app API
with open(os.path.join(B, "app_data", "patients.json"), "w") as f: json.dump([dict(code=SID, cohort="C", status="done", fingerprint="", series={}, steps_done={}, added=0, mode="semi", anatomy="synthseg")], f)
s_ = socket.socket(); s_.bind(("127.0.0.1", 0)); port = s_.getsockname()[1]; s_.close(); U = f"http://127.0.0.1:{port}"
app = subprocess.Popen([PY, os.path.join(ROOT, "app", "css_app.py"), "--port", str(port), "--no-window"], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
                       env=dict(os.environ, HOME=HOME, CSS_BASE=B, CSS_EXPERIMENTAL="1", PYTHONPATH=os.path.join(ROOT, "app", "guard"),
                                CSS_PROTECTED_PATHS=":".join([os.path.expanduser("~/css_project"), os.path.expanduser("~/cSS_experimental")])))
try:
    for _ in range(80):
        try: urllib.request.urlopen(U + "/api/state", timeout=2); break
        except Exception: time.sleep(0.25)
    r = json.load(urllib.request.urlopen(U + f"/api/lineage/study?code={SID}", timeout=60))
    check("Compare-runs API: runs (archived + active), lineage summary, review state", len(r["runs"]) == 2 and r["active"] == man["run_id"] and r["lineage"]["summary"]["possible"] == 2
          and r["state"]["state"] == "needs_rereview")
    html = urllib.request.urlopen(U + "/", timeout=30).read().decode()
    check("study panel has Compare runs and the re-run dialog explains lineage", 'data-ln="open"' in html and 'data-ln="rerun-note"' in html and "/lineage_view.js" in html)
    rq = urllib.request.Request(U + "/api/lineage/decide", data=json.dumps(dict(code=SID, row_uid="x", reviewer="Dr A", time="t", decision="confirm", by="Dr B")).encode(),
                                headers={"Content-Type": "application/json", "X-CSS-App": "1"})
    check("decide endpoint refuses an unknown call", json.load(urllib.request.urlopen(rq, timeout=60)).get("ok") is False)
finally:
    app.terminate(); app.wait(timeout=20)
shutil.rmtree(T, ignore_errors=True)
print(("ALL PASS" if not F else f"{len(F)} FAILED: {F}") + f" ({__file__})"); sys.exit(1 if F else 0)
