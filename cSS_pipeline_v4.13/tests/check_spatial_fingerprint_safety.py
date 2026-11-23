"""check_spatial_fingerprint_safety.py - Verifies that ambiguous or conflicting calls are never silently attached."""
import sys, os
import pandas as pd
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from css_common import match_calls, FP

def test_fingerprint_safety():
    # 1. Ambiguity test: One call, but two new candidates are almost equidistant (e.g. split)
    old_call = pd.DataFrame([dict(cand_id=1, vox_i=50.0, vox_j=50.0, vox_k=20.0, volume_mm3=100.0, hemi="L", call="cSS")])
    
    # Candidate A is at dist=1.0, Candidate B is at dist=1.2 (within 0.5 voxels of each other)
    cand_ambiguous = pd.DataFrame([
        dict(cand_id=10, vox_i=51.0, vox_j=50.0, vox_k=20.0, volume_mm3=98.0, hemi="L"),
        dict(cand_id=11, vox_i=50.0, vox_j=51.2, vox_k=20.0, volume_mm3=95.0, hemi="L"),
    ])
    
    m, dropped = match_calls(cand_ambiguous, old_call)
    assert m == {}, f"Ambiguous match should NOT attach, but attached: {m}"
    assert dropped == 1, f"Expected 1 dropped call due to ambiguity, got {dropped}"
    print("[PASS] Ambiguous candidate split is rejected from silent attachment.")

    # 2. Collision test: Two distinct old calls contend for the same new candidate
    old_two_calls = pd.DataFrame([
        dict(cand_id=1, vox_i=50.0, vox_j=50.0, vox_k=20.0, volume_mm3=100.0, hemi="L", call="cSS"),
        dict(cand_id=2, vox_i=50.5, vox_j=50.0, vox_k=20.0, volume_mm3=100.0, hemi="L", call="Vessel")
    ])
    single_cand = pd.DataFrame([
        dict(cand_id=10, vox_i=50.2, vox_j=50.0, vox_k=20.0, volume_mm3=100.0, hemi="L")
    ])
    m2, dropped2 = match_calls(single_cand, old_two_calls)
    assert m2 == {}, f"Conflicting calls contending for same candidate should NOT attach, got {m2}"
    assert dropped2 == 2, f"Expected 2 dropped calls due to collision, got {dropped2}"
    print("[PASS] Conflicting calls colliding on single candidate are rejected.")

    # 3. Hemisphere mismatch test: candidate centroid is close but on opposite hemisphere
    old_hemi_l = pd.DataFrame([dict(cand_id=1, vox_i=50.0, vox_j=50.0, vox_k=20.0, volume_mm3=100.0, hemi="L", call="cSS")])
    cand_hemi_r = pd.DataFrame([dict(cand_id=10, vox_i=50.5, vox_j=50.0, vox_k=20.0, volume_mm3=100.0, hemi="R")])
    m3, dropped3 = match_calls(cand_hemi_r, old_hemi_l)
    assert m3 == {}, f"Hemisphere mismatch should NOT attach, got {m3}"
    assert dropped3 == 1
    print("[PASS] Hemisphere mismatch is rejected from attachment.")

    # 4. Clean unambiguous match test: exactly one close candidate
    clean_cand = pd.DataFrame([
        dict(cand_id=10, vox_i=50.2, vox_j=50.0, vox_k=20.0, volume_mm3=98.0, hemi="L"),
        dict(cand_id=20, vox_i=80.0, vox_j=80.0, vox_k=20.0, volume_mm3=50.0, hemi="L")
    ])
    m4, dropped4 = match_calls(clean_cand, old_hemi_l)
    assert m4 == {10: "cSS"}, f"Expected clean match {10: 'cSS'}, got {m4}"
    assert dropped4 == 0
    print("[PASS] Clean unambiguous match successfully attaches.")

    print("\nALL SPATIAL FINGERPRINT SAFETY TESTS PASSED.")

if __name__ == "__main__":
    test_fingerprint_safety()
