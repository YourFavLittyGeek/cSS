"""manifest.py - the Percival import manifest (Excel), v5.16. One row = one MRI EXAMINATION. Research software; local only.

Template Percival_Import_Template.xlsx ALWAYS has these four columns, in this order (both modes):
    MRN | patient_name | accession_number | code (de-identifier)
Standard mode: accession_number is the required, unique study identifier; MRN (+ name) group the examinations into patients.
Incognito mode: code (de-identifier) is the study identifier: required unless Percival may generate it; it must be unique. Identifiable
columns are NOT shown in Incognito screens and are never copied into the de-identified registry (only into the encrypted vault, when
it is unlocked). Validation never merges records on a patient name or an MRN alone.
v5.18: OPTIONAL columns after the four: folder (the examination's folder, relative to the data folder - used when the folder names
mean nothing), study_date (YYYY-MM-DD or YYYYMMDD - helps to match an examination by MRN + date), radiologist, grade_R and grade_L
(the radiologist's cSS grades 0-2, previously a separate grades file). Older files with four columns
still work."""
import io, re

COLUMNS = ["MRN", "patient_name", "accession_number", "code (de-identifier)"]
KEY = {"MRN": "mrn", "patient_name": "patient_name", "accession_number": "accession", "code (de-identifier)": "code"}
OPTIONAL = ["folder", "study_date", "radiologist", "grade_R", "grade_L"]
OKEY = {"folder": "folder", "study_date": "study_date", "radiologist": "radiologist", "grade_R": "grade_R", "grade_L": "grade_L"}
EXAMPLE = [("123456", "John Smith", "ACC-001", "STUDY-001", "", "", "", "", ""), ("123456", "John Smith", "ACC-002", "STUDY-002", "", "", "", "", ""),
           ("789012", "Mary Jones", "ACC-003", "STUDY-003", "", "", "", "", "")]
CODE_RE = re.compile(r"[A-Za-z0-9_\-]{1,32}")


def template_bytes(example=True):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.comments import Comment
    wb = Workbook(); ws = wb.active; ws.title = "examinations"; ws.append(COLUMNS + OPTIONAL)
    for c in ws[1]: c.font = Font(bold=True); c.fill = PatternFill("solid", fgColor="DDE7F7")
    notes = ["patient MRN (Standard mode; groups examinations of one patient)", "patient name (Standard mode)",
             "accession number of THIS examination - required and unique in Standard mode", "de-identified study code of THIS examination - required "
             "and unique in Incognito mode (Percival can generate missing codes once)",
             "OPTIONAL: folder of THIS examination, relative to the data folder (e.g. folder_07 or batch2/exam_3) - use it when the folder names "
             "mean nothing", "OPTIONAL: study date of THIS examination (YYYY-MM-DD) - helps to match it by MRN + date",
             "OPTIONAL: radiologist who graded this examination", "OPTIONAL: radiologist's right-hemisphere cSS grade (0, 1 or 2)",
             "OPTIONAL: radiologist's left-hemisphere cSS grade (0, 1 or 2)"]
    for c, n in zip(ws[1], notes): c.comment = Comment(n, "Percival")
    if example:
        for r in EXAMPLE: ws.append(list(r))
    for col, w in zip("ABCDEFGHI", (14, 24, 20, 26, 26, 14, 16, 10, 10)): ws.column_dimensions[col].width = w
    info = wb.create_sheet("read me")
    for line in ("One row = one MRI examination. Repeat MRN and name on every row of the same patient.",
                 "Standard mode: accession_number is required and must be unique. Incognito mode: code (de-identifier) must be unique.",
                 "The example rows are illustrative - replace them.", "Keep the first four columns, in this order, in both modes.",
                 "folder and study_date are optional: fill them when the folder names do not tell which examination a row describes.",
                 "radiologist, grade_R and grade_L are optional: the radiologist's cSS grades (0-2 per hemisphere) for the agreement statistics.",
                 "This file holds identifiable data: store it only on this computer, never in cloud folders, e-mail or chat."):
        info.append([line])
    info.column_dimensions["A"].width = 120
    bio = io.BytesIO(); wb.save(bio); return bio.getvalue()


def read(path):
    """-> (rows [dict(row, mrn, patient_name, accession, code)], header problems). Reads xlsx or csv; every cell as text."""
    import pandas as pd
    df = pd.read_csv(path, dtype=str) if path.lower().endswith(".csv") else pd.read_excel(path, dtype=str, sheet_name=0)
    cols = [str(c).strip() for c in df.columns]
    probs = []
    if cols[:4] != COLUMNS: probs.append(f"the first four columns must be exactly {COLUMNS} in this order (found {cols[:4]})")
    df.columns = cols
    rows = []
    for i, r in df.iterrows():
        v = {KEY[c]: ("" if c not in df.columns or str(r.get(c)) in ("nan", "None") else str(r.get(c)).strip()) for c in COLUMNS}
        if not any(v.values()): continue
        for c in OPTIONAL: v[OKEY[c]] = "" if c not in df.columns or str(r.get(c)) in ("nan", "None", "NaT") else str(r.get(c)).strip()
        v["study_date"] = norm_date(v["study_date"])
        for g in ("grade_R", "grade_L"):
            x = re.sub(r"\.0$", "", v[g]); v[g] = x if x in ("0", "1", "2") else ""
        rows.append(dict(row=int(i) + 2, **v))                      # Excel row number (header = row 1)
    return rows, probs


def norm_date(x):
    """YYYY-MM-DD / YYYYMMDD / an Excel date -> YYYYMMDD (DICOM StudyDate form); '' when not a date"""
    m = re.match(r"^\s*(\d{4})-?(\d{2})-?(\d{2})", str(x or ""))
    return "".join(m.groups()) if m else ""


def validate(rows, mode, generate_codes=False, existing_codes=(), existing_accessions=()):
    """-> dict(ok, errors [dict(row, msg)], warnings, patients [{key, rows}], rows). Never merges on name / MRN alone; conflicting patient
    information is reported for correction."""
    errs, warns = [], []
    seen_acc, seen_code = {}, {}
    exist_c = {str(c).upper() for c in existing_codes}; exist_a = {str(a).upper() for a in existing_accessions}
    for r in rows:
        a, c = r["accession"], r["code"]
        if mode == "standard":
            if not a: errs.append(dict(row=r["row"], msg="accession_number is required in Standard mode"))
            if not r["mrn"]: errs.append(dict(row=r["row"], msg="MRN is required in Standard mode (it groups the examinations of one patient)"))
        else:
            if not c and not generate_codes: errs.append(dict(row=r["row"], msg="code (de-identifier) is required in Incognito mode (or let Percival generate missing codes)"))
        if c and not CODE_RE.fullmatch(c): errs.append(dict(row=r["row"], msg=f"code {c!r}: use 1-32 letters, digits, - or _"))
        if a:
            k = a.upper()
            if k in seen_acc: errs.append(dict(row=r["row"], msg=f"accession_number {a} also on row {seen_acc[k]} - each examination needs its own"))
            elif k in exist_a: errs.append(dict(row=r["row"], msg=f"accession_number {a} already exists in this project (see the duplicate check)"))
            seen_acc.setdefault(k, r["row"])
        if c:
            k = c.upper()
            if k in seen_code: errs.append(dict(row=r["row"], msg=f"code {c} also on row {seen_code[k]} - each examination needs its own"))
            elif k in exist_c: errs.append(dict(row=r["row"], msg=f"code {c} already exists in this project (see the duplicate check)"))
            seen_code.setdefault(k, r["row"])
    # patient grouping: Standard = by MRN; conflicting names on one MRN, and one name on several MRNs, are flagged (never merged)
    groups = {}
    for r in rows:
        key = r["mrn"] if mode == "standard" or r["mrn"] else f"row{r['row']}"
        groups.setdefault(key, []).append(r)
    for k, g in groups.items():
        names = {x["patient_name"].strip().lower() for x in g if x["patient_name"]}
        if len(names) > 1: errs.append(dict(row=g[0]["row"], msg=f"MRN {k}: different patient names on rows {', '.join(str(x['row']) for x in g)} - correct before import"))
    byname = {}
    for k, g in groups.items():
        for x in g:
            if x["patient_name"]: byname.setdefault(x["patient_name"].strip().lower(), set()).add(k)
    for n, ks in byname.items():
        if len(ks) > 1 and all(not k.startswith("row") for k in ks):
            warns.append(dict(row=0, msg=f"the same patient name appears with {len(ks)} different MRNs - kept as different patients (not merged)"))
    return dict(ok=not errs, errors=errs, warnings=warns, patients=[dict(key=k, rows=[x["row"] for x in g], n_exams=len(g)) for k, g in groups.items()], rows=rows)


def redact(rows, mode):
    """rows as they may be shown in the given mode: Incognito never shows MRN, name or accession"""
    if mode == "standard": return rows
    return [dict(row=r["row"], code=r["code"], has_identifiers=bool(r["mrn"] or r["patient_name"] or r["accession"])) for r in rows]
