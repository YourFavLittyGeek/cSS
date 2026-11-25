"""checked_copy.py - a verified copy for the app's own copies OUTSIDE the journaled engine's managed roots (2026-11-25, audit item 9).

The journaled TransferService only writes inside the project and the Pensieve folder and refuses app_data/import_src (protected). Two
copies the app makes fall outside that: the import copy (external source folder -> app_data/import_src/<key>/) and the Vault backup
(PERCIVAL_VAULT -> a folder the user chooses). Both used plain shutil copies with no check. Here every file is:
  1. copied to a temporary name next to the target (<target>.part-<pid>), the source hashed while it is read,
  2. flushed to disk (fsync),
  3. read back from the disk without the cache (F_NOCACHE) and its SHA-256 compared with the source,
  4. only then renamed to the target name.
A file that already exists at the target is never overwritten: identical content is skipped, different content is an error.
copy_tree() copies a whole folder into a NEW folder: first under <dst>.partial, renamed to <dst> only when every file matched;
on any failure the partial folder is removed and nothing is left under the final name."""
import hashlib
import os
import shutil
import subprocess

from uengine.transfer.copier import _hash_file, _fsync_dir

CHUNK = 4 * 1024 * 1024


class CheckedCopyError(RuntimeError):
    pass


def _clone(src, tmp):
    """APFS clone (cp -c) when source and target are on the same volume: no extra disk space; verified like any copy"""
    try:
        if os.stat(src).st_dev == os.stat(os.path.dirname(tmp)).st_dev:
            return subprocess.run(["cp", "-c", src, tmp], capture_output=True).returncode == 0
    except OSError:
        pass
    return False


def copy_file(src, dst, clone=True, replace=False):
    """copy ONE file with read-back verification. Returns dict(sha256, size, status 'copied' | 'replaced' | 'identical').
    replace=True (the import copy only: the app's own earlier copy under import_src may be re-imported): a DIFFERENT existing file is
    replaced - atomically and only after the new copy has been verified."""
    src = os.path.abspath(src); dst = os.path.abspath(dst)
    if not os.path.isfile(src): raise CheckedCopyError(f"source is not a file: {src}")
    if os.path.lexists(dst):
        s1 = _hash_file(src)[0]
        if os.path.isfile(dst) and not os.path.islink(dst) and _hash_file(dst)[0] == s1:
            return dict(sha256=s1, size=os.path.getsize(dst), status="identical")
        if not (replace and os.path.isfile(dst) and not os.path.islink(dst)):
            raise CheckedCopyError(f"a different file already exists at {dst} - not overwritten")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = f"{dst}.part-{os.getpid()}"
    if os.path.lexists(tmp): os.remove(tmp)
    try:
        if clone and _clone(src, tmp):
            s1 = _hash_file(src)[0]
        else:
            h = hashlib.sha256()
            with open(src, "rb") as fi, open(tmp, "wb") as fo:
                while True:
                    b = fi.read(CHUNK)
                    if not b: break
                    h.update(b); fo.write(b)
                fo.flush(); os.fsync(fo.fileno())
            s1 = h.hexdigest()
            try: shutil.copystat(src, tmp)
            except OSError: pass
        s2 = _hash_file(tmp, nocache=True)[0]
        if s1 != s2: raise CheckedCopyError(f"copy of {os.path.basename(src)} differs from the source after writing (checksum mismatch)")
        existed = os.path.lexists(dst)
        if existed and not replace: raise CheckedCopyError(f"{dst} appeared during the copy - not overwritten")
        (os.replace if existed else os.rename)(tmp, dst); _fsync_dir(os.path.dirname(dst))
        return dict(sha256=s1, size=os.path.getsize(dst), status="replaced" if existed else "copied")
    finally:
        if os.path.lexists(tmp): os.remove(tmp)


def copy_tree(src, dst, progress=None):
    """copy the folder src into the NEW folder dst (must not exist). Returns dict(files=[{rel, size, sha256}], bytes)."""
    src = os.path.abspath(src); dst = os.path.abspath(dst)
    if not os.path.isdir(src): raise CheckedCopyError(f"source is not a folder: {src}")
    if os.path.lexists(dst): raise CheckedCopyError(f"{dst} already exists - not overwritten")
    part = dst + ".partial"
    if os.path.lexists(part): shutil.rmtree(part)
    files = []
    try:
        for root, dirs, names in os.walk(src):
            dirs.sort()
            rel_root = os.path.relpath(root, src)
            os.makedirs(os.path.join(part, rel_root), exist_ok=True)
            for n in sorted(names):
                a = os.path.join(root, n)
                if os.path.islink(a) or not os.path.isfile(a): continue          # links / sockets are not copied (never followed)
                rel = os.path.normpath(os.path.join(rel_root, n))
                r = copy_file(a, os.path.join(part, rel))
                files.append(dict(rel=rel, size=r["size"], sha256=r["sha256"]))
                if progress: progress(len(files), rel)
        os.rename(part, dst); _fsync_dir(os.path.dirname(dst))
    except BaseException:
        shutil.rmtree(part, ignore_errors=True); raise
    return dict(files=files, bytes=sum(f["size"] for f in files))
