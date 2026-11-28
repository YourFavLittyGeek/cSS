"""identity_gui.py - the app's side of patient / examination identification (v5.16): global Standard / Incognito mode, the encrypted
identity vault, audited identifier edits, the guided import, and SERVER-SIDE redaction (Incognito, or a locked vault, never returns
an MRN, patient name or accession number - whatever the screen asks for). Research software; everything stays on this computer.
Mode lives in settings (identity_mode); the vault key only in memory for this app session."""
import os, re
import identity as IDM
import import_wizard as IW
import manifest as MF

ST = dict(ID=None)


def init(B, PAT, SET):
    app_lock = SET.get("app_lock_enabled", None)
    ID = IDM.Identity(B, app_lock_enabled=app_lock)
    ST["ID"] = ID
    SET.setdefault("identity_mode", "standard" if ID.vault_exists() else "incognito")
    SET.setdefault("app_lock_enabled", ID.app_lock_enabled)
    ID.migrate_existing(PAT)                                          # additive: uuid + patient per existing study; nothing renamed
    return ID


def ID(): return ST["ID"]
def mode(SET): return SET.get("identity_mode", "standard")
def reveal(SET):
    if not SET.get("app_lock_enabled", False) and not ID().app_lock_enabled:
        return mode(SET) == "standard"
    return mode(SET) == "standard" and ID().unlocked()


def ensure(PAT):
    """every study the app knows has an identity record (studies added by the older Add-studies flow get one too)"""
    I = ID(); n = 0
    for p in PAT:
        if not I.by_file_key(p["code"]):
            pu = I.add_patient(by="add studies"); I.add_study(pu, p["code"], p["code"] if not I.by_deid(p["code"]) else I.unique_code(),
                                                            fingerprint=str(p.get("fingerprint", "")), source="add studies", by="add studies",
                                                            identity_basis=IDM.ASSUMED); n += 1
    if n: I.commit()
    return n


def rekey(old, new):
    """the older Add-studies flow may change a study's code BEFORE processing (no file exists yet): its file key follows, audited"""
    I = ID(); u = I.by_file_key(old)
    if not u: return
    s = I.study(u); s["file_key"] = new
    if s["deid_code"] == old and not I.by_deid(new): s["deid_code"] = new
    I.R["history"].append(dict(time=IDM._now(), study_uuid=u, patient_uuid=s["patient_uuid"], field="file_key (before processing)", old=old, new=new, by="add studies", reason="code changed before processing"))
    I.commit()


def ident(code, SET):
    """the identity fields a screen may show for one study (file key) in the current mode"""
    I = ID(); u = I.by_file_key(code)
    if not u: return dict(study_id=code, id_kind="study code", deid_code=code)
    v = I.view(u, mode(SET)); v.pop("institution", None) if not reveal(SET) else None
    return v


def state(SET, PAT):
    I = ID(); ex = [ident(p["code"], SET) for p in PAT]
    return dict(mode=mode(SET), vault_exists=I.vault_exists(), unlocked=I.unlocked(), revealing=reveal(SET),
                app_lock_enabled=SET.get("app_lock_enabled", False), n_studies=len(I.R["studies"]),
                encryption=("passphrase" if I.vault_exists() else "device_key" if os.path.exists(I.vlocal_path) else
                            "none (plaintext)" if os.path.exists(I.vjson_path) else "not created yet"),
                vault_problem=I.problem, migrated=getattr(I, "migrated", None),
                n_patients=len(I.R["patients"]), accession_missing=sum(1 for v in ex if v.get("accession_missing")),
                template_columns=MF.COLUMNS)


def set_mode(SET, new, passphrase="", save=None):
    I = ID()
    if new not in ("standard", "incognito"): raise ValueError("mode must be standard or incognito")
    if new == "incognito":
        I.lock()
    elif I.vault_exists() and not I.unlocked():
        if not passphrase: return dict(ok=False, needs_passphrase=True, error="enter the vault passphrase to show patient identities")
        I.unlock(passphrase)
    SET["identity_mode"] = new
    if save: save()
    return dict(ok=True, mode=new, unlocked=I.unlocked())


def vault(op, d, SET, names=None, verify_dest=None):
    I = ID()
    if op == "enable_lock":
        I.enable_app_lock(str(d.get("passphrase", "")))
        SET["app_lock_enabled"] = True
        return dict(ok=True, app_lock_enabled=True)
    if op == "disable_lock":
        I.disable_app_lock(str(d.get("passphrase", "")))
        SET["app_lock_enabled"] = False
        return dict(ok=True, app_lock_enabled=False)
    if op == "create":
        I.create_vault(str(d.get("passphrase", "")))
        n = I.copy_names_into_vault(names() if names else {})
        return dict(ok=True, names_copied=n, note="private/names.csv was not changed")
    if op == "unlock":
        I.unlock(str(d.get("passphrase", ""))); n = I.copy_names_into_vault(names() if names else {}); return dict(ok=True, names_copied=n)
    if op == "lock": I.lock(); return dict(ok=True)
    if op == "change": I.change_passphrase(str(d.get("old", "")), str(d.get("new", ""))); return dict(ok=True)
    if op == "backup":
        ok, why = verify_dest(d.get("dest", "")) if verify_dest else (True, "")
        if not ok: return dict(ok=False, error=f"backup refused: {why}")
        return dict(ok=True, path=I.backup_vault(os.path.realpath(os.path.expanduser(d["dest"]))), note="the backup stays encrypted; keep the passphrase separately")
    if op == "recovery_key":                       # 2026-11-28: shown on request only, typed confirmation, never logged
        if str(d.get("confirm", "")) != "SHOW RECOVERY KEY": return dict(ok=False, error="type SHOW RECOVERY KEY to show it")
        return dict(ok=True, **I.recovery_key(), note="write it down or keep it in a password manager - OFFLINE; it opens the identity vault on any Mac")
    if op == "restore_recovery_key": return dict(ok=True, **I.restore_recovery_key(str(d.get("recovery_key", ""))))
    if op == "validate": return I.validate_vault_file(d["path"], str(d.get("passphrase", "")))
    if op == "restore": return dict(ok=True, **I.restore_vault(d["path"], str(d.get("passphrase", ""))))
    raise ValueError(f"unknown vault operation {op}")


def edit(d, SET, by):
    """study-level (one examination) or patient-level (all examinations of the patient) edit, audited"""
    I = ID(); code = str(d.get("code", "")); u = I.by_file_key(code)
    if not u: raise ValueError("unknown study")
    reason = str(d.get("reason", ""))[:300]; s = I.study(u)
    sensitive = any(k in d for k in ("accession", "institution", "mrn", "patient_name"))
    if sensitive and not reveal(SET): raise IDM.VaultLocked("switch to Standard mode and unlock the vault to edit MRN, name or accession")
    if sensitive and d.get("confirm") is not True: return dict(ok=False, needs_confirm=True, error="confirm the identity change")
    if any(k in d for k in ("deid_code", "display_name", "accession", "institution")):
        I.edit_study(u, by=by, reason=reason, **{k: d[k] for k in ("deid_code", "display_name", "accession", "institution") if k in d})
    if any(k in d for k in ("mrn", "patient_name", "pseudonym")):
        I.edit_patient(s["patient_uuid"], by=by, reason=reason, **{("name" if k == "patient_name" else k): d[k] for k in ("mrn", "patient_name", "pseudonym") if k in d})
    return dict(ok=True, study=ident(code, SET))


def history(code, SET):
    I = ID(); u = I.by_file_key(code)
    H = I.history(include_sensitive=reveal(SET))
    s = I.study(u) if u else None
    return [h for h in H if s and (h.get("study_uuid") == u or (not h.get("study_uuid") and h.get("patient_uuid") == s["patient_uuid"]))]


# ------------------------------------------------------------------ import wizard
def plan(d, SET, file_keys, verify_dest=None, hooks=None):
    lib = d.get("library")
    if lib is None: lib = dict(enabled=bool(SET.get("library_dir")), root=SET.get("library_dir", ""), whole_exam=bool(SET.get("library_whole_exam")))
    p = IW.new_plan(str(d.get("folder", "")), str(d.get("folder_is", "")), str(d.get("mode", "")), str(d.get("manifest", "") or ""),
                    bool(d.get("generate_codes")), ID(), file_keys, library=lib, verify_dest=verify_dest, sub_is=str(d.get("sub_is", "") or ""),
                    hooks=hooks, processing=d.get("processing") or {})
    return IW.view(p)


def plan_update(d, file_keys, verify_dest=None):
    return IW.view(IW.update(str(d.get("plan", "")), d.get("changes", []), ID(), file_keys, verify_dest=verify_dest))


def library_of(code):
    """where the examination's library copy is (Standard layout only while the vault is unlocked)"""
    u = ID().by_file_key(code)
    return ID().library(u) if u else {}


def plan_commit(d, add_to_queue, settings, by, import_src=""):
    if d.get("confirm") is not True: return dict(ok=False, needs_confirm=True, error="confirm the validated preview to import")
    settings = dict(settings, _import_src=import_src)
    return IW.commit(str(d.get("plan", "")), ID(), add_to_queue, settings, by=by)


# ------------------------------------------------------------------ redaction helpers for other screens
_ABS = re.compile(r"(?<![\w.])/(?:Users|Volumes|private|var|tmp|home|mnt|media)/[^\s'\"<>]*")


def redact_text(text, SET, base):
    """log / error text shown in the GUI: in Incognito (or locked) absolute paths outside the project are hidden (source folders can be
    named after patients); known identifiers of this session are never present because the vault is locked there."""
    if reveal(SET): return text
    def sub(m):
        p = m.group(0)
        return p if p.startswith(base) else "<path hidden in Incognito>"
    return _ABS.sub(sub, text or "")


def requires_accession(code, SET):
    """Standard mode: new processing / re-processing / export of a study need its accession number first (never generated)"""
    if mode(SET) != "standard": return ""
    v = ident(code, SET)
    if v.get("locked"): return "unlock the identity vault (Standard mode) first"
    return "enter the accession number of this study first (Studies › Edit identifiers)" if v.get("accession_missing") else ""
