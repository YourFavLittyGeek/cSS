"""Phase 3A.2 tests: server-enforced blinded initial read in the browser reviewer (review_web.py + review_blind.py).

A synthetic study carries recognisable SENTINEL values in every AI channel the reviewer can serve (evidence scores, model score, confidence,
review-tier reason, Percival score file, unified-score report, AI score file, excluded-object rule, detector fate) and sentinel ORIGINAL
candidate / excluded ids. Every route is called during the blind initial read and every reply (and the server log, the review log, the
snapshot side-car) is searched for them; after a completed read + unblind the same routes must show them (proves the search can see them).
Synthetic projects only; real reviewer server processes. Isolated (tests/_isolation.py)."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import ast
import json
import os
import re
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
S = os.path.join(ROOT, "scripts")
for p in (S, os.path.join(ROOT, "unified_engine"), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)
import review_blind as RB                                                 # noqa: E402
import review_io as RIO                                                   # noqa: E402

TRUE_IDS = [4101, 4102, 4103, 4104, 4105, 4106]                           # original (detector-rank) ids: must never reach the blind reviewer
EXCL_IDS = [61, 62]                                                       # excluded objects -> 10061, 10062
SENT = {"css_evidence": "0.246802", "vein_evidence": "0.135791", "score": "0.864213", "score_model": "0.913579", "confidence_pct": "87.654321",
        "confidence_why": "SENTINEL_CONF_WHY", "review_priority_reason": "SENTINEL_TIER_REASON", "darkness_z": "-7.531246",
        "tube_ratio": "0.471113", "pial_dist_mm": "-0.918273", "tram_frac": "0.272829"}
STRINGS = ["0.246802", "0.135791", "0.864213", "0.913579", "87.654321", "0.91", "SENTINEL_CONF_WHY", "SENTINEL_TIER_REASON", "-7.531246",
           "0.471113", "-0.918273", "0.272829", "SENTINEL_PERCIVAL", "SENTINEL_USCORE", "SENTINEL_AI_SCORE", "SENTINEL_RULE", "SENTINEL_OTHER_COMMENT",
           "SENTINEL_OTHER_MISSED", "0.987654", "I suspect", "trained ranking model", "rule-based evidence", "overlaps shown candidate",
           "excluded object", "4101", "4102", "4103", "4104", "4105", "4106", "10061", "10062"]


def build(b, sid="S1", extra=0):
    import nibabel as nib
    for d in ("review", "data", "work", "labels", "percival/scores", "uscore/reports", "home"): os.makedirs(os.path.join(b, d), exist_ok=True)
    sh = (40, 32, 20); I = np.full(sh, 100.0, np.float32); lab = np.zeros(sh, np.int16); xl = np.zeros(sh, np.int16); rows = []; ids = TRUE_IDS + [4107] * extra
    for k, cid in enumerate(ids):
        i, j, z = 3 + 5 * k, 6 + (k % 3) * 7, 5 + (k % 2) * 7
        lab[i:i + 2, j:j + 3, z:z + 2] = cid; I[lab == cid] = 40.0
        rows.append(dict(cand_id=cid, hemi="L" if k % 2 else "R", region="ctx-lh-postcentral", volume_mm3=float((lab == cid).sum()), vox_i=i, vox_j=j + 1,
                         vox_k=z, extent_mm=3.0, n_slices=2, review_priority_rank=2,
                         **{k_: (v if k_ in ("confidence_why", "review_priority_reason") else float(v)) for k_, v in SENT.items()}))
    for n, e in enumerate(EXCL_IDS):
        xl[30 + 3 * n:32 + 3 * n, 25:27, 14:16] = e
    aff = np.eye(4)
    nib.save(nib.Nifti1Image(I, aff), os.path.join(b, "data", f"{sid}_swi.nii"))
    nib.save(nib.Nifti1Image(lab, aff), os.path.join(b, "review", f"{sid}_candidates.nii.gz"))
    nib.save(nib.Nifti1Image(xl, aff), os.path.join(b, "review", f"{sid}_excluded.nii.gz"))
    pd.DataFrame(rows).to_csv(os.path.join(b, "review", f"{sid}_candidates.csv"), index=False)
    pd.DataFrame([dict(excl_id=e, reason=f"E12@v5.3: SENTINEL_RULE {e}", hemi="L", region="ctx-lh-precuneus", volume_mm3=8.0, **{k_: float(v) for k_, v in SENT.items() if k_ in ("css_evidence", "vein_evidence")})
                  for e in EXCL_IDS]).to_csv(os.path.join(b, "review", f"{sid}_excluded.csv"), index=False)
    json.dump(dict(model="SENTINEL_PERCIVAL_MODEL", study_score=dict(total=3, L_score=1, R_score=2, n_called=2), candidates={str(c): 0.5 for c in TRUE_IDS}),
              open(os.path.join(b, "percival", "scores", f"{sid}.json"), "w"))
    json.dump(dict(reports=[dict(cand_id=c, note="SENTINEL_USCORE") for c in TRUE_IDS]), open(os.path.join(b, "uscore", "reports", f"{sid}.json"), "w"))
    json.dump(dict(multifocality_0_4="SENTINEL_AI_SCORE"), open(os.path.join(b, "review", f"{sid}_score_ai.json"), "w"))
    # another reviewer's earlier work (must stay invisible to a blind reader)
    pd.DataFrame([dict(cand_id=4101, call="cSS", comment="SENTINEL_OTHER_COMMENT", reviewer="Reader B", time="2026-11-01 10:00:00",
                       vox_i=rows[0]["vox_i"], vox_j=rows[0]["vox_j"], vox_k=rows[0]["vox_k"], volume_mm3=rows[0]["volume_mm3"], fine_code="")]).to_csv(
        os.path.join(b, "review", f"{sid}_calls_Reader_B.csv"), index=False)
    m = pd.DataFrame([dict(missed_id=1, reviewer="Reader B", time="2026-11-01 10:00:00", vox_i=1, vox_j=1, vox_k=1, x_mm=1.0, y_mm=1.0, z_mm=1.0, can_i=1,
                           can_j=1, can_k=1, comment="SENTINEL_OTHER_MISSED", plane="axial", slice="1", shape="point", points="[]",
                           detector_fate="overlaps shown candidate #4101; excluded object 61: SENTINEL_RULE")])
    m.to_csv(os.path.join(b, "review", f"{sid}_missed.csv"), index=False)
    stub = os.path.join(b, "stubbin"); os.makedirs(stub, exist_ok=True)
    for tool in ("screencapture", "open", "xdg-open"):                       # no screenshot is taken and no window opened by the tests
        with open(os.path.join(stub, tool), "w") as f: f.write("#!/bin/sh\nfor a; do last=$a; done; [ -n \"$last\" ] && : > \"$last\" 2>/dev/null; exit 0\n")
        os.chmod(os.path.join(stub, tool), 0o755)
    return rows


class Server:
    def __init__(self, base, *flags, sid="S1"):
        with socket.socket() as so:
            so.bind(("127.0.0.1", 0)); port = so.getsockname()[1]
        env = dict(os.environ, CSS_BASE=base, HOME=os.path.join(base, "home"), PYTHONWARNINGS="ignore", PATH=os.path.join(base, "stubbin") + os.pathsep + os.environ["PATH"])
        self.p = subprocess.Popen([sys.executable, os.path.join(S, "review_web.py"), sid, "--no-browser", "--port", str(port), *flags],
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
        line = self.p.stdout.readline(); self.log = [line]
        if "http://" not in line: raise RuntimeError(line + self.p.stdout.read()[-2000:])
        self.u = "http://" + line.split("http://")[1].split()[0].rstrip("/")
        threading.Thread(target=lambda: [self.log.append(x) for x in self.p.stdout], daemon=True).start()

    def raw(self, method, path, body=None):
        r = urllib.request.Request(self.u + path, None if body is None else json.dumps(body).encode(),
                                   {"Content-Type": "application/json", "X-CSS": "1"} if body is not None else {}, method=method)
        for _ in range(240):
            try:
                with urllib.request.urlopen(r, timeout=120) as h: return h.status, h.read()
            except urllib.error.HTTPError as e: return e.code, e.read()
            except OSError: time.sleep(0.25)
        raise RuntimeError("no answer")

    def get(self, path): return json.loads(self.raw("GET", path)[1])
    def post(self, path, d): return json.loads(self.raw("POST", path, d)[1])

    def stop(self):
        if self.p.poll() is None: self.p.terminate()
        try: self.p.wait(10)
        except subprocess.TimeoutExpired: self.p.kill()


PHRASES = {"I suspect", "trained ranking model", "rule-based evidence", "overlaps shown candidate", "excluded object"}   # also UI wording in the page


def leaks(blob, static=False):
    t = blob.decode("utf-8", "replace") if isinstance(blob, (bytes, bytearray)) else blob
    return [x for x in STRINGS if x in t and not (static and x in PHRASES)]


def every_route(srv, rev, base):
    """call EVERY route once (as a reviewer would) -> [(method, path, status, body bytes)]"""
    q = f"study=S1&reviewer={urllib.parse.quote(rev)}"; out = []
    def g(path): st, b = srv.raw("GET", path); out.append(("GET", path, st, b)); return b
    def p(path, d): st, b = srv.raw("POST", path, d); out.append(("POST", path, st, b)); return b
    g("/"); g("/morph3d.js"); g("/api/vset"); g("/api/vol?study=S1&seq=swi"); g("/api/seqmeta?study=S1&seq=swi")
    m = json.loads(g(f"/api/meta?{q}")); mv = json.loads(g(f"/api/meta?{q}&mode=validation")); g("/api/meta?study=S1&reviewer=")
    g(f"/api/labels?{q}"); g(f"/api/labels?{q}&mode=validation")
    first = m["cands"][0]["id"]
    for r in ("struct3d", "uscore", "morph3d"): g(f"/api/{r}?{q}&cand={first}")
    p("/api/vset", dict(theme="dark")); p("/api/reviewer", dict(name=rev))
    p("/api/screencap", dict(study="S1", reviewer=rev, folder=os.path.join(base, "snaps"), x=0, y=0, w=10, h=10))
    p("/api/snapshot", dict(study="S1", reviewer=rev, image="data:image/png;base64," + "A" * 400, name="s.png", folder=os.path.join(base, "snaps"), sidecar=True,
                            meta=dict(cand_id=first, meter="0.987654", cur=[1, 1, 1], plane="axial", slice=1, seq="SWI")))
    p("/api/openfolder", dict(study="S1", reviewer=rev, path=os.path.join(base, "snaps")))
    p("/api/import", dict(study="S1", reviewer=rev, source="S1_calls_Reader_B.csv"))
    p("/api/primary", dict(study="S1", reviewer=rev, name=rev))
    p("/api/call", dict(study="S1", reviewer=rev, cand_id=first, call="cSS", meter="0.987654", mode=""))
    p("/api/call", dict(study="S1", reviewer=rev, cand_id=first, comment="mine"))
    for c in mv["cands"]:
        if c["id"] not in [x["id"] for x in m["cands"]]: p("/api/call", dict(study="S1", reviewer=rev, cand_id=c["id"], call="Normal", mode="validation"))
    p("/api/call", dict(study="S1", reviewer=rev, cand_id=999999, call="cSS"))
    p("/api/missed", dict(study="S1", reviewer=rev, action="add", ijk=[2, 2, 2], comment="my mark"))
    p("/api/missed", dict(study="S1", reviewer=rev, action="add", ijk=m["cands"][0]["centre"], comment="on a candidate"))   # its fate names the candidate
    p("/api/missed", dict(study="S1", reviewer=rev, action="delete", id=1))
    p("/api/missed", dict(study="S1", reviewer=rev, action="add"))                       # malformed: an internal error
    p("/api/finish", dict(study="S1", reviewer=rev, final=False))
    p("/api/unblind", dict(study="S1", reviewer=rev))
    return out


class TestBlindRead(unittest.TestCase):
    def setUp(self):
        self.b = tempfile.mkdtemp(prefix="p3a2_", dir=os.environ["CSS_BASE"]); self.rows = build(self.b)

    def test_route_table_covers_every_handled_route(self):
        import review_web as RW
        tree = ast.parse(open(os.path.join(S, "review_web.py")).read()); handled = set()
        for cls in [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "H"]:
            for fn in [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in ("do_GET", "do_POST")]:
                meth = fn.name[3:]
                for node in ast.walk(fn):
                    if isinstance(node, ast.Compare) and isinstance(node.left, ast.Attribute) and node.left.attr == "path":
                        for c in node.comparators:
                            if isinstance(c, ast.Constant) and isinstance(c.value, str): handled.add((meth, c.value))
        self.assertEqual(handled, set(RW.ROUTES), "every handled route must be classified, and every classified route handled")
        self.assertTrue(all(v in ("static", "image", "settings", "redacted", "refused", "write") for v in RW.ROUTES.values()))

    def test_no_route_leaks_ai_content_or_original_ids_during_the_blind_read(self):
        srv = Server(self.b, "--show-excluded")
        try:
            out = every_route(srv, "Reader A", self.b)
        finally: srv.stop()
        bad = [(m, p, st, leaks(b, p in ("/", "/morph3d.js"))) for m, p, st, b in out if leaks(b, p in ("/", "/morph3d.js"))]
        self.assertEqual(bad, [])
        for m_, p_, st_, b_ in out:                                         # missed marks: never the detector's fate during the blind read
            if p_.startswith(("/api/meta", "/api/missed", "/api/finish")) and st_ == 200:
                self.assertNotIn("detector_fate", b_.decode(), p_)
        lab = [x for x in out if x[1].startswith("/api/labels")]
        for _, _, st, body in lab:
            vals = set(np.unique(np.frombuffer(body, "<u2")).tolist()) - {0}
            self.assertTrue(vals and max(vals) <= len(TRUE_IDS) + len(EXCL_IDS), vals)
        st = {(m, p.split("?")[0]): s_ for m, p, s_, _ in out}
        for r in ("/api/struct3d", "/api/uscore", "/api/morph3d"): self.assertEqual(st[("GET", r)], 403)
        self.assertEqual(st[("POST", "/api/import")], 403); self.assertEqual(st[("POST", "/api/unblind")], 409)
        self.assertEqual(leaks("".join(srv.log), static=True), [], "server log (data sentinels; its fixed start-up text names the options)")
        # the review log is an internal provenance record: it keeps the ORIGINAL candidate ids by design (not served); it must hold no AI value
        rl = open(os.path.join(self.b, "review", "S1_review_log.csv")).read()
        self.assertEqual([x for x in leaks(rl) if not x.isdigit()], [], "review log (the browser's meter is not recorded)")
        side = [f for f in os.listdir(os.path.join(self.b, "snaps")) if f.endswith(".txt")]
        self.assertTrue(side); self.assertEqual(leaks(open(os.path.join(self.b, "snaps", side[0])).read()), [], "snapshot side-car")

    def test_after_a_completed_read_and_unblind_the_same_routes_show_them(self):
        srv = Server(self.b, "--show-excluded")
        try:
            m = srv.get("/api/meta?study=S1&reviewer=Reader%20A")
            self.assertTrue(m["blind"])
            for c in m["cands"]: srv.post("/api/call", dict(study="S1", reviewer="Reader A", cand_id=c["id"], call="Unsure"))
            r = srv.post("/api/finish", dict(study="S1", reviewer="Reader A", final=True, read_mode="second look", meter_visible=1))
            self.assertTrue(r.get("initial_complete"))
            fin = json.load(open(os.path.join(self.b, "review", "S1_final_Reader_A.json")))
            self.assertEqual((fin["read_mode"], fin["meter_visible"], fin["read_phase"], fin["ai_visible"]), ("validation", 0, "initial", False))
            self.assertEqual(srv.post("/api/unblind", dict(study="S1", reviewer="Reader A"))["read_phase"]["phase"], "second_look")
            out = every_route(srv, "Reader A", self.b)
        finally: srv.stop()
        seen = set(sum((leaks(b) for _, _, _, b in out), []))
        for must in ("0.246802", "SENTINEL_PERCIVAL", "SENTINEL_USCORE", "SENTINEL_RULE", "SENTINEL_OTHER_MISSED", "4101", "10061"):
            self.assertIn(must, seen, "the leak search must be able to see this channel")

    def test_a_partial_final_save_does_not_complete_the_read(self):
        srv = Server(self.b)
        try:
            m = srv.get("/api/meta?study=S1&reviewer=Reader%20A")
            for c in m["cands"][:-1]: srv.post("/api/call", dict(study="S1", reviewer="Reader A", cand_id=c["id"], call="Normal"))
            self.assertFalse(srv.post("/api/finish", dict(study="S1", reviewer="Reader A", final=True)).get("initial_complete"))
            r = srv.post("/api/unblind", dict(study="S1", reviewer="Reader A"))
            self.assertIn("initial read is complete", r["error"])
            self.assertTrue(srv.get("/api/meta?study=S1&reviewer=Reader%20A")["blind"])
        finally: srv.stop()

    def test_open_flag_and_client_parameters_cannot_unblind(self):
        srv = Server(self.b, "--open")
        try:
            for path in ("/api/meta?study=S1&reviewer=Reader%20C", "/api/meta?study=S1&reviewer=Reader%20C&mode=", "/api/meta?study=S1&reviewer=Reader%20C&mode=open&phase=second_look&open=1"):
                st, body = srv.raw("GET", path); j = json.loads(body)
                self.assertTrue(j["blind"]); self.assertTrue(j["open_read"]); self.assertEqual(leaks(body), [], path)
            st, body = srv.raw("POST", "/api/call", dict(study="S1", reviewer="Reader C", cand_id=1, call="cSS", mode="", read_phase="second_look", open=True))
            self.assertEqual(leaks(body), [])
        finally: srv.stop()
        ev, _ = RIO.read_journal(RIO.journal_path(self.b, "S1", "Reader C"))
        e = [x for x in ev if x.get("kind") == "call"][-1]
        self.assertEqual((e["read_phase"], e["ai_visible"]), ("initial", False))
        self.assertNotIn("open", e); self.assertEqual(e["client_meter"], "")

    def test_phase_and_blinded_ids_are_recorded_by_the_server(self):
        srv = Server(self.b)
        try:
            m = srv.get("/api/meta?study=S1&reviewer=Reader%20A")
            bid = m["cands"][0]["id"]; srv.post("/api/call", dict(study="S1", reviewer="Reader A", cand_id=bid, call="Vessel", meter="0.987654"))
        finally: srv.stop()
        mp = RB.stored_mapping(self.b, "S1", "Reader A"); key2true = {RB.cand_key(r): r["cand_id"] for r in self.rows}
        true_of = {v: key2true[k] for k, v in mp.items() if k in key2true}
        ev, probs = RIO.read_journal(RIO.journal_path(self.b, "S1", "Reader A")); self.assertEqual(probs, [])
        e = [x for x in ev if x.get("kind") == "call"][-1]
        self.assertEqual((e["read_phase"], e["ai_visible"], e["blind_id"], e["cand_id"]), ("initial", False, bid, true_of[bid]))
        calls = pd.read_csv(os.path.join(self.b, "review", "S1_calls_Reader_A.csv"))
        self.assertEqual(int(calls.cand_id.iloc[0]), true_of[bid])            # stored under the ORIGINAL id (internal mapping preserved)

    def test_blinded_ids_are_stable_per_reviewer_and_extend_after_redetection(self):
        srv = Server(self.b)
        try: a1 = {c["centre"][0]: c["id"] for c in srv.get("/api/meta?study=S1&reviewer=Reader%20A")["cands"]}
        finally: srv.stop()
        self.assertEqual(sorted(a1.values()), list(range(1, len(TRUE_IDS) + 1)))
        build(self.b, extra=1)                                                 # a re-detection adds one object
        srv = Server(self.b)
        try: a2 = {c["centre"][0]: c["id"] for c in srv.get("/api/meta?study=S1&reviewer=Reader%20A")["cands"]}
        finally: srv.stop()
        self.assertEqual({k: a2[k] for k in a1}, a1)
        self.assertEqual(sorted(set(a2.values()) - set(a1.values())), [len(TRUE_IDS) + 1])

    def test_label_volume_carries_the_blinded_id_at_each_candidate(self):
        srv = Server(self.b)
        try:
            m = srv.get("/api/meta?study=S1&reviewer=Reader%20A")
            L = np.frombuffer(srv.raw("GET", "/api/labels?study=S1&reviewer=Reader%20A")[1], "<u2").reshape((40, 32, 20), order="F")
        finally: srv.stop()
        for c in m["cands"]: self.assertEqual(int(L[tuple(c["centre"])]), c["id"])

    def test_identifiers_are_decorrelated_from_detector_rank(self):
        rs = []
        for _ in range(400):
            keys = [f"k{i}" for i in range(12)]; m = RB._assign({}, keys)
            r = np.argsort(np.argsort([m[k] for k in keys])); rs.append(np.corrcoef(np.arange(12), r)[0, 1])
        self.assertLess(abs(float(np.mean(rs))), 0.05)
        self.assertLess(sum(1 for x in rs if x > 0.999), 3)

    def test_anonymous_viewer_is_blind_and_writes_nothing(self):
        srv = Server(self.b)
        try: st, body = srv.raw("GET", "/api/meta?study=S1&reviewer=")
        finally: srv.stop()
        self.assertTrue(json.loads(body)["blind"]); self.assertEqual(leaks(body), [])
        self.assertEqual([f for f in os.listdir(os.path.join(self.b, "review")) if "_events_" in f], [])

    def test_other_reviewers_marks_cannot_be_deleted_blind(self):
        srv = Server(self.b)
        try:
            r = srv.post("/api/missed", dict(study="S1", reviewer="Reader A", action="delete", id=1))
            self.assertIn("no such missed-cSS mark of yours", r["error"])
        finally: srv.stop()
        self.assertIn("SENTINEL_OTHER_MISSED", open(os.path.join(self.b, "review", "S1_missed.csv")).read())

    def test_internal_errors_are_generic_and_logged_without_numbers(self):
        srv = Server(self.b)
        try:
            r = srv.post("/api/missed", dict(study="S1", reviewer="Reader A", action="add"))
            time.sleep(0.3)
        finally: srv.stop()
        self.assertRegex(r["error"], r"^the request could not be completed \(reference [0-9a-f]{8}\)$")
        lines = [l for l in srv.log if "[reviewer] error" in l]
        self.assertTrue(lines); self.assertFalse(re.search(r"\d", lines[0].split(":", 1)[1].replace(lines[0].split()[2], "")))

    def test_a_release_in_the_app_is_recorded_with_the_reviewers_calls(self):
        srv = Server(self.b)
        try:
            bid = srv.get("/api/meta?study=S1&reviewer=Reader%20A")["cands"][0]["id"]
            srv.post("/api/call", dict(study="S1", reviewer="Reader A", cand_id=bid, call="Normal"))
            with RIO.study_lock(self.b, "S1"):                               # what app/blind_gate.release() journals
                RIO.journal_append(self.b, "S1", RB.APP_RELEASE, "ai_released", by="me", reason="test")
            srv.post("/api/call", dict(study="S1", reviewer="Reader A", cand_id=bid, call="Vessel"))
        finally: srv.stop()
        ev, _ = RIO.read_journal(RIO.journal_path(self.b, "S1", "Reader A"))
        flags = [e["ai_released_in_app"] for e in ev if e.get("kind") == "call"]
        self.assertEqual(flags, [False, True])

    def test_the_app_no_longer_launches_the_reviewer_with_open(self):
        src = open(os.path.join(ROOT, "app", "css_app.py")).read()
        line = [l for l in src.splitlines() if 'if kind == "review": cmd = [sys.executable, f"{SC}/review_web.py"' in l][0]
        self.assertNotIn('"--open"', line)


if __name__ == "__main__":
    unittest.main()
