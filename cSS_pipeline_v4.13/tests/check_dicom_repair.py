"""v5.2.2 checks: cohort.py import on broken DICOM exports (dicom_repair.py), known answers. Needs pydicom and dcm2niix;
skipped (RESULT OK, with a note) when either is missing. No patient data: synthetic series written here.
usage: check_dicom_repair.py    (writes into $CSS_BASE/repair_check/)
The source folder imitates a browser download: files named ...-Series-<n>-<instance>.dcm, flagged JPEG Lossless, some
cut off part-way with a *.crswap beside them. A stub dcmdjpeg stands in for DCMTK (decodes = rewrites uncompressed;
fails on a cut-off file).
1. without --repair-missing: the SWI series with missing slices is NOT converted (flag incomplete), nothing with gaps.
2. with --repair-missing: SWI series 7 (3 of 40 missing, at most 2 in a row) -> complete 40-slice volume, same affine as
   the intact series, every readable slice bit-identical, interpolated slices = linear interpolation (exact on a
   signal linear in the slice index); series 8 (6 in a row missing) refused and removed; phase series 9 refused; the
   SWI is chosen and flagged repaired; crswap files counted; repair.json lists the decisions."""
import os, sys, shutil, subprocess, json, numpy as np, pandas as pd, nibabel as nib
HERE = os.path.dirname(os.path.abspath(__file__)); S = os.path.join(HERE, "..", "scripts")
py = sys.executable
B = f"{os.environ.get('CSS_BASE', '/tmp')}/repair_check"
def fail(m): print("FAIL:", m); sys.exit(1)
try:
    import pydicom
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import generate_uid, ExplicitVRLittleEndian
    from pydicom.encaps import encapsulate
except ImportError:
    print("skipped: pydicom not installed"); print("RESULT repair OK"); sys.exit(0)
if not shutil.which("dcm2niix"):
    print("skipped: dcm2niix not found"); print("RESULT repair OK"); sys.exit(0)
JPEG_LL = "1.2.840.10008.1.2.4.70"
shutil.rmtree(B, ignore_errors=True); os.makedirs(B)
study = generate_uid()

def write_series(folder, sn, n, desc, itype, missing=(), spacing=1.5, ts=JPEG_LL, vals=None):
    os.makedirs(folder, exist_ok=True); suid = generate_uid(); truth = []
    for i in range(1, n + 1):
        fm = FileMetaDataset(); fm.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.4"; uid = generate_uid()
        fm.MediaStorageSOPInstanceUID = uid; fm.TransferSyntaxUID = ts
        ds = Dataset(); ds.file_meta = fm; ds.SOPClassUID = fm.MediaStorageSOPClassUID; ds.SOPInstanceUID = uid
        ds.Modality = "MR"; ds.PatientName = "SYNTHETIC"; ds.PatientID = "SYN"; ds.StudyInstanceUID = study
        ds.SeriesInstanceUID = suid; ds.SeriesNumber = sn; ds.InstanceNumber = i; ds.AcquisitionNumber = 1
        ds.SeriesDescription = desc; ds.ImageType = itype; ds.Manufacturer = "SIEMENS"; ds.EchoTime = "20"
        ds.MagneticFieldStrength = "3"; ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        ds.ImagePositionPatient = [-48.0, -48.0, -30.0 + spacing * (i - 1)]; ds.SliceLocation = -30.0 + spacing * (i - 1)
        ds.PixelSpacing = [1.5, 1.5]; ds.SliceThickness = spacing; ds.SpacingBetweenSlices = spacing
        ds.Rows = ds.Columns = 64; ds.SamplesPerPixel = 1; ds.PhotometricInterpretation = "MONOCHROME2"
        ds.BitsAllocated = 16; ds.BitsStored = 12; ds.HighBit = 11; ds.PixelRepresentation = 0
        img = (vals(i) if vals else (100 + 10 * i + np.add.outer(np.arange(64), np.arange(64)))).astype(np.uint16)
        ds.PixelData = encapsulate([img.tobytes()]) if ts == JPEG_LL else img.tobytes(); truth.append(img)
        if ts == JPEG_LL: ds["PixelData"].VR = "OB"
        f = f"{folder}/04-541-321-2019-10-24-1111111-Series-{sn}-{i}.dcm"
        ds.save_as(f, enforce_file_format=True)
        if i in missing:                                      # cut off part-way, like the browser download
            b = open(f, "rb").read(); open(f, "wb").write(b[:int(len(b) * 0.6)]); open(f + ".crswap", "wb").write(b"")
    return np.stack(truth, -1)

stub = f"{B}/dcmdjpeg"
open(stub, "w").write(f"""#!{py}
import sys, pydicom
from pydicom.uid import ExplicitVRLittleEndian
from pydicom.encaps import generate_frames
try:
    ds = pydicom.dcmread(sys.argv[1]); n = ds.Rows * ds.Columns * 2
    fr = next(generate_frames(ds.PixelData, number_of_frames=1))
    if len(fr) != n: sys.exit(1)
except Exception:
    sys.exit(1)
ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian; ds.PixelData = fr; ds["PixelData"].VR = "OW"
ds.save_as(sys.argv[2], enforce_file_format=True)
""")
os.chmod(stub, 0o755)
C = f"{B}/drive"
truth7 = write_series(f"{C}/M01/SWI", 7, 40, "SWI_Images", ["ORIGINAL", "PRIMARY", "M", "SWI"], missing=(5, 17, 18))
write_series(f"{C}/M01/SWI", 8, 40, "mIP_Images(SW)", ["DERIVED", "PRIMARY", "MNIP"], missing=tuple(range(20, 26)))
write_series(f"{C}/M01/SWI", 9, 40, "Pha_Images", ["ORIGINAL", "PRIMARY", "P", "ND"], missing=(10,))
write_series(f"{C}/M01/T1", 2, 30, "T1 MPRAGE SAG", ["ORIGINAL", "PRIMARY", "M"], spacing=1.0)
full = write_series(f"{B}/intact/SWI", 7, 40, "SWI_Images", ["ORIGINAL", "PRIMARY", "M", "SWI"], ts=ExplicitVRLittleEndian)
env = dict(os.environ, CSS_BASE=B)
def imp(*extra):
    shutil.rmtree(f"{B}/raw", ignore_errors=True)
    r = subprocess.run([py, f"{S}/cohort.py", "import", C, "--dcmdjpeg", stub, *extra], capture_output=True, text=True, env=env)
    if r.returncode: print(r.stdout[-2000:], r.stderr[-2000:]); fail("cohort import failed")
    return pd.read_csv(f"{B}/review/cohort_import.csv", dtype=str).fillna("").set_index("study_id").loc["M01"], r.stdout

# 1. no repair
m, out = imp()
if m.swi_kind == "swi" or "swi_series7_incomplete_3of40" not in m["flags"]: fail(f"no repair: kind {m.swi_kind}, flags {m['flags']}")
for f in os.listdir(f"{B}/raw/M01/SWI"):
    if f.endswith(".json") and "SWI_Images" in json.load(open(f"{B}/raw/M01/SWI/{f}")).get("SeriesDescription", ""):
        fail("series 7 converted although slices are missing")
print(f"1. without --repair-missing: series 7 not converted (flags {m['flags']})")

# 2. repair
m, out = imp("--repair-missing")
fl = m["flags"].split(";")
for want in ("swi_10_crswap_files", "swi_series7_repaired_3of40_interpolated", "swi_series8_unrepairable_6of40", "swi_series9_unrepairable_1of40"):
    if want not in fl: fail(f"flag {want} missing: {fl}")
if m.swi_kind != "swi": fail(f"SWI not chosen after repair: {m.swi_kind} {m.swi}")
rep = json.load(open(f"{B}/raw/M01/SWI/repair.json"))["series"]
if rep["8"]["status"] != "removed" or "consecutive" not in rep["8"]["reason"] or "phase" not in rep["9"]["reason"]:
    fail(f"repair report {rep}")
img = nib.load(m.swi); A = np.asarray(img.dataobj)
subprocess.run(["dcm2niix", "-z", "y", "-f", "full", "-o", f"{B}/intact", f"{B}/intact/SWI"], capture_output=True)
ref = nib.load(f"{B}/intact/full.nii.gz"); R = np.asarray(ref.dataobj)
if A.shape != R.shape or not np.allclose(img.affine, ref.affine, atol=1e-4): fail(f"geometry {A.shape} vs {R.shape}\n{img.affine}\n{ref.affine}")
k_of = lambda inst: int(np.round(np.linalg.inv(ref.affine) @ np.r_[0.0, 0.0, -30.0 + 1.5 * (inst - 1), 1.0])[2])
good = [i for i in range(1, 41) if i not in (5, 17, 18)]
if not all(np.array_equal(A[..., k_of(i)], R[..., k_of(i)]) for i in good): fail("a readable slice changed")
for i in (5, 17, 18):          # the synthetic signal is linear in the slice index -> interpolation is exact
    if not np.array_equal(A[..., k_of(i)], R[..., k_of(i)]): fail(f"interpolated slice {i} differs by {np.abs(A[..., k_of(i)].astype(int) - R[..., k_of(i)]).max()}")
print(f"2. --repair-missing: series 7 -> {A.shape} volume, affine equal to the intact series, 37 readable slices identical, 3 "
      "interpolated slices exact on a linear signal; series 8 (6 consecutive missing) and phase series 9 refused and removed; "
      "10 crswap files counted")
print("RESULT repair OK")
