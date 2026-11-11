"""review_web.py server checks (no browser): PH3 in $CSS_BASE. usage: check_review_web.py
meta lists every candidate with a meter value in 0-1 and a band; a call without a reviewer name is refused; calls,
comment, undo-style clearing and a missed-cSS mark are written with the reviewer name; ID_calls.csv keeps the
review_css.py format; calls re-load for the same reviewer and not for another; names are remembered."""
import os, sys, json, time, subprocess, urllib.request, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); S = os.path.join(HERE, "..", "scripts"); B = os.environ["CSS_BASE"]
def fail(m): print("FAIL:", m); srv.kill(); sys.exit(1)
for f in ("PH3_calls.csv", "PH3_calls_Reader_A.csv", "PH3_review_log.csv", "PH3_missed.csv", "reviewers.json"):
    if os.path.exists(f"{B}/review/{f}"): os.remove(f"{B}/review/{f}")
srv = subprocess.Popen([sys.executable, f"{S}/review_web.py", "PH3", "--no-browser", "--port", "8931"], stdout=subprocess.PIPE, text=True)
U = srv.stdout.readline().split("http://")[1].split()[0]; U = "http://" + U.rstrip("/")
def get(p):
    for _ in range(60):
        try: return json.load(urllib.request.urlopen(U + p, timeout=60))
        except OSError: time.sleep(0.5)
    fail("server did not answer")
def post(p, d):
    r = urllib.request.Request(U + p, json.dumps(d).encode(), {"Content-Type": "application/json"})
    try: return json.load(urllib.request.urlopen(r, timeout=120))
    except urllib.error.HTTPError as e: return json.load(e)
m = get("/api/meta?study=PH3&reviewer="); n = len(m["cands"])
if not n or any(not (0 <= c["ai"]["score"] <= 1) or c["ai"]["band"] not in ("green", "yellow", "red") or not c["ai"]["suspect"] for c in m["cands"]):
    fail("meter values / bands")
if "error" not in post("/api/call", dict(study="PH3", reviewer="", cand_id=1, call="cSS")): fail("a call without a reviewer name must be refused")
post("/api/reviewer", dict(name="Reader A"))
ids = [c["id"] for c in m["cands"]]
post("/api/call", dict(study="PH3", reviewer="Reader A", cand_id=ids[0], call="cSS", meter=0.8))
post("/api/call", dict(study="PH3", reviewer="Reader A", cand_id=ids[1], call="Vein"))
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
if os.path.exists(f"{B}/review/PH3_final.json"): fail("no final record before the final save")
post("/api/call", dict(study="PH3", reviewer="Reader A", cand_id=ids[1], call="Vein", action="revote"))
g = post("/api/finish", dict(study="PH3", reviewer="Reader A", final=True, n_differ=1, meter_visible=1, comparison_shown=True))
fin = json.load(open(f"{B}/review/PH3_final.json"))
if fin["reviewer"] != "Reader A" or fin["n_revoted"] != 1 or fin["reviewer_score"]["multifocality_0_4"] != g["reader_score"]["multifocality_0_4"]: fail(f"final record: {fin}")
rep = pd.read_csv(f"{B}/review/css_report.csv")
if list(rep.Study) != ["PH3"] or "cSS score (0-4)" not in rep.columns or "Category" not in rep.columns: fail(f"report: {rep}")
if get("/api/meta?study=PH3&reviewer=Reader%20A")["final"]["reviewer"] != "Reader A": fail("final record not returned with the study")
for x in ("PH3_final.json", "PH3_score_ai.json", "css_report.csv", "css_report.xlsx"):
    if os.path.exists(f"{B}/review/{x}"): os.remove(f"{B}/review/{x}")
srv.kill()
for f in ("PH3_calls.csv", "PH3_calls_Reader_A.csv", "PH3_review_log.csv", "PH3_missed.csv", "reviewers.json"): os.remove(f"{B}/review/{f}")
print(f"review_web: {n} candidates with meter, name required, calls / comment / missed mark stored with the reviewer, re-loaded per reviewer;\n"
      f"   final score {rs['multifocality_0_4']}/4 ({rs['category']}), AI score {ai['multifocality_0_4']}/4 in its own file, final record + cohort report written")
print("RESULT review_web OK")
