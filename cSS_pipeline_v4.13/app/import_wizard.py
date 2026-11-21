"""import_wizard.py - guided import of MRI examinations with mandatory study identifiers (v5.16). Research software; local only.

Steps (the GUI follows them): 1 data folder -> 2 what the patient folder names are (MRN | patient name | de-identified patient code; asked,
never assumed) -> 3 mode for this import (Standard | Incognito; a de-identified folder naming recommends Incognito) -> 4 manifest (template /
completed file) -> 5 identifier validation -> 6 preview (patients, examinations, identifiers, duplicates, missing, conflicts, errors) ->
7 confirmed import. Nothing is imported unless every included examination has the identifier its mode requires and no error remains.

Examinations inside a patient folder: DICOM series are grouped by StudyInstanceUID; NIfTI series by their first sub-folder when the
patient folder holds several examination folders; otherwise the patient folder is one examination. Manifest rows are matched to
examinations by: DICOM AccessionNumber = accession_number; else a code equal to the examination / patient folder name; else one
examination + one row of that patient; anything else is left for the user to assign in the preview (never guessed).
Plans are kept in memory on the server; Incognito previews never contain MRN, name, accession, folder names or file paths."""
import os, re, secrets, threading, time
import series_detect as SD
import manifest as MF

PLANS = {}; LOCK = threading.Lock(); TTL = 6 * 3600
FOLDER_IS = ("mrn", "name", "deid")


def _dicom_ids(series):
    """AccessionNumber / StudyInstanceUID / InstitutionName of the first DICOM file of a series folder (server side only)"""
    try:
        import pydicom
        fs = sorted(f for f in os.listdir(series["path"]) if not f.startswith("."))
        for f in fs[:3]:
            try:
                d = pydicom.dcmread(os.path.join(series["path"], f), stop_before_pixels=True, force=True)
                return dict(accession=str(getattr(d, "AccessionNumber", "") or ""), study_uid=str(getattr(d, "StudyInstanceUID", "") or ""),
                            institution=str(getattr(d, "InstitutionName", "") or ""))
            except Exception: continue
    except Exception: pass
    return {}


def exams_of(folder):
    ser = SD.scan(folder); groups = {}
    tops = {s["relpath"].split(os.sep)[0] for s in ser if s.get("ok") and os.sep in s.get("relpath", "") and s.get("type") == "SWI"}
    for s in ser:
        if not s.get("ok"): continue
        if s.get("format") == "DICOM" and s.get("study_uid"): k = "uid:" + s["study_uid"]
        elif len(tops) > 1 and os.sep in s.get("relpath", ""): k = "dir:" + s["relpath"].split(os.sep)[0]
        else: k = "single"
        groups.setdefault(k, []).append(s)
    out = []
    for k, g in sorted(groups.items()):
        pick, _ = SD.choose(g)
        t1, _, _ = SD.choose_t1(g)
        if t1: pick["T1"] = t1
        else: pick.pop("T1", None)
        e = dict(key=k, series=g, chosen=pick, folder=os.path.join(folder, k[4:]) if k.startswith("dir:") else folder, sub=k[4:] if k.startswith("dir:") else "")
        swi = next((s for s in g if s["path"] == pick.get("SWI")), None)
        if swi:
            try: e["fingerprint"] = SD.content_fingerprint(swi["path"])
            except Exception as ex: e["fingerprint"] = ""; e["fp_error"] = str(ex)[:120]
            if swi.get("format") == "DICOM": e.update({f"dicom_{a}": b for a, b in _dicom_ids(swi).items()})
        out.append(e)
    return out


def new_plan(folder, folder_is, mode, manifest_path="", generate_codes=False, ID=None, existing_file_keys=()):
    if folder_is not in FOLDER_IS: raise ValueError("choose what the patient folder names are: MRN, patient name or de-identified patient code")
    if mode not in ("standard", "incognito"): raise ValueError("choose Standard or Incognito")
    if not os.path.isdir(folder): raise ValueError("not a folder")
    pts = sorted(d for d in os.listdir(folder) if os.path.isdir(os.path.join(folder, d)) and not d.startswith("."))
    rows, hprob = MF.read(manifest_path) if manifest_path else ([], [])
    plan = dict(id=secrets.token_urlsafe(12), created=time.time(), folder=folder, folder_is=folder_is, mode=mode, generate_codes=bool(generate_codes),
                manifest=bool(manifest_path), header_problems=hprob, rows=rows, patients=[], exams=[])
    for i, d in enumerate(pts, 1):
        pf = os.path.join(folder, d); ex = exams_of(pf)
        plan["patients"].append(dict(idx=i, folder_name=d, n_exams=len(ex)))
        for j, e in enumerate(ex, 1): plan["exams"].append(dict(e, eid=f"{i}.{j}", patient_idx=i, patient_folder=d, row=None, display_name="", include=True))
    _match(plan); revalidate(plan, ID, existing_file_keys)
    with LOCK:
        for k in [k for k, p in PLANS.items() if time.time() - p["created"] > TTL]: PLANS.pop(k, None)
        PLANS[plan["id"]] = plan
    return plan


def _match(plan):
    rows = plan["rows"]; fi = plan["folder_is"]; used = set()
    def rows_of(pfolder):
        if fi == "mrn": return [r for r in rows if r["mrn"] and r["mrn"].strip() == pfolder.strip()]
        if fi == "name": return [r for r in rows if r["patient_name"] and r["patient_name"].strip().lower() == pfolder.strip().lower().replace("_", " ")]
        return [r for r in rows if r["code"] and r["code"].strip() == pfolder.strip()]
    for p in plan["patients"]:
        ex = [e for e in plan["exams"] if e["patient_idx"] == p["idx"]]; cand = rows_of(p["folder_name"])
        for e in ex:
            m = [r for r in cand if r["accession"] and e.get("dicom_accession") and r["accession"].strip() == e["dicom_accession"].strip()] or \
                [r for r in rows if r["code"] and e["sub"] and r["code"].strip() == e["sub"].strip()]
            if len(m) == 1 and m[0]["row"] not in used: e["row"] = m[0]["row"]; e["matched_by"] = "DICOM accession" if m[0]["accession"] == e.get("dicom_accession") else "code = folder"; used.add(m[0]["row"])
        free_e = [e for e in ex if e["row"] is None]; free_r = [r for r in cand if r["row"] not in used]
        if len(free_e) == 1 and len(free_r) == 1:
            free_e[0]["row"] = free_r[0]["row"]; free_e[0]["matched_by"] = "only examination of this patient"; used.add(free_r[0]["row"])


def _row(plan, n): return next((r for r in plan["rows"] if r["row"] == n), None)


def revalidate(plan, ID=None, existing_file_keys=()):
    mode = plan["mode"]; errs = [dict(eid="", msg=m) for m in plan["header_problems"]]; warns = []
    if mode == "standard" and not plan["manifest"]: errs.append(dict(eid="", msg="Standard mode needs the manifest: every examination requires its accession number (never generated)"))
    if mode == "standard" and ID is not None and not ID.unlocked(): errs.append(dict(eid="", msg="unlock the identity vault: Standard mode stores MRN, name and accession only in the encrypted vault"))
    inc = [e for e in plan["exams"] if e["include"]]
    rowsel = [_row(plan, e["row"]) for e in inc if e["row"] is not None]
    ex_codes = list(existing_file_keys) + ([s["deid_code"] for s in ID.R["studies"].values()] if ID else [])
    ex_acc = []
    if ID is not None and ID.unlocked(): ex_acc = [v.get("accession", "") for v in ID._vault["studies"].values() if v.get("accession")]
    v = MF.validate([r for r in rowsel if r], mode, plan["generate_codes"], ex_codes, ex_acc) if rowsel else dict(errors=[], warnings=[])
    errs += [dict(eid=next((e["eid"] for e in inc if e["row"] == x["row"]), ""), msg=f"manifest row {x['row']}: {x['msg']}") for x in v["errors"]]
    warns += [dict(eid="", msg=x["msg"]) for x in v["warnings"]]
    rows_used = [e["row"] for e in inc if e["row"] is not None]
    for n in {n for n in rows_used if rows_used.count(n) > 1}: errs.append(dict(eid="", msg=f"manifest row {n} is assigned to more than one examination"))
    for e in plan["exams"]:
        e["problems"] = []
        r = _row(plan, e["row"]) if e["row"] is not None else None
        if not e["chosen"].get("SWI"): e["problems"].append("no SWI found")
        if plan["manifest"] and r is None and e["include"]: e["problems"].append("no manifest row assigned - choose the row of this examination")
        if mode == "standard" and e["include"] and (r is None or not r["accession"]): e["problems"].append("accession number missing")
        if mode == "incognito" and e["include"] and not (r and r["code"]) and not plan["generate_codes"] and not e.get("generated_code"):
            e["problems"].append("de-identified study code missing (enter it in the manifest or let Percival generate it)")
        if ID is not None:
            c = ID.classify(fingerprint=e.get("fingerprint", ""), dicom_study_uid=e.get("dicom_study_uid", ""), accession=(r or {}).get("accession", ""),
                            institution=e.get("dicom_institution", ""), deid_code=(r or {}).get("code", ""), mrn=(r or {}).get("mrn", ""))
            e["duplicate"] = c
            if c["kind"] == "same_exam" and e["include"]: e["include"] = False; e["excluded_why"] = c["why"]
            if c["kind"] == "conflict" and e["include"]: e["problems"].append(c["why"])
        if e["include"]:
            errs += [dict(eid=e["eid"], msg=f"examination {e['eid']}: {m}") for m in e["problems"]]
    if ID is not None and not ID.unlocked() and any(r["mrn"] or r["patient_name"] or r["accession"] for r in plan["rows"]):
        warns.append(dict(eid="", msg="the manifest holds MRN / name / accession values: they are NOT stored (identity vault locked) and never shown in Incognito"))
    plan["errors"], plan["warnings"] = errs, warns; plan["ok"] = not errs and any(e["include"] for e in plan["exams"])
    return plan


def update(plan_id, changes, ID=None, existing_file_keys=()):
    """changes: [dict(eid, row?, include?, display_name?)]"""
    p = PLANS.get(plan_id)
    if not p: raise ValueError("this import preview expired - start again")
    for c in changes:
        e = next((x for x in p["exams"] if x["eid"] == c.get("eid")), None)
        if not e: continue
        if "row" in c: e["row"] = int(c["row"]) if c["row"] not in (None, "") else None; e["matched_by"] = "assigned by you"
        if "include" in c: e["include"] = bool(c["include"]); e.pop("excluded_why", None) if c["include"] else None
        if "display_name" in c: e["display_name"] = str(c["display_name"])[:120]
    return revalidate(p, ID, existing_file_keys)


def view(plan):
    """what the browser may see. Incognito: no MRN / name / accession / folder names / paths."""
    inc = plan["mode"] == "incognito"
    pts = [dict(idx=p["idx"], label=f"patient folder {p['idx']}" if inc else p["folder_name"], n_exams=p["n_exams"]) for p in plan["patients"]]
    ex = []
    for e in plan["exams"]:
        r = _row(plan, e["row"]) if e["row"] is not None else None
        x = dict(eid=e["eid"], patient_idx=e["patient_idx"], include=e["include"], excluded_why=e.get("excluded_why", ""), problems=e["problems"],
                 matched_by=e.get("matched_by", ""), row=e["row"], display_name=e["display_name"], has_swi=bool(e["chosen"].get("SWI")),
                 series=[dict(type=s.get("type"), voxel=s.get("voxel"), format=s.get("format")) for s in e["series"] if s.get("type") in ("SWI", "T1", "FLAIR", "PHASE")],
                 duplicate=dict(kind=(e.get("duplicate") or {}).get("kind", ""), why=(e.get("duplicate") or {}).get("why", "")),
                 code=(r or {}).get("code", "") or e.get("generated_code", ""), code_generated=bool(e.get("generated_code")) or (plan["generate_codes"] and not (r or {}).get("code")))
        if not inc:
            x.update(patient_folder=e["patient_folder"], sub=e["sub"], mrn=(r or {}).get("mrn", ""), patient_name=(r or {}).get("patient_name", ""), accession=(r or {}).get("accession", ""))
        ex.append(x)
    rows = MF.redact(plan["rows"], plan["mode"])
    msgs = lambda L: [dict(eid=m["eid"], msg=m["msg"]) for m in L]
    return dict(id=plan["id"], mode=plan["mode"], folder_is=plan["folder_is"], generate_codes=plan["generate_codes"], patients=pts, exams=ex, rows=rows,
                errors=msgs(plan["errors"]), warnings=msgs(plan["warnings"]), ok=plan["ok"], n_exams=len(plan["exams"]), n_include=sum(e["include"] for e in plan["exams"]),
                recommend_incognito=plan["folder_is"] == "deid" and plan["mode"] == "standard")


def _neutral_copy(chosen, fk, root):
    """copy the chosen series into the project under NEUTRAL names (APFS clone when possible: no extra disk space) so that no source
    path - which can hold an MRN or a patient name - is stored by the app: root/<file key>/<TYPE>_series.<ext> (+ sidecar) or
    root/<file key>/<TYPE>/ for a DICOM series"""
    import shutil, subprocess
    if not root: return dict(chosen)
    out = {}; d = os.path.join(root, fk); os.makedirs(d, exist_ok=True)
    def cp(a, b):
        if subprocess.run(["cp", "-c", a, b], capture_output=True).returncode != 0: shutil.copy2(a, b)
    for k, src in chosen.items():
        if os.path.isdir(src):
            t = os.path.join(d, k); os.makedirs(t, exist_ok=True)
            for i, f in enumerate(sorted(x for x in os.listdir(src) if not x.startswith(".") and os.path.isfile(os.path.join(src, x)))):
                cp(os.path.join(src, f), os.path.join(t, f"{k}_{i:05d}.dcm"))
            out[k] = t
        else:
            ext = ".nii.gz" if src.endswith(".nii.gz") else ".nii"; t = os.path.join(d, f"{k}_series{ext}"); cp(src, t)
            js = re.sub(r"\.nii(\.gz)?$", ".json", src)
            if os.path.exists(js): cp(js, os.path.join(d, f"{k}_series.json"))
            out[k] = t
    return out


def commit(plan_id, ID, add_to_queue, settings, by=""):
    """create patient / study records (uuids; identifiers in the vault) and queue the included examinations under their file keys"""
    p = PLANS.get(plan_id)
    if not p: raise ValueError("this import preview expired - start again")
    revalidate(p, ID)
    if not p["ok"]: raise ValueError("the preview still has errors - nothing was imported")
    mode = p["mode"]; inc = [e for e in p["exams"] if e["include"]]; patients = {}; items = []; out = []
    try: return _commit(p, ID, add_to_queue, settings, by, mode, inc, patients, items, out)
    except Exception:
        ID.R = ID._load_registry()                        # any failure before the queue: no half-made identity records
        if ID.unlocked(): ID.unlock_reload()
        raise


def _commit(p, ID, add_to_queue, settings, by, mode, inc, patients, items, out):
    for e in inc:
        r = _row(p, e["row"]) if e["row"] is not None else {}
        r = r or {}
        code = r.get("code", "")
        if not code: code = e.get("generated_code") or ID.unique_code(); e["generated_code"] = code if not r.get("code") else ""
        fk = code if MF.CODE_RE.fullmatch(code) and not ID.by_file_key(code) else ID.unique_code()
        pkey = (r.get("mrn") if mode == "standard" or r.get("mrn") else "") or f"folder:{e['patient_idx']}"
        if pkey not in patients:
            mrn = r.get("mrn", "") if ID.unlocked() else ""; nm = r.get("patient_name", "") if ID.unlocked() else ""
            if p["folder_is"] == "mrn" and not mrn and ID.unlocked(): mrn = e["patient_folder"]
            if p["folder_is"] == "name" and not nm and ID.unlocked(): nm = e["patient_folder"].replace("_", " ")
            existing = ID.patients_by_mrn(mrn) if mrn and ID.unlocked() else []
            patients[pkey] = existing[0] if len(existing) == 1 else ID.add_patient(pseudonym=e["patient_folder"] if p["folder_is"] == "deid" else "", mrn=mrn, name=nm, by=by)
        su = ID.add_study(patients[pkey], fk, code, display_name=e["display_name"], accession=r.get("accession", "") if ID.unlocked() else "",
                          institution=e.get("dicom_institution", "") if ID.unlocked() else "", dicom_study_uid=e.get("dicom_study_uid", "") if ID.unlocked() else "",
                          fingerprint=e.get("fingerprint", ""), source="import wizard", by=by)
        items.append(dict(folder_name=fk, folder="", code=fk, name="", chosen=_neutral_copy(e["chosen"], fk, settings.get("_import_src")),
                          fingerprint=e.get("fingerprint", ""), fingerprint_v1=""))
        out.append(dict(eid=e["eid"], study_uuid=su, file_key=fk, deid_code=code, generated=bool(e.get("generated_code"))))
    def rollback():                                       # nothing committed yet: drop the new identity records (memory only)
        ID.R = ID._load_registry()
        if ID.unlocked(): ID.unlock_reload()
    try: q = add_to_queue(items, settings)
    except Exception: rollback(); raise
    if not q.get("ok"): rollback(); raise ValueError("queue refused: " + "; ".join(q.get("errors", [])))
    ID.commit(); PLANS.pop(p["id"], None)
    return dict(ok=True, imported=out, queued=q.get("added", []))
