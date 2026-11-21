"""check_duplicate_detection.py - regression test for the false "duplicate" on first-time import (v5.15), through the real app's /api/scan
and /api/queue on a SYNTHETIC project. Cases: genuinely different study with the same protocol header (was a false duplicate: same 64 KB
fingerprint) -> no warning; exact repeat, renamed folder, moved folder, recompressed .nii.gz of the same image -> exact duplicate, left
out by default, with the reason; a study known only by the old weak fingerprint -> "possible", not certain; a code clash with a
different image -> its own message, not "duplicate"; batch-internal repeat -> its own message; DICOM: two series whose
SeriesInstanceUIDs share the first 40 characters (the old truncated fingerprint) are different, the same series twice is a duplicate.
usage: python tests/check_duplicate_detection.py   (exit 1 on any FAIL)"""
import json, os, shutil, socket, subprocess, sys, tempfile, time, urllib.request
import numpy as np, nibabel as nib
H = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(H); PY = sys.executable
sys.path.insert(0, os.path.join(ROOT, "app")); import series_detect as SD   # noqa: E402
F = []
def check(n, ok, info=""): print(f"{'PASS' if ok else 'FAIL'}  {n}  {info}"); (None if ok else F.append(n))

T = tempfile.mkdtemp(prefix="dup_"); HOME = os.path.join(T, "home"); B = os.path.join(HOME, "syn_project"); SRC = os.path.join(T, "incoming")
for d in (os.path.join(B, "app_data"), os.path.join(B, "unified_engine"), SRC): os.makedirs(d)
with open(os.path.join(B, "unified_engine", "SYNTHETIC_BASE"), "w") as f: f.write("synthetic\n")
A0 = np.diag([0.8, 0.8, 1.2, 1]); A0[:3, 3] = [-90, -110, -60]
def swi(folder, seed, gz=False, shift=0.0):
    os.makedirs(folder, exist_ok=True); rng = np.random.default_rng(seed); v = np.zeros((128, 128, 40), np.int16)
    A = A0.copy(); A[0, 3] += shift
    yy, xx = np.mgrid[:128, :128]; m = ((xx - 64) / 45) ** 2 + ((yy - 64) / 55) ** 2 < 1
    for z in range(5, 35): v[:, :, z] = np.where(m, rng.integers(200, 900, (128, 128)), 0)
    img = nib.Nifti1Image(v, A); img.header["descrip"] = b"TE=20;SWI protocol"
    p = os.path.join(folder, "SWI_mag.nii" + (".gz" if gz else "")); nib.save(img, p)
    with open(os.path.join(folder, "SWI_mag.json"), "w") as f: json.dump(dict(SeriesDescription="SWI", ImageType=["ORIGINAL", "PRIMARY", "M", "SWI"]), f)
    return p
pa = swi(os.path.join(SRC, "STUDY_A"), 1); swi(os.path.join(SRC, "STUDY_B"), 2); swi(os.path.join(SRC, "STUDY_C"), 3); swi(os.path.join(SRC, "P_A"), 4)
shutil.copytree(os.path.join(SRC, "STUDY_A"), os.path.join(SRC, "STUDY_A_renamed")); os.makedirs(os.path.join(T, "elsewhere"))
shutil.copytree(os.path.join(SRC, "STUDY_A"), os.path.join(T, "elsewhere", "STUDY_A")); swi(os.path.join(SRC, "STUDY_A_gz"), 1, gz=True)
v1 = lambda f: next(s["fingerprint"] for s in SD.scan(f) if s.get("ok"))
check("regression precondition: different studies A and B share the OLD 64 KB fingerprint", v1(os.path.join(SRC, "STUDY_A")) == v1(os.path.join(SRC, "STUDY_B")))
check("new content fingerprints of A and B differ", SD.content_fingerprint(pa) != SD.content_fingerprint(os.path.join(SRC, "STUDY_B", "SWI_mag.nii")))
check(".nii and .nii.gz of the same image have the same content fingerprint", SD.content_fingerprint(pa) == SD.content_fingerprint(os.path.join(SRC, "STUDY_A_gz", "SWI_mag.nii.gz")))
swi(os.path.join(SRC, "STUDY_D"), 5, shift=7.5)                       # another protocol header -> another (weak) fingerprint group
shutil.copytree(os.path.join(SRC, "STUDY_C"), os.path.join(B, "raw", "P_OLD", "SWI"))   # the import's raw copy of an earlier study (before v5.15)
rec = lambda code, fp: dict(code=code, cohort="C", status="done", fingerprint=fp, series={}, steps_done={}, added=0, mode="semi", anatomy="synthseg")
pats = [rec("P_A", SD.content_fingerprint(pa)), rec("P_OLD", v1(os.path.join(SRC, "STUDY_C"))), rec("P_NORAW", v1(os.path.join(SRC, "STUDY_D")))]
with open(os.path.join(B, "app_data", "patients.json"), "w") as f: json.dump(pats, f)

s_ = socket.socket(); s_.bind(("127.0.0.1", 0)); port = s_.getsockname()[1]; s_.close(); U = f"http://127.0.0.1:{port}"
env = dict(os.environ, HOME=HOME, CSS_BASE=B, CSS_EXPERIMENTAL="1", PYTHONPATH=os.path.join(ROOT, "app", "guard"),
           CSS_PROTECTED_PATHS=":".join([os.path.expanduser("~/css_project"), os.path.expanduser("~/cSS_experimental")]))
app = subprocess.Popen([PY, os.path.join(ROOT, "app", "css_app.py"), "--port", str(port), "--no-window"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
def post(p, d):
    r = urllib.request.Request(U + p, data=json.dumps(d).encode(), headers={"Content-Type": "application/json", "X-CSS-App": "1"})
    return json.load(urllib.request.urlopen(r, timeout=120))
def scan(folder): return post("/api/scan", dict(path=folder, mode="single", folder_is="code", rule="whole"))["patients"][0]
try:
    for _ in range(80):
        try: urllib.request.urlopen(U + "/api/state", timeout=2); break
        except Exception: time.sleep(0.25)
    b = scan(os.path.join(SRC, "STUDY_B"))
    check("first-time import of a different study (same protocol header): no duplicate warning",
          not b.get("duplicate_of") and not any("DUPLICATE" in w or "already" in w for w in b["warnings"]), str(b["warnings"]))
    for name, folder in (("exact repeat", os.path.join(SRC, "STUDY_A")), ("renamed folder", os.path.join(SRC, "STUDY_A_renamed")),
                         ("moved folder", os.path.join(T, "elsewhere", "STUDY_A")), ("recompressed .nii.gz", os.path.join(SRC, "STUDY_A_gz"))):
        r = scan(folder)
        check(f"{name}: exact duplicate of P_A with the reason", r.get("duplicate_kind") == "exact" and r.get("duplicate_of") == ["P_A"]
              and any("complete image content" in w for w in r["warnings"]), str(r["warnings"])[:200])
    with open(os.path.join(B, "app_data", "patients.json")) as f: P = {p["code"]: p for p in json.load(f)}
    check("old weak fingerprint settled from the raw copy (additive: old value kept)", str(P["P_OLD"]["fingerprint"]).startswith("c2:")
          and P["P_OLD"]["fingerprint_v1"] == v1(os.path.join(SRC, "STUDY_C")) and P["P_A"]["fingerprint"] == SD.content_fingerprint(pa))
    check("patients.json backed up before the first fingerprint upgrade", os.path.exists(os.path.join(B, "app_data", "backups", "patients.before_fingerprint_v2.json")))
    c = scan(os.path.join(SRC, "STUDY_C"))
    check("re-import of that earlier study: exact duplicate after the upgrade", c.get("duplicate_kind") == "exact" and c.get("duplicate_of") == ["P_OLD"], str(c["warnings"])[:160])
    dd = scan(os.path.join(SRC, "STUDY_D"))
    check("old weak fingerprint without a raw copy: 'possible', never certain", dd.get("duplicate_kind") == "possible" and dd.get("duplicate_of") == ["P_NORAW"]
          and any("possibly" in w for w in dd["warnings"]))
    k = scan(os.path.join(SRC, "P_A"))
    check("code clash with a different image: own message, not a duplicate", not k.get("duplicate_of") and any("already used by another study" in w for w in k["warnings"])
          and not any("DUPLICATE" in w for w in k["warnings"]), str(k["warnings"]))
    q = post("/api/queue", dict(patients=[dict(folder_name="P_A", folder="x", code="P_A", chosen={"SWI": "x"})], settings=dict(cohort="C")))
    check("queue: existing code refused with a clear message", not q.get("ok") and any("already used by a study" in e for e in q.get("errors", [])), str(q))
    q = post("/api/queue", dict(patients=[dict(folder_name="X1", folder="x", code="NEW1", chosen={"SWI": "x"}), dict(folder_name="X2", folder="y", code="NEW1", chosen={"SWI": "y"})],
                                settings=dict(cohort="C")))
    check("queue: repeated code inside the batch has its own message", not q.get("ok") and any("more than once in this batch" in e for e in q.get("errors", [])), str(q))
    import pydicom
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian
    def series(folder, uid):
        os.makedirs(folder, exist_ok=True)
        for i in range(3):
            meta = FileMetaDataset(); meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.4"; meta.MediaStorageSOPInstanceUID = f"{uid}.{i}"
            meta.TransferSyntaxUID = ExplicitVRLittleEndian
            ds = FileDataset(os.path.join(folder, f"im{i}.dcm"), {}, file_meta=meta, preamble=b"\0" * 128)
            ds.SeriesInstanceUID = uid; ds.SOPInstanceUID = f"{uid}.{i}"; ds.SeriesDescription = "SWI"; ds.ImageType = ["ORIGINAL", "PRIMARY", "M", "SWI"]
            ds.PixelSpacing = [0.8, 0.8]; ds.SliceThickness = 1.2; ds.Rows = 4; ds.Columns = 4; ds.BitsAllocated = 16; ds.BitsStored = 16; ds.HighBit = 15
            ds.SamplesPerPixel = 1; ds.PhotometricInterpretation = "MONOCHROME2"; ds.PixelRepresentation = 0; ds.PixelData = (np.ones((4, 4), np.uint16) * i).tobytes()
            ds.save_as(os.path.join(folder, f"im{i}.dcm"), enforce_file_format=True)
    pre = "1.3.12.2.1107.5.2.43.167004.2026110609283565"           # 40+ shared characters, as from one scanner on one day
    series(os.path.join(T, "dcm", "S1", "SWI"), pre + "453222473.0.0.0"); series(os.path.join(T, "dcm", "S2", "SWI"), pre + "981726354.0.0.0")
    shutil.copytree(os.path.join(T, "dcm", "S1"), os.path.join(T, "dcm", "S1_again"))
    f1, f2, f3 = (SD.content_fingerprint(os.path.join(T, "dcm", x, "SWI")) for x in ("S1", "S2", "S1_again"))
    old = lambda x: (pre + x)[:40]
    check("DICOM regression precondition: the old 40-character fingerprints collide", old("453222473.0.0.0") == old("981726354.0.0.0"))
    check("DICOM: different series are different, the same series twice is identical", f1 != f2 and f1 == f3 and f1.startswith("uid:"))
finally:
    app.terminate(); app.wait(timeout=20)
shutil.rmtree(T, ignore_errors=True)
print(("ALL PASS" if not F else f"{len(F)} FAILED: {F}") + f" ({__file__})"); sys.exit(1 if F else 0)
