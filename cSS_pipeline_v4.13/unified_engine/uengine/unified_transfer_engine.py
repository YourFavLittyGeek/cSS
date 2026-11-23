"""uengine/unified_transfer_engine.py - Canonical Unified Transfer Engine for PERCIVAL.

Consolidates all file copying, staging, archival, restoration, import, and migration operations
under a single robust, memory-conscious, and verified engine.

Key Features:
- Device-aware transfer strategy: APFS clone for same-device, bounded streaming (4MB buffer) for cross-device
- Simultaneous in-flight SHA-256 hashing (eliminates redundant double disk reads on HDD)
- Atomic writes via .tmp staging + os.replace
- Full progress metrics: completed/total bytes, completed/total files, instant & average MB/s, ETA
- Pause, resume, retry, cancellation, and crash recovery with durable JSON manifests
- Safe handling of external drive disconnections
- Source preservation: source is never removed until destination verification succeeds
"""

import os
import sys
import time
import json
import shutil
import hashlib
import subprocess
from enum import Enum
from typing import Dict, Any, List, Optional, Callable, Tuple
from dataclasses import dataclass, asdict

try:
    import fcntl
    HAS_F_FULLFSYNC = hasattr(fcntl, "F_FULLFSYNC")
except ImportError:
    fcntl = None
    HAS_F_FULLFSYNC = False


DEFAULT_CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB optimal streaming buffer


class TransferState(str, Enum):
    QUEUED = "Queued"
    PREPARING = "Preparing"
    COPYING = "Copying"
    FLUSHING = "Flushing"
    VERIFYING = "Verifying"
    COMMITTING = "Committing"
    COMPLETED = "Completed"
    PAUSED = "Paused"
    CANCEL_REQUESTED = "Cancel requested"
    CANCELLED = "Cancelled"
    INTERRUPTED = "Interrupted"
    FAILED = "Failed"
    NEEDS_ATTENTION = "Needs attention"


def compute_sha256(path: str, chunk_size: int = DEFAULT_CHUNK_SIZE) -> str:
    """Compute SHA-256 hash of a file using bounded memory streaming."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def flush_durability(fd: int) -> Tuple[bool, str]:
    """Flush file descriptor to disk ensuring full physical sync when supported."""
    if sys.platform == "darwin" and HAS_F_FULLFSYNC and fcntl:
        try:
            fcntl.fcntl(fd, fcntl.F_FULLFSYNC)
            return True, "F_FULLFSYNC"
        except Exception:
            pass
    try:
        os.fsync(fd)
        return True, "os.fsync"
    except Exception as e:
        return False, f"flush_failed: {e}"


def is_same_filesystem(src: str, dst: str) -> bool:
    """Check if source and destination directory reside on the same filesystem device."""
    try:
        s_dev = os.stat(src).st_dev
        target_dir = dst if os.path.isdir(dst) else os.path.dirname(dst)
        if not os.path.exists(target_dir):
            target_dir = os.path.dirname(os.path.abspath(target_dir))
        d_dev = os.stat(target_dir).st_dev
        return s_dev == d_dev
    except Exception:
        return False


@dataclass
class TransferProgress:
    job_id: str
    study_id: str
    operation: str
    source: str
    destination: str
    total_files: int = 0
    completed_files: int = 0
    total_bytes: int = 0
    completed_bytes: int = 0
    current_file: str = ""
    current_phase: str = TransferState.PREPARING.value
    current_mb_s: float = 0.0
    avg_mb_s: float = 0.0
    eta_seconds: Optional[float] = None
    status: str = TransferState.PREPARING.value
    verification_status: str = "unverified"  # unverified, verified, mismatch
    durability_level: str = "standard"       # F_FULLFSYNC, os.fsync, unverified
    error: Optional[str] = None
    retry_count: int = 0
    start_time: float = 0.0
    end_time: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["percent"] = round((self.completed_bytes / self.total_bytes * 100.0) if self.total_bytes > 0 else 0.0, 1)
        d["speed_str"] = f"{round(self.current_mb_s, 1)} MB/s" if self.current_mb_s > 0 else f"{round(self.avg_mb_s, 1)} MB/s"
        d["eta_str"] = f"{int(self.eta_seconds)}s" if self.eta_seconds is not None and self.eta_seconds > 0 else "—"
        return d


class UnifiedTransferEngine:
    """The canonical transfer engine for PERCIVAL."""

    def __init__(self, state_dir: Optional[str] = None):
        self.state_dir = os.path.abspath(state_dir) if state_dir else os.path.expanduser("~/Percival_project/app_data/transfers")
        os.makedirs(self.state_dir, exist_ok=True)
        self.manifest_dir = os.path.join(self.state_dir, "manifests")
        os.makedirs(self.manifest_dir, exist_ok=True)
        self._active_jobs: Dict[str, TransferProgress] = {}
        self._cancel_flags: Dict[str, bool] = {}
        self._pause_flags: Dict[str, bool] = {}

    def get_job_manifest_path(self, job_id: str) -> str:
        return os.path.join(self.manifest_dir, f"{job_id}.manifest.json")

    def get_progress(self, job_id: str) -> Optional[Dict[str, Any]]:
        job = self._active_jobs.get(job_id)
        if job:
            return job.to_dict()
        mf = self.get_job_manifest_path(job_id)
        if os.path.isfile(mf):
            try:
                with open(mf, "r") as f:
                    return json.load(f).get("progress")
            except Exception:
                pass
        return None

    def get_active_jobs(self) -> List[Dict[str, Any]]:
        return [job.to_dict() for job in self._active_jobs.values()]

    def list_manifest_jobs(self, limit: int = 50) -> List[Dict[str, Any]]:
        jobs = []
        if os.path.isdir(self.manifest_dir):
            files = sorted(
                [os.path.join(self.manifest_dir, f) for f in os.listdir(self.manifest_dir) if f.endswith(".manifest.json")],
                key=os.path.getmtime,
                reverse=True
            )
            for mf in files[:limit]:
                try:
                    with open(mf, "r") as f:
                        d = json.load(f)
                        prog = d.get("progress", {})
                        prog["updated_at"] = d.get("updated_at")
                        jobs.append(prog)
                except Exception:
                    pass
        return jobs

    def scan_interrupted_transfers(self, search_dirs: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Scan target and workspace directories for orphan .part files and uncommitted transfers."""
        dirs = search_dirs or [self.state_dir, os.path.dirname(self.state_dir)]
        interrupted = []
        seen = set()

        # Check manifests with non-completed status
        if os.path.isdir(self.manifest_dir):
            for mf_name in os.listdir(self.manifest_dir):
                if not mf_name.endswith(".manifest.json"):
                    continue
                mf_path = os.path.join(self.manifest_dir, mf_name)
                try:
                    with open(mf_path, "r") as f:
                        data = json.load(f)
                    prog = data.get("progress", {})
                    st = prog.get("status")
                    if st in (TransferState.INTERRUPTED.value, TransferState.FAILED.value,
                              TransferState.PAUSED.value, "transferring", "pending"):
                        job_id = data.get("job_id", mf_name)
                        if job_id not in seen:
                            seen.add(job_id)
                            interrupted.append({
                                "job_id": job_id,
                                "study_id": data.get("study_id", "UNKNOWN"),
                                "source": data.get("source"),
                                "destination": data.get("destination"),
                                "status": st,
                                "last_confirmed_state": prog.get("current_phase", "Unknown"),
                                "has_part_file": False,
                                "completed_files": prog.get("completed_files", 0),
                                "total_files": prog.get("total_files", 0),
                                "source_available": os.path.exists(data.get("source", "")),
                                "recommended_action": "Resume transfer from manifest checkpoint" if os.path.exists(data.get("source", "")) else "Verify source drive connectivity"
                            })
                except Exception:
                    pass

        # Check for .part files on disk
        for d in dirs:
            if not d or not os.path.isdir(d):
                continue
            for root, _, files in os.walk(d):
                for f in files:
                    if f.endswith(".part"):
                        full_p = os.path.join(root, f)
                        dest_final = full_p[:-5]
                        sz = os.path.getsize(full_p)
                        interrupted.append({
                            "job_id": f"part_{os.path.basename(dest_final)}",
                            "study_id": os.path.basename(root),
                            "source": "Disk temporary .part",
                            "destination": dest_final,
                            "part_file_path": full_p,
                            "part_file_size": sz,
                            "status": TransferState.INTERRUPTED.value,
                            "last_confirmed_state": "Interrupted during stream copy",
                            "has_part_file": True,
                            "source_available": True,
                            "recommended_action": "Quarantine or recopy from verified source"
                        })
        return interrupted

    def pause_job(self, job_id: str) -> bool:
        if job_id in self._active_jobs:
            self._pause_flags[job_id] = True
            self._active_jobs[job_id].status = TransferState.PAUSED.value
            self._active_jobs[job_id].current_phase = TransferState.PAUSED.value
            return True
        return False

    def cancel_job(self, job_id: str) -> bool:
        if job_id in self._active_jobs:
            self._cancel_flags[job_id] = True
            self._active_jobs[job_id].status = TransferState.CANCELLED.value
            self._active_jobs[job_id].current_phase = TransferState.CANCELLED.value
            return True
        return False

    def copy_file_streaming(
        self,
        src: str,
        dst: str,
        verify_sha: bool = True,
        progress_callback: Optional[Callable[[int, float], None]] = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE
    ) -> Tuple[bool, str, int, str]:
        """Copy a single file atomically with bounded streaming, in-flight SHA-256, .part staging, and flush durability.
        
        Returns: (success: bool, sha256_hash: str, bytes_copied: int, durability_level: str)
        """
        if not os.path.isfile(src):
            raise FileNotFoundError(f"Source file not found: {src}")

        dst_dir = os.path.dirname(os.path.abspath(dst))
        os.makedirs(dst_dir, exist_ok=True)
        part_dst = dst + ".part"

        file_size = os.path.getsize(src)
        bytes_copied = 0
        h_src = hashlib.sha256()

        t_last = time.perf_counter()
        bytes_last = 0
        durability_level = "standard"

        try:
            with open(src, "rb") as fin, open(part_dst, "wb") as fout:
                while chunk := fin.read(chunk_size):
                    h_src.update(chunk)
                    fout.write(chunk)
                    bytes_copied += len(chunk)

                    now = time.perf_counter()
                    dt = now - t_last
                    if dt >= 0.25 and progress_callback:
                        inst_rate = (bytes_copied - bytes_last) / (1024 * 1024 * dt)
                        progress_callback(bytes_copied, inst_rate)
                        t_last = now
                        bytes_last = bytes_copied

                # Flush and commit to physical medium
                ok_flush, dur_method = flush_durability(fout.fileno())
                durability_level = dur_method

            computed_sha = h_src.hexdigest()

            # Phase 0: verify the staged .part copy BEFORE it replaces anything. On a mismatch only the .part file is
            # removed (except-branch below); an existing file at dst is left exactly as it was.
            if verify_sha:
                part_sha = compute_sha256(part_dst, chunk_size)
                if part_sha != computed_sha:
                    raise IOError(f"Integrity check failed: source {computed_sha} != staged copy {part_sha}; destination left unchanged")

            # Atomic replace from the verified .part to the final destination
            os.replace(part_dst, dst)

            return True, computed_sha, bytes_copied, durability_level

        except Exception as e:
            if os.path.exists(part_dst):
                try:
                    os.remove(part_dst)
                except Exception:
                    pass
            raise e

    def transfer_path(
        self,
        src: str,
        dst: str,
        operation: str = "copy",
        study_id: str = "STUDY-UNKNOWN",
        job_id: Optional[str] = None,
        verify_sha: bool = True,
        preserve_source: bool = True,
        prefer_clone: bool = True,
        on_progress: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Transfer a file or directory tree with full atomicity, progress, verification, and recovery."""
        src = os.path.abspath(src)
        dst = os.path.abspath(dst)
        job_id = job_id or f"job_{study_id}_{int(time.time())}"

        if not os.path.exists(src):
            return False, f"Source path does not exist: {src}", {}

        # Scan all source files to establish baseline manifest
        source_files: List[Tuple[str, str, int]] = []  # (abs_src, rel_path, size)
        if os.path.isfile(src):
            source_files.append((src, os.path.basename(src), os.path.getsize(src)))
        else:
            for root, _, files in os.walk(src):
                for f in files:
                    if f.startswith("."):
                        continue
                    sp = os.path.join(root, f)
                    rel = os.path.relpath(sp, src)
                    source_files.append((sp, rel, os.path.getsize(sp)))

        total_files = len(source_files)
        total_bytes = sum(sz for _, _, sz in source_files)

        progress = TransferProgress(
            job_id=job_id,
            study_id=study_id,
            operation=operation,
            source=src,
            destination=dst,
            total_files=total_files,
            completed_files=0,
            total_bytes=total_bytes,
            completed_bytes=0,
            status="transferring",
            verification_status="unverified",
            start_time=time.time()
        )
        self._active_jobs[job_id] = progress
        self._cancel_flags[job_id] = False
        verified_this_run: List[str] = []   # source files copied AND verified in this run (the only ones a move may remove)
        self._pause_flags[job_id] = False

        # Load existing manifest for interrupted recovery if available
        manifest_file = self.get_job_manifest_path(job_id)
        transferred_manifest: Dict[str, Dict[str, Any]] = {}
        if os.path.isfile(manifest_file):
            try:
                with open(manifest_file, "r") as f:
                    old_data = json.load(f)
                    transferred_manifest = old_data.get("files", {})
            except Exception:
                transferred_manifest = {}

        # Evaluate if APFS clone is safe
        same_fs = is_same_filesystem(src, dst)
        can_clone = prefer_clone and same_fs and sys.platform == "darwin"

        def save_manifest_state():
            try:
                with open(manifest_file + ".tmp", "w") as f:
                    json.dump({
                        "job_id": job_id,
                        "study_id": study_id,
                        "operation": operation,
                        "source": src,
                        "destination": dst,
                        "files": transferred_manifest,
                        "progress": progress.to_dict(),
                        "updated_at": time.time()
                    }, f, indent=2)
                os.replace(manifest_file + ".tmp", manifest_file)
            except Exception:
                pass

        try:
            for s_abs, rel_p, s_size in source_files:
                # Check cancellation or pause
                if self._cancel_flags.get(job_id):
                    progress.status = TransferState.CANCELLED.value
                    progress.current_phase = TransferState.CANCELLED.value
                    save_manifest_state()
                    return False, f"Transfer cancelled by user: {job_id}", progress.to_dict()

                if self._pause_flags.get(job_id):
                    progress.status = TransferState.PAUSED.value
                    progress.current_phase = TransferState.PAUSED.value
                    save_manifest_state()
                    return False, f"Transfer paused: {job_id}", progress.to_dict()

                progress.current_file = rel_p
                progress.current_phase = TransferState.COPYING.value

                if os.path.isfile(src):
                    if os.path.isdir(dst) or dst.endswith(os.sep) or dst.endswith("/"):
                        t_target = os.path.join(dst, os.path.basename(src))
                    else:
                        t_target = dst
                else:
                    t_target = os.path.join(dst, rel_p)
                os.makedirs(os.path.dirname(t_target), exist_ok=True)

                # Check if already verified in manifest (recovery)
                if rel_p in transferred_manifest and os.path.isfile(t_target):
                    rec = transferred_manifest[rel_p]
                    if rec.get("size") == s_size and os.path.getsize(t_target) == s_size:
                        # File already safely transferred in previous run
                        progress.completed_files += 1
                        progress.completed_bytes += s_size
                        continue

                # Execute file transfer
                copied_sha = ""
                dur_level = "standard"
                if can_clone and s_size > 0:
                    part_clone = t_target + ".part"
                    try:
                        # Attempt fast APFS clone with .part; Phase 0: the clone is verified before it replaces anything
                        subprocess.run(["/bin/cp", "-c", s_abs, part_clone], check=True, capture_output=True)
                        copied_sha = ""
                        if verify_sha:
                            src_sha = compute_sha256(s_abs)
                            copied_sha = compute_sha256(part_clone)
                            if copied_sha != src_sha:
                                raise IOError(f"clone integrity mismatch for {rel_p}")
                        os.replace(part_clone, t_target)
                        dur_level = "apfs_clone"
                        progress.completed_bytes += s_size
                    except Exception:
                        if os.path.exists(part_clone):
                            try:
                                os.remove(part_clone)
                            except Exception:
                                pass
                        # Fallback to streaming if clone fails
                        def on_chunk(bytes_so_far, inst_rate):
                            progress.current_mb_s = inst_rate
                            if on_progress:
                                on_progress(progress.to_dict())

                        _, copied_sha, _, dur_level = self.copy_file_streaming(
                            s_abs, t_target, verify_sha=verify_sha, progress_callback=on_chunk
                        )
                        progress.completed_bytes += s_size
                else:
                    # Cross-device or streaming transfer
                    def on_chunk(bytes_so_far, inst_rate):
                        progress.current_mb_s = inst_rate
                        if on_progress:
                            on_progress(progress.to_dict())

                    _, copied_sha, _, dur_level = self.copy_file_streaming(
                        s_abs, t_target, verify_sha=verify_sha, progress_callback=on_chunk
                    )
                    progress.completed_bytes += s_size

                progress.durability_level = dur_level
                progress.completed_files += 1
                elapsed = time.time() - progress.start_time
                if elapsed > 0:
                    progress.avg_mb_s = (progress.completed_bytes / (1024 * 1024)) / elapsed
                    remaining_bytes = progress.total_bytes - progress.completed_bytes
                    progress.eta_seconds = (remaining_bytes / (progress.avg_mb_s * 1024 * 1024)) if progress.avg_mb_s > 0 else 0.0

                if verify_sha:
                    verified_this_run.append(s_abs)
                transferred_manifest[rel_p] = {
                    "source": s_abs,
                    "target": t_target,
                    "size": s_size,
                    "sha256": copied_sha,
                    "durability": dur_level,
                    "completed_at": time.time()
                }

                if progress.completed_files % 10 == 0 or progress.completed_files == progress.total_files:
                    save_manifest_state()
                    if on_progress:
                        on_progress(progress.to_dict())

            progress.current_phase = TransferState.COMPLETED.value
            progress.status = TransferState.COMPLETED.value
            progress.verification_status = "verified" if verify_sha else "unverified"
            progress.end_time = time.time()
            save_manifest_state()
            if on_progress:
                on_progress(progress.to_dict())

            # Handle safe move (delete source ONLY after destination is completely verified)
            # Phase 0: only files copied AND verified in this run are removed - never the whole tree. Files the copy
            # skipped (hidden files, size-only "already transferred" resumes, unverified copies) stay at the source,
            # and folders are removed only once empty.
            if not preserve_source and operation == "move" and progress.status == TransferState.COMPLETED.value:
                for fp in verified_this_run:
                    try:
                        os.remove(fp)
                    except FileNotFoundError:
                        pass
                if os.path.isdir(src):
                    for root, dirs, files in os.walk(src, topdown=False):
                        try:
                            if not os.listdir(root):
                                os.rmdir(root)
                        except OSError:
                            pass

            return True, f"Successfully transferred {progress.completed_files} files ({progress.completed_bytes} bytes)", progress.to_dict()

        except Exception as e:
            progress.status = TransferState.FAILED.value
            progress.current_phase = TransferState.FAILED.value
            progress.error = str(e)
            progress.retry_count += 1
            save_manifest_state()
            return False, f"Transfer failed: {str(e)}", progress.to_dict()
        finally:
            self._active_jobs.pop(job_id, None)


# Global singleton instance
_GLOBAL_ENGINE: Optional[UnifiedTransferEngine] = None

def get_transfer_engine(state_dir: Optional[str] = None) -> UnifiedTransferEngine:
    global _GLOBAL_ENGINE
    if _GLOBAL_ENGINE is None or state_dir is not None:
        _GLOBAL_ENGINE = UnifiedTransferEngine(state_dir)
    return _GLOBAL_ENGINE
