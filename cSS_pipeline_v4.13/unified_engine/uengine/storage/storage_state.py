"""uengine/storage/storage_state.py - Authoritative Storage State & SQLite Journal Service.

Acts as the single source of truth for:
- Study storage locations across Mac SSD and External Vault
- Durable transfer jobs and per-file progress/verification states
- SQLite journal on internal SSD with WAL mode
- Audit logging for all storage operations
- Ejection eligibility and drive safety state
"""

import os
import time
import json
import sqlite3
import threading
from typing import Dict, Any, List, Optional, Tuple
from .models import StudyStorageState, DriveSafetyState, VolumeInfo
from .storage_paths import StoragePathsService


class StorageStateService:
    """Authoritative storage state manager backed by a transactional SQLite journal."""

    def __init__(self, paths_service: Optional[StoragePathsService] = None):
        self.paths = paths_service or StoragePathsService()
        self.db_dir = os.path.join(self.paths.workspace_root, "app_data", "transfers")
        os.makedirs(self.db_dir, exist_ok=True)
        self.db_path = os.path.join(self.db_dir, "storage_journal.db")
        self._lock = threading.RLock()
        self._init_journal_schema()

    def _get_connection(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path, timeout=30.0)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
        con.execute("PRAGMA foreign_keys=ON;")
        return con

    def _init_journal_schema(self) -> None:
        with self._lock, self._get_connection() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS transfer_jobs (
                    job_id TEXT PRIMARY KEY,
                    study_id TEXT NOT NULL,
                    operation TEXT NOT NULL, -- stage, archive, restore, copy, move
                    source_root TEXT NOT NULL,
                    dest_root TEXT NOT NULL,
                    status TEXT NOT NULL, -- pending, running, paused, completed, failed, cancelled
                    verification_status TEXT DEFAULT 'unverified',
                    total_files INTEGER DEFAULT 0,
                    completed_files INTEGER DEFAULT 0,
                    total_bytes INTEGER DEFAULT 0,
                    completed_bytes INTEGER DEFAULT 0,
                    current_mb_s REAL DEFAULT 0.0,
                    avg_mb_s REAL DEFAULT 0.0,
                    eta_seconds REAL DEFAULT 0.0,
                    error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    completed_at REAL
                );

                CREATE TABLE IF NOT EXISTS transfer_files (
                    file_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    study_id TEXT NOT NULL,
                    rel_path TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    dest_path TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    sha256 TEXT,
                    state TEXT NOT NULL, -- pending, copying, copied, verifying, verified, failed
                    error TEXT,
                    completed_at REAL,
                    FOREIGN KEY(job_id) REFERENCES transfer_jobs(job_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS storage_audit_events (
                    event_id TEXT PRIMARY KEY,
                    timestamp REAL NOT NULL,
                    operation_id TEXT,
                    study_id TEXT,
                    action TEXT NOT NULL,
                    source TEXT,
                    destination TEXT,
                    result TEXT NOT NULL, -- success, failure, warning
                    checksum TEXT,
                    details TEXT -- JSON
                );

                CREATE TABLE IF NOT EXISTS study_storage_ledger (
                    study_id TEXT PRIMARY KEY,
                    lifecycle_state TEXT NOT NULL,
                    original_mri_location TEXT,
                    active_workspace_location TEXT,
                    hdd_archive_location TEXT,
                    file_count INTEGER DEFAULT 0,
                    total_size_bytes INTEGER DEFAULT 0,
                    archive_status TEXT DEFAULT 'not_archived',
                    review_status TEXT DEFAULT 'incomplete',
                    last_operation TEXT,
                    updated_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_tf_job ON transfer_files(job_id);
                CREATE INDEX IF NOT EXISTS idx_audit_time ON storage_audit_events(timestamp);
            """)

    def record_audit_event(self, action: str, result: str, study_id: Optional[str] = None,
                           op_id: Optional[str] = None, src: Optional[str] = None,
                           dst: Optional[str] = None, checksum: Optional[str] = None,
                           details: Optional[Dict[str, Any]] = None) -> None:
        """Record an auditable storage action in the journal."""
        event_id = f"evt_{int(time.time() * 1000)}_{os.urandom(3).hex()}"
        with self._lock, self._get_connection() as con:
            con.execute(
                """INSERT INTO storage_audit_events
                   (event_id, timestamp, operation_id, study_id, action, source, destination, result, checksum, details)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (event_id, time.time(), op_id, study_id, action, src, dst, result, checksum, json.dumps(details or {}))
            )

    def get_audit_events(self, limit: int = 50, study_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock, self._get_connection() as con:
            if study_id:
                cur = con.execute("SELECT * FROM storage_audit_events WHERE study_id = ? ORDER BY timestamp DESC LIMIT ?", (study_id, limit))
            else:
                cur = con.execute("SELECT * FROM storage_audit_events ORDER BY timestamp DESC LIMIT ?", (limit,))
            return [dict(r) for r in cur.fetchall()]

    def update_job_status(self, job_id: str, status: str, completed_files: int = 0,
                          completed_bytes: int = 0, current_mb_s: float = 0.0,
                          avg_mb_s: float = 0.0, eta_seconds: float = 0.0,
                          error: Optional[str] = None) -> None:
        now = time.time()
        completed_at = now if status in ("completed", "failed", "cancelled") else None
        with self._lock, self._get_connection() as con:
            con.execute(
                """UPDATE transfer_jobs
                   SET status = ?, completed_files = ?, completed_bytes = ?, current_mb_s = ?,
                       avg_mb_s = ?, eta_seconds = ?, error = ?, updated_at = ?, completed_at = COALESCE(?, completed_at)
                   WHERE job_id = ?""",
                (status, completed_files, completed_bytes, current_mb_s, avg_mb_s, eta_seconds, error, now, completed_at, job_id)
            )

    def get_active_transfers_count(self) -> int:
        with self._lock, self._get_connection() as con:
            row = con.execute("SELECT COUNT(*) FROM transfer_jobs WHERE status IN ('running', 'transferring')").fetchone()
            return row[0] if row else 0

    def get_all_jobs(self, limit: int = 30) -> List[Dict[str, Any]]:
        with self._lock, self._get_connection() as con:
            rows = con.execute("SELECT * FROM transfer_jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    def get_storage_overview(self) -> Dict[str, Any]:
        """Produce authoritative storage overview for the GUI."""
        ssd_info = self.paths.get_internal_ssd_info()
        vault_info = self.paths.get_vault_info()

        # Categorize SSD workspace data
        ws = self.paths.workspace_root
        active_ws_bytes = 0
        staging_bytes = 0
        scratch_bytes = 0

        for cat, rel in [("staging", "app_data/staging"), ("scratch", "app_data/scratch"), ("work", "work")]:
            p = os.path.join(ws, rel)
            if os.path.isdir(p):
                sz = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(p) for f in fs)
                if cat == "staging": staging_bytes = sz
                elif cat == "scratch": scratch_bytes = sz
                elif cat == "work": active_ws_bytes = sz

        return {
            "mac_internal": {
                "total_gb": ssd_info.total_gb,
                "available_gb": ssd_info.available_gb,
                "used_gb": ssd_info.used_gb,
                "free_pct": ssd_info.free_pct,
                "active_workspace_mb": round(active_ws_bytes / (1024**2), 1),
                "staging_buffer_mb": round(staging_bytes / (1024**2), 1),
                "scratch_mb": round(scratch_bytes / (1024**2), 1),
                "tier": "EMERGENCY" if ssd_info.available_gb < 15 else ("CRITICAL" if ssd_info.available_gb < 35 else "HEALTHY")
            },
            "external_vault": {
                "connected": vault_info is not None and vault_info.is_connected,
                "total_gb": vault_info.total_gb if vault_info else 0.0,
                "available_gb": vault_info.available_gb if vault_info else 0.0,
                "used_gb": vault_info.used_gb if vault_info else 0.0,
                "free_pct": vault_info.free_pct if vault_info else 0.0,
                "mount_point": vault_info.mount_point if vault_info else "Disconnected",
                "volume_uuid": vault_info.volume_uuid if vault_info else "none",
                "tier": "HEALTHY" if (vault_info and vault_info.available_gb > 50) else ("CRITICAL" if vault_info else "DISCONNECTED")
            },
            "active_transfers": self.get_active_transfers_count()
        }
