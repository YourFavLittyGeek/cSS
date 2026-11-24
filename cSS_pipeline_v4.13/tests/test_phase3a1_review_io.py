"""Phase 3A.1 tests: cross-process safe writes and locking, append-only reviewer event journals, crash recovery and corruption
handling for the expert-review files. Synthetic projects only (temporary CSS_BASE); real reviewer server processes; real SIGKILL
crashes through the test-only crash points. Isolated (tests/_isolation.py)."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import glob
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
S = os.path.join(ROOT, "scripts")
for p in (S, os.path.join(ROOT, "unified_engine"), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)
import review_io as RIO                                                   # noqa: E402

FP = ["vox_i", "vox_j", "vox_k", "volume_mm3"]
CHILD_PATH = [S, os.path.join(ROOT, "unified_engine"), ROOT]


def sha(p):
    with open(p, "rb") as f: return hashlib.sha256(f.read()).hexdigest()


def run_child(code, env=None, timeout=60):
    return subprocess.run([sys.executable, "-c", f"import sys; sys.path[:0] = {CHILD_PATH!r}\n" + code], capture_output=True, text=True,
                          timeout=timeout, env=dict(os.environ, **(env or {})))


def new_project():
    b = tempfile.mkdtemp(prefix="p3a1_", dir=os.environ["CSS_BASE"])
    for d in ("review", "data", "work", "labels"): os.makedirs(os.path.join(b, d))
    return b


def calls_df(rows):
    return pd.DataFrame(rows, columns=["cand_id", "call", "comment", "reviewer", "time"] + FP + ["fine_code"])


def row(cid, call, comment="", rev="Reader A"):
    return dict(cand_id=cid, call=call, comment=comment, reviewer=rev, time="2026-11-23 10:00:00", vox_i=10 + cid, vox_j=12, vox_k=8,
                volume_mm3=30.0 + cid, fine_code="")


def make_study(b, sid="S1", n=6):
    """a tiny synthetic study the reviewer server can load: SWI, candidate label map, candidate table"""
    import nibabel as nib
    sh = (32, 32, 20); I = np.full(sh, 100.0, np.float32); lab = np.zeros(sh, np.int16); rows = []
    for k in range(1, n + 1):
        i, j, z = 4 + 4 * k, 8 + (k % 3) * 6, 6 + (k % 2) * 6
        lab[i:i + 2, j:j + 3, z:z + 2] = k; I[lab == k] = 40.0
        rows.append(dict(cand_id=k, hemi="L" if k % 2 else "R", region="ctx-lh-postcentral", volume_mm3=float((lab == k).sum()),
                         vox_i=i, vox_j=j + 1, vox_k=z, score=1.0 - k / 10, css_evidence=0.6, vein_evidence=0.4))
    aff = np.diag([1.0, 1.0, 1.0, 1.0])
    nib.save(nib.Nifti1Image(I, aff), os.path.join(b, "data", f"{sid}_swi.nii"))
    nib.save(nib.Nifti1Image(lab, aff), os.path.join(b, "review", f"{sid}_candidates.nii.gz"))
    pd.DataFrame(rows).to_csv(os.path.join(b, "review", f"{sid}_candidates.csv"), index=False)
    return [r["cand_id"] for r in rows]


class Server:
    """a real review_web.py process on a free port"""
    def __init__(self, base, sid="S1", env=None):
        os.makedirs(os.path.join(base, "home"), exist_ok=True)              # own HOME: the reviewer's Pensieve side-writes stay in this project
        with socket.socket() as so:
            so.bind(("127.0.0.1", 0)); port = so.getsockname()[1]
        self.p = subprocess.Popen([sys.executable, os.path.join(S, "review_web.py"), sid, "--no-browser", "--port", str(port)],
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                  env=dict(os.environ, CSS_BASE=base, HOME=os.path.join(base, "home"), PYTHONWARNINGS="ignore", **(env or {})))
        line = self.p.stdout.readline()
        if "http://" not in line: raise RuntimeError("reviewer did not start: " + line + self.p.stdout.read()[-2000:])
        self.u = "http://" + line.split("http://")[1].split()[0].rstrip("/")
        threading.Thread(target=lambda: [None for _ in self.p.stdout], daemon=True).start()   # drain output

    def get(self, path):
        for _ in range(240):
            try: return json.load(urllib.request.urlopen(self.u + path, timeout=60))
            except urllib.error.HTTPError as e: return json.load(e)
            except OSError: time.sleep(0.25)
        raise RuntimeError("no answer")

    def post(self, path, d):
        r = urllib.request.Request(self.u + path, json.dumps(d).encode(), {"Content-Type": "application/json", "X-CSS": "1"})
        try: return json.load(urllib.request.urlopen(r, timeout=120))
        except urllib.error.HTTPError as e: return json.load(e)

    def stop(self):
        if self.p.poll() is None: self.p.terminate()
        try: self.p.wait(10)
        except subprocess.TimeoutExpired: self.p.kill()


# ====================================================================== primitives
class TestAtomicWrites(unittest.TestCase):
    def test_crash_before_replace_keeps_the_old_file_and_tmp_is_cleaned(self):
        b = new_project(); p = os.path.join(b, "review", "f.csv")
        with open(p, "w") as f: f.write("old\n")
        r = run_child(f"import review_io as R; R.atomic_write_text({p!r}, 'new content\\n')", env=dict(PERCIVAL_TEST_CRASH_AT="review_io.after_tmp_write"))
        self.assertEqual(r.returncode, -9, r.stderr)
        self.assertEqual(open(p).read(), "old\n")
        left = [f for f in os.listdir(os.path.dirname(p)) if f.startswith(RIO.TMP_PREFIX)]
        self.assertEqual(len(left), 1)
        self.assertEqual(RIO.clean_orphan_tmp(os.path.dirname(p), older_than_s=0), 1)
        self.assertEqual([f for f in os.listdir(os.path.dirname(p)) if f.startswith(RIO.TMP_PREFIX)], [])

    def test_crash_after_replace_has_the_complete_new_file(self):
        b = new_project(); p = os.path.join(b, "review", "f.csv")
        with open(p, "w") as f: f.write("old\n")
        r = run_child(f"import review_io as R; R.atomic_write_text({p!r}, 'new content\\n')", env=dict(PERCIVAL_TEST_CRASH_AT="review_io.after_replace"))
        self.assertEqual(r.returncode, -9, r.stderr)
        self.assertEqual(open(p).read(), "new content\n")

    def test_file_and_folder_are_fsynced_and_mode_kept(self):
        b = new_project(); p = os.path.join(b, "review", "f.csv")
        with open(p, "w") as f: f.write("x")
        os.chmod(p, 0o640)
        real = os.fsync; calls = []
        with mock.patch("os.fsync", side_effect=lambda fd: (calls.append(fd), real(fd))):
            RIO.atomic_write_text(p, "y")
        self.assertGreaterEqual(len(calls), 2)                               # the file and its folder
        self.assertEqual(os.stat(p).st_mode & 0o777, 0o640)

    def test_append_line_closes_a_torn_last_line(self):
        b = new_project(); p = os.path.join(b, "review", "log.csv")
        with open(p, "w") as f: f.write("h\nfull\ntorn-par")
        RIO.append_line(p, "next")
        self.assertEqual(open(p).read(), "h\nfull\ntorn-par\nnext\n")


class TestLocks(unittest.TestCase):
    def test_study_lock_excludes_another_process_and_is_reentrant(self):
        b = new_project()
        child = subprocess.Popen([sys.executable, "-c", f"import sys,time; sys.path[:0]={CHILD_PATH!r}\nimport review_io as R\n"
                                  f"with R.study_lock({b!r}, 'S1'):\n    print('held', flush=True); time.sleep(2.0)"],
                                 stdout=subprocess.PIPE, text=True)
        self.assertEqual(child.stdout.readline().strip(), "held")
        t0 = time.monotonic()
        with self.assertRaises(RIO.LockTimeout):
            with RIO.study_lock(b, "S1", timeout=0.4): pass
        self.assertGreater(time.monotonic() - t0, 0.35)
        child.wait(10)
        with RIO.study_lock(b, "S1", timeout=2):
            with RIO.study_lock(b, "S1", timeout=2):                           # nested in one thread: no self-deadlock
                pass

    def test_threads_are_serialised(self):
        b = new_project(); inside = []; overlap = []
        def work():
            with RIO.study_lock(b, "S1"):
                inside.append(1)
                if len(inside) > 1: overlap.append(1)
                time.sleep(0.02); inside.pop()
        ts = [threading.Thread(target=work) for _ in range(8)]
        [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual(overlap, [])

    def test_bad_study_key_refused(self):
        for bad in ("../x", "a/b", "", ".hidden"):
            with self.assertRaises(ValueError): RIO.study_lock(new_project(), bad)


class TestJournal(unittest.TestCase):
    def test_hash_chain_verifies_and_tampering_is_reported(self):
        b = new_project()
        with RIO.study_lock(b, "S1"):
            for k in range(3): RIO.journal_append(b, "S1", "Reader A", "note", n=k)
        p = RIO.journal_path(b, "S1", "Reader A"); ev, probs = RIO.read_journal(p)
        self.assertEqual([e["seq"] for e in ev], [1, 2, 3]); self.assertEqual(probs, [])
        lines = open(p, "rb").read().split(b"\n")
        lines[1] = lines[1].replace(b'"n":1', b'"n":7')
        open(p, "wb").write(b"\n".join(lines))
        _, probs = RIO.read_journal(p)
        self.assertTrue(any("hash chain" in x for x in probs), probs)

    def test_torn_last_line_is_skipped_and_the_next_event_chains_to_the_last_good_one(self):
        b = new_project()
        with RIO.study_lock(b, "S1"):
            RIO.journal_append(b, "S1", "Reader A", "note", n=1)
        p = RIO.journal_path(b, "S1", "Reader A")
        with open(p, "ab") as f: f.write(b'{"schema":"review-events/1.0","seq":2,"tor')
        _, probs = RIO.read_journal(p)
        self.assertTrue(any("unreadable" in x for x in probs))
        with RIO.study_lock(b, "S1"): RIO.journal_append(b, "S1", "Reader A", "note", n=2)
        ev, probs = RIO.read_journal(p)
        self.assertEqual([e["n"] for e in ev], [1, 2])
        self.assertEqual([x for x in probs if "hash chain" in x or "sequence" in x], [])


# ====================================================================== reviewer tables: journal + recovery
class TestTableJournal(unittest.TestCase):
    def setUp(self):
        self.b = new_project(); self.p = os.path.join(self.b, "review", "S1_calls_Reader_A.csv")

    def write(self, rows, kind="call"):
        with RIO.study_lock(self.b, "S1"):
            RIO.ensure_table(self.b, "S1", "Reader A", "calls", self.p)
            return RIO.write_table(self.b, "S1", "Reader A", "calls", self.p, calls_df(rows), ["cand_id"] + FP, kind)

    def ensure(self):
        with RIO.study_lock(self.b, "S1"): return RIO.ensure_table(self.b, "S1", "Reader A", "calls", self.p)

    def history(self):
        self.write([row(1, "cSS")])
        self.write([row(1, "cSS"), row(2, "Vessel", 'tricky "quoted", comma\nand a newline')])
        self.write([row(2, "Normal", "changed my mind"), row(3, "cSS")])            # 1 removed, 2 corrected, 3 added
        self.write([row(3, "cSS"), row(2, "Normal", "changed my mind")])            # order changed
        return open(self.p, "rb").read()

    def test_every_change_is_an_event_and_the_file_rebuilds_byte_for_byte(self):
        final = self.history()
        ev, probs = RIO.read_journal(RIO.journal_path(self.b, "S1", "Reader A")); self.assertEqual(probs, [])
        self.assertEqual(len(ev), 4)
        self.assertIn("1|11|12|8|31.0", ev[2]["removed"])                            # the removed call stays in the history
        self.assertIn("Vessel", json.dumps(ev[1]["upserts"]))                        # the earlier (corrected) call is preserved
        os.remove(self.p)
        self.assertEqual(self.ensure()["status"], "recovered")
        self.assertEqual(open(self.p, "rb").read(), final)
        self.assertTrue(RIO.verify_study(self.b, "S1")["ok"])

    def test_records_added_in_non_sorted_order_rebuild_exactly(self):
        self.write([row(10, "cSS"), row(9, "Vessel"), row(2, "Normal")])       # one write, record keys not in text order ("10|" < "2|" < "9|")
        self.assertEqual(self.ensure()["status"], "ok")                        # the journal already agrees with the file (no repair needed)
        self.write([row(10, "cSS"), row(9, "Vessel"), row(2, "Normal"), row(11, "Artifact"), row(3, "cSS")])
        ev, _ = RIO.read_journal(RIO.journal_path(self.b, "S1", "Reader A"))
        self.assertEqual([e["kind"] for e in ev], ["call", "call"])            # no external-change / recovery event was needed
        final = open(self.p, "rb").read()
        self.assertEqual(self.ensure()["status"], "ok")
        os.remove(self.p); self.ensure(); self.assertEqual(open(self.p, "rb").read(), final)

    def test_crash_between_journal_and_file_rolls_forward(self):
        self.write([row(1, "cSS")]); before = open(self.p, "rb").read()
        df = calls_df([row(1, "cSS"), row(2, "Vessel")]); csv = os.path.join(self.b, "next.csv"); df.to_csv(csv, index=False)
        code = (f"import review_io as R, pandas as pd\n"
                f"with R.study_lock({self.b!r}, 'S1'):\n"
                f"    R.write_table({self.b!r}, 'S1', 'Reader A', 'calls', {self.p!r}, pd.read_csv({csv!r}, keep_default_na=False), "
                f"['cand_id', 'vox_i', 'vox_j', 'vox_k', 'volume_mm3'], 'call')")
        r = run_child(code, env=dict(PERCIVAL_TEST_CRASH_AT="review_io.after_journal"))
        self.assertEqual(r.returncode, -9, r.stderr)
        self.assertEqual(open(self.p, "rb").read(), before)                          # write-ahead: the journal is ahead of the file
        res = self.ensure()
        self.assertEqual((res["status"], "behind_journal" in res["detail"]), ("recovered", True))
        self.assertIn("Vessel", open(self.p).read())
        ev, _ = RIO.read_journal(RIO.journal_path(self.b, "S1", "Reader A"))
        self.assertEqual(ev[-1]["kind"], "recovered")

    def test_truncated_file_is_quarantined_and_rebuilt(self):
        final = self.history()
        open(self.p, "wb").write(final[: len(final) // 2])
        damaged = open(self.p, "rb").read()
        res = self.ensure()
        self.assertEqual(res["status"], "recovered")
        self.assertEqual(open(self.p, "rb").read(), final)
        q = glob.glob(os.path.join(self.b, "review", "quarantine", "*S1_calls_Reader_A.csv"))
        self.assertEqual(len(q), 1); self.assertEqual(open(q[0], "rb").read(), damaged)

    def test_garbage_file_is_quarantined_and_rebuilt(self):
        final = self.history()
        open(self.p, "wb").write(b"\x00\x01\x02 not a csv \xff")
        self.assertEqual(self.ensure()["status"], "recovered")
        self.assertEqual(open(self.p, "rb").read(), final)
        self.assertEqual(len(glob.glob(os.path.join(self.b, "review", "quarantine", "*"))), 1)

    def test_external_change_is_kept_and_recorded(self):
        self.history()
        ext = calls_df([row(5, "Artifact", "edited by another tool")]).to_csv(index=False)
        open(self.p, "w").write(ext)
        res = self.ensure()
        self.assertEqual(res["status"], "external_change")
        self.assertEqual(open(self.p).read(), ext)                                   # not overwritten
        ev, _ = RIO.read_journal(RIO.journal_path(self.b, "S1", "Reader A"))
        self.assertEqual((ev[-1]["kind"], ev[-1]["snapshot"]), ("external_change", ext))
        self.write([row(5, "Artifact", "edited by another tool"), row(6, "cSS")])       # later writes continue from it
        os.remove(self.p); self.ensure()
        self.assertIn("edited by another tool", open(self.p).read())

    def test_deliberate_restore_of_an_older_state_is_not_undone(self):
        self.write([row(1, "cSS")]); old = open(self.p, "rb").read()
        self.write([row(1, "cSS"), row(2, "Vessel")]); self.write([row(1, "cSS"), row(2, "Vessel"), row(3, "Normal")])
        open(self.p, "wb").write(old)                                               # two states back (a person restored a backup)
        self.assertEqual(self.ensure()["status"], "external_change")
        self.assertEqual(open(self.p, "rb").read(), old)

    def test_unreadable_file_without_journal_is_refused_and_left_untouched(self):
        open(self.p, "wb").write(b"\xff\xfe garbage")
        before = sha(self.p)
        with self.assertRaises(RIO.RecoveryError): self.ensure()
        self.assertEqual(sha(self.p), before)
        self.assertFalse(os.path.exists(RIO.journal_path(self.b, "S1", "Reader A")))

    def test_historical_file_reads_create_nothing_and_first_write_records_it_exactly(self):
        hist = calls_df([row(1, "cSS", "historical read"), row(2, "Vessel")]).to_csv(index=False).replace("\n", "\n", 1)
        open(self.p, "w").write(hist); t0 = os.stat(self.p).st_mtime_ns
        self.assertEqual(self.ensure()["status"], "no_journal")
        self.assertFalse(os.path.exists(RIO.journal_path(self.b, "S1", "Reader A")))
        self.assertEqual(os.stat(self.p).st_mtime_ns, t0)
        self.write([row(1, "cSS", "historical read"), row(2, "Vessel"), row(3, "Normal")])
        ev, _ = RIO.read_journal(RIO.journal_path(self.b, "S1", "Reader A"))
        self.assertEqual((ev[0]["kind"], ev[0]["snapshot"], ev[0]["file_sha256"]), ("baseline", hist, hashlib.sha256(hist.encode()).hexdigest()))
        self.assertTrue(RIO.verify_study(self.b, "S1")["ok"])


# ====================================================================== the real reviewer server
class TestReviewerServer(unittest.TestCase):
    def setUp(self):
        self.b = new_project(); self.ids = make_study(self.b)

    def test_concurrent_windows_lose_no_call_or_missed_mark(self):
        import review_roles as RR                                              # Phase 3A.3: the shared file holds EXPERT consensus only
        RR.set_role(self.b, "Reader A", "expert", "test admin", "fixture", RR.CONFIRM_ROLE)
        slow = dict(PERCIVAL_TEST_SLOW_AT="review_io.table_write=0.08")             # widens any read-modify-write race
        A, B2 = Server(self.b, env=slow), Server(self.b, env=slow)
        try:
            A.post("/api/reviewer", dict(name="Reader A"))
            jobs = []; replies = []
            post = lambda srv, path, body: replies.append((path, body.get("comment", body.get("cand_id")), srv.post(path, body)))
            for k, cid in enumerate(self.ids):                                       # the SAME reviewer in two windows, interleaved
                srv = A if k % 2 else B2
                jobs.append(threading.Thread(target=post, args=(srv, "/api/call", dict(study="S1", reviewer="Reader A", cand_id=cid, call="cSS"))))
                jobs.append(threading.Thread(target=post, args=(srv, "/api/missed", dict(study="S1", reviewer="Reader A" if k % 2 else "Reader B",
                                                                                              action="add", ijk=[3 + k, 3, 3], comment=f"m{k}"))))
            [j.start() for j in jobs]; [j.join() for j in jobs]
        finally:
            A.stop(); B2.stop()
        self.assertEqual([r for r in replies if not r[2].get("ok")], [], "every request must succeed (otherwise its cause is shown here)")
        c = pd.read_csv(os.path.join(self.b, "review", "S1_calls_Reader_A.csv"))
        self.assertEqual(sorted(c.cand_id.astype(int)), sorted(self.ids))
        m = pd.read_csv(os.path.join(self.b, "review", "S1_missed.csv"))
        self.assertEqual(sorted(m.comment), sorted(f"m{k}" for k in range(len(self.ids))))
        self.assertEqual(len(set(m.missed_id)), len(m))
        log = pd.read_csv(os.path.join(self.b, "review", "S1_review_log.csv"))
        self.assertEqual(len(log), len(self.ids))
        rep = RIO.verify_study(self.b, "S1"); self.assertTrue(rep["ok"], rep)
        sh = pd.read_csv(os.path.join(self.b, "review", "S1_calls.csv"))                # derived shared file still produced
        self.assertEqual(sorted(sh.cand_id.astype(int)), sorted(self.ids))

    def test_reviewer_killed_mid_save_recovers_on_restart(self):
        A = Server(self.b)
        try:
            A.post("/api/call", dict(study="S1", reviewer="Reader A", cand_id=self.ids[0], call="cSS"))
        finally: A.stop()
        A = Server(self.b, env=dict(PERCIVAL_TEST_CRASH_AT="review_io.after_journal"))
        try:
            with self.assertRaises(Exception):
                r = urllib.request.Request(A.u + "/api/call", json.dumps(dict(study="S1", reviewer="Reader A", cand_id=self.ids[1], call="Vessel")).encode(),
                                           {"Content-Type": "application/json", "X-CSS": "1"})
                urllib.request.urlopen(r, timeout=60).read()
            A.p.wait(10); self.assertEqual(A.p.returncode, -9)
        finally: A.stop()
        self.assertNotIn("Vessel", open(os.path.join(self.b, "review", "S1_calls_Reader_A.csv")).read())
        A = Server(self.b)
        try:
            m = A.get("/api/meta?study=S1&reviewer=Reader%20A")
            self.assertIn("rebuilt from the event journal", m["note"])
            self.assertEqual(m["calls"][str(self.ids[1])]["call"], "Vessel")
        finally: A.stop()
        self.assertTrue(RIO.verify_study(self.b, "S1")["ok"])

    def test_corrupt_reviewer_file_is_quarantined_and_rebuilt_by_the_server(self):
        A = Server(self.b)
        try:
            for cid in self.ids[:3]: A.post("/api/call", dict(study="S1", reviewer="Reader A", cand_id=cid, call="Normal", comment="c"))
            p = os.path.join(self.b, "review", "S1_calls_Reader_A.csv"); good = open(p, "rb").read()
            open(p, "wb").write(good[:40])
            m = A.get("/api/meta?study=S1&reviewer=Reader%20A")
            self.assertEqual(sorted(int(k) for k in m["calls"]), sorted(self.ids[:3]))
            self.assertEqual(open(p, "rb").read(), good)
            self.assertEqual(len(glob.glob(os.path.join(self.b, "review", "quarantine", "*"))), 1)
        finally: A.stop()

    def test_unrecoverable_file_is_refused_not_overwritten(self):
        p = os.path.join(self.b, "review", "S1_calls_Reader_A.csv")
        open(p, "wb").write(b"\xff\xfe not csv"); before = sha(p)
        A = Server(self.b)
        try:
            r = A.post("/api/call", dict(study="S1", reviewer="Reader A", cand_id=self.ids[0], call="cSS"))
            self.assertIn("RecoveryError", r.get("error", ""))
        finally: A.stop()
        self.assertEqual(sha(p), before)

    def test_missed_marks_journaled_and_deletions_kept_in_history(self):
        A = Server(self.b)
        try:
            A.post("/api/missed", dict(study="S1", reviewer="Reader A", action="add", ijk=[5, 5, 5], comment="first"))
            r = A.post("/api/missed", dict(study="S1", reviewer="Reader A", action="add", ijk=[6, 6, 6], comment="second"))
            A.post("/api/missed", dict(study="S1", reviewer="Reader A", action="delete", id=int(r["missed"][0]["missed_id"])))
        finally: A.stop()
        ev, _ = RIO.read_journal(RIO.journal_path(self.b, "S1", "Reader A"))
        dele = [e for e in ev if e.get("kind") == "missed_delete"]
        self.assertEqual(len(dele), 1); self.assertEqual(dele[0]["rows"][0]["status"], "deleted"); self.assertEqual(dele[0]["rows"][0]["comment"], "first")
        own = pd.read_csv(os.path.join(self.b, "review", "S1_missed_by_Reader_A.csv"))            # Phase 3A.3: tombstone kept in the reviewer's file
        self.assertEqual(sorted(own.status), ["active", "deleted"])
        os.remove(os.path.join(self.b, "review", "S1_missed.csv"))
        A = Server(self.b)
        try: m = A.get("/api/meta?study=S1&reviewer=Reader%20A")
        finally: A.stop()
        self.assertEqual([x["comment"] for x in m["missed"]], ["second"])


# ====================================================================== other writers of reviewer files
class TestLedgerWriters(unittest.TestCase):
    def test_consolidation_is_refused_and_a_restore_becomes_the_journal_head(self):
        import call_ledger as CL
        b = new_project()
        pd.DataFrame([dict(cand_id=1, vox_i=11, vox_j=12, vox_k=8, volume_mm3=31.0)]).to_csv(os.path.join(b, "review", "S1_candidates.csv"), index=False)
        p = os.path.join(b, "review", "S1_calls_Reader_A.csv")
        with RIO.study_lock(b, "S1"): RIO.write_table(b, "S1", "Reader A", "calls", p, calls_df([row(1, "cSS")]), ["cand_id"] + FP, "call")
        before = open(p, "rb").read()
        with self.assertRaises(PermissionError): CL.consolidate(b, ["S1"], CL.CONFIRM, by="tester")      # Phase 3A.4: removed
        self.assertEqual(open(p, "rb").read(), before)
        with RIO.study_lock(b, "S1"): RIO.write_table(b, "S1", "Reader A", "calls", p, calls_df([row(1, "Vessel")]), ["cand_id"] + FP, "call")
        arch = os.path.join(b, "review", "call_history", "S1", "manual_1"); os.makedirs(arch); open(os.path.join(arch, "S1_calls_Reader_A.csv"), "wb").write(before)
        CL.restore(b, "S1", os.path.relpath(arch, b))
        self.assertEqual(open(p, "rb").read(), before)
        ev, _ = RIO.read_journal(RIO.journal_path(b, "S1", "Reader A")); self.assertEqual(ev[-1]["kind"], "restore")
        self.assertIn("Vessel", json.dumps(ev))                                  # the later call stays in the history
        with RIO.study_lock(b, "S1"):
            self.assertEqual(RIO.ensure_table(b, "S1", "Reader A", "calls", p)["status"], "ok")

    def test_policy_changes_from_parallel_processes_are_all_kept(self):
        b = new_project()
        code = "import call_ledger as CL, sys\nfor k in range(5): CL.set_policy({b!r}, 'study', 'S%d_%d' % ({n}, k), dict(mode='consensus', quorum=1 + k % 2), by='p{n}')"
        ps = [subprocess.Popen([sys.executable, "-c", f"import sys; sys.path[:0] = {CHILD_PATH!r}\n" + code.format(b=b, n=n)]) for n in range(4)]
        [p.wait(60) for p in ps]
        P = json.load(open(os.path.join(b, "review", "call_policy.json")))
        self.assertEqual(len(P["studies"]), 20); self.assertEqual(len(P["history"]), 20)

    def test_inherit_calls_is_journaled(self):
        b = new_project(); make_study(b, "S1", 3)
        os.makedirs(os.path.join(b, "review", "changes"))
        pd.DataFrame([dict(fate="kept", new_id=1, call="cSS", cand_id=7), dict(fate="kept", new_id=2, call="Vessel", cand_id=8)]).to_csv(
            os.path.join(b, "review", "changes", "S1_old_candidates_fate.csv"), index=False)
        os.makedirs(os.path.join(b, "home"))
        r = run_child("import inherit_calls as I; print(I.run('S1', 'Reader A', False)[0])", env=dict(CSS_BASE=b, HOME=os.path.join(b, "home")))
        self.assertEqual(r.returncode, 0, r.stderr)
        ev, _ = RIO.read_journal(RIO.journal_path(b, "S1", "Reader A"))
        self.assertEqual(ev[-1]["kind"], "inherit"); self.assertEqual(ev[-1]["n_inherited"], 2)
        self.assertTrue(RIO.verify_study(b, "S1")["ok"])


if __name__ == "__main__":
    unittest.main()
