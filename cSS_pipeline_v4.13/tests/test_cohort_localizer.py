"""2026-11-25 cohort.py import: a 1-slice localizer that dcm2niix split off the SWI series is never chosen as the SWI
(Study-026 ran on 400_SWAN_i00001, 512x512x1, instead of 400_SWAN_i00002, 512x512x52). NIfTI only, temporary CSS_BASE."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import json
import os
import subprocess
import sys
import tempfile
import unittest

import nibabel as nib
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
S = os.path.join(os.path.dirname(HERE), "scripts")


def series(folder, name, vox, shape, desc="SWAN", it=("ORIGINAL", "PRIMARY", "M", "SWI")):
    os.makedirs(folder, exist_ok=True)
    nib.save(nib.Nifti1Image(np.ones(shape, np.float32), np.diag(list(vox) + [1.0])), f"{folder}/{name}.nii.gz")
    json.dump(dict(SeriesDescription=desc, ImageType=list(it), EchoTime=0.02), open(f"{folder}/{name}.json", "w"))


class TestLocalizer(unittest.TestCase):
    def test_real_volume_beats_a_finer_single_slice(self):
        B = tempfile.mkdtemp(prefix="cohort_loc_", dir=os.environ["CSS_BASE"]); C = f"{B}/cohort"
        series(f"{C}/L01/SWI", "400_SWAN_i00001", (0.47, 0.47, 0.47), (40, 40, 1))
        series(f"{C}/L01/SWI", "400_SWAN_i00002", (0.39, 0.39, 3.0), (40, 40, 52))
        series(f"{C}/L02/SWI", "10_SWI_Images", (0.9, 0.9, 1.5), (20, 20, 12))            # normal study: unchanged
        series(f"{C}/L02/SWI", "11_SWI_Images_Eq_1", (0.8, 0.8, 1.5), (20, 20, 12))
        r = subprocess.run([sys.executable, f"{S}/cohort.py", "import", C], capture_output=True, text=True, env=dict(os.environ, CSS_BASE=B))
        self.assertEqual(r.returncode, 0, r.stdout[-800:] + r.stderr[-800:])
        T = pd.read_csv(f"{B}/review/cohort_import.csv", dtype=str).fillna("").set_index("study_id")
        self.assertTrue(T.loc["L01", "swi"].endswith("400_SWAN_i00002.nii.gz"), T.loc["L01", "swi"])
        self.assertIn("swi_localizer_skipped", T.loc["L01", "flags"])
        self.assertTrue(T.loc["L02", "swi"].endswith("11_SWI_Images_Eq_1.nii.gz"))      # smallest voxel still wins otherwise
        self.assertNotIn("swi_localizer_skipped", T.loc["L02", "flags"])


if __name__ == "__main__":
    unittest.main()
