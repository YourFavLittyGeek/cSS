"""2026-11-25: setting a reviewer's role re-writes the EFFECTIVE calls (review/ID_calls.csv) of every study that reviewer called; before the
fix they stayed as written before the role change (empty for studies read before the reviewer became an expert). Also the startup check
finds studies whose effective calls are older than the roles journal. Temporary project only. Isolated (tests/_isolation.py)."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import os
import sys
import tempfile
import time
import unittest

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "scripts"), os.path.join(ROOT, "app")):
    if p not in sys.path: sys.path.insert(0, p)
import call_ledger as CL          # noqa: E402
import review_roles as RR         # noqa: E402
import review_calls_gui as RCG    # noqa: E402


class TestRoleRefresh(unittest.TestCase):
    def setUp(self):
        self.B = tempfile.mkdtemp(prefix="role_refresh_"); r = os.path.join(self.B, "review"); os.makedirs(r)
        C = pd.DataFrame([dict(cand_id=i, vox_i=10 * i, vox_j=20, vox_k=30, volume_mm3=40.0 + i, hemi="L") for i in (1, 2, 3)])
        for sid in ("S1", "S2"):
            C.to_csv(os.path.join(r, f"{sid}_candidates.csv"), index=False)
        rows = [dict(cand_id=i, call=c, comment="", reviewer="Dr A", time="2026-11-25 10:00:00", vox_i=10 * i, vox_j=20, vox_k=30,
                     volume_mm3=40.0 + i, fine_code="") for i, c in ((1, "cSS"), (2, "Vessel"), (3, "Normal"))]
        pd.DataFrame(rows).to_csv(os.path.join(r, "S1_calls_Dr_A.csv"), index=False)
        RR.verify_historical(self.B, "S1", "Dr A", "admin", "fixture", "synthetic blind labels written by the test", RR.CONFIRM_VERIFY)
        self.PAT = [dict(code="S1", cohort=""), dict(code="S2", cohort="")]

    def n_shared(self, sid):
        p = os.path.join(self.B, "review", f"{sid}_calls.csv")
        return len(pd.read_csv(p)) if os.path.exists(p) else None

    def test_role_change_rebuilds_effective_calls(self):
        CL.materialize(self.B, "S1", "", by="Dr A", rescore=False)
        self.assertEqual(self.n_shared("S1"), 0)                                    # no expert yet: nothing effective (the user's state)
        time.sleep(0.02)
        self.assertEqual(RCG.stale_effective(self.B, self.PAT), [])                 # no roles journal yet
        r = RCG.set_role(self.B, "Dr A", "expert", "admin", "is the expert", RR.CONFIRM_ROLE, PAT=self.PAT, background=False)
        self.assertEqual(r["rebuilding"], ["S1"])                                   # only the studies this reviewer called
        self.assertEqual(self.n_shared("S1"), 3)
        self.assertIsNone(self.n_shared("S2"))
        self.assertEqual(RCG.stale_effective(self.B, self.PAT), [])
        own = pd.read_csv(os.path.join(self.B, "review", "S1_calls_Dr_A.csv"))
        self.assertEqual(list(own.call), ["cSS", "Vessel", "Normal"])               # reviewer's own file untouched

    def test_startup_finds_studies_older_than_the_role_change(self):
        CL.materialize(self.B, "S1", "", by="Dr A", rescore=False)
        time.sleep(0.05)
        RR.set_role(self.B, "Dr A", "expert", "admin", "old route: no rebuild", RR.CONFIRM_ROLE)   # what the app did before the fix
        os.utime(RR.roles_journal(self.B), (time.time() + 5, time.time() + 5))
        self.assertEqual(RCG.stale_effective(self.B, self.PAT), ["S1"])
        RCG.refresh_effective(self.B, self.PAT, ["S1"])
        self.assertEqual(self.n_shared("S1"), 3)


if __name__ == "__main__":
    unittest.main()
