"""Phase 0: imported FIRST by `python -m unittest discover -s tests` (discovery imports test modules in sorted order), so the
documented plain command is isolated before any application module is imported. Every other test module also calls
_isolation.activate() itself, so running a single file is isolated too."""
import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import _isolation; _isolation.activate()  # noqa: E401,E702
import unittest


class TestIsolationBootstrap(unittest.TestCase):
    def test_isolation_is_active(self):
        st = _isolation.STATE
        self.assertTrue(st["active"])
        self.assertEqual(os.environ.get("PERCIVAL_TEST_ISOLATION"), "1")
        self.assertNotEqual(os.path.realpath(os.path.expanduser("~")), _isolation.REAL_HOME)


if __name__ == "__main__":
    unittest.main()
