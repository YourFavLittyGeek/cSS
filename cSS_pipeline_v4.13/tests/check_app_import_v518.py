"""check_app_import_v518.py - v5.18 single Add-studies pathway, study library and export with files, through the real app (SYNTHETIC data,
write guard on, simulated pipeline runs). Covers:
  Standard  MRN folders + accession sub-folders without Excel (both identifiers from the folder names); blank codes generated;
            accession folders + Excel (MRN, name) matched by accession = folder name; MRN missing -> blocked;
            irrelevant folder names: an Excel row without 'folder' is refused, the folder column matches; grades from the Excel file
  Incognito the key is required; the vault passphrase is required (screens stay de-identified); code folders become the study code
            (v5.18 fix: they were replaced by generated PCV codes); a missing code blocks; the vault is locked again after the import;
            no MRN / name / accession / folder name in any response; Patient column = incognito icon
  Series    automatic SWI / T1 with reasons (phase and minIP never the SWI; 2-D T1 skipped for the 3-D one); manual override marked
            "chosen by you"; thumbnail PNG; DICOM header accession only cross-checks (it is never an identifier source)
  Library   Standard <MRN>/<accession>/, Incognito <code>/ (no grouping); every file verified; originals byte-identical and never renamed;
            an existing different examination in the place blocks the import (nothing overwritten); re-import = already in the library
  Export    Studies with files to a chosen folder: Standard MRN/accession folders, Incognito code folders without identifiers and without
            DICOM files; sha256 manifest verified; Desktop refused
  GUI       Add studies = one screen with two tabs (From folders / From another project); no "Store names", no separate guided import;
            folder-name choices name / MRN / accession / code / irrelevant
usage: python tests/check_app_import_v518.py [--shots DIR]   (exit 1 on any FAIL)"""
import glob, hashlib, json, re, os, shutil, socket, subprocess, sys, tempfile, time, urllib.error, urllib.request
import numpy as np, nibabel as nib
H = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(H); PY = sys.executable
sys.path.insert(0, os.path.join(ROOT, "app")); import manifest as MF   # noqa: E402
F = []
def check(n, ok, info=""): print(f"{'PASS' if ok else 'FAIL'}  {n}  {info}"); (None if ok else F.append(n))
SHOTS = sys.argv[sys.argv.index("--shots") + 1] if "--shots" in sys.argv else None
PW = "synthetic passphrase 518"
NAMES = ["Johnathan Smithfield", "Maryanne Jonesworth", "Pietro Albrechtsen"]
MRNS = ["55177301", "88204612", "66311907"]
ACCS = ["ACCX-1001", "ACCX-1002", "ACCX-1003", "ACCX-2001", "ACCX-3001", "ACCX-3002", "ACCX-4001"]
T = tempfile.mkdtemp(prefix="imp518_"); HOME = os.path.join(T, "home"); B = os.path.join(HOME, "syn_project")
for d in ("app_data", "private", "review"): os.makedirs(os.path.join(B, d))
LIB = os.path.join(T, "library"); XP = os.path.join(T, "exports"); os.makedirs(LIB); os.makedirs(XP); os.makedirs(os.path.join(HOME, "Desktop"))
SRC = os.path.join(T, "incoming")          # source folders: their paths must never appear (the chosen library / export folders may)


def nii(path, shape, vox, seed, desc, itype):
    os.makedirs(os.path.dirname(path), exist_ok=True); rng = np.random.default_rng(seed)
    v = rng.integers(50, 900, shape).astype(np.int16); nib.save(nib.Nifti1Image(v, np.diag(list(vox) + [1])), path)
    with open(path.replace(".nii", ".json"), "w") as f: json.dump(dict(SeriesDescription=desc, ImageType=itype, MRAcquisitionType="3D" if desc.startswith("T1_MPRAGE") else "2D"), f)
def exam(folder, seed, t1=True, extra_swi=False, phase=False, minip=False, t1_2d=False, flair=False):
    nii(os.path.join(folder, f"SWI_{NAMES[0].replace(' ', '_')}.nii"), (48, 48, 20), (0.8, 0.8, 1.2), seed, "SWI_Images", ["ORIGINAL", "PRIMARY", "M", "SWI"])
    if extra_swi: nii(os.path.join(folder, "SWI_lowres.nii"), (32, 32, 12), (1.2, 1.2, 2.5), seed + 100, "SWI_lowres", ["ORIGINAL", "PRIMARY", "M", "SWI"])
    if phase: nii(os.path.join(folder, "SWI_phase.nii"), (48, 48, 20), (0.8, 0.8, 1.2), seed + 200, "SWI_Pha_Images", ["ORIGINAL", "PRIMARY", "P", "SWI"])
    if minip: nii(os.path.join(folder, "mIP_Images.nii"), (48, 48, 20), (0.8, 0.8, 1.2), seed + 300, "mIP_Images(SW)", ["DERIVED", "SECONDARY", "MNIP"])
    if t1: nii(os.path.join(folder, "T1_MPRAGE.nii"), (112, 112, 112), (1.0, 1.0, 1.0), seed + 400, "T1_MPRAGE_SAG", ["ORIGINAL", "PRIMARY", "M"])
    if t1_2d: nii(os.path.join(folder, "T1_axial_2D.nii"), (64, 64, 24), (0.9, 0.9, 5.0), seed + 500, "T1_AX_SE", ["ORIGINAL", "PRIMARY", "M"])
    if flair: nii(os.path.join(folder, "FLAIR_axial.nii"), (64, 64, 30), (0.9, 0.9, 4.0), seed + 600, "FLAIR_AX", ["ORIGINAL", "PRIMARY", "M"])
def dicom_exam(folder, seed, acc, pid):
    import pydicom
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid
    st = generate_uid(); rng = np.random.default_rng(seed)
    for desc, itype, n in (("SWI_Images", ["ORIGINAL", "PRIMARY", "M", "SWI"], 10),):
        se = generate_uid(); d = os.path.join(folder, desc); os.makedirs(d)
        for k in range(n):
            fm = FileMetaDataset(); fm.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.4"; fm.MediaStorageSOPInstanceUID = generate_uid(); fm.TransferSyntaxUID = ExplicitVRLittleEndian
            ds = FileDataset(os.path.join(d, f"IM{k:04d}.dcm"), {}, file_meta=fm, preamble=b"\0" * 128)
            ds.SOPClassUID = fm.MediaStorageSOPClassUID; ds.SOPInstanceUID = fm.MediaStorageSOPInstanceUID; ds.StudyInstanceUID = st; ds.SeriesInstanceUID = se
            ds.PatientName = NAMES[2]; ds.PatientID = pid; ds.AccessionNumber = acc; ds.StudyDate = "20250105"; ds.Modality = "MR"
            ds.SeriesDescription = desc; ds.ImageType = itype; ds.PixelSpacing = [0.8, 0.8]; ds.SliceThickness = 1.2; ds.EchoTime = 20; ds.MagneticFieldStrength = 3
            ds.MRAcquisitionType = "3D"; ds.InstanceNumber = k + 1; ds.ImagePositionPatient = [0, 0, k * 1.2]; ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
            ds.Rows = ds.Columns = 32; ds.SamplesPerPixel = 1; ds.PhotometricInterpretation = "MONOCHROME2"; ds.BitsAllocated = ds.BitsStored = 16; ds.HighBit = 15; ds.PixelRepresentation = 0
            ds.PixelData = rng.integers(0, 900, (32, 32)).astype(np.uint16).tobytes(); ds.is_little_endian = True; ds.is_implicit_VR = False
            ds.save_as(os.path.join(d, f"IM{k:04d}.dcm"), write_like_original=False)
def xlsx(path, rows):
    from openpyxl import load_workbook
    with open(path, "wb") as f: f.write(MF.template_bytes(example=False))
    wb = load_workbook(path); ws = wb["examinations"]
    for r in rows: ws.append(list(r) + [""] * (9 - len(r)))
    wb.save(path)
def tree_hash(d):
    out = {}
    for root, _, fs in os.walk(d):
        for f in fs:
            p = os.path.join(root, f)
            with open(p, "rb") as fh: out[os.path.relpath(p, d)] = hashlib.sha256(fh.read()).hexdigest()
    return out

# ---- synthetic sources
S1 = os.path.join(SRC, "std_mrn"); exam(os.path.join(S1, MRNS[0], ACCS[0]), 1, extra_swi=True, phase=True, minip=True, t1_2d=True, flair=True); exam(os.path.join(S1, MRNS[0], ACCS[1]), 2); exam(os.path.join(S1, MRNS[1], ACCS[3]), 3)
S2 = os.path.join(SRC, "std_acc"); exam(os.path.join(S2, ACCS[4]), 4); exam(os.path.join(S2, ACCS[5]), 5)
X2 = os.path.join(T, "std_acc.xlsx"); xlsx(X2, [(MRNS[2], NAMES[2], ACCS[4], ""), (MRNS[2], NAMES[2], ACCS[5], "SYNC-ACC5")])
S3 = os.path.join(SRC, "std_none"); exam(os.path.join(S3, "batch_a", "x1"), 6); exam(os.path.join(S3, "batch_b"), 7)
X3bad = os.path.join(T, "std_none_bad.xlsx"); xlsx(X3bad, [("70000001", "", "ACCN-01", "", "batch_a/x1"), ("70000002", "", "ACCN-02", "", "", "", "Dr Q", "1", "2")])
X3 = os.path.join(T, "std_none.xlsx"); xlsx(X3, [("70000001", "", "ACCN-01", "", "batch_a/x1"), ("70000002", "", "ACCN-02", "", "batch_b", "", "Dr Q", "1", "2")])
S4 = os.path.join(SRC, "inc_code"); exam(os.path.join(S4, "SYNC-0101"), 11); exam(os.path.join(S4, "SYNC-0102"), 12)
X4 = os.path.join(T, "inc_key.xlsx"); xlsx(X4, [("90000001", "Inco Patientone", "ACCI-01", "SYNC-0101"), ("90000001", "Inco Patientone", "ACCI-02", "SYNC-0102")])
S5 = os.path.join(SRC, "inc_dicom"); dicom_exam(os.path.join(S5, "anything_7"), 21, "ACCD-0001", "40000001")
X5 = os.path.join(T, "inc_dicom.xlsx"); xlsx(X5, [("40000001", "Dicom Persona", "ACCD-0001", "SYNC-D001", "anything_7")])
X5nocode = os.path.join(T, "inc_dicom_nocode.xlsx"); xlsx(X5nocode, [("40000001", "Dicom Persona", "ACCD-0001", "", "anything_7")])
ORIG = {d: tree_hash(d) for d in (S1, S2, S3, S4, S5)}
SECRETS = NAMES + MRNS + ACCS + ["Inco Patientone", "90000001", "ACCI-01", "ACCI-02", "Dicom Persona", "40000001", "ACCD-0001", "70000001", "ACCN-01", SRC]


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
def start():
    port = free_port(); env = dict(os.environ, HOME=HOME, CSS_BASE=B, CSS_EXPERIMENTAL="1", CSS_APP_FAKE_RUN="1", CSS_APP_FAKE_STEP_S="0.03", PYTHONPATH=os.path.join(ROOT, "app", "guard"),
                                   CSS_PROTECTED_PATHS=":".join([os.path.expanduser("~/css_project"), os.path.expanduser("~/cSS_experimental"), os.path.expanduser("~/Projects/cSS")]))
    p = subprocess.Popen([PY, os.path.join(ROOT, "app", "css_app.py"), "--port", str(port), "--no-window"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    U = f"http://127.0.0.1:{port}"
    for _ in range(80):
        try: urllib.request.urlopen(U + "/api/state", timeout=2); return p, U
        except Exception: time.sleep(0.25)
    return p, U
def raw(U, path):
    try: return urllib.request.urlopen(U + path, timeout=120).read()
    except urllib.error.HTTPError as e: return e.read()
def get(U, path): return json.loads(raw(U, path))
SEEN = []
def post(U, path, d):
    rq = urllib.request.Request(U + path, data=json.dumps(d).encode(), headers={"Content-Type": "application/json", "X-CSS-App": "1"})
    b = urllib.request.urlopen(rq, timeout=300).read().decode(); SEEN.append((path, b)); return json.loads(b)
def leaks(text): return [s for s in SECRETS if s in text]
def wait(cond, limit=60):
    t0 = time.time()
    while time.time() - t0 < limit:
        if cond(): return True
        time.sleep(0.3)
    return False
def done_codes(U, codes): return wait(lambda: all({p["code"]: p["status"] for p in get(U, "/api/state")["patients"]}.get(c) == "done" for c in codes))
chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
def dom(U, url): return _noscript(_dom(U, url))
def _noscript(D):                                        # the rendered page only: the app's own script source contains the same markup as text
    import re as _re; return _re.sub(r"<script\b[^>]*>.*?</script>", "", D, flags=_re.S)
def _dom(U, url): return subprocess.run([chrome, "--headless=new", "--disable-gpu", f"--user-data-dir={os.path.join(T, 'chrome')}", "--virtual-time-budget=9000", "--dump-dom", f"{U}/{url}"],
                                       capture_output=True, text=True, timeout=120).stdout if os.path.exists(chrome) else ""
def shot(U, name, url, h=1300):
    if SHOTS and os.path.exists(chrome):
        os.makedirs(SHOTS, exist_ok=True)
        subprocess.run([chrome, "--headless=new", "--disable-gpu", f"--user-data-dir={os.path.join(T, 'chrome')}", "--hide-scrollbars", f"--window-size=1500,{h}", "--virtual-time-budget=9000",
                        f"--screenshot={os.path.join(SHOTS, name + '.png')}", f"{U}/{url}"], capture_output=True, timeout=120)
def job(U, jid, path):
    out = {}
    wait(lambda: out.update(get(U, f"{path}?id={jid}")) or out.get("state") in ("finished", "failed"), 60); return out
LIBON = dict(enabled=True, root=LIB, whole_exam=False)
PROC = dict(cohort="C518")

app, U = start()
try:
    # ------------------------------------------------------------------ GUI: one Add-studies screen
    D = dom(U, "#add")
    check("Add studies: one screen, two tabs (From folders / From another project)", 'data-id="addtabs"' in D and "From folders" in D and "From another project" in D, "")
    check("no separate guided import and no 'Store names' option", "Open guided import" not in D and "Store names" not in D and "From image folders" not in D)
    check("folder-name choices: patient name / MRN / accession number / code / irrelevant", all(x in D for x in ('data-v="name"', 'data-v="mrn"', 'data-v="accession"', 'data-v="code"', 'data-v="none"')))
    # template: the app window (pywebview) ignores browser downloads, so the GUI saves it into a chosen folder (regression: "Download template" did nothing)
    check("GUI: no browser-download link for the template; a Save template button instead", 'href="/api/id/template.xlsx"' not in D and 'data-iw="template"' in D and "Save template" in D)
    TD = os.path.join(T, "templates"); os.makedirs(TD)
    r1 = post(U, "/api/id/template/save", dict(dest=TD)); r2 = post(U, "/api/id/template/save", dict(dest=TD))
    import pandas as _pd
    cols = list(_pd.read_excel(r1.get("path", "/nonexistent"), dtype=str).columns) if r1.get("ok") else []
    check("template saved into the chosen folder (4 columns + optional columns)", r1.get("ok") and cols[:4] == MF.COLUMNS and cols[4:] == MF.OPTIONAL, str(r1))
    check("a second save never overwrites (numbered copy)", r2.get("ok") and r2["path"].endswith("Percival_Import_Template (2).xlsx") and os.path.exists(r1["path"]))
    check("template save to Desktop refused (it will hold identifiers)", post(U, "/api/id/template/save", dict(dest=os.path.join(HOME, "Desktop"))).get("ok") is False)
    # vault (Standard needs it; Incognito import stores the key in it)
    r = post(U, "/api/id/vault/create", dict(passphrase=PW)); check("identity vault created", r.get("ok"), str(r))
    post(U, "/api/id/mode", dict(mode="standard", passphrase=PW))
    # ------------------------------------------------------------------ Standard A: MRN folders + accession sub-folders, no Excel
    pa = post(U, "/api/id/import/plan", dict(folder=S1, folder_is="mrn", sub_is="accession", mode="standard", library=LIBON, processing=PROC))
    E = {e["accession"]: e for e in pa["exams"]}
    check("Standard, no Excel: MRN and accession from the folder names", pa["ok"] and sorted(E) == sorted([ACCS[0], ACCS[1], ACCS[3]]) and all(e["accession_source"] == "folder name" and e["mrn_source"] == "folder name" for e in pa["exams"]), str(pa.get("errors"))[:300])
    check("Standard: blank code is generated at import", all(e["code_generated"] and not e["code"] for e in pa["exams"]))
    check("library place = <MRN>/<accession>", E[ACCS[0]]["library"] == os.path.join(MRNS[0], ACCS[0]))
    e0 = E[ACCS[0]]
    check("series: SWI and T1 chosen automatically with the reason", set(e0["chosen"]) >= {"SWI", "T1"} and "phase / minIP never" in e0["auto_why"]["SWI"] and "3-D" in e0["auto_why"]["T1"])
    sv = get(U, f"/api/id/import/series?plan={pa['id']}&eid={e0['eid']}")
    by = {s["description"]: s for s in sv["series"]}
    check("automatic SWI = the high-resolution magnitude (not phase, not minIP, not the low-resolution one)", "SWI" in by["SWI_Images ORIGINAL\\PRIMARY\\M\\SWI"]["chosen_as"] if "SWI_Images ORIGINAL\\PRIMARY\\M\\SWI" in by else any(s["chosen_as"] == ["SWI"] and "lowres" not in s["description"] and "Pha" not in s["description"] and "mIP" not in s["description"] for s in sv["series"]), str([(s["description"], s["chosen_as"]) for s in sv["series"]])[:300])
    check("automatic T1 = the 3-D MPRAGE (2-D T1 skipped)", any("MPRAGE" in s["description"] and "T1" in s["chosen_as"] for s in sv["series"]))
    check("FLAIR detected and chosen (it is offered again)", any("FLAIR" in s["description"] and "FLAIR" in s["chosen_as"] for s in sv["series"]) and "FLAIR" in e0["chosen"])
    check("series advice per examination (several SWI noted; skipped 2-D T1 explained)", any("SWI series" in a["msg"] for a in e0["advice"]) and any("another T1 was not chosen" in a["msg"] for a in e0["advice"]), str(e0["advice"])[:300])
    e2 = E[ACCS[3]]
    check("series advice: no FLAIR is an optional note, not a warning", any(a["level"] == "info" and "no FLAIR" in a["msg"] for a in e2["advice"]) and not any(a["level"] == "warn" for a in e2["advice"]))
    th = raw(U, f"/api/id/import/thumb?plan={pa['id']}&eid={e0['eid']}&i=0"); check("thumbnail of a series (PNG made locally)", th[:8] == b"\x89PNG\r\n\x1a\n")
    low = next(s["i"] for s in sv["series"] if "lowres" in s["description"])
    pu = post(U, "/api/id/import/update", dict(plan=pa["id"], changes=[dict(eid=e0["eid"], series=dict(SWI=low))]))
    e0b = next(e for e in pu["exams"] if e["eid"] == e0["eid"])
    check("manual series choice applied and marked 'chosen by you'", e0b["chosen"]["SWI"] == low and e0b["user_series"])
    pu = post(U, "/api/id/import/update", dict(plan=pa["id"], changes=[dict(eid=e0["eid"], series=dict(SWI=next(s["i"] for s in sv["series"] if "SWI" in s["auto_as"])))]))
    check("back to the automatic choice: no longer 'chosen by you'", not next(e for e in pu["exams"] if e["eid"] == e0["eid"])["user_series"])
    import urllib.parse as _up
    shot(U, "v518_add_standard_preview", f"#add?folder={_up.quote(S1, safe='')}&folder_is=mrn&sub_is=accession&mode=standard&cohort=C518&go=1", 2300)
    ca = post(U, "/api/id/import/commit", dict(plan=pa["id"], confirm=True, cohort="C518", by="tester"))
    keyA = [x["file_key"] for x in ca.get("imported", [])]
    check("Standard import committed and queued", ca.get("ok") and len(keyA) == 3 and done_codes(U, keyA), str(ca)[:200])
    jl = job(U, ca["library_job"], "/api/id/library/job")
    check("library: 3 examinations copied and verified", jl.get("state") == "finished" and [i["state"] for i in jl["items"]] == ["copied"] * 3, str(jl)[:300])
    d0 = os.path.join(LIB, MRNS[0], ACCS[0])
    lj = json.load(open(os.path.join(d0, "percival_library.json")))
    check("library folder <MRN>/<accession> with neutral file names and a verified file list", os.path.isfile(os.path.join(d0, "SWI", "SWI.nii")) and os.path.isfile(os.path.join(d0, "T1", "T1.nii"))
          and all(len(f["sha256"]) == 64 for f in lj["files"]) and not any(NAMES[0].replace(" ", "_") in f["file"] for f in lj["files"]))
    check("library copy is identical to the original", hashlib.sha256(open(os.path.join(d0, "SWI", "SWI.nii"), "rb").read()).hexdigest() == ORIG[S1][os.path.join(MRNS[0], ACCS[0], f"SWI_{NAMES[0].replace(' ', '_')}.nii")])
    check("originals unchanged and never renamed", tree_hash(S1) == ORIG[S1])
    R = {r["code"]: r for r in get(U, "/api/results")}
    check("one patient (MRN) with two examinations, grouped by MRN", sorted(R[k]["ident"]["n_exams_of_patient"] for k in keyA) == [1, 2, 2] and {R[k]["ident"]["mrn"] for k in keyA} == {MRNS[0], MRNS[1]})
    check("generated codes stored (study usable in Incognito)", all(R[k]["ident"]["deid_code"].startswith("PCV-") for k in keyA))
    D = dom(U, "#studies")
    check("Studies (Standard): separate Code / Accession / Patient name / MRN columns, each sortable", all(f'data-sk="{k}"' in D for k in ("code", "acc", "name", "mrn", "cohort", "status", "cand", "rev", "score")) and 'data-id="patcol"' in D)
    check("Studies: status filter offers every status", all(f"<option>{x}</option>" in D or f"<option selected=\"\">{x}</option>" in D for x in ("Needs attention", "Needs your decision", "Processing", "Paused", "Waiting", "Not processed", "Ready for review", "Review in progress", "Needs re-review", "Reviewed")))
    check("Studies (Standard): grouped by MRN by default (one header per patient, examination count)", D.count('class="sgroup"') == 2 and f"MRN {MRNS[0]}" in D and "2 examinations" in D)
    D2 = dom(U, "#studies?grp=none&sort=mrn&dir=desc")
    rows_m = [m for m in MRNS[:2] if m in D2]
    check("Studies: no grouping on request; sort by MRN descending", 'class="sgroup"' not in D2 and D2.index(MRNS[1]) < D2.index(MRNS[0]), str(rows_m))
    D3 = dom(U, "#studies?grp=none&sort=mrn&dir=asc")
    check("Studies: sort by MRN ascending", D3.index(MRNS[0]) < D3.index(MRNS[1]))
    D4 = dom(U, f"#studies?grp=name&mrn={MRNS[1]}")
    TB4 = D4[D4.find("<tbody>"):D4.find("</tbody>")]       # the studies table only (the hidden log dialog lists every study too)
    check("Studies: filter by MRN; grouped by patient name", MRNS[1] in TB4 and f">{ACCS[0]}<" not in TB4 and 'class="sgroup"' in TB4)
    D5 = dom(U, "#studies?grp=none&status=Reviewed")
    check("Studies: filter by status (none reviewed yet)", "No study matches these filters." in D5)
    shot(U, "v518_studies_standard", "#studies")
    pa2 = post(U, "/api/id/import/plan", dict(folder=S1, folder_is="mrn", sub_is="accession", mode="standard", library=LIBON, processing=PROC))
    check("re-import: recognised and left out", all(not e["include"] and e["duplicate"]["kind"] == "same_exam" for e in pa2["exams"]))
    # ------------------------------------------------------------------ Standard B: accession folders + Excel
    pb = post(U, "/api/id/import/plan", dict(folder=S2, folder_is="accession", mode="standard", manifest=X2, library=LIBON, processing=PROC))
    check("accession folders: Excel rows matched by accession = folder name", pb["ok"] and all(e["matched_by"] == "accession = folder name" for e in pb["exams"]) and {e["mrn"] for e in pb["exams"]} == {MRNS[2]}, str(pb.get("errors"))[:300])
    check("Excel code used; blank Excel code generated", sorted(e["code"] for e in pb["exams"]) == ["", "SYNC-ACC5"])
    # MRN missing -> blocked
    pm = post(U, "/api/id/import/plan", dict(folder=S2, folder_is="accession", mode="standard", processing=PROC))
    check("Standard without MRN: blocked (MRN is required from the user)", not pm["ok"] and any("MRN missing" in x["msg"] for x in pm["errors"]))
    # put a DIFFERENT examination in a library place -> blocked, nothing overwritten
    os.makedirs(os.path.join(LIB, MRNS[2], ACCS[4])); open(os.path.join(LIB, MRNS[2], ACCS[4], "other.txt"), "w").write("someone else")
    pb = post(U, "/api/id/import/plan", dict(folder=S2, folder_is="accession", mode="standard", manifest=X2, library=LIBON, processing=PROC))
    check("library place already holds a different examination: blocked, nothing overwritten", not pb["ok"] and any("different examination" in x["msg"] for x in pb["errors"]) and open(os.path.join(LIB, MRNS[2], ACCS[4], "other.txt")).read() == "someone else")
    shutil.rmtree(os.path.join(LIB, MRNS[2]))
    pb = post(U, "/api/id/import/plan", dict(folder=S2, folder_is="accession", mode="standard", manifest=X2, library=LIBON, processing=PROC))
    cb = post(U, "/api/id/import/commit", dict(plan=pb["id"], confirm=True, cohort="C518", by="tester")); keyB = [x["file_key"] for x in cb.get("imported", [])]
    check("accession-folder import committed", cb.get("ok") and done_codes(U, keyB) and job(U, cb["library_job"], "/api/id/library/job").get("state") == "finished")
    # ------------------------------------------------------------------ Standard C: irrelevant folder names
    pc = post(U, "/api/id/import/plan", dict(folder=S3, folder_is="none", mode="standard", processing=PROC))
    check("irrelevant folder names without Excel: refused", pc.get("ok") is False and "folder" in pc.get("error", ""))
    pc = post(U, "/api/id/import/plan", dict(folder=S3, folder_is="none", mode="standard", manifest=X3bad, processing=PROC))
    check("irrelevant folder names: an Excel row without 'folder' is refused", not pc["ok"] and any("must name its examination's folder" in x["msg"] for x in pc["errors"]))
    pc = post(U, "/api/id/import/plan", dict(folder=S3, folder_is="none", mode="standard", manifest=X3, library=LIBON, processing=PROC))
    check("irrelevant folder names: matched by the Excel folder column", pc["ok"] and all(e["matched_by"] == "Excel folder column" for e in pc["exams"]) and sorted(e["accession"] for e in pc["exams"]) == ["ACCN-01", "ACCN-02"], str(pc.get("errors"))[:300])
    cc = post(U, "/api/id/import/commit", dict(plan=pc["id"], confirm=True, cohort="C518", by="tester")); keyC = [x["file_key"] for x in cc.get("imported", [])]
    check("grades from the Excel file reach the study", cc.get("ok") and done_codes(U, keyC) and any(p.get("grade_R") == "1" and p.get("grade_L") == "2" and p.get("radiologist") == "Dr Q" for p in get(U, "/api/state")["patients"] if p["code"] in keyC))
    job(U, cc["library_job"], "/api/id/library/job")
    # ------------------------------------------------------------------ export (Standard)
    k0 = keyA[0]
    with open(os.path.join(B, "review", f"{k0}_candidates.csv"), "w") as f: f.write("cand_id,vox_i,vox_j,vox_k\n1,1,2,3\n")
    os.makedirs(os.path.join(B, "work"), exist_ok=True); nii(os.path.join(B, "work", f"{k0}_brainmask.nii"), (8, 8, 8), (1, 1, 1), 99, "mask", ["DERIVED"])
    r = post(U, "/api/xs/plan", dict(codes=[k0], parts=dict(processed=True, mri=True), dest=os.path.join(HOME, "Desktop")))
    check("export to Desktop refused (iCloud sync)", r.get("ok") and not r["dest_ok"])
    r = post(U, "/api/xs/start", dict(codes=[k0], parts=dict(processed=True, mri=True), dest=XP))
    check("export needs the clinical-data confirmation", r.get("needs_confirm") is True)
    r = post(U, "/api/xs/start", dict(codes=[k0], parts=dict(processed=True, mri=True), dest=XP, confirm_clinical=True))
    jx = job(U, r.get("job", ""), "/api/xs/job")
    out = jx.get("folder", "")
    sd = os.path.join(out, MRNS[0], next(k for k in (ACCS[0], ACCS[1]) if os.path.isdir(os.path.join(out, MRNS[0], k)))) if out and os.path.isdir(os.path.join(out, MRNS[0])) else ""
    man = json.load(open(os.path.join(out, "export_manifest.json"))) if out and os.path.exists(os.path.join(out, "export_manifest.json")) else {"files": []}
    okh = all(hashlib.sha256(open(os.path.join(out, f["file"]), "rb").read()).hexdigest() == f["sha256"] for f in man["files"] if "sha256" in f)
    check("Standard export: <MRN>/<accession>/ with results, processed files and MRI; every file verified", jx.get("state") == "finished" and sd and os.path.isfile(os.path.join(sd, "results", f"{k0}_candidates.csv"))
          and os.path.isfile(os.path.join(sd, "processed", f"{k0}_brainmask.nii")) and os.path.isdir(os.path.join(sd, "mri", "SWI")) and okh and os.path.isfile(os.path.join(out, "results.xlsx")), str(jx)[:300])
    # ------------------------------------------------------------------ Incognito
    post(U, "/api/id/mode", dict(mode="incognito"))
    pi = post(U, "/api/id/import/plan", dict(folder=S4, folder_is="code", mode="incognito", processing=PROC))
    check("Incognito without the key: refused", pi.get("ok") is False and "key" in pi.get("error", ""))
    pi = post(U, "/api/id/import/plan", dict(folder=S4, folder_is="code", mode="incognito", manifest=X4, library=LIBON, processing=PROC))
    check("Incognito: the vault passphrase is required to store the key", not pi["ok"] and any("vault passphrase" in x["msg"] for x in pi["errors"]))
    r = post(U, "/api/id/vault/unlock", dict(passphrase=PW)); st = get(U, "/api/id/state")
    check("vault unlocked for the import while the screens stay de-identified", r.get("ok") and st["mode"] == "incognito" and st["unlocked"] and not st["revealing"])
    pi = post(U, "/api/id/import/plan", dict(folder=S4, folder_is="code", mode="incognito", manifest=X4, library=LIBON, processing=PROC))
    check("v5.18 fix: code folder names become the study codes", pi["ok"] and sorted(e["code"] for e in pi["exams"]) == ["SYNC-0101", "SYNC-0102"] and all(e["code_source"] in ("Excel", "folder name") for e in pi["exams"]), str(pi.get("errors"))[:300])
    check("Incognito library = one folder per code (no grouping)", sorted(e["library"] for e in pi["exams"]) == ["SYNC-0101", "SYNC-0102"])
    check("Incognito preview: no MRN / name / accession / folder names / paths", not leaks(json.dumps(pi)), str(leaks(json.dumps(pi))))
    ci = post(U, "/api/id/import/commit", dict(plan=pi["id"], confirm=True, cohort="C518", by="tester")); keyI = [x["file_key"] for x in ci.get("imported", [])]
    check("Incognito import committed under the given codes", ci.get("ok") and sorted(keyI) == ["SYNC-0101", "SYNC-0102"] and done_codes(U, keyI))
    check("vault locked again after the Incognito import", get(U, "/api/id/state")["unlocked"] is False)
    jl = job(U, ci["library_job"], "/api/id/library/job")
    check("Incognito library folders <code>/ copied and verified", jl.get("state") == "finished" and all(os.path.isfile(os.path.join(LIB, c, "SWI", "SWI.nii")) for c in keyI))
    # DICOM, irrelevant folder names; the header accession only cross-checks
    post(U, "/api/id/vault/unlock", dict(passphrase=PW))
    pd_ = post(U, "/api/id/import/plan", dict(folder=S5, folder_is="none", mode="incognito", manifest=X5nocode, processing=PROC))
    check("Incognito: a missing code blocks the import", not pd_["ok"] and any("code missing" in x["msg"] for x in pd_["errors"]))
    pd_ = post(U, "/api/id/import/plan", dict(folder=S5, folder_is="none", mode="incognito", manifest=X5, library=LIBON, processing=PROC))
    check("DICOM examination matched by the folder column; code from the key", pd_["ok"] and pd_["exams"][0]["code"] == "SYNC-D001" and pd_["exams"][0]["matched_by"] == "Excel folder column", str(pd_.get("errors"))[:300])
    cd = post(U, "/api/id/import/commit", dict(plan=pd_["id"], confirm=True, cohort="C518", by="tester")); keyD = [x["file_key"] for x in cd.get("imported", [])]
    check("DICOM import committed", cd.get("ok") and done_codes(U, keyD) and job(U, cd["library_job"], "/api/id/library/job").get("state") == "finished")
    # Incognito export: code folders, no identifiers, no DICOM
    r = post(U, "/api/xs/start", dict(codes=keyD + [k0], parts=dict(processed=True, mri=True, logs=True), dest=XP, confirm_clinical=True)); jx = job(U, r.get("job", ""), "/api/xs/job"); out = jx.get("folder", "")
    allf = [os.path.relpath(os.path.join(rt, f), out) for rt, _, fs in os.walk(out) for f in fs] if out else []
    txt = "".join(open(os.path.join(out, f), errors="replace").read() for f in allf if f.endswith((".txt", ".json", ".csv", ".log")))
    deid0 = get(U, f"/api/id/study?code={k0}")["deid_code"]
    check("Incognito export: one folder per code, no MRN / accession folders", jx.get("state") == "finished" and os.path.isdir(os.path.join(out, "SYNC-D001")) and os.path.isdir(os.path.join(out, deid0)) and not os.path.isdir(os.path.join(out, MRNS[0])), str(jx)[:200])
    check("Incognito export: no DICOM files (their headers hold identifiers)", not any(f.endswith(".dcm") for f in allf))
    check("Incognito export: no identifier in file names or text files", not leaks(" ".join(allf) + txt), str(leaks(" ".join(allf) + txt))[:200])
    D = dom(U, "#studies")
    check("Studies (Incognito): Patient column shows the incognito icon, no identifiers", 'data-id="incog"' in D and not leaks(D), str(leaks(D))[:200])
    check("Studies (Incognito): no grouping, no accession / name / MRN columns", 'class="sgroup"' not in D and 'data-sk="mrn"' not in D and 'data-sk="acc"' not in D and "Incognito: list by code" in D)
    shot(U, "v518_studies_incognito", "#studies")
    post(U, "/api/id/vault/unlock", dict(passphrase=PW))
    shot(U, "v518_add_incognito_preview", f"#add?folder={_up.quote(S4, safe='')}&folder_is=code&mode=incognito&cohort=C518&go=1&manifest={_up.quote(X4, safe='')}", 2300)
    post(U, "/api/id/vault/lock", {})
    bodies = [b for p_, b in SEEN if "/api/id/import/" in p_ and '"mode": "incognito"' in b]
    check("no Incognito import response contained an identifier", bodies and not any(leaks(b) for b in bodies))
finally:
    app.terminate(); app.wait(timeout=20)
check("all original folders unchanged", all(tree_hash(d) == h for d, h in ORIG.items()))
logs = "".join(open(f, errors="replace").read() for f in glob.glob(os.path.join(B, "app_data", "logs", "*")) + glob.glob(os.path.join(B, "logs", "*")))
reg = open(os.path.join(B, "app_data", "identity", "registry.json")).read()
check("no MRN / name / accession / source path in the registry or the logs", not leaks(reg + logs), str(leaks(reg + logs))[:200])
shutil.rmtree(T, ignore_errors=True)
print(("ALL PASS" if not F else f"{len(F)} FAILED: {F}") + f" ({__file__})"); sys.exit(1 if F else 0)
