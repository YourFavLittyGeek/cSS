"""Finds MRI series in a patient folder (DICOM folders or NIfTI files, any depth <= 4) and proposes a sequence type for each.
Read-only. Used by css_app.py; can also be run alone:  python series_detect.py FOLDER"""
import os, re, sys, json, hashlib
try:
    import pydicom
except ImportError:
    pydicom = None
import nibabel as nib

TYPES = ["SWI", "T1", "FLAIR", "PHASE", "ignore"]
PAT = [("ignore", r"mip|mnip|min[\s_-]*ip|minip"),
       ("PHASE", r"pha\b|phase|_ph\b|filt[\s_-]*pha|\bpha_|swi.*pha"),
       ("SWI", r"swi|swan|susc|venobold|swip|t2\*|t2[\s_-]*star|\bgre\b|_gre|gre_|hemo|merge|medic|flash|fl2d|fl3d|ffe|t2[\s_-]*gre"),
       ("FLAIR", r"flair|dark[\s_-]*fluid|ir[\s_-]*fse"),
       ("T1", r"t1|mprage|mp[\s_-]*rage|bravo|spgr|tfe|fspgr|mp2rage|uni\b|vibe"),
       ("ignore", r"localizer|locali[sz]er|scout|survey|aahead|calibration|dwi|adc|trace|tof|mra|pd\b|t2")]

def classify(text, image_type=""):
    t = (text or "").lower()
    it = (image_type or "").upper()
    if "MIN IP" in it or "MNIP" in it or "MIP" in it.split("\\"): return "ignore", "minimum-intensity projection (never used)"
    if "\\P\\" in f"\\{it}\\" or "PHASE" in it: return "PHASE", "ImageType phase"
    for typ, pat in PAT:
        if re.search(pat, t): return typ, f"name / description matches {typ}"
    return "ignore", "not recognised (choose a type if needed)"

def is_dicom(p):
    try:
        with open(p, "rb") as f: return f.read(132)[128:132] == b"DICM"
    except OSError: return False

def _dicom_info(files):
    info = dict(n_files=len(files))
    if pydicom is None: return info
    for f in files[:3]:
        try:
            d = pydicom.dcmread(f, stop_before_pixels=True, force=True)
            ps = getattr(d, "PixelSpacing", [None, None]); st = getattr(d, "SliceThickness", None)
            info.update(description=str(getattr(d, "SeriesDescription", "") or getattr(d, "ProtocolName", "")),
                        image_type="\\".join(map(str, getattr(d, "ImageType", []) or [])),
                        series_uid=str(getattr(d, "SeriesInstanceUID", "")), voxel=[float(ps[0]) if ps[0] else None, float(ps[1]) if ps[1] else None,
                                                                              float(st) if st else None],
                        te=float(getattr(d, "EchoTime", 0) or 0), field=float(getattr(d, "MagneticFieldStrength", 0) or 0))
            return info
        except Exception: continue
    return info

def scan(folder, max_depth=4):
    """-> list of series dicts: path, format, files, description, proposed type, reason, voxel, fingerprint"""
    out = []
    folder = os.path.abspath(folder)
    for root, dirs, files in os.walk(folder):
        depth = root[len(folder):].count(os.sep)
        dirs[:] = sorted(d for d in dirs if not d.startswith(".")) if depth < max_depth else []
        files = sorted(f for f in files if not f.startswith(".") and not f.endswith(".crswap"))
        niis = [f for f in files if f.endswith((".nii", ".nii.gz"))]
        for f in niis:
            p = os.path.join(root, f); name = f.replace(".nii.gz", "").replace(".nii", "")
            try:
                img = nib.load(p); vox = [round(float(v), 2) for v in img.header.get_zooms()[:3]]; shape = list(img.shape[:3])
            except Exception as e:
                out.append(dict(path=p, format="NIfTI", ok=False, error=str(e), name=f)); continue
            desc = ""
            js = os.path.join(root, name + ".json")
            if os.path.exists(js):
                try: j = json.load(open(js)); desc = j.get("SeriesDescription", "") + " " + "\\".join(j.get("ImageType", []))
                except Exception: pass
            typ, why = classify(f"{os.path.basename(root) if root != folder else ''} {f} {desc}", desc)
            out.append(dict(path=p, format="NIfTI", ok=True, name=(os.path.basename(root) + "/" + f) if root != folder else f, relpath=os.path.relpath(p, folder), files=1, description=desc.strip(), type=typ, reason=why,
                            voxel=vox, shape=shape, fingerprint=hashlib.sha1(open(p, "rb").read(1 << 16)).hexdigest()[:16]))
        dcm = [os.path.join(root, f) for f in files if f.lower().endswith(".dcm") or (not os.path.splitext(f)[1] and is_dicom(os.path.join(root, f)))]
        if dcm:
            inf = _dicom_info(dcm)
            typ, why = classify(f"{os.path.basename(root)} {inf.get('description', '')}", inf.get("image_type", ""))
            out.append(dict(path=root, format="DICOM", ok=True, name=os.path.basename(root), relpath=os.path.relpath(root, folder), files=len(dcm),
                            description=inf.get("description", ""), image_type=inf.get("image_type", ""), type=typ, reason=why,
                            voxel=inf.get("voxel"), shape=[None, None, len(dcm)], te=inf.get("te"), field=inf.get("field"),
                            fingerprint=(inf.get("series_uid") or hashlib.sha1(open(dcm[0], "rb").read(1 << 16)).hexdigest())[:40]))
    return out

def _res(s):
    v = [x for x in (s.get("voxel") or []) if x]
    return max(v) if v else 99.0

def choose(series):
    """one series per type: highest resolution (smallest largest voxel side); for SWI the magnitude/processed, never phase/minIP"""
    pick, alt = {}, {}
    for t in ("SWI", "T1", "FLAIR", "PHASE"):
        c = sorted([s for s in series if s.get("ok") and s.get("type") == t], key=lambda s: (_res(s), -s.get("files", 0)))
        if c: pick[t] = c[0]["path"]; alt[t] = [s["path"] for s in c[1:]]
    return pick, alt

if __name__ == "__main__":
    s = scan(sys.argv[1]); p, a = choose(s)
    for x in s: print(f"{x.get('type', '?'):7} {x.get('format'):6} {x.get('name')}  {x.get('description', '')}  {x.get('voxel')}")
    print("chosen:", json.dumps(p, indent=1))
