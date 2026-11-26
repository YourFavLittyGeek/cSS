"""2026-11-26 the user's "mix" (docs: HANDOVER): the current test patients stay as an early-warning test group; new patients go to
development; then ONE fresh test cohort of consecutive new patients (never chosen by cSS status) until N with cSS AND N without are
reviewed; it is SEALED (never trained on, never evaluated - training and SHADOW leave it out) until it is complete and opened ONCE.
Every step: typed phrase + person + reason; no patient ever changes group; the policy survives a balance / new split version.
Temporary store only. Isolated (tests/_isolation.py)."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "app"), os.path.join(ROOT, "unified_engine")):
    if p not in sys.path: sys.path.insert(0, p)
from uengine.percival import split as SP        # noqa: E402
NODE = shutil.which("node")


class TestMix(unittest.TestCase):
    def setUp(self):
        self.st = tempfile.mkdtemp(prefix="split_mix_")
        S = SP.create(self.st, 0.2, "t", "fixture", patients=[], carry_test=["E1", "E2"])
        for i in range(20): S["assignment"][f"D{i}"] = "development"
        SP._js(os.path.join(self.st, "split", f"{S['version']}.json"), S)

    def test_whole_path(self):
        st = self.st
        with self.assertRaises(SP.SplitError): SP.set_policy(st, "fresh_test", "Dr A", "why", SP.CONFIRM_FRESH)     # development phase first
        with self.assertRaises(PermissionError): SP.set_policy(st, "development_only", "Dr A", "why", "yes")
        with self.assertRaises(SP.SplitError): SP.set_policy(st, "development_only", "", "why", SP.CONFIRM_DEV_ONLY)
        SP.set_policy(st, "development_only", "Dr A", "mix: develop first", SP.CONFIRM_DEV_ONLY)
        self.assertEqual([SP.partition_of(st, f"N{i}") for i in range(30)], ["development"] * 30)      # never test in this phase
        self.assertEqual(SP.partition_of(st, "E1"), "test")                                            # early-warning group stays
        with self.assertRaises(SP.SplitError): SP.set_policy(st, "fresh_test", "Dr A", "why", SP.CONFIRM_FRESH, target=5)   # >= 10
        SP.set_policy(st, "fresh_test", "Dr A", "final test", SP.CONFIRM_FRESH, target=10)
        with self.assertRaises(SP.SplitError): SP.set_policy(st, "fresh_test", "Dr A", "again", SP.CONFIRM_FRESH)
        fresh = [f"F{i}" for i in range(25)]
        self.assertEqual([SP.partition_of(st, p) for p in fresh], ["test"] * 25)                        # consecutive, all of them
        self.assertEqual(SP.sealed(st), set(fresh))
        cl = {p: ("css" if i % 3 == 0 else "no_css") for i, p in enumerate(fresh[:20])}                   # 7 cSS, 13 without reviewed
        f = SP.fresh_state(st, cl); self.assertIsNone(f["closed"]); self.assertEqual((f["css"], f["no_css"], f["unreviewed"]), (7, 13, 5))
        with self.assertRaises(SP.SplitError): SP.open_final(st, "Dr A", "why", SP.CONFIRM_OPEN)          # not complete
        cl.update({p: "css" for p in fresh[20:]}); f = SP.fresh_state(st, cl)
        self.assertTrue(f["closed"]); self.assertEqual(SP.partition_of(st, "AFTER"), "development")      # complete: back to development
        self.assertEqual(SP.partition_of(st, "F3"), "test")                                              # nobody changes group
        with self.assertRaises(PermissionError): SP.open_final(st, "Dr A", "why", "open")
        SP.open_final(st, "Dr A", "cohort complete", SP.CONFIRM_OPEN); self.assertEqual(SP.sealed(st), set())
        with self.assertRaises(SP.SplitError): SP.open_final(st, "Dr A", "twice", SP.CONFIRM_OPEN)        # once only
        log = SP.current(st)["policy_log"]; self.assertEqual([x["to"] for x in log], ["development_only", "fresh_test"])

    def test_policy_survives_a_balance(self):
        SP.set_policy(self.st, "development_only", "Dr A", "mix", SP.CONFIRM_DEV_ONLY)
        cl = {"E1": "css", "E2": "css", **{f"D{i}": "no_css" for i in range(20)}}
        S = SP.balance(self.st, cl, "Dr A", "balance", SP.CONFIRM_BALANCE, min_per_class=2)
        self.assertEqual(S["policy"], "development_only"); self.assertEqual(SP.partition_of(self.st, "NEW"), "development")


class TestAppWiring(unittest.TestCase):
    def test_training_and_shadow_leave_the_sealed_cohort_out(self):
        src = open(os.path.join(ROOT, "app", "percival_gui.py")).read()
        i = src.index("def _train(reason):"); body = src[i:src.index("\ndef ", i + 10)]
        self.assertIn("SEAL = _sealed()", body); self.assertIn("in SEAL", body)
        i = src.index("def _shadow(version):"); self.assertIn("not in SEAL", src[i:i + 1200])
        app = open(os.path.join(ROOT, "app", "css_app.py")).read()
        for op in ('"test_group_policy"', '"test_group_open"'): self.assertIn(op, app)

    @unittest.skipIf(NODE is None, "node is not installed")
    def test_screen_steps(self):
        js = open(os.path.join(ROOT, "app", "percival_view.js")).read(); a = js.index("function pvSplitPolicy(T)"); b = js.index("\n", js.index("`}", a))
        def html(T):
            code = "const esc=x=>String(x);" + js[a:b] + f";process.stdout.write(pvSplitPolicy({json.dumps(T)}))"
            r = subprocess.run([NODE, "-e", code], capture_output=True, text=True, timeout=30)
            if r.returncode: raise RuntimeError(r.stderr)
            return r.stdout
        h = html(dict(policy="random", early_test=dict(css=5, no_css=5), target=30))
        self.assertIn("pv-tg-dev", h); self.assertNotIn("pv-tg-fresh", h); self.assertIn("5 with cSS, 5 without", h)
        h = html(dict(policy="development_only", target=30)); self.assertIn("pv-tg-fresh", h); self.assertNotIn("pv-tg-dev", h)
        F = dict(members=12, css=3, no_css=7, unreviewed=2, target_per_class=30, closed=None, opened=None)
        h = html(dict(policy="fresh_test", fresh=F, target=30)); self.assertIn("12 patients in the fresh cohort", h); self.assertNotIn("pv-tg-open", h)
        h = html(dict(policy="fresh_test", fresh=dict(F, closed="2027-01-01"), target=30)); self.assertIn("pv-tg-open", h)


if __name__ == "__main__":
    unittest.main()
