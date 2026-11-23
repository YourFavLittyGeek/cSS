"""uengine/transfer/copier.py - verified single-file copy (the only primitive that writes transfer data).

Two phases, so a multi-file job can verify EVERY file before it touches ANY destination (milestone 1b):

  stage_file(src, dst, ...)      -> StagedFile    policy checks, source identity, job-owned  <dst>.part-<job>, SHA-256
                                                   while copying, flush (checked), uncached read-back, compare,
                                                   source-unchanged check. No destination is touched.
  commit_staged(staged, mode)    -> CopyResult    publish the verified .part under the destination name
  rollback_committed(result)                      undo one commit of this job (only if the file is still ours)
  discard_staged(staged)                          remove a .part this job created
  verified_copy(...)                              stage + commit for a single file (milestone 1a API)

Exclusive commit (Phase 1b, measured 2026-11-23 on disk images - docs/engineering/FILESYSTEM_GUARANTEES.md):
every publish uses renamex_np(RENAME_EXCL) - atomic "rename only if the target name is free"; if the filesystem does not
support it, link()+unlink() (also atomic and exclusive). If NEITHER is supported (exFAT) the commit is REFUSED with
ExclusiveCommitUnsupported - there is no check-then-rename fallback, because that cannot exclude a destination created
between the check and the rename. A plain overwriting rename is never used to publish.

Replacement (REPLACE_AFTER_VERIFY / PRESERVE_PREVIOUS) moves the old file aside to <dst>.replaced-<job> (exclusive) and
then publishes the new file (exclusive); the old version stays until the caller (the service) has verified the whole job
- or is moved back by rollback. Files inside the Vault are never replaced (archives are write-once).
"""
import ctypes
import ctypes.util
import errno
import hashlib
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX
    fcntl = None

from .crashpoints import crash
from .models import CommitMode
from ..safety import PathPolicy, SafetyError, inside
from ..unified_transfer_engine import flush_durability

CHUNK = 4 * 1024 * 1024
JOB_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
# filesystems measured to lack BOTH renamex_np(RENAME_EXCL) and link(): refused before any data is copied
NO_EXCLUSIVE_COMMIT_FS = frozenset({"exfat"})


class CopyError(RuntimeError):
    """the copy failed; the destination is unchanged"""


class CopyRefused(CopyError):
    """refused by the safety policy before anything was written"""


class ExclusiveCommitUnsupported(CopyRefused):
    """the destination filesystem cannot atomically create a file only if its name is free"""


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


class RollbackError(CopyError):
    """a committed file could not be undone safely (it is no longer the file this job wrote)"""


@dataclass
class StagedFile:
    src: str
    dst: str
    part: str
    job_tag: str
    size: int
    src_sha256: str
    part_sha256: str
    src_identity: tuple
    part_identity: tuple
    durability: str
    nocache_readback: bool
    existing_sha256: Optional[str] = None     # hash of a destination that existed when staging started


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
    dst_identity: Optional[tuple] = None
    timings: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------------------------- platform primitives
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


class _StatFS(ctypes.Structure):          # macOS struct statfs (64-bit inode layout)
    _fields_ = [("f_bsize", ctypes.c_uint32), ("f_iosize", ctypes.c_int32), ("f_blocks", ctypes.c_uint64),
                ("f_bfree", ctypes.c_uint64), ("f_bavail", ctypes.c_uint64), ("f_files", ctypes.c_uint64),
                ("f_ffree", ctypes.c_uint64), ("f_fsid", ctypes.c_int32 * 2), ("f_owner", ctypes.c_uint32),
                ("f_type", ctypes.c_uint32), ("f_flags", ctypes.c_uint32), ("f_fssubtype", ctypes.c_uint32),
                ("f_fstypename", ctypes.c_char * 16), ("f_mntonname", ctypes.c_char * 1024),
                ("f_mntfromname", ctypes.c_char * 1024), ("f_flags_ext", ctypes.c_uint32), ("f_reserved", ctypes.c_uint32 * 7)]


_LIBC = None
if sys.platform == "darwin":
    try:
        _LIBC = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        _LIBC.renamex_np.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        _LIBC.renamex_np.restype = ctypes.c_int
    except (OSError, AttributeError):
        _LIBC = None
RENAME_EXCL = 0x00000004


def fs_type(path: str) -> str:
    """filesystem type name of the volume holding path ('apfs', 'exfat', 'msdos', 'hfs', ...; '' if unknown)"""
    if _LIBC is None:
        return ""
    p = path
    while p and not os.path.exists(p):
        p = os.path.dirname(p)
    st = _StatFS()
    fn = getattr(_LIBC, "statfs64", None) or _LIBC.statfs
    try:
        if fn(os.fsencode(p or "/"), ctypes.byref(st)) != 0:
            return ""
    except Exception:
        return ""
    return st.f_fstypename.decode(errors="replace")


def _rename_exclusive(src: str, dst: str) -> str:
    """atomically give src the name dst ONLY if dst does not exist. Raises FileExistsError if it exists, and
    ExclusiveCommitUnsupported if the filesystem offers no atomic exclusive primitive. Returns the method used."""
    if _LIBC is not None:
        if _LIBC.renamex_np(os.fsencode(src), os.fsencode(dst), RENAME_EXCL) == 0:
            return "renamex_np(RENAME_EXCL)"
        e = ctypes.get_errno()
        if e == errno.EEXIST:
            raise FileExistsError(errno.EEXIST, "destination exists", dst)
        if e not in (errno.ENOTSUP, errno.EOPNOTSUPP, errno.EINVAL, errno.ENOSYS):
            raise OSError(e, os.strerror(e), dst)
    if os.path.isdir(src):
        raise ExclusiveCommitUnsupported(f"the filesystem of {dst} ({fs_type(dst) or 'unknown'}) cannot rename a folder "
                                         f"exclusively; refused rather than risk replacing an existing folder")
    try:
        os.link(src, dst)                   # atomic and exclusive: fails with EEXIST if dst exists
    except FileExistsError:
        raise
    except OSError as e:
        if e.errno in (errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EXDEV, errno.EMLINK, errno.ENOSYS):
            raise ExclusiveCommitUnsupported(
                f"the filesystem of {dst} ({fs_type(dst) or 'unknown'}) supports neither an exclusive rename nor hard "
                f"links, so Percival cannot guarantee that an existing file is never overwritten; the operation was "
                f"refused (use an APFS- or HFS+-formatted destination)") from e
        raise
    os.remove(src)
    return "link+unlink"


def _identity(st):
    return (st.st_size, st.st_mtime_ns, st.st_ino)


def _remove_quietly(p: str) -> None:
    try:
        os.remove(p)
    except FileNotFoundError:
        pass


def _free_name(dst: str, job_tag: str, attempt: int) -> str:
    d, base = os.path.split(dst)
    stem, ext = (base[:-7], ".nii.gz") if base.endswith(".nii.gz") else os.path.splitext(base)
    return os.path.join(d, f"{stem}_restored_{job_tag}{'' if attempt == 1 else f'_{attempt}'}{ext}")


def preflight_destination(dst: str) -> None:
    """refuse before copying when the destination filesystem is known to lack an exclusive commit"""
    t = fs_type(os.path.dirname(dst) or dst)
    if t in NO_EXCLUSIVE_COMMIT_FS:
        raise ExclusiveCommitUnsupported(
            f"the destination {dst} is on a {t} volume, which supports neither an exclusive rename nor hard links; "
            f"Percival refuses to write there because it cannot guarantee that an existing file is never overwritten "
            f"(reading from {t} volumes is unaffected; use an APFS- or HFS+-formatted destination)")


# ---------------------------------------------------------------------------------------------- phase 1: stage
def stage_file(src: str, dst: str, *, policy: PathPolicy, job_tag: str, mode: CommitMode, chunk_size: int = CHUNK,
               control: Optional[Callable[[], Optional[str]]] = None,
               progress: Optional[Callable[[str, int], None]] = None,
               on_created: Optional[Callable[[str, tuple], None]] = None):
    """copy src into a verified, flushed, job-owned .part next to dst. Returns a StagedFile, or a CopyResult when no
    copy is needed (identical destination -> skipped_identical; NEVER_OVERWRITE + different -> conflict)."""
    mode = CommitMode(mode)
    if not isinstance(job_tag, str) or not JOB_TAG_RE.match(job_tag):
        raise CopyRefused(f"invalid job tag {job_tag!r}")
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
    if mode in (CommitMode.REPLACE_AFTER_VERIFY, CommitMode.PRESERVE_PREVIOUS) and policy.vault and inside(dst_c, policy.vault) \
            and os.path.lexists(dst_c):
        raise CopyRefused(f"{dst_c} is an archived file in the Vault; archives are never replaced")
    preflight_destination(dst_c)
    if os.path.lexists(part):
        raise StalePartFile(f"{part} already exists (left by an earlier attempt of job {job_tag}); recovery must decide")
    if os.path.isdir(dst_c) or (os.path.lexists(dst_c) and not os.path.isfile(dst_c)):
        raise CopyRefused(f"destination exists and is not a regular file: {dst_c}")
    parent = os.path.dirname(dst_c)
    if not os.path.isdir(parent):
        policy.check_write_target(parent)
        os.makedirs(parent, exist_ok=True)

    st0 = os.stat(src_c)
    size = st0.st_size
    existing_sha = None
    if os.path.lexists(dst_c):
        src_sha, _ = _hash_file(src_c)
        existing_sha, _ = _hash_file(dst_c)
        if _identity(os.stat(src_c)) != _identity(st0):
            raise SourceChanged(f"source changed while comparing with the existing destination: {src_c}")
        if src_sha == existing_sha:
            return CopyResult("skipped_identical", src_c, dst_c, size, src_sha, existing_sha)
        if mode == CommitMode.NEVER_OVERWRITE:
            return CopyResult("conflict", src_c, dst_c, size, src_sha, existing_sha)

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
        if on_created is not None:                       # 1c write-ahead: the .part's identity is journaled before any data
            on_created(part, _identity(os.fstat(fd)))
        crash("stage.after_part_recorded")
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
            if progress:
                progress("flushing", written)
            ok_flush, durability = flush_durability(fout.fileno())
            if not ok_flush:
                raise FlushFailed(f"could not flush {part} to the device: {durability}")
        src_sha = h.hexdigest()
        if written != size:
            raise SourceChanged(f"source size changed during the copy ({size} -> {written} bytes)")
        part_sha, nocache = _hash_file(part, nocache=True, chunk=chunk_size)
        if progress:
            progress("verifying", written)
        if part_sha != src_sha:
            raise IntegrityError(f"staged copy reads back differently: source {src_sha} != staged {part_sha}; destination unchanged")
        if _identity(os.stat(src_c)) != _identity(st0):
            raise SourceChanged(f"source was modified during the copy: {src_c}")
        return StagedFile(src_c, dst_c, part, job_tag, size, src_sha, part_sha, _identity(st0), _identity(os.stat(part)),
                          durability, nocache, existing_sha)
    except BaseException:
        if created and not keep_part:
            _remove_quietly(part)
        raise


def discard_staged(staged: StagedFile) -> bool:
    """remove a .part this job created - only if it is still the file staging wrote"""
    try:
        st = os.lstat(staged.part)
    except FileNotFoundError:
        return False
    if _identity(st) != staged.part_identity:
        raise RollbackError(f"{staged.part} is no longer the file this job staged; left untouched")
    os.remove(staged.part)
    return True


# ---------------------------------------------------------------------------------------------- phase 2: commit
def commit_staged(staged: StagedFile, mode: CommitMode, *, policy: PathPolicy,
                  _before_commit: Optional[Callable[[], None]] = None,
                  on_intent: Optional[Callable[[dict], None]] = None) -> CopyResult:
    """publish a verified .part under its destination name (exclusive). On any failure the .part is removed and the
    destination is exactly as it was (a moved-aside previous version is moved back)."""
    mode = CommitMode(mode)
    t0 = time.time()
    try:
        if _identity(os.lstat(staged.part)) != staged.part_identity:
            raise IntegrityError(f"{staged.part} changed after verification; not committed")
        if _identity(os.stat(staged.src)) != staged.src_identity:
            raise SourceChanged(f"source {staged.src} changed after it was verified; not committed")
        if _before_commit:
            _before_commit()                      # test hook: e.g. a destination appearing at the last moment
        target = policy.check_write_target(staged.dst)
        preserved = None
        method = ""
        def intent(t, preserved_path=None, old_identity=None):
            if on_intent is not None:                     # 1c write-ahead: journaled BEFORE any rename
                on_intent(dict(target=t, preserved_path=preserved_path, old_identity=old_identity))

        if mode == CommitMode.NEVER_OVERWRITE:
            intent(target)
            try:
                method = _rename_exclusive(staged.part, target)
            except FileExistsError:
                other, _ = _hash_file(target)
                _remove_quietly(staged.part)
                return CopyResult("skipped_identical" if other == staged.src_sha256 else "conflict", staged.src, target,
                                  staged.size, staged.src_sha256, other, durability=staged.durability,
                                  nocache_readback=staged.nocache_readback)
        elif mode == CommitMode.NEW_NAME:
            attempt = 0
            while True:
                intent(target)
                try:
                    method = _rename_exclusive(staged.part, target)
                    break
                except FileExistsError:
                    other, _ = _hash_file(target)
                    if other == staged.src_sha256:
                        _remove_quietly(staged.part)
                        return CopyResult("skipped_identical", staged.src, target, staged.size, staged.src_sha256, other)
                    attempt += 1
                    if attempt > 50:
                        raise CopyError(f"no free name for {staged.dst}")
                    target = policy.check_write_target(_free_name(staged.dst, staged.job_tag, attempt))
        else:  # PRESERVE_PREVIOUS / REPLACE_AFTER_VERIFY: old version aside (exclusive), then publish (exclusive)
            if policy.vault and inside(target, policy.vault) and os.path.lexists(target):
                raise CopyRefused(f"{target} is an archived file in the Vault; archives are never replaced")
            if os.path.lexists(target):
                preserved = policy.check_write_target(f"{target}.replaced-{staged.job_tag}")
                intent(target, preserved, _identity(os.lstat(target)))
                try:
                    _rename_exclusive(target, preserved)
                except FileExistsError:
                    raise CopyError(f"{preserved} already exists; refusing to overwrite a preserved version")
                crash("commit.after_move_aside")
            else:
                intent(target)
            try:
                method = _rename_exclusive(staged.part, target)
            except BaseException:
                if preserved:
                    try:
                        _rename_exclusive(preserved, target)          # the previous version returns
                        preserved = None
                    except FileExistsError:
                        raise CopyError(f"{target} was created by someone else during the commit; the previous version is "
                                        f"kept at {preserved} - nothing was overwritten")
                raise
        crash("commit.after_publish")
        dir_synced = _fsync_dir(os.path.dirname(target))
        st = os.lstat(target)
        if st.st_size != staged.size:
            raise CopyError(f"committed file {target} has the wrong size")
        return CopyResult("committed", staged.src, target, staged.size, staged.src_sha256, staged.part_sha256,
                          preserved_path=preserved, durability=staged.durability, dir_synced=dir_synced,
                          nocache_readback=staged.nocache_readback, dst_identity=_identity(st),
                          timings={"commit_s": time.time() - t0, "method": method})
    except BaseException:
        if _same(staged.part, staged.part_identity):     # only the .part this job staged
            _remove_quietly(staged.part)
        raise


def _same(path, ident) -> bool:
    try:
        return _identity(os.lstat(path)) == ident
    except FileNotFoundError:
        return False


def remove_if_identity(path: str, ident, *, policy: PathPolicy, expect_sha256: Optional[str] = None) -> str:
    """remove path ONLY if it is exactly the recorded file (identity, and content hash when given).
    -> 'removed' | 'absent' | 'mismatch'  (a mismatch is never removed)"""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return "absent"
    if ident is None or _identity(st) != tuple(ident) or not os.path.isfile(path) or os.path.islink(path):
        return "mismatch"
    if expect_sha256 is not None and _hash_file(path)[0] != expect_sha256:
        return "mismatch"
    policy.check_write_target(path)
    os.remove(path)
    _fsync_dir(os.path.dirname(path))
    return "removed"


def restore_preserved(preserved: str, target: str, old_ident, *, policy: PathPolicy) -> str:
    """move a preserved previous version back under its name (exclusive).
    -> 'restored' | 'already_restored' | 'absent' | 'mismatch' | 'occupied'"""
    try:
        st = os.lstat(preserved)
    except FileNotFoundError:
        try:
            if old_ident is not None and _identity(os.lstat(target)) == tuple(old_ident):
                return "already_restored"
        except FileNotFoundError:
            pass
        return "absent"
    if old_ident is None or _identity(st) != tuple(old_ident):
        return "mismatch"
    policy.check_write_target(target)
    try:
        _rename_exclusive(preserved, target)
    except FileExistsError:
        return "occupied"
    _fsync_dir(os.path.dirname(target))
    return "restored"


def rollback_committed(result: CopyResult, *, policy: PathPolicy) -> None:
    """undo one commit of this job: remove the committed file ONLY if it is still exactly the file this job wrote, then
    move a preserved previous version back (exclusive). Raises RollbackError if that cannot be done safely."""
    if result.status != "committed":
        return
    if not _same(result.dst, result.dst_identity):
        raise RollbackError(f"{result.dst} is no longer the file this job committed; not removed")
    policy.check_write_target(result.dst)
    os.remove(result.dst)
    if result.preserved_path:
        try:
            _rename_exclusive(result.preserved_path, result.dst)
        except FileExistsError:
            raise RollbackError(f"{result.dst} was re-created by someone else; previous version kept at {result.preserved_path}")
    _fsync_dir(os.path.dirname(result.dst))


def finalize_preserved(result: CopyResult, *, policy: PathPolicy) -> bool:
    """after the WHOLE job is verified and committed: remove this job's preserved previous version"""
    p = result.preserved_path
    if not p or ".replaced-" not in os.path.basename(p) or not os.path.lexists(p):
        return False
    policy.check_write_target(p)
    os.remove(p)
    return True


# ---------------------------------------------------------------------------------------------- one-file convenience
def verified_copy(src: str, dst: str, *, policy: PathPolicy, job_tag: str, mode: CommitMode,
                  chunk_size: int = CHUNK,
                  control: Optional[Callable[[], Optional[str]]] = None,
                  progress: Optional[Callable[[str, int], None]] = None,
                  _before_commit: Optional[Callable[[], None]] = None) -> CopyResult:
    """stage + commit one file. REPLACE_AFTER_VERIFY removes the moved-aside old version once the new one is committed
    (single-file job = whole job verified); PRESERVE_PREVIOUS keeps it."""
    mode = CommitMode(mode)
    staged = stage_file(src, dst, policy=policy, job_tag=job_tag, mode=mode, chunk_size=chunk_size,
                        control=control, progress=progress)
    if isinstance(staged, CopyResult):
        return staged
    res = commit_staged(staged, mode, policy=policy, _before_commit=_before_commit)
    if mode == CommitMode.REPLACE_AFTER_VERIFY and res.status == "committed" and res.preserved_path:
        finalize_preserved(res, policy=policy)
        res.preserved_path = None
    return res
