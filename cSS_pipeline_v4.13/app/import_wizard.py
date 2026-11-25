"""import_wizard.py - THE import of MRI examinations from folders (v5.16 guided import; v5.18 single Add-studies pathway). Local only.

Steps (the GUI follows them): 1 data folder (one examination, or many: one sub-folder per patient / examination; detected) -> 2 what
the folder names are: patient name | MRN | accession number | de-identified code | irrelevant (use the Excel file and the scan
headers); asked, never assumed; optionally what the examination SUB-folder names are -> 3 mode (Standard | Incognito) -> 4 Excel file
(Percival_Import_Template.xlsx: identifiers, optional folder / study date / radiologist grades) -> 5 study library (a verified COPY,
organised MRN/accession or patient code/study code; originals untouched) -> 6 processing options -> 7 preview -> import and start.
Nothing is imported unless every included examination has the identifier its mode requires and no error remains.

Identifiers come from the USER: the Excel file (the key) or the folder names (a helper that fills them in); first source wins, shown:
  accession  Excel accession_number > accession-number folder name                  never generated; the scan header only cross-checks
  MRN        Excel MRN > MRN folder name
  name       Excel patient_name > patient-name folder name                           optional
  code       typed in the preview > Excel code > code folder name > (Standard only) generated at import, kept for Incognito
Standard: MRN and accession number required for every examination; examinations are grouped into patients by MRN; a blank code
is generated. Incognito: the key (Excel file with MRN, name, accession number and code) is required and stored in the encrypted vault
(the passphrase is asked; the screens stay de-identified); every examination needs its code (its unique identifier); no grouping is
shown - studies are listed by code. Folder names 'irrelevant': every Excel row must name its folder (column 'folder') and matching is
done by that column only.

Examinations: DICOM series are grouped by StudyInstanceUID; NIfTI series by their first sub-folder when a patient folder holds several
examination folders; otherwise the folder is one examination.

Manifest rows are matched to examinations, strongest evidence first (each rule only when it gives exactly one free row):
  1 accession: Excel accession_number = DICOM AccessionNumber or = the accession-number folder name
  2 code = examination / patient folder name
  3 Excel 'folder' column = the examination's folder (relative to the data folder) or its patient folder
  4 MRN (folder or DICOM PatientID) and study date
  5 the only examination + the only row of that patient
A row whose accession differs from the scan header's AccessionNumber is never matched; anything else is left for the user to assign.

Series: T1 and SWI chosen automatically with the reason shown; the user can choose any other series (marked "chosen by you").
Plans are kept in memory on the server; Incognito previews never contain MRN, name, accession, folder names or file paths."""
import io, os, re, secrets, threading, time
import series_detect as SD
import manifest as MF
import study_library as SL

PLANS = {}; LOCK = threading.Lock(); TTL = 6 * 3600
FOLDER_IS = ("name", "mrn", "accession", "code", "none")
ALIAS = {"deid": "code"}                                   # v5.16 name of the code choice
SUB_IS = ("", "accession", "code")
SER_TYPES = ("SWI", "T1", "PHASE", "FLAIR")


def _s(x): return str(x or "").strip()
def _nf(x): return _s(x).strip("/").replace("\\", "/").lower()


def _dicom_ids(series):
    """AccessionNumber / StudyInstanceUID / InstitutionName / PatientID / StudyDate of the first DICOM file of a series folder (server side only)"""
    try:
        import pydicom
        fs = sorted(f for f in os.listdir(series["path"]) if not f.startswith("."))
        for f in fs[:3]:
            try:
                d = pydicom.dcmread(os.path.join(series["path"], f), stop_before_pixels=True, force=True)
                return dict(accession=str(getattr(d, "AccessionNumber", "") or ""), study_uid=str(getattr(d, "StudyInstanceUID", "") or ""),
                            institution=str(getattr(d, "InstitutionName", "") or ""), patient_id=str(getattr(d, "PatientID", "") or ""),
                            study_date=str(getattr(d, "StudyDate", "") or ""))
            except Exception: continue
    except Exception: pass
    return {}


def _auto_reasons(g, pick):
    out = {}
    swi = next((s for s in g if s["path"] == pick.get("SWI")), None)
    if swi:
        n = sum(1 for s in g if s.get("ok") and s.get("type") == "SWI")
        out["SWI"] = f"{swi.get('reason') or 'susceptibility series'}" + (f"; highest resolution of {n} SWI series" if n > 1 else "") + "; phase / minIP never used as the SWI"
    if pick.get("T1"):
        t = next((s for s in g if s["path"] == pick["T1"]), None)
        out["T1"] = ("T1 " + SD.t1_quality(t)[2]) if t else "T1"
    for k in ("PHASE", "FLAIR"):
        if pick.get(k): out[k] = "matching series of the examination"
    return out


def _t1_skipped(e):
    out = []
    for s in e["series"]:
        if s.get("ok") and s.get("type") == "T1" and s["path"] != e["chosen"].get("T1"):
            u, _, why = SD.t1_quality(s)
            if not u: out.append(dict(path=s["path"], name="another T1 series", reason=why))
    return out


def exams_of(folder, data_root=None):
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
        efolder = os.path.join(folder, k[4:]) if k.startswith("dir:") else folder
        sub = k[4:] if k.startswith("dir:") else ""
        firsts = {s["relpath"].split(os.sep)[0] for s in g if os.sep in s.get("relpath", "")}
        if k == "single" and len(firsts) == 1 and all(os.sep in s.get("relpath", "") for s in g):   # ONE examination sub-folder: keep its name
            sub = firsts.pop(); efolder = os.path.join(folder, sub)
        if k.startswith("uid:"):                          # the examination's own folder: common parent of its series
            dirs = [s["path"] if os.path.isdir(s["path"]) else os.path.dirname(s["path"]) for s in g]
            try: efolder = os.path.commonpath(dirs)
            except ValueError: efolder = folder
            rel = os.path.relpath(efolder, folder)
            if rel != "." and len(groups) > 1: sub = rel.split(os.sep)[0]
        e = dict(key=k, series=g, chosen=pick, auto=dict(pick), auto_why=_auto_reasons(g, pick), user_series=False, folder=efolder, sub=sub,
                 relfolder=os.path.relpath(efolder, data_root) if data_root else "")
        dates = {s.get("study_date") for s in g if s.get("study_date")}
        e["study_date"] = MF.norm_date(sorted(dates)[0]) if dates else ""
        _fingerprint(e)
        out.append(e)
    return out


def _fingerprint(e):
    swi = next((s for s in e["series"] if s["path"] == e["chosen"].get("SWI")), None)
    for k in ("fingerprint", "fp_error"): e.pop(k, None)
    if swi:
        try: e["fingerprint"] = SD.content_fingerprint(swi["path"])
        except Exception as ex: e["fingerprint"] = ""; e["fp_error"] = str(ex)[:120]
        if swi.get("format") == "DICOM":
            ids = _dicom_ids(swi); e.update({f"dicom_{a}": b for a, b in ids.items()})
            if ids.get("study_date") and not e.get("study_date"): e["study_date"] = MF.norm_date(ids["study_date"])


def _patient_like(path):
    """sub-folders that each hold their own MRI series (the chosen folder holds MANY examinations / patients)"""
    hits = []
    for d in sorted(os.listdir(path))[:400]:
        p = os.path.join(path, d)
        if d.startswith(".") or not os.path.isdir(p): continue
        ser = SD.scan(p, max_depth=3)
        if any(x.get("type") == "SWI" for x in ser) or len(ser) >= 3: hits.append(d)
    return hits


def new_plan(folder, folder_is, mode, manifest_path="", generate_codes=False, ID=None, existing_file_keys=(), library=None, verify_dest=None,
             sub_is="", hooks=None, processing=None):
    folder_is = ALIAS.get(folder_is, folder_is)
    if folder_is not in FOLDER_IS: raise ValueError("choose what the folder names are: patient name, MRN, accession number, de-identified code, or irrelevant")
    if sub_is not in SUB_IS: raise ValueError("unknown sub-folder meaning")
    if mode not in ("standard", "incognito"): raise ValueError("choose Standard or Incognito")
    if not os.path.isdir(folder): raise ValueError("not a folder")
    if folder_is == "none" and not manifest_path:
        raise ValueError("the folder names are irrelevant: choose the Excel file - every row must name its examination's folder (column 'folder')")
    if mode == "incognito" and not manifest_path:
        raise ValueError("Incognito import: choose the key - the Excel file with MRN, patient name, accession number and code of every examination")
    rows, hprob = MF.read(manifest_path) if manifest_path else ([], [])
    plan = dict(id=secrets.token_urlsafe(12), created=time.time(), folder=folder, folder_is=folder_is, sub_is=sub_is, mode=mode, generate_codes=bool(generate_codes),
                manifest=bool(manifest_path), header_problems=hprob, rows=rows, patients=[], exams=[], hooks=hooks or {},
                library=dict(enabled=False, root="", whole_exam=False), processing=dict(cohort="", anatomy="synthseg", run_mode="semi", results_dir=""))
    plan["processing"].update({k: v for k, v in (processing or {}).items() if k in plan["processing"]})
    many = _patient_like(folder)
    if many: tops = [(d, os.path.join(folder, d)) for d in many]; plan["layout"] = "many"
    else: tops = [(os.path.basename(os.path.normpath(folder)), folder)]; plan["layout"] = "one"
    for i, (d, pf) in enumerate(tops, 1):
        ex = exams_of(pf, folder if plan["layout"] == "many" else os.path.dirname(os.path.normpath(folder)))
        plan["patients"].append(dict(idx=i, folder_name=d, n_exams=len(ex)))
        for j, e in enumerate(ex, 1):
            plan["exams"].append(dict(e, eid=f"{i}.{j}", patient_idx=i, patient_folder=d, row=None, display_name="", include=True, code_override="", n_in_folder=len(ex), j=j,
                                      pathway=""))
    plan["has_subfolders"] = any(e["sub"] for e in plan["exams"])
    km = plan["hooks"].get("known_match")                   # v5.20: processed before in another project (e.g. the previous version)?
    if km:
        for e in plan["exams"]:
            m = km(e)
            if m and m.get("processed"): e["reuse_src"] = m; e["reuse"] = True
    _match(plan)
    for e in plan["exams"]: _pathway(plan, e)
    set_library(plan, library or {}, verify_dest)
    revalidate(plan, ID, existing_file_keys)
    with LOCK:
        for k in [k for k, p in PLANS.items() if time.time() - p["created"] > TTL]: PLANS.pop(k, None)
        PLANS[plan["id"]] = plan
    return plan


def _pathway(plan, e):
    """recommended processing pathway + check (the app's own rule, css_app.check_pathway)"""
    f = plan["hooks"].get("pathway")
    if not f: e.update(check="ok", pathway_rec="synthseg", pathway_reason="", overlap=""); e["pathway"] = e["pathway"] or "synthseg"; return
    r = dict(chosen=e["chosen"], t1_skipped=_t1_skipped(e)); f(r, e["series"])
    rec = r.get("pathway") or ""
    if plan["processing"]["anatomy"] == "recon" and rec == "synthseg": rec = "recon"
    e.update(check=r.get("check", "ok"), pathway_rec=rec, pathway_reason=r.get("pathway_reason", ""), overlap=r.get("overlap", ""))
    if not e.get("pathway_user"): e["pathway"] = rec


# ------------------------------------------------------------------ identifiers of an examination (first available source wins)
def folder_value(plan, e, what):
    """the identifier the FOLDER NAMES give for this examination ('' when they do not give it)"""
    fi, si = plan["folder_is"], plan["sub_is"]
    top, sub = _s(e["patient_folder"]), _s(e["sub"])
    if what == "mrn": return top if fi == "mrn" else ""
    if what == "name": return top.replace("_", " ") if fi == "name" else ""
    if what == "accession":
        if si == "accession" and sub: return sub
        if fi == "accession": return sub or (top if e["n_in_folder"] == 1 else "")
        return ""
    if what == "code":
        for c in ((sub,) if sub and (si == "code" or fi == "code") else ()) + (((top,) if e["n_in_folder"] == 1 else (f"{top}_{e['j']}",)) if fi == "code" else ()):
            if c and MF.CODE_RE.fullmatch(c): return c
        return ""
    return ""


def ids(plan, e):
    r = _row(plan, e["row"]) if e["row"] is not None else None
    r = r or {}
    def first(*pairs):
        for v, src in pairs:
            if _s(v): return _s(v), src
        return "", ""
    acc = first((r.get("accession"), "Excel"), (folder_value(plan, e, "accession"), "folder name"))
    mrn = first((r.get("mrn"), "Excel"), (folder_value(plan, e, "mrn"), "folder name"))
    name = first((r.get("patient_name"), "Excel"), (folder_value(plan, e, "name"), "folder name"))
    code = first((e.get("code_override"), "you"), (r.get("code"), "Excel"), (folder_value(plan, e, "code"), "folder name"), (e.get("generated_code"), "generated"))
    return dict(accession=acc[0], accession_src=acc[1], mrn=mrn[0], mrn_src=mrn[1], name=name[0], name_src=name[1], code=code[0], code_src=code[1],
                radiologist=r.get("radiologist", ""), grade_R=r.get("grade_R", ""), grade_L=r.get("grade_L", ""))


def study_code(plan, e): return ids(plan, e)["code"]


def _match(plan):
    rows = plan["rows"]; fi = plan["folder_is"]; used = set()
    def take(e, r, why): e["row"] = r["row"]; e["matched_by"] = why; used.add(r["row"])
    def one(c): c = [r for r in c if r["row"] not in used]; return c[0] if len(c) == 1 else None
    def acc_conflict(e, r): return bool(r["accession"] and e.get("dicom_accession") and _s(r["accession"]).upper() != _s(e["dicom_accession"]).upper())
    def mrn_of(e): return folder_value(plan, e, "mrn")
    ex = plan["exams"]
    if fi == "none":                                                                # irrelevant folder names: the Excel 'folder' column only
        for e in ex:
            names = {_nf(e["relfolder"])} | ({_nf(e["patient_folder"])} if e["n_in_folder"] == 1 and e["patient_folder"] else set())
            r = one([r for r in rows if r.get("folder") and _nf(r["folder"]) in names - {"", "."}])
            if r and acc_conflict(e, r): e["header_conflict"] = f"Excel row {r['row']} names this folder, but its accession number differs from the scan header - check the row"
            if r: take(e, r, "Excel folder column")
        for e in ex: e.setdefault("header_conflict", "")
        return
    for e in ex:                                                                    # 1 accession (scan header or accession folder name)
        for a, why in ((e.get("dicom_accession"), "DICOM accession"), (folder_value(plan, e, "accession"), "accession = folder name")):
            if e["row"] is None and _s(a):
                r = one([r for r in rows if r["accession"] and _s(r["accession"]).upper() == _s(a).upper() and not acc_conflict(e, r)])
                if r: take(e, r, why)
    for e in ex:                                                                    # 2 code = folder name
        if e["row"] is None:
            names = {_s(e["sub"])} | ({_s(e["patient_folder"])} if fi == "code" else set())
            r = one([r for r in rows if r["code"] and _s(r["code"]) in names - {""} and not acc_conflict(e, r)])
            if r: take(e, r, "code = folder name")
    for e in ex:                                                                    # 3 Excel 'folder' column
        if e["row"] is None:
            names = {_nf(e["relfolder"])} | ({_nf(e["patient_folder"])} if e["n_in_folder"] == 1 and e["patient_folder"] else set())
            r = one([r for r in rows if r.get("folder") and _nf(r["folder"]) in names - {"", "."} and not acc_conflict(e, r)])
            if r: take(e, r, "Excel folder column")
    for e in ex:                                                                    # 4 MRN + study date
        if e["row"] is None and e.get("study_date") and mrn_of(e):
            r = one([r for r in rows if r.get("study_date") == e["study_date"] and _s(r["mrn"]) == mrn_of(e) and not acc_conflict(e, r)])
            if r: take(e, r, "MRN + study date")
    def rows_of_patient(e):
        if fi == "name": return [r for r in rows if r["patient_name"] and _s(r["patient_name"]).lower() == _s(e["patient_folder"]).lower().replace("_", " ")]
        if fi == "code": return [r for r in rows if r["code"] and _s(r["code"]) == _s(e["patient_folder"])]
        m = mrn_of(e); return [r for r in rows if m and r["mrn"] and _s(r["mrn"]) == m]
    groups = {}
    for e in ex:
        k = (f"mrn:{mrn_of(e)}" if mrn_of(e) else "") if fi in ("mrn", "none", "accession") else f"folder:{e['patient_idx']}"
        if k: groups.setdefault(k, []).append(e)
    for k, g in groups.items():                                                     # 5 the only examination + the only row of a patient
        free_e = [e for e in g if e["row"] is None]; free_r = [r for r in rows_of_patient(g[0]) if r["row"] not in used]
        if len(free_e) == 1 and len(free_r) == 1 and not acc_conflict(free_e[0], free_r[0]): take(free_e[0], free_r[0], "only examination of this patient")
    for e in ex:
        e["header_conflict"] = ""
        if e["row"] is None and e.get("dicom_accession"):
            c = [r for r in rows if r["row"] not in used and acc_conflict(e, r) and ((mrn_of(e) and _s(r["mrn"]) == mrn_of(e)) or (r.get("folder") and _nf(r["folder"]) == _nf(e["relfolder"])))]
            if c: e["header_conflict"] = f"manifest row {c[0]['row']} looks like this examination, but its accession number differs from the scan header - not matched"


def _row(plan, n): return next((r for r in plan["rows"] if r["row"] == n), None)


def set_library(plan, lib, verify_dest=None):
    L = plan["library"]
    if "enabled" in lib: L["enabled"] = bool(lib["enabled"])
    if "whole_exam" in lib: L["whole_exam"] = bool(lib["whole_exam"])
    if "root" in lib: L["root"] = os.path.realpath(os.path.expanduser(_s(lib["root"]))) if _s(lib["root"]) else ""
    if not L["root"]: L["root_ok"], L["root_why"] = False, "choose the study library folder"
    else:
        ok, why = verify_dest(L["root"]) if verify_dest else (os.path.isdir(L["root"]), "not a folder")
        L["root_ok"], L["root_why"] = bool(ok), ("" if ok else why)


def patient_code(plan, e):
    """Incognito library folder of the patient: the de-identified patient folder name ('' = the patient's pseudonym, decided at import)"""
    if plan["folder_is"] == "code" and e["n_in_folder"] > 1 and MF.CODE_RE.fullmatch(_s(e["patient_folder"])): return _s(e["patient_folder"])
    if plan["folder_is"] == "code" and e["sub"] and MF.CODE_RE.fullmatch(_s(e["patient_folder"])): return _s(e["patient_folder"])
    return ""


def library_place(plan, e):
    i = ids(plan, e)
    if plan["mode"] == "standard": return SL.place("standard", mrn=i["mrn"], accession=i["accession"])
    if not i["code"]: return "", "the study code is generated at import - its library folder is made then"
    return SL.place("incognito", study_code=i["code"])


def revalidate(plan, ID=None, existing_file_keys=()):
    mode = plan["mode"]; errs = [dict(eid="", msg=m) for m in plan["header_problems"]]; warns = []
    if mode == "standard" and ID is not None:
        if getattr(ID, "app_lock_enabled", False) and not ID.unlocked():
            errs.append(dict(eid="", msg="unlock the identity vault: Standard mode stores MRN, name and accession only in the encrypted vault"))
    if mode == "incognito" and ID is not None:
        if not ID.vault_exists() or not ID.unlocked():
            errs.append(dict(eid="", msg="enter the vault passphrase: the key (MRN, name, accession number, code) is stored only in the encrypted vault - the screens stay de-identified"))
    if plan["folder_is"] == "none" and plan["rows"] and any(not r.get("folder") for r in plan["rows"]):
        errs.append(dict(eid="", msg="the folder names are irrelevant: every Excel row must name its examination's folder (column 'folder') - rows " +
                         ", ".join(str(r["row"]) for r in plan["rows"] if not r.get("folder"))[:120] + " have none"))
    L = plan["library"]
    if L["enabled"] and not L["root_ok"]: errs.append(dict(eid="", msg=f"study library folder refused: {L['root_why']}"))
    inc = [e for e in plan["exams"] if e["include"]]
    I = {e["eid"]: ids(plan, e) for e in plan["exams"]}
    ex_codes = {str(c).upper() for c in list(existing_file_keys) + ([s["deid_code"] for s in ID.R["studies"].values()] if ID else [])}
    ex_acc = set()
    if ID is not None and ID.unlocked(): ex_acc = {_s(v.get("accession")).upper() for v in ID._vault["studies"].values() if v.get("accession")}
    rows_used = [e["row"] for e in inc if e["row"] is not None]
    for n in {n for n in rows_used if rows_used.count(n) > 1}: errs.append(dict(eid="", msg=f"manifest row {n} is assigned to more than one examination"))
    all_acc = [I[e["eid"]]["accession"].upper() for e in inc if I[e["eid"]]["accession"]]
    all_code = [I[e["eid"]]["code"].upper() for e in inc if I[e["eid"]]["code"]]
    names_by_mrn = {}
    for e in inc:
        i = I[e["eid"]]
        if mode == "standard" and i["mrn"] and i["name"]: names_by_mrn.setdefault(i["mrn"], set()).add(i["name"].lower())
    for m, ns in names_by_mrn.items():
        if len(ns) > 1: errs.append(dict(eid="", msg="one MRN has different patient names in this import - correct the Excel file before importing (never merged on a name)"))
    for e in plan["exams"]:
        e["problems"] = []; e["notes"] = []; i = I[e["eid"]]
        r = _row(plan, e["row"]) if e["row"] is not None else None
        if not e["chosen"].get("SWI"): e["problems"].append("no SWI chosen - pick the SWI series (Series…) or untick the examination")
        if e.get("header_conflict") and e["row"] is None: e["problems"].append(e["header_conflict"])
        if plan["manifest"] and r is None and (plan["folder_is"] == "none" or mode == "incognito"): e["problems"].append("no Excel row assigned - choose the row of this examination")
        elif plan["manifest"] and r is None and plan["rows"]: e["notes"].append("no Excel row for this examination")
        if True:                                                                    # both modes: MRN + accession from the user
            if not i["accession"]: e["problems"].append("accession number missing (Excel file or accession-number folder names; never generated)")
            if not i["mrn"]: e["problems"].append("MRN missing (Excel file or MRN folder names)")
            if i["accession"] and all_acc.count(i["accession"].upper()) > 1 and e["include"]: e["problems"].append("this accession number is used by more than one examination of this import")
            if i["accession"] and i["accession"].upper() in ex_acc: e["problems"].append("this accession number already exists in this project (see the duplicate check)")
        if not i["code"] and mode == "incognito":
            e["problems"].append("code missing - in Incognito every examination needs its code (Excel file, code folder names, or type it)")
        if i["accession"] and e.get("dicom_accession") and i["accession"].upper() != _s(e["dicom_accession"]).upper():
            e["notes"].append("the scan header has a different accession number - check that this is the right examination")
        if i["code"] and not MF.CODE_RE.fullmatch(i["code"]): e["problems"].append(f"study code {i['code']!r}: use 1-32 letters, digits, - or _")
        if i["code"] and e["include"] and all_code.count(i["code"].upper()) > 1: e["problems"].append(f"study code {i['code']} is used by more than one examination of this import")
        if i["code"] and i["code"].upper() in ex_codes: e["problems"].append(f"study code {i['code']} already exists in this project")
        if ID is not None:
            c = ID.classify(fingerprint=e.get("fingerprint", ""), dicom_study_uid=e.get("dicom_study_uid", ""), accession=i["accession"] if mode == "standard" else (r or {}).get("accession", ""),
                            institution=e.get("dicom_institution", ""), deid_code=i["code"], mrn=i["mrn"])
            e["duplicate"] = c; ch = e.get("dup_choice", ""); e["dup_target"] = ""
            if c.get("retired_note"): e["notes"].append(c["retired_note"])
            if c["kind"] in ("same_exam", "conflict"):                   # v5.20: the user decides - skip / replace / import and keep the old for ML / cancel
                d = plan["hooks"].get("describe"); e["dup_other"] = d(c["study_uuid"]) if d and c.get("study_uuid") else {}
                if ch in ("replace", "keep_ml"):
                    e["dup_target"] = c["study_uuid"]; e["include"] = True; e.pop("excluded_why", None)
                    e["problems"] = [p for p in e["problems"] if "already exists" not in p and "already used" not in p]
                elif c["kind"] == "same_exam" or ch == "skip":
                    if e["include"] or not e.get("excluded_why"): e["include"] = False; e["excluded_why"] = c["why"] + (" - skipped" if ch == "skip" else "")
                    e["problems"] = [p for p in e["problems"] if "already exists" not in p]
                else:
                    e["problems"].append(c["why"] + " - choose: skip, replace the old study, import and keep the old results for ML, or cancel and correct the identifier")
        e["library_rel"], e["library_why"] = library_place(plan, e) if L["enabled"] else ("", "")
        e["library_state"] = ""
        if L["enabled"] and L["root_ok"] and e["library_rel"]:
            d = os.path.join(L["root"], e["library_rel"])
            if os.path.exists(d):
                try:
                    import json
                    same = bool(e.get("fingerprint")) and json.load(open(os.path.join(d, "percival_library.json"))).get("fingerprint") == e.get("fingerprint")
                except Exception: same = False
                try: owner = json.load(open(os.path.join(d, "percival_library.json"))).get("study_uuid", "")
                except Exception: owner = ""
                if same and not e.get("dup_target"): e["library_state"] = "already in the library"
                elif e.get("dup_target") and owner == e["dup_target"]: e["library_state"] = "replaces the old study's library copy (it goes to the Trash)"
                else: e["problems"].append("the study library already has a different examination in this folder - check the identifiers (nothing is overwritten)")
        if e["check"] == "cannot" and "no SWI" not in " ".join(e["problems"]): e["problems"].append(e["pathway_reason"])
        lln = plan["hooks"].get("looks_like_name")
        if lln and plan["folder_is"] in ("code", "accession", "mrn") and any(lln(x) for x in (e["patient_folder"], e["sub"]) if x):
            e["notes"].append("a folder name looks like a person's name - check what the folder names are (step 2)")
        if e.get("reuse_src"):
            e["reuse_ok"] = e["reuse_src"]["code"] not in set(existing_file_keys) and not (ID is not None and ID.by_file_key(e["reuse_src"]["code"]))
            if e.get("reuse") and not e["reuse_ok"]: e["notes"].append("processed before, but its key is already used in this project - it will be processed again")
        if e["include"]:
            errs += [dict(eid=e["eid"], msg=f"examination {e['eid']}: {m}") for m in e["problems"]]
    if not plan["processing"].get("cohort"): warns.append(dict(eid="", msg="no cohort chosen - the studies are added without a cohort (processing options)"))
    if ID is not None and not ID.unlocked() and any(r["mrn"] or r["patient_name"] or r["accession"] for r in plan["rows"]):
        warns.append(dict(eid="", msg="the Excel file holds MRN / name / accession values: they are NOT stored (identity vault locked) and never shown in Incognito"))
    if L["enabled"] and mode == "standard":
        warns.append(dict(eid="", msg="Standard library folders are named by MRN and accession number: keep the library on an encrypted local disk (FileVault); never sync it to a cloud"))
    plan["errors"], plan["warnings"] = errs, warns; plan["ok"] = not errs and any(e["include"] for e in plan["exams"])
    return plan


def update(plan_id, changes, ID=None, existing_file_keys=(), verify_dest=None):
    """changes: [dict(eid, row?, include?, display_name?, code?, pathway?, series?{TYPE: index | ''}) | dict(library={...}) | dict(processing={...})]"""
    p = PLANS.get(plan_id)
    if not p: raise ValueError("this import preview expired - start again")
    for c in changes:
        if "library" in c: set_library(p, c["library"] or {}, verify_dest); continue
        if "processing" in c:
            p["processing"].update({k: _s(v) for k, v in (c["processing"] or {}).items() if k in p["processing"]})
            for e in p["exams"]: _pathway(p, e)
            continue
        e = next((x for x in p["exams"] if x["eid"] == c.get("eid")), None)
        if not e: continue
        if "row" in c: e["row"] = int(c["row"]) if c["row"] not in (None, "") else None; e["matched_by"] = "assigned by you"
        if "include" in c: e["include"] = bool(c["include"]); e.pop("excluded_why", None) if c["include"] else None
        if "display_name" in c: e["display_name"] = str(c["display_name"])[:120]
        if "code" in c: e["code_override"] = _s(c["code"])[:32]
        if "pathway" in c: e["pathway"] = _s(c["pathway"]); e["pathway_user"] = e["pathway"] != e.get("pathway_rec")
        if "reuse" in c: e["reuse"] = bool(c["reuse"])
        if "dup_choice" in c:
            if c["dup_choice"] not in ("", "skip", "replace", "keep_ml"): raise ValueError("unknown duplicate choice")
            e["dup_choice"] = c["dup_choice"]
            if c["dup_choice"] in ("", "skip"): e["include"] = False if c["dup_choice"] == "skip" else e["include"]
        if "series" in c:
            for t, i in (c["series"] or {}).items():
                if t not in SER_TYPES: continue
                if i in (None, ""): e["chosen"].pop(t, None)
                else:
                    i = int(i)
                    if not 0 <= i < len(e["series"]): raise ValueError("unknown series")
                    e["chosen"][t] = e["series"][i]["path"]
            e["user_series"] = {t: e["chosen"].get(t) for t in SER_TYPES} != {t: e["auto"].get(t) for t in SER_TYPES}
            _fingerprint(e); _pathway(p, e)
    return revalidate(p, ID, existing_file_keys)


def series_view(plan_id, eid):
    """every series of an examination for the manual choice (Incognito: no folder / file names)"""
    plan = PLANS.get(plan_id)
    if not plan: raise ValueError("this import preview expired - start again")
    e = next(x for x in plan["exams"] if x["eid"] == eid); inc = plan["mode"] == "incognito"; out = []
    for i, s in enumerate(e["series"]):
        x = dict(i=i, type=s.get("type"), format=s.get("format"), description=s.get("description", ""), voxel=s.get("voxel"), files=s.get("files"),
                 te=s.get("te"), mr_acq=s.get("mr_acq", ""), reason=s.get("reason", ""), shape=s.get("shape"), usable_t1=SD.t1_quality(s)[2] if s.get("type") == "T1" else "",
                 chosen_as=[t for t in SER_TYPES if e["chosen"].get(t) == s["path"]], auto_as=[t for t in SER_TYPES if e["auto"].get(t) == s["path"]])
        if not inc: x["name"] = s.get("name", "")
        out.append(x)
    return dict(eid=eid, series=out, auto_why=e.get("auto_why", {}), user_series=bool(e.get("user_series")))


def thumb(plan_id, eid, i):
    """PNG of the middle slice of series i (made on this computer)"""
    p = PLANS.get(plan_id)
    if not p: raise ValueError("this import preview expired - start again")
    e = next(x for x in p["exams"] if x["eid"] == eid); s = e["series"][int(i)]
    import numpy as np
    if s.get("format") == "NIfTI":
        import nibabel as nib
        d = np.asanyarray(nib.load(s["path"]).dataobj)
        while d.ndim > 3: d = d[..., 0]
        a = d[:, :, d.shape[2] // 2].T[::-1] if d.ndim == 3 else d
    else:
        import pydicom
        fs = sorted(f for f in os.listdir(s["path"]) if not f.startswith("."))
        a = pydicom.dcmread(os.path.join(s["path"], fs[len(fs) // 2]), force=True).pixel_array
        while a.ndim > 2: a = a[a.shape[0] // 2]
    a = a.astype(float); lo, hi = np.percentile(a, [1, 99.5]) if a.size else (0, 1)
    a = np.clip((a - lo) / ((hi - lo) or 1), 0, 1)
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    h, w = a.shape; fig = plt.figure(figsize=(2.2 * w / max(h, w), 2.2 * h / max(h, w)), dpi=80); ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
    ax.imshow(a, cmap="gray", interpolation="nearest", aspect="auto"); bio = io.BytesIO(); fig.savefig(bio, format="png"); plt.close(fig)
    return bio.getvalue()


def advice(e):
    """warnings (warn) and recommendations (info) about the chosen series of one examination"""
    out = []; ser = {s["path"]: s for s in e["series"]}; ch = e["chosen"]
    sw, t1, fl = ser.get(ch.get("SWI")), ser.get(ch.get("T1")), ser.get(ch.get("FLAIR"))
    n_swi = sum(1 for s in e["series"] if s.get("ok") and s.get("type") == "SWI")
    if not sw: out.append(("warn", "no SWI chosen - pick the SWI series, or untick the examination"))
    elif sw.get("type") != "SWI": out.append(("warn", f"the chosen SWI was detected as {sw.get('type') or 'unknown'} - check that it is the susceptibility magnitude"))
    if n_swi > 1 and sw: out.append(("info", f"{n_swi} SWI series - the highest resolution was chosen; check it is the full-brain magnitude"))
    if not t1: out.append(("warn", "no usable T1 - the SWI-only pathway runs (alone, less accurate anatomy); choose a T1 if there is one"))
    else:
        u, _, why = SD.t1_quality(t1)
        if not u: out.append(("warn", f"the chosen T1 is not usable for anatomy: {why}"))
        elif "2-D" in why: out.append(("warn", f"the chosen T1 is 2-D ({why}) - a 3-D T1 gives more accurate anatomy"))
    for s in [s for s in e["series"] if s.get("ok") and s.get("type") == "T1" and s["path"] != ch.get("T1")][:2]:
        u, _, why = SD.t1_quality(s)
        out.append(("info", f"another T1 was not chosen: {why}" + ("" if not u else " - the chosen one ranks higher (3-D, finer, whole brain)")))
    if e.get("overlap", "").startswith("different"): out.append(("warn", f"T1 and SWI: {e['overlap']} - check the T1 is from the same visit"))
    if not fl: out.append(("info", "no FLAIR chosen (optional)" + (" - one is available" if any(s.get("type") == "FLAIR" for s in e["series"]) else "")))
    if ch.get("PHASE") is None and any(s.get("type") == "PHASE" for s in e["series"]): out.append(("info", "a phase series is available (optional)"))
    if e.get("user_series"): out.append(("info", "series chosen by you"))
    return [dict(level=l, msg=m) for l, m in out]


def view(plan):
    """what the browser may see. Incognito: no MRN / name / accession / folder names / paths."""
    inc = plan["mode"] == "incognito"
    pts = [dict(idx=p["idx"], label="" if inc else p["folder_name"], n_exams=p["n_exams"]) for p in plan["patients"]]
    ex = []
    for e in plan["exams"]:
        i = ids(plan, e)
        x = dict(eid=e["eid"], patient_idx=e["patient_idx"], include=e["include"], excluded_why=e.get("excluded_why", ""), problems=e["problems"], notes=e.get("notes", []),
                 matched_by=e.get("matched_by", ""), row=e["row"], display_name=e["display_name"], has_swi=bool(e["chosen"].get("SWI")),
                 series=[dict(type=s.get("type"), voxel=s.get("voxel"), format=s.get("format")) for s in e["series"] if s.get("type") in SER_TYPES],
                 chosen={t: next((k for k, s in enumerate(e["series"]) if s["path"] == e["chosen"].get(t)), None) for t in SER_TYPES if e["chosen"].get(t)},
                 auto_why=e.get("auto_why", {}), user_series=bool(e.get("user_series")), n_series=len(e["series"]),
                 duplicate=dict(kind=(e.get("duplicate") or {}).get("kind", ""), why=(e.get("duplicate") or {}).get("why", "")),
                 dup_choice=e.get("dup_choice", ""), dup_other=e.get("dup_other", {}),
                 reuse=bool(e.get("reuse") and e.get("reuse_src") and e.get("reuse_ok", True)), reuse_possible=bool(e.get("reuse_src") and e.get("reuse_ok", True)),
                 reuse_from=(dict(kind=e["reuse_src"]["kind"], code=e["reuse_src"]["code"] if not inc else "") if e.get("reuse_src") else {}),
                 code=i["code"], code_source=i["code_src"], code_generated=not i["code"] and plan["mode"] == "standard",
                 library=e.get("library_rel", "") if plan["library"]["enabled"] else "", library_state=e.get("library_state", ""), library_why=e.get("library_why", ""),
                 check=e.get("check", ""), pathway=e.get("pathway", ""), pathway_rec=e.get("pathway_rec", ""), pathway_reason=e.get("pathway_reason", ""), overlap=e.get("overlap", ""),
                 has_grades=bool(i["grade_R"] or i["grade_L"]), advice=advice(e),
                 all_series=[dict(i=k, type=s.get("type") or "?", description=(s.get("description") or "")[:60], voxel=s.get("voxel"), files=s.get("files"))
                             for k, s in enumerate(e["series"]) if s.get("ok")])
        if not inc:
            x.update(patient_folder=e["patient_folder"], sub=e["sub"], mrn=i["mrn"], mrn_source=i["mrn_src"], patient_name=i["name"], accession=i["accession"],
                     accession_source=i["accession_src"], study_date=e.get("study_date", ""), radiologist=i["radiologist"], grade_R=i["grade_R"], grade_L=i["grade_L"])
        ex.append(x)
    rows = MF.redact(plan["rows"], plan["mode"])
    msgs = lambda L: [dict(eid=m["eid"], msg=m["msg"]) for m in L]
    L = plan["library"]
    return dict(id=plan["id"], mode=plan["mode"], folder_is=plan["folder_is"], sub_is=plan["sub_is"], has_subfolders=plan.get("has_subfolders", False), layout=plan.get("layout", ""),
                generate_codes=plan["generate_codes"], patients=pts, exams=ex, rows=rows,
                errors=msgs(plan["errors"]), warnings=msgs(plan["warnings"]), ok=plan["ok"], n_exams=len(plan["exams"]), n_include=sum(e["include"] for e in plan["exams"]),
                recommend_incognito=plan["folder_is"] == "code" and plan["mode"] == "standard", processing=dict(plan["processing"]),
                library=dict(enabled=L["enabled"], root=L["root"], whole_exam=L["whole_exam"], root_ok=L.get("root_ok", False), root_why=L.get("root_why", "")))


def _neutral_copy(chosen, fk, root, tick=None):
    """copy the chosen series into the project under NEUTRAL names (fast copy or APFS clone when on same device: no extra disk space)
    so that no source path - which can hold an MRN or a patient name - is stored by the app: root/<file key>/<TYPE>_series.<ext> (+ sidecar) or
    root/<file key>/<TYPE>/ for a DICOM series"""
    import shutil, subprocess
    if not root: return dict(chosen)
    out = {}; d = os.path.join(root, fk); os.makedirs(d, exist_ok=True)
    try:
        dest_dev = os.stat(d).st_dev
    except Exception:
        dest_dev = None

    def cp(a, b):
        try:
            # Check if same filesystem device before attempting clone
            if dest_dev is not None and os.stat(a).st_dev == dest_dev:
                if subprocess.run(["cp", "-c", a, b], capture_output=True).returncode == 0:
                    return
        except Exception:
            pass
        # High performance copy across filesystems (e.g. ExFAT USB to internal APFS)
        shutil.copyfile(a, b)

    for k, src in chosen.items():
        if os.path.isdir(src):
            t = os.path.join(d, k); os.makedirs(t, exist_ok=True)
            fl = sorted(x for x in os.listdir(src) if not x.startswith(".") and os.path.isfile(os.path.join(src, x)))
            for i, f in enumerate(fl):
                cp(os.path.join(src, f), os.path.join(t, f"{k}_{i:05d}.dcm"))
                if tick and (i % 25 == 0 or i == len(fl) - 1): tick(f"{k} {i + 1}/{len(fl)} files")
            out[k] = t
        else:
            ext = ".nii.gz" if src.endswith(".nii.gz") else ".nii"; t = os.path.join(d, f"{k}_series{ext}"); cp(src, t)
            js = re.sub(r"\.nii(\.gz)?$", ".json", src)
            if os.path.exists(js): cp(js, os.path.join(d, f"{k}_series.json"))
            out[k] = t
    return out


def commit(plan_id, ID, add_to_queue, settings, by=""):
    """create patient / study records (uuids; identifiers in the vault), queue the included examinations under their file keys, then
    copy them into the study library in the background (originals untouched)"""
    p = PLANS.get(plan_id)
    if not p: raise ValueError("this import preview expired - start again")
    for k in ("cohort", "anatomy", "run_mode", "results_dir"):
        if settings.get(k): p["processing"][k] = settings[k]
    revalidate(p, ID)
    if not p["ok"]: raise ValueError("the preview still has errors - nothing was imported")
    mode = p["mode"]; inc = [e for e in p["exams"] if e["include"]]; patients = {}; items = []; out = []
    made = settings.setdefault("_copies_made", [])
    try: return _commit(p, ID, add_to_queue, settings, by, mode, inc, patients, items, out)
    except Exception:
        ID.R = ID._load_registry()                        # any failure before the queue: no half-made identity records
        if ID.unlocked(): ID.unlock_reload()
        _drop_copies(made)                                # ... and no orphan image copies (they used to stay in app_data/import_src)
        raise


def _drop_copies(paths):
    """remove the neutral copies made by a failed import attempt (the app's own copies under import_src - originals are never touched)"""
    import shutil
    for d in paths:
        if os.path.basename(os.path.dirname(d)) == "import_src" and os.path.isdir(d): shutil.rmtree(d, ignore_errors=True)


def _commit(p, ID, add_to_queue, settings, by, mode, inc, patients, items, out):
    lib_items = []; P = p["processing"]; reuse_items = []; reuse_src = {}
    res = [e for e in inc if e.get("dup_target") and e.get("dup_choice") in ("replace", "keep_ml")]
    if res:                                                                   # v5.20: resolve duplicates first (old study purged / retired)
        rs = settings.get("_resolve")
        if not rs: raise ValueError("duplicate resolution is not available here")
        if any(e["dup_choice"] == "replace" for e in res) and settings.get("_replace_confirm") != "REPLACE":
            raise ValueError("type REPLACE to confirm: replacing purges the old studies (files to the Trash)")
        for e in res:
            fk = (ID.R["studies"].get(e["dup_target"]) or {}).get("file_key")
            if fk: rs(e["dup_choice"], fk)
        ID.R = ID._load_registry()                                            # the resolution committed its own changes
        if ID.unlocked(): ID.unlock_reload()
    rep = settings.get("_progress") or (lambda *a, **k: None); n_inc = len(inc)
    for n_e, e in enumerate(inc):
        i = ids(p, e)
        code = i["code"]; generated = False
        if not code: code = ID.unique_code(); e["generated_code"] = code; generated = True
        fk = code if MF.CODE_RE.fullmatch(code) and not ID.by_file_key(code) else ID.unique_code()
        reuse = bool(e.get("reuse") and e.get("reuse_src") and e.get("reuse_ok", True) and settings.get("_reuse"))
        if reuse: fk = e["reuse_src"]["code"]                 # the processed files keep the key they were made under
        pkey = (f"mrn:{i['mrn']}" if i["mrn"] and (mode == "standard" or i["mrn_src"] in ("Excel", "folder name")) else "") or \
               (f"pid:{e['dicom_patient_id']}" if e.get("dicom_patient_id") and p["folder_is"] in ("none", "accession") else "") or f"folder:{e['patient_idx']}"
        if pkey not in patients:
            mrn = i["mrn"] if ID.unlocked() else ""; nm = i["name"] if ID.unlocked() else ""
            existing = ID.patients_by_mrn(mrn) if mrn and ID.unlocked() else []
            patients[pkey] = existing[0] if len(existing) == 1 else ID.add_patient(pseudonym=patient_code(p, e) or (e["patient_folder"] if p["folder_is"] == "code" and MF.CODE_RE.fullmatch(_s(e["patient_folder"])) else ""),
                                                                                    mrn=mrn, name=nm, by=by)
        su = ID.add_study(patients[pkey], fk, code, display_name=e["display_name"], accession=i["accession"] if ID.unlocked() else "",
                          institution=e.get("dicom_institution", "") if ID.unlocked() else "", dicom_study_uid=e.get("dicom_study_uid", "") if ID.unlocked() else "",
                          fingerprint=e.get("fingerprint", ""), source="add studies", by=by,
                          identity_basis="import:" + pkey.split(":", 1)[0])            # v5.25: mrn | pid | folder (the grouping you chose)
        rep(n_e, f"Copying examination {n_e + 1} of {n_inc} ({fk}) into the project")
        if settings.get("_import_src") and not os.path.isdir(os.path.join(settings["_import_src"], fk)): settings.setdefault("_copies_made", []).append(os.path.join(settings["_import_src"], fk))
        chosen_copy = _neutral_copy(e["chosen"], fk, settings.get("_import_src"), tick=lambda t, _n=n_e, _fk=fk: rep(_n, f"Copying examination {_n + 1} of {n_inc} ({_fk}): {t}", log=False))
        (reuse_items if reuse else items).append(dict(folder_name=fk, folder="", code=fk, name="", chosen=chosen_copy,
                          fingerprint=e.get("fingerprint", ""), fingerprint_v1="", radiologist=i["radiologist"], grade_R=i["grade_R"], grade_L=i["grade_L"],
                          pathway=e.get("pathway") or e.get("pathway_rec") or "", pathway_rec=e.get("pathway_rec", ""), pathway_reason=e.get("pathway_reason", ""),
                          check=e.get("check", ""), decided=True))
        out.append(dict(eid=e["eid"], study_uuid=su, file_key=fk, deid_code=code, generated=generated, user_series=bool(e.get("user_series")), reused=reuse))
        if reuse: reuse_src[fk] = e["reuse_src"]
        L = p["library"]
        if L["enabled"]:
            if mode == "standard": rel, why = SL.place("standard", mrn=i["mrn"], accession=i["accession"])
            else: rel, why = SL.place("incognito", study_code=code)
            if rel:
                lib_items.append(dict(code=fk, study_uuid=su, rel=rel, identifiable=mode == "standard", fingerprint=e.get("fingerprint", ""),
                                      files=SL.layout(e["chosen"], e["series"], L["whole_exam"], mode),
                                      meta=dict(study_uuid=su, file_key=fk, deid_code=code, layout=mode, whole_exam=L["whole_exam"], app="Percival")))
    def rollback():                                       # nothing committed yet: drop the new identity records (memory only)
        ID.R = ID._load_registry()
        if ID.unlocked(): ID.unlock_reload()
    qs = dict(settings, cohort=P["cohort"] or settings.get("cohort", ""), anatomy=P["anatomy"], mode=P["run_mode"], results_dir=P["results_dir"])
    rep(n_inc, "Registering the studies and adding them to the processing queue")
    try: q = add_to_queue(items, qs)
    except Exception: rollback(); raise
    if not q.get("ok"): rollback(); raise ValueError("queue refused: " + "; ".join(q.get("errors", [])))
    ID.commit(); PLANS.pop(p["id"], None)
    for it in reuse_items:                                    # bring in the earlier processing; if that fails, process normally
        src = reuse_src[it["code"]]
        try: settings["_reuse"](src["project"], it["code"], qs, it)
        except Exception as ex:
            for o in out:
                if o["file_key"] == it["code"]: o["reused"] = False; o["reuse_error"] = str(ex)[:200]
            add_to_queue([it], qs)
    job = ""
    if lib_items:
        root = p["library"]["root"]
        def done(it, res):
            if res["state"] in ("copied", "already"):
                try: ID.set_library(it["study_uuid"], root, it["rel"], it["identifiable"]); ID.commit()
                except Exception: pass
        job = SL.start_job(root, lib_items, on_item=done)
    return dict(ok=True, imported=out, queued=q.get("added", []), library_job=job, library_n=len(lib_items))
