"""pensieve_backup.py - Specialized SQLite backup and protection engine for PENSIEVE memory.

Implements safe, atomic SQLite backups using Python's `sqlite3.Connection.backup` API
with WAL checkpointing, pre- and post-backup PRAGMA integrity checks, SHA-256 checksums,
and dual-destination snapshot rotation (Data Vault + secondary local/cloud destination).
"""

import hashlib
import json
import os
import shutil
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


class PensieveBackupEngine:
    def __init__(
        self,
        db_path: str,
        vault_dir: Optional[str] = None,
        secondary_backup_dir: Optional[str] = None,
    ):
        self.db_path = os.path.abspath(db_path)
        self.vault_dir = os.path.abspath(vault_dir) if vault_dir else None
        self.secondary_dir = os.path.abspath(secondary_backup_dir) if secondary_backup_dir else None

    def check_source_integrity(self) -> Tuple[bool, str]:
        """Run PRAGMA integrity_check on active database."""
        if not os.path.exists(self.db_path):
            return False, f"Source database file not found: {self.db_path}"
        try:
            con = sqlite3.connect(self.db_path)
            cur = con.cursor()
            res = cur.execute("PRAGMA integrity_check;").fetchall()
            con.close()
            if res and res[0][0] == "ok":
                return True, "ok"
            return False, f"Integrity check failed: {res}"
        except Exception as e:
            return False, str(e)

    def create_snapshot(self, label: str = "auto") -> Dict[str, Any]:
        """Perform consistent online SQLite backup using Connection.backup() API."""
        # 1. Pre-check source integrity
        ok, msg = self.check_source_integrity()
        if not ok:
            raise RuntimeError(f"Cannot snapshot corrupted source database: {msg}")

        # 2. Checkpoint WAL to flush all transactions to main database file
        try:
            con = sqlite3.connect(self.db_path)
            con.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            con.close()
        except Exception:
            pass

        ts = time.strftime("%Y%m%d_%H%M%S")
        filename = f"pensieve_snapshot_{ts}_{label}.db"
        tmp_snapshot = os.path.join(os.path.dirname(self.db_path), f".{filename}.tmp")

        # 3. Use sqlite3.Connection.backup API for consistent zero-corruption copy
        src_conn = sqlite3.connect(self.db_path)
        dst_conn = sqlite3.connect(tmp_snapshot)
        try:
            src_conn.backup(dst_conn, pages=100)
        finally:
            dst_conn.close()
            src_conn.close()

        # 4. Verify integrity of the newly created snapshot
        chk_conn = sqlite3.connect(tmp_snapshot)
        try:
            cur = chk_conn.cursor()
            res = cur.execute("PRAGMA integrity_check;").fetchall()
            if not res or res[0][0] != "ok":
                raise RuntimeError(f"Created snapshot failed integrity check: {res}")
        finally:
            chk_conn.close()

        snapshot_hash = file_sha256(tmp_snapshot)
        snapshot_size = os.path.getsize(tmp_snapshot)
        destinations: List[str] = []

        # 5. Distribute to Primary Vault destination if configured
        if self.vault_dir:
            vault_snapshots_dir = os.path.join(self.vault_dir, "PENSIEVE", "snapshots")
            try:
                os.makedirs(vault_snapshots_dir, exist_ok=True)
                v_dst = os.path.join(vault_snapshots_dir, filename)
                shutil.copy2(tmp_snapshot, v_dst)
                self._rotate_snapshots(vault_snapshots_dir, max_keep=10)
                destinations.append(v_dst)
            except Exception:
                pass

        # 6. Distribute to Secondary destination if configured
        if self.secondary_dir:
            os.makedirs(self.secondary_dir, exist_ok=True)
            s_dst = os.path.join(self.secondary_dir, filename)
            shutil.copy2(tmp_snapshot, s_dst)
            self._rotate_snapshots(self.secondary_dir, max_keep=5)
            destinations.append(s_dst)

        # If no external destinations, keep in local db directory under 'snapshots'
        if not destinations:
            local_snapshots = os.path.join(os.path.dirname(self.db_path), "snapshots")
            os.makedirs(local_snapshots, exist_ok=True)
            l_dst = os.path.join(local_snapshots, filename)
            shutil.copy2(tmp_snapshot, l_dst)
            self._rotate_snapshots(local_snapshots, max_keep=10)
            destinations.append(l_dst)

        # Clean up temporary staging snapshot
        try:
            os.remove(tmp_snapshot)
        except Exception:
            pass

        return {
            "success": True,
            "filename": filename,
            "timestamp": ts,
            "label": label,
            "size_bytes": snapshot_size,
            "size_mb": round(snapshot_size / (1024**2), 2),
            "sha256": snapshot_hash,
            "destinations": destinations,
        }

    def verify_backup(self, backup_file: str) -> Dict[str, Any]:
        """Validate integrity and schema of a specific snapshot file."""
        if not os.path.isfile(backup_file):
            return {"valid": False, "error": f"File not found: {backup_file}"}

        try:
            con = sqlite3.connect(backup_file)
            cur = con.cursor()
            res = cur.execute("PRAGMA integrity_check;").fetchall()
            is_ok = bool(res and res[0][0] == "ok")
            # Query tables
            tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
            con.close()

            return {
                "valid": is_ok,
                "size_bytes": os.path.getsize(backup_file),
                "sha256": file_sha256(backup_file),
                "tables": tables,
                "error": None if is_ok else f"Corrupt: {res}",
            }
        except Exception as e:
            return {"valid": False, "error": str(e)}

    def restore_backup(self, backup_file: str, pre_restore_safety_backup: bool = True) -> Dict[str, Any]:
        """Restore database from a verified snapshot with pre-restore safety copy."""
        # 1. Verify target snapshot
        v = self.verify_backup(backup_file)
        if not v.get("valid"):
            raise ValueError(f"Cannot restore from invalid or corrupt backup: {v.get('error')}")

        safety_file = None
        # 2. Take pre-restore safety snapshot of active DB if it exists
        if pre_restore_safety_backup and os.path.exists(self.db_path):
            ts = time.strftime("%Y%m%d_%H%M%S")
            safety_file = os.path.join(os.path.dirname(self.db_path), f"pensieve_pre_restore_safety_{ts}.db")
            src_conn = sqlite3.connect(self.db_path)
            dst_conn = sqlite3.connect(safety_file)
            try:
                src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
                src_conn.close()

        # 3. Restore snapshot into active database using backup API
        b_conn = sqlite3.connect(backup_file)
        act_conn = sqlite3.connect(self.db_path)
        try:
            b_conn.backup(act_conn)
        finally:
            act_conn.close()
            b_conn.close()

        # 4. Final verification of restored database
        ok, msg = self.check_source_integrity()
        if not ok:
            # If restore failed, rollback from safety backup
            if safety_file and os.path.exists(safety_file):
                shutil.copy2(safety_file, self.db_path)
            raise RuntimeError(f"Restored database failed integrity check: {msg}")

        return {
            "success": True,
            "restored_from": backup_file,
            "safety_backup": safety_file,
            "restored_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": "Verified Healthy",
        }

    def list_snapshots(self) -> Dict[str, List[Dict[str, Any]]]:
        """Enumerate available snapshots across all configured backup locations."""
        locations = {}
        if self.vault_dir and os.path.isdir(self.vault_dir):
            vp = os.path.join(self.vault_dir, "PENSIEVE", "snapshots")
            if os.path.isdir(vp):
                locations["vault"] = self._list_dir_snapshots(vp)

        if self.secondary_dir and os.path.isdir(self.secondary_dir):
            locations["secondary"] = self._list_dir_snapshots(self.secondary_dir)

        local_p = os.path.join(os.path.dirname(self.db_path), "snapshots")
        if os.path.isdir(local_p):
            locations["local"] = self._list_dir_snapshots(local_p)

        return locations

    def _list_dir_snapshots(self, directory: str) -> List[Dict[str, Any]]:
        snaps = []
        for f in sorted(os.listdir(directory)):
            if f.startswith("pensieve_snapshot_") and f.endswith(".db"):
                fp = os.path.join(directory, f)
                snaps.append({
                    "filename": f,
                    "path": fp,
                    "size_mb": round(os.path.getsize(fp) / (1024**2), 2),
                    "modified": os.path.getmtime(fp),
                })
        return snaps

    def _rotate_snapshots(self, directory: str, max_keep: int) -> None:
        """Enforce snapshot retention policy (keeps the newest max_keep snapshots)."""
        snaps = []
        for f in os.listdir(directory):
            if f.startswith("pensieve_snapshot_") and f.endswith(".db"):
                fp = os.path.join(directory, f)
                snaps.append((os.path.getmtime(fp), fp))
        snaps.sort()
        # Remove oldest if exceeding max_keep
        while len(snaps) > max_keep:
            oldest_time, oldest_path = snaps.pop(0)
            try:
                os.remove(oldest_path)
            except Exception:
                pass
