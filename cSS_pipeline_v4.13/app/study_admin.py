"""study_admin.py - v5.20 study administration: identifier checkpoint, edits, archive, Remove (keep for ML), Purge, retirement. Local only.

Checkpoint (check_ids) - one rule set used before ANY identifier is saved (edit, import, restore, bring-in): the de-identified code must not
be used by another examination nor equal another study's internal file key; the accession number (with its institution) must not belong to
another examination; a library folder must not already hold a different examination. Archived studies keep their identifiers reserved.

Edits are all-or-nothing (Identity.transaction): patient fields (MRN, name), examination fields (accession, code, display name) and the
cohort are checked first, then applied together, then propagated: the study library folder is renamed (Standard <MRN>/<accession>,
Incognito <code>), the results workbook is rebuilt. Files inside the project are named by the permanent internal file key and need no change.

Archive: hidden from Studies / Activity / Review lists, every file kept; restored unchanged. Training includes archived studies unless the
setting "train_include_archived" is switched off.

Remove (keep for ML): images and processing files go to the Trash; candidate tables, every reviewer's calls, labels, scores, features and
image patches are kept. The study is RETIRED: it gets a new internal key RET-xxxx-xxxx-xxxx (kept files renamed), its accession number and
code are released (the old values stay only in the encrypted audit), so a future import of the same examination is not a duplicate.
Purge: every file of the study (and its study library copy) goes to the Trash; the identity record is deleted; the audit keeps the event.
Both refuse a study that is processing.
"""
import datetime, glob, json, os, re, shutil, subprocess, time

KEEP_EXT = (".csv", ".json", ".npz", ".npy", ".txt", ".xlsx", ".tsv")


def now(): return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ------------------------------------------------------------------ checkpoint
def check_ids(I, file_keys, code=None, accession=None, institution="", exclude=None):
    """-> list of reasons why the identifiers cannot be used (empty = OK). exclude: the study's own uuid"""
    errs = []
    if code is not None:
        c = str(code).strip()
        if not c: errs.append("the code cannot be empty")
        elif not re.fullmatch(r"[A-Za-z0-9_\-]{1,32}", c): errs.append(f"code {c!r}: use 1-32 letters, digits, - or _")
        else:
            o = I.by_deid(c)
            if o and o != exclude: errs.append(f"code {c} is already used by another examination" + (" (archived)" if I.R["studies"][o].get("archived") else ""))
            fk_owner = I.by_file_key(c)
            if fk_owner and fk_owner != exclude: errs.append(f"code {c} equals another study's internal key")
            elif c in set(file_keys) and not fk_owner: errs.append(f"code {c} equals another study's internal key")
    if accession is not None:
        a = str(accession).strip()
        if not a: errs.append("the accession number cannot be empty")
        elif not I.unlocked(): errs.append("unlock the identity vault to check the accession number")
        else:
            o = [u for u in I.by_accession(a, institution) if u != exclude]
            if o: errs.append(f"accession number {a} already belongs to another examination" + (" (archived)" if I.R["studies"][o[0]].get("archived") else ""))
    return errs


# ------------------------------------------------------------------ files of a study
def study_files(B, AD, fk):
    """every path (file or folder) of the study inside the project"""
    pats = [f"{B}/data/{fk}_*", f"{B}/data/{fk}", f"{B}/raw/{fk}", f"{B}/work/{fk}_*", f"{B}/work/{fk}", f"{B}/review/{fk}_*", f"{B}/review/call_history/{fk}_*",
            f"{B}/subjects/{fk}", f"{B}/synthseg/{fk}", f"{B}/synthseg/{fk}_*", f"{B}/runs/{fk}", f"{B}/results/{fk}_*", f"{B}/results/*/{fk}_*",
            f"{B}/uscore/reports/{fk}.json", f"{B}/unified_engine/shadow/{fk}.json", f"{B}/unified_engine/image_ml/{fk}*", f"{AD}/import_src/{fk}",
            f"{AD}/staging/{fk}", f"{AD}/qc/{fk}.png", f"{AD}/logs/{fk}.log", f"{B}/logs/{fk}_*"]
    out = []
    for p in pats:
        for x in glob.glob(p):
            if x not in out and (os.path.isfile(x) or os.path.isdir(x) or os.path.islink(x)): out.append(x)
    return out


def ml_keep(path, B):
    """kept by Remove (keep for ML): results / calls / labels / scores / features / patches - never images or processing outputs"""
    rel = os.path.relpath(path, B)
    if os.path.isdir(path): return False
    if rel.startswith(("review" + os.sep, "uscore" + os.sep, "unified_engine" + os.sep, "results" + os.sep)) and path.endswith(KEEP_EXT): return True
    return "patch" in os.path.basename(path).lower() and path.endswith((".npz", ".npy", ".json"))


def size_of(paths):
    n = 0
    for p in paths:
        if os.path.isfile(p): n += os.path.getsize(p)
        elif os.path.isdir(p):
            for r, _, fs in os.walk(p):
                for f in fs:
                    try: n += os.path.getsize(os.path.join(r, f))
                    except OSError: pass
    return n


# ------------------------------------------------------------------ Trash
def to_trash(paths, B, label):
    """move paths to the macOS Trash (recoverable). Paths inside the project are first gathered in one folder on the same disk (fast rename),
    then that folder is trashed. CSS_TRASH_DIR overrides the Trash (tests). -> (where, n)"""
    paths = [p for p in paths if os.path.lexists(p)]
    if not paths: return "", 0
    stamp = time.strftime("%Y%m%d_%H%M%S"); stage = os.path.join(B, "app_data", "trash_staging", f"Percival_{label}_{stamp}")
    os.makedirs(stage, exist_ok=True); n = 0
    for p in paths:
        rel = os.path.relpath(p, B) if os.path.realpath(p).startswith(os.path.realpath(B) + os.sep) else os.path.join("outside_project", os.path.basename(p))
        t = os.path.join(stage, rel); os.makedirs(os.path.dirname(t), exist_ok=True)
        try: os.rename(p, t)
        except OSError: shutil.move(p, t)
        n += 1
    override = os.environ.get("CSS_TRASH_DIR")
    if override:
        os.makedirs(override, exist_ok=True); dest = os.path.join(override, os.path.basename(stage)); shutil.move(stage, dest); return dest, n
    r = subprocess.run(["osascript", "-e", f'tell application "Finder" to delete (POSIX file "{stage}" as alias)'], capture_output=True, text=True)
    if r.returncode == 0: return "the Trash", n
    dest = os.path.join(os.path.expanduser("~/.Trash"), os.path.basename(stage))
    try: shutil.move(stage, dest); return "the Trash", n
    except Exception: return stage, n                       # last resort: left in app_data/trash_staging (reported)


# ------------------------------------------------------------------ edit (transactional) + propagation
def edit(ctx, code, fields, by="app user", reason=""):
    """fields: any of mrn, patient_name, accession, deid_code, display_name, cohort. -> dict(ok, study, changes, library) or dict(ok=False, error)"""
    I = ctx["ID"](); u = I.by_file_key(code)
    if not u: return dict(ok=False, error="unknown study")
    s = I.study(u); f = {k: (str(v).strip() if v is not None else None) for k, v in fields.items()}
    sens = any(k in f for k in ("mrn", "patient_name", "accession"))
    if sens and not ctx["reveal"](): return dict(ok=False, error="switch to Standard mode and unlock the vault to edit MRN, patient name or accession number")
    cur = I.view(u, "standard" if I.unlocked() else "incognito")
    ch = {k: v for k, v in f.items() if v is not None and v != (cur.get(k) if k != "cohort" else (ctx["pget"](code) or {}).get("cohort", ""))}
    if not ch: return dict(ok=True, study=cur, changes={}, library="")
    errs = check_ids(I, ctx["file_keys"](), code=ch.get("deid_code"), accession=ch.get("accession"), institution=cur.get("institution", ""), exclude=u)
    if "mrn" in ch:
        if not ch["mrn"]: errs.append("the MRN cannot be empty")
        elif [x for x in I.patients_by_mrn(ch["mrn"]) if x != s["patient_uuid"]]:
            errs.append(f"MRN {ch['mrn']} belongs to another patient record - patients are never merged automatically")
    lib = I.library(u); new_rel = ""
    if lib and lib.get("rel") and not lib.get("locked"):
        if lib["layout"] == "standard" and ("mrn" in ch or "accession" in ch):
            import study_library as SL
            new_rel, why = SL.place("standard", mrn=ch.get("mrn", cur.get("mrn", "")), accession=ch.get("accession", cur.get("accession", "")))
        elif lib["layout"] == "incognito" and "deid_code" in ch:
            import study_library as SL
            new_rel, why = SL.place("incognito", study_code=ch["deid_code"])
        if new_rel and new_rel != lib["rel"] and os.path.exists(os.path.join(lib["root"], new_rel)):
            errs.append(f"the study library already has a folder for the new identifier - nothing was changed")
    if errs: return dict(ok=False, error="; ".join(errs), checkpoint=errs)
    def apply():
        st = {k: ch[k] for k in ("accession", "deid_code", "display_name") if k in ch}
        if st: I.edit_study(u, by=by, reason=reason, **st)
        pt = {("name" if k == "patient_name" else k): ch[k] for k in ("mrn", "patient_name") if k in ch}
        if pt: I.edit_patient(s["patient_uuid"], by=by, reason=reason, **pt)
        if new_rel and new_rel != lib["rel"]: I.set_library(u, lib["root"], new_rel, lib["layout"] == "standard")
    try: I.transaction(apply)
    except Exception as e: return dict(ok=False, error=str(e))
    libmsg = ""
    if new_rel and new_rel != lib["rel"]:                       # identifiers saved: now move the library folder (verified rename)
        src, dst = os.path.join(lib["root"], lib["rel"]), os.path.join(lib["root"], new_rel)
        if os.path.isdir(src):
            os.makedirs(os.path.dirname(dst), exist_ok=True); os.rename(src, dst); libmsg = "library folder renamed"
            try: os.rmdir(os.path.dirname(src))                 # empty old MRN folder
            except OSError: pass
        else: libmsg = "library folder not found (disk not connected?) - its record was updated; rename it when the disk is back"
    if "cohort" in ch:
        p = ctx["pget"](code)
        if p is not None: p["cohort"] = ch["cohort"]; ctx["save_pat"]()
    try: ctx["after_edit"](code)
    except Exception: pass
    return dict(ok=True, study=I.view(u, "standard" if I.unlocked() else "incognito"), changes={k: True for k in ch}, library=libmsg)


# ------------------------------------------------------------------ archive
def archive(ctx, codes, on, by="app user"):
    I = ctx["ID"](); done = []
    for c in codes:
        p = ctx["pget"](c); u = I.by_file_key(c)
        if not p: continue
        if on and p.get("status") in ("running", "starting", "paused"): continue
        if on: p["archived"] = dict(at=now(), by=by)
        else: p.pop("archived", None)
        if u:
            if on: I.R["studies"][u]["archived"] = True
            else: I.R["studies"][u].pop("archived", None)
            I.R["history"].append(dict(time=now(), action="archived" if on else "restored", study_uuid=u, by=by))
        done.append(c)
    ctx["save_pat"](); I.commit(); return dict(ok=True, done=done, skipped=[c for c in codes if c not in done])


# ------------------------------------------------------------------ remove / purge / retire
def pensieve_copy(ctx, code):
    """the study's copy on the Pensieve drive (2026-11-25): None, or dict(state, path, exists, bytes). state in_pensieve = the
    images are ONLY there; copied = also on the Mac"""
    try:
        with open(os.path.join(ctx["B"], "review", f"{code}_pensieve.json")) as f: m = json.load(f)
    except (OSError, ValueError):
        return None
    vault = (ctx.get("vault") or (lambda: ""))() or ""
    p = os.path.join(vault, "studies", code) if vault else ""
    ex = bool(p) and os.path.isdir(p)
    st = "in_pensieve" if m.get("state") in ("in_pensieve", "deleting") else m.get("state", "")
    return dict(state=st, path=p, exists=ex, bytes=size_of([p]) if ex else 0, versions=m.get("versions") or [m.get("version")])


def drive_trash(path, label):
    """move a folder on the Pensieve drive to that drive's Trash (Finder; recoverable). CSS_TRASH_DIR overrides (tests)."""
    if not path or not os.path.isdir(path): return "", 0
    override = os.environ.get("CSS_TRASH_DIR")
    if override:
        os.makedirs(override, exist_ok=True); dest = os.path.join(override, f"Pensieve_{label}_{time.strftime('%Y%m%d_%H%M%S')}")
        shutil.move(path, dest); return dest, 1
    r = subprocess.run(["osascript", "-e", f'tell application "Finder" to delete (POSIX file "{path}" as alias)'], capture_output=True, text=True)
    if r.returncode != 0: raise RuntimeError(f"the Pensieve copy could not be moved to the Trash: {(r.stderr or r.stdout).strip()[:200]}")
    return "the Pensieve drive's Trash", 1


def plan_removal(ctx, codes, mode):
    """-> what Remove / Purge would do, per study: files to the Trash, files kept, sizes; refusals"""
    B, AD = ctx["B"], ctx["AD"]; I = ctx["ID"](); out = []
    for c in codes:
        p = ctx["pget"](c); u = I.by_file_key(c)
        if not p: out.append(dict(code=c, refused="unknown study")); continue
        if p.get("status") in ("running", "starting", "paused"): out.append(dict(code=c, refused="processing - stop it first")); continue
        fs = study_files(B, AD, c)
        keep = [x for x in fs if mode == "remove" and ml_keep(x, B)]
        gone = [x for x in fs if x not in keep]
        lib = I.library(u) if u else {}
        libp = os.path.join(lib["root"], lib["rel"]) if lib and lib.get("rel") else ""
        calls = len([x for x in fs if re.search(r"_calls(_[^/]*)?\.csv$", x)])
        out.append(dict(code=c, trash=gone, keep=keep, library=libp if libp and os.path.isdir(libp) else "", library_locked=bool(lib and lib.get("locked")),
                        n_trash=len(gone), n_keep=len(keep), bytes_trash=size_of(gone) + (size_of([libp]) if libp and os.path.isdir(libp) else 0), bytes_keep=size_of(keep),
                        has_calls=calls > 0, pensieve=pensieve_copy(ctx, c)))
    return out


def _rekey_files(paths, old, new):
    """rename kept files old -> new key and replace the exact key token inside text files (csv / json / txt)"""
    tok = re.compile(rf"(?<![A-Za-z0-9_\-]){re.escape(old)}(?![A-Za-z0-9_\-])"); out = []
    for p in paths:
        d, b = os.path.split(p); nb = b.replace(old, new, 1) if b.startswith(old) else b; np_ = os.path.join(d, nb)
        if p.endswith((".csv", ".json", ".txt", ".tsv")):
            try:
                with open(p, errors="strict") as f: t = f.read()
                t2 = tok.sub(new, t)
                with open(p + ".tmp", "w") as f: f.write(t2)
                os.replace(p + ".tmp", p)
            except UnicodeDecodeError: pass
        if np_ != p: os.rename(p, np_)
        out.append(np_)
    return out


def retire(ctx, code, by="app user", reason=""):
    """the study keeps its results / calls for ML under a new internal key; its accession and code are released. -> new key"""
    I = ctx["ID"](); u = I.by_file_key(code); p = ctx["pget"](code)
    if not p: raise ValueError("unknown study")
    new = I.unique_code(prefix="RET")
    B, AD = ctx["B"], ctx["AD"]
    keep = [x for x in study_files(B, AD, code) if ml_keep(x, B)]
    def apply():
        if u:
            s = I.R["studies"][u]; old_code = s["deid_code"]
            I._audit(False, u, s["patient_uuid"], "deid_code", old_code, new, by, reason or "retired (kept for ML)")
            s.update(file_key=new, deid_code=new, retired=dict(at=now(), by=by, reason=reason or "kept for machine learning", fingerprint=s.get("fingerprint", ""),
                                                             dicom_uid_hash=s.get("dicom_uid_hash", "")))
            s["fingerprint"] = ""; s["dicom_uid_hash"] = ""         # a later import of the same images is not a duplicate (noted, not blocked)
            s.pop("archived", None); s.pop("library_root", None); s.pop("library_rel", None); s.pop("library_layout", None)
            if I.unlocked():
                vs = I._vault["studies"].setdefault(u, {})
                if vs.get("accession"): I._audit(True, u, s["patient_uuid"], "accession", vs["accession"], "", by, "released on retirement")
                vs["accession_released"] = vs.get("accession", ""); vs["accession"] = ""; vs.pop("library_rel", None)
            else:
                raise ValueError("unlock the identity vault: retiring releases the accession number (kept in the encrypted audit)")
    I.transaction(apply)
    _rekey_files(keep, code, new)
    p.update(code=new, status="retired", retired=dict(at=now(), by=by, from_key=code)); p.pop("archived", None)
    ctx["save_pat"](); return new


def purge_identity(I, code, by="app user"):
    u = I.by_file_key(code)
    if not u: return
    pu = I.R["studies"][u]["patient_uuid"]
    def apply():
        I.R["studies"].pop(u, None); I.R["history"].append(dict(time=now(), action="purged", study_uuid=u, file_key=code, by=by))
        if I._vault is not None:
            vs = I._vault["studies"].pop(u, None)
            I._vault["history"].append(dict(time=now(), action="purged", study_uuid=u, accession=(vs or {}).get("accession", ""), by=by))
        if not any(s["patient_uuid"] == pu for s in I.R["studies"].values()):
            I.R["patients"].pop(pu, None)
            if I._vault is not None: I._vault["patients"].pop(pu, None)
    I.transaction(apply)


def remove(ctx, codes, mode, by="app user", delete_library=True, pensieve=None):
    """mode: 'remove' (keep for ML, retire) or 'purge'. pensieve: what happens to a copy on the Pensieve drive - 'keep' (stays
    on the drive, marked detached) or 'trash' (the drive's Trash); required when a study has one. -> dict(ok, done, refused, trash)"""
    if mode not in ("remove", "purge"): raise ValueError("mode must be remove or purge")
    I = ctx["ID"](); B = ctx["B"]; plan = plan_removal(ctx, codes, mode); done, refused, where = [], [], ""
    for x in plan:
        if x.get("refused"): refused.append(dict(code=x["code"], why=x["refused"])); continue
        c = x["code"]; pv = x.get("pensieve")
        if pv and pv.get("exists") and pensieve not in ("keep", "trash"):
            refused.append(dict(code=c, why="this study has a copy on the Pensieve drive: choose to keep it there or move it to the drive's Trash")); continue
        if mode == "remove" and not I.unlocked():
            refused.append(dict(code=c, why="unlock the identity vault (the accession number is released into the encrypted audit)")); continue
        paths = list(x["trash"]) + ([x["library"]] if delete_library and x["library"] else [])
        if pv and pv.get("exists") and pensieve == "trash":
            try: drive_trash(pv["path"], c)
            except RuntimeError as e: refused.append(dict(code=c, why=str(e))); continue
        where, n = to_trash(paths, B, c)
        if mode == "purge":
            purge_identity(I, c, by); ctx["drop_pat"](c); done.append(dict(code=c, purged=True, trashed=n))
        else:
            new = retire(ctx, c, by, reason="removed - results kept for machine learning"); done.append(dict(code=c, retired_as=new, trashed=n, kept=x["n_keep"]))
            mk = os.path.join(B, "review", f"{new}_pensieve.json")            # the marker moved with the review files: never restore from it
            if os.path.exists(mk):
                try:
                    with open(mk) as f: m = json.load(f)
                    m.update(state="detached", detached_reason=f"study removed (results kept as {new}); drive copy "
                             + ("kept under " + os.path.join("studies", c) if pensieve == "keep" else "moved to the drive's Trash"), original_code=c)
                    with open(mk + ".tmp", "w") as f: json.dump(m, f, indent=1)
                    os.replace(mk + ".tmp", mk)
                except (OSError, ValueError): pass
    try: ctx["after_edit"](None)
    except Exception: pass
    return dict(ok=not refused, done=done, refused=refused, trash=where)
