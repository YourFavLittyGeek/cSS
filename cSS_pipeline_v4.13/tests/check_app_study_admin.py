"""check_app_study_admin.py - v5.20 study administration through the real app (SYNTHETIC data; write guard on; simulated runs; the Trash
is a temporary folder via CSS_TRASH_DIR - the real Trash is never touched). Covers:
  identifier rule  Standard: accession on the Activity / panel screens, code hidden except on Studies; Incognito: code everywhere;
                   notifications carry the internal key but are shown with the mode's identifier
  study panel      Standard: MRN first, cohort, accession, code (small), this patient's examinations; Incognito: code only
  edit             checkpoint before saving (duplicate accession / code / MRN of another patient refused, NOTHING changed - all-or-nothing);
                   valid edit applied everywhere (Studies, registry, library folder renamed); audit kept; bulk cohort edit
  archive          hidden from Studies / Activity, listed on the Archive screen, restored unchanged; cohort archive; training setting
  remove / purge   preview; typed confirmation; Remove keeps results / calls under a new RET identifier (accession and code released,
                   images + library copy to the Trash); Purge moves everything to the Trash and frees the identifiers; re-import allowed
  import duplicates same accession, different images: skip / replace (REPLACE typed, old purged) / keep the old for ML (old retired)
  previous version  projects found on this Mac; bring in all processed studies; an import of an examination processed in the previous
                   version reuses its results (not processed again)
usage: python tests/check_app_study_admin.py [--shots DIR]   (exit 1 on any FAIL)"""
import glob, hashlib, json, os, re, shutil, socket, subprocess, sys, tempfile, time, urllib.error, urllib.parse, urllib.request
import numpy as np, nibabel as nib
H = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(H); PY = sys.executable
sys.path.insert(0, os.path.join(ROOT, "app")); import manifest as MF, series_detect as SD   # noqa: E402
F = []
def check(n, ok, info=""): print(f"{'PASS' if ok else 'FAIL'}  {n}  {info}"); (None if ok else F.append(n))
SHOTS = sys.argv[sys.argv.index("--shots") + 1] if "--shots" in sys.argv else None
PW = "synthetic passphrase 520"
T = tempfile.mkdtemp(prefix="sa520_"); HOME = os.path.join(T, "home"); B = os.path.join(HOME, "syn_project"); TRASH = os.path.join(T, "trash")
for d in ("app_data", "private", "review"): os.makedirs(os.path.join(B, d))
LIB = os.path.join(T, "library"); os.makedirs(LIB); SRC = os.path.join(T, "incoming")


def nii(path, shape, vox, seed, desc, itype):
    os.makedirs(os.path.dirname(path), exist_ok=True); v = np.random.default_rng(seed).integers(50, 900, shape).astype(np.int16)
    nib.save(nib.Nifti1Image(v, np.diag(list(vox) + [1])), path)
    with open(path.replace(".nii", ".json"), "w") as f: json.dump(dict(SeriesDescription=desc, ImageType=itype), f)
def exam(folder, seed):
    nii(os.path.join(folder, "swi.nii"), (40, 40, 16), (0.8, 0.8, 1.2), seed, "SWI_Images", ["ORIGINAL", "PRIMARY", "M", "SWI"])
def xlsx(path, rows):
    from openpyxl import load_workbook
    with open(path, "wb") as f: f.write(MF.template_bytes(example=False))
    wb = load_workbook(path); ws = wb["examinations"]
    for r in rows: ws.append(list(r))
    wb.save(path)
NAMES = ["Alphonse Synthetica", "Beatrix Synthetica"]; MRN = ["71000001", "72000002"]
exam(os.path.join(SRC, "a", MRN[0], "ACCS-001"), 1); exam(os.path.join(SRC, "a", MRN[0], "ACCS-002"), 2); exam(os.path.join(SRC, "a", MRN[1], "ACCS-003"), 3)
XA = os.path.join(T, "a.xlsx"); xlsx(XA, [(MRN[0], NAMES[0], "ACCS-001", "SYN-A1"), (MRN[0], NAMES[0], "ACCS-002", "SYN-A2"), (MRN[1], NAMES[1], "ACCS-003", "SYN-A3")])
# a NEW examination that re-uses accession ACCS-003 (different images) -> duplicate choices
exam(os.path.join(SRC, "dup", MRN[1], "ACCS-003"), 33)
# previous Percival version (~/cSS_experimental): one processed study OLD01 whose SWI is the same examination as SRC/prev/<MRN>/ACCS-090
PREV = os.path.join(HOME, "cSS_experimental"); exam(os.path.join(SRC, "prev", MRN[1], "ACCS-090"), 90)
os.makedirs(os.path.join(PREV, "data")); shutil.copy(os.path.join(SRC, "prev", MRN[1], "ACCS-090", "swi.nii"), os.path.join(PREV, "data", "OLD01_swi.nii"))
for k, code in enumerate(("OLD01", "OLD02")):
    if code == "OLD02": nii(os.path.join(PREV, "data", "OLD02_swi.nii"), (40, 40, 16), (0.8, 0.8, 1.2), 91, "SWI", ["SWI"])
    os.makedirs(os.path.join(PREV, "review"), exist_ok=True)
    open(os.path.join(PREV, "review", f"{code}_candidates.csv"), "w").write("cand_id,vox_i,vox_j,vox_k\n1,1,2,3\n")
    open(os.path.join(PREV, "review", f"{code}_calls.csv"), "w").write("cand_id,call\n1,cSS\n")
os.makedirs(os.path.join(PREV, "app_data")); json.dump([dict(code="OLD01", fingerprint=SD.content_fingerprint(os.path.join(PREV, "data", "OLD01_swi.nii")), status="done"),
                                                       dict(code="OLD02", fingerprint="c2:other", status="done")], open(os.path.join(PREV, "app_data", "patients.json"), "w"))
XP = os.path.join(T, "prev.xlsx"); xlsx(XP, [(MRN[1], NAMES[1], "ACCS-090", "SYN-P1")])
PREV_HASH = {p: hashlib.sha256(open(p, "rb").read()).hexdigest() for p in glob.glob(PREV + "/**/*", recursive=True) if os.path.isfile(p)}


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
def start():
    port = free_port(); env = dict(os.environ, HOME=HOME, CSS_BASE=B, CSS_EXPERIMENTAL="1", CSS_APP_FAKE_RUN="1", CSS_APP_FAKE_STEP_S="0.03", CSS_TRASH_DIR=TRASH,
                                   PYTHONPATH=os.path.join(ROOT, "app", "guard"), CSS_PROTECTED_PATHS=":".join([os.path.expanduser("~/css_project"), os.path.expanduser("~/cSS_experimental"), os.path.expanduser("~/Projects/cSS")]))
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
def wait(cond, limit=60):
    t0 = time.time()
    while time.time() - t0 < limit:
        if cond(): return True
        time.sleep(0.3)
    return False
def pats(U): return {p["code"]: p for p in get(U, "/api/state")["patients"]}
def done(U, codes): return wait(lambda: all(pats(U).get(c, {}).get("status") == "done" for c in codes))
chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
def dom(U, url):
    if not os.path.exists(chrome): return ""
    D = subprocess.run([chrome, "--headless=new", "--disable-gpu", f"--user-data-dir={os.path.join(T, 'chrome')}", "--virtual-time-budget=12000", "--dump-dom", f"{U}/{url}"],
                       capture_output=True, text=True, timeout=120).stdout
    return re.sub(r"<script\b[^>]*>.*?</script>", "", D, flags=re.S)
def shot(U, name, url, h=1300):
    if SHOTS and os.path.exists(chrome):
        os.makedirs(SHOTS, exist_ok=True)
        subprocess.run([chrome, "--headless=new", "--disable-gpu", f"--user-data-dir={os.path.join(T, 'chrome')}", "--hide-scrollbars", f"--window-size=1500,{h}", "--virtual-time-budget=12000",
                        f"--screenshot={os.path.join(SHOTS, name + '.png')}", f"{U}/{url}"], capture_output=True, timeout=120)
def plan(U, folder, x, mode="standard"):
    return post(U, "/api/id/import/plan", dict(folder=folder, folder_is="mrn", sub_is="accession", mode=mode, manifest=x, library=dict(enabled=True, root=LIB), processing=dict(cohort="C520")))
def commit(U, pl, **kw): return post(U, "/api/id/import/commit", dict(plan=pl["id"], confirm=True, cohort="C520", by="tester", **kw))
def libjob(U, r):
    if r.get("library_job"): wait(lambda: get(U, f"/api/id/library/job?id={r['library_job']}").get("state") == "finished", 60)

app, U = start()
try:
    post(U, "/api/id/vault/create", dict(passphrase=PW)); post(U, "/api/id/mode", dict(mode="standard", passphrase=PW))
    pa = plan(U, os.path.join(SRC, "a"), XA); ca = commit(U, pa); keys = {x["deid_code"]: x["file_key"] for x in ca.get("imported", [])}
    check("setup: three synthetic examinations imported and processed (simulated)", ca.get("ok") and len(keys) == 3 and done(U, list(keys.values())), str(pa.get("errors"))[:300])
    libjob(U, ca)
    A1, A2, A3 = keys["SYN-A1"], keys["SYN-A2"], keys["SYN-A3"]
    for c in (A1, A2, A3):
        open(os.path.join(B, "review", f"{c}_candidates.csv"), "w").write("cand_id,vox_i,vox_j,vox_k\n1,1,2,3\n")
        open(os.path.join(B, "review", f"{c}_calls_Dr_Q.csv"), "w").write(f"cand_id,call,study\n1,cSS,{c}\n")
        os.makedirs(os.path.join(B, "work"), exist_ok=True); nii(os.path.join(B, "work", f"{c}_brainmask.nii"), (6, 6, 6), (1, 1, 1), 5, "m", ["D"])
    # ------------------------------------------------------------------ identifier rule
    D = re.sub(r"<[^>]+>", " ", dom(U, "#act"))      # visible text only (internal keys in attributes are not shown)
    check("Activity (Standard): studies named by accession number, code hidden", "ACCS-001" in D and "SYN-A1" not in D, str([D[max(0, m.start() - 120):m.end() + 40] for m in re.finditer("SYN-A1", D)][:2]))
    D = dom(U, f"#studies?open={A1}")
    check("study panel (Standard): MRN first, cohort, accession, code shown small", 'data-id="sh-mrn"' in D and f"MRN <span class=\"mono\">{MRN[0]}</span>" in D and "C520" in D and "SYN-A1" in D)
    check("study panel: this patient's examinations listed", 'data-id="sh-exams"' in D and D.count('data-shx="') == 2)
    shot(U, "v520_panel_standard", f"#studies?open={A1}")
    # ------------------------------------------------------------------ edit + checkpoint
    r = post(U, "/api/sa/edit", dict(code=A1, fields=dict(accession="ACCS-003"), confirm=True))
    check("checkpoint: duplicate accession refused", r.get("ok") is False and "already belongs" in r.get("error", ""), str(r))
    r = post(U, "/api/sa/edit", dict(code=A1, fields=dict(deid_code="SYN-A3"), confirm=True))
    check("checkpoint: duplicate code refused", r.get("ok") is False and "already used" in r.get("error", ""), str(r))
    r = post(U, "/api/sa/edit", dict(code=A1, fields=dict(mrn=MRN[1]), confirm=True))
    check("checkpoint: MRN of another patient refused (never merged)", r.get("ok") is False and "another patient" in r.get("error", ""), str(r))
    r = post(U, "/api/sa/edit", dict(code=A1, fields=dict(mrn="79999999", accession="ACCS-003"), confirm=True))
    v = get(U, f"/api/id/study?code={A1}")
    check("all-or-nothing: a refused combined edit changes nothing (MRN unchanged)", r.get("ok") is False and v["mrn"] == MRN[0] and v["accession"] == "ACCS-001")
    r = post(U, "/api/sa/edit", dict(code=A1, fields=dict(accession="ACCS-001X", display_name="Brain MRI", cohort="C520B"), confirm=True, reason="typo"))
    v = get(U, f"/api/id/study?code={A1}")
    check("valid edit saved everywhere (identity + cohort)", r.get("ok") and v["accession"] == "ACCS-001X" and v["display_name"] == "Brain MRI" and pats(U)[A1]["cohort"] == "C520B", str(r))
    check("study library folder renamed to the new accession", os.path.isdir(os.path.join(LIB, MRN[0], "ACCS-001X")) and not os.path.exists(os.path.join(LIB, MRN[0], "ACCS-001")), r.get("library", ""))
    h = get(U, f"/api/id/history?code={A1}")["history"]
    check("edit audited with its reason", any(x.get("field") == "accession" and x.get("new") == "ACCS-001X" and x.get("reason") == "typo" for x in h))
    r = post(U, "/api/sa/bulk", dict(codes=[A2, A3], fields=dict(cohort="C520B"), confirm=True))
    check("bulk edit: cohort of several studies", r.get("ok") and pats(U)[A2]["cohort"] == "C520B" and pats(U)[A3]["cohort"] == "C520B")
    # ------------------------------------------------------------------ archive
    r = post(U, "/api/sa/archive", dict(codes=[A2], on=True))
    D = dom(U, "#studies?grp=none")
    check("archived: hidden from Studies", r.get("ok") and f'data-st="{A2}"' not in D and f'data-st="{A1}"' in D)
    D = dom(U, "#archive")
    check("Archive screen lists the archived study", 'data-id="archive-list"' in D and "ACCS-002" in D)
    shot(U, "v520_archive", "#archive")
    r = post(U, "/api/id/import/plan", dict(folder=os.path.join(SRC, "a"), folder_is="mrn", sub_is="accession", mode="standard", manifest=XA, processing=dict(cohort="C520")))
    check("archived identifiers stay reserved (re-import of it recognised)", any(e["duplicate"]["kind"] == "same_exam" for e in r["exams"]))
    r = post(U, "/api/sa/archive", dict(codes=[A2], on=False))
    check("restored unchanged", r.get("ok") and not pats(U)[A2].get("archived") and f'data-st="{A2}"' in dom(U, "#studies?grp=none"))
    # ------------------------------------------------------------------ remove (keep for ML)
    pr = post(U, "/api/sa/plan_remove", dict(codes=[A2], mode="remove"))
    st = pr["studies"][0]
    check("Remove preview: files to the Trash and result files kept, with sizes", pr.get("ok") and st["n_trash"] > 0 and st["n_keep"] >= 2 and st["has_calls"], str(st))
    check("Remove refused without the typed confirmation", post(U, "/api/sa/remove", dict(codes=[A2], mode="remove", confirm_phrase="remove")).get("needs_confirm"))
    rr = post(U, "/api/sa/remove", dict(codes=[A2], mode="remove", confirm_phrase="REMOVE"))
    new = (rr.get("done") or [{}])[0].get("retired_as", "")
    P_ = pats(U)
    check("Remove: the study is retired under a new RET identifier", rr.get("ok") and new.startswith("RET-") and new in P_ and A2 not in P_ and P_[new].get("retired"), str(rr))
    check("Remove: calls and candidate table kept, renamed to the new identifier (content too)", os.path.exists(os.path.join(B, "review", f"{new}_candidates.csv")) and
          open(os.path.join(B, "review", f"{new}_calls_Dr_Q.csv")).read().strip().endswith(new) and not glob.glob(os.path.join(B, "review", f"{A2}_*")))
    tr = glob.glob(os.path.join(TRASH, "*"))
    check("Remove: images / processing and the library copy moved to the (test) Trash", tr and glob.glob(os.path.join(TRASH, "*", "work", f"{A2}_brainmask.nii")) and
          not os.path.exists(os.path.join(LIB, MRN[0], "ACCS-002")) and glob.glob(os.path.join(TRASH, "*", "outside_project", "ACCS-002")))
    check("Remove: accession and code released", not any(x["ident"].get("accession") == "ACCS-002" for x in get(U, "/api/results")) and
          post(U, "/api/sa/edit", dict(code=A1, fields=dict(deid_code="SYN-A2"), confirm=True)).get("ok"))
    post(U, "/api/sa/edit", dict(code=A1, fields=dict(deid_code="SYN-A1"), confirm=True))
    D = dom(U, "#archive")
    check("retired study shown on the Archive screen (kept for ML), not in Studies", f'data-st="{new}"' not in dom(U, "#studies?grp=none") and "Removed, kept for ML (1)" in D)
    rp = post(U, "/api/id/import/plan", dict(folder=os.path.join(SRC, "a"), folder_is="mrn", sub_is="accession", mode="standard", manifest=XA, processing=dict(cohort="C520")))
    e2 = next(e for e in rp["exams"] if e["accession"] == "ACCS-002")
    check("re-import of the removed examination is allowed (noted, not a duplicate)", e2["duplicate"]["kind"] in ("new", "same_patient_new_exam") and any("previously removed" in n for n in e2["notes"]))
    # ------------------------------------------------------------------ import duplicates: same accession, different images
    pd_ = plan(U, os.path.join(SRC, "dup"), XA.replace("a.xlsx", "a.xlsx"))
    e3 = pd_["exams"][0]
    check("duplicate accession detected: choices offered, import blocked until chosen", e3["duplicate"]["kind"] == "conflict" and not pd_["ok"] and e3["dup_other"].get("label") == "ACCS-003", str(e3["duplicate"]))
    pu = post(U, "/api/id/import/update", dict(plan=pd_["id"], changes=[dict(eid=e3["eid"], dup_choice="replace")]))
    check("choice Replace: plan valid", pu["ok"], str(pu.get("errors"))[:200])
    r = commit(U, pu)
    check("Replace needs REPLACE typed", r.get("ok") is False and "REPLACE" in r.get("error", ""))
    pd_ = plan(U, os.path.join(SRC, "dup"), XA); post(U, "/api/id/import/update", dict(plan=pd_["id"], changes=[dict(eid=pd_["exams"][0]["eid"], dup_choice="keep_ml")]))
    r = commit(U, pd_); P_ = pats(U)
    newA3 = r.get("imported", [{}])[0].get("file_key", "")
    check("choice Import, keep old for ML: old study retired, new one imported with the accession", r.get("ok") and len([p for p in P_.values() if p.get("retired")]) == 2 and not P_[newA3].get("retired")
          and get(U, f"/api/id/study?code={newA3}")["accession"] == "ACCS-003", str(r)[:300])
    # ------------------------------------------------------------------ purge
    done(U, [newA3]); libjob(U, r)
    rr = post(U, "/api/sa/remove", dict(codes=[newA3], mode="purge", confirm_phrase="PURGE")); P_ = pats(U)
    check("Purge: study gone, identity deleted, files in the Trash", rr.get("ok") and newA3 not in P_ and not glob.glob(os.path.join(B, "review", f"{newA3}_*")) and
          not any(x["ident"].get("accession") == "ACCS-003" for x in get(U, "/api/results")), str(rr))
    pd_ = plan(U, os.path.join(SRC, "dup"), XA)
    check("after Purge the identifiers are free again (import valid)", pd_["ok"] and pd_["exams"][0]["duplicate"]["kind"] in ("new", "same_patient_new_exam"), str(pd_.get("errors"))[:200])
    # ------------------------------------------------------------------ previous version
    kp = get(U, "/api/kp/list")["projects"]; pv = next((k for k in kp if k["path"].endswith("cSS_experimental")), {})
    check("previous Percival version found with its processed studies", pv.get("kind") == "previous Percival version" and pv.get("n_processed") == 2, str(kp))
    pp = plan(U, os.path.join(SRC, "prev"), XP); e4 = pp["exams"][0]
    check("import: examination processed in the previous version is recognised (reuse offered, on)", e4["reuse_possible"] and e4["reuse"], str({k: e4.get(k) for k in ("reuse", "reuse_possible", "reuse_from")}))
    r = commit(U, pp); P_ = pats(U); ok_ = r.get("ok") and r["imported"][0]["reused"] and "OLD01" in P_ and P_["OLD01"]["status"] == "done"
    check("reused: results brought in, not processed again", ok_ and os.path.exists(os.path.join(B, "review", "OLD01_candidates.csv")) and get(U, "/api/id/study?code=OLD01")["accession"] == "ACCS-090", str(r)[:300])
    r = post(U, "/api/kp/bring_all", dict(path=PREV)); P_ = pats(U)
    check("bring in all remaining processed studies of the previous version", "OLD02" in P_ and any(x["ok"] for x in r.get("results", [])), str(r)[:300])
    check("the previous project was only read (unchanged)", PREV_HASH == {p: hashlib.sha256(open(p, "rb").read()).hexdigest() for p in glob.glob(PREV + "/**/*", recursive=True) if os.path.isfile(p)})
    # ------------------------------------------------------------------ Incognito: code everywhere
    post(U, "/api/id/mode", dict(mode="incognito"))
    D = re.sub(r"<[^>]+>", " ", dom(U, "#act") + dom(U, f"#studies?open={A1}").replace('data-id="sh-code"', ">SHCODE<"))
    check("Incognito: code everywhere, no accession / MRN / name", "SYN-A1" in D and "ACCS-001" not in D and MRN[0] not in D and NAMES[0] not in D and "SHCODE" in D)
    shot(U, "v520_panel_incognito", f"#studies?open={A1}")
finally:
    app.terminate(); app.wait(timeout=20)
shutil.rmtree(T, ignore_errors=True)
print(("ALL PASS" if not F else f"{len(F)} FAILED: {F}") + f" ({__file__})"); sys.exit(1 if F else 0)
