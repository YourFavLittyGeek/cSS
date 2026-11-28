"""2026-11-28 audit finding (data loss): an unreadable patients.json / settings.json must never be replaced by an empty default.
Truncated, empty, invalid, unreadable (permission), temporarily unreadable, interrupted write, recovery from backup, concurrent writers, and
the app's jload/jsave wiring. Temporary folders only. Isolated (tests/_isolation.py)."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import json
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "app"))
import safe_json as SJ          # noqa: E402

GOOD = [dict(code="Study-001", status="done"), dict(code="Study-002", status="done")]


class T(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="sj_"); SJ.PROBLEMS.clear(); self.p = os.path.join(self.d, "patients.json")

    def write(self, raw):
        with open(self.p, "wb") as f: f.write(raw)

    def test_missing_is_default(self):
        self.assertEqual(SJ.load(self.d, "patients.json", []), []); self.assertNotIn("patients.json", SJ.PROBLEMS)
        SJ.save(self.d, "patients.json", GOOD); self.assertEqual(SJ.load(self.d, "patients.json", []), GOOD)

    def _corrupt_case(self, raw):
        SJ.save(self.d, "patients.json", GOOD); SJ.save(self.d, "patients.json", GOOD + [dict(code="Study-003")])   # .bak = GOOD
        self.write(raw)
        v = SJ.load(self.d, "patients.json", [])
        self.assertEqual(v, GOOD)                                                     # last good backup, never []
        pr = SJ.PROBLEMS["patients.json"]; self.assertIn("backup", pr["action"]); self.assertTrue(os.path.exists(pr["preserved"]))
        with open(pr["preserved"], "rb") as f: self.assertEqual(f.read(), raw)          # the unreadable original is kept byte for byte

    def test_truncated(self): self._corrupt_case(b'[{"code": "Study-001", "sta')
    def test_empty(self): self._corrupt_case(b"")
    def test_whitespace(self): self._corrupt_case(b"  \n")
    def test_invalid(self): self._corrupt_case(b"not json at all")

    def test_no_backup_blocks_writes(self):
        self.write(b'{"broken": ')
        self.assertEqual(SJ.load(self.d, "patients.json", []), [])                    # the app can start ...
        self.assertTrue(SJ.blocked("patients.json"))
        with self.assertRaises(SJ.BlockedError): SJ.save(self.d, "patients.json", [])  # ... but can never overwrite the file
        with open(self.p, "rb") as f: self.assertEqual(f.read(), b'{"broken": ')
        self.assertFalse(SJ.unblock(self.d, "patients.json", "", "")["ok"])
        self.assertTrue(SJ.unblock(self.d, "patients.json", "Dr A", "file was test data")["ok"]); SJ.save(self.d, "patients.json", GOOD)

    def test_permission_error(self):
        SJ.save(self.d, "patients.json", GOOD)
        real = SJ._parse
        def deny(p):
            if p == self.p: raise PermissionError(13, "Permission denied")
            return real(p)
        with mock.patch.object(SJ, "_parse", side_effect=deny):
            self.assertEqual(SJ.load(self.d, "patients.json", []), [])                # no backup yet -> blocked, not empty-overwritten
        self.assertTrue(SJ.blocked("patients.json"))
        with self.assertRaises(SJ.BlockedError): SJ.save(self.d, "patients.json", [])

    def test_temporary_read_failure_retried(self):
        SJ.save(self.d, "patients.json", GOOD); real = SJ._parse; n = {"k": 0}
        def flaky(p):
            n["k"] += 1
            if n["k"] == 1: raise OSError("Resource temporarily unavailable")
            return real(p)
        with mock.patch.object(SJ, "_parse", side_effect=flaky): self.assertEqual(SJ.load(self.d, "patients.json", []), GOOD)
        self.assertNotIn("patients.json", SJ.PROBLEMS)

    def test_interrupted_write_keeps_old_file(self):
        SJ.save(self.d, "patients.json", GOOD)
        with mock.patch.object(SJ.os, "replace", side_effect=OSError("power lost")):
            with self.assertRaises(OSError): SJ.save(self.d, "patients.json", [dict(code="X")])
        self.assertEqual(SJ.load(self.d, "patients.json", []), GOOD)
        self.assertEqual([f for f in os.listdir(self.d) if ".tmp" in f], [])           # no temporary left behind

    def test_vanished_file_restored_from_backup(self):
        SJ.save(self.d, "patients.json", GOOD); SJ.save(self.d, "patients.json", GOOD); os.remove(self.p)
        self.assertEqual(SJ.load(self.d, "patients.json", []), GOOD)

    def test_concurrent_writers(self):
        errs = []
        def w(i):
            try:
                for k in range(30): SJ.save(self.d, "patients.json", [dict(code=f"T{i}-{k}")])
            except Exception as e: errs.append(e)
        th = [threading.Thread(target=w, args=(i,)) for i in range(6)]; [t.start() for t in th]; [t.join() for t in th]
        self.assertEqual(errs, []); self.assertEqual(len(SJ.load(self.d, "patients.json", [])), 1)

    def test_app_uses_it(self):
        src = open(os.path.join(ROOT, "app", "css_app.py")).read()
        i = src.index("def jload(name, default):"); body = src[i:i + 200]
        self.assertIn("SJ.load(AD, name, default)", body); self.assertNotIn("except Exception: return default", body)
        self.assertIn("SJ.save(AD, name, obj)", src); self.assertIn("state_problems=SJ.PROBLEMS", src)


if __name__ == "__main__":
    unittest.main()
