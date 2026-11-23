"""uengine/storage/models.py - Data models for PERCIVAL Unified Storage Architecture.

Defines immutable and serializable data structures for volume tracking, storage lifecycle states,
transfer jobs, journaling, sync preview, ejection safety, and audit logs.
"""

import time
from enum import Enum
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict, field


class StudyStorageState(str, Enum):
    DISCOVERED = "DISCOVERED"
    REGISTERED = "REGISTERED"
    STAGING = "STAGING"
    STAGED = "STAGED"
    READY_FOR_PROCESSING = "READY_FOR_PROCESSING"
    PROCESSING = "PROCESSING"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVIEWED = "REVIEWED"
    AWAITING_ARCHIVAL = "AWAITING_ARCHIVAL"
    ARCHIVING = "ARCHIVING"
    ARCHIVED_VERIFIED = "ARCHIVED_VERIFIED"
    PAUSED = "PAUSED"
    TRANSFER_INTERRUPTED = "TRANSFER_INTERRUPTED"
    INTEGRITY_WARNING = "INTEGRITY_WARNING"
    CONFLICT = "CONFLICT"
    MISSING_SOURCE = "MISSING_SOURCE"
    MISSING_ARCHIVE = "MISSING_ARCHIVE"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    FAILED = "FAILED"


class DriveSafetyState(str, Enum):
    DRIVE_NOT_CONNECTED = "DRIVE NOT CONNECTED"
    DETECTING = "DETECTING"
    READY = "READY"
    BUSY = "BUSY"
    TRANSFERRING = "TRANSFERRING"
    VERIFYING = "VERIFYING"
    PREPARING_TO_EJECT = "PREPARING TO EJECT"
    BLOCKED = "BLOCKED"
    SAFE_TO_EJECT = "SAFE TO EJECT"
    UNKNOWN = "UNKNOWN"
    # Aliases for backward compatibility
    IN_USE = "BUSY"
    PREPARING = "PREPARING TO EJECT"
    ATTENTION_REQUIRED = "BLOCKED"
    DISCONNECTED = "DRIVE NOT CONNECTED"


class StorageCategory(str, Enum):
    ORIGINAL_MRI = "original_mri"
    IMPORTED_SOURCE = "imported_source"
    ACTIVE_WORKSPACE = "active_workspace"
    PROCESSED_MRI = "processed_mri"
    ALBUS_CANDIDATES = "albus_candidates"
    LUMOS_OUTPUTS = "lumos_outputs"
    NOX_OUTPUTS = "nox_outputs"
    PERCIVAL_RESULTS = "percival_results"
    EXPERT_ANNOTATIONS = "expert_annotations"
    PENSIEVE_DATABASE = "pensieve_database"
    PENSIEVE_BACKUP = "pensieve_backup"
    MODELS_CHECKPOINTS = "models_checkpoints"
    TEMPORARY_STAGING = "temporary_staging"
    PROCESSING_CACHE = "processing_cache"
    LOGS_DIAGNOSTICS = "logs_diagnostics"
    RESEARCH_DOCUMENTS = "research_documents"
    UNKNOWN = "unknown"


@dataclass
class VolumeInfo:
    mount_point: str
    volume_name: str
    filesystem: str
    device_node: str
    volume_uuid: str
    total_bytes: int
    available_bytes: int
    used_bytes: int
    is_vault: bool = False
    is_internal: bool = False
    is_connected: bool = True
    read_only: bool = False

    @property
    def free_pct(self) -> float:
        return round((self.available_bytes / self.total_bytes * 100.0) if self.total_bytes > 0 else 0.0, 1)

    @property
    def total_gb(self) -> float:
        return round(self.total_bytes / (1024**3), 2)

    @property
    def available_gb(self) -> float:
        return round(self.available_bytes / (1024**3), 2)

    @property
    def used_gb(self) -> float:
        return round(self.used_bytes / (1024**3), 2)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["free_pct"] = self.free_pct
        d["total_gb"] = self.total_gb
        d["available_gb"] = self.available_gb
        d["used_gb"] = self.used_gb
        return d


@dataclass
class EjectCheckResult:
    can_eject: bool
    state: DriveSafetyState
    reason: str
    active_operations_count: int = 0
    active_job_ids: List[str] = field(default_factory=list)
    open_handles_count: int = 0
    pending_journal_count: int = 0
    volume_uuid: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    details: Dict[str, Any] = field(default_factory=dict)      # 1e: active / parked jobs, open handles

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value if isinstance(self.state, DriveSafetyState) else self.state
        return d


@dataclass
class SyncItem:
    study_id: str
    relative_path: str
    source_path: str
    destination_path: str
    size_bytes: int
    action: str  # copy, skip, conflict, archive
    source_sha256: str = ""
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SyncPreview:
    mode: str
    total_items: int
    total_bytes: int
    items_to_copy: List[SyncItem] = field(default_factory=list)
    items_conflicting: List[SyncItem] = field(default_factory=list)
    items_skipped: List[SyncItem] = field(default_factory=list)
    destination_available_bytes: int = 0
    can_proceed: bool = True
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "total_items": self.total_items,
            "total_bytes": self.total_bytes,
            "total_mb": round(self.total_bytes / (1024**2), 2),
            "to_copy_count": len(self.items_to_copy),
            "conflict_count": len(self.items_conflicting),
            "skipped_count": len(self.items_skipped),
            "items_to_copy": [i.to_dict() for i in self.items_to_copy],
            "items_conflicting": [i.to_dict() for i in self.items_conflicting],
            "items_skipped": [i.to_dict() for i in self.items_skipped],
            "destination_available_gb": round(self.destination_available_bytes / (1024**3), 2),
            "can_proceed": self.can_proceed,
            "message": self.message
        }
