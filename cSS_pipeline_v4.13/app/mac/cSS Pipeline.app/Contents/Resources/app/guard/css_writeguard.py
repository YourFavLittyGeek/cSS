"""Central write protection of the PRODUCTION project for the experimental cSS app (v5.14.2-rc2).

Protected roots: the canonical (symlink-resolved) ~/css_project, plus any path in CSS_PROTECTED_PATHS (':'-separated).
Two layers, one rule set:
  1. check_base / check_dest: explicit validation of the project folder and of every user-chosen destination
     (export, backup, results) - refuses the protected roots, anything inside them, anything that resolves into them
     through a symlink, an ancestor of them (base only), cloud-synced folders and ~/Desktop / ~/Documents (destinations).
  2. install(): a Python audit hook that refuses, inside the running process, EVERY write-type file operation
     (open for writing / creating / appending, os.open with write flags, rename/replace, remove, rmdir, mkdir, symlink, link,
     chmod, chown, utime, truncate, rmtree, xattr) whose canonical target lies inside a protected root, and the creation of a
     symlink / hard link that points into one. Reading stays allowed (bringing studies in reads production).
     The experimental launcher sets PYTHONPATH to this folder (sitecustomize.py), so every Python process the app starts -
     pipeline scripts, reviewer, unified score - carries the hook. Non-Python programs (shell, FreeSurfer binaries) are not
     hooked; they only ever run with paths inside the validated experimental project.
Active only when CSS_EXPERIMENTAL=1 (set by the experimental launcher): the production app never loads this module."""
import os, sys

CLOUD_MARKERS = ("/Library/Mobile Documents/", "/Library/CloudStorage/", "/Dropbox", "/Google Drive", "/OneDrive", "/iCloud", "/Box/", "/pCloud")

class ProductionWriteRefused(PermissionError):
    pass

def canon(p):
    """absolute, symlink-resolved path (resolves the existing part of a path that does not exist yet)"""
    if isinstance(p, bytes): p = os.fsdecode(p)
    return os.path.realpath(os.path.abspath(os.path.expanduser(os.fspath(p))))

def protected_roots():
    roots = [os.path.join(os.path.expanduser("~"), "css_project")]
    roots += [x for x in os.environ.get("CSS_PROTECTED_PATHS", "").split(":") if x.strip()]
    out = []
    for r in roots:
        out.append(canon(r))
        a = os.path.abspath(os.path.expanduser(r))               # also the un-resolved spelling (production may be a symlink)
        if a not in out: out.append(a)
    return out

def _inside(p, root): return p == root or p.startswith(root.rstrip("/") + "/")

def protected_hit(path):
    """the protected root this path (canonical or as written) lies in, else None"""
    try: c = canon(path)
    except Exception: return None
    a = os.path.abspath(os.path.expanduser(os.fsdecode(path) if isinstance(path, bytes) else os.fspath(path)))
    for r in protected_roots():
        if _inside(c, r) or _inside(a, r): return r
    return None

def check_base(path):
    """(ok, reason) for the experimental PROJECT folder"""
    if not path or not str(path).strip(): return False, "no project folder"
    c = canon(path)
    r = protected_hit(path)
    if r: return False, f"{path} is the production project or inside it ({r})"
    for r in protected_roots():
        if _inside(r, c): return False, f"{path} contains the production project ({r}); choose a separate folder"
    if any(m.lower() in (c + "/").lower() for m in CLOUD_MARKERS): return False, f"{path} is inside a cloud-synced folder"
    return True, "ok"

def check_dest(path):
    """(ok, reason) for a user-chosen DESTINATION of clinical-derived files (export, backup, results)"""
    if not path or not str(path).strip(): return False, "no destination chosen"
    p = canon(path); h = canon("~")
    if protected_hit(path): return False, "the destination is the production project ~/css_project or inside it (also through a symlink)"
    if any(m.lower() in (p + "/").lower() for m in CLOUD_MARKERS): return False, "the destination is inside a cloud-synced folder (iCloud / Dropbox / Google Drive / OneDrive)"
    for d in ("Desktop", "Documents"):
        q = os.path.join(h, d)
        if _inside(p, q): return False, f"~/{d} is refused: iCloud 'Desktop & Documents' can sync it without any sign in the path"
    if not os.path.isdir(p): return False, "the folder does not exist"
    if not os.access(p, os.W_OK): return False, "the folder is not writable"
    return True, "local folder"

def assert_write_ok(path, what="write"):
    r = protected_hit(path)
    if r: raise ProductionWriteRefused(f"cSS experimental write guard: {what} refused - {os.fsdecode(path) if isinstance(path, bytes) else path} is inside the production project {r}")

_WFLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
def _hook(event, args):
    if event == "open":
        path, mode, flags = (list(args) + [None, None, None])[:3]
        if not isinstance(path, (str, bytes, os.PathLike)): return
        w = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (isinstance(flags, int) and flags & _WFLAGS)
        if w: assert_write_ok(path, "opening for writing")
    elif event in ("os.rename", "os.link"):
        assert_write_ok(args[1], event); assert_write_ok(args[0], event)
    elif event == "os.symlink":
        assert_write_ok(args[1], "creating a symlink")
        if protected_hit(args[0]): raise ProductionWriteRefused(f"cSS experimental write guard: a symlink into the production project is refused ({args[0]})")
    elif event in ("subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn"):
        # a program started from the experimental app is not hooked itself: refuse to start one that is pointed at production
        items = []
        if event == "os.system": items = [args[0]]
        else:
            a = args[1] if len(args) > 1 else None
            items = [a] if isinstance(a, (str, bytes, os.PathLike)) else list(a or [])
            if event == "subprocess.Popen" and len(args) > 2 and args[2]: items.append(args[2])      # cwd
        for it in items:
            if isinstance(it, (str, bytes, os.PathLike)):
                for tok in (os.fsdecode(it) if isinstance(it, bytes) else os.fspath(it)).split():
                    if "/" in tok or tok.startswith("~"):
                        if protected_hit(tok.strip("'\"")): raise ProductionWriteRefused(f"cSS experimental write guard: starting a program on the production project is refused ({tok})")
    elif event in ("os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.chown", "os.utime", "os.truncate", "os.chflags", "os.lchflags",
                   "os.setxattr", "os.removexattr", "shutil.rmtree", "shutil.chown"):
        if args and isinstance(args[0], (str, bytes, os.PathLike)): assert_write_ok(args[0], event)

_INSTALLED = [False]
def install():
    if _INSTALLED[0] or os.environ.get("CSS_EXPERIMENTAL") != "1": return False
    sys.addaudithook(_hook); _INSTALLED[0] = True
    return True
