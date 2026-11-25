"""2026-11-25 Transfer Center: live progress while copying, 'On this Mac' activity, Pensieve drive label (node, no project)."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import json
import os
import shutil
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VIEW = os.path.join(os.path.dirname(HERE), "app", "transfer_view.js")
NODE = shutil.which("node")
PJ_DIR = os.path.join(os.path.dirname(HERE), "app")


def run_js(expr):
    code = f"const T = require({json.dumps(VIEW)}); process.stdout.write(JSON.stringify({expr}));"
    r = subprocess.run([NODE, "-e", code], capture_output=True, text=True, timeout=30)
    if r.returncode:
        raise RuntimeError(r.stderr)
    return json.loads(r.stdout)


def job(state, **p):
    prog = dict(files_done=0, files_total=12, bytes_committed=0, bytes_staged=0, bytes_total=200 * 2 ** 20, current_file=None)
    prog.update(p)
    return dict(job_id="j1", operation="archive", study_id="Study-001", state=state, progress=prog)


@unittest.skipIf(NODE is None, "node is not installed")
class TestProgressText(unittest.TestCase):
    def test_copying_shows_copied_bytes_and_the_current_file(self):
        j = job("copying", bytes_staged=100 * 2 ** 20, current_file="work/Study-001_dark.nii.gz")
        t = run_js(f"T.tcProgressText({json.dumps(j)})")
        self.assertIn("100.0 MB of 200.0 MB copied (50 %)", t)
        self.assertIn("work/Study-001_dark.nii.gz", t)
        self.assertNotIn("0/12", t)                       # the old text said '0/N files, 0 B committed' for the whole copy

    def test_committing_counts_files_in_place(self):
        t = run_js(f"T.tcProgressText({json.dumps(job('committing', files_done=5, bytes_committed=80 * 2 ** 20))})")
        self.assertIn("5 of 12 files in place", t)

    def test_queued_and_completed(self):
        self.assertIn("Waiting to start", run_js(f"T.tcProgressText({json.dumps(job('queued'))})"))
        t = run_js(f"T.tcProgressText({json.dumps(job('completed', files_done=12, bytes_committed=200 * 2 ** 20))})")
        self.assertIn("12 of 12 files", t)

    def test_file_names_are_escaped(self):
        t = run_js(f"T.tcProgressText({json.dumps(job('copying', current_file='<img src=x>'))})")
        self.assertNotIn("<img", t)

    def test_drive_card_says_pensieve(self):
        t = run_js('T.tcVault({verdict: "unavailable", reasons: []}, {})')
        self.assertIn("Pensieve drive", t)
        self.assertIn("Not connected", t)
        self.assertNotIn("Vault", t)


@unittest.skipIf(NODE is None, "node is not installed")
class TestMacActivity(unittest.TestCase):
    def test_running_and_finished_rows(self):
        jobs = [dict(id="import-1", kind="import", title="Importing 3 examination(s)", state="running", done=1, total=4,
                     label="copying Study-002", pct=25, eta_s=120, error=""),
                dict(id="cleanup-1", kind="cleanup", title="Temporary MRI copies of Study-001 deleted", state="done", done=1,
                     total=1, label="310 MB freed on the Mac", pct=100, ended=1795600000, error="")]
        t = run_js(f"T.tcMac({json.dumps(jobs)})")
        self.assertIn("On this Mac", t)
        self.assertIn("copying Study-002 (1/4)", t)
        self.assertIn("about 2 min left", t)
        self.assertIn("310 MB freed on the Mac", t)
        self.assertEqual(run_js("T.tcMac([])"), "")

    def test_progress_jobs_note_and_recent(self):
        _s.path.insert(0, PJ_DIR)
        import progress_jobs as PJ
        PJ.note("cleanup", "Temporary MRI copies of Study-009 deleted", "12 MB freed on the Mac")
        r = PJ.recent()
        self.assertEqual(r[0]["kind"], "cleanup")
        self.assertEqual(r[0]["state"], "done")
        self.assertIn("ended", r[0])


if __name__ == "__main__":
    unittest.main()
