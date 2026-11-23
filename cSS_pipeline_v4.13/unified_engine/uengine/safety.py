"""uengine/safety.py - Phase 0 server-side safety policy for every file operation the app can be asked to do.

One rule set, used by FileManager, CleaningManager, StudyWorkspaceManager, SyncManager and the HTTP dispatchers:

* Study codes are validated before they are ever joined into a path or a glob (an empty code used to mean
  "every file in review/").
* Every path is canonicalised (symlinks resolved) and must lie inside the project base or the configured Vault.
* PROTECTED locations are never deleted, moved, renamed, overwritten or written into through these APIs:
  original MRI (raw/, data/, app_data/import_src/, Vault original_mri/ and Dicom/, the Dicom/ folder next to the Vault),
  reader / expert records and the call ledger (review/, labels/, historical/), the trained Percival model store
  (percival/), private identity data (private/), Pensieve (Vault Pensieve|PENSIEVE/, pensieve*.db) and top-level
  app_data files (settings, patients, setup state).
* Structural folders (the project base, the Vault root, work/, studies/, app_data/staging/ ...) can never be deleted
  or renamed as a whole.

Comparisons are case-insensitive on macOS (APFS and exFAT volumes are case-insensitive by default), so 'RAW/' or
'Processed_MRI' vs 'processed_mri' cannot be used to slip past the rules.

The pipeline scripts and the reviewer write review/, data/ ... through their own code paths; this policy governs only
the generic storage / file-management operations exposed by the application server.
"""
import os
import re
import sys
from typing import Iterable, List, Optional

STUDY_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

PROTECTED_BASE_DIRS = ("raw", "data", "review", "labels", "historical", "percival", "private",
                       os.path.join("app_data", "import_src"))
PROTECTED_VAULT_DIRS = ("original_mri", "Dicom", "Pensieve", "PENSIEVE", "manifest")
PROTECTED_FILE_NAMES = {"pensieve.db", "pensieve.db-wal", "pensieve.db-shm", "pensieve_core.db",
                        "live_pensieve.db", "identity_vault.enc", "identity_vault.json", "names.csv"}
BASE_STRUCTURE = {"app_data", "work", "subjects", "synthseg", "logs", "results", "runs", "scripts", "unified_engine",
                  "unified_score", "uscore", "percival", "review", "raw", "data", "labels", "historical", "private",
                  "app", "tests", "backups", "exports"}
APP_DATA_STRUCTURE = {"staging", "scratch", "quarantine", "transfers", "logs", "qc", "import_src", "pipeline_backups",
                      "pensieve_snapshots", "identity"}
VAULT_STRUCTURE = {"studies", "archive", "processed_mri", "original_mri", "dicom", "pensieve", "manifest", "models",
                   "candidates", "backups", "snapshots"}


class SafetyError(ValueError):
    """A requested operation was refused by the safety policy."""


def _key(p: str) -> str:
    return p.lower() if sys.platform == "darwin" else p


def canon(path) -> str:
    """absolute, symlink-resolved path (the existing part of a not-yet-existing path is resolved too)"""
    if isinstance(path, bytes):
        path = os.fsdecode(path)
    return os.path.realpath(os.path.abspath(os.path.expanduser(os.fspath(path))))


def inside(path: str, root: str) -> bool:
    """path == root or path below root (case-insensitive on macOS)"""
    p, r = _key(path), _key(root.rstrip(os.sep) or os.sep)
    if r == os.sep:
        return True
    return p == r or p.startswith(r + os.sep)


def volumes_root() -> str:
    """where external volumes are mounted; tests point PERCIVAL_VOLUMES_ROOT at an empty temporary folder"""
    return os.environ.get("PERCIVAL_VOLUMES_ROOT") or "/Volumes"


def real_home() -> str:
    """the account's real home folder, independent of $HOME (which tests override)"""
    try:
        import pwd
        return pwd.getpwuid(os.getuid()).pw_dir
    except Exception:
        return os.path.expanduser("~")


def validate_study_code(code) -> str:
    """return the code unchanged if it is a safe study identifier, else raise SafetyError"""
    if not isinstance(code, str) or not STUDY_CODE_RE.match(code):
        raise SafetyError(f"invalid study code {code!r}: use 1-64 letters, digits, '-' or '_' (starting with a letter or digit)")
    return code


def parse_study_codes(value) -> List[str]:
    """a list, or a comma-separated string (query parameters), of validated study codes; None/'' -> []"""
    if value is None or value == "":
        return []
    items = value.split(",") if isinstance(value, str) else list(value)
    out: List[str] = []
    for it in items:
        c = validate_study_code(it.strip() if isinstance(it, str) else it)
        if c not in out:
            out.append(c)
    return out


def study_file_matches(filename: str, code: str) -> bool:
    """True if a file name belongs to study `code` (M1 must not match M10_candidates.csv)"""
    return filename == code or filename.startswith(code + "_") or filename.startswith(code + ".")


def is_simple_name(name) -> bool:
    return isinstance(name, str) and name not in ("", ".", "..") and os.sep not in name and "/" not in name and "\x00" not in name


class PathPolicy:
    """the managed locations of one project base + (optional) Vault, and the checks every operation must pass"""

    def __init__(self, base_dir: str, vault_root: Optional[str] = None):
        self.base = canon(base_dir)
        self.vault = canon(vault_root) if vault_root else None
        self.roots = [self.base] + ([self.vault] if self.vault else [])
        prot = [os.path.join(self.base, d) for d in PROTECTED_BASE_DIRS]
        self.read_only_roots: List[str] = []
        if self.vault:
            prot += [os.path.join(self.vault, d) for d in PROTECTED_VAULT_DIRS]
            sibling_dicom = os.path.join(os.path.dirname(self.vault), "Dicom")
            prot.append(sibling_dicom)
            self.read_only_roots.append(canon(sibling_dicom))
        self.protected = [canon(p) for p in prot]
        self.app_data = canon(os.path.join(self.base, "app_data"))

    # ---------------------------------------------------------------- classification
    def root_of(self, c: str) -> Optional[str]:
        for r in self.roots:
            if inside(c, r):
                return r
        return None

    def protected_reason(self, c: str) -> Optional[str]:
        for pr in self.protected:
            if inside(c, pr):
                return f"{c} is inside the protected location {pr}"
        if os.path.basename(c) in PROTECTED_FILE_NAMES:
            return f"{os.path.basename(c)} is a protected database / identity file"
        if _key(os.path.dirname(c)) == _key(self.app_data) and not os.path.isdir(c):
            return f"{c} is an application state file (app_data/)"
        return None

    def is_structural(self, c: str) -> bool:
        if any(_key(c) == _key(r) for r in self.roots):
            return True
        parent, name = os.path.dirname(c), os.path.basename(c).lower()
        if _key(parent) == _key(self.base) and name in {n.lower() for n in BASE_STRUCTURE}:
            return True
        if _key(parent) == _key(self.app_data) and name in APP_DATA_STRUCTURE:
            return True
        if self.vault and _key(parent) == _key(self.vault) and name in VAULT_STRUCTURE:
            return True
        return False

    def contains_protected(self, c: str) -> bool:
        return any(inside(pr, c) for pr in self.protected)

    # ---------------------------------------------------------------- checks (return the canonical path or raise)
    def check_source(self, path) -> str:
        """readable source for copy / verify / archive: inside the project, the Vault or the Dicom folder next to it"""
        if not path:
            raise SafetyError("no source path given")
        c = canon(path)
        if not (self.root_of(c) or any(inside(c, r) for r in self.read_only_roots)):
            raise SafetyError(f"source {c} is outside the project and the Vault")
        if not os.path.exists(c):
            raise SafetyError(f"source does not exist: {c}")
        return c

    def check_write_target(self, path) -> str:
        """a path that will be created or overwritten"""
        if not path:
            raise SafetyError("no destination path given")
        c = canon(path)
        if not self.root_of(c):
            raise SafetyError(f"destination {c} is outside the project and the Vault")
        if any(_key(c) == _key(r) for r in self.roots):
            raise SafetyError(f"destination {c} is a storage root")
        why = self.protected_reason(c)
        if why:
            raise SafetyError(f"write refused: {why}")
        return c

    def check_destination_dir(self, path) -> str:
        """an existing folder that new items will be created in (the folder itself is not modified)"""
        if not path:
            raise SafetyError("no destination folder given")
        c = canon(path)
        if not self.root_of(c):
            raise SafetyError(f"destination {c} is outside the project and the Vault")
        why = self.protected_reason(c)
        if why:
            raise SafetyError(f"write refused: {why}")
        return c

    def check_modify(self, path) -> str:
        """an existing item that will be renamed, moved away or deleted"""
        if not path:
            raise SafetyError("no path given")
        raw = os.path.abspath(os.path.expanduser(os.fspath(path)))
        if not os.path.lexists(raw):
            raise SafetyError(f"path does not exist: {raw}")
        c = canon(raw)
        link = os.path.join(canon(os.path.dirname(raw)), os.path.basename(raw))   # the item itself (parents resolved)
        for p in {link, c}:                                 # the link itself and what it points to must both be allowed
            if not self.root_of(p):
                raise SafetyError(f"{p} is outside the project and the Vault")
            why = self.protected_reason(p)
            if why:
                raise SafetyError(f"refused: {why}")
            if self.is_structural(p):
                raise SafetyError(f"refused: {p} is a structural storage folder and cannot be removed or renamed as a whole")
            if self.contains_protected(p):
                raise SafetyError(f"refused: {p} contains protected data")
        return c

    check_delete = check_modify

    def filter_allowed(self, paths: Iterable[str]) -> List[str]:
        out = []
        for p in paths:
            try:
                self.check_modify(p)
                out.append(p)
            except SafetyError:
                pass
        return out
