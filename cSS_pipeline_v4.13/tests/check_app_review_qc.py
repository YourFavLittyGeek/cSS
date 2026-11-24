"""check_app_review_qc.py - Phase B regression test through the real app (SYNTHETIC project, write guard on):
Anatomy QC screen (restored): reachable from the navigation, FreeSurfer installation detected (version, tools, licence readable; licence
CONTENTS never returned), per-study verdicts ok / outputs missing (partial recon listed) / low confidence / not processed, QC image made
on request and served, Freeview arguments (dry run); review status: a NON-primary reviewer's finished review -> Reviewed, persists after a
restart, -> Needs re-review after re-detection; reviewer calls: policy API (newest default, reviewer rule), consolidation refused without the
phrase (hard stop) and nothing changed, Excel export has the per-reviewer sheet; browser DOM of the QC screen and the Studies status.
usage: python tests/check_app_review_qc.py [--shots DIR]   (exit 1 on any FAIL)"""
import glob, io, json, os, shutil, socket, subprocess, sys, tempfile, time, urllib.error, urllib.request, zipfile
import pandas as pd
H = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(H); PY = sys.executable
sys.path.insert(0, os.path.join(ROOT, "unified_engine")); sys.path.insert(0, os.path.join(ROOT, "scripts"))
from uengine.imaging import synthetic_images as SI      # noqa: E402
F = []
def check(n, ok, info=""): print(f"{'PASS' if ok else 'FAIL'}  {n}  {info}"); (None if ok else F.append(n))
SHOTS = sys.argv[sys.argv.index("--shots") + 1] if "--shots" in sys.argv else None
SECRET = "LICENCE-CONTENT-MUST-NEVER-APPEAR-7f3a"

T = tempfile.mkdtemp(prefix="revqc_"); HOME = os.path.join(T, "home"); B = os.path.join(HOME, "syn_project"); FS = os.path.join(T, "fs")
os.makedirs(os.path.join(B, "app_data")); os.makedirs(os.path.join(FS, "bin"))
with open(os.path.join(FS, "build-stamp.txt"), "w") as f: f.write("freesurfer-macOS-darwin_arm64-8.2.0-SYNTHETIC-TEST\n")
with open(os.path.join(FS, "license.txt"), "w") as f: f.write(SECRET + "\n")
for t in ("mri_synthseg", "mri_synthstrip", "recon-all", "mri_convert", "freeview"):
    p = os.path.join(FS, "bin", t)
    with open(p, "w") as f: f.write("#!/bin/sh\nexit 0\n")
    os.chmod(p, 0o755)
for code in ("SYNQ1", "SYNQ2", "SYNQ3"): SI.write_study(B, code)                     # synthetic SWI + labels + detector-like tables
def qcj(code, status, **kw):
    with open(os.path.join(B, "review", f"{code}_qc.json"), "w") as f: json.dump({**dict(status=status, label_shift_mm=0.3, edge_agreement_mm=0.6, reasons=[]), **kw}, f)
qcj("SYNQ1", "ok", registration=dict(method="bbregister", cost=0.45)); qcj("SYNQ2", "ok"); qcj("SYNQ3", "low_confidence_review", reasons=["thick slices"])
os.makedirs(os.path.join(B, "subjects", "SYNQ2", "mri")); open(os.path.join(B, "subjects", "SYNQ2", "mri", "orig.mgz"), "w").close()   # partial recon
pats = [dict(code=c, cohort="C1", status="done", fingerprint="", series={}, steps_done={}, added=0, mode="semi", anatomy="synthseg") for c in ("SYNQ1", "SYNQ2", "SYNQ3", "SYNQ4")]
with open(os.path.join(B, "app_data", "patients.json"), "w") as f: json.dump(pats, f)
with open(os.path.join(B, "app_data", "settings.json"), "w") as f: json.dump(dict(freesurfer_home=FS, fs_license=os.path.join(FS, "license.txt")), f)
# review: Dr A (primary, saved first) did part; Dr B (NOT primary) finished every candidate later
cand = pd.read_csv(os.path.join(B, "review", "SYNQ1_candidates.csv")); FP = ["vox_i", "vox_j", "vox_k", "volume_mm3"]
def calls(rev, rows):
    pd.DataFrame([dict(cand_id=c, call=k, comment="", reviewer=rev, time=t, **cand.set_index("cand_id").loc[c, FP].to_dict()) for c, k, t in rows]).to_csv(
        os.path.join(B, "review", f"SYNQ1_calls_{rev.replace(' ', '_')}.csv"), index=False)
ids = list(cand.cand_id)
calls("Dr A", [(ids[0], "cSS", "2026-01-01 10:00:00")])
with open(os.path.join(B, "review", "SYNQ1_primary.json"), "w") as f: json.dump(dict(reviewer="Dr A"), f)
calls("Dr B", [(i, "Vessel" if i != ids[0] else "Artifact", "2026-02-01 10:00:00") for i in ids])
with open(os.path.join(B, "review", "SYNQ1_final_Dr_B.json"), "w") as f: json.dump(dict(reviewer="Dr B", saved="2026-02-01 10:05:00"), f)

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
def start():
    port = free_port(); env = dict(os.environ, HOME=HOME, CSS_BASE=B, CSS_EXPERIMENTAL="1", PYTHONPATH=os.path.join(ROOT, "app", "guard"), CSS_FREEVIEW_DRYRUN="1",
                                   CSS_PROTECTED_PATHS=":".join([os.path.expanduser("~/css_project"), os.path.expanduser("~/cSS_experimental"), os.path.expanduser("~/Projects/cSS")]))
    env.pop("FREESURFER_HOME", None); env.pop("FS_LICENSE", None)
    p = subprocess.Popen([PY, os.path.join(ROOT, "app", "css_app.py"), "--port", str(port), "--no-window"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    U = f"http://127.0.0.1:{port}"
    for _ in range(80):
        try: urllib.request.urlopen(U + "/api/state", timeout=2); return p, U
        except Exception: time.sleep(0.25)
    return p, U
def raw(U, path): return urllib.request.urlopen(U + path, timeout=120).read()
def get(U, path): return json.loads(raw(U, path))
def post(U, path, d):
    rq = urllib.request.Request(U + path, data=json.dumps(d).encode(), headers={"Content-Type": "application/json", "X-CSS-App": "1"})
    return json.load(urllib.request.urlopen(rq, timeout=300))
SEEN = []
def J(U, path, d=None):
    r = get(U, path) if d is None else post(U, path, d); SEEN.append(json.dumps(r)); return r

app, U = start()
try:
    html = raw(U, "/").decode()
    check("Anatomy QC in the navigation, routed and loaded", 'data-v="qc"' in html and 'if(V==="qc")' in html and "/qc_view.js" in html)
    check("QC view served", b"function qcView" in raw(U, "/qc_view.js"))
    st = J(U, "/api/fsqc/state"); I = st["install"]; S = {s["code"]: s for s in st["studies"]}
    check("FreeSurfer detected (folder, version, tools, licence readable)", I["home"] == FS and "8.2.0" in I["version"] and I["tools"]["mri_synthseg"] and I["license"]["readable"] and I["ready"])
    check("QC ok: outputs present and recorded status ok", S["SYNQ1"]["verdict"] == "ok" and S["SYNQ1"]["route"] == "T1 SynthSeg", S["SYNQ1"]["why"])
    check("partial FreeSurfer recon: outputs missing, listed", S["SYNQ2"]["verdict"] == "missing_outputs" and any("aparc.a2009s+aseg.mgz" in m for m in S["SYNQ2"]["missing"])
          and S["SYNQ2"]["freesurfer"]["mri/orig.mgz"] == "present", S["SYNQ2"]["why"])
    check("low-confidence QC shown as such", S["SYNQ3"]["verdict"] == "low_confidence")
    check("study without outputs: not processed, never 'ok'", S["SYNQ4"]["verdict"] == "not_processed")
    check("no QC image yet -> reported, can be made", S["SYNQ1"]["snapshot"]["exists"] is False and S["SYNQ1"]["snapshot"]["can_make"] is True)
    r = J(U, "/api/fsqc/snapshot", dict(code="SYNQ1"))
    check("QC image made on request", r.get("ok") is True and os.path.exists(os.path.join(B, "app_data", "qc", "SYNQ1.png")), str(r))
    check("QC image served", raw(U, "/api/qc?code=SYNQ1")[:8] == b"\x89PNG\r\n\x1a\n")
    r = J(U, "/api/fsqc/snapshot", dict(code="SYNQ4")); check("QC image refused when inputs are missing", r.get("ok") is False and "needs" in r.get("error", ""))
    r = J(U, "/api/fsqc/freeview", dict(code="SYNQ1", what="swi"))
    check("Freeview: labels on the SWI (local program, dry run)", r.get("ok") and r["args"][0].endswith("/bin/freeview") and any("SYNQ1_seg_swispace" in a for a in r["args"]))
    r = J(U, "/api/fsqc/freeview", dict(code="SYNQ1", what="recon")); check("Freeview recon refused without a recon", r.get("ok") is False)
    res = {x["code"]: x for x in J(U, "/api/results")}
    q1 = res["SYNQ1"]
    check("non-primary reviewer's finished review -> Reviewed", q1.get("review_state") == "reviewed" and "Dr B" in q1.get("review_reason", ""), q1.get("review_reason"))
    check("Phase 3A: review progress counts every call; effective calls = expert consensus", q1.get("reviewed") == len(ids) and q1.get("calls_rule", "").startswith("consensus of designated experts"))
    check("other studies not reviewed yet", res["SYNQ2"].get("review_state") == "not_started")
    pol = J(U, "/api/calls/policy"); check("policy API lists reviewers; default = expert consensus", set(pol["reviewers"]) == {"Dr A", "Dr B"} and pol["policy"]["default"] == {"mode": "consensus", "quorum": 1})
    r = J(U, "/api/calls/role", dict(name="Dr A", role="expert", by="admin", reason="fixture", confirm="yes")); check("Phase 3A: role change refused without the typed phrase", r.get("ok") is False and r.get("refused"))
    for n_ in ("Dr A", "Dr B"): J(U, "/api/calls/role", dict(name=n_, role="expert", by="admin", reason="designated expert", confirm=pol["confirm"]["role"]))
    rl = J(U, "/api/calls/roles"); check("Phase 3A: roles recorded with history", {v["name"]: v["role"] for v in rl["roles"].values()} == {"Dr A": "expert", "Dr B": "expert"} and len(rl["history"]) == 2)
    r = J(U, "/api/calls/policy", dict(scope="study", target="SYNQ1", rule=dict(mode="newest"), by="tester")); check("Phase 3A: newest-wins refused", r.get("ok") is False)
    r = J(U, "/api/calls/policy", dict(scope="study", target="SYNQ1", rule=dict(mode="reference", reviewer="Dr A", fallback="consensus"), by="tester"))
    sh = pd.read_csv(os.path.join(B, "review", "SYNQ1_calls.csv")).set_index("cand_id").call
    check("study rule: reference expert Dr A, expert consensus elsewhere", r.get("ok") and sh[ids[0]] == "cSS" and sh[ids[-1]] == "Vessel")
    check("rule change archived the previous effective file", os.path.isdir(os.path.join(B, "review", "call_history", "SYNQ1")))
    before = {f: open(f, "rb").read() for f in glob.glob(os.path.join(B, "review", "SYNQ1_calls_*.csv"))}
    r = J(U, "/api/calls/consolidate", dict(scope="study", target="SYNQ1")); check("consolidation without phrase: hard stop", r.get("needs_confirm") is True)
    r = J(U, "/api/calls/consolidate", dict(scope="study", target="SYNQ1", confirm="yes please")); check("consolidation with a wrong phrase: refused", r.get("refused") is True)
    check("refused consolidation changed nothing", {f: open(f, "rb").read() for f in before} == before)
    plan = J(U, "/api/calls/consolidate_plan?scope=study&target=SYNQ1"); check("Phase 3A: consolidation removed (plan says so)", plan.get("removed") is True)
    r = J(U, "/api/calls/consolidate", dict(scope="study", target="SYNQ1", confirm="REWRITE OLD CALLS")); check("Phase 3A: consolidation refused even with the old phrase", r.get("refused") is True and {f: open(f, "rb").read() for f in before} == before)
    xl = pd.read_excel(io.BytesIO(raw(U, "/api/export.xlsx")), sheet_name=None)
    cc = xl.get("candidate_calls", pd.DataFrame())
    check("Excel: per-reviewer call + date-time columns, old call kept", {"Dr A · call", "Dr A · date and time", "Dr B · call", "Dr B · date and time", "Effective call"} <= set(cc.columns)
          and (cc[(cc.Study == "SYNQ1") & (cc.Candidate == ids[0])]["Dr A · call"] == "cSS").all()
          and (cc[(cc.Study == "SYNQ1") & (cc.Candidate == ids[0])]["Dr B · call"] == "Artifact").all() and len(cc[(cc.Study == "SYNQ1")]) == len(ids), str(list(cc.columns))[:200])
    check("Excel: call policy sheet", "call_policy" in xl)
    shots = []
    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if os.path.exists(chrome):
        prof = os.path.join(T, "chrome")
        dom = lambda url: subprocess.run([chrome, "--headless=new", "--disable-gpu", f"--user-data-dir={prof}", "--virtual-time-budget=9000", "--dump-dom", f"{U}/{url}"],
                                         capture_output=True, text=True, timeout=120).stdout
        D = dom("#qc:SYNQ2")
        check("browser: QC screen with installation, studies and the missing files", 'data-qc="install"' in D and 'data-qc="studies"' in D and "outputs missing" in D
              and "aparc.a2009s+aseg.mgz" in D and SECRET not in D)
        D = dom("#studies"); check("browser: Studies shows Reviewed for SYNQ1", "Reviewed" in D and "SYNQ1" in D)
        if SHOTS:
            os.makedirs(SHOTS, exist_ok=True)
            for name, url in (("anatomy_qc", "#qc:SYNQ1"), ("anatomy_qc_missing", "#qc:SYNQ2"), ("studies_review_status", "#studies")):
                subprocess.run([chrome, "--headless=new", "--disable-gpu", f"--user-data-dir={prof}", "--hide-scrollbars", "--window-size=1500,1500", "--virtual-time-budget=9000",
                                f"--screenshot={os.path.join(SHOTS, name + '.png')}", f"{U}/{url}"], capture_output=True, timeout=120); shots.append(name)
    else: print("NOTE  Google Chrome not found - browser checks not run")
finally:
    app.terminate(); app.wait(timeout=20)
app, U = start()
try:
    q1 = {x["code"]: x for x in J(U, "/api/results")}["SYNQ1"]
    check("review status persists after a restart", q1.get("review_state") == "reviewed")
    time.sleep(1.1); c2 = cand.copy(); c2.loc[c2.cand_id == ids[-1], ["vox_i", "vox_j"]] = c2.loc[c2.cand_id == ids[-1], ["vox_i", "vox_j"]] + 9
    c2.to_csv(os.path.join(B, "review", "SYNQ1_candidates.csv"), index=False); os.utime(os.path.join(B, "review", "SYNQ1_candidates.nii.gz"))
    q1 = {x["code"]: x for x in J(U, "/api/results")}["SYNQ1"]
    check("re-detection that moves a candidate -> Needs re-review", q1.get("review_state") == "needs_rereview", q1.get("review_reason"))
finally:
    app.terminate(); app.wait(timeout=20)
check("licence contents never returned by any API response", not any(SECRET in s for s in SEEN))
if SHOTS: check("screenshots written", all(os.path.exists(os.path.join(SHOTS, n + ".png")) for n in ("anatomy_qc", "anatomy_qc_missing", "studies_review_status")))
shutil.rmtree(T, ignore_errors=True)
print(("ALL PASS" if not F else f"{len(F)} FAILED: {F}") + f" ({__file__})"); sys.exit(1 if F else 0)
