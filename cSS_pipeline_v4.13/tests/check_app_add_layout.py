"""check_app_add_layout.py - v5.18 Add studies › From folders preview layout through the real app + headless Chrome (SYNTHETIC folders;
replaces the v5.17 batch-table check - that screen was merged into this one): a very long folder path and six examination folders with
long names and long series file names are planned via the #add deep link; at 1280 and 1500 px the preview must not overflow
horizontally, no control may be clipped inside its cell, one row per examination, the codes taken from the folder names.
usage: python tests/check_app_add_layout.py [--shots DIR]   (exit 1 on any FAIL)"""
import json, os, re, shutil, socket, subprocess, sys, tempfile, time, urllib.parse, urllib.request
import numpy as np, nibabel as nib
H = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(H); PY = sys.executable
F = []
def check(n, ok, info=""): print(f"{'PASS' if ok else 'FAIL'}  {n}  {info}"); (None if ok else F.append(n))
SHOTS = sys.argv[sys.argv.index("--shots") + 1] if "--shots" in sys.argv else None
chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if not os.path.exists(chrome): print("SKIP  Google Chrome not found"); print("ALL PASS"); sys.exit(0)
T = tempfile.mkdtemp(prefix="batch_"); HOME = os.path.join(T, "home"); B = os.path.join(HOME, "syn_project"); os.makedirs(os.path.join(B, "app_data"))
LONG = os.path.join(T, "Research_Imaging_Archive_2026_exported_from_the_departmental_PACS", "Cerebral_Amyloid_Angiopathy_cohort_SWI_and_T1_series",
                    "batch_with_a_deliberately_very_long_folder_name_to_test_wrapping")
for i in range(6):
    d = os.path.join(LONG, f"SYNTH-CODE-{i:02d}_with_a_long_descriptive_folder_name_for_layout_testing"[:32])
    for sub, desc in (("SWI_magnitude_series_high_resolution_axial_3D", "SWI"), ("T1_MPRAGE_sagittal_isotropic_1mm_series", "T1 MPRAGE")):
        os.makedirs(os.path.join(d, sub)); f = os.path.join(d, sub, f"{sub}_reconstruction_number_0001_of_the_examination.nii")
        nib.save(nib.Nifti1Image(np.random.default_rng(i * 7 + len(sub)).integers(0, 500, (32, 32, 16)).astype(np.int16), np.diag([0.8, 0.8, 1.2, 1])), f)
        with open(f[:-4] + ".json", "w") as fh: json.dump(dict(SeriesDescription=desc, ImageType=["ORIGINAL", "PRIMARY", "M"] + (["SWI"] if desc == "SWI" else [])), fh)
sys.path.insert(0, os.path.join(ROOT, "app")); import manifest as MF   # noqa: E402
from openpyxl import load_workbook
KEY = os.path.join(T, "key.xlsx")
with open(KEY, "wb") as f: f.write(MF.template_bytes(example=False))
wb = load_workbook(KEY); ws = wb["examinations"]
for i in range(6): ws.append([f"9100000{i}", f"Synthetic Layout Person {i}", f"ACCL-{i:04d}", f"SYNTH-CODE-{i:02d}_with_a_long_descriptive_folder_name_for_layout_testing"[:32]])
wb.save(KEY)
s_ = socket.socket(); s_.bind(("127.0.0.1", 0)); port = s_.getsockname()[1]; s_.close(); U = f"http://127.0.0.1:{port}"
app = subprocess.Popen([PY, os.path.join(ROOT, "app", "css_app.py"), "--port", str(port), "--no-window"], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
                       env=dict(os.environ, HOME=HOME, CSS_BASE=B, CSS_EXPERIMENTAL="1", PYTHONPATH=os.path.join(ROOT, "app", "guard"),
                                CSS_PROTECTED_PATHS=":".join([os.path.expanduser("~/css_project"), os.path.expanduser("~/cSS_experimental")])))
try:
    for _ in range(80):
        try: urllib.request.urlopen(U + "/api/state", timeout=2); break
        except Exception: time.sleep(0.25)
    url = f"{U}/#add?folder=" + urllib.parse.quote(LONG, safe="") + "&folder_is=code&mode=incognito&cohort=LAYOUT&go=1&manifest=" + urllib.parse.quote(KEY, safe="")
    for w in (1280, 1500):
        for attempt in range(1, 4):         # the preview waits for the server's plan (real time); under load the first dump can be too early
            D = subprocess.run([chrome, "--headless=new", "--disable-gpu", f"--user-data-dir={os.path.join(T, f'chrome{w}_{attempt}')}", f"--window-size={w},1100", "--virtual-time-budget=25000",
                                "--dump-dom", url], capture_output=True, text=True, timeout=240).stdout
            rows = len(re.findall(r'<tr data-iwe="', D))
            if rows: break
        print(f"INFO  {w} px: preview rendered on attempt {attempt}")
        check(f"{w} px: one row per examination", rows == 6, f"{rows} rows")
        m = re.search(r'data-iw="preview"[^>]*data-overflow="(\w+)"', D) or re.search(r'data-overflow="(\w+)"[^>]*data-iw="preview"', D)
        check(f"{w} px: no horizontal scrolling in the preview", bool(m) and m.group(1) == "no", m.group(1) if m else "not measured")
        cb = re.search(r'data-clipped="(\w+)"', D)
        check(f"{w} px: no control clipped inside its cell", bool(cb) and cb.group(1) == "no", (cb.group(1) if cb else "not measured") + " " + ";".join(re.findall(r'data-clipwhat="([^"]*)"', D)))
        check(f"{w} px: codes taken from the folder names", D.count('value="SYNTH-CODE-0') == 6)
        check(f"{w} px: Incognito: icon in the Patient column, no name / MRN / accession shown", 'data-id="incog"' in D and "Synthetic Layout Person" not in D and "9100000" not in D and "ACCL-" not in D)
        if SHOTS:
            os.makedirs(SHOTS, exist_ok=True)
            subprocess.run([chrome, "--headless=new", "--disable-gpu", f"--user-data-dir={os.path.join(T, f'chromes{w}')}", "--hide-scrollbars", f"--window-size={w},1100",
                            "--virtual-time-budget=15000", f"--screenshot={os.path.join(SHOTS, f'add_preview_{w}px.png')}", url], capture_output=True, timeout=180)
finally:
    app.terminate(); app.wait(timeout=20)
shutil.rmtree(T, ignore_errors=True)
print(("ALL PASS" if not F else f"{len(F)} FAILED: {F}") + f" ({__file__})"); sys.exit(1 if F else 0)
