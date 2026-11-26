"""albus_measure.py SUBJECT FORCED_LABELS.nii.gz - ALBUS RE-DETECTION of expert-marked missed cSS (2026-11-25).

Runs the production detector (scripts/detect_css.py, verified against its pinned sha256 - the file itself is NOT changed) with three
in-memory additions:
  1. the objects of FORCED_LABELS (a label map on the SWI grid, one id per marked lesion) replace the generated objects just before
     the feature block, so every one is measured by the unchanged feature code;
  2. the exclusion rule that would remove an object is recorded (forced_would_exclude) but not applied;
  3. the output has the columns forced_obj (= the id in FORCED_LABELS) and forced_would_exclude.
Generation gates are soft (CSS_SOFT_GATES=1: the failed gate is recorded in soft_gate_fail). An object of < 5 voxels is dropped by the
detector as always.
NEVER run on a project: it writes the detector's outputs into $CSS_BASE. The app runs it on a disposable copy (percival/albus_redetect)."""
import hashlib, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DETECTOR = os.path.join(HERE, "detect_css.py")
PINNED = "c15b29f69af7af29aae408810ad859f5ba900b7c85ce9ffb7b2970685aee73bf"      # = uengine.provenance.DETECTOR_SHA256

PATCHES = [
    ("objs = ndi.find_objects(lab)\nrows = []",
     "_F = np.asarray(nib.load(FORCE_OBJ).dataobj).astype(np.int32)\n"
     "if _F.shape != lab.shape: sys.exit(f\"{subj}: forced objects are not on the SWI grid\")\n"
     "lab = _F; n_pieces = None; PIECES = None; del _F\n"
     "objs = ndi.find_objects(lab)\nrows = []"),
    ("for r in rows:\n    rv, r[\"_excl\"] = exclusion(r)\n",
     "for r in rows:\n    rv, r[\"_excl\"] = exclusion(r)\n"
     "    r[\"forced_would_exclude\"] = f\"{rv}: {r['_excl']}\" if rv else \"\"; rv, r[\"_excl\"] = \"\", \"\"\n"),
    ("    df[\"accept\"] = \"\"\n    df = df[cols]",
     "    df[\"accept\"] = \"\"\n    df[\"forced_obj\"] = df[\"_lab\"]; cols = cols + [\"forced_obj\", \"forced_would_exclude\"]\n    df = df[cols]"),
]


def source():
    raw = open(DETECTOR, "rb").read()
    if hashlib.sha256(raw).hexdigest() != PINNED:
        raise SystemExit("detect_css.py differs from the pinned version - ALBUS re-detection refused (update albus_measure.py with the detector)")
    s = raw.decode()
    for a, b in PATCHES:
        if s.count(a) != 1: raise SystemExit("detect_css.py: re-detection anchor not found")
        s = s.replace(a, b)
    return s


def main():
    if len(sys.argv) != 3: raise SystemExit(__doc__)
    sid, forced = sys.argv[1], os.path.abspath(sys.argv[2])
    if not os.path.exists(forced): raise SystemExit(f"{forced} not found")
    code = compile(source(), DETECTOR, "exec")
    os.environ["CSS_SOFT_GATES"] = "1"
    sys.argv = [DETECTOR, sid]
    g = {"__name__": "__main__", "__file__": DETECTOR, "FORCE_OBJ": forced}
    exec(code, g)


if __name__ == "__main__":
    main()
