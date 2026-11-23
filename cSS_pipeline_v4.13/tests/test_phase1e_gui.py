"""Phase 1e.3 tests: the Transfer Center GUI reflects the durable journal.

Real job states are produced by the backend (completed, conflict -> needs_attention, permission -> failed, paused,
SIGKILL -> interrupted, queued); the payloads of the real endpoints are fed to app/transfer_view.js in Node
(tests/gui_transfer_harness.js) and the rendered views / offered controls / posted requests are checked. Isolated."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import json
import os
import shutil
import subprocess
import sys
import threading
import unittest
import urllib.request
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "app"), os.path.join(ROOT, "unified_engine"), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from test_phase1a_transfer_core import Env, _w                         # noqa: E402
from test_phase1d_workers import big, wait                              # noqa: E402
from uengine.storage.eject_manager import EjectManager                  # noqa: E402
from uengine.storage.storage_paths import StoragePathsService           # noqa: E402
from uengine.transfer import api as TAPI                                # noqa: E402
from uengine.transfer.service import TransferRefused, TransferService    # noqa: E402
from uengine.transfer.workers import TransferWorkerPool                  # noqa: E402

NODE = shutil.which("node")
CHILD_PATH = [os.path.join(ROOT, "unified_engine"), ROOT, HERE]
EXPECTED_ACTIONS = {"completed": [], "needs_attention": ["assess", "resume", "discard"], "failed": ["discard", "assess"],
                    "paused": ["resume", "discard", "assess"], "interrupted": ["resume", "discard", "assess"],
                    "queued": ["pause", "cancel"]}
EXPECTED_TAB = {"completed": "history", "needs_attention": "attention", "failed": "attention", "paused": "attention",
                "interrupted": "attention", "queued": "queued"}


@unittest.skipIf(NODE is None, "node is not installed")
class TestTransferCenterGUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.E = E = Env()
        svc = TransferService(E.base, E.vault)
        v = E.vault
        cls.jobs = {}
        cls.jobs["completed"] = svc.transfer("archive", [(E.work("C1/a.nii", b"A"), os.path.join(v, "studies", "C1"))], study_id="C1")["job_id"]
        _w(os.path.join(v, "studies", "N1", "a.nii"), b"ARCHIVED")
        cls.jobs["needs_attention"] = svc.transfer("archive", [(E.work("N1/a.nii", b"NEW"), os.path.join(v, "studies", "N1"))], study_id="N1")["job_id"]
        ro = os.path.join(v, "studies", "F1")
        os.makedirs(ro)
        os.chmod(ro, 0o555)
        try:
            cls.jobs["failed"] = svc.transfer("archive", [(E.work("F1/a.nii", b"F"), os.path.join(ro, "sub"))], study_id="F1")["job_id"]
        finally:
            os.chmod(ro, 0o755)
        pool = TransferWorkerPool(E.base, v, poll_s=0.05).start()
        with mock.patch.dict(os.environ, {"PERCIVAL_TEST_SLOW_AT": "copy.chunk=0.05"}):
            j = pool.submit("archive", [(os.path.dirname(big(os.path.join(E.base, "work", "P1", "x.nii"), 24)), os.path.join(v, "studies", "P1"))],
                            study_id="P1")["job_id"]
            wait(lambda: svc.journal.get_job(j)["state"] == "copying", what="copying")
            pool.pause(j)
            wait(lambda: svc.journal.get_job(j)["state"] == "paused", what="paused")
        pool.shutdown(5)
        pool.close()
        cls.jobs["paused"] = j
        src = os.path.dirname(E.work("I1/a.nii", b"I" * 5000))
        code = f"""
import sys
sys.path[:0] = {CHILD_PATH!r}
from uengine.transfer.service import TransferService
s = TransferService({E.base!r}, {v!r})
j = s.submit("archive", [({src!r}, {os.path.join(v, "studies", "I1")!r})], study_id="I1"); print(j, flush=True); s.run(j)
"""
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60,
                             env=dict(os.environ, PERCIVAL_TEST_CRASH_AT="commit.after_record"))
        cls.jobs["interrupted"] = out.stdout.split()[0]
        svc.detect_interrupted()
        cls.jobs["queued"] = svc.submit("archive", [(E.work("Q1/a.nii", b"Q"), os.path.join(v, "studies", "Q1"))], study_id="Q1")
        cls.svc = svc
        cls.pool = TransferWorkerPool(E.base, v)                              # NOT started: the queued job stays queued
        cls.fixture = dict(
            jobs=TAPI.handle_get("jobs", {}, cls.pool)["jobs"], workers=TAPI.handle_get("workers", {}, cls.pool)["workers"],
            vault=TAPI.handle_get("vault_check", {}, cls.pool)["vault"],
            eject=EjectManager(StoragePathsService(E.base, v)).check_ejection_safety().to_dict(),
            detail=TAPI.handle_get("job", {"id": cls.jobs["interrupted"]}, cls.pool), detail_id=cls.jobs["interrupted"],
            assess=svc.assess(cls.jobs["interrupted"]), search="C1")
        fx = os.path.join(E.tmp, "fixture.json")
        with open(fx, "w") as f:
            json.dump(cls.fixture, f)
        r = subprocess.run([NODE, os.path.join(HERE, "gui_transfer_harness.js"), fx], capture_output=True, text=True, timeout=60)
        if r.returncode:
            raise RuntimeError(r.stderr)
        cls.out = json.loads(r.stdout)

    @classmethod
    def tearDownClass(cls):
        cls.pool.close()
        cls.svc.close()
        cls.E.close()

    def test_backend_produced_every_state(self):
        st = {j["job_id"]: j["state"] for j in self.fixture["jobs"]}
        self.assertEqual({k: st[v] for k, v in self.jobs.items()}, {k: k for k in self.jobs})

    def test_every_job_is_shown_once_in_the_tab_of_its_journal_state(self):
        shown = {t: ids for t, ids in self.out["states_shown"].items()}
        for state, jid in self.jobs.items():
            tabs = [t for t, ids in shown.items() if jid in ids]
            self.assertEqual(tabs, [EXPECTED_TAB[state]], f"{state}: {tabs}")
        all_states = set()
        for html in self.out["tabs"].values():
            import re
            all_states |= set(re.findall(r'data-state="([^"]+)"', html))
        self.assertLessEqual(all_states, {j["state"] for j in self.fixture["jobs"]})    # never a state the journal lacks

    def test_controls_follow_the_journaled_state(self):
        for state, jid in self.jobs.items():
            self.assertEqual(self.out["actions"][jid], EXPECTED_ACTIONS[state], state)
        # what the GUI does not offer, the backend refuses / ignores
        with self.assertRaises(TransferRefused):
            self.pool.cancel_queued(self.jobs["paused"])
        with self.assertRaises(TransferRefused):
            self.pool.pause(self.jobs["completed"])
        self.assertTrue(self.pool.resume(self.jobs["completed"])["noop"])

    def test_refresh_replaces_all_client_data(self):
        self.assertNotIn("stale-client-only", self.out["after_fetch_ids"])
        self.assertEqual(self.out["after_fetch_ids"], [j["job_id"] for j in self.fixture["jobs"]])

    def test_errors_and_recovery_are_visible(self):
        att = self.out["tabs"]["attention"]
        failed = next(j for j in self.fixture["jobs"] if j["job_id"] == self.jobs["failed"])
        self.assertIn("Permission denied", failed["error"]["message"])
        self.assertIn("Permission denied", att)
        self.assertIn("exist with different content", att)                              # needs_attention reason
        d = self.out["detail_html"]
        self.assertIn("Recovery check", d)
        self.assertIn("Resume possible: <b>yes</b>", d)
        for f in self.fixture["detail"]["files"]:
            self.assertIn(f["rel_path"], d)

    def test_vault_and_eject_come_from_the_backend(self):
        html = self.out["tabs"]["attention"]
        self.assertIn(f'data-verdict="{self.fixture["vault"]["verdict"]}"', html)
        self.assertIn(f'data-eject="{self.fixture["eject"]["state"]}"', html)

    def test_history_search(self):
        self.assertEqual(self.out["search"], [self.jobs["completed"]])

    def test_controls_post_to_the_backend_and_discard_needs_confirmation(self):
        posts = [c for c in self.out["calls"] if c["body"]]
        self.assertEqual([(c["url"], c["body"]["job_id"]) for c in posts],
                         [("/api/transfer/jobs/pause", "J-PAUSE"), ("/api/transfer/jobs/discard", "J-YES"),
                          ("/api/transfer/jobs/resume", "J-RES"), ("/api/transfer/jobs/cancel", "J-CAN")])

    def test_untrusted_text_is_escaped(self):
        self.assertNotIn("<img src=x", self.out["escaped"])
        self.assertNotIn("<script>", self.out["escaped"])
        self.assertIn("&lt;script&gt;", self.out["escaped"])


class TestServedAndWired(unittest.TestCase):
    def test_served_by_the_app_and_sidebar_uses_the_journal(self):
        import css_app
        srv = css_app.ThreadingHTTPServer(("127.0.0.1", 0), css_app.H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            base = f"http://127.0.0.1:{srv.server_address[1]}"
            js = urllib.request.urlopen(base + "/transfer_view.js", timeout=20).read().decode()
            self.assertIn("function tcRender", js)
            self.assertNotIn("window.V", js)
            html = urllib.request.urlopen(base + "/", timeout=20).read().decode()
            self.assertIn("/api/transfer/jobs?state=preparing", html)                      # sidebar meter: journal
            self.assertIn("b.disabled=!chk.can_eject", html)                                 # eject button: backend decides
            for name in ("sync_view.js", "settings_view.js", "transfer_view.js"):
                src = urllib.request.urlopen(f"{base}/{name}", timeout=20).read().decode()
                import re
                self.assertEqual(re.findall(r"(?<![.\w])round\(", src), [], name)          # the undefined helper is gone
        finally:
            srv.shutdown()
            srv.server_close()
            css_app.transfer_pool_shutdown(5)


if __name__ == "__main__":
    unittest.main()
