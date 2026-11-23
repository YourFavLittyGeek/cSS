"""Phase 1 milestone 1d tests: Transfer Center endpoints, background workers, cooperative pause / resume.

Isolated (tests/_isolation.py); synthetic files; real interruptions where practical: SIGKILL of a worker process,
forced detach of an APFS disk image mid-copy, a genuinely full HFS+ image. Pause points are held open with the
test-only delay facility (crashpoints PERCIVAL_TEST_SLOW_AT, honoured only under test isolation)."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "app"), os.path.join(ROOT, "unified_engine"), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from test_phase1a_transfer_core import Env, _w                           # noqa: E402
from uengine.transfer import crashpoints as CPT                          # noqa: E402
from uengine.transfer import tree as TR                                  # noqa: E402
from uengine.transfer.service import TransferRefused, TransferService     # noqa: E402
from uengine.transfer.workers import TransferWorkerPool                   # noqa: E402

PY = sys.executable
CHILD_PATH = [os.path.join(ROOT, "unified_engine"), ROOT, HERE]
A, B, C = b"A" * 70000, b"B" * 250000, b"C" * 30
TERMINAL = {"completed", "completed_with_retained_sources", "cancelled"}


def wait(pred, timeout=60.0, step=0.02, what="condition"):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = pred()
        if v:
            return v
        time.sleep(step)
    raise AssertionError(f"timed out waiting for {what}")


def big(path, mb):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.truncate(mb * 1024 * 1024)
        f.seek(mb * 1024 * 1024 // 2)
        f.write(b"MARK")
    return path


class PoolBase(unittest.TestCase):
    def setUp(self):
        CPT.REACHED.clear()
        self.E = Env()
        self.pool = TransferWorkerPool(self.E.base, self.E.vault, poll_s=0.05).start()
        self.svc = TransferService(self.E.base, self.E.vault)
        self._env = mock.patch.dict(os.environ, {})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self.pool.shutdown(10)
        self.pool.close()
        self.svc.close()
        self.E.assert_protected_intact(self)
        self.E.close()

    def slow(self, spec):
        os.environ["PERCIVAL_TEST_SLOW_AT"] = spec

    def fast(self):
        os.environ.pop("PERCIVAL_TEST_SLOW_AT", None)

    def state(self, job):
        return self.svc.journal.get_job(job)["state"]

    def until(self, job, states, timeout=60):
        states = set([states] if isinstance(states, str) else states)
        return wait(lambda: self.state(job) in states and self.state(job), timeout, what=f"{job} in {states}")

    def tree(self, rel, files):
        root = os.path.join(self.E.base, "work", rel)
        for n, d in files.items():
            _w(os.path.join(root, n), d)
        return root

    def reached(self, name, n=1):
        return wait(lambda: CPT.REACHED.count(name) >= n, what=f"{name} x{n}")

    def no_artifacts(self):
        art = [a for r in (self.E.base, self.E.vault) for a in TR.list_stale_artifacts(r) if "otherjob" not in a["path"]]
        self.assertEqual(art, [])


# ================================================================================================ pause / resume
class TestPauseResume(PoolBase):
    def test_pause_mid_copy_keeps_own_partial_part_then_resume(self):
        src = big(os.path.join(self.E.base, "work", "P1", "big.nii"), 48)
        dst = os.path.join(self.E.vault, "studies", "P1")
        foreign = _w(os.path.join(dst, "big.nii.part-otherjob"), b"SOMEONE ELSE")
        self.slow("copy.chunk=0.05")
        job = self.pool.submit("archive", [(os.path.dirname(src), dst)], study_id="P1")["job_id"]
        self.reached("copy.chunk", 3)
        self.assertTrue(self.pool.pause(job)["pause_requested"])
        self.until(job, "paused")
        f0 = self.svc.journal.get_files(job)[0]
        self.assertEqual(f0["state"], "copying")
        self.assertTrue(os.path.exists(f0["part_path"]))                      # partial copy kept, identity journaled
        self.assertIsNotNone(f0["part_identity"])
        self.assertFalse(os.path.exists(os.path.join(dst, "big.nii")))
        self.assertIsNone(self.svc.journal.get_job(job)["control"])
        self.fast()
        self.assertEqual(self.pool.resume(job)["requested"], "resume")
        self.until(job, TERMINAL)
        self.assertEqual(self.state(job), "completed")
        with open(src, "rb") as a, open(os.path.join(dst, "big.nii"), "rb") as b:
            self.assertEqual(a.read(), b.read())
        self.assertFalse(os.path.exists(f0["part_path"]))
        self.assertEqual(open(foreign, "rb").read(), b"SOMEONE ELSE")         # unrecognized temp file untouched
        os.remove(foreign)
        self.no_artifacts()

    def _pause_at(self, point, kind="archive"):
        if kind == "archive":
            src, dst = self.tree("PA", {"a.nii": A, "b.nii": B, "c.nii": C}), os.path.join(self.E.vault, "studies", "PA")
            items, study = [(src, dst)], "PA"
        elif kind == "move":
            src, dst = self.tree("PM", {"a.nii": A, "b.nii": B}), os.path.join(self.E.base, "work", "PM_out")
            items, study = [(src, dst)], None
        else:
            src = os.path.join(self.E.vault, "studies", "PS")
            for n, d in (("a.nii", A), ("b.nii", B)):
                _w(os.path.join(src, n), d)
            dst = self.tree("PS_ws", {"a.nii": b"OLD-A", "b.nii": b"OLD-B"})
            items, study = [(src, dst)], "PS"
        self.slow(f"checkpoint.{point}=0.4")
        job = self.pool.submit(kind, items, study_id=study)["job_id"]
        self.reached(f"checkpoint.{point}")
        self.pool.pause(job)
        self.until(job, "paused")
        return job, src, dst

    def test_pause_between_files(self):
        self.slow("checkpoint.before_stage=0.4")
        src, dst = self.tree("PB", {"a.nii": A, "b.nii": B, "c.nii": C}), os.path.join(self.E.vault, "studies", "PB")
        job = self.pool.submit("archive", [(src, dst)], study_id="PB")["job_id"]
        self.reached("checkpoint.before_stage", 2)
        self.pool.pause(job)
        self.until(job, "paused")
        st = [f["state"] for f in self.svc.journal.get_files(job)]
        self.assertEqual(st[0], "verified")
        self.assertEqual(set(st[1:]), {"pending"})
        self.assertFalse(os.path.exists(os.path.join(dst, "a.nii")))            # nothing published while staging
        self.fast()
        self.pool.resume(job)
        self.until(job, TERMINAL)
        for n, d in (("a.nii", A), ("b.nii", B), ("c.nii", C)):
            self.assertEqual(open(os.path.join(dst, n), "rb").read(), d)
        self.no_artifacts()

    def test_pause_between_commits_then_resume(self):
        job, src, dst = self._pause_at("between_commits")
        st = [f["state"] for f in self.svc.journal.get_files(job)]
        self.assertEqual(st[0], "committed")
        self.assertIn("verified", st[1:])
        self.fast()
        self.pool.resume(job)
        self.until(job, TERMINAL)
        for n, d in (("a.nii", A), ("b.nii", B), ("c.nii", C)):
            self.assertEqual(open(os.path.join(dst, n), "rb").read(), d)
        self.no_artifacts()

    def test_pause_between_commits_then_discard(self):
        job, src, dst = self._pause_at("between_commits")
        self.fast()
        self.pool.discard(job)
        self.until(job, TERMINAL)
        self.assertEqual(self.state(job), "cancelled")
        self.assertFalse(os.path.exists(dst))
        for n, d in (("a.nii", A), ("b.nii", B), ("c.nii", C)):
            self.assertEqual(open(os.path.join(src, n), "rb").read(), d)
        self.no_artifacts()

    def test_pause_before_removing_move_sources(self):
        job, src, dst = self._pause_at("before_remove_sources", kind="move")
        self.assertEqual({f["state"] for f in self.svc.journal.get_files(job)}, {"committed"})
        self.assertTrue(os.path.exists(os.path.join(src, "a.nii")))             # nothing removed while paused
        self.fast()
        self.pool.resume(job)
        self.until(job, TERMINAL)
        self.assertFalse(os.path.exists(os.path.join(src, "a.nii")))
        self.assertEqual(open(os.path.join(dst, "b.nii"), "rb").read(), B)

    def test_pause_before_finalize_keeps_previous_versions_until_resume(self):
        job, src, dst = self._pause_at("before_finalize", kind="stage")
        preserved = [f["preserved_path"] for f in self.svc.journal.get_files(job)]
        self.assertTrue(all(os.path.exists(p) for p in preserved))
        self.fast()
        self.pool.resume(job)
        self.until(job, TERMINAL)
        self.assertFalse(any(os.path.exists(p) for p in preserved))
        self.assertEqual(open(os.path.join(dst, "a.nii"), "rb").read(), A)

    def test_pause_queued_job_and_pause_during_resume(self):
        self.slow("copy.chunk=0.05")
        first = self.pool.submit("archive", [(os.path.dirname(big(os.path.join(self.E.base, "work", "Q1", "x.nii"), 24)),
                                               os.path.join(self.E.vault, "studies", "Q1"))], study_id="Q1")["job_id"]
        self.reached("copy.chunk")
        src, dst = self.tree("Q2", {"a.nii": A, "b.nii": B}), os.path.join(self.E.vault, "studies", "Q2")
        second = self.pool.submit("archive", [(src, dst)], study_id="Q2")["job_id"]   # same device: waits in the queue
        self.assertEqual(self.state(second), "queued")
        self.assertEqual(self.pool.pause(second)["state"], "paused")
        self.until(first, TERMINAL)
        time.sleep(0.3)
        self.assertEqual(self.state(second), "paused")                            # a paused job is never picked up
        self.slow("checkpoint.resume_before_commit=0.4")
        self.pool.resume(second)
        self.reached("checkpoint.resume_before_commit")
        self.pool.pause(second)
        self.until(second, "paused")
        self.assertEqual(self.svc.journal.get_job(second)["recovery_decision"], "resume")
        with self.assertRaises(TransferRefused):                                  # decision recorded: no switching
            self.pool.discard(second)
        self.fast()
        self.pool.resume(second)
        self.until(second, TERMINAL)
        self.assertEqual(open(os.path.join(dst, "b.nii"), "rb").read(), B)

    def test_pause_and_resume_requests_are_idempotent(self):
        job, src, dst = self._pause_at("between_commits")
        self.assertTrue(self.pool.pause(job)["noop"])
        self.fast()
        self.slow("checkpoint.resume_before_commit=0.3")
        self.pool.resume(job)
        r2 = self.pool.resume(job)
        self.assertTrue(r2.get("already_requested") or r2.get("noop") or r2.get("requested"))
        self.fast()
        self.until(job, TERMINAL)
        self.assertTrue(self.pool.resume(job)["noop"])
        recov = [e for e in self.svc.journal.events(job) if e["to_state"] == "recovering"]
        self.assertEqual(len(recov), 1)                                            # resumed exactly once


# ================================================================================================ worker lifecycle
class TestWorkers(PoolBase):
    def test_shutdown_pauses_running_job_and_a_new_pool_resumes_it(self):
        self.slow("copy.chunk=0.05")
        src = big(os.path.join(self.E.base, "work", "S1", "x.nii"), 32)
        dst = os.path.join(self.E.vault, "studies", "S1")
        job = self.pool.submit("archive", [(os.path.dirname(src), dst)], study_id="S1")["job_id"]
        self.reached("copy.chunk", 2)
        rep = self.pool.shutdown(10)
        self.assertEqual(rep["states"][job], "paused")
        self.assertEqual(rep["still_running"], [])
        self.pool.close()
        self.fast()
        self.pool = TransferWorkerPool(self.E.base, self.E.vault, poll_s=0.05).start()
        self.assertEqual(self.state(job), "paused")                                # paused is not "interrupted"
        self.pool.resume(job)
        self.until(job, TERMINAL)
        self.assertEqual(os.path.getsize(os.path.join(dst, "x.nii")), os.path.getsize(src))

    def test_worker_crash_is_never_reported_as_completion(self):
        src, dst = self.tree("W1", {"a.nii": A}), os.path.join(self.E.vault, "studies", "W1")
        with mock.patch.object(TransferService, "_run_locked", side_effect=RuntimeError("worker crashed (simulated)")):
            job = self.pool.submit("archive", [(src, dst)], study_id="W1")["job_id"]
            self.until(job, "interrupted")
        hist = wait(lambda: [h for h in self.pool.history if h["job_id"] == job], what="worker history")
        self.assertIn("worker crashed", hist[0]["crashed"])
        self.assertEqual(hist[0]["journal_state"], "interrupted")
        self.pool.resume(job)
        self.until(job, TERMINAL)
        self.assertEqual(open(os.path.join(dst, "a.nii"), "rb").read(), A)

    def test_killed_worker_process_is_detected_and_recovered(self):
        src = big(os.path.join(self.E.base, "work", "K1", "x.nii"), 24)
        dst = os.path.join(self.E.vault, "studies", "K1")
        code = f"""
import os, sys, time
sys.path[:0] = {CHILD_PATH!r}
from uengine.transfer.workers import TransferWorkerPool
p = TransferWorkerPool({self.E.base!r}, {self.E.vault!r}, poll_s=0.05).start()
print("JOB " + p.submit("archive", [({os.path.dirname(src)!r}, {dst!r})], study_id="K1")["job_id"], flush=True)
time.sleep(120)
"""
        self.pool.shutdown(5)                     # only the child's pool may pick the job up (any pool could run it)
        self.pool.close()
        env = dict(os.environ, PERCIVAL_TEST_SLOW_AT="copy.chunk=0.1")
        child = subprocess.Popen([PY, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        job = child.stdout.readline().split()[1]
        wait(lambda: self.state(job) in ("copying", "flushing", "verifying"), what="child copying")
        self.assertEqual(self.svc.detect_interrupted(), [])                       # alive: never marked
        os.kill(child.pid, signal.SIGKILL)
        child.wait(timeout=30)
        self.pool = TransferWorkerPool(self.E.base, self.E.vault, poll_s=0.05).start()
        self.assertEqual(self.pool.detected_at_start, [job])
        self.pool.resume(job)
        self.until(job, TERMINAL)
        self.assertEqual(os.path.getsize(os.path.join(dst, "x.nii")), os.path.getsize(src))
        self.no_artifacts()

    def test_duplicate_execution_across_processes_is_impossible(self):
        srcs = [self.tree(f"D{i}", {"a.nii": A, "b.nii": B}) for i in range(3)]
        code = f"""
import sys, time
sys.path[:0] = {CHILD_PATH!r}
from uengine.transfer.workers import TransferWorkerPool
p = TransferWorkerPool({self.E.base!r}, {self.E.vault!r}, poll_s=0.01).start()
time.sleep(6); p.shutdown(5)
"""
        child = subprocess.Popen([PY, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                 env=dict(os.environ, PERCIVAL_TEST_SLOW_AT="checkpoint.before_stage=0.05"))
        self.slow("checkpoint.before_stage=0.05")
        jobs = [self.pool.submit("archive", [(s, os.path.join(self.E.vault, "studies", f"D{i}"))], study_id=f"D{i}")["job_id"]
                for i, s in enumerate(srcs)]
        for j in jobs:
            self.until(j, TERMINAL)
        child.wait(timeout=60)
        for j in jobs:
            prep = [e for e in self.svc.journal.events(j) if e["to_state"] == "preparing"]
            self.assertEqual(len(prep), 1, f"{j} executed {len(prep)} times")
            self.assertEqual(self.state(j), "completed")

    def test_simultaneous_jobs_same_device_run_one_at_a_time(self):
        self.slow("checkpoint.before_stage=0.05")
        jobs = [self.pool.submit("archive", [(self.tree(f"M{i}", {"a.nii": A, "b.nii": B}),
                                               os.path.join(self.E.vault, "studies", f"M{i}"))], study_id=f"M{i}")["job_id"]
                for i in range(4)]
        peak = [0]

        def sample():
            while not all(self.state(j) in TERMINAL for j in jobs):
                peak[0] = max(peak[0], len(self.pool.status()["running"]))
                time.sleep(0.005)
        sample()
        self.assertEqual(peak[0], 1)                                                # one worker per device
        self.assertEqual({self.state(j) for j in jobs}, {"completed"})

    def test_two_jobs_same_destination(self):
        src1 = self.tree("E1", {"a.nii": A})
        src2 = self.tree("E2", {"a.nii": A})
        src3 = self.tree("E3", {"a.nii": b"DIFFERENT"})
        dst = os.path.join(self.E.vault, "studies", "E")
        j1 = self.pool.submit("archive", [(src1, dst)], study_id="E")["job_id"]
        j2 = self.pool.submit("archive", [(src2, dst)], study_id="E")["job_id"]
        j3 = self.pool.submit("archive", [(src3, dst)], study_id="E")["job_id"]
        for j in (j1, j2):
            self.until(j, TERMINAL)
        self.until(j3, "needs_attention")
        self.assertEqual(open(os.path.join(dst, "a.nii"), "rb").read(), A)        # never overwritten
        self.assertEqual({self.state(j1), self.state(j2)}, {"completed"})

    def test_duplicate_requests_create_one_job(self):
        src, dst = self.tree("R1", {"a.nii": A}), os.path.join(self.E.vault, "studies", "R1")
        out, barrier = [], threading.Barrier(8)

        def go():
            barrier.wait()
            out.append(self.pool.submit("archive", [(src, dst)], study_id="R1", request_id="req-R1-0001"))
        ts = [threading.Thread(target=go) for _ in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(len({o["job_id"] for o in out}), 1)
        self.assertEqual(sum(1 for o in out if not o["duplicate"]), 1)
        self.until(out[0]["job_id"], TERMINAL)
        self.assertEqual(len(self.svc.journal.list_jobs()), 1)

    def test_disk_permission_failure_is_a_structured_failure(self):
        src = self.tree("X1", {"a.nii": A})
        studies = os.path.join(self.E.vault, "studies")
        os.chmod(studies, 0o555)
        try:
            job = self.pool.submit("archive", [(src, os.path.join(studies, "X1"))], study_id="X1")["job_id"]
            self.until(job, ("failed", "needs_attention"))
        finally:
            os.chmod(studies, 0o755)
        from uengine.transfer.api import job_summary
        s = job_summary(self.svc.journal.get_job(job), self.pool)
        self.assertEqual(s["error"]["code"], "failed")
        self.assertIn("Permission denied", s["error"]["message"])
        self.assertFalse(os.path.exists(os.path.join(studies, "X1")))


# ================================================================================================ real volumes
class TestVolumes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="p1d_fs_")
        cls.imgs, cls.mounts = {}, {}
        if not shutil.which("hdiutil"):
            return
        for key, fs, size in (("apfs", "APFS", "64m"), ("small", "HFS+", "8m"), ("exfat", "ExFAT", "32m")):
            img, mnt = os.path.join(cls.root, f"{key}.dmg"), os.path.join(cls.root, f"mnt_{key}")
            os.makedirs(mnt)
            if subprocess.run(["hdiutil", "create", "-quiet", "-size", size, "-fs", fs, "-volname", f"P1D{key}", img],
                              capture_output=True).returncode == 0:
                cls.imgs[key] = img
                if cls.attach(key):
                    cls.mounts[key] = mnt

    @classmethod
    def attach(cls, key):
        mnt = os.path.join(cls.root, f"mnt_{key}")
        subprocess.run(["hdiutil", "attach", "-quiet", "-nobrowse", "-noverify", "-mountpoint", mnt, cls.imgs[key]], capture_output=True)
        return os.path.ismount(mnt)

    @classmethod
    def tearDownClass(cls):
        for mnt in cls.mounts.values():
            for extra in ([], ["-force"]):
                if os.path.ismount(mnt):
                    subprocess.run(["hdiutil", "detach", "-quiet", *extra, mnt], capture_output=True)
        shutil.rmtree(cls.root, ignore_errors=True)

    def setUp(self):
        CPT.REACHED.clear()
        self.E = Env()
        self._env = mock.patch.dict(os.environ, {})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self.E.assert_protected_intact(self)
        self.E.close()

    def mnt(self, key):
        if key not in self.mounts:
            self.skipTest(f"{key} image unavailable")
        return self.mounts[key]

    def test_volume_disconnected_mid_copy_is_interrupted_not_rolled_back(self):
        mnt = self.mnt("apfs")
        vault = os.path.join(mnt, "PERCIVAL_VAULT")
        os.makedirs(os.path.join(vault, "studies"), exist_ok=True)
        src = big(os.path.join(self.E.base, "work", "V1", "x.nii"), 24)
        pool = TransferWorkerPool(self.E.base, vault, poll_s=0.05).start()
        svc = TransferService(self.E.base, vault)
        try:
            os.environ["PERCIVAL_TEST_SLOW_AT"] = "copy.chunk=0.15"
            job = pool.submit("archive", [(os.path.dirname(src), os.path.join(vault, "studies", "V1"))], study_id="V1")["job_id"]
            wait(lambda: CPT.REACHED.count("copy.chunk") >= 2, what="copying")
            subprocess.run(["hdiutil", "detach", "-quiet", "-force", mnt], capture_output=True)
            self.assertFalse(os.path.isdir(vault))
            wait(lambda: svc.journal.get_job(job)["state"] == "interrupted", what="interrupted")
            self.assertIn("volume unavailable", svc.journal.get_job(job)["error"])
            self.assertNotIn("rolling_back", [e["to_state"] for e in svc.journal.events(job)])
            os.environ.pop("PERCIVAL_TEST_SLOW_AT")
            self.assertTrue(self.attach("apfs"))
            pool.resume(job)
            wait(lambda: svc.journal.get_job(job)["state"] in TERMINAL, what="resumed")
            self.assertEqual(svc.journal.get_job(job)["state"], "completed")
            self.assertEqual(os.path.getsize(os.path.join(vault, "studies", "V1", "x.nii")), os.path.getsize(src))
            self.assertEqual(TR.list_stale_artifacts(vault), [])
        finally:
            pool.shutdown(5)
            pool.close()
            svc.close()
            if not os.path.ismount(mnt):
                self.attach("apfs")

    def test_real_disk_full_fails_cleanly(self):
        mnt = self.mnt("small")
        vault = os.path.join(mnt, "PERCIVAL_VAULT")
        os.makedirs(os.path.join(vault, "studies"), exist_ok=True)
        src = big(os.path.join(self.E.base, "work", "F1", "too_big.nii"), 20)
        pool = TransferWorkerPool(self.E.base, vault, poll_s=0.05).start()
        svc = TransferService(self.E.base, vault)
        try:
            job = pool.submit("archive", [(os.path.dirname(src), os.path.join(vault, "studies", "F1"))], study_id="F1")["job_id"]
            wait(lambda: svc.journal.get_job(job)["state"] in ("failed", "needs_attention", "interrupted"), what="disk full")
            job_rec = svc.journal.get_job(job)
            self.assertEqual(job_rec["state"], "failed")
            self.assertIn("No space left", job_rec["error"])
            self.assertFalse(os.path.exists(os.path.join(vault, "studies", "F1")))
            self.assertEqual(TR.list_stale_artifacts(vault), [])                   # the partial copy was removed
        finally:
            pool.shutdown(5)
            pool.close()
            svc.close()

    def test_exfat_destination_refused_by_the_endpoint_layer(self):
        vault = os.path.join(self.mnt("exfat"), "PERCIVAL_VAULT")
        os.makedirs(os.path.join(vault, "studies"), exist_ok=True)
        from uengine.transfer import api
        pool = TransferWorkerPool(self.E.base, vault, poll_s=0.05).start()
        try:
            r = api.handle_post("jobs/create", dict(operation="archive", items=[dict(src=self.E.work("M01/a.nii", b"a"),
                                                                                    dst=os.path.join(vault, "studies", "M01"))]), pool)
            self.assertFalse(r["ok"])
            self.assertEqual(r["error"]["code"], "refused")
            self.assertIn("exfat", r["error"]["message"])
            self.assertEqual(pool._svc.journal.list_jobs(), [])
        finally:
            pool.shutdown(5)
            pool.close()


# ================================================================================================ endpoints
class TestEndpoints(unittest.TestCase):
    """through app/css_app.py (bound to the isolated project) - direct calls and real HTTP"""

    @classmethod
    def setUpClass(cls):
        import css_app
        cls.app = css_app
        cls.B = css_app.B

    def tearDown(self):
        self.app.transfer_pool_shutdown(5)

    def files(self, rel, content):
        root = os.path.join(self.B, "work", rel)
        for n, d in content.items():
            _w(os.path.join(root, n), d)
        return root

    def done(self, job):
        return wait(lambda: self.app.transfer_get("job", {"id": job})["job"]["terminal"], what="job done")

    def test_create_validation(self):
        post = self.app.transfer_post
        cases = [dict(operation="delete", items=[dict(src="a", dst="b")]), dict(operation="archive", items=[]),
                 dict(operation="archive", items="x"), dict(operation="archive", items=[dict(src=1, dst="b")]),
                 dict(operation="archive", items=[dict(src="a", dst="b")], request_id="../x")]
        for c in cases:
            with self.subTest(c=c):
                r = post("jobs/create", c)
                self.assertFalse(r["ok"])
                self.assertEqual(r["error"]["code"], "bad_request")
        r = post("jobs/create", dict(operation="archive", items=[dict(src=self.files("V0", {"a.nii": A}),
                                                                       dst=os.path.join(self.B, "raw", "V0"))]))
        self.assertEqual(r["error"]["code"], "refused")                             # Phase 0 policy at the endpoint
        r = post("jobs/create", dict(operation="move", items=[dict(src=os.path.join(self.B, "review"),
                                                                    dst=os.path.join(self.B, "work", "stolen"))]))
        self.assertEqual(r["error"]["code"], "refused")
        for op in ("jobs/pause", "jobs/resume", "jobs/discard", "jobs/cancel"):
            self.assertEqual(post(op, dict(job_id="../x"))["error"]["code"], "bad_request")
            self.assertEqual(post(op, dict(job_id="nope"))["error"]["code"], "not_found")
        self.assertEqual(post("jobs/unknown", {})["error"]["code"], "not_found")
        self.assertEqual(self.app.transfer_get("job", {"id": "nope"})["error"]["code"], "not_found")
        self.assertEqual(self.app.transfer_get("jobs", {"state": "bogus"})["error"]["code"], "bad_request")

    def test_create_list_detail_assess_workers_for_each_operation(self):
        post, get = self.app.transfer_post, self.app.transfer_get
        jobs = {}
        jobs["archive"] = post("jobs/create", dict(operation="archive", items=[dict(src=self.files("EA", {"a.nii": A}),
                                                                                    dst=os.path.join(self.B, "work", "EA_arch"))]))
        stage_src = self.files("ES_src", {"a.nii": B})
        jobs["stage"] = post("jobs/create", dict(operation="stage", items=[dict(src=stage_src, dst=os.path.join(self.B, "work", "ES"))]))
        jobs["move"] = post("jobs/create", dict(operation="move", items=[dict(src=self.files("EM", {"a.nii": C}),
                                                                              dst=os.path.join(self.B, "work", "EM_out"))]))
        for op, r in jobs.items():
            self.assertTrue(r["ok"], r)
            self.done(r["job_id"])
            d = get("job", {"id": r["job_id"]})
            self.assertEqual(d["job"]["state"], "completed")
            self.assertEqual(d["job"]["operation"], op)
            self.assertEqual(d["job"]["progress"]["percent_committed"], 100.0)
            self.assertEqual([f["state"] for f in d["files"]], ["source_removed" if op == "move" else "committed"])
            self.assertTrue(any(e["to_state"] == "completed" for e in d["events"]))
            self.assertIsNone(d["job"]["error"])
        lst = get("jobs", {"limit": "10"})
        self.assertTrue({r["job_id"] for r in jobs.values()} <= {j["job_id"] for j in lst["jobs"]})
        self.assertEqual({j["state"] for j in get("jobs", {"state": "completed"})["jobs"]}, {"completed"})
        a = get("assess", {"id": jobs["archive"]["job_id"]})["assessment"]
        self.assertTrue(a["terminal"])
        w = get("workers", {})["workers"]
        self.assertTrue(w["alive"])

    def test_cancel_only_before_start_and_pause_resume_via_endpoints(self):
        post, get = self.app.transfer_post, self.app.transfer_get
        os.environ["PERCIVAL_TEST_SLOW_AT"] = "copy.chunk=0.05"
        try:
            src1 = os.path.dirname(big(os.path.join(self.B, "work", "C1", "x.nii"), 24))
            j1 = post("jobs/create", dict(operation="archive", items=[dict(src=src1, dst=os.path.join(self.B, "work", "C1_out"))]))["job_id"]
            wait(lambda: get("job", {"id": j1})["job"]["state"] == "copying", what="j1 copying")
            j2 = post("jobs/create", dict(operation="archive", items=[dict(src=self.files("C2", {"a.nii": A}),
                                                                           dst=os.path.join(self.B, "work", "C2_out"))]))["job_id"]
            self.assertEqual(post("jobs/cancel", dict(job_id=j2))["state"], "cancelled")
            self.assertFalse(os.path.exists(os.path.join(self.B, "work", "C2_out")))
            self.assertEqual(post("jobs/cancel", dict(job_id=j1))["error"]["code"], "refused")   # running: pause + discard
            self.assertTrue(post("jobs/pause", dict(job_id=j1))["ok"])
            wait(lambda: get("job", {"id": j1})["job"]["state"] == "paused", what="j1 paused")
            s = get("job", {"id": j1})["job"]
            self.assertFalse(s["running"])
            self.assertLess(s["progress"]["bytes_committed"], s["progress"]["bytes_total"])
        finally:
            os.environ.pop("PERCIVAL_TEST_SLOW_AT", None)
        self.assertEqual(post("jobs/resume", dict(job_id=j1))["requested"], "resume")
        self.done(j1)
        self.assertEqual(get("job", {"id": j1})["job"]["state"], "completed")

    def test_http_round_trip(self):
        srv = self.app.ThreadingHTTPServer(("127.0.0.1", 0), self.app.H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            base = f"http://127.0.0.1:{srv.server_address[1]}/api/transfer/"
            body = json.dumps(dict(operation="archive", request_id="http-req-1",
                                   items=[dict(src=self.files("H1", {"a.nii": A}), dst=os.path.join(self.B, "work", "H1_out"))])).encode()
            req = urllib.request.Request(base + "jobs/create", data=body, headers={"X-CSS-App": "1", "Content-Type": "application/json"})
            r = json.loads(urllib.request.urlopen(req, timeout=20).read())
            self.assertTrue(r["ok"], r)
            r2 = json.loads(urllib.request.urlopen(urllib.request.Request(base + "jobs/create", data=body,
                                                                         headers={"X-CSS-App": "1"}), timeout=20).read())
            self.assertTrue(r2["duplicate"])
            self.assertEqual(r2["job_id"], r["job_id"])
            wait(lambda: json.loads(urllib.request.urlopen(base + f"job?id={r['job_id']}", timeout=20).read())["job"]["terminal"])
            lst = json.loads(urllib.request.urlopen(base + "jobs", timeout=20).read())
            self.assertIn(r["job_id"], [j["job_id"] for j in lst["jobs"]])
            with self.assertRaises(urllib.error.HTTPError):                       # POST without the app header: forbidden
                urllib.request.urlopen(urllib.request.Request(base + "jobs/create", data=body), timeout=20)
            legacy = json.loads(urllib.request.urlopen(base + "summary", timeout=20).read())   # legacy endpoint unchanged
            self.assertIn("active_count", legacy)
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
