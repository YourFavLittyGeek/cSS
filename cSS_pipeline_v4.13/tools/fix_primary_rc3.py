#!/usr/bin/env python3
"""One-time fix for RC3 (v5.14.2-rc3): make the reviewer's own reads count in the EXPERIMENTAL project.

Problem: RC3's import copied review/<ID>_primary.json (the study's earlier production primary reviewer, e.g. "Redo_v53") into the
experimental project. For those studies your reads were saved only to review/<ID>_calls_<you>.csv, not to the shared
review/<ID>_calls.csv that Results and training read.

What it does, per study where <ID>_calls_<READER>.csv exists and the primary reviewer is someone else:
  1. backs up every file it will touch into review/backup_fixprimary_<time>/ (nothing is deleted)
  2. moves the imported <ID>_primary.json to historical/<ID>/review/ (where the other earlier reader files are)
  3. makes READER the primary reviewer (the reviewer's own primary() function)
  4. re-saves READER's calls with the reviewer's own functions (matched to the current candidates by fingerprint, exactly as the
     reviewer does) -> writes the shared <ID>_calls.csv; READER's own file keeps the same calls
  5. if READER's score file <ID>_score_rev_<READER>.json exists and there is no shared <ID>_score.json, copies it to <ID>_score.json
Reads nothing from and writes nothing to ~/css_project. Dry run unless --apply.

usage (Mac, conda env css):
  CSS_BASE=~/cSS_experimental python3 fix_primary_rc3.py Selim            # dry run: shows what would change
  CSS_BASE=~/cSS_experimental python3 fix_primary_rc3.py Selim --apply    # does it
"""
import os, sys, glob, json, shutil, time
args = [a for a in sys.argv[1:] if not a.startswith("--")]
if not args: sys.exit(__doc__)
READER, APPLY = args[0], "--apply" in sys.argv
B = os.path.realpath(os.path.expanduser(os.environ.get("CSS_BASE", "~/cSS_experimental")))
PROD = os.path.realpath(os.path.expanduser("~/css_project"))
if B == PROD or B.startswith(PROD + "/"): sys.exit("refused: CSS_BASE is the production project; this fix is for the experimental project only")
if not os.path.isdir(f"{B}/review") or not os.path.isdir(f"{B}/scripts"): sys.exit(f"refused: {B} does not look like the experimental project")
sys.path.insert(0, f"{B}/scripts")
import review_web as rw

todo = []
for f in sorted(glob.glob(f"{B}/review/*_calls_{rw.slug(READER)}.csv")):
    sid = os.path.basename(f)[:-len(f"_calls_{rw.slug(READER)}.csv")]
    cur = rw.primary(sid)
    if cur == READER.strip(): print(f"  {sid}: already primary = {READER} - nothing to do"); continue
    todo.append((sid, cur, f))
print(f"{len(todo)} studies to fix (reader {READER}, project {B}){'' if APPLY else ' - DRY RUN, add --apply to change files'}")
stamp = time.strftime("%Y%m%d_%H%M%S"); bk = f"{B}/review/backup_fixprimary_{stamp}"
for sid, cur, f in todo:
    rw.IDS[:] = [sid]; s = rw.study(sid)
    mine, note = s._read_calls(f, "")
    n = sum(1 for v in mine.values() if v.get("call"))
    shared = f"{B}/review/{sid}_calls.csv"; sp = f"{B}/review/{sid}_score_rev_{rw.slug(READER)}.json"; ss = f"{B}/review/{sid}_score.json"
    print(f"  {sid}: primary '{cur or '-'}' -> '{READER}'; {n} calls -> shared {os.path.basename(shared)}"
          f"{' (replaces existing shared file, backed up)' if os.path.exists(shared) else ''}"
          f"{'; score copied to ' + os.path.basename(ss) if os.path.exists(sp) and not os.path.exists(ss) else ''}{(' -' + note) if note else ''}")
    if not APPLY: continue
    os.makedirs(bk, exist_ok=True)
    for p in (f, shared, f"{B}/review/{sid}_primary.json", ss, sp, f"{B}/review/{sid}_candidates.csv"):
        if os.path.exists(p): shutil.copy2(p, bk)
    pj = f"{B}/review/{sid}_primary.json"
    if os.path.exists(pj):
        h = f"{B}/historical/{sid}/review"; os.makedirs(h, exist_ok=True)
        dst = f"{h}/{sid}_primary.json" if not os.path.exists(f"{h}/{sid}_primary.json") else f"{h}/{sid}_primary_{stamp}.json"
        shutil.move(pj, dst)
    rw.primary(sid, READER)
    s.save(READER, mine)                       # the reviewer's own save: READER's file + (now primary) the shared calls file
    if os.path.exists(sp) and not os.path.exists(ss): shutil.copy2(sp, ss)
    with open(f"{B}/review/{sid}_review_log.csv", "a") as lf:
        lf.write(f'{rw.now()},"{READER}",fix_primary_rc3,,,"primary {cur or "-"} -> {READER}; {n} calls written to the shared file",,,,,\n')
if APPLY and todo: print(f"done. Backups: {bk}. Reopen the app: Results counts these reads now.")
