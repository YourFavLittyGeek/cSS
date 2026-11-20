"""Fill missing slices of a DICOM series by interpolation (v5.2.2, opt-in: cohort.py import --repair-missing).
Research software. Used when an export left some files unreadable (e.g. browser downloads that stopped part-way,
leaving *.crswap files) and the study cannot be exported again yet.

Per series (SeriesNumber) of a staged, already decompressed folder:
  - the unreadable files' instance numbers come from their header (read without pixel data) or, failing that, from the
    file name (...Series-<series>-<instance>.dcm);
  - the slice position (ImagePositionPatient) must be a straight-line function of the instance number on the readable
    files (largest deviation <= 0.1 mm), else the series is refused (irregular / multi-volume);
  - refused as well: more than max_frac of the slices missing, more than max_run consecutive missing slices, a phase
    series (interpolating phase across wraps is wrong), fewer than 3 readable slices;
  - each missing slice = linear interpolation (by instance distance) of the nearest readable slice below and above
    (at the series ends: a copy of the nearest), written as a new file with its own position, instance number and UID,
    ImageComments 'cSS pipeline: interpolated slice'.
A refused series is REMOVED from the staged folder (never converted with gaps). Every decision is in the report.
Interpolated slices cannot show a lesion that is only in that slice: results from repaired series are preliminary.
Needs pydicom (conda install -n css -c conda-forge pydicom)."""
import os, re, glob, numpy as np

FN_RE = re.compile(r"Series-(\d+)-(\d+)\.dcm$", re.I)


def _hdr(path):
    import pydicom
    try:
        ds = pydicom.dcmread(path, stop_before_pixels=True, force=True)
        it = [str(t).upper() for t in (ds.get("ImageType") or [])]
        ipp = ds.get("ImagePositionPatient")
        return dict(series=int(ds.SeriesNumber) if "SeriesNumber" in ds else None,
                    instance=int(ds.InstanceNumber) if "InstanceNumber" in ds else None,
                    ipp=np.array([float(v) for v in ipp]) if ipp is not None else None,
                    loc=float(ds.SliceLocation) if "SliceLocation" in ds else None,
                    phase="P" in it or "PHASE" in it)
    except Exception:
        return dict(series=None, instance=None, ipp=None, loc=None, phase=False)


def _failed_ids(path):
    h = _hdr(path)
    m = FN_RE.search(os.path.basename(path))
    if h["series"] is None and m: h["series"] = int(m.group(1))
    if h["instance"] is None and m: h["instance"] = int(m.group(2))
    return h


def _runs(missing, present):
    """longest run of consecutive missing instances (inside the series' instance range)"""
    allv = sorted(set(missing) | set(present)); best = cur = 0; miss = set(missing)
    for v in range(allv[0], allv[-1] + 1):
        cur = cur + 1 if v in miss else 0; best = max(best, cur)
    return best


def repair_folder(staged_dir, failed_paths, enabled, max_frac=0.2, max_run=2, tol_mm=0.1):
    """staged_dir: readable (decompressed) files of one modality folder; failed_paths: the unreadable source files.
    -> (flags, report dict). Removes every series that has missing files and is not repaired."""
    import pydicom
    from pydicom.uid import generate_uid
    good = {}
    for f in sorted(glob.glob(os.path.join(staged_dir, "*"))):
        h = _hdr(f)
        if h["series"] is not None: good.setdefault(h["series"], []).append((f, h))
    bad = {}
    unknown = []
    for f in failed_paths:
        h = _failed_ids(f)
        if h["series"] is None or h["instance"] is None: unknown.append(os.path.basename(f)); continue
        bad.setdefault(h["series"], []).append(h["instance"])
    flags, rep = [], dict(unidentified_failed_files=unknown, series={})
    if unknown: flags.append(f"{len(unknown)}_unreadable_files_of_unknown_series")
    for sn, miss in sorted(bad.items()):
        g = good.get(sn, []); miss = sorted(set(miss)); n = len(g) + len(miss)
        r = dict(n_slices=n, n_missing=len(miss), missing_instances=miss)
        inst = np.array([h["instance"] for _, h in g]) if g else np.array([])
        reason = ""
        if not enabled: reason = "incomplete (repair not requested)"
        elif len(g) < 3: reason = "fewer than 3 readable slices"
        elif any(h["phase"] for _, h in g): reason = "phase series (not interpolated)"
        elif len(miss) / n > max_frac: reason = f"{len(miss)}/{n} slices missing (> {max_frac:.0%})"
        elif _runs(miss, inst.tolist()) > max_run: reason = f"{_runs(miss, inst.tolist())} consecutive slices missing (> {max_run})"
        elif len(set(inst.tolist())) != len(inst) or any(h["ipp"] is None for _, h in g):
            reason = "duplicate instance numbers / no slice positions (multi-volume?)"
        if not reason:
            P = np.array([h["ipp"] for _, h in g]); A = np.c_[np.ones(len(inst)), inst]
            coef, *_ = np.linalg.lstsq(A, P, rcond=None); dev = float(np.abs(A @ coef - P).max())
            r["position_fit_max_dev_mm"] = round(dev, 4)
            if dev > tol_mm: reason = f"slice positions not linear in instance number (max deviation {dev:.2f} mm)"
        if reason:
            for f, _ in g: os.remove(f)
            r["status"] = "removed"; r["reason"] = reason
            flags.append(f"series{sn}_{'incomplete' if not enabled else 'unrepairable'}_{len(miss)}of{n}")
            rep["series"][str(sn)] = r; continue
        locs = [(h["instance"], h["loc"]) for _, h in g if h["loc"] is not None]
        lc = np.polyfit([a for a, _ in locs], [b for _, b in locs], 1) if len(locs) >= 2 else None
        by_inst = {h["instance"]: f for f, h in g}; keys = np.array(sorted(by_inst))
        cache = {}
        def arr(i):
            if i not in cache: cache[i] = pydicom.dcmread(by_inst[i]).pixel_array.astype(np.float64)
            return cache[i]
        for m in miss:
            lo, hi = keys[keys < m], keys[keys > m]
            if len(lo) and len(hi):
                a, b = int(lo[-1]), int(hi[0]); w = (m - a) / (b - a); px = (1 - w) * arr(a) + w * arr(b); src = a if w <= 0.5 else b
            else:
                src = int(lo[-1]) if len(lo) else int(hi[0]); px = arr(src)
            ds = pydicom.dcmread(by_inst[src])
            dt = ds.pixel_array.dtype
            info = np.iinfo(dt) if np.issubdtype(dt, np.integer) else None
            px = np.clip(np.rint(px), info.min, info.max) if info else px
            ds.PixelData = px.astype(dt).tobytes()
            ds.InstanceNumber = int(m)
            ds.ImagePositionPatient = [f"{v:.6f}" for v in (coef[0] + coef[1] * m)]
            if lc is not None and "SliceLocation" in ds: ds.SliceLocation = f"{np.polyval(lc, m):.6f}"
            uid = generate_uid(); ds.SOPInstanceUID = uid
            if hasattr(ds, "file_meta"): ds.file_meta.MediaStorageSOPInstanceUID = uid
            ds.ImageComments = "cSS pipeline: interpolated slice"
            ds.save_as(os.path.join(staged_dir, f"interp_s{sn}_i{m:05d}.dcm"))
        r["status"] = "repaired"; r["interpolated"] = miss
        flags.append(f"series{sn}_repaired_{len(miss)}of{n}_interpolated")
        rep["series"][str(sn)] = r
    return flags, rep
