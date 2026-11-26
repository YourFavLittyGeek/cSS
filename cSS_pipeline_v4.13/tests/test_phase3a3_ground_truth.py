"""Phase 3A.3-3A.6 tests: reviewer roles, expert consensus + adjudication, provenance classes, journal-verified rebuilds, per-reviewer missed-cSS
storage + whole-study search, closed bypasses (app missed-lesion op, review_css.py, reviewer-window primary), Percival ground-truth gating, and
the historical-data migration (plan / apply / rollback). Synthetic projects only. Isolated (tests/_isolation.py)."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import glob
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
S = os.path.join(ROOT, "scripts")
for p in (S, os.path.join(ROOT, "app"), os.path.join(ROOT, "unified_engine"), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)
import call_ledger as CL                                                  # noqa: E402
import review_io as RIO                                                   # noqa: E402
import review_roles as RR                                                 # noqa: E402
import review_migrate as MG                                               # noqa: E402
from test_phase3a2_blind import Server, build                             # noqa: E402

FP = ["vox_i", "vox_j", "vox_k", "volume_mm3"]
COLS = ["cand_id", "call", "comment", "reviewer", "time"] + FP + ["fine_code"]


def proj():
    b = tempfile.mkdtemp(prefix="p3a3_", dir=os.environ["CSS_BASE"])
    for d in ("review", "home"): os.makedirs(os.path.join(b, d))
    cand = pd.DataFrame([dict(cand_id=i, vox_i=10 * i, vox_j=5, vox_k=5, volume_mm3=20.0 + i) for i in range(1, 7)])
    cand.to_csv(os.path.join(b, "review", "S1_candidates.csv"), index=False)
    return b, cand


def write(b, cand, rev, calls, phase="initial", vis=False, released=False, kind="call", comment=""):
    rows = [dict(cand_id=c, call=v, comment=comment, reviewer=rev, time=f"2026-11-23 10:00:{c:02d}", **{f: cand.set_index("cand_id").loc[c, f] for f in FP}, fine_code="")
            for c, v in calls.items()]
    p = os.path.join(b, "review", f"S1_calls_{RR.slug(rev)}.csv")
    old = pd.read_csv(p).to_dict("records") if os.path.exists(p) else []
    rows = [r for r in old if int(r["cand_id"]) not in calls] + rows
    with RIO.study_lock(b, "S1"):
        RIO.ensure_table(b, "S1", rev, "calls", p)
        RIO.write_table(b, "S1", rev, "calls", p, pd.DataFrame(rows, columns=COLS), ["cand_id"] + FP, kind, read_phase=phase, ai_visible=vis, ai_released_in_app=released)


def expert(b, *names):
    for n in names: RR.set_role(b, n, "expert", "admin", "fixture", RR.CONFIRM_ROLE)


def complete(b, *names, sid="S1"):
    """the reviewers completed their (blind) review of the study - what the reviewer server journals on a complete final save"""
    for n in names:
        with RIO.study_lock(b, sid): RIO.journal_append(b, sid, n, "initial_completed", n_candidates=0, n_called=0)


def st(b): return {r["cand_id"]: r for r in CL.effective(b, "S1")["rows"]}


class TestRoles(unittest.TestCase):
    def test_roles_need_confirmation_reason_and_are_never_automatic(self):
        b, cand = proj(); write(b, cand, "Dr A", {1: "cSS"})
        self.assertEqual(RR.role_of(b, "Dr A"), "unknown")                    # making calls never promotes
        for bad in (dict(confirm="yes"), dict(reason=""), dict(by="")):
            kw = dict(by="admin", reason="r", confirm=RR.CONFIRM_ROLE); kw.update(bad)
            with self.assertRaises((PermissionError, ValueError)): RR.set_role(b, "Dr A", "expert", **kw)
        with self.assertRaises(ValueError): RR.set_role(b, "Dr A", "chief", "admin", "r", RR.CONFIRM_ROLE)
        with self.assertRaises(PermissionError): RR.set_adjudicator(b, "Dr A", True, "admin", "r", RR.CONFIRM_ADJUDICATOR)   # not an expert
        expert(b, "Dr A"); RR.set_role(b, "Dr A", "trainee", "admin", "demoted", RR.CONFIRM_ROLE)
        h = RR.history(b); self.assertEqual(h["problems"], [])
        self.assertEqual([(e["role"], e["previous"]) for e in h["events"]], [("expert", "unknown"), ("trainee", "expert")])
        self.assertEqual(RR.role_of(b, "Dr A"), "trainee")


class TestConsensus(unittest.TestCase):
    def setUp(self):
        self.b, self.cand = proj(); b, c = self.b, self.cand
        write(b, c, "Dr A", {1: "cSS", 2: "Vessel", 3: "Unsure", 4: "cSS", 6: "Normal"})
        write(b, c, "Dr B", {1: "cSS", 2: "Normal", 3: "Unsure", 4: "Vessel"})
        write(b, c, "Trainee T", {5: "cSS", 4: "cSS"}); write(b, c, "Dr C", {6: "Artifact"}, comment="[imported from Dr_A] ")
        expert(b, "Dr A", "Dr B", "Dr C"); RR.set_role(b, "Trainee T", "trainee", "admin", "fixture", RR.CONFIRM_ROLE); complete(b, "Dr A", "Dr B")

    def test_statuses(self):
        s = st(self.b)
        self.assertEqual({k: v["status"] for k, v in s.items()},
                         {1: "resolved", 2: "resolved", 3: "abstained", 4: "disagreement", 5: "no_expert", 6: "incomplete"})
        self.assertTrue(s[2]["subtype_mixed"]); self.assertEqual(s[2]["effective_call"], "Normal")
        self.assertEqual(s[6]["experts_missing"], ["Dr B"])                    # Dr B completed the review but has no call on #6: not resolved by Dr A
        self.assertEqual(s[6]["n_expert_calls"], 1)                           # the imported call of Dr C is not an independent review

    def test_only_completed_expert_reviews_take_part(self):
        b, c = self.b, self.cand
        write(b, c, "Dr D", {1: "Vessel"}); expert(b, "Dr D")                 # an expert whose review is not completed
        s = st(b); self.assertEqual((s[1]["status"], s[1]["experts_pending"]), ("resolved", ["Dr D"]))
        complete(b, "Dr D"); self.assertEqual(st(b)[1]["status"], "disagreement")         # once completed, the disagreement counts
        b2, c2 = proj(); write(b2, c2, "Dr E", {1: "cSS"}); expert(b2, "Dr E")
        self.assertEqual(st(b2)[1]["status"], "pending_review")

    def test_quorum_reference_and_removed_modes(self):
        CL.set_policy(self.b, "all", "", dict(mode="consensus", quorum=3))
        s = st(self.b); self.assertEqual((s[1]["status"], s[6]["status"]), ("insufficient", "incomplete"))
        CL.set_policy(self.b, "all", "", dict(mode="consensus", quorum=2)); self.assertEqual(st(self.b)[1]["status"], "resolved")
        CL.set_policy(self.b, "all", "", dict(mode="reference", reviewer="Dr B", fallback="none"))
        s = st(self.b); self.assertEqual((s[4]["status"], s[4]["effective_call"], s[6]["status"]), ("resolved", "Vessel", "no_expert"))
        for bad in (dict(mode="newest"), dict(mode="reviewer", reviewer="Dr A", fallback="newest")):
            with self.assertRaises(ValueError): CL.set_policy(self.b, "all", "", bad)
        with self.assertRaises(PermissionError): CL.set_policy(self.b, "all", "", dict(mode="reference", reviewer="Trainee T"))
        json.dump(dict(schema="call-policy/1.0", default=dict(mode="newest"), cohorts={}, studies={}, history=[]), open(CL.policy_path(self.b), "w"))
        self.assertEqual(CL.resolve(CL.load_policy(self.b), "S1")[0]["mode"], "consensus")              # old files read as consensus

    def test_shared_file_holds_only_resolved_and_disagreements_survive(self):
        CL.materialize(self.b, "S1", rescore=False)
        sh = pd.read_csv(os.path.join(self.b, "review", "S1_calls.csv"))
        self.assertEqual(sorted(sh.cand_id), [1, 2])
        self.assertIn("cSS", open(os.path.join(self.b, "review", "S1_calls_Dr_A.csv")).read())
        self.assertIn("Vessel", open(os.path.join(self.b, "review", "S1_calls_Dr_B.csv")).read())

    def test_adjudication(self):
        b = self.b; before = {p: open(p, "rb").read() for p in glob.glob(os.path.join(b, "review", "S1_calls_*.csv"))}
        with self.assertRaises(PermissionError): CL.adjudicate(b, "S1", 4, "cSS", "Dr A", "x")        # no adjudication permission yet
        RR.set_adjudicator(b, "Dr A", True, "admin", "senior", RR.CONFIRM_ADJUDICATOR)
        with self.assertRaises(ValueError): CL.adjudicate(b, "S1", 4, "Unsure", "Dr A", "x")
        with self.assertRaises(ValueError): CL.adjudicate(b, "S1", 4, "cSS", "Dr A", "")
        CL.adjudicate(b, "S1", 4, "cSS", "Dr A", "consensus meeting")
        s = st(b)[4]; self.assertEqual((s["status"], s["effective_call"], s["adjudication"]["by"]), ("adjudicated", "cSS", "Dr A"))
        self.assertEqual((s["provenance_class"], s["primary_eligible"]), ("adjudicated_post_3A", False))   # 3B policy: never automatically eligible
        self.assertEqual({p: open(p, "rb").read() for p in before}, before)   # reviewers' calls untouched
        CL.withdraw_adjudication(b, "S1", 4, "Dr A", "re-read"); self.assertEqual(st(b)[4]["status"], "disagreement")
        ev, probs = RIO.read_journal(RIO.journal_path(b, "S1", RR.ADJUDICATION))
        self.assertEqual(probs, []); self.assertEqual([e["kind"] for e in ev], ["adjudicate", "adjudication_withdrawn"])
        self.assertEqual(len(ev[0]["calls_seen"]), 3)

    def test_consolidation_removed(self):
        with self.assertRaises(PermissionError): CL.consolidate(self.b, ["S1"], CL.CONFIRM)


class TestProvenance(unittest.TestCase):
    def test_classes_and_primary_eligibility(self):
        b, cand = proj(); expert(b, "Dr A", "Dr H")
        write(b, cand, "Dr A", {1: "cSS", 2: "cSS"}, phase="initial", vis=False)
        write(b, cand, "Dr A", {2: "Normal"}, phase="second_look", vis=True)    # changed in the second look
        write(b, cand, "Dr A", {3: "Vessel"}, phase="initial", vis=False, released=True)
        complete(b, "Dr A")
        s = st(b)
        self.assertEqual({k: (s[k]["provenance_class"], s[k]["primary_eligible"]) for k in (1, 2, 3)},
                         {1: ("verified_blind_post_3A", True), 2: ("not_blind_post_3A", False), 3: ("not_blind_post_3A", False)})
        cand.to_csv(os.path.join(b, "review", "S2_candidates.csv"), index=False)        # a pre-3A read (no journal) with a final record
        pd.DataFrame([dict(cand_id=4, call="cSS", comment="", reviewer="Dr H", time="2025-01-01 10:00:00", **cand.set_index("cand_id").loc[4, FP].to_dict(), fine_code="")],
                     columns=COLS).to_csv(os.path.join(b, "review", "S2_calls_Dr_H.csv"), index=False)
        json.dump(dict(reviewer="Dr H", saved="2025-01-01"), open(os.path.join(b, "review", "S2_final_Dr_H.json"), "w"))
        r4 = lambda: {r["cand_id"]: r for r in CL.effective(b, "S2")["rows"]}[4]
        self.assertEqual((r4()["provenance_class"], r4()["primary_eligible"]), ("historical_blinding_unknown", False))
        with self.assertRaises(PermissionError): RR.verify_historical(b, "S2", "Dr H", "admin", "r", "e", "ok")
        with self.assertRaises(ValueError): RR.verify_historical(b, "S2", "Dr H", "admin", "r", "", RR.CONFIRM_VERIFY)
        with self.assertRaises(ValueError): RR.verify_historical(b, "S2", "Nobody", "admin", "r", "e", RR.CONFIRM_VERIFY)   # no review to verify
        RR.verify_historical(b, "S2", "Dr H", "admin", "audit of the 2025 read", "validation read, meter hidden (final record)", RR.CONFIRM_VERIFY)
        self.assertEqual((r4()["provenance_class"], r4()["primary_eligible"]), ("historical_blinding_verified", True))

    def test_verification_covers_only_the_calls_that_were_verified(self):
        b, cand = proj(); expert(b, "Dr H")
        p = os.path.join(b, "review", "S1_calls_Dr_H.csv")
        mk = lambda calls: pd.DataFrame([dict(cand_id=c, call=v, comment="", reviewer="Dr H", time="2025-01-01 10:00:00", **cand.set_index("cand_id").loc[c, FP].to_dict(), fine_code="")
                                         for c, v in calls], columns=COLS).to_csv(p, index=False)
        mk([(1, "cSS"), (2, "Vessel")])
        RR.verify_historical(b, "S1", "Dr H", "admin", "audit", "validation read", RR.CONFIRM_VERIFY)
        mk([(1, "Vessel"), (2, "Vessel"), (3, "cSS")])                       # edited outside the reviewer AFTER the verification
        s = st(b)
        self.assertEqual([s[k]["provenance_class"] for k in (1, 2, 3)], ["historical_blinding_unknown", "historical_blinding_verified", "historical_blinding_unknown"])

    def test_adjudicated_historical_label_and_snapshot_rows_stay_historical(self):
        b, cand = proj(); expert(b, "Dr H", "Dr K"); RR.set_adjudicator(b, "Dr K", True, "admin", "r", RR.CONFIRM_ADJUDICATOR); complete(b, "Dr H")
        pd.DataFrame([dict(cand_id=c, call=v, comment="", reviewer="Dr H", time="2025-01-01 10:00:00", **cand.set_index("cand_id").loc[c, FP].to_dict(), fine_code="")
                      for c, v in ((1, "cSS"), (2, "Vessel"))], columns=COLS).to_csv(os.path.join(b, "review", "S1_calls_Dr_H.csv"), index=False)
        write(b, cand, "Dr H", {3: "Normal"})                                  # first journaled change re-keys the old rows
        s = st(b)
        self.assertEqual([s[k]["provenance_class"] for k in (1, 2, 3)], ["historical_blinding_unknown", "historical_blinding_unknown", "verified_blind_post_3A"])
        CL.adjudicate(b, "S1", 1, "cSS", "Dr K", "reviewed the historical read")
        self.assertEqual((st(b)[1]["provenance_class"], st(b)[1]["primary_eligible"]), ("historical_adjudicated", False))   # 3B: kept, not eligible


class TestIntegrity(unittest.TestCase):
    def test_rebuild_refused_when_a_reviewer_file_differs_from_its_journal(self):
        b, cand = proj(); expert(b, "Dr A"); write(b, cand, "Dr A", {1: "cSS"})
        CL.materialize(b, "S1", rescore=False); shared = open(os.path.join(b, "review", "S1_calls.csv"), "rb").read()
        p = os.path.join(b, "review", "S1_calls_Dr_A.csv"); open(p, "a").write("garbage,,,\n")
        self.assertTrue(CL.integrity(b, "S1"))
        rec = CL.materialize(b, "S1", rescore=False)
        self.assertTrue(rec["refused"]); self.assertEqual(open(os.path.join(b, "review", "S1_calls.csv"), "rb").read(), shared)
        self.assertTrue(CL.effective(b, "S1")["problems"])


class TestReviewerMissedAndWholeStudy(unittest.TestCase):
    def setUp(self):
        self.b = tempfile.mkdtemp(prefix="p3a3w_", dir=os.environ["CSS_BASE"]); build(self.b)

    def test_missed_marks_drawn_in_the_viewer_are_saved(self):
        """2026-11-25 regression: the page sent the plane INDEX (0 / 1 / 2) and the server accepted only names - every drawn mark was refused
        ('invalid shape or plane') and the user's 45 reviews saved none. The request below is exactly what the page sends now and before."""
        b = self.b; srv = Server(b)
        try:
            for plane in (0, "axial", 2):
                r = srv.post("/api/missed", dict(study="S1", reviewer="Reader P", mode="", action="add", plane=plane, slice=5, shape="rect",
                                                 strokes=[[[4.2, 4.0, 5.0], [7.5, 6.8, 5.0]]], comment=""))
                self.assertTrue(r.get("ok"), (plane, r))
            r = srv.post("/api/missed", dict(study="S1", reviewer="Reader P", mode="", action="add", plane=1, slice=5, shape="pen",
                                             strokes=[[[4.0, 5.0, 4.0], [5.0, 5.0, 5.0], [6.0, 5.0, 6.0]]], comment="pen"))
            self.assertTrue(r.get("ok"), r)
            self.assertIn("error", srv.post("/api/missed", dict(study="S1", reviewer="Reader P", action="add", plane="oblique", shape="rect",
                                                                strokes=[[[4, 4, 5], [6, 6, 5]]])))
        finally: srv.stop()
        own = pd.read_csv(os.path.join(b, "review", "S1_missed_by_Reader_P.csv"))
        self.assertEqual(list(own.plane), ["axial", "axial", "sagittal", "coronal"]); self.assertEqual(list(own.status), ["active"] * 4)
        shared = pd.read_csv(os.path.join(b, "review", "S1_missed.csv"))                     # what ALBUS / PERCIVAL read
        self.assertEqual(int((shared.reviewer == "Reader P").sum()), 4)
        html = open(os.path.join(ROOT, "scripts", "review_web.html")).read()
        self.assertIn('plane:PLN[d.k].toLowerCase()', html)                                 # the page sends the plane name
        for k in ('if(t!=="miss")flushDraft();', 'if(tool==="miss"){flushDraft();setTool("pan");return}', "await PENDING_MISS"):
            self.assertIn(k, html)                                                           # moving on saves the drawn mark, never drops it

    def test_missed_marks_per_reviewer_tombstones_no_reuse_validation_legacy_kept(self):
        b = self.b; legacy = open(os.path.join(b, "review", "S1_missed.csv"), "rb").read()
        srv = Server(b)
        try:
            a1 = srv.post("/api/missed", dict(study="S1", reviewer="Reader A", action="add", ijk=[5, 5, 5], comment="one"))
            self.assertTrue(a1["ok"], a1)
            ids = sorted(r["missed_id"] for r in srv.get("/api/meta?study=S1&reviewer=Reader%20A")["missed"])
            srv.post("/api/missed", dict(study="S1", reviewer="Reader A", action="delete", id=ids[-1]))
            a3 = srv.post("/api/missed", dict(study="S1", reviewer="Reader C", action="add", ijk=[6, 6, 6], comment="two"))
            for bad in (dict(action="add", ijk=[999, 1, 1]), dict(action="add", ijk=["x", 1, 1]), dict(action="add", ijk=[1, 1, 1], shape="blob"),
                        dict(action="explode"), dict(action="add", strokes=[[[1, 1, 1]] * 20001]), dict(action="delete", id="abc")):
                r = srv.post("/api/missed", dict(study="S1", reviewer="Reader A", **bad)); self.assertIn("error", r, bad)
            self.assertIn("recorded before Phase 3A", srv.post("/api/missed", dict(study="S1", reviewer="Reader A", action="delete", id=1))["error"])
        finally: srv.stop()
        ra = pd.read_csv(os.path.join(b, "review", "S1_missed_by_Reader_A.csv")); rc = pd.read_csv(os.path.join(b, "review", "S1_missed_by_Reader_C.csv"))
        self.assertEqual(list(ra.status), ["deleted"]); self.assertGreater(int(rc.missed_id.iloc[0]), int(ra.missed_id.iloc[0]))   # never reused
        self.assertEqual(open(os.path.join(b, "review", "S1_missed_legacy.csv"), "rb").read(), legacy)                         # kept byte for byte
        d = pd.read_csv(os.path.join(b, "review", "S1_missed.csv"))
        self.assertEqual(sorted(d.comment), ["SENTINEL_OTHER_MISSED", "two"]); self.assertEqual(sorted(d.source), ["legacy", "reviewer"])
        open(os.path.join(b, "review", "S1_missed.csv"), "a").write("999,intruder,,1,1,1\n")               # changed outside the reviewer
        srv = Server(b)
        try: srv.post("/api/missed", dict(study="S1", reviewer="Reader C", action="add", ijk=[7, 7, 7], comment="three"))
        finally: srv.stop()
        ext = glob.glob(os.path.join(b, "review", "S1_missed_external_*.csv")); self.assertEqual(len(ext), 1)
        self.assertIn("intruder", open(ext[0]).read()); self.assertNotIn("intruder", open(os.path.join(b, "review", "S1_missed.csv")).read())

    def test_whole_study_search_shows_no_detector_output_and_records_independence(self):
        b = self.b; srv = Server(b)
        try:
            m = srv.get("/api/meta?study=S1&reviewer=Reader%20W&mode=wholestudy")
            self.assertEqual((m["cands"], m["calls"], m["whole_study"]["detector_seen_before"]), ([], {}, False))
            L = np.frombuffer(srv.raw("GET", "/api/labels?study=S1&reviewer=Reader%20W&mode=wholestudy")[1], "<u2"); self.assertFalse(L.any())
            self.assertEqual(srv.post("/api/wholestudy", dict(study="S1", reviewer="Reader V", action="complete"))["error"][:9], "open the ")
            srv.post("/api/missed", dict(study="S1", reviewer="Reader W", action="add", ijk=[4, 4, 4], mode="wholestudy"))
            r = srv.post("/api/wholestudy", dict(study="S1", reviewer="Reader W", action="complete"))
            self.assertEqual((r["whole_study"]["completed"], r["whole_study"]["n_marks"]), (True, 1))
            srv.get("/api/meta?study=S1&reviewer=Reader%20X")                     # candidate review first ...
            self.assertTrue(srv.get("/api/meta?study=S1&reviewer=Reader%20X&mode=wholestudy")["whole_study"]["detector_seen_before"])   # ... recorded
        finally: srv.stop()
        own = pd.read_csv(os.path.join(b, "review", "S1_missed_by_Reader_W.csv")); self.assertEqual(list(own.context), ["whole_study"])

    def test_reviewer_window_cannot_set_primary_and_no_automatic_primary(self):
        srv = Server(self.b)
        try:
            bid = srv.get("/api/meta?study=S1&reviewer=Reader%20A")["cands"][0]["id"]
            srv.post("/api/call", dict(study="S1", reviewer="Reader A", cand_id=bid, call="cSS"))
            st_, body = srv.raw("POST", "/api/primary", dict(study="S1", reviewer="Reader A", name="Reader A"))
        finally: srv.stop()
        self.assertEqual(st_, 403); self.assertFalse(os.path.exists(os.path.join(self.b, "review", "S1_primary.json")))


class TestClosedBypasses(unittest.TestCase):
    def test_app_missed_lesion_op_is_disabled(self):
        import css_app
        p = os.path.join(css_app.B, "review", "BYP_missed.csv")
        r = css_app.pg_post("missed_lesion", dict(study_id="BYP", reviewer_id="x", vox_i=1, vox_j=1, vox_k=1, comment="a,b"))
        self.assertFalse(r["ok"]); self.assertIn("disabled", r["error"]); self.assertFalse(os.path.exists(p))
        r = css_app.pg_post("missed_lesion", dict(study_id="../../escape", reviewer_id="x")); self.assertFalse(r["ok"])

    def test_review_css_saves_only_provenanced_calls(self):
        b = tempfile.mkdtemp(prefix="p3a3c_", dir=os.environ["CSS_BASE"]); build(b)
        cp = os.path.join(b, "review", "S1_candidates.csv"); c = pd.read_csv(cp)
        for k in ("surface_alignment", "mirror_dark_frac", "vein_tree_mm"): c[k] = 0.5          # the detector columns review_css.py displays
        c.to_csv(cp, index=False)
        env = dict(os.environ, CSS_BASE=b, CSS_REVIEW_TEST="1", MPLBACKEND="Agg", HOME=os.path.join(b, "home"))
        calls_before = {p: open(p, "rb").read() for p in glob.glob(os.path.join(b, "review", "S1_calls*.csv"))}
        r = subprocess.run([sys.executable, os.path.join(S, "review_css.py"), "S1", "--redo"], capture_output=True, text=True, env=env)
        self.assertIn("decisions NOT saved", r.stdout + r.stderr)
        self.assertEqual({p: open(p, "rb").read() for p in glob.glob(os.path.join(b, "review", "S1_calls*.csv"))}, calls_before)   # nothing written
        self.assertEqual(glob.glob(os.path.join(b, "review", "S1_events_*.jsonl")), [])
        r = subprocess.run([sys.executable, os.path.join(S, "review_css.py"), "S1", "--redo", "--reviewer", "Tester"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        ev, _ = RIO.read_journal(RIO.journal_path(b, "S1", "Tester"))
        e = [x for x in ev if x.get("kind") == "review_css"][-1]
        self.assertEqual((e["read_phase"], e["ai_visible"], e["tool"]), ("unblinded_legacy", True, "review_css.py"))
        s = {x["cand_id"]: x for x in CL.effective(b, "S1")["rows"]}
        self.assertTrue(all(x["status"] == "no_expert" for x in s.values() if x["history"]))          # Tester is not an expert
        self.assertFalse(any(x["primary_eligible"] for x in s.values()))


class TestPercivalGating(unittest.TestCase):
    def test_only_eligible_expert_ground_truth_reaches_training(self):
        import css_app; css_app.pg_init(); PG = css_app.PG; B = css_app.B
        os.makedirs(os.path.join(B, "review"), exist_ok=True)
        cand = pd.DataFrame([dict(cand_id=i, vox_i=10 * i, vox_j=5, vox_k=5, volume_mm3=20.0 + i) for i in range(1, 6)])
        cand.to_csv(os.path.join(B, "review", "GT1_candidates.csv"), index=False)
        def w(rev, calls, **kw):
            rows = [dict(cand_id=c, call=v, comment="", reviewer=rev, time="2026-11-23 10:00:00", **cand.set_index("cand_id").loc[c, FP].to_dict(), fine_code="") for c, v in calls.items()]
            p = os.path.join(B, "review", f"GT1_calls_{RR.slug(rev)}.csv")
            with RIO.study_lock(B, "GT1"): RIO.write_table(B, "GT1", rev, "calls", p, pd.DataFrame(rows, columns=COLS), ["cand_id"] + FP, "call", **kw)
        w("Exp One", {1: "cSS", 2: "Vessel", 3: "cSS"}, read_phase="initial", ai_visible=False)
        w("Exp Two", {1: "cSS", 2: "Vessel", 3: "Normal"}, read_phase="initial", ai_visible=False)
        w("Novice", {4: "cSS"}, read_phase="initial", ai_visible=False)
        for n in ("Exp One", "Exp Two"): RR.set_role(B, n, "expert", "admin", "fixture", RR.CONFIRM_ROLE); complete(B, n, sid="GT1")
        pd.DataFrame([dict(missed_id=1, reviewer="Novice", time="t", vox_i=1, vox_j=1, vox_k=1, x_mm=1, y_mm=1, z_mm=1, can_i=1, can_j=1, can_k=1, comment="",
                           plane="axial", slice=1, shape="point", points="[]", detector_fate="", context="", read_phase="initial", ai_visible="False", source="reviewer")]
                     ).to_csv(os.path.join(B, "review", "GT1_missed.csv"), index=False)
        lab = PG.label_summary("GT1")
        self.assertEqual(lab["labels"], {1: 1, 2: 0})
        self.assertEqual(lab["detail"][3]["gt_status"], "disagreement"); self.assertEqual(lab["detail"][4]["gt_block"], "NO_EXPERT")
        self.assertEqual(lab["missed_detail"]["missed_1"]["gt_block"], "REVIEWER_NOT_EXPERT")
        from uengine.percival import eligibility as EL
        self.assertEqual(EL.evaluate(dict(label_kind="disputed", conflict=True))["status"], "needs_adjudication")
        self.assertEqual(EL.evaluate(dict(label_kind="css", gt_block="NOT_PRIMARY_GROUND_TRUTH"))["status"], "excluded")


class TestMigration(unittest.TestCase):
    def fixture(self):
        b, cand = proj()
        pd.DataFrame([dict(cand_id=1, call="cSS", comment="", reviewer="Old Reader", time="2025-01-01 10:00:00", **cand.set_index("cand_id").loc[1, FP].to_dict(), fine_code="")],
                     columns=COLS).to_csv(os.path.join(b, "review", "S1_calls_Old_Reader.csv"), index=False)
        json.dump(dict(reviewer="Old Reader", read_mode="validation", meter_visible=0, saved="2025-01-01"), open(os.path.join(b, "review", "S1_final_Old_Reader.json"), "w"))
        open(os.path.join(b, "review", "S1_missed.csv"), "w").write("missed_id,reviewer,time,vox_i,vox_j,vox_k\n1,Old Reader,t,1,2,3\n2,Old Reader,t,4,5\n")
        json.dump(dict(schema="call-policy/1.0", default=dict(mode="newest"), cohorts={}, studies={}, history=[]), open(CL.policy_path(b), "w"))
        return b

    def snap(self, b):
        return {os.path.relpath(p, b): hashlib.sha256(open(p, "rb").read()).hexdigest() for p in glob.glob(os.path.join(b, "review", "**"), recursive=True) if os.path.isfile(p)}

    def test_plan_is_read_only_and_classifies_without_promoting(self):
        b = self.fixture(); before = self.snap(b)
        rep = MG.plan(b)
        self.assertEqual(self.snap(b), before)
        r = rep["studies"][0]["reviewers"][0]
        self.assertEqual((r["proposed_class"], r["verification_candidate"], r["role"]), ("historical_blinding_unknown", True, "unknown"))

    def test_apply_backup_idempotent_no_promotion_and_rollback(self):
        b = self.fixture(); before = self.snap(b)
        with self.assertRaises(PermissionError): MG.apply(b, "admin", "yes")
        res = MG.apply(b, "admin", MG.CONFIRM); ts = res["time"]
        man = json.load(open(os.path.join(b, "review", "migration", ts, "manifest.json")))
        self.assertEqual({o["file"]: o["sha256"] for o in man["originals"]}, before)                 # every original checksummed
        for o in man["originals"]:
            self.assertEqual(hashlib.sha256(open(os.path.join(b, "review", "migration", ts, "originals", o["file"]), "rb").read()).hexdigest(), o["sha256"])
        self.assertEqual(open(os.path.join(b, "review", "S1_calls_Old_Reader.csv"), "rb").read(),
                         open(os.path.join(b, "review", "migration", ts, "originals", "review", "S1_calls_Old_Reader.csv"), "rb").read())   # never edited
        self.assertTrue(os.path.exists(os.path.join(b, "review", "S1_missed_legacy.csv")))
        self.assertEqual(json.load(open(CL.policy_path(b)))["schema"], CL.POLICY_V2)
        self.assertEqual(RR.current(b), {})                                                     # no role assigned
        s = st(b)[1]; self.assertEqual((s["status"], s["primary_eligible"]), ("no_expert", False))
        expert(b, "Old Reader")
        s = st(b)[1]; self.assertEqual((s["provenance_class"], s["primary_eligible"]), ("historical_blinding_unknown", False))  # never promoted
        self.assertTrue(MG.apply(b, "admin", MG.CONFIRM)["noop"])
        with self.assertRaises(PermissionError): MG.rollback(b, ts, "no")
        MG.rollback(b, ts, MG.CONFIRM_ROLLBACK)
        after = {k: v for k, v in self.snap(b).items() if not k.startswith("review/migration/") and k != "review/project_roles_events.jsonl"}
        self.assertEqual(after, before)                                                          # byte-identical; created files removed


if __name__ == "__main__":
    unittest.main()
