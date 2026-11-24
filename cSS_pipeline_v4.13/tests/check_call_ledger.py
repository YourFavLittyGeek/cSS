"""check_call_ledger.py - every reviewer's calls kept; effective call = consensus of designated experts (Phase 3A; newest-wins removed); reviewer rule per study / cohort / all with
precedence; review states (Not started / In progress / Reviewed / Needs re-review); effective file in the legacy format with archive;
reviewer files never changed by policy; consolidation refused without the phrase, archived, restorable; Excel sheet columns.
Synthetic review folder only (no images; the re-scoring path is covered by check_review_web.py on the phantom).
usage: python tests/check_call_ledger.py   (exit 1 on any FAIL)"""
import hashlib, json, os, shutil, sys, tempfile, time
import pandas as pd
H = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(H)
sys.path.insert(0, os.path.join(ROOT, "scripts")); sys.path.insert(0, os.path.join(ROOT, "app"))
import call_ledger as CL          # noqa: E402
import review_calls_gui as RCG    # noqa: E402
F = []
def check(n, ok, info=""): print(f"{'PASS' if ok else 'FAIL'}  {n}  {info}"); (None if ok else F.append(n))
def rd(p):
    with open(p) as f: return f.read()
def jl(p):
    with open(p) as f: return json.load(f)
def jw(o, p):
    with open(p, "w") as f: json.dump(o, f)
def touch(p): open(p, "w").close()
def sha(p):
    with open(p, "rb") as f: return hashlib.sha256(f.read()).hexdigest()

B = tempfile.mkdtemp(prefix="ledger_"); R = os.path.join(B, "review"); os.makedirs(R); os.makedirs(os.path.join(B, "app_data"))
CAND = pd.DataFrame(dict(cand_id=[1, 2, 3], vox_i=[10, 40, 70], vox_j=[10, 40, 70], vox_k=[5, 10, 15], volume_mm3=[30.0, 50.0, 80.0]))
def setup(sid, cohort="C1"):
    CAND.to_csv(os.path.join(R, f"{sid}_candidates.csv"), index=False); touch(os.path.join(R, f"{sid}_candidates.nii.gz"))
    pp = os.path.join(B, "app_data", "patients.json"); pats = jl(pp) if os.path.exists(pp) else []
    pats.append(dict(code=sid, cohort=cohort, status="done")); jw(pats, pp)
def calls(sid, reviewer, rows):
    d = pd.DataFrame([dict(cand_id=c, call=k, comment="", reviewer=reviewer, time=t, **CAND.set_index("cand_id").loc[c].to_dict()) for c, k, t in rows])
    p = os.path.join(R, f"{sid}_calls_{CL.slug(reviewer)}.csv"); d.to_csv(p, index=False); return p
def eff(sid): return {r["cand_id"]: (r["effective_call"], r["source_reviewer"]) for r in CL.effective(B, sid)["rows"]}

setup("SYN1"); setup("SYN2"); setup("SYN3", cohort="C2")
import review_roles as RR                                                     # Phase 3A.3: only designated experts decide
for n_ in ("Dr A", "Dr B"): RR.set_role(B, n_, "expert", "test admin", "fixture", RR.CONFIRM_ROLE)
check("no calls -> Not started", CL.review_state(B, "SYN1")["state"] == "not_started")
pa = calls("SYN1", "Dr A", [(1, "cSS", "2026-01-01 10:00:00"), (2, "Vessel", "2026-01-01 10:01:00")])
check("some calls -> In progress", CL.review_state(B, "SYN1")["state"] == "in_progress")
pb = calls("SYN1", "Dr B", [(1, "Artifact", "2026-02-01 09:00:00"), (3, "Normal", "2026-02-01 09:01:00")])
check("default = expert consensus; cSS vs Artifact stays unresolved (no newest-wins)", eff("SYN1") == {1: ("", ""), 2: ("Vessel", "Dr A"), 3: ("Normal", "Dr B")}, str(eff("SYN1")))
E = CL.effective(B, "SYN1"); r1 = next(r for r in E["rows"] if r["cand_id"] == 1)
check("history keeps every call with reviewer and time; disagreement status", [(h["reviewer"], h["call"], h["time"]) for h in r1["history"]] ==
      [("Dr A", "cSS", "2026-01-01 10:00:00"), ("Dr B", "Artifact", "2026-02-01 09:00:00")] and r1["disagreement"] and r1["status"] == "disagreement")
check("all called but not finished -> In progress", CL.review_state(B, "SYN1")["state"] == "in_progress")
jw(dict(reviewer="Dr B", saved="2026-02-01 09:05:00"), os.path.join(R, "SYN1_final_Dr_B.json"))
st = CL.review_state(B, "SYN1")
check("all called + final save -> Reviewed (review progress), unresolved counted separately", st["state"] == "reviewed" and "Dr B" in st["reason"] and st["n_unresolved"] == 1, st["reason"])
before = {p: sha(p) for p in (pa, pb)}
CL.set_policy(B, "study", "SYN1", dict(mode="reference", reviewer="Dr A", fallback="consensus"), by="test")
check("study rule: reference expert, expert consensus where they did not call", eff("SYN1") == {1: ("cSS", "Dr A"), 2: ("Vessel", "Dr A"), 3: ("Normal", "Dr B")})
CL.set_policy(B, "study", "SYN1", dict(mode="reference", reviewer="Dr A", fallback="none"))
check("fallback none: candidates the expert did not call stay unresolved", eff("SYN1")[3] == ("", ""))
check("policy never changes reviewer files", {p: sha(p) for p in (pa, pb)} == before)
calls("SYN2", "Dr A", [(1, "cSS", "2026-01-01 10:00:00")]); calls("SYN2", "Dr B", [(1, "Vessel", "2026-03-01 10:00:00")])
calls("SYN3", "Dr A", [(1, "cSS", "2026-01-01 10:00:00")]); calls("SYN3", "Dr B", [(1, "Vessel", "2026-03-01 10:00:00")])
CL.set_policy(B, "cohort", "C1", dict(mode="reference", reviewer="Dr A"))
check("cohort rule applies to its studies only", eff("SYN2")[1] == ("cSS", "Dr A") and eff("SYN3")[1] == ("", ""))
CL.set_policy(B, "all", "", dict(mode="reference", reviewer="Dr B"))
check("all-studies rule; study rule still overrides", eff("SYN3")[1] == ("Vessel", "Dr B") and eff("SYN1")[3] == ("", ""))
CL.set_policy(B, "study", "SYN1", None); CL.set_policy(B, "cohort", "C1", None); CL.set_policy(B, "all", "", dict(mode="consensus", quorum=1))
check("overrides removed -> back to expert consensus", eff("SYN1")[1] == ("", "") and eff("SYN2")[1] == ("", ""))
P = CL.load_policy(B)
check("every rule change is in the history", len(P["history"]) == 7 and all("time" in h for h in P["history"]))
bad = 0
for r_ in (dict(mode="reviewer"), dict(mode="newest"), dict(mode="reference", reviewer="Nobody")):
    try: CL.set_policy(B, "all", "", r_)
    except (ValueError, PermissionError): bad += 1
check("invalid / removed / non-expert rules refused", bad == 3)
# effective file
with open(os.path.join(R, "SYN1_calls.csv"), "w") as f: f.write("cand_id,call,vox_i,vox_j,vox_k,volume_mm3\n1,cSS,10,10,5,30.0\n")
old_shared = rd(os.path.join(R, "SYN1_calls.csv"))
rec = CL.materialize(B, "SYN1", rescore=False)
sh = pd.read_csv(os.path.join(R, "SYN1_calls.csv"))
check("effective file keeps the legacy format", list(sh.columns) == ["cand_id", "call", "vox_i", "vox_j", "vox_k", "volume_mm3"])
check("effective file holds only RESOLVED calls (the disagreement is left out)", dict(zip(sh.cand_id, sh.call)) == {2: "Vessel", 3: "Normal"})
hd = os.path.join(R, "call_history", "SYN1")
check("previous effective file archived", rec["changed"] and any(rd(os.path.join(hd, f)) == old_shared for f in os.listdir(hd)))
check("effective record written", jl(os.path.join(R, "SYN1_effective.json"))["rule"] == {"mode": "consensus", "quorum": 1})
check("reviewer files unchanged by materialize", {p: sha(p) for p in (pa, pb)} == before)
# re-detection -> Needs re-review
time.sleep(1.1); moved = CAND.copy(); moved.loc[moved.cand_id == 3, ["vox_i", "vox_j"]] = [90, 90]
moved.to_csv(os.path.join(R, "SYN1_candidates.csv"), index=False); touch(os.path.join(R, "SYN1_candidates.nii.gz"))
st = CL.review_state(B, "SYN1")
check("candidates changed after the review -> Needs re-review", st["state"] == "needs_rereview" and st["n_stale"] == 1, st["reason"])
CAND.to_csv(os.path.join(R, "SYN1_candidates.csv"), index=False)
# legacy shared file only
setup("SYN4"); pd.DataFrame(dict(cand_id=[1], call=["cSS"], vox_i=[10], vox_j=[10], vox_k=[5], volume_mm3=[30.0])).to_csv(os.path.join(R, "SYN4_calls.csv"), index=False)
r4 = next(r for r in CL.effective(B, "SYN4")["rows"] if r["cand_id"] == 1)
check("calls made before v5.4 are kept as an unnamed reviewer who never decides", r4["history"][0]["reviewer"] == CL.LEGACY and r4["status"] == "no_expert")
# consolidation removed (Phase 3A.4); restore still works
pre = {f: sha(os.path.join(R, f)) for f in os.listdir(R) if f.startswith("SYN1_calls_")}
refused = 0
for ph in ("yes", CL.CONFIRM):
    try: CL.consolidate(B, ["SYN1"], ph)
    except PermissionError: refused += 1
check("consolidation refused even with the phrase; reviewer files unchanged", refused == 2 and {f: sha(os.path.join(R, f)) for f in pre} == pre)
arch = os.path.join(R, "call_history", "SYN1", "manual_restore"); os.makedirs(arch); shutil.copy2(pa, arch)
calls("SYN1", "Dr A", [(1, "Normal", "2026-04-01 10:00:00")])
CL.restore(B, "SYN1", os.path.relpath(arch, B))
check("restore brings the reviewer file back byte-identical", sha(pa) == before[pa])
try: CL.restore(B, "SYN2", os.path.relpath(arch, B)); wrong = False
except ValueError: wrong = True
check("restore refuses another study's archive", wrong)
# Excel sheet + app wrapper
PAT = jl(os.path.join(B, "app_data", "patients.json"))
df = RCG.calls_sheet(B, PAT)
check("Excel sheet: one call + date-time + role column per reviewer, status, provenance, effective call", {"Dr A · call", "Dr A · date and time", "Dr B · call", "Dr B · role",
      "Effective call", "Effective call from", "Rule", "Status", "Provenance class", "Primary training ground truth"} <= set(df.columns) and len(df) == 12)
row = df[(df.Study == "SYN1") & (df.Candidate == 1)].iloc[0]
check("Excel sheet keeps both experts' calls of a disagreement; no effective call", row["Dr A · call"] == "cSS" and row["Dr B · call"] == "Artifact" and row["Effective call"] == "" and row["Status"] == "disagreement")
s1 = RCG.state(B, "SYN1"); s2 = RCG.state(B, "SYN1"); check("app state cached and equal", s1 == s2 and s1["state"] in CL.STATES)
shutil.rmtree(B, ignore_errors=True)
print(("ALL PASS" if not F else f"{len(F)} FAILED: {F}") + f" ({__file__})"); sys.exit(1 if F else 0)
