"""check_call_ledger.py - every reviewer's calls kept; effective call = newest by default; reviewer rule per study / cohort / all with
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
check("no calls -> Not started", CL.review_state(B, "SYN1")["state"] == "not_started")
pa = calls("SYN1", "Dr A", [(1, "cSS", "2026-01-01 10:00:00"), (2, "Vessel", "2026-01-01 10:01:00")])
check("some calls -> In progress", CL.review_state(B, "SYN1")["state"] == "in_progress")
pb = calls("SYN1", "Dr B", [(1, "Artifact", "2026-02-01 09:00:00"), (3, "Normal", "2026-02-01 09:01:00")])
check("default = newest call of any reviewer", eff("SYN1") == {1: ("Artifact", "Dr B"), 2: ("Vessel", "Dr A"), 3: ("Normal", "Dr B")}, str(eff("SYN1")))
E = CL.effective(B, "SYN1"); r1 = next(r for r in E["rows"] if r["cand_id"] == 1)
check("history keeps every call with reviewer and time", [(h["reviewer"], h["call"], h["time"]) for h in r1["history"]] ==
      [("Dr A", "cSS", "2026-01-01 10:00:00"), ("Dr B", "Artifact", "2026-02-01 09:00:00")] and r1["disagreement"])
check("all called but not finished -> In progress", CL.review_state(B, "SYN1")["state"] == "in_progress")
jw(dict(reviewer="Dr B", saved="2026-02-01 09:05:00"), os.path.join(R, "SYN1_final_Dr_B.json"))
st = CL.review_state(B, "SYN1")
check("all called + final save (non-primary reviewer) -> Reviewed", st["state"] == "reviewed" and "Dr B" in st["reason"], st["reason"])
before = {p: sha(p) for p in (pa, pb)}
CL.set_policy(B, "study", "SYN1", dict(mode="reviewer", reviewer="Dr A", fallback="newest"), by="test")
check("study rule: chosen reviewer, newest where they did not call", eff("SYN1") == {1: ("cSS", "Dr A"), 2: ("Vessel", "Dr A"), 3: ("Normal", "Dr B")})
CL.set_policy(B, "study", "SYN1", dict(mode="reviewer", reviewer="Dr A", fallback="none"))
check("fallback none: candidates the reviewer did not call stay empty", eff("SYN1")[3] == ("", ""))
check("policy never changes reviewer files", {p: sha(p) for p in (pa, pb)} == before)
calls("SYN2", "Dr A", [(1, "cSS", "2026-01-01 10:00:00")]); calls("SYN2", "Dr B", [(1, "Vessel", "2026-03-01 10:00:00")])
calls("SYN3", "Dr A", [(1, "cSS", "2026-01-01 10:00:00")]); calls("SYN3", "Dr B", [(1, "Vessel", "2026-03-01 10:00:00")])
CL.set_policy(B, "cohort", "C1", dict(mode="reviewer", reviewer="Dr A"))
check("cohort rule applies to its studies only", eff("SYN2")[1] == ("cSS", "Dr A") and eff("SYN3")[1] == ("Vessel", "Dr B"))
CL.set_policy(B, "all", "", dict(mode="reviewer", reviewer="Dr A"))
check("all-studies rule; study rule still overrides", eff("SYN3")[1] == ("cSS", "Dr A") and eff("SYN1")[3] == ("", ""))
CL.set_policy(B, "study", "SYN1", None); CL.set_policy(B, "cohort", "C1", None); CL.set_policy(B, "all", "", dict(mode="newest"))
check("overrides removed -> back to newest", eff("SYN1")[1] == ("Artifact", "Dr B") and eff("SYN2")[1] == ("Vessel", "Dr B"))
P = CL.load_policy(B)
check("every rule change is in the history", len(P["history"]) == 7 and all("time" in h for h in P["history"]))
try: CL.set_policy(B, "all", "", dict(mode="reviewer")); bad = False
except ValueError: bad = True
check("invalid rule refused", bad)
# effective file
with open(os.path.join(R, "SYN1_calls.csv"), "w") as f: f.write("cand_id,call,vox_i,vox_j,vox_k,volume_mm3\n1,cSS,10,10,5,30.0\n")
old_shared = rd(os.path.join(R, "SYN1_calls.csv"))
rec = CL.materialize(B, "SYN1", rescore=False)
sh = pd.read_csv(os.path.join(R, "SYN1_calls.csv"))
check("effective file keeps the legacy format", list(sh.columns) == ["cand_id", "call", "vox_i", "vox_j", "vox_k", "volume_mm3"])
check("effective file holds the effective calls", dict(zip(sh.cand_id, sh.call)) == {1: "Artifact", 2: "Vessel", 3: "Normal"})
hd = os.path.join(R, "call_history", "SYN1")
check("previous effective file archived", rec["changed"] and any(rd(os.path.join(hd, f)) == old_shared for f in os.listdir(hd)))
check("effective record written", jl(os.path.join(R, "SYN1_effective.json"))["rule"] == {"mode": "newest"})
check("reviewer files unchanged by materialize", {p: sha(p) for p in (pa, pb)} == before)
# re-detection -> Needs re-review
time.sleep(1.1); moved = CAND.copy(); moved.loc[moved.cand_id == 3, ["vox_i", "vox_j"]] = [90, 90]
moved.to_csv(os.path.join(R, "SYN1_candidates.csv"), index=False); touch(os.path.join(R, "SYN1_candidates.nii.gz"))
st = CL.review_state(B, "SYN1")
check("candidates changed after the review -> Needs re-review", st["state"] == "needs_rereview" and st["n_stale"] == 1, st["reason"])
CAND.to_csv(os.path.join(R, "SYN1_candidates.csv"), index=False)
# legacy shared file only
setup("SYN4"); pd.DataFrame(dict(cand_id=[1], call=["cSS"], vox_i=[10], vox_j=[10], vox_k=[5], volume_mm3=[30.0])).to_csv(os.path.join(R, "SYN4_calls.csv"), index=False)
check("calls made before v5.4 are read as an unnamed reviewer", eff("SYN4")[1] == ("cSS", CL.LEGACY))
# consolidation
pre = {f: sha(os.path.join(R, f)) for f in os.listdir(R) if f.startswith("SYN1_calls_")}
try: CL.consolidate(B, ["SYN1"], "yes"); refused = False
except PermissionError: refused = True
check("consolidation refused without the exact phrase", refused and {f: sha(os.path.join(R, f)) for f in pre} == pre)
plan = CL.consolidate_plan(B, ["SYN1"]); check("plan counts the calls to remove", plan == [dict(study="SYN1", candidates_with_history=1, calls_to_remove=1)], str(plan))
done = CL.consolidate(B, ["SYN1"], CL.CONFIRM, by="test")
a = pd.read_csv(pa)
check("consolidation keeps only the newest call per candidate", 1 not in set(a.cand_id) and 2 in set(a.cand_id) and eff("SYN1")[1] == ("Artifact", "Dr B"))
arch = os.path.join(B, done[0]["archive"])
check("consolidation archived every file first", all(os.path.exists(os.path.join(arch, f)) and sha(os.path.join(arch, f)) == h for f, h in pre.items()))
CL.restore(B, "SYN1", done[0]["archive"])
check("restore brings the reviewer files back byte-identical", {f: sha(os.path.join(R, f)) for f in pre} == pre)
try: CL.restore(B, "SYN2", done[0]["archive"]); wrong = False
except ValueError: wrong = True
check("restore refuses another study's archive", wrong)
# Excel sheet + app wrapper
PAT = jl(os.path.join(B, "app_data", "patients.json"))
df = RCG.calls_sheet(B, PAT)
check("Excel sheet: one call + date-time column per reviewer, effective call and source", {"Dr A · call", "Dr A · date and time", "Dr B · call", "Dr B · date and time",
      "Effective call", "Effective call from", "Rule"} <= set(df.columns) and len(df) == 12)
row = df[(df.Study == "SYN1") & (df.Candidate == 1)].iloc[0]
check("Excel sheet keeps the old call next to the new one", row["Dr A · call"] == "cSS" and row["Dr B · call"] == "Artifact" and row["Effective call"] == "Artifact")
s1 = RCG.state(B, "SYN1"); s2 = RCG.state(B, "SYN1"); check("app state cached and equal", s1 == s2 and s1["state"] in CL.STATES)
shutil.rmtree(B, ignore_errors=True)
print(("ALL PASS" if not F else f"{len(F)} FAILED: {F}") + f" ({__file__})"); sys.exit(1 if F else 0)
