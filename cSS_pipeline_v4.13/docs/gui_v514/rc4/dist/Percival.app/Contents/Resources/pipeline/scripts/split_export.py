#!/usr/bin/env python3
"""Split a candidate-export zip (export_candidates.py) into N smaller zips under a size limit. Research software.
usage: split_export.py EXPORT.zip [--parts 2] [--max-mb 25] [--out DIR]
Writes EXPORT_part1of2.zip, EXPORT_part2of2.zip, ... Patients are kept whole and balanced by size (largest first,
into the lightest part). A patient too large for one part is split by candidate folder; its overview.png goes with
its first candidate. Every part keeps README.txt (with the part's patients) and gets summary.csv / excluded.csv
filtered to its own folders. Nothing is lost: the script checks that every file lands in exactly one part.
Exits with an error (and writes no zips) if the parts do not fit --max-mb: try --parts 3."""
import sys, os, io, zipfile, argparse, pandas as pd

ROOT_FILES = ("README.txt", "summary.csv", "excluded.csv")


def build_units(zin, max_bytes):
    """(name, [member files], compressed bytes): one unit per patient, split by candidate if it is too large"""
    size = {i.filename: i.compress_size for i in zin.infolist() if not i.is_dir()}
    by_pat = {}
    for n in size:
        if n in ROOT_FILES: continue
        p = n.split("/")
        if len(p) >= 2: by_pat.setdefault(p[0], []).append(n)
    units = []
    for pat, files in sorted(by_pat.items()):
        total = sum(size[f] for f in files)
        if total <= max_bytes:
            units.append((pat, files, total)); continue
        groups = {}
        for f in files:
            key = "/".join(f.split("/")[:2]) if f.count("/") >= 2 else f"{pat}/overview"
            groups.setdefault(key, []).append(f)
        ov = groups.pop(f"{pat}/overview", [])
        for i, (key, fs) in enumerate(sorted(groups.items())):
            if i == 0: fs = fs + ov                         # overview.png travels with the first candidate
            units.append((key, fs, sum(size[f] for f in fs)))
    return units, size


def pack(units, parts):
    bins = [{"files": [], "size": 0, "units": []} for _ in range(parts)]
    for name, files, sz in sorted(units, key=lambda u: -u[2]):
        b = min(bins, key=lambda b: b["size"])
        b["files"] += files; b["size"] += sz; b["units"].append(name)
    return bins


def write_part(zin, b, path, idx, parts):
    folders = {"/".join(f.split("/")[:2]) for f in b["files"] if f.count("/") >= 2}
    pats = sorted({f.split("/")[0] for f in b["files"]})
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zo:
        for f in b["files"]:
            zo.writestr(f, zin.read(f))
        for name in ("summary.csv", "excluded.csv"):
            if name in zin.namelist():
                df = pd.read_csv(io.BytesIO(zin.read(name)), dtype=str)
                zo.writestr(name, df[df["folder"].isin(folders)].to_csv(index=False))
        readme = zin.read("README.txt").decode() if "README.txt" in zin.namelist() else ""
        zo.writestr("README.txt", readme + f"\nPART {idx} of {parts}: patients {', '.join(pats)}; "
                                           f"{len(folders)} candidate/excluded folders.\n")
    return os.path.getsize(path), pats, len(folders)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("zip"); ap.add_argument("--parts", type=int, default=2)
    ap.add_argument("--max-mb", type=float, default=25.0, help="limit per part (the upload limit is 30 MB)")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    if a.parts < 2: sys.exit("--parts must be 2 or more")
    out_dir = a.out or os.path.dirname(os.path.abspath(a.zip)); os.makedirs(out_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(a.zip))[0]
    max_bytes = a.max_mb * 1e6
    with zipfile.ZipFile(a.zip) as zin:
        units, size = build_units(zin, max_bytes)
        bins = pack(units, a.parts)
        expected = sorted(f for f in size if f not in ROOT_FILES)
        placed = sorted(f for b in bins for f in b["files"])
        if placed != expected: sys.exit("internal check failed: an image would be lost or duplicated - nothing written")
        too_big = [i for i, b in enumerate(bins) if b["size"] > max_bytes]
        if too_big:
            sys.exit(f"parts {[i + 1 for i in too_big]} still exceed {a.max_mb:g} MB (compressed estimate) - use --parts 3 "
                     f"(or a larger --parts) and run again; nothing written")
        report = []
        for i, b in enumerate(bins, 1):
            path = os.path.join(out_dir, f"{base}_part{i}of{a.parts}.zip")
            real, pats, nfold = write_part(zin, b, path, i, a.parts)
            status = "OK" if real <= 30e6 else "TOO BIG for upload - use --parts 3"
            line = f"part {i} of {a.parts}: {path}  {real / 1e6:.1f} MB  patients {', '.join(pats)}  ({nfold} folders)  {status}"
            print(line); report.append(line)
        with open(os.path.join(out_dir, f"{base}_split_report.txt"), "w") as f:
            f.write("\n".join(report) + "\n")
        print(f"all {len(expected)} files placed exactly once; report: {os.path.join(out_dir, base + '_split_report.txt')}")
