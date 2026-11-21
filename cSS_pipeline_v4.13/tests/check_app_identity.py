"""check_app_identity.py - v5.16 identification through the real app (SYNTHETIC data, write guard on, simulated pipeline runs):
default Incognito without a vault (existing studies keep working); template download (4 columns in order); vault set-up copies legacy
names; Standard mode shows names / MRN / accession and flags a missing accession (re-processing and export refused until entered);
audited accession / MRN / name / code edits keep uuids, file keys and the existing review; guided Standard import with a two-examination
patient; re-import recognised; Incognito import with the key (codes from the folder names; kept after a restart); mode switch; Incognito: no MRN /
name / accession / source path in any API response, the GUI, log views or exports; restart: vault locked, wrong passphrase refused;
no identifier in the registry, patients.json or the logs.
usage: python tests/check_app_identity.py [--shots DIR]   (exit 1 on any FAIL)"""
import glob, io, json, os, shutil, socket, subprocess, sys, tempfile, time, urllib.error, urllib.request
import numpy as np, nibabel as nib, pandas as pd
H = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(H); PY = sys.executable
sys.path.insert(0, os.path.join(ROOT, "app")); import manifest as MF   # noqa: E402
F = []
def check(n, ok, info=""): print(f"{'PASS' if ok else 'FAIL'}  {n}  {info}"); (None if ok else F.append(n))
SHOTS = sys.argv[sys.argv.index("--shots") + 1] if "--shots" in sys.argv else None
PW = "synthetic test passphrase 42"
SECRETS = ["Alpha Synthperson", "Beta Synthperson", "77100001", "ACCI-0001", "Legacy Personname", "Johnathan Smithfield", "Maryanne Jonesworth", "55177301", "88204612", "ACCX-0001", "ACCX-0002", "ACCX-0003", "ACCX-0900"]

T = tempfile.mkdtemp(prefix="ident_app_"); HOME = os.path.join(T, "home"); B = os.path.join(HOME, "syn_project"); SRC = os.path.join(T, "incoming_55177301_src")
for d in ("app_data", "private", "review"): os.makedirs(os.path.join(B, d))
with open(os.path.join(B, "private", "names.csv"), "w") as f: f.write("code,name\nP001,Legacy Personname\n")
pats = [dict(code="P001", cohort="C1", status="done", fingerprint="", series={}, steps_done={}, added=0, mode="semi", anatomy="synthseg", pathway="synthseg")]   # no grade fields: like a linked study
with open(os.path.join(B, "app_data", "patients.json"), "w") as f: json.dump(pats, f)
cand = pd.DataFrame(dict(cand_id=[1, 2], vox_i=[10, 20], vox_j=[10, 20], vox_k=[5, 6], volume_mm3=[30.0, 40.0])); cand.to_csv(os.path.join(B, "review", "P001_candidates.csv"), index=False)
open(os.path.join(B, "review", "P001_candidates.nii.gz"), "w").close()
pd.DataFrame([dict(cand_id=c, call="cSS", comment="", reviewer="Dr A", time="2026-01-01 10:00:00", **cand.set_index("cand_id").loc[c].to_dict()) for c in (1, 2)]).to_csv(
    os.path.join(B, "review", "P001_calls_Dr_A.csv"), index=False)
with open(os.path.join(B, "review", "P001_final_Dr_A.json"), "w") as f: json.dump(dict(reviewer="Dr A", saved="2026-01-01 10:05:00"), f)
def swi(folder, seed):
    os.makedirs(folder, exist_ok=True); rng = np.random.default_rng(seed); v = np.zeros((48, 48, 20), np.int16); v[8:40, 8:40, 4:16] = rng.integers(200, 900, (32, 32, 12))
    nib.save(nib.Nifti1Image(v, np.diag([0.8, 0.8, 1.2, 1])), os.path.join(folder, "SWI_Johnathan_Smithfield.nii"))
    with open(os.path.join(folder, "SWI_Johnathan_Smithfield.json"), "w") as f: json.dump(dict(SeriesDescription="SWI", ImageType=["ORIGINAL", "PRIMARY", "M", "SWI"]), f)
swi(os.path.join(SRC, "55177301", "EXAM_A"), 1); swi(os.path.join(SRC, "55177301", "EXAM_B"), 2); swi(os.path.join(SRC, "88204612"), 3)
INC = os.path.join(T, "incognito_src"); swi(os.path.join(INC, "PT-ALPHA"), 11); swi(os.path.join(INC, "PT-BETA"), 12)
man = os.path.join(T, "manifest.xlsx")
with open(man, "wb") as f: f.write(MF.template_bytes(example=False))
from openpyxl import load_workbook
wb = load_workbook(man); ws = wb["examinations"]
for r in (("55177301", "Johnathan Smithfield", "ACCX-0001", "EXAM_A"), ("55177301", "Johnathan Smithfield", "ACCX-0002", "EXAM_B"), ("88204612", "Maryanne Jonesworth", "ACCX-0003", "")): ws.append(list(r))
wb.save(man)
inc_key = os.path.join(T, "inc_key.xlsx")
with open(inc_key, "wb") as f: f.write(MF.template_bytes(example=False))
wb = load_workbook(inc_key); ws = wb["examinations"]
for r in (("77100001", "Alpha Synthperson", "ACCI-0001", "PT-ALPHA"), ("77100002", "Beta Synthperson", "ACCI-0002", "PT-BETA")): ws.append(list(r))
wb.save(inc_key)

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
def start():
    port = free_port(); env = dict(os.environ, HOME=HOME, CSS_BASE=B, CSS_EXPERIMENTAL="1", CSS_APP_FAKE_RUN="1", CSS_APP_FAKE_STEP_S="0.05", PYTHONPATH=os.path.join(ROOT, "app", "guard"),
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
def post(U, path, d):
    rq = urllib.request.Request(U + path, data=json.dumps(d).encode(), headers={"Content-Type": "application/json", "X-CSS-App": "1"})
    return json.load(urllib.request.urlopen(rq, timeout=300))
def res(U): return {r["code"]: r for r in get(U, "/api/results")}
def leaks(text): return [s for s in SECRETS + [SRC] if s in text]
def wait_done(U, codes, limit=60):
    t0 = time.time()
    while time.time() - t0 < limit:
        st = {p["code"]: p["status"] for p in get(U, "/api/state")["patients"]}
        if all(st.get(c) == "done" for c in codes): return True
        time.sleep(0.3)
    return False
chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
def dom(U, url): return subprocess.run([chrome, "--headless=new", "--disable-gpu", f"--user-data-dir={os.path.join(T, 'chrome')}", "--virtual-time-budget=9000", "--dump-dom", f"{U}/{url}"],
                                       capture_output=True, text=True, timeout=120).stdout if os.path.exists(chrome) else ""
def shot(U, name, url, h=1300):
    if SHOTS and os.path.exists(chrome):
        os.makedirs(SHOTS, exist_ok=True)
        subprocess.run([chrome, "--headless=new", "--disable-gpu", f"--user-data-dir={os.path.join(T, 'chrome')}", "--hide-scrollbars", f"--window-size=1500,{h}", "--virtual-time-budget=9000",
                        f"--screenshot={os.path.join(SHOTS, name + '.png')}", f"{U}/{url}"], capture_output=True, timeout=120)

app, U = start()
try:
    st = get(U, "/api/id/state")
    check("no vault yet -> Incognito by default; existing study registered", st["mode"] == "incognito" and not st["vault_exists"] and st["n_studies"] == 1)
    r1 = res(U)["P001"]
    check("Incognito without vault: legacy name not shown; study id = its code", r1["ident"]["study_id"] == "P001" and not leaks(json.dumps(r1)))
    tb = raw(U, "/api/id/template.xlsx")
    if tb[:2] != b"PK": print("DIAG template response was not an xlsx:", tb[:300])      # intermittent failure seen once (2026-11-20): keep the evidence
    xl = pd.read_excel(io.BytesIO(tb), dtype=str) if tb[:2] == b"PK" else pd.DataFrame()
    check("template: the four columns in order (+ v5.18 optional columns after them), example rows", list(xl.columns)[:4] == MF.COLUMNS and list(xl.columns)[4:] == MF.OPTIONAL and len(xl) == 3)
    check("vault: short passphrase refused", post(U, "/api/id/vault/create", dict(passphrase="short")).get("ok") is False)
    r = post(U, "/api/id/vault/create", dict(passphrase=PW)); check("vault created; legacy names copied in", r.get("ok") and r["names_copied"] == 1)
    check("names.csv unchanged", open(os.path.join(B, "private", "names.csv")).read() == "code,name\nP001,Legacy Personname\n")
    r = post(U, "/api/id/mode", dict(mode="standard")); check("Standard mode (vault unlocked this session)", r.get("ok") and r["unlocked"])
    r1 = res(U)["P001"]
    check("Standard: legacy name shown, accession missing flagged", r1["name"] == "Legacy Personname" and r1["ident"]["accession_missing"] is True)
    check("Standard: re-processing refused without accession", "accession" in post(U, "/api/control", dict(code="P001", action="rerun")).get("error", ""))
    check("Standard: export refused without accession", b"accession" in raw(U, "/api/export.xlsx"))
    r = post(U, "/api/id/edit", dict(code="P001", accession="ACCX-0900", reason="enter accession"))
    check("sensitive edit needs confirmation", r.get("needs_confirm") is True)
    uu = get(U, "/api/id/study?code=P001")["study_uuid"]
    r = post(U, "/api/id/edit", dict(code="P001", accession="ACCX-0900", reason="enter accession", confirm=True, by="tester"))
    check("accession entered", r.get("ok") and res(U)["P001"]["ident"]["study_id"] == "ACCX-0900" and not res(U)["P001"]["ident"]["accession_missing"])
    post(U, "/api/id/edit", dict(code="P001", deid_code="SYNCODE-1", display_name="Brain MRI - SWI", reason="rename", by="tester"))
    v = get(U, "/api/id/study?code=P001")
    check("uuid and file key unchanged after edits", v["study_uuid"] == uu and v["file_key"] == "P001" and v["deid_code"] == "SYNCODE-1")
    check("existing review still linked after edits", res(U)["P001"].get("review_state") == "reviewed")
    h = get(U, "/api/id/history?code=P001")["history"]
    check("audit history (Standard, unlocked): accession old -> new with reason", any(x["field"] == "accession" and x["new"] == "ACCX-0900" and x["reason"] == "enter accession" for x in h))
    check("Standard export allowed once every study has an accession", raw(U, "/api/export.xlsx")[:2] == b"PK")
    # guided Standard import (two examinations of one patient)
    pv = post(U, "/api/id/import/plan", dict(folder=SRC, folder_is="mrn", mode="standard", manifest=man, processing=dict(cohort="C2")))
    check("Standard plan: 2 patients, 3 examinations, all matched, valid", len(pv["patients"]) == 2 and pv["n_exams"] == 3 and pv["ok"], str(pv.get("errors"))[:300])
    check("Standard preview shows accession numbers", sorted(e["accession"] for e in pv["exams"]) == ["ACCX-0001", "ACCX-0002", "ACCX-0003"])
    check("commit without confirmation refused", post(U, "/api/id/import/commit", dict(plan=pv["id"])).get("needs_confirm") is True)
    cm = post(U, "/api/id/import/commit", dict(plan=pv["id"], confirm=True, cohort="C2", by="tester"))
    keys = [x["file_key"] for x in cm.get("imported", [])]
    check("imported and queued under opaque file keys", cm.get("ok") and len(keys) == 3 and all(k.startswith("EXAM_") or k.startswith("PCV-") for k in keys) and wait_done(U, keys), str(keys))
    R = res(U)
    check("one patient with two examinations", sorted(R[k]["ident"]["n_exams_of_patient"] for k in keys) == [1, 2, 2]
          and {R[k]["ident"]["mrn"] for k in keys} == {"55177301", "88204612"})
    pv2 = post(U, "/api/id/import/plan", dict(folder=SRC, folder_is="mrn", mode="standard", manifest=man, processing=dict(cohort="C2")))
    check("re-import: every examination recognised and left out", all(not e["include"] and e["duplicate"]["kind"] == "same_exam" for e in pv2["exams"]) and not pv2["ok"])
    shot(U, "studies_standard", "#studies"); shot(U, "import_preview_standard", "#import")
    D = dom(U, "#studies")
    check("browser Standard: names / MRN / accession on the Studies screen", "Johnathan Smithfield" in D and "ACCX-0001" in D and 'data-id="mode"' in D)
    gen = [x["deid_code"] for x in cm["imported"] if x["generated"]]
    check("Standard import: the blank Excel code was generated (unique PCV code, usable in Incognito)", len(gen) == 1 and gen[0].startswith("PCV-"))
    # Incognito import: the key is required; v5.18 fix - code folder names become the study codes (they were replaced by generated codes)
    pi0 = post(U, "/api/id/import/plan", dict(folder=INC, folder_is="deid", mode="incognito", generate_codes=True))
    check("Incognito import without the key refused", pi0.get("ok") is False and "key" in pi0.get("error", ""))
    pi = post(U, "/api/id/import/plan", dict(folder=INC, folder_is="code", mode="incognito", manifest=inc_key, processing=dict(cohort="C3")))
    check("Incognito plan valid; codes taken from the folder names", pi["ok"] and sorted(e["code"] for e in pi["exams"]) == ["PT-ALPHA", "PT-BETA"], str(pi.get("errors"))[:300])
    ci = post(U, "/api/id/import/commit", dict(plan=pi["id"], confirm=True, cohort="C3", by="tester"))
    gen += [x["deid_code"] for x in ci["imported"]]
    check("Incognito import committed under the folder codes", sorted(x["deid_code"] for x in ci["imported"]) == ["PT-ALPHA", "PT-BETA"] and wait_done(U, [x["file_key"] for x in ci["imported"]]))
    # Incognito
    r = post(U, "/api/id/mode", dict(mode="incognito")); check("switch to Incognito locks the vault", r.get("ok") and not r["unlocked"])
    bodies = []
    for path in ("/api/state", "/api/results", "/api/id/state", "/api/id/study?code=P001", "/api/id/history?code=P001", "/api/calls/policy", "/api/fsqc/state", "/api/proc/studies",
                 "/api/se/state", "/api/im/state", "/api/u/state", f"/api/log?code={keys[0]}", "/api/export.xlsx"):
        b = raw(U, path)
        try: bodies.append((path, b.decode("utf-8", "replace") if path != "/api/export.xlsx" else pd.read_excel(io.BytesIO(b), sheet_name=None).__repr__()))
        except Exception as e: bodies.append((path, f"<{type(e).__name__}>"))
    bad = [(p_, leaks(t)) for p_, t in bodies if leaks(t)]
    check("Incognito: no MRN / name / accession / source path in any API response or export", not bad, str(bad)[:300])
    R = res(U)
    check("Incognito: study ids are de-identified codes", R["P001"]["ident"]["study_id"] == "SYNCODE-1" and all(R[k]["ident"]["id_kind"] == "de-identified study code" for k in keys))
    D = dom(U, "#studies") + dom(U, "#act") + dom(U, "#uni") + dom(U, "#qc") + dom(U, "#shadow")
    check("Incognito GUI screens show no identifiers", D and not leaks(D), str(leaks(D)))
    shot(U, "studies_incognito", "#studies")
    pv3 = post(U, "/api/id/import/plan", dict(folder=SRC, folder_is="mrn", mode="incognito", manifest=man))
    check("Incognito import preview: no identifiers, no folder names", not leaks(json.dumps(pv3)), str(leaks(json.dumps(pv3))))
    check("Incognito: sensitive edit refused", post(U, "/api/id/edit", dict(code="P001", accession="X", confirm=True)).get("ok") is False)
finally:
    app.terminate(); app.wait(timeout=20)
app, U = start()
try:
    st = get(U, "/api/id/state"); check("restart: mode persists (Incognito), vault locked", st["mode"] == "incognito" and not st["unlocked"])
    check("generated codes kept after the restart", set(gen) <= {r["ident"]["deid_code"] for r in res(U).values()})
    r = post(U, "/api/id/mode", dict(mode="standard")); check("Standard needs the passphrase", r.get("needs_passphrase") is True)
    check("wrong passphrase refused", post(U, "/api/id/mode", dict(mode="standard", passphrase="wrong wrong wrong")).get("ok") is False)
    check("correct passphrase: identities back", post(U, "/api/id/mode", dict(mode="standard", passphrase=PW)).get("ok") and res(U)["P001"]["name"] == "Legacy Personname")
    shot(U, "edit_identifiers", "#studies")
finally:
    app.terminate(); app.wait(timeout=20)
files = [os.path.join(B, "app_data", "identity", "registry.json")] + glob.glob(os.path.join(B, "app_data", "logs", "*")) + glob.glob(os.path.join(B, "logs", "*"))
with open(os.path.join(B, "app_data", "patients.json")) as f: wiz = [p for p in json.load(f) if p["code"] != "P001"]
txt0 = json.dumps(wiz)                                     # studies imported by the wizard (the legacy record has no source paths)
txt = txt0 + "".join(open(f, errors="replace").read() for f in files if os.path.isfile(f))
check("no MRN / name / accession / source path in the registry, patients.json or logs", not leaks(txt), str(leaks(txt)))
check("imported series copied under neutral names", glob.glob(os.path.join(B, "app_data", "import_src", "*", "SWI_series.nii")) and not glob.glob(os.path.join(B, "app_data", "import_src", "**", "*Smithfield*"), recursive=True))
check("staged series use neutral names (no patient name in file names)", not glob.glob(os.path.join(B, "app_data", "staging", "*", "*", "*Smithfield*")))
with open(os.path.join(B, "private", "identity_vault.enc"), "rb") as f: vb = f.read()
check("vault encrypted at rest", not any(s.encode() in vb for s in SECRETS))
shutil.rmtree(T, ignore_errors=True)
print(("ALL PASS" if not F else f"{len(F)} FAILED: {F}") + f" ({__file__})"); sys.exit(1 if F else 0)
