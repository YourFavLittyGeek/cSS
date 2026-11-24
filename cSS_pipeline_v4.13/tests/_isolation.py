"""tests/_isolation.py - Phase 0 test isolation for the PERCIVAL unittest suite.

activate() must run before any application module is imported (it is idempotent). It:

1. points HOME, CSS_BASE and PERCIVAL_VOLUMES_ROOT at a fresh temporary tree, sets PERCIVAL_TEST_ISOLATION=1 and switches
   off bytecode writing (so nothing is written next to the code either);
2. installs a Python audit hook that REFUSES, inside this process, every write-type file operation (open for writing,
   os.open with write flags, rename / replace, remove, rmdir, mkdir, rmtree, chmod, chown, utime, truncate, symlink, link,
   sqlite3.connect - sqlite creates files in C, bypassing open) whose canonical target is inside the account's REAL home
   folder (looked up with pwd, independent of $HOME) or under the real /Volumes; and refuses to start `diskutil` or any
   program whose arguments point at the live project folders or /Volumes.

Every refusal is recorded in STATE["violations"] (app code often swallows exceptions; the runner fails on any recorded
violation) and printed at exit. The probe tests in test_phase0_isolation.py prove the hook works.
"""
import atexit
import os
import sys
import tempfile

STATE = {"active": False, "root": None, "violations": [], "owns_root": False}


def _real_home():
    try:
        import pwd
        return os.path.realpath(pwd.getpwuid(os.getuid()).pw_dir)
    except Exception:
        return os.path.realpath(os.path.expanduser("~"))


REAL_HOME = _real_home()
REAL_VOLUMES = "/Volumes"
LIVE_MARKERS = [os.path.join(REAL_HOME, n) for n in ("Percival_project", "css_project", "Percival_demo", ".percival_vault_config.json",
                                                    ".percival_local_journal.db", os.path.join("Library", "Application Support", "Percival Dev"))]


class IsolationViolation(PermissionError):
    """a test tried to write outside its temporary tree"""


def _k(p):
    return p.lower() if sys.platform == "darwin" else p


def _inside(p, root):
    p, r = _k(p), _k(root.rstrip("/"))
    return p == r or p.startswith(r + "/")


def _canon(p):
    if isinstance(p, bytes):
        p = os.fsdecode(p)
    return os.path.realpath(os.path.abspath(os.path.expanduser(os.fspath(p))))


def forbidden(path):
    """the protected root this path is in, else None (the isolation tree itself is always allowed)"""
    try:
        c = _canon(path)
    except Exception:
        return None
    root = STATE.get("root")
    if root and _inside(c, root):
        return None
    if _inside(c, REAL_HOME):
        return REAL_HOME
    if _inside(c, REAL_VOLUMES) or _inside(c, "/private" + REAL_VOLUMES):
        return REAL_VOLUMES
    return None


def _refuse(what, path, root):
    msg = f"PERCIVAL test isolation: {what} refused - {path} is inside {root}"
    STATE["violations"].append(msg)
    raise IsolationViolation(msg)


def _fd_path(fd):
    """the folder an open directory descriptor refers to (macOS F_GETPATH), else None"""
    try:
        import fcntl
        return os.fsdecode(fcntl.fcntl(fd, fcntl.F_GETPATH, bytes(1024))).rstrip("\x00") or None
    except Exception:
        return None


def _check(path, what, dir_fd=None):
    if isinstance(path, (str, bytes, os.PathLike)):
        p = os.fsdecode(path) if isinstance(path, bytes) else os.fspath(path)
        if isinstance(dir_fd, int) and not os.path.isabs(p):
            base = _fd_path(dir_fd)        # shutil.rmtree & co. pass names relative to an open directory
            if base is None:
                _refuse(what, p, "an unresolvable directory descriptor (fail closed)")
            p = os.path.join(base, p)
        r = forbidden(p)
        if r:
            _refuse(what, p, r)


_WFLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC


def _hook(event, args):
    if event == "open":
        path, mode, flags = (list(args) + [None, None, None])[:3]
        if not isinstance(path, (str, bytes, os.PathLike)):
            return
        w = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (isinstance(flags, int) and flags & _WFLAGS)
        if w:
            _check(path, "opening for writing")
    elif event in ("os.rename", "os.link"):          # (src, dst, src_dir_fd, dst_dir_fd)
        a = list(args) + [None, None, None, None]
        _check(a[0], event, a[2])
        _check(a[1], event, a[3])
    elif event == "os.symlink":                       # (src, dst, dir_fd)
        a = list(args) + [None, None, None]
        _check(a[1], "creating a symlink", a[2])
    elif event in ("os.remove", "os.rmdir", "shutil.rmtree"):                     # (path, dir_fd)
        a = list(args) + [None, None]
        _check(a[0], event, a[1])
    elif event in ("os.mkdir", "os.chmod"):                                       # (path, mode, dir_fd)
        a = list(args) + [None, None, None]
        _check(a[0], event, a[2])
    elif event == "os.utime":                                                     # (path, times, ns, dir_fd)
        a = list(args) + [None] * 4
        _check(a[0], event, a[3])
    elif event == "os.chown":                                                     # (path, uid, gid, dir_fd)
        a = list(args) + [None] * 4
        _check(a[0], event, a[3])
    elif event in ("os.truncate", "os.chflags", "os.lchflags", "os.setxattr", "os.removexattr", "shutil.chown"):
        if args:
            _check(args[0], event)
    elif event == "sqlite3.connect":
        db = args[0] if args else None
        if isinstance(db, (str, bytes, os.PathLike)) and os.fspath(db) not in (":memory:", b":memory:", ""):
            d = os.fsdecode(db) if isinstance(db, bytes) else os.fspath(db)
            if d.startswith("file:"):                       # sqlite URI: file:<path>?<query>
                from urllib.parse import parse_qs, unquote
                path, _, query = d[5:].partition("?")
                if "ro" in parse_qs(query).get("mode", []):
                    return                                   # read-only open: never a write
                d = unquote(path)
            _check(d, "opening an sqlite database")
    elif event in ("subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn"):
        items = []
        if event == "os.system":
            items = [args[0]]
        else:
            exe = args[0] if args else None
            a = args[1] if len(args) > 1 else None
            items = ([exe] if isinstance(exe, (str, bytes, os.PathLike)) else []) + \
                    ([a] if isinstance(a, (str, bytes, os.PathLike)) else list(a or []))
            if event == "subprocess.Popen" and len(args) > 2 and args[2]:
                items.append(args[2])
        strs = [os.fsdecode(i) if isinstance(i, bytes) else os.fspath(i) for i in items if isinstance(i, (str, bytes, os.PathLike))]
        cmdline = " ".join(strs)
        for s in strs:
            for tok in s.split():
                t = tok.strip("'\"")
                if os.path.basename(t) == "diskutil":
                    toks = [x.strip("'\"") for x in cmdline.split()]
                    i = next(j for j, x in enumerate(toks) if os.path.basename(x) == "diskutil")
                    verb = next((x for x in toks[i + 1:] if not x.startswith("-") and os.path.basename(x) != "diskutil"), "")
                    if verb not in ("info", "list"):     # read-only queries are allowed; unmount / eject / erase / mount ... never
                        _refuse("starting diskutil " + (verb or "(no verb)"), cmdline, "the test environment (never change drives from a test)")
                if "/" in t or t.startswith("~"):
                    c = _canon(t)
                    if any(_inside(c, m) for m in LIVE_MARKERS) or _inside(c, REAL_VOLUMES):
                        _refuse("starting a program on live data", cmdline, "the live project / volumes")


def _report():
    if STATE["violations"]:
        sys.stderr.write(f"\nPERCIVAL test isolation: {len(STATE['violations'])} refused write(s) - see above; first: "
                         f"{STATE['violations'][0]}\n")
    if STATE.get("owns_root") and STATE.get("root") and os.environ.get("PERCIVAL_KEEP_TEST_ROOT") != "1":
        import shutil
        shutil.rmtree(STATE["root"], ignore_errors=True)


def activate():
    """isolate this test process (idempotent); returns STATE"""
    if STATE["active"]:
        return STATE
    root = os.environ.get("PERCIVAL_TEST_ROOT") if os.environ.get("PERCIVAL_TEST_ISOLATION") == "1" else None
    if not root or not os.path.isdir(root):
        base_tmp = tempfile.gettempdir()
        if _inside(_canon(base_tmp), REAL_HOME):
            base_tmp = "/private/tmp"
        root = tempfile.mkdtemp(prefix="percival_iso_", dir=base_tmp)
        STATE["owns_root"] = True
    root = _canon(root)
    home = os.path.join(root, "home")
    base = os.path.join(home, "Percival_project")
    vols = os.path.join(root, "Volumes")
    tmp = os.path.join(root, "tmp")
    for d in (home, base, vols, tmp):
        os.makedirs(d, exist_ok=True)
    os.environ.setdefault("PERCIVAL_FS_SEARCH", "")   # tests never pick up this Mac's real FreeSurfer (app start-up search, setup_gui.find_freesurfer)
    os.environ.update(HOME=home, CSS_BASE=base, PERCIVAL_VOLUMES_ROOT=vols, PERCIVAL_TEST_ISOLATION="1",
                      PERCIVAL_TEST_ROOT=root, PYTHONDONTWRITEBYTECODE="1", TMPDIR=tmp, MPLCONFIGDIR=os.path.join(home, ".mpl"))
    tempfile.tempdir = tmp
    sys.dont_write_bytecode = True
    STATE.update(active=True, root=root, home=home, base=base, volumes=vols)
    sys.addaudithook(_hook)
    atexit.register(_report)
    return STATE
