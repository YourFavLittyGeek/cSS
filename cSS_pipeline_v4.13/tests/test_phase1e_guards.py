"""Phase 1e.2 tests: migrations disabled; maintenance refused while unfinished transfer jobs still need the data.

Through app/css_app.py dispatchers bound to the isolated project. Synthetic data only."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import json
import os
import shutil
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "app"), os.path.join(ROOT, "unified_engine"), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from test_phase1a_transfer_core import _w                               # noqa: E402
from test_phase1d_workers import big, wait                              # noqa: E402

TERMINAL = {"completed", "completed_with_retained_sources", "cancelled"}


class TestGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import css_app
        cls.app = css_app
        cls.B = css_app.B

    def tearDown(self):
        self.app.transfer_pool_shutdown(5)
        os.environ.pop("PERCIVAL_TEST_SLOW_AT", None)
        for n in ("G1", "G1_out", "OTHER", "MIG_TARGET"):
            shutil.rmtree(os.path.join(self.B, "work", n), ignore_errors=True)

    def paused_job(self):
        src = os.path.dirname(big(os.path.join(self.B, "work", "G1", "a.nii"), 24))
        os.environ["PERCIVAL_TEST_SLOW_AT"] = "copy.chunk=0.05"
        post, get = self.app.transfer_post, self.app.transfer_get
        job = post("jobs/create", dict(operation="archive", study_id="G1",
                                       items=[dict(src=src, dst=os.path.join(self.B, "work", "G1_out"))]))["job_id"]
        wait(lambda: get("job", {"id": job})["job"]["state"] == "copying", what="copying")
        post("jobs/pause", dict(job_id=job))
        wait(lambda: get("job", {"id": job})["job"]["state"] == "paused", what="paused")
        os.environ.pop("PERCIVAL_TEST_SLOW_AT")
        return job, src

    def discard(self, job):
        self.app.transfer_post("jobs/discard", dict(job_id=job))
        wait(lambda: self.app.transfer_get("job", {"id": job})["job"]["state"] in TERMINAL, what="discarded")

    def test_migrations_are_disabled_but_planning_works(self):
        target = os.path.join(self.B, "work", "MIG_TARGET")
        os.makedirs(target)
        pp = os.path.expanduser("~/Library/Application Support/Percival Dev/project_path")
        before = open(pp).read() if os.path.exists(pp) else None
        ws_before = self.app.SET.get("workspace_dir")
        r = self.app.storage_post("migrate_execute", dict(target_dir=target, verify_checksums=True))
        self.assertFalse(r["ok"])
        self.assertTrue(r["migration_disabled"])
        self.assertEqual(os.listdir(target), [])                                  # nothing copied
        self.assertEqual(open(pp).read() if os.path.exists(pp) else None, before)  # project_path never rewritten
        self.assertEqual(self.app.SET.get("workspace_dir"), ws_before)
        self.assertFalse(self.app.migration_post("execute", dict(plan={}))["ok"])
        plan = self.app.storage_post("migrate_plan", dict(target_dir=target))
        self.assertNotIn("migration_disabled", plan)                               # read-only planning still available

    def test_global_maintenance_refused_while_any_job_is_unfinished(self):
        ops = [("storage_post", "prune", dict(action="prune_scratch", days=30)), ("storage_post", "free_space_execute", {}),
               ("clean_post", "execute", dict(categories=["temp_processing"])), ("clean_post", "quarantine_purge", dict(purge_all=True))]
        for fn, op, d in ops:                                                      # no unfinished job: not blocked
            with self.subTest(op=op, phase="idle"):
                self.assertNotIn("blocked_by", getattr(self.app, fn)(op, d))
        job, src = self.paused_job()
        try:
            for fn, op, d in ops:
                with self.subTest(op=op, phase="paused job"):
                    r = getattr(self.app, fn)(op, d)
                    self.assertFalse(r["ok"])
                    self.assertEqual([b["job_id"] for b in r["blocked_by"]], [job])
        finally:
            self.discard(job)
        self.assertNotIn("blocked_by", self.app.storage_post("prune", dict(action="prune_scratch", days=30)))

    def test_path_and_study_scoped_operations(self):
        job, src = self.paused_job()
        other = _w(os.path.join(self.B, "work", "OTHER", "x.nii"), b"x")
        try:
            for fn, op, d in (("files_post", "delete", dict(path=os.path.join(src, "a.nii"), confirm=True)),
                              ("files_post", "delete", dict(path=src, confirm=True)),
                              ("files_post", "move", dict(src=src, dst_dir=os.path.join(self.B, "work", "OTHER"))),
                              ("files_post", "rename", dict(path=src, new_name="renamed")),
                              ("files_post", "delete", dict(path=os.path.join(self.B, "work", "G1_out"), confirm=True)),
                              ("storage_post", "clean", dict(code="G1")), ("storage_post", "delete", dict(code="G1")),
                              ("clean_post", "delete_study", dict(study_code="G1", target="all")),
                              ("workspace_post", "clean", dict(study_id="G1"))):
                with self.subTest(op=op, d=d):
                    r = getattr(self.app, fn)(op, d)
                    self.assertFalse(r["ok"], r)
                    self.assertEqual([b["job_id"] for b in r["blocked_by"]], [job])
            self.assertTrue(os.path.exists(os.path.join(src, "a.nii")))
            # unrelated data and studies are not blocked
            self.assertTrue(self.app.files_post("delete", dict(path=other, confirm=True))["ok"])
            self.assertNotIn("blocked_by", self.app.storage_post("clean", dict(code="OTHER")))
        finally:
            self.discard(job)
        self.assertNotIn("blocked_by", self.app.files_post("rename", dict(path=src, new_name="G1_renamed")))
        shutil.rmtree(os.path.join(self.B, "work", "G1_renamed"), ignore_errors=True)

    def test_unknown_state_refuses_destructive_maintenance(self):
        from uengine.transfer import guards as G
        with mock.patch.object(G, "unfinished_jobs", side_effect=RuntimeError("journal unreadable")):
            r = self.app.storage_post("free_space_execute", {})
        self.assertFalse(r["ok"])
        self.assertIn("could not be checked", r["error"])


if __name__ == "__main__":
    unittest.main()
