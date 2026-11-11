#!/usr/bin/env python3
"""Make the 'before' snapshot of v53_change_report.py AFTER redetect.py was already run (the snapshot step was forgotten).
Research software; expert review required.
usage: snapshot_from_backup.py M02,M03,...  [--backup review/backup_20261111_0910]
redetect.py copies the lists and calls it replaces to review/backup_<date_time>/. This tool (per study) puts the current NEW files aside, puts the backed-up OLD
lists and calls back in place, runs `v53_change_report.py snapshot` (which needs the old state because it scores the old accept sets), and puts the NEW files
back - always, also after an error; each restored file is checked by sha256. Afterwards run `v53_change_report.py after ...` and `inherit_calls.py ...` as usual.
Without --backup the newest review/backup_* folder is used. Caveat: the old AI/reader SCORES in the snapshot are computed with the NEW dark-voxel map in work/
(the zone changed with v5.3), so the 'before' scores can differ slightly from what you saw then; the lists, calls and fate of each old object are exact.
Files touched in review/: ID_candidates.*, ID_excluded.*, ID_calls*.csv, ID_missed.csv, ID_surface_features.csv (all restored)."""
import sys, os, glob, shutil, hashlib, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from css_common import base as _base
a = sys.argv[1:]
if not a or a[0].startswith("-"): sys.exit(__doc__)
B = _base(); S = os.path.dirname(os.path.abspath(__file__)); R = f"{B}/review"
bk = a[a.index("--backup") + 1] if "--backup" in a else (sorted(glob.glob(f"{R}/backup_*")) or [None])[-1]
if not bk or not os.path.isdir(bk): sys.exit("no backup folder (review/backup_*): redetect.py makes one")
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
print(f"backup: {bk}")
bad = []
for sid in [s for s in a[0].split(",") if s]:
    old = sorted(os.path.basename(f) for f in glob.glob(f"{bk}/{sid}_*"))
    if f"{sid}_candidates.csv" not in old or f"{sid}_candidates.nii.gz" not in old: print(f"{sid}: no old candidate list in the backup - skipped"); bad.append(sid); continue
    pat = (f"{sid}_candidates.*", f"{sid}_excluded.*", f"{sid}_calls*.csv", f"{sid}_missed.csv", f"{sid}_surface_features.csv")
    cur = sorted({f for p in pat for f in glob.glob(f"{R}/{p}")})
    stash = f"{R}/_new_stash_{sid}"; os.makedirs(stash, exist_ok=True)
    hashes = {os.path.basename(f): sha(f) for f in cur}
    for f in cur: shutil.move(f, f"{stash}/{os.path.basename(f)}")
    try:
        for n in old: shutil.copy2(f"{bk}/{n}", f"{R}/{n}")
        r = subprocess.run([sys.executable, f"{S}/v53_change_report.py", "snapshot", sid], env=dict(os.environ, CSS_BASE=B))
        if r.returncode: bad.append(sid)
    finally:
        for p in pat:
            for f in glob.glob(f"{R}/{p}"): os.remove(f)
        for n in os.listdir(stash): shutil.move(f"{stash}/{n}", f"{R}/{n}")
        os.rmdir(stash)
        miss = [n for n, h in hashes.items() if not os.path.exists(f"{R}/{n}") or sha(f"{R}/{n}") != h]
        print(f"{sid}: new files restored ({len(hashes)} checked)" + (f"   !!! CHANGED: {miss}" if miss else ""))
        if miss: bad.append(sid)
print("\nnext: python scripts/v53_change_report.py after " + a[0] + "   then: python scripts/inherit_calls.py " + a[0] + ' --reviewer "<primary reviewer>"' + (f"\nPROBLEMS: {', '.join(bad)}" if bad else ""))
sys.exit(1 if bad else 0)
