"""2026-11-25 Remove / Purge know about the study's copy on the Pensieve drive: a choice is required (keep / drive Trash),
nothing is touched without it. Temporary folders, CSS_TRASH_DIR, stub identity store."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "app"))
import study_admin as SA                                                     # noqa: E402


def _w(p, d=b"x"):
    os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "wb").write(d); return p


class TestRemovePensieve(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp(prefix="rmpv_", dir=os.environ["CSS_BASE"])
        self.B = os.path.join(self.t, "proj"); self.AD = os.path.join(self.B, "app_data"); self.V = os.path.join(self.t, "vault")
        self.trash = os.path.join(self.t, "trash")
        _w(os.path.join(self.B, "review", "S5_candidates.csv")); _w(os.path.join(self.B, "review", "S5_calls_A.csv"))
        _w(os.path.join(self.B, "review", "S5_pensieve.json"), json.dumps(dict(state="in_pensieve", version="r1", files=[])).encode())
        _w(os.path.join(self.V, "studies", "S5", "r1", "data", "S5_swi.nii"), b"IMAGES")
        I = mock.MagicMock(); I.by_file_key.return_value = None; I.library.return_value = {}; I.unlocked.return_value = True
        self.dropped = []
        self.ctx = dict(ID=lambda: I, B=self.B, AD=self.AD, pget=lambda c: dict(code=c, status="done"), drop_pat=self.dropped.append,
                        after_edit=lambda c: None, vault=lambda: self.V)
        self.env = mock.patch.dict(os.environ, {"CSS_TRASH_DIR": self.trash}); self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_plan_shows_the_drive_copy(self):
        pv = SA.plan_removal(self.ctx, ["S5"], "purge")[0]["pensieve"]
        self.assertEqual(pv["state"], "in_pensieve")
        self.assertTrue(pv["exists"])
        self.assertEqual(pv["bytes"], 6)

    def test_no_choice_nothing_happens(self):
        r = SA.remove(self.ctx, ["S5"], "purge")
        self.assertFalse(r["ok"])
        self.assertIn("Pensieve", r["refused"][0]["why"])
        self.assertTrue(os.path.exists(os.path.join(self.B, "review", "S5_calls_A.csv")))
        self.assertTrue(os.path.isdir(os.path.join(self.V, "studies", "S5")))
        self.assertEqual(self.dropped, [])

    def test_keep_leaves_the_drive_copy(self):
        r = SA.remove(self.ctx, ["S5"], "purge", pensieve="keep")
        self.assertTrue(r["ok"], r)
        self.assertFalse(os.path.exists(os.path.join(self.B, "review", "S5_calls_A.csv")))
        self.assertTrue(os.path.isfile(os.path.join(self.V, "studies", "S5", "r1", "data", "S5_swi.nii")))

    def test_trash_moves_the_drive_copy_to_the_trash(self):
        r = SA.remove(self.ctx, ["S5"], "purge", pensieve="trash")
        self.assertTrue(r["ok"], r)
        self.assertFalse(os.path.exists(os.path.join(self.V, "studies", "S5")))
        self.assertTrue(any(n.startswith("Pensieve_S5_") for n in os.listdir(self.trash)))


if __name__ == "__main__":
    unittest.main()
