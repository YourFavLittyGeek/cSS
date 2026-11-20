#!/usr/bin/env python3
"""Re-run ONLY the detection on studies that are already prepared. Research software; expert review required.
usage: redetect.py M12,M13,M14,M15 [--v53] [--dry-run]
No skull-stripping, no FreeSurfer, no registration: it reuses data/ID_swi.nii and the label files in work/ that
run_css.sh made, and runs detect_css.py (then surface_features.py when recon-all surfaces exist), one study at a
time. A few minutes and about 2 GB of memory per study.
  --v53      detect with CSS_V53=1 (cortex-outline zone, skull / midline / extent / orbitofrontal rules, 6 mm merge)
  --dry-run  only list what would be done
Before each study the current review/ID_candidates.*, ID_excluded.*, ID_calls*.csv and ID_missed.csv are copied to
review/backup_<date_time>/. Calls are re-attached to the new list by candidate fingerprint; a call whose candidate
changed shape (e.g. merged by v5.3) is NOT carried over and that candidate must be read again - the reviewer says
how many. For studies that were already read, run v53_compare.py first: it changes nothing in the project."""
import sys, os, glob, shutil, subprocess, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from css_common import base as _base
a = sys.argv[1:]
if not a or a[0].startswith("-"): sys.exit(__doc__)
B = _base(); S = os.path.dirname(os.path.abspath(__file__)); v53 = "--v53" in a; dry = "--dry-run" in a
stamp = time.strftime("%Y%m%d_%H%M"); bk = f"{B}/review/backup_{stamp}"; ok = []; bad = []
for sid in [s for s in a[0].split(",") if s]:
    need = [f"{B}/data/{sid}_swi.nii", f"{B}/work/{sid}_seg_swispace.nii.gz"]
    miss = [f for f in need if not os.path.exists(f)]
    if miss:
        print(f"{sid}: NOT prepared ({', '.join(os.path.basename(f) for f in miss)} missing) - run run_css.sh for it first"); bad.append(sid); continue
    t1 = os.path.exists(f"{B}/work/{sid}_t1seg_swispace.nii.gz")
    print(f"{sid}: detect {'with v5.3' if v53 else '(v5.2 rules)'}; anatomy {'T1' if t1 else 'SWI-only' + (' - v5.3 will switch itself off' if v53 else '')}", flush=True)
    if dry: continue
    files = [f for pat in (f"{sid}_candidates.*", f"{sid}_excluded.*", f"{sid}_calls*.csv", f"{sid}_missed.csv", f"{sid}_surface_features.csv")
             for f in glob.glob(f"{B}/review/{pat}")]
    if files:
        os.makedirs(bk, exist_ok=True)
        for f in files: shutil.copy2(f, bk)
    env = dict(os.environ, CSS_V53="1" if v53 else "0")
    r = subprocess.run([sys.executable, f"{S}/detect_css.py", sid], env=env)
    if r.returncode: print(f"{sid}: detect_css.py stopped with exit code {r.returncode} (see the message above)"); bad.append(sid); continue
    if os.path.exists(f"{B}/subjects/{sid}/surf/lh.pial") and os.path.exists(f"{S}/surface_features.py"):
        if subprocess.run([sys.executable, f"{S}/surface_features.py", sid], env=env).returncode: print(f"{sid}: surface_features.py failed (detection is complete)")
    ok.append(sid)
print(f"\ndone: {', '.join(ok) or 'none'}" + (f"   NOT done: {', '.join(bad)}" if bad else "") + (f"\nprevious lists and calls: {bk}" if ok and os.path.isdir(bk) else "")
      + ("\nread them with:  python scripts/review_web.py " + ",".join(ok) if ok else ""))
