"""Stages 5-7 - data authority (identity service, hash-chained event log with registry replay, one versioned configuration), validation
governance (pre-registered evaluation plan, no test-set reuse across cycles, automatic cycles off, inter-reader agreement baseline, drift
monitoring) and approval integrity (local signatures). SYNTHETIC / temporary projects only."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "scripts"), os.path.join(ROOT, "app"), os.path.join(ROOT, "unified_engine"), ROOT, HERE):
    if p not in sys.path: sys.path.insert(0, p)
from uengine import event_log as EV, identity_service as IS, pensieve_index as PI, approval_signing as AS   # noqa: E402
from uengine.percival import component_registry as CR                                                       # noqa: E402


def store(): return tempfile.mkdtemp(prefix="st5_", dir=os.environ["CSS_BASE"])


class TestIdentityService(unittest.TestCase):
    def test_one_service_patient_partition_and_consistency(self):
        st = store(); m = {"S1": "P1", "S2": "P1", "S3": None}
        I = IS.IdentityService(st, m.get, fingerprint_of=lambda s: f"fp-{s}", test_fraction=0.2)
        r1, r2, r3 = I.records(["S1", "S2", "S3"])
        self.assertEqual(r1["partition"], r2["partition"]); self.assertIn(r1["partition"], ("development", "test"))
        self.assertIsNone(r3["patient"]); self.assertIsNone(r3["partition"])         # no identity -> never assigned / trained on
        self.assertEqual(I.digest(["S1", "S2"]), I.digest(["S2", "S1"]))
        self.assertEqual(I.check_rows([dict(study="S1", patient="P1"), dict(study="S2", patient="P9")]),
                         [dict(study="S2", row_patient="P9", service_patient="P1")])


class TestEventLog(unittest.TestCase):
    def test_registry_changes_are_events_and_the_registry_is_rebuilt_from_them(self):
        st = store()
        CR.approve(st, "NOX", dict(feature_set=["a"]), "Dr A", "first", CR.CONFIRM, evidence={})
        CR.approve(st, "NOX", dict(feature_set=["a", "b"]), "Dr A", "second", CR.CONFIRM, evidence={})
        CR.rollback(st, "NOX", "Dr A", "undo", CR.CONFIRM)
        V = EV.verify(st); self.assertTrue(V["chain"]["ok"]); self.assertTrue(V["registry_matches_events"])
        self.assertEqual(V["types"]["component_change"], 2); self.assertEqual(V["types"]["rollback"], 1)
        self.assertEqual(EV.replay_registry(st), {"NOX": "v001"})
        CR._js(os.path.join(CR._d(st, "NOX"), "active.json"), dict(version="v002"))     # a hand edit outside the app
        V = EV.verify(st); self.assertFalse(V["registry_matches_events"]); self.assertEqual(V["differences"][0]["from_events"], "v001")
        self.assertEqual(EV.rebuild_registry(st, "Dr A", "restore"), {"NOX": "v001"}); self.assertTrue(EV.verify(st)["registry_matches_events"])

    def test_tampering_breaks_the_chain(self):
        st = store(); [EV.append(st, "training_run", "PERCIVAL", run=f"run{i}") for i in range(3)]
        p = EV._path(st); L = open(p).read().splitlines(); e = json.loads(L[1]); e["payload"]["run"] = "forged"; L[1] = json.dumps(e, sort_keys=True)
        open(p, "w").write("\n".join(L) + "\n")
        self.assertEqual(EV.verify_chain(st)["broken_at"], 1)
        with self.assertRaises(ValueError): EV.append(st, "made_up", "x")


class TestSignatures(unittest.TestCase):
    def test_approvals_are_signed_and_edits_detected(self):
        st = store(); V = CR.approve(st, "LUMOS", dict(image_kind="cnn"), "Dr A", "freeze", CR.CONFIRM, evidence={})
        self.assertTrue(CR.active(st, "LUMOS")["signature_ok"]); self.assertEqual(V["signature"]["scheme"], AS.SCHEME)
        p = os.path.join(CR._d(st, "LUMOS"), "v001.json"); d = json.load(open(p)); d["by"] = "Someone Else"; json.dump(d, open(p, "w"))
        self.assertFalse(CR.active(st, "LUMOS")["signature_ok"])
        self.assertTrue(CR.load(st, "LUMOS", "v000")["signature_ok"])
        self.assertEqual(oct(os.stat(AS.key_path()).st_mode & 0o777), "0o600")
        self.assertFalse(AS.key_path().startswith(os.environ["CSS_BASE"]))           # the key is not inside the project


class TestReaderAgreement(unittest.TestCase):
    def test_kappa_between_experts_on_shared_blind_calls(self):
        b = store(); con = PI._connect(PI.path(b))
        con.execute("INSERT INTO studies (study_id) VALUES ('S1')"); con.execute("INSERT INTO studies (study_id) VALUES ('S2')")
        calls = {"Dr A": ["cSS", "cSS", "Vessel", "Normal", "cSS", "Vessel", "Unsure", "cSS"], "Dr B": ["cSS", "Vessel", "Vessel", "Normal", "cSS", "Vessel", "cSS", "cSS"]}
        for rev, cs in calls.items():
            for i, c in enumerate(cs):
                con.execute("INSERT INTO expert_calls (event_key, study_id, candidate_uid, reviewer, role, call, read_phase, time, source_kind) VALUES (?,?,?,?,?,?,?,?,?)",
                            (f"{rev}{i}", f"S{1 + i % 2}", f"u{i}", rev, "expert", c, "initial", f"2026-11-24 10:00:0{i}", "expert_human"))
        con.commit(); con.close()
        R = PI.reader_agreement(b); pr = R["pairs"][0]
        self.assertEqual(pr["n"], 7)                                                 # the Unsure call is an abstention, not a vote
        self.assertAlmostEqual(pr["agreement"], 6 / 7); self.assertGreater(pr["kappa"], 0.5)


class TestValidationGovernance(unittest.TestCase):
    def setUp(self):
        import css_app; css_app.pg_init(); self.PG = css_app.PG; self.app = css_app

    def test_automatic_cycles_off_by_default(self):
        PG = self.PG; S = PG.CTX["SET"]; old = S.pop("percival_autocycle", None)
        try: self.assertFalse(PG.maybe_cycle())
        finally:
            if old is not None: S["percival_autocycle"] = old
        self.assertIn('SET.setdefault("percival_autocycle", False)', open(os.path.join(ROOT, "app", "css_app.py")).read())

    def test_plan_milestones_and_no_test_reuse(self):
        PG = self.PG
        for f in ("evaluation_plan.json",): (os.remove(PG.P(f)) if os.path.exists(PG.P(f)) else None)
        if os.path.exists(PG.P("split", "test_consultations.jsonl")): os.remove(PG.P("split", "test_consultations.jsonl"))
        M = dict(version="v001", test=dict(n=40, percival=dict(auc=0.8))); ok = dict(passed=True, reasons=[], criteria="")
        a = PG.test_reuse_gate(M, ok, ["P1", "P2"]); self.assertFalse(a["passed"]); self.assertIn("no pre-registered evaluation plan", a["reasons"][0])
        self.assertFalse(PG.evaluation_plan_save({}, "percival", "auto", PG.PLAN_CONFIRM)["ok"])
        self.assertFalse(PG.evaluation_plan_save({}, "Dr A", "plan", "yes")["ok"])
        self.assertFalse(PG.evaluation_plan_save(dict(test_size=dict(min_test_patients_per_class=2)), "Dr A", "too small", PG.PLAN_CONFIRM)["ok"])
        self.assertTrue(PG.evaluation_plan_save({}, "Dr A", "pre-registration", PG.PLAN_CONFIRM)["ok"])
        a = PG.test_reuse_gate(M, ok, ["P1", "P2"]); self.assertIn("no evaluation milestone", a["reasons"][0])
        self.assertTrue(PG.milestone_declare("pilot", "Dr A", "first look", PG.PLAN_CONFIRM)["ok"])
        a = PG.test_reuse_gate(M, ok, ["P1", "P2"]); self.assertTrue(a["passed"], a); self.assertTrue(a["test_consultation"]["used_for_acceptance"])
        b = PG.test_reuse_gate(dict(M, version="v002"), ok, ["P1", "P2"]); self.assertFalse(b["passed"]); self.assertIn("test-set reuse is refused", b["reasons"][0])
        self.assertTrue(PG.milestone_declare("second", "Dr A", "new version", PG.PLAN_CONFIRM)["ok"])
        c = PG.test_reuse_gate(dict(M, version="v003"), ok, ["P1", "P2"]); self.assertTrue(c["passed"])
        self.assertEqual(len(PG.test_consultations()), 5)
        E = self.app.pg_get("evaluation_plan", {}); self.assertEqual(len(E["plan"]["milestones"]), 2)

    def test_config_snapshot_and_events_routes(self):
        PG = self.PG; a = PG.config_snapshot(); b = PG.config_snapshot(); self.assertEqual(a["sha256"], b["sha256"])
        S = PG.CTX["SET"]; old = S.get("percival_test_fraction")
        S["percival_test_fraction"] = 0.31
        try: c = PG.config_snapshot(); self.assertNotEqual(c["sha256"], a["sha256"])
        finally:
            if old is None: S.pop("percival_test_fraction", None)
            else: S["percival_test_fraction"] = old
        ev = self.app.pg_get("events", {}); self.assertTrue(ev["verify"]["chain"]["ok"]); self.assertGreaterEqual(ev["verify"]["types"]["config_changed"], 1)
        d = self.app.pg_get("drift", {}); self.assertIn("by_subgroup", d)
        self.assertIn("pairs", self.app.pg_get("reader_agreement", {})) if self.app.pg_get("reader_agreement", {}).get("available") else None


if __name__ == "__main__":
    unittest.main()
