"""check_app_batch_layout.py - v5.17 batch Add-studies layout through the real app + headless Chrome (SYNTHETIC folders): a very long folder
path and six patient folders with long names and long series file names are scanned; the table must not overflow horizontally at 1280 and
1500 px window widths, show one row per patient, the full path readably (wrapped) and short series labels with the full path as tooltip.
usage: python tests/check_app_batch_layout.py [--shots DIR]   (exit 1 on any FAIL)"""
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
    d = os.path.join(LONG, f"SYNTH_PATIENT_{i:02d}_with_a_long_descriptive_folder_name_for_layout_testing")
    for sub, desc in (("SWI_magnitude_series_high_resolution_axial_3D", "SWI"), ("T1_MPRAGE_sagittal_isotropic_1mm_series", "T1 MPRAGE")):
        os.makedirs(os.path.join(d, sub)); f = os.path.join(d, sub, f"{sub}_reconstruction_number_0001_of_the_examination.nii")
        nib.save(nib.Nifti1Image(np.zeros((32, 32, 16), np.int16) + i, np.diag([0.8, 0.8, 1.2, 1])), f)
        with open(f[:-4] + ".json", "w") as fh: json.dump(dict(SeriesDescription=desc, ImageType=["ORIGINAL", "PRIMARY", "M"] + (["SWI"] if desc == "SWI" else [])), fh)
s_ = socket.socket(); s_.bind(("127.0.0.1", 0)); port = s_.getsockname()[1]; s_.close(); U = f"http://127.0.0.1:{port}"
app = subprocess.Popen([PY, os.path.join(ROOT, "app", "css_app.py"), "--port", str(port), "--no-window"], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
                       env=dict(os.environ, HOME=HOME, CSS_BASE=B, CSS_EXPERIMENTAL="1", PYTHONPATH=os.path.join(ROOT, "app", "guard"),
                                CSS_PROTECTED_PATHS=":".join([os.path.expanduser("~/css_project"), os.path.expanduser("~/cSS_experimental")])))
try:
    for _ in range(80):
        try: urllib.request.urlopen(U + "/api/state", timeout=2); break
        except Exception: time.sleep(0.25)
    url = f"{U}/#add?folder=" + urllib.parse.quote(LONG, safe="")
    for w in (1280, 1500):
        D = subprocess.run([chrome, "--headless=new", "--disable-gpu", f"--user-data-dir={os.path.join(T, f'chrome{w}')}", f"--window-size={w},1100", "--virtual-time-budget=15000",
                            "--dump-dom", url], capture_output=True, text=True, timeout=180).stdout
        rows = len(re.findall(r'<tr data-i="\d+"', D))
        check(f"{w} px: one row per patient folder", rows == 6, f"{rows} rows")
        m = re.search(r'id="tbl"[^>]*data-overflow="(\w+)"', D) or re.search(r'data-overflow="(\w+)"[^>]*id="tbl"', D)
        check(f"{w} px: no horizontal scrolling in the study table", bool(m) and m.group(1) == "no", m.group(1) if m else "not measured")
        cb = re.search(r'id="tbl"[^>]*data-clipped="(\w+)"', D) or re.search(r'data-clipped="(\w+)"[^>]*id="tbl"', D)
        check(f"{w} px: no control clipped inside its cell (Include checkbox, selects)", bool(cb) and cb.group(1) == "no", (cb.group(1) if cb else "not measured") + " " + ";".join(re.findall(r'data-clipwhat="([^"]*)"', D)))
        check(f"{w} px: full folder path shown, wrapped by segment", 'data-add="path"' in D and "Cerebral_Amyloid_Angiopathy_cohort_SWI_and_T1_series" in D)
        check(f"{w} px: series labels shortened, full path kept in the tooltip", "…" in D and "SWI_magnitude_series_high_resolution_axial_3D/" in D)
        if SHOTS:
            os.makedirs(SHOTS, exist_ok=True)
            subprocess.run([chrome, "--headless=new", "--disable-gpu", f"--user-data-dir={os.path.join(T, f'chromes{w}')}", "--hide-scrollbars", f"--window-size={w},1100",
                            "--virtual-time-budget=15000", f"--screenshot={os.path.join(SHOTS, f'batch_add_{w}px.png')}", url], capture_output=True, timeout=180)
finally:
    app.terminate(); app.wait(timeout=20)
shutil.rmtree(T, ignore_errors=True)
print(("ALL PASS" if not F else f"{len(F)} FAILED: {F}") + f" ({__file__})"); sys.exit(1 if F else 0)
