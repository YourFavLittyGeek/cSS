"""uengine.imaging - Stage 2 P1: image index and geometry gate for candidate-level SWI image learning (SYNTHETIC data only).

Research software. Not for clinical use. Nothing here scores, excludes or changes a candidate; it describes image files and refuses
images whose geometry cannot be trusted. Every function that reads a study refuses a non-synthetic base or study (no override in P1).
Design: docs/stage2_image_learning/ (ARCHITECTURE_DESIGN, DATA_SCHEMA sections 2, IMAGE_PIPELINE_DESIGN section 2).

Production code reused VERBATIM (pinned sha256, never copied or edited):
  scripts/css_qc.py       orientation / obliquity block, QC thresholds, read_acq()
  scripts/detect_css.py   the detector's stop condition (array axis 2 must be the S-I axis and the thickest)
  scripts/css_surface.py  read_lta()"""
import os
from .. import provenance as pv

IMAGING_VERSION = "uengine-imaging/0.1"
INDEX_SCHEMA = "css-image-index/1.0"

CSS_QC = os.path.join(pv.SCRIPTS, "css_qc.py")
CSS_SURFACE = os.path.join(pv.SCRIPTS, "css_surface.py")
PINNED = {
    "scripts/css_qc.py": "ffc6af1656f7e23ce8262e6ffe3de6f73981d4629c424839acb86d2f3cf0442c",
    "scripts/css_surface.py": "674216e9135592c7384a793ba2512f1a82f97a6f64b9356f76e298b422584720",
    "scripts/detect_css.py": pv.DETECTOR_SHA256,
}


class NotSynthetic(PermissionError):
    """raised before any image file of a non-synthetic base or study is opened"""


def verify_sources():
    """-> list of (path, problem); empty = every production file the imaging package executes is byte-identical to the pinned one"""
    bad = []
    for rel, h in PINNED.items():
        p = os.path.join(pv.ROOT, rel)
        if not os.path.exists(p): bad.append((rel, "missing"))
        elif pv.sha256_file(p) != h: bad.append((rel, "sha256 differs from the pinned value"))
    return bad
