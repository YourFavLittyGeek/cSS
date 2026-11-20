#!/usr/bin/env python3
"""Import and run a whole cohort of subject folders (v5.2.1). Research software.
usage: cohort.py import COHORT_DIR [--ids M01,M02] [--dcm2niix dcm2niix]
       cohort.py run [--ids M01,M02] [--no-recon] [--redo]
COHORT_DIR holds one folder per study code (M01, M02 ... - codes, never names), each with sub-folders T1, SWI and
FLAIR (case-insensitive; FLAIR may be missing). A sub-folder may hold DICOM files (converted with dcm2niix) or NIfTI
files (+ dcm2niix JSON sidecars, copied); either way they land in $CSS_BASE/raw/ID/<T1|SWI|FLAIR> and the runs read
only that copy (an existing raw/ID/MOD is kept: delete it to re-import).
'import' picks the series to use and writes review/cohort_import.csv - CHECK IT before 'run':
  SWI    the processed SWI (description / ImageType SWI), else the magnitude; NEVER the minIP (mIP / MNIP / MIP),
         never the phase. The phase series of the same folder (ImageType P / PHASE, description Pha) -> --phase,
         only if it has the SWI's grid.
  T1     the most isotropic series (smallest largest voxel side; ties: smallest voxel) - an original 3-D sagittal
  FLAIR  acquisition beats a thick axial MPR reformat; orientation does not matter (registered to the SWI).
  DICOM  copied into raw/ID/MOD/_dicom first; JPEG-compressed files are decompressed with dcmdjpeg (DCMTK: conda install
         -n css -c conda-forge dcmtk). A file that does not decode is a broken / partly written file: the series is
         never converted with gaps: with --repair-missing its missing slices are interpolated from the neighbours
         (dicom_repair.py; refused above --max-missing-frac 0.2 or --max-missing-run 2 consecutive slices, for phase
         series and irregular positions), otherwise the series is removed. Flags <mod>_series<N>_repaired_KofM_
         interpolated / _unrepairable_ / _incomplete_; details in raw/ID/MOD/repair.json, unreadable_files.txt. A
         volume with missing slices hides lesions without any error; interpolated slices cannot show a lesion that
         is only in that slice. Browser downloads leave *.crswap files beside broken files (<mod>_N_crswap_files).
'run' skips a study without a usable SWI or T1 (--allow-no-t1: SWI-only route).
  flags  dcm2niix_<mod>_<reason> (messages in raw/ID/MOD/dcm2niix.log), swi_slice_gt_2mm, t1_not_3d (largest side > 1.5 mm), several_swi_candidates, no_t1, no_flair, no_phase ...
'run' calls run_css.sh for every study in the table, ONE AT A TIME (NOVIEW=1; CSS_THREADS, CSS_QC_STRICT,
CSS_MIXED_REVIEW, CSS_USE_MIMIC are passed through), logs to logs/ID_run.log, skips studies already detected unless
--redo, and appends the outcome (ok / qc_insufficient / failed + exit code) to review/cohort_run.csv.
Scoring is NOT automatic: read each case with review_css.py ID (blinded to the expert grades), then
compare_grades.py."""
import sys, os, glob, json, shutil, argparse, subprocess, datetime, numpy as np, pandas as pd, nibabel as nib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from css_common import base as _base

MODS = ("T1", "SWI", "FLAIR")
DCM2NIIX_EXIT = {1: "error", 2: "no_dicom_found", 4: "corrupt_file", 5: "input_folder_invalid", 6: "output_folder_invalid",
                 7: "output_read_only", 8: "some_files_failed", 9: "rename_error", 10: "incomplete_volumes"}


def transfer_syntax(path):
    """(0002,0010) Transfer Syntax UID from the DICOM file meta header ('' if not a Part-10 file)"""
    try:
        b = open(path, "rb").read(16384)
    except OSError:
        return ""
    if b[128:132] != b"DICM": return ""
    i = 132
    while i + 8 <= len(b):
        grp, el = int.from_bytes(b[i:i + 2], "little"), int.from_bytes(b[i + 2:i + 4], "little")
        if grp != 2: break
        vr = b[i + 4:i + 6]
        if vr in (b"OB", b"OW", b"OF", b"SQ", b"UT", b"UN"):
            n = int.from_bytes(b[i + 8:i + 12], "little"); v0 = i + 12
        else:
            n = int.from_bytes(b[i + 6:i + 8], "little"); v0 = i + 8
        if el == 0x0010: return b[v0:v0 + n].decode("ascii", "ignore").strip("\x00 ")
        i = v0 + n
    return ""


def stage_dicom(src, dst, dcmdjpeg):
    """copy a DICOM folder to dst, decompressing JPEG files with dcmdjpeg (DCMTK). A JPEG file that does not decode is
    a broken / partly written file (browser downloads leave *.crswap beside them). -> (dict failed / unchecked, n_failed,
    n_crswap). Skips macOS '._' files and *.crswap."""
    shutil.rmtree(dst, ignore_errors=True); os.makedirs(dst)
    tool = shutil.which(dcmdjpeg) if dcmdjpeg else None
    failed, unchecked, n_swap = [], 0, 0
    for root, _, files in os.walk(src):
        for fn in sorted(files):
            if fn.endswith(".crswap"): n_swap += 1; continue
            if fn.startswith("._") or fn.startswith("."): continue
            f = os.path.join(root, fn); t = os.path.join(dst, f"{len(os.listdir(dst)):05d}_{fn}")
            ts = transfer_syntax(f)
            if ts.startswith("1.2.840.10008.1.2.4."):                       # JPEG family
                if tool is None:
                    shutil.copy2(f, t); unchecked += 1; continue
                r = subprocess.run([tool, f, t], capture_output=True)
                if r.returncode:
                    failed.append(os.path.relpath(f, src))
                    if os.path.exists(t): os.remove(t)
            else:
                shutil.copy2(f, t)
    return dict(failed=failed, unchecked=unchecked), len(failed), n_swap


def find_sub(folder, mod):
    for d in sorted(os.listdir(folder)):
        if os.path.isdir(os.path.join(folder, d)) and d.lower() == mod.lower(): return os.path.join(folder, d)
    return None


def niftis(d):
    return sorted(glob.glob(f"{d}/**/*.nii.gz", recursive=True) + glob.glob(f"{d}/**/*.nii", recursive=True))


def series_info(p):
    js = p[:-7] + ".json" if p.endswith(".nii.gz") else p[:-4] + ".json"
    j = json.load(open(js)) if os.path.exists(js) else {}
    im = nib.load(p); z = [float(v) for v in im.header.get_zooms()[:3]]
    it = j.get("ImageType", []); it = it if isinstance(it, list) else [str(it)]
    desc = str(j.get("SeriesDescription", "")) + " " + os.path.basename(p)
    return dict(path=p, shape=tuple(int(s) for s in im.shape[:3]), vox=z, te=j.get("EchoTime"), image_type=[str(t).upper() for t in it],
                desc=desc, affine=im.affine, n_dims=len(im.shape))


def kind_swi(s):
    d = s["desc"].lower(); it = s["image_type"]
    if any(k in d for k in ("mip", "mnip", "minip")) or "MNIP" in it or "MIP" in it: return "minip"
    if "P" in it or "PHASE" in it or "pha" in d: return "phase"
    if "swi" in d or "SWI" in it: return "swi"
    if "mag" in d or "M" in it: return "magnitude"
    return "unknown"


def pick_structural(series):
    ok = [s for s in series if s["n_dims"] == 3]
    if not ok: return None
    return sorted(ok, key=lambda s: (round(max(s["vox"]), 2), float(np.prod(s["vox"]))))[0]


def cmd_import(a, B):
    rows = []
    subjects = sorted(d for d in os.listdir(a.cohort_dir) if os.path.isdir(os.path.join(a.cohort_dir, d)))
    if a.ids: subjects = [s for s in subjects if s in a.ids.split(",")]
    for sid in subjects:
        src = os.path.join(a.cohort_dir, sid); row = dict(study_id=sid); flags = []
        found = {}
        for mod in MODS:
            d = find_sub(src, mod)
            if d is None: found[mod] = []; continue
            out = f"{B}/raw/{sid}/{mod}"; os.makedirs(out, exist_ok=True)
            # everything is copied / converted into $CSS_BASE/raw/ID/MOD: the runs never read the source drive
            # (external drives disconnect; their names often contain spaces)
            if not niftis(out):
                src_nii = niftis(d)
                for f in src_nii:                                  # NIfTI (+ JSON sidecar) as they are
                    shutil.copy2(f, out)
                    js = f[:-7] + ".json" if f.endswith(".nii.gz") else f[:-4] + ".json"
                    if os.path.exists(js): shutil.copy2(js, out)
                if not src_nii:                                    # DICOM -> NIfTI; its messages kept in the log
                    staged, bad, n_swap = stage_dicom(d, f"{out}/_dicom", a.dcmdjpeg)
                    if n_swap: flags.append(f"{mod.lower()}_{n_swap}_crswap_files")
                    if bad:                       # a series with missing slices is repaired (opt-in) or removed
                        open(f"{out}/unreadable_files.txt", "w").write("\n".join(staged["failed"]) + "\n")
                        try:
                            import dicom_repair
                            fl, rep = dicom_repair.repair_folder(f"{out}/_dicom", [os.path.join(d, f) for f in staged["failed"]],
                                                                 a.repair_missing, a.max_missing_frac, a.max_missing_run)
                        except ImportError:
                            fl, rep = ["pydicom_missing_cannot_repair_or_isolate"], {}
                            shutil.rmtree(f"{out}/_dicom", ignore_errors=True); os.makedirs(f"{out}/_dicom")
                        json.dump(rep, open(f"{out}/repair.json", "w"), indent=2, default=str)
                        flags += [f"{mod.lower()}_{x}" for x in fl]
                    if staged["unchecked"]: flags.append(f"{mod.lower()}_jpeg_not_checked_no_dcmdjpeg")
                    r = subprocess.run([a.dcm2niix, "-z", "y", "-f", "%s_%d", "-o", out, f"{out}/_dicom"], capture_output=True, text=True)
                    open(f"{out}/dcm2niix.log", "w").write(r.stdout + r.stderr)
                    if r.returncode:
                        flags.append(f"dcm2niix_{mod.lower()}_{DCM2NIIX_EXIT.get(r.returncode, f'exit{r.returncode}')}")
            nii = niftis(out)
            found[mod] = [series_info(p) for p in nii]
        sw = found["SWI"]; kinds = [(kind_swi(s), s) for s in sw]
        main = [s for k, s in kinds if k == "swi"] or [s for k, s in kinds if k == "magnitude"] or [s for k, s in kinds if k == "unknown"]
        if len(main) > 1: flags.append("several_swi_candidates")
        swi = sorted(main, key=lambda s: float(np.prod(s["vox"])))[0] if main else None
        if swi is None: flags.append("no_swi" if not sw else "only_minip_or_phase_in_swi_folder")
        ph = [s for k, s in kinds if k == "phase" and swi is not None and s["shape"] == swi["shape"]
              and np.allclose(s["affine"], swi["affine"], atol=1e-3)]
        if any(k == "phase" for k, _ in kinds) and not ph: flags.append("phase_not_on_swi_grid")
        t1, fl = pick_structural(found["T1"]), pick_structural(found["FLAIR"])
        if t1 is None: flags.append("no_t1")
        elif max(t1["vox"]) > 1.5: flags.append("t1_not_3d")
        if fl is None: flags.append("no_flair")
        if swi is not None and swi["vox"][2] > 2.0: flags.append("swi_slice_gt_2mm")
        if not ph: flags.append("no_phase")
        fmt = lambda s: "x".join(f"{v:.2f}" for v in s["vox"]) if s else ""
        row.update(swi=swi["path"] if swi else "", swi_vox_mm=fmt(swi), swi_te=swi["te"] if swi else "",
                   swi_kind=kind_swi(swi) if swi else "", phase=ph[0]["path"] if ph else "",
                   t1=t1["path"] if t1 else "", t1_vox_mm=fmt(t1), flair=fl["path"] if fl else "", flair_vox_mm=fmt(fl),
                   n_swi_series=len(sw), n_t1_series=len(found["T1"]), n_flair_series=len(found["FLAIR"]),
                   flags=";".join(flags))
        rows.append(row)
        print(f"{sid}: SWI {row['swi_kind'] or '-'} {row['swi_vox_mm']}  T1 {row['t1_vox_mm'] or '-'}  FLAIR {row['flair_vox_mm'] or '-'}"
              f"  phase {'yes' if ph else 'no'}" + (f"  [{row['flags']}]" if flags else ""))
    os.makedirs(f"{B}/review", exist_ok=True)
    pd.DataFrame(rows).to_csv(f"{B}/review/cohort_import.csv", index=False)
    print(f"-> {B}/review/cohort_import.csv ({len(rows)} studies). Check the chosen series, then: cohort.py run")


def cmd_run(a, B):
    t = pd.read_csv(f"{B}/review/cohort_import.csv", dtype=str).fillna("")
    if a.ids: t = t[t.study_id.isin(a.ids.split(","))]
    os.makedirs(f"{B}/logs", exist_ok=True); runlog = f"{B}/review/cohort_run.csv"
    env = dict(os.environ, NOVIEW="1"); env.setdefault("CSS_THREADS", "4")
    for _, r in t.iterrows():
        s = r.study_id
        if not r.swi: print(f"{s}: no SWI chosen - skipped ({r['flags']})"); continue
        if not r.t1 and not a.allow_no_t1:
            print(f"{s}: no usable T1 - skipped (--allow-no-t1 runs the SWI-only route; {r['flags']})"); continue
        if os.path.exists(f"{B}/review/{s}_manifest.json") and os.path.exists(f"{B}/review/{s}_candidates.csv") and not a.redo:
            print(f"{s}: already detected - skipped (--redo to run again)"); continue
        cmd = ["zsh", f"{B}/scripts/run_css.sh", s, r.swi]
        if r.t1: cmd += ["--t1", r.t1]
        if r.flair: cmd += ["--flair", r.flair]
        if r.t1 and not a.no_recon: cmd += ["--recon"]
        if r.phase: cmd += ["--phase", r.phase]
        t0 = datetime.datetime.now(); print(f"{s}: running ({t0:%H:%M}) ... log: logs/{s}_run.log", flush=True)
        with open(f"{B}/logs/{s}_run.log", "w") as lf:
            rc = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, env=env).returncode
        status = "ok" if rc == 0 else ("qc_insufficient" if rc == 3 else "failed")
        mins = round((datetime.datetime.now() - t0).total_seconds() / 60, 1)
        print(f"{s}: {status} (exit {rc}, {mins} min)")
        old = pd.read_csv(runlog) if os.path.exists(runlog) else pd.DataFrame()
        pd.concat([old, pd.DataFrame([dict(study_id=s, status=status, exit_code=rc, minutes=mins, finished=f"{datetime.datetime.now():%Y-%m-%d %H:%M}",
                                           command=" ".join(cmd[2:]))])], ignore_index=True).to_csv(runlog, index=False)
    print(f"-> {runlog}. Next: read every case with review_css.py ID (blinded to the expert grades), then compare_grades.py")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("import"); i.add_argument("cohort_dir"); i.add_argument("--ids", default=""); i.add_argument("--dcm2niix", default="dcm2niix")
    i.add_argument("--dcmdjpeg", default="dcmdjpeg")
    i.add_argument("--repair-missing", action="store_true", help="fill missing slices by interpolation (dicom_repair.py)")
    i.add_argument("--max-missing-frac", type=float, default=0.2); i.add_argument("--max-missing-run", type=int, default=2)
    r = sub.add_parser("run"); r.add_argument("--ids", default=""); r.add_argument("--no-recon", action="store_true"); r.add_argument("--redo", action="store_true")
    r.add_argument("--allow-no-t1", action="store_true")
    a = ap.parse_args(); B = _base()
    cmd_import(a, B) if a.cmd == "import" else cmd_run(a, B)
