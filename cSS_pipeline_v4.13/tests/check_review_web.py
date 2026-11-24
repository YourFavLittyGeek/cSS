"""review_web.py server checks (no browser): PH3 in $CSS_BASE. usage: check_review_web.py
meta lists every candidate with a meter value in 0-1 and a band; a call without a reviewer name is refused; calls,
comment, undo-style clearing and a missed-cSS mark are written with the reviewer name; ID_calls.csv keeps the
review_css.py format; calls re-load for the same reviewer and not for another; names are remembered."""
import os, sys, json, time, subprocess, urllib.request, pandas as pd, numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); S = os.path.join(HERE, "..", "scripts"); B = os.environ["CSS_BASE"]
def fail(m): print("FAIL:", m); srv.kill(); sys.exit(1)
for f in ("PH3_calls.csv", "PH3_calls_Reader_A.csv", "PH3_calls_Reader_B.csv", "PH3_review_log.csv", "PH3_missed.csv", "reviewers.json", "PH3_primary.json",
          "call_policy.json", "PH3_effective.json", "PH3_lineage.json", "PH3_lineage_decisions.json"):            # v5.15+: ledger files, so the test can be re-run
    if os.path.exists(f"{B}/review/{f}"): os.remove(f"{B}/review/{f}")
import shutil as _sh, glob as _gl; _sh.rmtree(f"{B}/review/call_history/PH3", ignore_errors=True)
for f in _gl.glob(f"{B}/review/PH3_final*.json") + _gl.glob(f"{B}/review/PH3_score_rev_*.json") + _gl.glob(f"{B}/review/PH3_excluded_audit_*.csv") + _gl.glob(f"{B}/review/PH3_calls_*.csv") + _gl.glob(f"{B}/review/PH3_events_*.jsonl"):
    os.remove(f)                                                     # reviewer-made files of an earlier run of this test (detector outputs are kept)
srv = subprocess.Popen([sys.executable, f"{S}/review_web.py", "PH3", "--no-browser", "--port", "8931", "--audit"], stdout=subprocess.PIPE, text=True)
U = srv.stdout.readline().split("http://")[1].split()[0]; U = "http://" + U.rstrip("/")
def get(p):
    for _ in range(60):
        try: return json.load(urllib.request.urlopen(U + p, timeout=60))
        except OSError: time.sleep(0.5)
    fail("server did not answer")
def get_bytes(p): return urllib.request.urlopen(U + p, timeout=60).read()
def post(p, d):
    r = urllib.request.Request(U + p, json.dumps(d).encode(), {"Content-Type": "application/json", "X-CSS": "1"})
    try: return json.load(urllib.request.urlopen(r, timeout=120))
    except urllib.error.HTTPError as e: return json.load(e)
# Phase 3A.2: every reviewer's FIRST read of a study is blind (server-enforced). A new reviewer and the anonymous view get no AI content and
# blinded ids; refused routes answer 403. Fixture: the readers used below completed an earlier blind read and chose the second look (the
# same journal events the server writes), so the rest of this check exercises the second-look behaviour as before.
mb0 = get("/api/meta?study=PH3&reviewer=Reader%20New"); ma0 = get("/api/meta?study=PH3&reviewer=")
for m0 in (mb0, ma0):
    if not m0.get("blind") or any(c_["ai"]["band"] != "hidden" or c_.get("conf") is not None for c_ in m0["cands"]) or m0.get("percival") or m0.get("ai_score"):
        fail("a first read must be blind: no AI content")
_nx0 = len(pd.read_csv(f"{B}/review/PH3_excluded.csv")) if os.path.exists(f"{B}/review/PH3_excluded.csv") else 0
_b0 = [c_["id"] for c_ in mb0["cands"]]          # candidates and audit objects share one shuffled id space (audit objects stay unrecognisable)
if len(set(_b0)) != len(_b0) or min(_b0) < 1 or max(_b0) > len(_b0) + _nx0: fail(f"blinded ids must be distinct numbers in 1..N+M: {_b0}")
sys.path.insert(0, S); import review_blind as _RB0
_cd0 = pd.read_csv(f"{B}/review/PH3_candidates.csv"); _mp0 = _RB0.stored_mapping(B, "PH3", "Reader New")
_pairs0 = [(int(r_.cand_id), _mp0[_RB0.cand_key(r_)]) for _, r_ in _cd0.iterrows()]
if len(_pairs0) > 2 and all(t_ == b_ for t_, b_ in _pairs0): fail("blinded ids must not repeat the detector-rank ids")
if "error" not in post("/api/import", dict(study="PH3", reviewer="Reader New", source="legacy")): fail("import must be refused during a blind read")
try: urllib.request.urlopen(U + "/api/struct3d?study=PH3&cand=1&reviewer=Reader%20New", timeout=60); fail("shape reading must be refused during a blind read")
except urllib.error.HTTPError as e_:
    if e_.code != 403: fail(f"shape reading during a blind read -> {e_.code}")
sys.path.insert(0, S); import review_blind as _RB, review_io as _RIO
for _r in ("Reader A", "Reader B", "Reader C", "Reader D", "Reader X", "Reader Z", "Reader Q"):
    with _RIO.study_lock(B, "PH3"): _RIO.journal_append(B, "PH3", _r, "initial_completed", n_candidates=0, n_called=0, note="test fixture: earlier blind read")
    _RB.unblind(B, "PH3", _r)
m = get("/api/meta?study=PH3&reviewer=Reader%20A"); n = len(m["cands"])
if m.get("blind") or m["read_phase"]["phase"] != "second_look": fail("after a completed read + unblind the second look is open")
if not n or any(not (0 <= c["ai"]["score"] <= 1) or c["ai"]["band"] not in ("green", "yellow", "red") or not c["ai"]["suspect"] for c in m["cands"]):
    fail("meter values / bands")
if "error" not in post("/api/call", dict(study="PH3", reviewer="", cand_id=1, call="cSS")): fail("a call without a reviewer name must be refused")
post("/api/reviewer", dict(name="Reader A"))
ids = [c["id"] for c in m["cands"]]
post("/api/call", dict(study="PH3", reviewer="Reader A", cand_id=ids[0], call="cSS", meter=0.8))
post("/api/call", dict(study="PH3", reviewer="Reader A", cand_id=ids[1], call="Vessel"))
post("/api/call", dict(study="PH3", reviewer="Reader A", cand_id=ids[1], call="", action="clear"))
post("/api/call", dict(study="PH3", reviewer="Reader A", cand_id=ids[2], comment="check, \"quoted\""))
if "error" not in post("/api/call", dict(study="PH3", reviewer="Reader A", cand_id=ids[0], call="Banana")): fail("unknown call accepted")
r = post("/api/missed", dict(study="PH3", reviewer="Reader A", action="add", ijk=m["cands"][0]["centre"], comment="here"))
if len(r["missed"]) != 1: fail("missed mark not stored")
c = pd.read_csv(f"{B}/review/PH3_calls.csv")
if list(c.columns) != ["cand_id", "call", "vox_i", "vox_j", "vox_k", "volume_mm3"] or list(c.call) != ["cSS"]: fail(f"ID_calls.csv format / content: {c}")
a = pd.read_csv(f"{B}/review/PH3_calls_Reader_A.csv")
if set(a.reviewer) != {"Reader A"} or len(a) != 2 or "quoted" not in str(a.comment.tolist()): fail(f"per-reviewer file: {a}")
if len(pd.read_csv(f"{B}/review/PH3_review_log.csv")) != 4: fail("log must hold the 4 accepted actions")
ms = pd.read_csv(f"{B}/review/PH3_missed.csv")
if ms.reviewer[0] != "Reader A" or [ms.can_i[0], ms.can_j[0], ms.can_k[0]] != m["cands"][0]["centre"]: fail("missed csv")
if get("/api/meta?study=PH3&reviewer=Reader%20A")["calls"][str(ids[0])]["call"] != "cSS": fail("calls not re-loaded")
if get("/api/meta?study=PH3&reviewer=Reader%20B")["calls"]: fail("another reviewer must start empty")
if get("/api/meta?study=PH3&reviewer=")["reviewers"]["last"] != "Reader A": fail("last reviewer name not remembered")
f = post("/api/finish", dict(study="PH3", reviewer="Reader A"))
if f["counts"]["cSS"] != 1 or f["unread"] != n - 1: fail(f"summary: {f}")
# v5.5 final score: reviewer score from the reader's calls, AI score from the green-band candidates (own file), final save
rs, ai = f.get("reader_score") or {}, f.get("ai_score") or {}
if rs.get("multifocality_0_4") is None or rs.get("category") not in ("absent", "focal", "disseminated") or "n_lines_total" not in rs: fail(f"reader score: {rs}")
if ai.get("multifocality_0_4") is None or not os.path.exists(f"{B}/review/PH3_score_ai.json"): fail(f"AI score: {ai}")
if json.load(open(f"{B}/review/PH3_score.json"))["multifocality_0_4"] != rs["multifocality_0_4"]: fail("the AI scoring must not overwrite the reader's score file")
if os.path.exists(f"{B}/review/PH3_final_Reader_A.json"): fail("no final record before the final save")
post("/api/call", dict(study="PH3", reviewer="Reader A", cand_id=ids[1], call="Vessel", action="revote"))
g = post("/api/finish", dict(study="PH3", reviewer="Reader A", final=True, n_differ=1, meter_visible=1, comparison_shown=True))
if g.get("error") or not os.path.exists(f"{B}/review/PH3_final_Reader_A.json"): fail(f"final save failed: {g.get('error')}")
fin = json.load(open(f"{B}/review/PH3_final_Reader_A.json"))
if not fin.get("primary"): fail("Reader A saved first and must be the primary reviewer")
if fin["reviewer"] != "Reader A" or fin["n_revoted"] != 1 or fin["reviewer_score"]["multifocality_0_4"] != g["reader_score"]["multifocality_0_4"]: fail(f"final record: {fin}")
rep = pd.read_csv(f"{B}/review/css_report.csv")
if list(rep.Study) != ["PH3"] or "cSS score (0-4)" not in rep.columns or "Category" not in rep.columns: fail(f"report: {rep}")
if get("/api/meta?study=PH3&reviewer=Reader%20A")["final"]["reviewer"] != "Reader A": fail("final record not returned with the study")
# v5.7: a second reviewer starts empty, can import, has own score + final; v5.15: shared files = effective (newest) calls
if get("/api/meta?study=PH3&reviewer=Reader%20B")["calls"]: fail("a new reviewer must start empty")
shared_before = open(f"{B}/review/PH3_calls.csv").read(); score_before = open(f"{B}/review/PH3_score.json").read()
srcs = get("/api/meta?study=PH3&reviewer=Reader%20B")["import_sources"]
if not any(s_["key"] == "PH3_calls_Reader_A.csv" for s_ in srcs): fail(f"import sources: {srcs}")
im = post("/api/import", dict(study="PH3", reviewer="Reader B", source="PH3_calls_Reader_A.csv"))
if im.get("imported", 0) < 1 or not str(im["calls"][str(ids[0])]["comment"]).startswith("[imported from Reader_A]"): fail(f"import: {im}")
post("/api/call", dict(study="PH3", reviewer="Reader B", cand_id=ids[0], call="Microbleed"))
mb = get("/api/meta?study=PH3&reviewer=Reader%20B")["calls"][str(ids[0])]
if mb["call"] != "Microbleed" or mb["comment"].startswith("[imported"): fail(f"Microbleed call / import marker not cleared: {mb}")
gb = post("/api/finish", dict(study="PH3", reviewer="Reader B", final=True, read_mode="validation"))
if gb["counts"].get("Microbleed") != 1 or gb["counts"].get("cSS", 0) != 0: fail(f"Reader B counts: {gb['counts']}")
# v5.15 (user decision 2026-11-20): every reviewer is kept; the shared ID_calls.csv / ID_score.json hold the EFFECTIVE calls, by default
# the NEWEST call of any reviewer. Reader B's newer Microbleed call is now effective; Reader A's own file is untouched; the earlier shared
# files were copied to review/call_history/ first; choosing Reader A restores A's calls as the effective ones.
sh = pd.read_csv(f"{B}/review/PH3_calls.csv").set_index("cand_id").call
if sh.get(ids[0]) != "Microbleed": fail(f"newest call (Reader B: Microbleed) must be effective: {dict(sh)}")
if list(pd.read_csv(f"{B}/review/PH3_calls.csv").columns) != ["cand_id", "call", "vox_i", "vox_j", "vox_k", "volume_mm3"]: fail("ID_calls.csv format changed")
if pd.read_csv(f"{B}/review/PH3_calls_Reader_A.csv").set_index("cand_id").call.get(ids[0]) != "cSS": fail("Reader A's own calls were changed")
if json.load(open(f"{B}/review/PH3_score.json"))["multifocality_0_4"] != 0: fail("shared score must follow the effective calls")
hist = os.listdir(f"{B}/review/call_history/PH3")
if not any(h.endswith("_PH3_calls.csv") and open(f"{B}/review/call_history/PH3/{h}").read() == shared_before for h in hist): fail("earlier shared calls not archived")
if not any(h.endswith("_PH3_score.json") and open(f"{B}/review/call_history/PH3/{h}").read() == score_before for h in hist): fail("earlier shared score not archived")
eff = json.load(open(f"{B}/review/PH3_effective.json"))
if eff["rule"] != {"mode": "newest"} or eff["score_current"] is not True: fail(f"effective record: {eff}")
post("/api/primary", dict(study="PH3", reviewer="Reader A", name="Reader A"))                 # = use Reader A's calls for this study
if open(f"{B}/review/PH3_calls.csv").read() != shared_before: fail("choosing Reader A must make A's calls effective again")
if json.load(open(f"{B}/review/PH3_score.json"))["multifocality_0_4"] != json.loads(score_before)["multifocality_0_4"]: fail("score must follow Reader A again")
if not os.path.exists(f"{B}/review/PH3_score_rev_Reader_B.json") or gb["reader_score"]["multifocality_0_4"] != 0: fail(f"Reader B own score: {gb.get('reader_score')}")
fb = json.load(open(f"{B}/review/PH3_final_Reader_B.json"))
if fb["primary"] or fb["n_microbleed"] != 1 or fb["read_mode"] != "second look" or fb["read_phase"] != "second_look": fail(f"Reader B final (read mode from the server, not the page): {fb}")
rep = pd.read_csv(f"{B}/review/css_report.csv")
if sorted(rep.Reviewer) != ["Reader A", "Reader B"] or "Microbleeds called" not in rep.columns: fail(f"report rows per reviewer: {rep[['Study', 'Reviewer']]}")
if get("/api/meta?study=PH3&reviewer=Reader%20A")["final"]["reviewer"] != "Reader A": fail("final record must be per reviewer")
post("/api/primary", dict(study="PH3", reviewer="Reader B", name="Reader B"))
if get("/api/meta?study=PH3&reviewer=")["primary"] != "Reader B": fail("primary reviewer not changed")
# v5.7 validation read: excluded-object audit sample, separate audit file, never scored, import refused
mv = get("/api/meta?study=PH3&reviewer=Reader%20C&mode=validation")
au = [c_ for c_ in mv["cands"] if c_.get("audit")]
nx_ = len(pd.read_csv(f"{B}/review/PH3_excluded.csv"))
_xr = pd.read_csv(f"{B}/review/PH3_excluded.csv"); _ok = int((~_xr.reason.astype(str).str.lower().str.startswith("infratentorial")).sum())
if mv.get("mode") != "validation" or (_ok and len(au) != max(1, round(0.2 * _ok))): fail(f"audit sample: {len(au)} of {_ok} eligible excluded objects")
if any(str(_xr[_xr.excl_id == c_["id"] - 10000].reason.iloc[0]).lower().startswith("infratentorial") for c_ in au): fail("infratentorial objects must never be in the audit sample")
if nx_ and au:
    aid = au[0]["id"]
    if aid < 10000 or any(c_["id"] == aid for c_ in get("/api/meta?study=PH3&reviewer=Reader%20C")["cands"]): fail("audit objects must appear only in a validation read")
    post("/api/call", dict(study="PH3", reviewer="Reader C", cand_id=aid, call="cSS", mode="validation"))
    post("/api/call", dict(study="PH3", reviewer="Reader C", cand_id=ids[0], call="Vessel", mode="validation"))
    af = pd.read_csv(f"{B}/review/PH3_excluded_audit_Reader_C.csv")
    if list(af.excl_id) != [aid - 10000] or af.call[0] != "cSS" or not str(af.rule[0]): fail(f"audit file: {af}")
    gc = post("/api/finish", dict(study="PH3", reviewer="Reader C", final=True, read_mode="validation"))
    if gc["counts"]["cSS"] != 0 or gc["unread"] != n - 1: fail(f"audit calls must never be scored: {gc['counts']}, unread {gc['unread']}")
    if [x_["id"] for x_ in gc["audit"]] != [aid] or gc["audit"][0]["call"] != "cSS" or not gc["audit"][0]["rule"]: fail(f"audit list after the final save: {gc['audit']}")
    if any(c_.get("rule") for c_ in get("/api/meta?study=PH3&reviewer=Reader%20D&mode=validation")["cands"] if c_.get("audit")): fail("the excluded rule must stay hidden before the final save")
    rv = [c_ for c_ in get("/api/meta?study=PH3&reviewer=Reader%20C&mode=validation")["cands"] if c_.get("audit")]
    if not rv or not all(c_.get("rule") for c_ in rv): fail("the rule must be revealed after the final save")
    fc = json.load(open(f"{B}/review/PH3_final_Reader_C.json"))
    if [x["excl_id"] for x in fc["audit_css"]] != [aid - 10000] or fc["audit_n_read"] != 1: fail(f"final audit record: {fc}")
    L = get_bytes("/api/labels?study=PH3&reviewer=Reader%20C&mode=validation")
    if not (np.frombuffer(L, "<u2") == aid).any(): fail("audit object missing from the label volume of the validation read")
    if "error" not in post("/api/import", dict(study="PH3", reviewer="Reader C", source="legacy", mode="validation")): fail("import must be refused in a validation read")
    for x in ("PH3_excluded_audit_Reader_C.csv", "PH3_final_Reader_C.json", "PH3_calls_Reader_C.csv", "PH3_score_rev_Reader_C.json"):
        if os.path.exists(f"{B}/review/{x}"): os.remove(f"{B}/review/{x}")
sc = get("/api/meta?study=PH3&reviewer=")["side_check"]
if sc.get("labels_ok") is not True or sc.get("bad"): fail(f"side check (world coordinates): {sc}")
for x in ("PH3_final_Reader_A.json", "PH3_final_Reader_B.json", "PH3_score_rev_Reader_B.json", "PH3_calls_Reader_B.csv", "PH3_primary.json"):
    if os.path.exists(f"{B}/review/{x}"): os.remove(f"{B}/review/{x}")
for x in ("PH3_final.json", "PH3_score_ai.json", "css_report.csv", "css_report.xlsx"):
    if os.path.exists(f"{B}/review/{x}"): os.remove(f"{B}/review/{x}")
# v5.6 snapshots + request guards
import base64, urllib.error
png = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + bytes(200)).decode()
sd = f"{B}/review/snap_test"
r = post("/api/snapshot", dict(study="PH3", reviewer="Reader A", folder=sd, name="../../evil name.png", image=png, sidecar=True, meta=dict(cur=[1, 2, 3], plane="axial", slice=4, cand_id=1)))
if os.path.dirname(r["path"]) != os.path.abspath(sd) or ".." in os.path.basename(r["path"]) or not os.path.exists(r["path"]): fail(f"snapshot path: {r}")
if not os.path.exists(os.path.splitext(r["path"])[0] + ".txt") or "voxel xyz: 1 2 3" not in open(os.path.splitext(r["path"])[0] + ".txt").read(): fail("sidecar")
r2 = post("/api/snapshot", dict(study="PH3", reviewer="Reader A", folder=sd, name="../../evil name.png", image=png))
if r2["path"] == r["path"]: fail("a snapshot must never overwrite an earlier one")
if "error" not in post("/api/snapshot", dict(study="PH3", reviewer="Reader A", folder=sd, name="a.png", image="data:image/png;base64,AAAA")): fail("tiny image accepted")
if "error" not in post("/api/snapshot", dict(study="PH3", reviewer="", folder=sd, name="a.png", image=png)): fail("snapshot without reviewer accepted")
try: urllib.request.urlopen(urllib.request.Request(U + "/api/call", b"{}", {"Content-Type": "application/json"}), timeout=20); fail("POST without X-CSS accepted")
except urllib.error.HTTPError as e:
    if e.code != 403: fail(f"POST without X-CSS -> {e.code}")
import shutil as _sh; _sh.rmtree(sd, ignore_errors=True)
if not get("/api/meta?study=PH3&reviewer=")["snapdir"].endswith("snapshots/PH3") or "side_check" not in get("/api/meta?study=PH3&reviewer=") or "vox" not in get("/api/meta?study=PH3&reviewer=")["cands"][0]: fail("meta snapdir / cand vox")
srv.kill()
# v5.7-E-fix5 default: without --audit no rule-excluded object is ever listed, also in a validation read of a new reviewer
srv2 = subprocess.Popen([sys.executable, f"{S}/review_web.py", "PH3", "--no-browser", "--port", "8932", "--open"], stdout=subprocess.PIPE, text=True)
U = "http://127.0.0.1:8932"
_m2 = get("/api/meta?study=PH3&reviewer=Reader%20Z&mode=validation")
srv2.kill()
if any(c_.get("audit") or c_["id"] >= 10000 for c_ in _m2["cands"]): fail("without --audit no excluded object may be shown")
if _m2.get("open_read") is not True: fail("--open must be passed to the page (open_read)")
srv2 = subprocess.Popen([sys.executable, f"{S}/review_web.py", "PH3", "--no-browser", "--port", "8932", "--open"], stdout=subprocess.PIPE, text=True)
_m2b = get("/api/meta?study=PH3&reviewer=Reader%20Never&mode=")
srv2.kill()
if not _m2b.get("blind") or any(c_["ai"]["band"] != "hidden" for c_ in _m2b["cands"]): fail("--open must not skip the blind first read")
if len(_m2["cands"]) != n: fail(f"without --audit the list must be exactly the shown candidates: {len(_m2['cands'])} vs {n}")
# v5.8.3 --show-excluded: every excluded object listed with its rule; a call on one goes to the audit file, never into the calls / score
srv3 = subprocess.Popen([sys.executable, f"{S}/review_web.py", "PH3", "--no-browser", "--port", "8933", "--open", "--show-excluded"], stdout=subprocess.PIPE, text=True)
U = "http://127.0.0.1:8933"
try:
    _m3 = get("/api/meta?study=PH3&reviewer=Reader%20X"); _xe = pd.read_csv(f"{B}/review/PH3_excluded.csv")
    _ex = [c_ for c_ in _m3["cands"] if c_["id"] >= 10000]
    if len(_ex) != len(_xe) or not all(c_.get("rule") for c_ in _ex): fail(f"--show-excluded must list all {len(_xe)} excluded objects with their rule: {len(_ex)}")
    if _ex:
        post("/api/call", dict(study="PH3", reviewer="Reader X", cand_id=_ex[0]["id"], call="cSS", action="call"))
        if not os.path.exists(f"{B}/review/PH3_excluded_audit_Reader_X.csv"): fail("excluded-object call must go to the audit file")
        _cx = f"{B}/review/PH3_calls_Reader_X.csv"
        if os.path.exists(_cx) and (pd.read_csv(_cx).cand_id >= 10000).any(): fail("excluded-object calls must never enter the calls file")
        os.remove(f"{B}/review/PH3_excluded_audit_Reader_X.csv")
finally: srv3.kill()
print(f"--show-excluded: {len(_ex)} excluded objects listed with their rule; calls kept apart from the score")
print(f"default (no --audit): a new reviewer's validation read lists only the {n} shown candidates")
# v5.17: Quick Add fine labels are stored with the call and mapped to css-labels/2.0; calls on candidates of an EARLIER run survive a save
sys.argv = sys.argv[:1]; sys.path.insert(0, S); import review_web as rw, label_schema as LS
rw.IDS[:] = ["PH3"]; st_ = rw.study("PH3"); ids_ = list(st_.df.cand_id.astype(int)); pq = f"{B}/review/PH3_calls_Reader_Q.csv"
pd.DataFrame([dict(cand_id=999, call="cSS", comment="earlier run", reviewer="Reader Q", time="2026-01-01 09:00:00", vox_i=1, vox_j=1, vox_k=1, volume_mm3=1.0)]).to_csv(pq, index=False)
st_.save("Reader Q", {ids_[0]: dict(call="Vessel", comment="", time="2026-02-02 10:00:00", fine="VS")})
q_ = pd.read_csv(pq)
if not ((q_.cand_id == 999) & (q_.comment == "earlier run")).any(): fail("a call on an earlier run's candidate was dropped by a save")
if q_[q_.cand_id == ids_[0]].fine_code.tolist() != ["VS"]: fail(f"fine label not stored with the call: {q_.to_dict('records')}")
if "CA" in rw.FINE["Vessel"] or "VS" not in rw.FINE["Vessel"]: fail("fine labels must belong to their call")
v2 = LS.build(B); r_ = v2[(v2.reviewer_id == "Reader Q") & (v2.obj_id == str(ids_[0]))]
if r_.primary_class.tolist() != ["definite_mimic"] or r_.mimic_subtype.tolist() != ["vein_surface"]: fail(f"css-labels/2.0 conversion: {r_.to_dict('records')}")
if LS.from_v1("C", 3)[0] != "indeterminate" or LS.from_v1("VS", 5)[1] != "vein_surface" or LS.from_v1("H", None)[0] != "out_of_scope": fail("1.0 -> 2.0 conversion rules")
os.remove(pq); print("Quick Add fine labels stored and mapped to css-labels/2.0; earlier-run calls survive saves")
for f in ("PH3_calls.csv", "PH3_calls_Reader_A.csv", "PH3_review_log.csv", "PH3_missed.csv", "reviewers.json"): os.remove(f"{B}/review/{f}")
print(f"review_web: {n} candidates with meter, name required, calls / comment / missed mark stored with the reviewer, re-loaded per reviewer;\n"
      f"   final score {rs['multifocality_0_4']}/4 ({rs['category']}), AI score {ai['multifocality_0_4']}/4 in its own file, final record + cohort report written")
print("RESULT review_web OK")
