"""identity.py - Percival patient / MRI-examination identification (v5.16): Standard and Incognito modes, permanent internal UUIDs,
an encrypted local identity vault, unique study identifiers, audited edits, examination-level duplicate classification.
Research software. Everything stays on this computer.

Identifiers of one MRI EXAMINATION (a study):
  study_uuid    permanent, generated here, never editable, never shown as an identifier
  file_key      the key every pipeline file is named with (data/<key>_swi.nii, review/<key>_*). Existing studies: their current code.
                New imports: a generated opaque code (never an accession number, MRN or name). It never changes.
  deid_code     de-identified study code: REQUIRED and unique in the project; editable (audited); Incognito identifier
  accession     accession number: REQUIRED in Standard mode, unique per institution; editable (audited); stored ONLY in the vault
  display_name  free text ("Brain MRI - SWI"); never an identity
Patient: patient_uuid (permanent) + pseudonym (de-identified patient identity, editable) in the registry; MRN and name ONLY in the vault.
Files:
  app_data/identity/registry.json   NO direct identifiers: uuids, file keys, deid codes, pseudonyms, display names, fingerprints,
                                    the non-sensitive edit history
  private/identity_vault.enc        AES-256-GCM, key = scrypt(passphrase): MRN, names, accessions, institution, DICOM StudyInstanceUID,
                                    the sensitive edit history (old / new values). A backup copy is kept before every write.
The vault is unlocked per app session with the passphrase; Incognito mode, lock() or quit forget the key. While locked or in Incognito,
no function of this module returns an MRN, name or accession."""
import base64, datetime, hashlib, json, os, re, secrets, shutil, threading, uuid

SCHEMA = "percival-identity/1.0"
VAULT_SCHEMA = "percival-identity-vault/1.0"
CODE_RE = re.compile(r"[A-Za-z0-9_\-]{1,32}")
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"            # no 0/O, 1/I/L, U: unambiguous to read and type
SCRYPT = dict(n=2 ** 15, r=8, p=1, dklen=32)
MAXMEM = 64 * 1024 * 1024                                        # scrypt n=2^15, r=8 needs 32 MiB (+ overhead); OpenSSL's default cap is 32 MiB
LOCK = threading.Lock()
MAX_VAULT_BACKUPS = 20


class VaultLocked(PermissionError): pass
class IdentityError(ValueError): pass


def _now(): return datetime.datetime.now().isoformat(timespec="seconds")


def new_code(prefix="PCV"):
    """cryptographically random de-identified study code, e.g. PCV-7KQ2-M9TX-4HDR (12 symbols of 30 ~ 59 bits)"""
    s = "".join(secrets.choice(CODE_ALPHABET) for _ in range(12))
    return f"{prefix}-{s[:4]}-{s[4:8]}-{s[8:]}"


def norm(x): return re.sub(r"\s+", " ", str(x or "").strip())


class Identity:
    def __init__(self, base):
        self.B = base; self.dir = os.path.join(base, "app_data", "identity"); self.vpath = os.path.join(base, "private", "identity_vault.enc")
        os.makedirs(self.dir, exist_ok=True); os.makedirs(os.path.dirname(self.vpath), exist_ok=True)
        self.rpath = os.path.join(self.dir, "registry.json"); self._key = None; self._vault = None; self.R = self._load_registry()

    # ------------------------------------------------------------------ registry (no direct identifiers)
    def _load_registry(self):
        if os.path.exists(self.rpath):
            with open(self.rpath) as f: R = json.load(f)
            if R.get("schema") != SCHEMA: raise IdentityError(f"unknown identity registry schema {R.get('schema')}")
            return R
        return dict(schema=SCHEMA, created=_now(), patients={}, studies={}, history=[])

    def _save_registry(self):
        tmp = self.rpath + ".tmp"
        with open(tmp, "w") as f: json.dump(self.R, f, indent=1)
        os.replace(tmp, self.rpath)

    # ------------------------------------------------------------------ vault (encrypted)
    def vault_exists(self): return os.path.exists(self.vpath)
    def unlocked(self): return self._key is not None

    def _derive(self, passphrase, salt):
        return hashlib.scrypt(passphrase.encode(), salt=salt, maxmem=MAXMEM, **SCRYPT)

    def _encrypt(self, obj):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        nonce = secrets.token_bytes(12); ct = AESGCM(self._key).encrypt(nonce, json.dumps(obj).encode(), VAULT_SCHEMA.encode())
        return json.dumps(dict(schema=VAULT_SCHEMA, kdf=dict(name="scrypt", salt=base64.b64encode(self._salt).decode(), **{k: v for k, v in SCRYPT.items()}),
                               cipher="AES-256-GCM", nonce=base64.b64encode(nonce).decode(), data=base64.b64encode(ct).decode())).encode()

    def _decrypt(self, blob, passphrase):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.exceptions import InvalidTag
        h = json.loads(blob)
        if h.get("schema") != VAULT_SCHEMA: raise IdentityError("not a Percival identity vault")
        salt = base64.b64decode(h["kdf"]["salt"]); key = hashlib.scrypt(passphrase.encode(), salt=salt, n=h["kdf"]["n"], r=h["kdf"]["r"], p=h["kdf"]["p"], dklen=h["kdf"]["dklen"], maxmem=MAXMEM)
        try: obj = json.loads(AESGCM(key).decrypt(base64.b64decode(h["nonce"]), base64.b64decode(h["data"]), VAULT_SCHEMA.encode()))
        except InvalidTag: raise VaultLocked("wrong passphrase (or the vault file was altered)")
        return key, salt, obj

    def create_vault(self, passphrase):
        if self.vault_exists(): raise IdentityError("a vault already exists - unlock it, or restore a backup")
        if len(passphrase or "") < 10: raise IdentityError("choose a passphrase of at least 10 characters")
        self._salt = secrets.token_bytes(16); self._key = self._derive(passphrase, self._salt)
        self._vault = dict(created=_now(), patients={}, studies={}, history=[]); self._write_vault(); return True

    def unlock(self, passphrase):
        if not self.vault_exists(): raise IdentityError("no identity vault yet - create one first")
        with open(self.vpath, "rb") as f: blob = f.read()
        self._key, self._salt, self._vault = self._decrypt(blob, passphrase); return True

    def lock(self): self._key = None; self._vault = None

    def unlock_reload(self):
        """discard unsaved vault changes: re-read the vault from disk with the key of this session"""
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        if self._key is None: return
        with open(self.vpath, "rb") as f: h = json.loads(f.read())
        self._vault = json.loads(AESGCM(self._key).decrypt(base64.b64decode(h["nonce"]), base64.b64decode(h["data"]), VAULT_SCHEMA.encode()))

    def _need(self):
        if self._key is None: raise VaultLocked("the identity vault is locked")
        return self._vault

    def _write_vault(self):
        if self.vault_exists():                                      # versioned backup before every write
            bd = os.path.join(os.path.dirname(self.vpath), "vault_backups"); os.makedirs(bd, exist_ok=True)
            shutil.copy2(self.vpath, os.path.join(bd, f"identity_vault.{datetime.datetime.now():%Y%m%d_%H%M%S_%f}.enc"))
            old = sorted(os.listdir(bd))
            for f in old[:-MAX_VAULT_BACKUPS]: os.remove(os.path.join(bd, f))
        tmp = self.vpath + ".tmp"
        with open(tmp, "wb") as f: f.write(self._encrypt(self._vault))
        os.chmod(tmp, 0o600); os.replace(tmp, self.vpath)

    def change_passphrase(self, old, new):
        self.unlock(old)
        if len(new or "") < 10: raise IdentityError("choose a passphrase of at least 10 characters")
        self._salt = secrets.token_bytes(16); self._key = self._derive(new, self._salt); self._write_vault(); return True

    def backup_vault(self, dest_dir):
        """copy the ENCRYPTED vault to a verified local folder (it stays encrypted; the passphrase is needed to use it)"""
        self._need(); os.makedirs(dest_dir, exist_ok=True)
        out = os.path.join(dest_dir, f"percival_identity_vault_{datetime.datetime.now():%Y%m%d_%H%M%S}.enc"); shutil.copy2(self.vpath, out); return out

    def validate_vault_file(self, path, passphrase):
        with open(path, "rb") as f: _, _, obj = self._decrypt(f.read(), passphrase)
        return dict(ok=True, patients=len(obj.get("patients", {})), studies=len(obj.get("studies", {})))

    def restore_vault(self, path, passphrase):
        info = self.validate_vault_file(path, passphrase)
        if self.vault_exists():
            bd = os.path.join(os.path.dirname(self.vpath), "vault_backups"); os.makedirs(bd, exist_ok=True)
            shutil.copy2(self.vpath, os.path.join(bd, f"identity_vault.before_restore.{datetime.datetime.now():%Y%m%d_%H%M%S}.enc"))
        shutil.copy2(path, self.vpath); os.chmod(self.vpath, 0o600); self.unlock(passphrase); return info

    # ------------------------------------------------------------------ records
    def study(self, study_uuid): return self.R["studies"].get(study_uuid)
    def by_file_key(self, key): return next((u for u, s in self.R["studies"].items() if s["file_key"] == key), None)
    def by_deid(self, code): return next((u for u, s in self.R["studies"].items() if s["deid_code"] == code), None)

    def by_accession(self, accession, institution=""):
        V = self._need(); a = norm(accession).upper(); inst = norm(institution).upper()
        return [u for u, s in V["studies"].items() if norm(s.get("accession")).upper() == a and norm(s.get("institution")).upper() == inst and a]

    def patients_by_mrn(self, mrn):
        V = self._need(); m = norm(mrn)
        return [u for u, p in V["patients"].items() if m and norm(p.get("mrn")) == m]

    def unique_code(self, prefix="PCV"):
        for _ in range(1000):
            c = new_code(prefix)
            if not self.by_deid(c) and not self.by_file_key(c): return c
        raise IdentityError("could not generate a unique code")

    def add_patient(self, pseudonym="", mrn="", name="", by=""):
        pu = str(uuid.uuid4())
        self.R["patients"][pu] = dict(pseudonym=norm(pseudonym) or f"PT-{secrets.token_hex(4).upper()}", created=_now(), created_by=by)
        if mrn or name:
            V = self._need(); V["patients"][pu] = dict(mrn=norm(mrn), name=norm(name))
        return pu

    def add_study(self, patient_uuid, file_key, deid_code, display_name="", accession="", institution="", dicom_study_uid="", fingerprint="", source="import", by=""):
        if not CODE_RE.fullmatch(file_key or ""): raise IdentityError(f"invalid file key {file_key!r}")
        if self.by_file_key(file_key): raise IdentityError(f"file key {file_key} already belongs to another examination")
        if not norm(deid_code): raise IdentityError("every examination needs a de-identified study code")
        if self.by_deid(deid_code): raise IdentityError(f"de-identified study code {deid_code} is already used by another examination")
        if accession:
            V = self._need()
            if self.by_accession(accession, institution): raise IdentityError(f"accession number {accession} already exists" + (f" at {institution}" if institution else ""))
        su = str(uuid.uuid4())
        self.R["studies"][su] = dict(patient_uuid=patient_uuid, file_key=file_key, deid_code=norm(deid_code), display_name=norm(display_name), created=_now(),
                                     created_by=by, source=source, fingerprint=fingerprint,
                                     dicom_uid_hash=hashlib.sha256(dicom_study_uid.encode()).hexdigest() if dicom_study_uid else "")
        if accession or institution or dicom_study_uid:
            V = self._need(); V["studies"][su] = dict(accession=norm(accession), institution=norm(institution), dicom_study_uid=dicom_study_uid)
        return su

    # ------------------------------------------------------------------ v5.18 study library place (copy of the original examination)
    def set_library(self, study_uuid, root, rel, identifiable):
        """identifiable (Standard layout MRN/accession): the relative folder goes to the vault only; Incognito layout (codes): registry"""
        s = self.R["studies"][study_uuid]; s["library_root"] = root; s["library_layout"] = "standard" if identifiable else "incognito"
        if identifiable:
            V = self._need(); V["studies"].setdefault(study_uuid, {})["library_rel"] = rel; s.pop("library_rel", None)
        else: s["library_rel"] = rel

    def library(self, study_uuid):
        """-> dict(root, rel, layout, locked) of the examination's library copy ({} when it has none)"""
        s = self.R["studies"].get(study_uuid) or {}
        if not s.get("library_root"): return {}
        if s.get("library_layout") == "standard":
            if self._key is None: return dict(root=s["library_root"], rel="", layout="standard", locked=True)
            return dict(root=s["library_root"], rel=self._vault["studies"].get(study_uuid, {}).get("library_rel", ""), layout="standard", locked=False)
        return dict(root=s["library_root"], rel=s.get("library_rel", ""), layout="incognito", locked=False)

    def commit(self):
        if getattr(self, "_defer", False): return            # inside transaction(): written once at the end
        with LOCK:
            self._save_registry()
            if self._key is not None: self._write_vault()

    def transaction(self, fn):
        """v5.20 all-or-nothing change: fn() runs with commits deferred; on any error the registry and vault are restored in memory and
        nothing is written; on success everything is written once"""
        import copy
        snap = (copy.deepcopy(self.R), copy.deepcopy(self._vault) if self._vault is not None else None)
        self._defer = True
        try: out = fn()
        except Exception:
            self.R, self._vault = snap; self._defer = False; raise
        self._defer = False; self.commit(); return out

    # ------------------------------------------------------------------ migration of existing studies (additive)
    def migrate_existing(self, PAT, names=None, by="migration"):
        """every existing study gets a uuid + patient; its code stays its file key and becomes its deid code; names (private/names.csv)
        are copied into the vault when it is unlocked. Nothing is renamed or deleted. Returns the number of studies added."""
        n = 0
        for p in PAT:
            if self.by_file_key(p["code"]): continue
            nm = (names or {}).get(p["code"], "") if self.unlocked() else ""
            pu = self.add_patient(by=by, name=nm) if nm else self.add_patient(by=by)
            self.add_study(pu, p["code"], p["code"] if not self.by_deid(p["code"]) else self.unique_code(), source="existing study (before v5.16)",
                           fingerprint=str(p.get("fingerprint", "")), by=by); n += 1
        if n: self.R["history"].append(dict(time=_now(), action="migrate_existing", studies=n, by=by)); self.commit()
        return n

    def copy_names_into_vault(self, names, by="migration"):
        """names.csv (code -> name) into the vault for studies that have no name there yet (names.csv itself is not changed)"""
        V = self._need(); n = 0
        for su, s in self.R["studies"].items():
            nm = names.get(s["file_key"])
            if nm and not V["patients"].get(s["patient_uuid"], {}).get("name"):
                V["patients"].setdefault(s["patient_uuid"], {})["name"] = norm(nm); n += 1
        if n: V["history"].append(dict(time=_now(), action="names_csv_copied", n=n, by=by)); self.commit()
        return n

    # ------------------------------------------------------------------ views (the ONLY way identifiers leave this module)
    def view(self, study_uuid, mode):
        """what a screen may show for one examination in the given mode. In Incognito or while locked: never MRN / name / accession."""
        s = self.R["studies"][study_uuid]; p = self.R["patients"].get(s["patient_uuid"], {})
        out = dict(study_uuid=study_uuid, file_key=s["file_key"], deid_code=s["deid_code"], display_name=s["display_name"], patient_uuid=s["patient_uuid"],
                   patient_pseudonym=p.get("pseudonym", ""), n_exams_of_patient=sum(1 for x in self.R["studies"].values() if x["patient_uuid"] == s["patient_uuid"]),
                   in_library=bool(s.get("library_root")))
        if mode == "standard":
            if self._key is None: out.update(locked=True, study_id=s["deid_code"], id_kind="de-identified code (vault locked)")
            else:
                vs = self._vault["studies"].get(study_uuid, {}); vp = self._vault["patients"].get(s["patient_uuid"], {})
                out.update(mrn=vp.get("mrn", ""), patient_name=vp.get("name", ""), accession=vs.get("accession", ""), institution=vs.get("institution", ""),
                           study_id=vs.get("accession", ""), id_kind="accession number", accession_missing=not vs.get("accession"))
        else: out.update(study_id=s["deid_code"], id_kind="de-identified study code")
        return out

    # ------------------------------------------------------------------ audited edits
    def _audit(self, sensitive, study_uuid, patient_uuid, field, old, new, by, reason):
        e = dict(time=_now(), study_uuid=study_uuid, patient_uuid=patient_uuid, field=field, by=by, reason=reason)
        if sensitive: self._vault["history"].append(dict(e, old=old, new=new)); self.R["history"].append(dict(e, sensitive=True))
        else: self.R["history"].append(dict(e, old=old, new=new))

    def edit_study(self, study_uuid, by, reason="", deid_code=None, display_name=None, accession=None, institution=None):
        """study-level fields of ONE examination. Uniqueness checked before anything changes; uuid and file key never change."""
        s = self.R["studies"].get(study_uuid)
        if not s: raise IdentityError("unknown examination")
        if deid_code is not None:
            c = norm(deid_code)
            if not c: raise IdentityError("the de-identified study code cannot be empty")
            o = self.by_deid(c)
            if o and o != study_uuid: raise IdentityError(f"de-identified study code {c} is already used by another examination")
        if accession is not None or institution is not None:
            V = self._need(); vs = V["studies"].get(study_uuid, {})
            a = norm(accession if accession is not None else vs.get("accession", "")); inst = norm(institution if institution is not None else vs.get("institution", ""))
            if not a: raise IdentityError("the accession number cannot be empty")
            other = [u for u in self.by_accession(a, inst) if u != study_uuid]
            if other: raise IdentityError(f"accession number {a} already belongs to another examination")
        if deid_code is not None and norm(deid_code) != s["deid_code"]:
            self._audit(False, study_uuid, s["patient_uuid"], "deid_code", s["deid_code"], norm(deid_code), by, reason); s["deid_code"] = norm(deid_code)
        if display_name is not None and norm(display_name) != s["display_name"]:
            self._audit(False, study_uuid, s["patient_uuid"], "display_name", s["display_name"], norm(display_name), by, reason); s["display_name"] = norm(display_name)
        if accession is not None or institution is not None:
            vs = self._vault["studies"].setdefault(study_uuid, {})
            for k, v in (("accession", accession), ("institution", institution)):
                if v is not None and norm(v) != vs.get(k, ""):
                    self._audit(True, study_uuid, s["patient_uuid"], k, vs.get(k, ""), norm(v), by, reason); vs[k] = norm(v)
        self.commit(); return self.view(study_uuid, "standard" if self.unlocked() else "incognito")

    def edit_patient(self, patient_uuid, by, reason="", mrn=None, name=None, pseudonym=None):
        """patient-level fields: apply to every examination of the patient (they share the patient record)"""
        p = self.R["patients"].get(patient_uuid)
        if not p: raise IdentityError("unknown patient")
        if pseudonym is not None and norm(pseudonym) != p.get("pseudonym", ""):
            if not norm(pseudonym): raise IdentityError("the de-identified patient identity cannot be empty")
            self._audit(False, "", patient_uuid, "pseudonym", p.get("pseudonym", ""), norm(pseudonym), by, reason); p["pseudonym"] = norm(pseudonym)
        if mrn is not None or name is not None:
            V = self._need(); vp = V["patients"].setdefault(patient_uuid, {})
            if mrn is not None:
                m = norm(mrn); other = [u for u in self.patients_by_mrn(m) if u != patient_uuid]
                if other: raise IdentityError(f"MRN {m} already belongs to another patient record - merging patients is not done automatically")
            for k, v in (("mrn", mrn), ("name", name)):
                if v is not None and norm(v) != vp.get(k, ""):
                    self._audit(True, "", patient_uuid, k, vp.get(k, ""), norm(v), by, reason); vp[k] = norm(v)
        self.commit(); return dict(patient_uuid=patient_uuid, exams=[u for u, s in self.R["studies"].items() if s["patient_uuid"] == patient_uuid])

    def history(self, include_sensitive=False):
        """non-sensitive edit history; with include_sensitive and an unlocked vault, the old / new values of sensitive edits too"""
        if include_sensitive: return list(self._need()["history"])
        return [dict(h) for h in self.R["history"]]

    # ------------------------------------------------------------------ examination-level duplicate classification
    def classify(self, fingerprint="", dicom_study_uid="", accession="", institution="", deid_code="", mrn=""):
        """-> dict(kind, study_uuid, why). kinds: new | same_exam (re-import / moved: same image content or same DICOM StudyInstanceUID) |
        conflict (an identifier already used by a DIFFERENT examination, or the same accession with another patient) |
        same_patient_new_exam. Ambiguous cases are reported, never merged."""
        hit = [u for u, s in self.R["studies"].items() if fingerprint and s.get("fingerprint") == fingerprint]
        if dicom_study_uid:
            h = hashlib.sha256(dicom_study_uid.encode()).hexdigest()
            hit += [u for u, s in self.R["studies"].items() if s.get("dicom_uid_hash") == h and u not in hit]
        acc = self.by_accession(accession, institution) if accession and self.unlocked() else []
        dc = self.by_deid(deid_code) if deid_code else None
        if hit:
            u = hit[0]; why = "same image content" if fingerprint and self.R["studies"][u].get("fingerprint") == fingerprint else "same DICOM StudyInstanceUID"
            if (acc and acc[0] != u) or (dc and dc != u):
                return dict(kind="conflict", study_uuid=u, why=f"{why} as an existing examination, but the given identifier belongs to a different examination")
            return dict(kind="same_exam", study_uuid=u, why=f"{why} as an existing examination (re-import or moved folder): it is not imported again")
        if acc:
            pu = self.R["studies"][acc[0]]["patient_uuid"]; pm = self.patients_by_mrn(mrn) if mrn else []
            if pm and pu not in pm: return dict(kind="conflict", study_uuid=acc[0], why="this accession number belongs to an examination of a DIFFERENT patient")
            return dict(kind="conflict", study_uuid=acc[0], why="this accession number is already used by another examination (different images)")
        if dc: return dict(kind="conflict", study_uuid=dc, why="this de-identified study code is already used by another examination (different images)")
        ret = [u for u, s in self.R["studies"].items() if fingerprint and (s.get("retired") or {}).get("fingerprint") == fingerprint]
        note = f"previously removed - its results are kept for machine learning as {self.R['studies'][ret[0]]['deid_code']}" if ret else ""
        if mrn and self.unlocked() and self.patients_by_mrn(mrn): return dict(kind="same_patient_new_exam", study_uuid="", why="existing patient (same MRN), new examination", retired_note=note)
        return dict(kind="new", study_uuid="", why="new examination", retired_note=note)
