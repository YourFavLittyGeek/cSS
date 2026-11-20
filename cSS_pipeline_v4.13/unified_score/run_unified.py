"""run_unified.py - CLI of the EXPERIMENTAL unified cSS score (branch experimental/unified-score). Research only.
Reads production outputs read-only from $CSS_BASE; writes only to $CSS_BASE/uscore (or --out).

  python unified_score/run_unified.py extract [ID ...]   features + decomposition + detectors + perturbations (no labels)
  python unified_score/run_unified.py train              development studies only (manifest: M01-M26 since 2026-11-20): nested LOPO -> model_trained.json (NOT frozen)
  python unified_score/run_unified.py freeze FREEZE      freeze the trained model -> model_frozen.json
  python unified_score/run_unified.py score              frozen model -> categories + per-candidate reports (no labels)
  python unified_score/run_unified.py report             cohort report (development and held-out kept separate)
  python unified_score/run_unified.py heldout HASH       ONLY after approval: held-out labels with the frozen model hash
  python unified_score/run_unified.py app ID             the app's automatic step for one patient (any code; display only)

Without IDs, extract runs every included study (development and held-out). Suppression is disabled in this stage."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uscore import common as cm, pipeline as pl, report as rp

B = os.environ.get("CSS_BASE", os.path.expanduser("~/css_project"))
args = sys.argv[1:]
out = os.path.join(B, "uscore")
if "--out" in args: i = args.index("--out"); out = args[i + 1]; del args[i:i + 2]
if not args: sys.exit(__doc__)
cmd, rest = args[0], args[1:]
if os.environ.get("CSS_USCORE_DEMO") == "1":          # SYNTHETIC demo / GUI tests only: SYN studies, every output stamped synthetic
    C = cm.Cohort(os.environ["CSS_USCORE_MANIFEST"], eligible_prefix="SYN", synthetic_test=True)
else:
    C = cm.Cohort()
print(f"run_unified {cmd}: base {B}, out {out}, manifest {os.path.basename(C.manifest)} ({C.manifest_sha[:12]}), suppression "
      f"{'ENABLED' if cm.SUPPRESSION_ENABLED else 'disabled'}")
if cmd == "extract":
    ids = rest or (C.studies("development") + C.studies("held-out"))
    for s in ids:
        try:
            r = pl.extract_study(B, s, C, out); print(f"  {s}: {len(r)} candidates")
        except cm.CohortError as e:
            sys.exit(f"  REFUSED: {e}")
        except FileNotFoundError as e:
            print(f"  {s}: NOT EXTRACTED - {e} (recorded; the study stays in the manifest)")
elif cmd == "train":
    M, rep = pl.train(B, C, out)
    print(f"  model {M['model_hash'][:16]} trained (not frozen); development AUC {rep['outer_auc_calibrated']}, slope {rep['calibration_slope']}, "
          f"probability output {M['probability_output']}")
elif cmd == "score":
    ids = [s for s in C.studies("development") + C.studies("held-out") if os.path.exists(f"{out}/features/{s}.json")]
    r = pl.score(C, out, ids); print(f"  {len(r)} candidates scored")
elif cmd == "report":
    print("  ", rp.cohort_report(out))
elif cmd == "freeze":
    print("  ", pl.freeze(out, rest[0] if rest else ""))
elif cmd == "app":
    import json as _j
    r = pl.score_application(B, rest[0], C, out); print(_j.dumps(r))
elif cmd == "heldout":
    if not rest: sys.exit("heldout needs the frozen model hash (see model_frozen.json) - run only with the user's approval")
    r = pl.evaluate_heldout(B, C, out, rest[0]); print(f"  held-out: n {r['n']}, AUC {r['auc']}")
else:
    sys.exit(__doc__)
