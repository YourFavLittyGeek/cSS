"""uengine/transfer/copier.py - Phase 1a: verified single-file copy (the only primitive that writes transfer data).

verified_copy(src, dst, policy=..., job_tag=..., mode=...) performs, in order (plan section 3):
  1. policy checks (Phase 0 PathPolicy): source readable inside the project / Vault, regular file, not a symlink;
     destination a permitted write target; staged / preserved names permitted too
  2. source identity recorded: size, mtime_ns, inode
  3. destination already present -> hash both; identical content is SKIPPED (never rewritten); otherwise the commit mode
     decides (NEVER_OVERWRITE -> CONFLICT without writing anything)
  4. stream into a job-owned  <dst>.part-<job_tag>  (4 MB chunks, SHA-256 while copying); pause / cancel checked
     between chunks
  5. flush (F_FULLFSYNC, fallback fsync) - a failed flush fails the copy
  6. read the staged file back with F_NOCACHE (bypassing the macOS buffer cache) and hash it
  7. compare source hash == read-back hash, and the source identity is unchanged (else SOURCE_CHANGED)
  8. commit by mode; flush the destination directory; confirm the destination size
Any failure before the commit removes ONLY the job's .part file; the destination is never touched before step 8.
A pause keeps the .part (resume re-verifies it - milestone 1c). Directory trees, queues, locks and the journal are the
service's job (milestone 1b); this module handles exactly one file.
"""
import errno
import hashlib
import os
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX
    fcntl = None

from .models import CommitMode
from ..safety import PathPolicy, SafetyError
from ..unified_transfer_engine import flush_durability

CHUNK = 4 * 1024 * 1024
JOB_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class CopyError(RuntimeError):
    """the copy failed; the destination is unchanged"""


class CopyRefused(CopyError):
    """refused by the safety policy before anything was written"""


class IntegrityError(CopyError):
    """the staged copy did not read back identical to the source"""


class SourceChanged(CopyError):
    """the source was modified while it was being copied"""


class FlushFailed(CopyError):
    pass


class StalePartFile(CopyError):
    """a .part file of this job already exists - recovery (not a fresh copy) must decide what happens to it"""


class CopyCancelled(CopyError):
    """cancelled between chunks; the .part file was removed"""


class CopyPaused(CopyError):
    """paused between chunks; the .part file is KEPT for a verified resume"""

    def __init__(self, msg, part_path, bytes_written):
        super().__init__(msg)
        self.part_path, self.bytes_written = part_path, bytes_written


@dataclass
class CopyResult:
    status: str                         # committed | skipped_identical | conflict
    src: str
    dst: str                            # where the content now is (NEW_NAME may differ from the requested dst)
    size: int
    src_sha256: str
    dst_sha256: Optional[str] = None    # read-back hash of what was committed (== src_sha256), or the existing file's hash
    preserved_path: Optional[str] = None
    durability: str = ""
    dir_synced: bool = False
    nocache_readback: bool = False
    timings: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------------------------- hashing (patchable)
def _hash_file(path: str, nocache: bool = False, chunk: int = CHUNK):
    """(sha256 hex, nocache_applied). nocache=True asks macOS not to serve the read from the buffer cache."""
    h = hashlib.sha256()
    applied = False
    fd = os.open(path, os.O_RDONLY)
    try:
        if nocache and fcntl is not None and hasattr(fcntl, "F_NOCACHE"):
            try:
                fcntl.fcntl(fd, fcntl.F_NOCACHE, 1)
                applied = True
            except OSError:
                applied = False
        with os.fdopen(fd, "rb", closefd=False) as f:
            for b in iter(lambda: f.read(chunk), b""):
                h.update(b)
    finally:
        os.close(fd)
    return h.hexdigest(), applied


def _fsync_dir(path: str) -> bool:
    """flush a directory entry change (rename) to disk; some filesystems (exFAT) refuse - reported, not fatal"""
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return False
    try:
        os.fsync(fd)
        return True
    except OSError:
        return False
    finally:
        os.close(fd)


def _identity(st):
    return (st.st_size, st.st_mtime_ns, st.st_ino)


def _remove_quietly(p: str) -> None:
    try:
        os.remove(p)
    except FileNotFoundError:
        pass


def _free_name(dst: str, job_tag: str) -> str:
    d, base = os.path.split(dst)
    stem, ext = (base[:-7], ".nii.gz") if base.endswith(".nii.gz") else os.path.splitext(base)
    for i in range(1, 1000):
        cand = os.path.join(d, f"{stem}_restored_{job_tag}{'' if i == 1 else f'_{i}'}{ext}")
        if not os.path.lexists(cand):
            return cand
    raise CopyError(f"no free name for {dst}")


def _link_no_overwrite(part: str, target: str) -> None:
    """atomically create target from part, failing if target exists (hard link); fallback for filesystems without hard
    links (exFAT): re-check then rename - the remaining race window is documented in the plan"""
    try:
        os.link(part, target)
        os.remove(part)
        return
    except FileExistsError:
        raise
    except OSError as e:
        if e.errno not in (errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EXDEV, errno.EMLINK):
            raise
    if os.path.lexists(target):
        raise FileExistsError(errno.EEXIST, "destination appeared", target)
    os.rename(part, target)


# ---------------------------------------------------------------------------------------------- the copy
def verified_copy(src: str, dst: str, *, policy: PathPolicy, job_tag: str, mode: CommitMode,
                  chunk_size: int = CHUNK,
                  control: Optional[Callable[[], Optional[str]]] = None,
                  progress: Optional[Callable[[str, int], None]] = None,
                  _before_commit: Optional[Callable[[], None]] = None) -> CopyResult:
    """copy one file with full verification. control() is polled between chunks and may return "pause" or "cancel".
    progress(phase, bytes) reports bytes written ("copying") / read back ("verifying")."""
    mode = CommitMode(mode)
    if not isinstance(job_tag, str) or not JOB_TAG_RE.match(job_tag):
        raise CopyRefused(f"invalid job tag {job_tag!r}")
    t0 = time.time()

    # 1. policy -----------------------------------------------------------------------------------------------
    if not src or os.path.islink(src):
        raise CopyRefused(f"source is a symbolic link or missing: {src!r} (links are never followed)")
    try:
        src_c = policy.check_source(src)
        dst_c = policy.check_write_target(dst)
        part = policy.check_write_target(f"{dst_c}.part-{job_tag}")
    except SafetyError as e:
        raise CopyRefused(str(e)) from e
    if not os.path.isfile(src_c):
        raise CopyRefused(f"source is not a regular file: {src_c}")
    if os.path.lexists(part):
        raise StalePartFile(f"{part} already exists (left by an earlier attempt of job {job_tag}); recovery must decide")
    if os.path.isdir(dst_c) or (os.path.lexists(dst_c) and not os.path.isfile(dst_c)):
        raise CopyRefused(f"destination exists and is not a regular file: {dst_c}")
    parent = os.path.dirname(dst_c)
    if not os.path.isdir(parent):
        policy.check_write_target(parent)
        os.makedirs(parent, exist_ok=True)

    # 2. source identity --------------------------------------------------------------------------------------
    st0 = os.stat(src_c)
    size = st0.st_size

    # 3. destination already present --------------------------------------------------------------------------
    if os.path.lexists(dst_c):
        src_sha, _ = _hash_file(src_c)
        dst_sha, _ = _hash_file(dst_c)
        if _identity(os.stat(src_c)) != _identity(st0):
            raise SourceChanged(f"source changed while comparing with the existing destination: {src_c}")
        if src_sha == dst_sha:
            return CopyResult("skipped_identical", src_c, dst_c, size, src_sha, dst_sha, timings={"total_s": time.time() - t0})
        if mode == CommitMode.NEVER_OVERWRITE:
            return CopyResult("conflict", src_c, dst_c, size, src_sha, dst_sha, timings={"total_s": time.time() - t0})

    # 4. stream into the job-owned .part ----------------------------------------------------------------------
    h = hashlib.sha256()
    written = 0
    keep_part = False
    created = False                                  # only a .part THIS call created is ever removed
    try:
        try:
            fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            raise StalePartFile(f"{part} appeared concurrently; not ours - left untouched")
        created = True
        with os.fdopen(fd, "wb") as fout, open(src_c, "rb") as fin:
            while True:
                if control is not None:
                    c = control()
                    if c == "cancel":
                        raise CopyCancelled(f"cancelled at {written} of {size} bytes")
                    if c == "pause":
                        fout.flush()
                        flush_durability(fout.fileno())
                        keep_part = True
                        raise CopyPaused(f"paused at {written} of {size} bytes", part, written)
                b = fin.read(chunk_size)
                if not b:
                    break
                h.update(b)
                fout.write(b)
                written += len(b)
                if progress:
                    progress("copying", written)
            fout.flush()
            # 5. flush -------------------------------------------------------------------------------------------
            ok_flush, durability = flush_durability(fout.fileno())
            if not ok_flush:
                raise FlushFailed(f"could not flush {part} to the device: {durability}")
        src_sha = h.hexdigest()
        if written != size:
            raise SourceChanged(f"source size changed during the copy ({size} -> {written} bytes)")

        # 6. uncached read-back -------------------------------------------------------------------------------
        part_sha, nocache = _hash_file(part, nocache=True, chunk=chunk_size)
        if progress:
            progress("verifying", written)

        # 7. compare ------------------------------------------------------------------------------------------
        if part_sha != src_sha:
            raise IntegrityError(f"staged copy reads back differently: source {src_sha} != staged {part_sha}; destination unchanged")
        if _identity(os.stat(src_c)) != _identity(st0):
            raise SourceChanged(f"source was modified during the copy: {src_c}")

        if _before_commit:
            _before_commit()                         # test hook: e.g. a destination appearing at the last moment

        # 8. commit -------------------------------------------------------------------------------------------
        preserved = None
        target = dst_c
        if mode == CommitMode.NEVER_OVERWRITE:
            try:
                _link_no_overwrite(part, target)
            except FileExistsError:
                other, _ = _hash_file(target)
                _remove_quietly(part)
                status = "skipped_identical" if other == src_sha else "conflict"
                return CopyResult(status, src_c, target, size, src_sha, other, durability=durability,
                                  nocache_readback=nocache, timings={"total_s": time.time() - t0})
        elif mode == CommitMode.NEW_NAME:
            if os.path.lexists(target):
                target = policy.check_write_target(_free_name(target, job_tag))
            try:
                _link_no_overwrite(part, target)
            except FileExistsError:
                target = policy.check_write_target(_free_name(target, job_tag + "b"))
                _link_no_overwrite(part, target)
        elif mode == CommitMode.PRESERVE_PREVIOUS:
            if os.path.lexists(target):
                preserved = policy.check_write_target(f"{target}.replaced-{job_tag}")
                if os.path.lexists(preserved):
                    raise CopyError(f"{preserved} already exists; refusing to overwrite a preserved version")
                os.rename(target, preserved)
                try:
                    os.replace(part, target)
                except Exception:
                    os.rename(preserved, target)          # roll back: the previous version returns
                    raise
            else:
                _link_no_overwrite(part, target)
        else:  # REPLACE_AFTER_VERIFY
            os.replace(part, target)

        dir_synced = _fsync_dir(os.path.dirname(target))
        if os.path.getsize(target) != size:
            raise CopyError(f"committed file {target} has the wrong size")    # (cannot happen after rename; defensive)
        return CopyResult("committed", src_c, target, size, src_sha, part_sha, preserved_path=preserved,
                          durability=durability, dir_synced=dir_synced, nocache_readback=nocache,
                          timings={"total_s": time.time() - t0})
    except BaseException:
        if created and not keep_part:
            _remove_quietly(part)
        raise
