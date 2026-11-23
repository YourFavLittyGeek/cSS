"""Phase 1d safety audit: shutdown safety, resume / discard request durability, rollback-failure handling.

Isolated (tests/_isolation.py), synthetic data, temporary projects only. The real application (app/css_app.py run as a
program against a temporary project) is stopped with SIGTERM / SIGINT; worker processes are killed at random instants
(seeded fuzz) and at timed-out shutdown; rollback is made to fail by permission errors, journal failures, injected
I/O errors and SIGKILL."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import errno
import json
import os
import random
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "unified_engine"), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from test_phase1a_transfer_core import Env, _w                         # noqa: E402
from test_phase1c_recovery import Scenario, tree_fp, A, B, C            # noqa: E402
from test_phase1d_workers import big, wait                              # noqa: E402
from uengine.transfer import tree as TR                                 # noqa: E402
from uengine.transfer.models import FileState                           # noqa: E402
from uengine.transfer.service import TransferRefused, TransferService    # noqa: E402
from uengine.transfer.workers import TransferWorkerPool                  # noqa: E402

PY = sys.executable
CHILD_PATH = [os.path.join(ROOT, "unified_engine"), ROOT, HERE]
TERMINAL = {"completed", "completed_with_retained_sources", "cancelled"}
POOL_CHILD = r"""
import os, sys, time, json
sys.path[:0] = %(path)r
from uengine.transfer.workers import TransferWorkerPool
p = TransferWorkerPool(%(base)r, %(vault)r, poll_s=0.02).start()
job = p.submit(%(op)r, %(items)r, study_id=%(study)r)["job_id"]
print("JOB " + job, flush=True)
if %(shutdown_after)r is not None:
    while True:
        st = p._svc.journal.get_job(job)["state"]
        if st == %(shutdown_when)r or st in ("completed", "cancelled", "failed"):
            break
        time.sleep(0.01)
    rep = p.shutdown(timeout=%(shutdown_after)r)
    print("SHUTDOWN " + json.dumps(rep), flush=True)
    os._exit(0)                                   # exactly what the application does after its shutdown timeout
time.sleep(120)
"""


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Base(unittest.TestCase):
    def setUp(self):
        self.E = Env()
        self.svc = TransferService(self.E.base, self.E.vault)

    def tearDown(self):
        self.svc.close()
        self.E.assert_protected_intact(self)
        self.E.close()

    def state(self, job):
        return self.svc.journal.get_job(job)["state"]

    def pool_child(self, sc, env_extra, shutdown_after=None, shutdown_when=None):
        code = POOL_CHILD % dict(path=CHILD_PATH, base=self.E.base, vault=self.E.vault, op=sc.op, items=sc.items(),
                                 study=sc.study, shutdown_after=shutdown_after, shutdown_when=shutdown_when)
        env = dict(os.environ, **env_extra)
        p = subprocess.Popen([PY, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        job = p.stdout.readline().split()[1]
        return p, job


# ================================================================================================ 1. shutdown safety
class TestShutdownSafety(Base):
    def test_timed_out_shutdown_then_exit_leaves_nothing_running_and_the_job_recoverable(self):
        """a job inside a commit (no safe boundary) when the shutdown timeout expires: the process exits anyway (os._exit,
        like the app); afterwards nothing changes on disk any more, the job lock is free, and 1c recovers the job"""
        for decision in ("resume", "discard"):
            with self.subTest(decision=decision):
                self.svc.close()
                self.E.close()
                self.E = Env()
                self.svc = TransferService(self.E.base, self.E.vault)
                sc = Scenario(self.E, "archive")
                p, job = self.pool_child(sc, {"PERCIVAL_TEST_SLOW_AT": "commit.after_intent=3"},
                                         shutdown_after=0.5, shutdown_when="committing")
                out, _ = p.communicate(timeout=60)
                rep = json.loads(next(l for l in out.splitlines() if l.startswith("SHUTDOWN "))[9:])
                self.assertEqual(rep["still_running"], [job])                       # it did NOT reach a safe boundary
                self.assertEqual(p.returncode, 0)
                fp = tree_fp(self.E.tmp)
                time.sleep(1.5)
                self.assertEqual(tree_fp(self.E.tmp), fp, "a worker kept changing files after the process exited")
                self.assertEqual(self.state(job), "committing")                    # never 'completed' because it exited
                self.assertEqual(self.svc.journal.get_job(job)["control"], "pause")  # the dead owner's unanswered request
                self.assertEqual(self.svc.detect_interrupted(), [job])             # lock released by the dead process
                self.assertIsNone(self.svc.journal.get_job(job)["control"])         # ...is dropped with its owner
                r = self.svc.resume(job) if decision == "resume" else self.svc.discard(job)
                self.assertTrue(r["ok"], r)
                (sc.check_resumed if decision == "resume" else sc.check_discarded)(self)

    def _run_app(self, base, port, sig):
        home = os.path.join(self.E.tmp, f"apphome_{sig}")
        os.makedirs(home, exist_ok=True)
        env = dict(os.environ, HOME=home, CSS_BASE=base, PERCIVAL_TEST_SLOW_AT="copy.chunk=0.05")
        env.pop("PERCIVAL_TEST_CRASH_AT", None)
        app = subprocess.Popen([PY, os.path.join(ROOT, "app", "css_app.py"), "--port", str(port), "--no-window"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
        wait(lambda: socket.socket().connect_ex(("127.0.0.1", port)) == 0, 120, 0.1, "app listening")
        return app

    def test_real_application_sigterm_and_sigint_pause_running_transfers(self):
        for sig in (signal.SIGTERM, signal.SIGINT):
            with self.subTest(sig=sig.name):
                base = os.path.join(self.E.tmp, f"appproj_{sig.name}")
                os.makedirs(base)
                src = os.path.dirname(big(os.path.join(base, "work", "APP", "x.nii"), 40))
                port = free_port()
                app = self._run_app(base, port, sig.name)
                try:
                    url = f"http://127.0.0.1:{port}/api/transfer/"
                    body = json.dumps(dict(operation="archive", items=[dict(src=src, dst=os.path.join(base, "work", "APP_out"))])).encode()
                    r = json.loads(urllib.request.urlopen(urllib.request.Request(url + "jobs/create", data=body,
                                                                                 headers={"X-CSS-App": "1"}), timeout=30).read())
                    job = r["job_id"]
                    wait(lambda: json.loads(urllib.request.urlopen(url + f"job?id={job}", timeout=10).read())["job"]["state"] == "copying",
                         60, 0.05, "app copying")
                    app.send_signal(sig)
                    app.wait(timeout=60)
                finally:
                    if app.poll() is None:
                        app.kill()
                        app.wait()
                svc = TransferService(base, None)
                try:
                    self.assertEqual(svc.journal.get_job(job)["state"], "paused")    # paused at a safe boundary on exit
                    f0 = svc.journal.get_files(job)[0]
                    self.assertTrue(os.path.exists(f0["part_path"]))                 # own partial copy kept for resume
                    self.assertEqual(svc.detect_interrupted(), [])
                    self.assertTrue(svc.resume(job)["ok"])
                    self.assertEqual(os.path.getsize(os.path.join(base, "work", "APP_out", "x.nii")), 40 * 1024 * 1024)
                    self.assertEqual(TR.list_stale_artifacts(os.path.join(base, "work")), [])
                finally:
                    svc.close()

    def test_random_instant_kill_fuzz(self):
        """SIGKILL of a worker process at random instants (not only at named boundaries): every job is recoverable and
        no data is ever lost or left half-published"""
        rnd = random.Random(20261123)
        slow = ",".join(f"{p}=0.02" for p in ("copy.chunk", "checkpoint.before_stage", "commit.after_intent", "commit.after_publish",
                                              "commit.after_record", "move.after_intent", "move.after_remove", "finalize.after_intent",
                                              "checkpoint.between_commits", "stage.after_verified"))
        outcomes = {}
        for i in range(24):
            kind = ("archive", "stage", "move")[i % 3]
            decision = "resume" if (i // 3) % 2 == 0 else "discard"
            with self.subTest(i=i, kind=kind, decision=decision):
                self.svc.close()
                self.E.close()
                self.E = Env()
                self.svc = TransferService(self.E.base, self.E.vault)
                sc = Scenario(self.E, kind)
                p, job = self.pool_child(sc, {"PERCIVAL_TEST_SLOW_AT": slow})
                time.sleep(rnd.uniform(0.0, 0.5))
                p.kill()
                p.wait(timeout=30)
                st = self.state(job)
                if st in TERMINAL:
                    outcomes["finished_before_kill"] = outcomes.get("finished_before_kill", 0) + 1
                    sc.check_resumed(self)
                    continue
                if st != "queued":
                    self.assertEqual(self.svc.detect_interrupted(), [job])
                outcomes[st] = outcomes.get(st, 0) + 1
                # a kill between creating a .part and journaling its identity leaves an UNRECOGNIZED file: it must be
                # reported by the assessment and left untouched by recovery (then removed here by the test)
                unrec = [n.split(": ", 1)[1] for n in (self.svc.assess(job)["notes"] if st != "queued" else [])
                         if n.startswith("unrecognized temporary file")]
                if st == "queued":                                              # killed before the worker started
                    self.assertTrue(self.svc.run(job)["ok"])
                    sc.check_resumed(self)
                    continue
                r = self.svc.resume(job) if decision == "resume" else self.svc.discard(job)
                for u in unrec:
                    self.assertTrue(os.path.exists(u), "an unrecognized temporary file was deleted")
                    os.remove(u)
                    outcomes["unrecognized_left_untouched"] = outcomes.get("unrecognized_left_untouched", 0) + 1
                if decision == "resume":
                    self.assertTrue(r["ok"], r)
                    sc.check_resumed(self)
                elif r["state"] == "needs_attention":                           # previous version already finalized
                    self.assertEqual(kind, "stage")
                    for n in ("a.nii", "b.nii"):
                        self.assertIn(open(os.path.join(sc.dst, n), "rb").read(), (sc.content[n], b"OLD-LOCAL-" + n[0].upper().encode()))
                else:
                    self.assertEqual(r["state"], "cancelled", r)
                    sc.check_discarded(self)
        print(f"\n[fuzz] outcomes: {outcomes}", file=sys.stderr)
        self.assertGreaterEqual(sum(v for k, v in outcomes.items() if k not in ("finished_before_kill", "unrecognized_left_untouched")), 12, outcomes)


# ================================================================================================ 2. request durability
class TestRequestDurability(Base):
    def paused_job(self, kind="archive"):
        sc = Scenario(self.E, kind)
        pool = TransferWorkerPool(self.E.base, self.E.vault, poll_s=0.02).start()
        with mock.patch.dict(os.environ, {"PERCIVAL_TEST_SLOW_AT": "checkpoint.between_commits=0.5"}):
            job = pool.submit(sc.op, sc.items(), study_id=sc.study)["job_id"]
            wait(lambda: self.state(job) == "committing", what="committing")
            pool.pause(job)
            wait(lambda: self.state(job) == "paused", what="paused")
        pool.shutdown(5)
        pool.close()
        return sc, job

    def test_resume_request_lost_by_restart_is_harmless(self):
        sc, job = self.paused_job()
        pool = TransferWorkerPool(self.E.base, self.E.vault)                    # never started: request never runs
        self.assertEqual(pool.resume(job)["requested"], "resume")
        pool.close()                                                            # "restart"
        j = self.svc.journal.get_job(job)
        self.assertEqual((j["state"], j["recovery_decision"]), ("paused", None))  # nothing lost, nothing completed
        pool = TransferWorkerPool(self.E.base, self.E.vault, poll_s=0.02).start()
        try:
            self.assertEqual(pool.detected_at_start, [])
            pool.discard(job)                                                    # still the user's free choice
            wait(lambda: self.state(job) in TERMINAL, what="discarded")
            self.assertEqual(self.state(job), "cancelled")
            sc.check_discarded(self)
        finally:
            pool.shutdown(5)
            pool.close()

    def _killed_during(self, decision, point):
        sc, job = self.paused_job()
        code = f"""
import os, sys
sys.path[:0] = {CHILD_PATH!r}
from uengine.transfer.service import TransferService
s = TransferService({self.E.base!r}, {self.E.vault!r})
print(s.{decision}({job!r})["state"], flush=True)
"""
        p = subprocess.run([PY, "-c", code], capture_output=True, text=True, env=dict(os.environ, PERCIVAL_TEST_CRASH_AT=point), timeout=60)
        self.assertEqual(p.returncode, -9, p.stderr[-500:])
        return sc, job

    def test_restart_during_resume_keeps_the_decision_and_never_completes_by_itself(self):
        for point in ("recover.after_decision", "commit.after_intent", "commit.after_publish"):
            with self.subTest(point=point):
                self.svc.close()
                self.E.close()
                self.E = Env()
                self.svc = TransferService(self.E.base, self.E.vault)
                sc, job = self._killed_during("resume", point)
                self.assertEqual(self.state(job), "recovering")
                pool = TransferWorkerPool(self.E.base, self.E.vault, poll_s=0.02).start()
                try:
                    self.assertEqual(pool.detected_at_start, [job])
                    j = self.svc.journal.get_job(job)
                    self.assertEqual((j["state"], j["recovery_decision"]), ("interrupted", "resume"))
                    self.assertFalse([e for e in self.svc.journal.events(job) if e["to_state"] == "completed"])
                    with self.assertRaises(TransferRefused):
                        pool.discard(job)                                        # decision cannot be switched
                    pool.resume(job)
                    wait(lambda: self.state(job) in TERMINAL, what="resumed")
                    sc.check_resumed(self)
                finally:
                    pool.shutdown(5)
                    pool.close()

    def test_restart_during_discard_keeps_the_decision(self):
        sc, job = self._killed_during("discard", "undo.after_remove")
        pool = TransferWorkerPool(self.E.base, self.E.vault, poll_s=0.02).start()
        try:
            self.assertEqual(pool.detected_at_start, [job])
            self.assertEqual(self.svc.journal.get_job(job)["recovery_decision"], "discard")
            with self.assertRaises(TransferRefused):
                pool.resume(job)
            pool.discard(job)
            wait(lambda: self.state(job) in TERMINAL, what="discarded")
            sc.check_discarded(self)
        finally:
            pool.shutdown(5)
            pool.close()

    def test_graceful_shutdown_during_resume_pauses_with_the_decision(self):
        sc, job = self.paused_job()
        pool = TransferWorkerPool(self.E.base, self.E.vault, poll_s=0.02).start()
        with mock.patch.dict(os.environ, {"PERCIVAL_TEST_SLOW_AT": "checkpoint.resume_before_commit=0.5"}):
            pool.resume(job)
            wait(lambda: self.state(job) == "recovering", what="recovering")
            rep = pool.shutdown(10)
        pool.close()
        self.assertEqual(rep["states"][job], "paused")
        self.assertEqual(self.svc.journal.get_job(job)["recovery_decision"], "resume")
        self.assertTrue(self.svc.resume(job)["ok"])
        sc.check_resumed(self)


# ================================================================================================ 3. rollback failures
class TestRollbackFailures(Base):
    def test_permission_error_during_rollback_needs_attention_and_deletes_nothing_unproven(self):
        sc = Scenario(self.E, "archive")
        job = self.svc.submit(sc.op, sc.items(), study_id=sc.study)

        def fail_third(i, f):
            if i == 2:
                os.chmod(sc.dst, 0o555)                                          # rollback can no longer remove files
                raise OSError(errno.EACCES, "Permission denied (simulated during commit)")
        try:
            r = self.svc.run(job, _hooks={"before_commit": fail_third})
            self.assertEqual(r["state"], "needs_attention", r)                  # not crashed, not "failed", not guessed
            self.assertTrue(any("could not be completed" in e for e in r["errors"]), r["errors"])
            st = {f["rel_path"]: f["state"] for f in self.svc.journal.get_files(job)}
            self.assertEqual(st["a.nii"], "rolling_back")                       # intent journaled, undo pending
            self.assertEqual(open(os.path.join(sc.dst, "a.nii"), "rb").read(), A)
        finally:
            os.chmod(sc.dst, 0o755)
        d = self.svc.discard(job)                                                # 1c discard finishes the undo later
        self.assertEqual(d["state"], "cancelled", d)
        sc.check_discarded(self)

    def test_journal_failure_during_rollback_never_deletes(self):
        sc = Scenario(self.E, "archive")
        job = self.svc.submit(sc.op, sc.items(), study_id=sc.study)
        real = self.svc.journal.transition_file

        def no_undo_intent(job_id, seq, new_state, *a, **k):
            if FileState(new_state) == FileState.ROLLING_BACK:
                raise sqlite3.OperationalError("database or disk is full (simulated)")
            return real(job_id, seq, new_state, *a, **k)

        def fail_third(i, f):
            if i == 2:
                raise OSError(errno.ENOSPC, "No space left on device (simulated)")
        with mock.patch.object(self.svc.journal, "transition_file", side_effect=no_undo_intent):
            r = self.svc.run(job, _hooks={"before_commit": fail_third})
        self.assertEqual(r["state"], "needs_attention", r)
        for n, d in (("a.nii", A), ("b.nii", B)):                                # intent could not be written -> no delete
            self.assertEqual(open(os.path.join(sc.dst, n), "rb").read(), d)
        d = self.svc.discard(job)
        self.assertEqual(d["state"], "cancelled", d)
        sc.check_discarded(self)

    def test_changed_file_during_failing_job_is_never_deleted(self):
        sc = Scenario(self.E, "archive")
        job = self.svc.submit(sc.op, sc.items(), study_id=sc.study)

        def tamper_then_fail(i, f):
            if i == 2:
                with open(os.path.join(sc.dst, "a.nii"), "ab") as fh:
                    fh.write(b"edited by someone else")
                raise OSError(errno.EIO, "I/O error (simulated)")
        r = self.svc.run(job, _hooks={"before_commit": tamper_then_fail})
        self.assertEqual(r["state"], "needs_attention", r)
        self.assertTrue(open(os.path.join(sc.dst, "a.nii"), "rb").read().endswith(b"edited by someone else"))
        self.assertFalse(os.path.exists(os.path.join(sc.dst, "b.nii")))         # ours -> rolled back
        self.assertIn(os.path.join(sc.dst, "a.nii"), [x["path"] for x in r["left_untouched"]])

    def test_disk_full_rollback_follows_intent_and_identity(self):
        sc = Scenario(self.E, "stage")
        job = self.svc.submit(sc.op, sc.items(), study_id=sc.study)

        def fail(i, f):
            if i == 2:
                raise OSError(errno.ENOSPC, "No space left on device (simulated)")
        r = self.svc.run(job, _hooks={"before_commit": fail})
        self.assertEqual(r["state"], "failed", r)
        sc.check_discarded(self)                                                 # previous local versions restored
        ev = self.svc.journal.events(job)
        undo = [(e["seq"], e["to_state"]) for e in ev if e["kind"] == "file" and e["to_state"] in ("rolling_back", "rolled_back")]
        for seq in (0, 1):                                                       # intent BEFORE the undo, for every commit
            self.assertLess(undo.index((seq, "rolling_back")), undo.index((seq, "rolled_back")))

    def test_sigkill_during_rollback_then_recovery(self):
        for point, decision in (("undo.after_intent", "resume"), ("undo.after_remove", "discard"), ("undo.after_restore", "discard"),
                                ("undo.after_remove:2", "resume")):
            with self.subTest(point=point, decision=decision):
                self.svc.close()
                self.E.close()
                self.E = Env()
                self.svc = TransferService(self.E.base, self.E.vault)
                sc = Scenario(self.E, "stage")
                code = f"""
import sys
sys.path[:0] = {CHILD_PATH!r}
from uengine.transfer.service import TransferService
s = TransferService({self.E.base!r}, {self.E.vault!r})
j = s.submit({sc.op!r}, {sc.items()!r}, study_id={sc.study!r}); print("JOB " + j, flush=True)
s.run(j)
"""
                env = dict(os.environ, PERCIVAL_TEST_FAIL_AT="commit.after_intent:3=ENOSPC", PERCIVAL_TEST_CRASH_AT=point)
                p = subprocess.run([PY, "-c", code], capture_output=True, text=True, env=env, timeout=60)
                job = p.stdout.split()[1]
                self.assertEqual(p.returncode, -9, p.stderr[-500:])
                self.assertEqual(self.state(job), "rolling_back")
                self.assertEqual(self.svc.detect_interrupted(), [job])
                r = self.svc.resume(job) if decision == "resume" else self.svc.discard(job)
                self.assertTrue(r["ok"], r)
                (sc.check_resumed if decision == "resume" else sc.check_discarded)(self)


if __name__ == "__main__":
    unittest.main()
