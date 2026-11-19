"""Importing a study from another project (e.g. production) into the experimental project (rc2: verified, isolated COPY).
rc1 linked the FreeSurfer folder with a symlink; the user required an isolated copy in rc2, so the expectations below changed
from "linked" to "copied, verified, independent". Checks: source never changed (content + modification time of every file),
FreeSurfer copied and independent, every copy verified by sha256, reader files kept out of the pipeline's view, a failed /
interrupted import leaves nothing behind and is reported, a source that changes during the import is refused."""
import os, sys, glob, json, hashlib, tempfile, shutil
import numpy as np, nibabel as nib
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..")); sys.path.insert(0, os.path.join(ROOT, "app"))
import processing_manager as pm
F = []
def ok(c, m): print(("PASS " if c else "FAIL ") + m); c or F.append(m)
def nii(p, v=1.0):
    os.makedirs(os.path.dirname(p), exist_ok=True); nib.save(nib.Nifti1Image(np.full((6, 6, 4), v, np.float32), np.eye(4)), p)
def w(p, t):
    os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "w").write(t)
SRC, DST, S = tempfile.mkdtemp(), tempfile.mkdtemp(), "M02"
nii(f"{SRC}/data/{S}_swi.nii"); nii(f"{SRC}/data/{S}_t1.nii.gz", 2.0); nii(f"{SRC}/work/{S}_seg_swispace.nii.gz"); w(f"{SRC}/work/{S}_swi2t1.lta", "1 4 4\n")
nii(f"{SRC}/work/{S}_R1_seg_swispace.nii.gz")                   # robustness copy: must not be brought in
w(f"{SRC}/review/{S}_candidates.csv", "cand_id\n1\n"); w(f"{SRC}/review/{S}_score_ai.json", "{}")
for r in ("calls.csv", "calls_Dr.csv", "final.json", "score.json", "review_log.csv", "missed.csv"): w(f"{SRC}/review/{S}_{r}", "reader")
for n in ("aparc.a2009s+aseg", "orig", "brain"): os.makedirs(f"{SRC}/subjects/{S}/mri", exist_ok=True); nib.save(nib.MGHImage(np.ones((4, 4, 4), np.float32), np.eye(4)), f"{SRC}/subjects/{S}/mri/{n}.mgz")
w(f"{SRC}/subjects/{S}/surf/lh.pial", "surface"); w(f"{SRC}/subjects/{S}/scripts/build-stamp.txt", "freesurfer 8.2.0")
os.symlink("lh.pial", f"{SRC}/subjects/{S}/surf/lh.pial.T1")     # FreeSurfer uses internal relative symlinks: kept as links
w(f"{SRC}/fsaverage_like/label.txt", "outside"); os.symlink(f"{SRC}/fsaverage_like/label.txt", f"{SRC}/subjects/{S}/surf/ext_abs")   # absolute link leading outside
h = lambda B: {p: (hashlib.sha256(open(p, "rb").read()).hexdigest(), os.stat(p).st_mtime) for p in glob.glob(f"{B}/**/*", recursive=True) if os.path.isfile(p) and not os.path.islink(p)}
before = h(SRC)
r = pm.import_study(SRC, DST, S)
fsd = f"{DST}/subjects/{S}"
ok(os.path.isdir(fsd) and not os.path.islink(fsd), "FreeSurfer folder COPIED into the experimental project (not a symlink)")
ok(r["freesurfer"]["method"] in ("copy", "apfs_clone") and r["freesurfer"]["files"] == 7, f"FreeSurfer copy verified file by file ({r['freesurfer']['method']}, {r['freesurfer']['files']} files)")
ok(os.path.islink(f"{fsd}/surf/lh.pial.T1") and os.readlink(f"{fsd}/surf/lh.pial.T1") == "lh.pial", "FreeSurfer-internal relative symlinks kept relative (point inside the copy)")
ok(not os.path.islink(f"{fsd}/surf/ext_abs") and open(f"{fsd}/surf/ext_abs").read() == "outside" and r["freesurfer"]["external_links_materialized"] == 1, "a symlink leading outside the subject folder is replaced by a real copy (no path back into the source)")
open(f"{fsd}/mri/orig.mgz", "ab").write(b"x"); open(f"{fsd}/surf/lh.pial", "w").write("changed")
ok(h(SRC) == before, "writing into the experimental FreeSurfer copy does not change the original")
ok(os.path.exists(f"{DST}/data/{S}_swi.nii") and os.path.exists(f"{DST}/work/{S}_seg_swispace.nii.gz") and os.path.exists(f"{DST}/review/{S}_candidates.csv"), "images, labels, earlier detector outputs copied")
ok(all(x["sha256"] for x in r["copied"]) and r["verified"] and r["source_unchanged"], "every copied file verified by sha256; source confirmed unchanged after the import")
ok(not glob.glob(f"{DST}/review/{S}_calls*") and not glob.glob(f"{DST}/review/{S}_final*") and not os.path.exists(f"{DST}/review/{S}_score.json"), "no reader file in the experimental review folder")
ok(len(glob.glob(f"{DST}/historical/{S}/review/*")) == 6 and os.path.exists(f"{DST}/review/{S}_score_ai.json"), "reader files kept in historical/ for comparison (historical outputs preserved)")
hist = {x["path"]: x["sha256"] for x in r["historical"]}
ok(all(hashlib.sha256(open(f"{DST}/{p}", "rb").read()).hexdigest() == v for p, v in hist.items()), "historical copies identical to the source files")
ok(not glob.glob(f"{DST}/work/{S}_R1*"), "temporary robustness copies not brought in")
ok(json.load(open(f"{DST}/runs/{S}/import.json"))["source"] == os.path.realpath(SRC) and not glob.glob(f"{DST}/.import_staging/*"), "import record written last; staging removed")
for args, m in (((SRC, DST, S), "importing twice refused"), ((SRC, SRC, S), "source = destination refused")):
    try: pm.import_study(*args); ok(False, m)
    except ValueError: ok(True, m)
# interrupted import: nothing left behind, reported, source untouched
S2 = "M03"; nii(f"{SRC}/data/{S2}_swi.nii"); nii(f"{SRC}/work/{S2}_seg_swispace.nii.gz"); w(f"{SRC}/review/{S2}_candidates.csv", "c\n")
shutil.copytree(f"{SRC}/subjects/{S}", f"{SRC}/subjects/{S2}", symlinks=True); before = h(SRC)
try: pm.import_study(SRC, DST, S2, _fail_after=2); ok(False, "interrupted import reported")
except pm.ImportError_ as e: ok("rolled back" in str(e), "interrupted import reported as failed and rolled back")
ok(not glob.glob(f"{DST}/data/{S2}_*") and not os.path.exists(f"{DST}/subjects/{S2}") and not glob.glob(f"{DST}/.import_staging/*") and not os.path.exists(f"{DST}/runs/{S2}"), "nothing of the interrupted import left in the experimental project")
# crash during placement (staging left behind) -> rolled back at the next start
stage = f"{DST}/.import_staging/{S2}_crash"; os.makedirs(stage); os.makedirs(f"{DST}/data", exist_ok=True); w(f"{DST}/data/{S2}_swi.nii", "half")
json.dump(dict(code=S2, state="placing", targets=[f"data/{S2}_swi.nii"]), open(f"{stage}/STAGING.json", "w"))
ok(pm.recover_imports(DST) == [S2] and not os.path.exists(f"{DST}/data/{S2}_swi.nii") and not os.path.exists(stage), "crash during placement: rolled back at the next start and reported")
# source changing during the import -> refused
orig = pm._tree_hashes; calls = [0]
def flaky(root):
    calls[0] += 1; out = orig(root)
    if calls[0] == 3: out = dict(out, **{"mri/orig.mgz": "changed"})
    return out
pm._tree_hashes = flaky
try: pm.import_study(SRC, DST, S2); ok(False, "source change during import refused")
except pm.ImportError_ as e: ok("changed during the import" in str(e), "a source that changes during the import is refused (nothing imported)")
pm._tree_hashes = orig
ok(not glob.glob(f"{DST}/data/{S2}_*"), "after the refused import nothing was placed")
r2 = pm.import_study(SRC, DST, S2); ok(r2["verified"], "the same study imports cleanly afterwards")
ok(h(SRC) == before, "source project unchanged throughout (every file: content and modification time)")
st = pm.Study(DST, S); a = st.audit()
ok(a["stages"]["anatomy"]["kind"] == "freesurfer", "imported FreeSurfer recognised by the Processing Manager")
print("ALL PASS" if not F else f"{len(F)} FAILED"); sys.exit(1 if F else 0)
