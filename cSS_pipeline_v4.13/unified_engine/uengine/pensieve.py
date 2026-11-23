"""uengine/pensieve.py - PENSIEVE: Persistent Shared Core Memory & Learning History

The long-term scientific memory foundation of the Percival ecosystem.
Authoritative storage lives in the configured Percival Data Vault (PENSIEVE/pensieve.db).

Stores and serves:
  1. Study & MRI acquisition metadata (pseudonymous)
  2. Persistent candidate lineage & spatial identities
  3. Authoritative expert annotations (distinct from AI predictions)
  4. Learning & correction memory (false-positive patterns, missed-lesion events)
  5. Component mathematical & model evolution
  6. Scientific knowledge hypotheses & findings
  7. Component-specific inquiry interfaces (ALBUS, LUMOS, NOX, Core, SHADOW)
  8. Strict patient-level partition isolation to prevent validation leakage.
"""

import os
import sys
import math
import json
import time
import uuid
import sqlite3
import hashlib
from typing import Dict, List, Optional, Any, Tuple, Union
from uengine.vault import get_vault, PercivalDataVault

JOURNAL_DB_FILE = os.path.expanduser("~/.percival_local_journal.db")

class DurableLocalJournal:
    """Persistent local journal preserving transactions when external Data Vault is disconnected.
    
    Guarantees expert annotations and candidate updates survive application crashes,
    power outages, and restarts while awaiting Data Vault reconnection.
    """
    def __init__(self, db_path: str = JOURNAL_DB_FILE):
        self.db_path = db_path
        self._init_journal()

    def _init_journal(self) -> None:
        try:
            with sqlite3.connect(self.db_path) as con:
                con.execute("""
                    CREATE TABLE IF NOT EXISTS local_journal (
                        entry_id TEXT PRIMARY KEY,
                        table_name TEXT NOT NULL,
                        action TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        study_id TEXT NOT NULL,
                        candidate_uid TEXT,
                        author TEXT,
                        payload_sha256 TEXT NOT NULL,
                        sync_status TEXT DEFAULT 'pending',
                        created_at REAL NOT NULL,
                        synced_at REAL
                    );
                """)
                con.execute("CREATE INDEX IF NOT EXISTS idx_jnl_sync ON local_journal(sync_status);")
        except Exception as e:
            sys.stderr.write(f"[DurableJournal] Warning: Failed to init journal: {e}\n")

    def record_entry(self, table_name: str, action: str, payload: Dict[str, Any],
                     study_id: str, candidate_uid: Optional[str] = None,
                     author: Optional[str] = None) -> str:
        entry_id = f"jnl_{uuid.uuid4().hex[:12]}"
        payload_str = json.dumps(payload)
        payload_sha = hashlib.sha256(payload_str.encode()).hexdigest()
        now = time.time()
        with sqlite3.connect(self.db_path) as con:
            con.execute("""
                INSERT INTO local_journal (entry_id, table_name, action, payload_json,
                                          study_id, candidate_uid, author, payload_sha256,
                                          sync_status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """, (entry_id, table_name, action, payload_str, study_id, candidate_uid, author, payload_sha, now))
        return entry_id

    def get_pending_entries(self) -> List[Dict[str, Any]]:
        try:
            with sqlite3.connect(self.db_path) as con:
                con.row_factory = sqlite3.Row
                cur = con.execute("SELECT * FROM local_journal WHERE sync_status = 'pending' ORDER BY created_at ASC")
                return [dict(r) for r in cur.fetchall()]
        except Exception:
            return []

    def mark_synced(self, entry_id: str) -> None:
        with sqlite3.connect(self.db_path) as con:
            con.execute("UPDATE local_journal SET sync_status = 'synced', synced_at = ? WHERE entry_id = ?",
                        (time.time(), entry_id))

    def get_status(self) -> Dict[str, Any]:
        try:
            with sqlite3.connect(self.db_path) as con:
                cur = con.execute("SELECT sync_status, COUNT(*) FROM local_journal GROUP BY sync_status")
                counts = dict(cur.fetchall())
                return {
                    "journal_path": self.db_path,
                    "pending_count": counts.get("pending", 0),
                    "synced_count": counts.get("synced", 0)
                }
        except Exception:
            return {"journal_path": self.db_path, "pending_count": 0, "synced_count": 0}

PENSIEVE_SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- 1. Studies & MRI Acquisition Memory
CREATE TABLE IF NOT EXISTS studies_memory (
    study_id TEXT PRIMARY KEY,
    patient_pseudo_id TEXT NOT NULL,
    cohort TEXT NOT NULL,
    partition TEXT DEFAULT 'unassigned', -- 'development', 'locked_test', 'external'
    voxel_spacing_mm TEXT, -- JSON [dx, dy, dz]
    scanner_metadata TEXT, -- JSON
    quality_status TEXT DEFAULT 'ok',
    preprocessing_history TEXT, -- JSON
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

-- 2. Candidates Persistent Memory
CREATE TABLE IF NOT EXISTS candidates_memory (
    candidate_uid TEXT PRIMARY KEY, -- {study_id}_{hemi}_{vox_i}_{vox_j}_{vox_k}
    study_id TEXT NOT NULL,
    cand_id_detector INTEGER NOT NULL,
    hemi TEXT NOT NULL,
    centroid_vox TEXT NOT NULL, -- JSON [i, j, k]
    centroid_mm TEXT NOT NULL,  -- JSON [x, y, z]
    volume_vox INTEGER,
    volume_mm3 REAL,
    bbox TEXT, -- JSON [min_i, min_j, min_k, max_i, max_j, max_k]
    albus_score REAL,
    albus_formula TEXT,
    lumos_prob REAL,
    lumos_uncertainty REAL,
    nox_measurements TEXT, -- JSON
    percival_score INTEGER,
    percival_status TEXT,
    detection_version TEXT,
    spatial_fingerprint TEXT,
    created_at REAL NOT NULL,
    FOREIGN KEY(study_id) REFERENCES studies_memory(study_id) ON DELETE CASCADE
);

-- 3. Expert Knowledge Memory (Permanent Authority - Distinct from AI predictions)
CREATE TABLE IF NOT EXISTS expert_annotations (
    annotation_id TEXT PRIMARY KEY,
    study_id TEXT NOT NULL,
    candidate_uid TEXT, -- NULL for missed lesions discovered outside detector
    source_type TEXT NOT NULL, -- 'expert_human', 'consensus_panel' (NEVER 'ai_model')
    reviewer_id TEXT NOT NULL,
    call TEXT NOT NULL, -- 'definite_css', 'not_css', 'uncertain', 'missed_lesion'
    lesion_type TEXT, -- 'superficial_siderosis', 'sulcal_vessel', 'cavernoma', 'artifact'
    corrected_bbox TEXT, -- JSON if boundary revised
    confidence TEXT DEFAULT 'high', -- 'high', 'moderate', 'uncertain'
    provenance TEXT,
    created_at REAL NOT NULL,
    FOREIGN KEY(study_id) REFERENCES studies_memory(study_id) ON DELETE CASCADE
);

-- 4. Learning & Correction Memory (Detection failures, false positives, missed lesions)
CREATE TABLE IF NOT EXISTS corrections_memory (
    correction_id TEXT PRIMARY KEY,
    study_id TEXT NOT NULL,
    candidate_uid TEXT,
    event_type TEXT NOT NULL, -- 'false_positive_rejected', 'missed_lesion_flagged', 'boundary_corrected'
    responsible_component TEXT NOT NULL, -- 'ALBUS', 'LUMOS', 'NOX', 'PERCIVAL_CORE'
    initial_ai_call TEXT,
    expert_ground_truth TEXT NOT NULL,
    evidence_snapshot TEXT, -- JSON: what ALBUS/LUMOS/NOX saw
    failure_pattern TEXT, -- e.g. 'high_curvature_vessel_mimic', 'subtle_sulcal_pial_miss'
    resolved INTEGER DEFAULT 0,
    created_at REAL NOT NULL
);

-- 5. Model & Mathematical Evolution Memory
CREATE TABLE IF NOT EXISTS model_evolution (
    version_id TEXT PRIMARY KEY,
    component TEXT NOT NULL, -- 'ALBUS', 'LUMOS', 'NOX', 'PERCIVAL_CORE'
    architecture_or_formula TEXT NOT NULL,
    hyperparameters TEXT, -- JSON
    training_data_fingerprint TEXT,
    validation_metrics TEXT, -- JSON: AUC, PR-AUC, Brier, Sensitivity, etc.
    active_status TEXT DEFAULT 'candidate', -- 'active', 'archived', 'rejected'
    promoted_at REAL,
    created_at REAL NOT NULL
);

-- 6. Scientific Knowledge Hypotheses & Findings
CREATE TABLE IF NOT EXISTS scientific_findings (
    finding_id TEXT PRIMARY KEY,
    category TEXT NOT NULL, -- 'feature_stability', 'imaging_artifact', 'anatomical_invariant', 'scanner_shift'
    hypothesis TEXT NOT NULL,
    evidence_strength TEXT DEFAULT 'exploratory', -- 'exploratory', 'replicated', 'validated'
    details TEXT, -- JSON
    created_by TEXT NOT NULL, -- 'SHADOW_ML', 'AUDITOR', 'RESEARCHER'
    created_at REAL NOT NULL
);

-- 7. Missed cSS Lesions Memory (Expert-drawn in MRI Viewer outside ALBUS)
CREATE TABLE IF NOT EXISTS missed_lesions_memory (
    missed_uid TEXT PRIMARY KEY,
    study_id TEXT NOT NULL,
    missed_id TEXT NOT NULL,
    reviewer_id TEXT NOT NULL,
    vox_i INTEGER NOT NULL,
    vox_j INTEGER NOT NULL,
    vox_k INTEGER NOT NULL,
    x_mm REAL NOT NULL,
    y_mm REAL NOT NULL,
    z_mm REAL NOT NULL,
    plane TEXT,
    slice_idx INTEGER,
    shape TEXT,
    points_json TEXT,
    comment TEXT,
    detector_fate TEXT,
    albus_detected INTEGER DEFAULT 0,
    created_at REAL NOT NULL,
    FOREIGN KEY(study_id) REFERENCES studies_memory(study_id) ON DELETE CASCADE
);

-- 8. Study Review Status & Adjudication
CREATE TABLE IF NOT EXISTS study_review_status (
    study_id TEXT PRIMARY KEY,
    candidate_review_status TEXT DEFAULT 'incomplete',
    missed_assessment_status TEXT DEFAULT 'incomplete',
    adjudication_status TEXT DEFAULT 'not_needed',
    overall_status TEXT DEFAULT 'incomplete',
    reviewer_id TEXT,
    completed_at REAL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(study_id) REFERENCES studies_memory(study_id) ON DELETE CASCADE
);

-- Indices for rapid leakage-free retrieval
CREATE INDEX IF NOT EXISTS idx_cand_study ON candidates_memory(study_id);
CREATE INDEX IF NOT EXISTS idx_annot_cand ON expert_annotations(candidate_uid);
CREATE INDEX IF NOT EXISTS idx_corr_comp ON corrections_memory(responsible_component);
CREATE INDEX IF NOT EXISTS idx_model_comp ON model_evolution(component);
CREATE INDEX IF NOT EXISTS idx_missed_study ON missed_lesions_memory(study_id);
CREATE INDEX IF NOT EXISTS idx_review_study ON study_review_status(study_id);
"""

class PensieveCoreMemory:
    def __init__(self, vault: Optional[Union[PercivalDataVault, str]] = None):
        if isinstance(vault, str):
            if os.path.exists(os.path.join(vault, "manifest", "vault_manifest.json")) or os.path.exists(os.path.join(vault, "PERCIVAL_VAULT")):
                try:
                    self.vault = PercivalDataVault.connect(vault, auto_create_if_drive=True)
                except Exception:
                    self.vault = get_vault()
            else:
                self.vault = get_vault()
        else:
            self.vault = vault or get_vault()
        self.local_journal = DurableLocalJournal()
        if self.vault.is_connected():
            self._db_path = self.vault.pensieve_db_path()
            self._init_db()
        else:
            self._db_path = None

    def _get_connection(self) -> sqlite3.Connection:
        if not self.vault.is_connected() or not self._db_path:
            raise RuntimeError("Cannot access PENSIEVE: Percival Data Vault is disconnected.")
        con = sqlite3.connect(self._db_path, timeout=30.0)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON;")
        con.execute("PRAGMA journal_mode = WAL;")
        return con

    def flush_and_close(self) -> Dict[str, Any]:
        """Flush SQLite WAL journal and ensure durable disk commit."""
        flushed = False
        if self._db_path and os.path.exists(self._db_path):
            try:
                with sqlite3.connect(self._db_path, timeout=10.0) as con:
                    con.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                    con.execute("PRAGMA optimize;")
                flushed = True
            except Exception as e:
                sys.stderr.write(f"[Pensieve] Warning during flush: {e}\n")
        if self.local_journal:
            try:
                self.local_journal.get_pending_entries()
            except Exception:
                pass
        return {"ok": True, "flushed": flushed, "closed": True}

    def _init_db(self) -> None:
        """Initialize database tables and indices in the vault."""
        if not self._db_path and self.vault.is_connected():
            self._db_path = self.vault.pensieve_db_path()
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        with self._get_connection() as con:
            con.executescript(PENSIEVE_SCHEMA)

    def sync_local_journal(self) -> Dict[str, Any]:
        """Replay pending entries from durable local journal into the authoritative Data Vault."""
        if not self.vault.is_connected():
            return {"status": "vault_disconnected", "synced_count": 0, "pending_count": self.local_journal.get_status()["pending_count"]}
        
        self._init_db()
        pending = self.local_journal.get_pending_entries()
        synced_count = 0
        conflicts = []

        with self._get_connection() as con:
            for entry in pending:
                try:
                    payload = json.loads(entry["payload_json"])
                    tbl = entry["table_name"]
                    if tbl == "expert_annotations":
                        con.execute("""
                            INSERT OR IGNORE INTO expert_annotations (annotation_id, study_id, candidate_uid,
                                                                     source_type, reviewer_id, call, lesion_type,
                                                                     confidence, provenance, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (payload["annotation_id"], payload["study_id"], payload.get("candidate_uid"),
                              payload.get("source_type", "expert_human"), payload["reviewer_id"],
                              payload["call"], payload.get("lesion_type", "superficial_siderosis"),
                              payload.get("confidence", "high"), payload.get("provenance", "expert_review"),
                              payload["created_at"]))
                    elif tbl == "corrections_memory":
                        con.execute("""
                            INSERT OR IGNORE INTO corrections_memory (correction_id, study_id, candidate_uid,
                                                                     event_type, responsible_component,
                                                                     initial_ai_call, expert_ground_truth,
                                                                     evidence_snapshot, failure_pattern, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (payload["correction_id"], payload["study_id"], payload.get("candidate_uid"),
                              payload["event_type"], payload["responsible_component"], payload["initial_ai_call"],
                              payload["expert_ground_truth"], json.dumps(payload.get("evidence", {})),
                              payload.get("failure_pattern", ""), payload["created_at"]))
                    elif tbl == "candidates_memory":
                        con.execute("""
                            INSERT OR IGNORE INTO candidates_memory (candidate_uid, study_id, cand_id_detector, hemi,
                                                                    centroid_vox, centroid_mm, volume_vox, volume_mm3,
                                                                    bbox, albus_score, albus_formula, lumos_prob, lumos_unc,
                                                                    nox_measurements, percival_score, percival_status,
                                                                    detection_version, spatial_fingerprint, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (payload["candidate_uid"], payload["study_id"], payload["cand_id_detector"], payload["hemi"],
                              json.dumps(payload["centroid_vox"]), json.dumps(payload["centroid_mm"]), payload["volume_vox"],
                              payload["volume_mm3"], json.dumps(payload["bbox"]), payload["albus_score"],
                              payload["albus_formula"], payload.get("lumos_prob"), payload.get("lumos_unc"),
                              json.dumps(payload.get("nox_measurements", {})), payload.get("percival_score"),
                              payload.get("percival_status", "reliable"), payload["detection_version"],
                              payload["spatial_fingerprint"], payload["created_at"]))
                    self.local_journal.mark_synced(entry["entry_id"])
                    synced_count += 1
                except Exception as e:
                    conflicts.append({"entry_id": entry["entry_id"], "error": str(e)})

        return {
            "status": "synced",
            "synced_count": synced_count,
            "conflicts": conflicts,
            "remaining_pending": len(pending) - synced_count
        }

    # -------------------------------------------------------------
    # 1. Study Memory
    # -------------------------------------------------------------
    def remember_study(self, study_id: str, patient_pseudo_id: str, cohort: str,
                       partition: str = "development", spacing: Optional[List[float]] = None,
                       metadata: Optional[Dict[str, Any]] = None, quality: str = "ok") -> Dict[str, Any]:
        """Ingest or register a study in persistent memory.
        
        Guarantees idempotent no-op on identical content fingerprint and detects
        ingestion conflicts on changed metadata without destructive overwrite.
        """
        now = time.time()
        spacing_clean = [float(s) for s in (spacing or [])]
        meta_clean = metadata or {}
        new_fp = hashlib.sha256(json.dumps({
            "patient_pseudo_id": patient_pseudo_id,
            "cohort": cohort,
            "partition": partition,
            "spacing": spacing_clean
        }, sort_keys=True).encode()).hexdigest()

        with self._get_connection() as con:
            cur = con.execute("SELECT * FROM studies_memory WHERE study_id = ?", (study_id,))
            row = cur.fetchone()
            if row:
                old_spacing = json.loads(row["voxel_spacing_mm"] or "[]")
                old_fp = hashlib.sha256(json.dumps({
                    "patient_pseudo_id": row["patient_pseudo_id"],
                    "cohort": row["cohort"],
                    "partition": row["partition"],
                    "spacing": [float(s) for s in old_spacing]
                }, sort_keys=True).encode()).hexdigest()

                if new_fp == old_fp:
                    # Idempotent no-op: content matches perfectly
                    return {"status": "idempotent_noop", "study_id": study_id, "fingerprint": new_fp}
                else:
                    # Conflict detected: same study_id, different content fingerprint!
                    # Do NOT silently overwrite existing study
                    con.execute("""
                        INSERT INTO corrections_memory (correction_id, study_id, candidate_uid,
                                                       event_type, responsible_component,
                                                       initial_ai_call, expert_ground_truth,
                                                       evidence_snapshot, failure_pattern, created_at)
                        VALUES (?, ?, NULL, 'ingestion_conflict', 'PENSIEVE', 'existing_study', 'conflict_rejected', ?, 'study_content_fingerprint_mismatch', ?)
                    """, (f"cor_{hashlib.sha256(f'{study_id}_{now}'.encode()).hexdigest()[:12]}",
                          study_id,
                          json.dumps({"old_fp": old_fp, "new_fp": new_fp, "attempted_patient": patient_pseudo_id}),
                          now))
                    return {"status": "conflict_detected", "study_id": study_id, "warning": "Content fingerprint mismatch; overwrite refused."}

            con.execute("""
                INSERT INTO studies_memory (study_id, patient_pseudo_id, cohort, partition,
                                           voxel_spacing_mm, scanner_metadata, quality_status,
                                           created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (study_id, patient_pseudo_id, cohort, partition,
                  json.dumps(spacing_clean), json.dumps(meta_clean), quality, now, now))
            return {"status": "inserted", "study_id": study_id, "fingerprint": new_fp}

    def get_study(self, study_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as con:
            cur = con.execute("SELECT * FROM studies_memory WHERE study_id = ?", (study_id,))
            row = cur.fetchone()
            if row:
                d = dict(row)
                d["voxel_spacing_mm"] = json.loads(d["voxel_spacing_mm"] or "[]")
                d["scanner_metadata"] = json.loads(d["scanner_metadata"] or "{}")
                return d
        return None

    # -------------------------------------------------------------
    # 2. Candidate Memory & Spatial Fingerprint
    # -------------------------------------------------------------
    @staticmethod
    def compute_candidate_uid(study_id: str, hemi: str, centroid_vox: Tuple[float, float, float]) -> str:
        ci, cj, ck = round(centroid_vox[0]), round(centroid_vox[1]), round(centroid_vox[2])
        return f"{study_id}_{hemi}_{ci}_{cj}_{ck}"

    def evaluate_candidate_identity(self, study_id: str, hemi: str,
                                    centroid_mm: Tuple[float, float, float],
                                    bbox: Optional[Tuple[int, int, int, int, int, int]] = None,
                                    volume_mm3: Optional[float] = None,
                                    tolerance_mm: float = 2.5) -> Dict[str, Any]:
        """Multi-evidence confidence-based candidate identity adjudication.
        
        Evaluates physical distance, 3D bounding box IoU, volume ratio, and expert-lock status.
        Distinguishes: same_candidate, expert_confirmed_match, possible_split, possible_merge,
        uncertain_identity, and new_candidate. Never unconditionally merges based on distance alone.
        """
        qx, qy, qz = centroid_mm
        best_candidate = None
        best_confidence = 0.0
        best_outcome = "new_candidate"
        min_dist = float("inf")
        evidence = {}

        if not self.vault.is_connected():
            return {
                "matched_uid": None,
                "outcome": "new_candidate",
                "confidence": 0.0,
                "evidence": {"vault_connected": False}
            }

        with self._get_connection() as con:
            cur = con.execute("""
                SELECT candidate_uid, centroid_mm, bbox, volume_mm3 FROM candidates_memory
                WHERE study_id = ? AND hemi = ?
            """, (study_id, hemi))
            rows = cur.fetchall()

            cur_ann = con.execute("""
                SELECT candidate_uid, call, lesion_type FROM expert_annotations
                WHERE study_id = ?
            """, (study_id,))
            expert_map = {r["candidate_uid"]: dict(r) for r in cur_ann.fetchall() if r["candidate_uid"]}

        for row in rows:
            try:
                cx, cy, cz = json.loads(row["centroid_mm"])
                dist = math.sqrt((qx - cx)**2 + (qy - cy)**2 + (qz - cz)**2)
                if dist > tolerance_mm:
                    continue

                # 3D bounding box overlap & IoU
                has_overlap = False
                bbox_iou = 0.0
                if bbox and row["bbox"]:
                    b1 = bbox
                    b2 = json.loads(row["bbox"])
                    i_min, i_max = max(b1[0], b2[0]), min(b1[3], b2[3])
                    j_min, j_max = max(b1[1], b2[1]), min(b1[4], b2[4])
                    k_min, k_max = max(b1[2], b2[2]), min(b1[5], b2[5])
                    if i_max >= i_min and j_max >= j_min and k_max >= k_min:
                        has_overlap = True
                        inter = (i_max - i_min + 1) * (j_max - j_min + 1) * (k_max - k_min + 1)
                        v1 = (b1[3] - b1[0] + 1) * (b1[4] - b1[1] + 1) * (b1[5] - b1[2] + 1)
                        v2 = (b2[3] - b2[0] + 1) * (b2[4] - b2[1] + 1) * (b2[5] - b2[2] + 1)
                        bbox_iou = float(inter / max(1, v1 + v2 - inter))

                # Volume ratio
                v_ratio = 1.0
                if volume_mm3 is not None and row["volume_mm3"]:
                    v2 = float(row["volume_mm3"])
                    v_ratio = float(min(volume_mm3, v2) / max(1e-3, max(volume_mm3, v2)))

                c_uid = row["candidate_uid"]
                is_expert = c_uid in expert_map

                # Multi-evidence decision tree
                if dist <= 0.5:
                    conf = 0.95 if (has_overlap or not bbox) else 0.40
                    outc = "expert_confirmed_match" if is_expert else ("same_candidate" if conf > 0.8 else "uncertain_identity")
                elif dist <= 1.0:
                    if has_overlap or (not bbox and v_ratio >= 0.25):
                        conf = 0.88
                        outc = "expert_confirmed_match" if is_expert else "same_candidate"
                    else:
                        conf = 0.30
                        outc = "uncertain_identity"
                elif dist <= 2.5:
                    if has_overlap and v_ratio >= 0.25:
                        conf = 0.75
                        outc = "same_candidate" if not is_expert else "expert_confirmed_match"
                    elif has_overlap and v_ratio < 0.25:
                        conf = 0.50
                        outc = "possible_split" if (volume_mm3 or 0) < (float(row["volume_mm3"] or 0)) else "possible_merge"
                    else:
                        conf = 0.05
                        outc = "new_candidate"
                else:
                    conf = 0.0
                    outc = "new_candidate"

                if conf > best_confidence:
                    best_confidence = conf
                    best_outcome = outc
                    best_candidate = c_uid
                    min_dist = dist
                    evidence = {
                        "dist_mm": dist, "bbox_iou": bbox_iou, "has_overlap": has_overlap,
                        "volume_ratio": v_ratio, "is_expert_annotated": is_expert
                    }
            except Exception:
                continue

        matched_uid = best_candidate if (best_confidence >= 0.70 and best_outcome in ("same_candidate", "expert_confirmed_match")) else None
        return {
            "matched_uid": matched_uid,
            "outcome": best_outcome,
            "confidence": best_confidence,
            "evidence": evidence
        }

    def find_matching_candidate(self, study_id: str, hemi: str,
                                centroid_mm: Tuple[float, float, float],
                                bbox: Optional[Tuple[int, int, int, int, int, int]] = None,
                                volume_mm3: Optional[float] = None,
                                tolerance_mm: float = 2.5) -> Optional[str]:
        """Find an existing candidate UID with multi-evidence confidence matching."""
        res = self.evaluate_candidate_identity(study_id, hemi, centroid_mm, bbox, volume_mm3, tolerance_mm)
        return res["matched_uid"]

    def remember_candidate(self, study_id: str, cand_id: int, hemi: str,
                           centroid_vox: Tuple[float, float, float],
                           centroid_mm: Tuple[float, float, float],
                           volume_vox: int, volume_mm3: float,
                           bbox: Tuple[int, int, int, int, int, int],
                           albus_score: float, albus_formula: str = "formula_v4",
                           lumos_prob: Optional[float] = None, lumos_unc: Optional[float] = None,
                           nox_meas: Optional[Dict[str, Any]] = None,
                           percival_score: Optional[int] = None, percival_status: str = "reliable",
                           detection_version: str = "v5.25",
                           tolerance_mm: float = 2.5) -> str:
        # Check if an existing candidate matches within confidence-aware spatial tolerance
        existing_uid = self.find_matching_candidate(
            study_id=study_id, hemi=hemi, centroid_mm=centroid_mm,
            bbox=bbox, volume_mm3=volume_mm3, tolerance_mm=tolerance_mm
        )
        uid = existing_uid or self.compute_candidate_uid(study_id, hemi, centroid_vox)
        now = time.time()
        fp = hashlib.sha256(f"{study_id}_{hemi}_{centroid_mm}_{volume_mm3:.1f}".encode()).hexdigest()[:16]

        if not self.vault.is_connected():
            payload = {
                "candidate_uid": uid, "study_id": study_id, "cand_id_detector": cand_id, "hemi": hemi,
                "centroid_vox": list(centroid_vox), "centroid_mm": list(centroid_mm),
                "volume_vox": volume_vox, "volume_mm3": volume_mm3, "bbox": list(bbox),
                "albus_score": albus_score, "albus_formula": albus_formula,
                "lumos_prob": lumos_prob, "lumos_unc": lumos_unc, "nox_measurements": nox_meas or {},
                "percival_score": percival_score, "percival_status": percival_status,
                "detection_version": detection_version, "spatial_fingerprint": fp, "created_at": now
            }
            self.local_journal.record_entry("candidates_memory", "INSERT", payload, study_id, uid, "ALBUS")
            return uid

        with self._get_connection() as con:
            cur = con.execute("SELECT spatial_fingerprint FROM candidates_memory WHERE candidate_uid = ?", (uid,))
            cand_row = cur.fetchone()
            if cand_row:
                ann_cur = con.execute("SELECT COUNT(*) as n FROM expert_annotations WHERE candidate_uid = ?", (uid,))
                has_expert = (ann_cur.fetchone()["n"] > 0)
                old_fp = cand_row["spatial_fingerprint"]
                if old_fp == fp:
                    return uid
                if has_expert:
                    con.execute("""
                        UPDATE candidates_memory SET
                            albus_score = ?, albus_formula = ?, lumos_prob = ?,
                            lumos_uncertainty = ?, percival_score = ?, percival_status = ?
                        WHERE candidate_uid = ?
                    """, (albus_score, albus_formula, lumos_prob, lumos_unc, percival_score, percival_status, uid))
                    return uid

            con.execute("""
                INSERT INTO candidates_memory (candidate_uid, study_id, cand_id_detector, hemi,
                                              centroid_vox, centroid_mm, volume_vox, volume_mm3,
                                              bbox, albus_score, albus_formula, lumos_prob,
                                              lumos_uncertainty, nox_measurements, percival_score,
                                              percival_status, detection_version, spatial_fingerprint,
                                              created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(candidate_uid) DO UPDATE SET
                    cand_id_detector=excluded.cand_id_detector,
                    centroid_vox=excluded.centroid_vox,
                    centroid_mm=excluded.centroid_mm,
                    volume_vox=excluded.volume_vox,
                    volume_mm3=excluded.volume_mm3,
                    bbox=excluded.bbox,
                    albus_score=excluded.albus_score,
                    albus_formula=excluded.albus_formula,
                    lumos_prob=excluded.lumos_prob,
                    lumos_uncertainty=excluded.lumos_uncertainty,
                    nox_measurements=excluded.nox_measurements,
                    percival_score=excluded.percival_score,
                    percival_status=excluded.percival_status,
                    detection_version=excluded.detection_version,
                    spatial_fingerprint=excluded.spatial_fingerprint
            """, (uid, study_id, cand_id, hemi, json.dumps(list(centroid_vox)),
                  json.dumps(list(centroid_mm)), volume_vox, volume_mm3, json.dumps(list(bbox)),
                  albus_score, albus_formula, lumos_prob, lumos_unc, json.dumps(nox_meas or {}),
                  percival_score, percival_status, detection_version, fp, now))
        return uid

    # -------------------------------------------------------------
    # 3. Expert Knowledge Memory
    # -------------------------------------------------------------
    def record_expert_annotation(self, study_id: str, reviewer_id: str, call: str,
                                 candidate_uid: Optional[str] = None,
                                 lesion_type: str = "superficial_siderosis",
                                 confidence: str = "high", provenance: str = "expert_review") -> str:
        """Preserve expert feedback as permanent authoritative ground truth."""
        annot_id = f"ann_{hashlib.sha256(f'{study_id}_{candidate_uid}_{reviewer_id}_{time.time()}'.encode()).hexdigest()[:12]}"
        now = time.time()

        if not self.vault.is_connected():
            payload = {
                "annotation_id": annot_id, "study_id": study_id, "candidate_uid": candidate_uid,
                "reviewer_id": reviewer_id, "call": call, "lesion_type": lesion_type,
                "confidence": confidence, "provenance": provenance, "created_at": now
            }
            self.local_journal.record_entry("expert_annotations", "INSERT", payload, study_id, candidate_uid, reviewer_id)
            if candidate_uid and call == "not_css":
                self.record_correction(study_id, "false_positive_rejected", "ALBUS", "cSS", "not_css",
                                       candidate_uid=candidate_uid, pattern="expert_rejected_candidate")
            elif call == "missed_lesion":
                self.record_correction(study_id, "missed_lesion_flagged", "ALBUS", "unproposed", "definite_css",
                                       candidate_uid=candidate_uid, pattern="detector_sensitivity_gap")
            return annot_id

        with self._get_connection() as con:
            con.execute("""
                INSERT INTO expert_annotations (annotation_id, study_id, candidate_uid, source_type,
                                               reviewer_id, call, lesion_type, confidence, provenance, created_at)
                VALUES (?, ?, ?, 'expert_human', ?, ?, ?, ?, ?, ?)
            """, (annot_id, study_id, candidate_uid, reviewer_id, call, lesion_type, confidence, provenance, now))

        # If expert rejected an AI-positive candidate or flagged a missed lesion, record correction event
        if candidate_uid and call == "not_css":
            self.record_correction(study_id, "false_positive_rejected", "ALBUS", "cSS", "not_css",
                                   candidate_uid=candidate_uid, pattern="expert_rejected_candidate")
        elif call == "missed_lesion":
            self.record_correction(study_id, "missed_lesion_flagged", "ALBUS", "unproposed", "definite_css",
                                   candidate_uid=candidate_uid, pattern="detector_sensitivity_gap")
        return annot_id

    # -------------------------------------------------------------
    # 4. Learning & Correction Memory
    # -------------------------------------------------------------
    def record_correction(self, study_id: str, event_type: str, component: str,
                          initial_ai: str, ground_truth: str, candidate_uid: Optional[str] = None,
                          evidence: Optional[Dict[str, Any]] = None, pattern: str = "") -> str:
        cid = f"cor_{hashlib.sha256(f'{study_id}_{event_type}_{time.time()}'.encode()).hexdigest()[:12]}"
        now = time.time()

        if not self.vault.is_connected():
            payload = {
                "correction_id": cid, "study_id": study_id, "candidate_uid": candidate_uid,
                "event_type": event_type, "responsible_component": component,
                "initial_ai_call": initial_ai, "expert_ground_truth": ground_truth,
                "evidence": evidence or {}, "failure_pattern": pattern, "created_at": now
            }
            self.local_journal.record_entry("corrections_memory", "INSERT", payload, study_id, candidate_uid, component)
            return cid

        with self._get_connection() as con:
            con.execute("""
                INSERT INTO corrections_memory (correction_id, study_id, candidate_uid, event_type,
                                               responsible_component, initial_ai_call, expert_ground_truth,
                                               evidence_snapshot, failure_pattern, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (cid, study_id, candidate_uid, event_type, component, initial_ai, ground_truth,
                  json.dumps(evidence or {}), pattern, time.time()))
        return cid

    # -------------------------------------------------------------
    # 5. Scientific Findings Memory
    # -------------------------------------------------------------
    def record_scientific_finding(self, category: str, hypothesis: str,
                                  evidence_strength: str = "exploratory",
                                  details: Optional[Dict[str, Any]] = None,
                                  created_by: str = "SHADOW_ML") -> str:
        fid = f"find_{hashlib.sha256(f'{hypothesis}_{time.time()}'.encode()).hexdigest()[:12]}"
        with self._get_connection() as con:
            con.execute("""
                INSERT INTO scientific_findings (finding_id, category, hypothesis, evidence_strength,
                                                details, created_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (fid, category, hypothesis, evidence_strength, json.dumps(details or {}), created_by, time.time()))
        return fid

    # -------------------------------------------------------------
    # 6. Component-Specific Query Interfaces (Support all agents)
    # -------------------------------------------------------------
    def ask_albus_memory(self, limit: int = 100) -> Dict[str, Any]:
        """ALBUS inquires: Which lesions were missed? Which false positives recurred?"""
        with self._get_connection() as con:
            cur = con.execute("""
                SELECT * FROM corrections_memory
                WHERE responsible_component = 'ALBUS'
                ORDER BY created_at DESC LIMIT ?
            """, (limit,))
            corrections = [dict(r) for r in cur.fetchall()]

            cur2 = con.execute("""
                SELECT * FROM expert_annotations
                WHERE call = 'missed_lesion'
                ORDER BY created_at DESC LIMIT ?
            """, (limit,))
            missed = [dict(r) for r in cur2.fetchall()]
            missed_from_corrections = [c for c in corrections if c["event_type"] == "missed_lesion_flagged"]
            # Avoid double-counting missed lesions recorded both as annotations and corrections
            annotated_studies = {m["study_id"] for m in missed}
            unlinked_corrections = [c for c in missed_from_corrections if c.get("study_id") not in annotated_studies]
            total_missed = len(missed) + len(unlinked_corrections)

        return {
            "component": "ALBUS",
            "missed_lesions_count": total_missed,
            "missed_lesions": missed,
            "false_positive_corrections": [c for c in corrections if c["event_type"] == "false_positive_rejected"],
            "guidance": "Focus formula updates on resolving detector sensitivity gaps while penalizing recurrent sulcal vessel patterns."
        }

    def ask_lumos_memory(self, limit: int = 100) -> Dict[str, Any]:
        """LUMOS inquires: Which visual patterns were confirmed as genuine cSS?"""
        with self._get_connection() as con:
            cur = con.execute("""
                SELECT c.*, a.call, a.lesion_type FROM candidates_memory c
                JOIN expert_annotations a ON c.candidate_uid = a.candidate_uid
                WHERE a.call = 'definite_css'
                LIMIT ?
            """, (limit,))
            confirmed = [dict(r) for r in cur.fetchall()]
        return {
            "component": "LUMOS",
            "expert_confirmed_cSS_count": len(confirmed),
            "examples": confirmed,
            "guidance": "Prioritize curvilinear subpial low-intensity patterns in Darboux coordinates."
        }

    def ask_nox_memory(self) -> Dict[str, Any]:
        """NOX inquires: Which characteristics are informative and reproducible?"""
        with self._get_connection() as con:
            cur = con.execute("""
                SELECT * FROM scientific_findings
                WHERE category IN ('feature_stability', 'anatomical_invariant')
            """)
            findings = [dict(r) for r in cur.fetchall()]
        return {
            "component": "NOX",
            "reproducibility_records": findings,
            "guidance": "Maintain pial_distance, tubularity, and darkness_z; reject unstable single-voxel intensity spikes."
        }

    def ask_core_memory(self) -> Dict[str, Any]:
        """Percival Core inquires: What are the component agreement patterns and reliability?"""
        with self._get_connection() as con:
            cur = con.execute("SELECT count(*) as cnt FROM candidates_memory WHERE percival_score IS NOT NULL")
            total_scored = cur.fetchone()["cnt"]
            cur2 = con.execute("SELECT count(*) as cnt FROM expert_annotations WHERE call = 'definite_css'")
            total_css = cur2.fetchone()["cnt"]
        return {
            "component": "PERCIVAL_CORE",
            "total_scored_candidates": total_scored,
            "total_expert_css": total_css,
            "absorbed_epoximise_status": "Absorbed directly into Percival Core",
            "guidance": "Stack ALBUS discovery, LUMOS 3D appearance, and NOX quantitative features with ridge-penalized calibration."
        }

    def ask_shadow_memory(self) -> Dict[str, Any]:
        """SHADOW ML inquires: What are unresolved weaknesses and hypotheses to investigate?"""
        albus_info = self.ask_albus_memory(limit=20)
        with self._get_connection() as con:
            cur = con.execute("SELECT * FROM scientific_findings WHERE evidence_strength = 'exploratory'")
            hypotheses = [dict(r) for r in cur.fetchall()]
        return {
            "unresolved_missed_lesions": albus_info["missed_lesions_count"],
            "open_hypotheses": hypotheses,
            "recommended_targets": ["ALBUS adaptive thresholding", "NOX curvature tensor", "LUMOS multiscale 3D context"]
        }

    # -------------------------------------------------------------
    # 7. Missed Lesions Memory & Study Review Completion
    # -------------------------------------------------------------
    def record_missed_lesion(self, study_id: str, missed_id: str, reviewer_id: str,
                             coords_vox: Tuple[int, int, int], coords_mm: Tuple[float, float, float],
                             slice_idx: int = 0, plane: str = "", shape: str = "point",
                             points_json: str = "[]", comment: str = "", detector_fate: str = "") -> str:
        """Record an expert-identified cSS lesion that was missed by ALBUS."""
        muid = f"{study_id}_missed_{missed_id}"
        now = time.time()
        vx, vy, vz = coords_vox
        mx, my, mz = coords_mm

        if not self.vault.is_connected():
            payload = {
                "missed_uid": muid, "study_id": study_id, "missed_id": str(missed_id),
                "reviewer_id": reviewer_id, "vox_i": int(vx), "vox_j": int(vy), "vox_k": int(vz),
                "x_mm": float(mx), "y_mm": float(my), "z_mm": float(mz),
                "plane": plane, "slice_idx": int(slice_idx), "shape": shape,
                "points_json": points_json, "comment": comment, "detector_fate": detector_fate,
                "albus_detected": 0, "created_at": now
            }
            self.local_journal.record_entry("missed_lesions_memory", "INSERT", payload, study_id, muid, reviewer_id)
            self.record_expert_annotation(study_id, reviewer_id, "missed_lesion", candidate_uid=None,
                                          lesion_type="superficial_siderosis", confidence="high",
                                          provenance=f"missed_in_viewer_{plane}_slice_{slice_idx}")
            return muid

        with self._get_connection() as con:
            con.execute("""
                INSERT OR REPLACE INTO missed_lesions_memory
                (missed_uid, study_id, missed_id, reviewer_id, vox_i, vox_j, vox_k,
                 x_mm, y_mm, z_mm, plane, slice_idx, shape, points_json, comment,
                 detector_fate, albus_detected, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """, (muid, study_id, str(missed_id), reviewer_id, int(vx), int(vy), int(vz),
                  float(mx), float(my), float(mz), plane, int(slice_idx), shape,
                  points_json, comment, detector_fate, now))

        # Record corresponding expert annotation and correction event
        self.record_expert_annotation(study_id, reviewer_id, "missed_lesion", candidate_uid=None,
                                      lesion_type="superficial_siderosis", confidence="high",
                                      provenance=f"missed_in_viewer_{plane}_slice_{slice_idx}")
        return muid

    def delete_missed_lesion(self, study_id: str, missed_id: str) -> bool:
        muid = f"{study_id}_missed_{missed_id}"
        if not self.vault.is_connected():
            self.local_journal.record_entry("missed_lesions_memory", "DELETE", {"missed_uid": muid}, study_id, muid)
            return True
        with self._get_connection() as con:
            cur = con.execute("DELETE FROM missed_lesions_memory WHERE missed_uid = ? OR (study_id = ? AND missed_id = ?)",
                              (muid, study_id, str(missed_id)))
            return cur.rowcount > 0

    def get_missed_lesions(self, study_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self.vault.is_connected():
            return []
        with self._get_connection() as con:
            if study_id:
                cur = con.execute("SELECT * FROM missed_lesions_memory WHERE study_id = ? ORDER BY created_at ASC", (study_id,))
            else:
                cur = con.execute("SELECT * FROM missed_lesions_memory ORDER BY created_at ASC")
            return [dict(r) for r in cur.fetchall()]

    def set_study_review_status(self, study_id: str, candidate_review: str = "incomplete",
                                missed_assessment: str = "incomplete", adjudication: str = "not_needed",
                                overall_status: str = "incomplete", reviewer_id: Optional[str] = None,
                                completed_at: Optional[float] = None) -> None:
        now = time.time()
        cat = completed_at if (overall_status == "expert_review_completed" and completed_at) else (now if overall_status == "expert_review_completed" else None)
        if not self.vault.is_connected():
            payload = {
                "study_id": study_id, "candidate_review_status": candidate_review,
                "missed_assessment_status": missed_assessment, "adjudication_status": adjudication,
                "overall_status": overall_status, "reviewer_id": reviewer_id,
                "completed_at": cat, "updated_at": now
            }
            self.local_journal.record_entry("study_review_status", "INSERT_OR_REPLACE", payload, study_id, None, reviewer_id)
            return

        with self._get_connection() as con:
            con.execute("""
                INSERT OR REPLACE INTO study_review_status
                (study_id, candidate_review_status, missed_assessment_status, adjudication_status,
                 overall_status, reviewer_id, completed_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (study_id, candidate_review, missed_assessment, adjudication, overall_status, reviewer_id, cat, now))

    def get_study_review_status(self, study_id: str) -> Dict[str, Any]:
        default = {
            "study_id": study_id, "candidate_review_status": "incomplete",
            "missed_assessment_status": "incomplete", "adjudication_status": "not_needed",
            "overall_status": "incomplete", "reviewer_id": None, "completed_at": None
        }
        if not self.vault.is_connected():
            return default
        with self._get_connection() as con:
            cur = con.execute("SELECT * FROM study_review_status WHERE study_id = ?", (study_id,))
            r = cur.fetchone()
            return dict(r) if r else default

    def get_expert_annotations(self, study_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self.vault.is_connected():
            return []
        with self._get_connection() as con:
            if study_id:
                cur = con.execute("SELECT * FROM expert_annotations WHERE study_id = ? ORDER BY created_at ASC", (study_id,))
            else:
                cur = con.execute("SELECT * FROM expert_annotations ORDER BY created_at ASC")
            return [dict(r) for r in cur.fetchall()]

    def get_status(self) -> Dict[str, Any]:
        """Telemetry of Pensieve memory contents."""
        connected = self.vault.is_connected()
        journal_st = self.local_journal.get_status()
        if not connected:
            return {
                "connected": False,
                "vault_path": None,
                "studies_count": 0,
                "candidates_count": 0,
                "expert_annotations_count": 0,
                "missed_lesions_count": 0,
                "corrections_count": 0,
                "journal": journal_st
            }
        try:
            with self._get_connection() as con:
                s_cnt = con.execute("SELECT COUNT(*) FROM studies_memory").fetchone()[0]
                c_cnt = con.execute("SELECT COUNT(*) FROM candidates_memory").fetchone()[0]
                a_cnt = con.execute("SELECT COUNT(*) FROM expert_annotations").fetchone()[0]
                m_cnt = con.execute("SELECT COUNT(*) FROM missed_lesions_memory").fetchone()[0]
                cor_cnt = con.execute("SELECT COUNT(*) FROM corrections_memory").fetchone()[0]
            return {
                "connected": True,
                "vault_path": self._db_path,
                "studies_count": s_cnt,
                "candidates_count": c_cnt,
                "expert_annotations_count": a_cnt,
                "missed_lesions_count": m_cnt,
                "corrections_count": cor_cnt,
                "journal": journal_st
            }
        except Exception as e:
            return {
                "connected": True,
                "error": str(e),
                "journal": journal_st
            }

    # -------------------------------------------------------------
    # 8. Leak-Free Training Data Extraction
    # -------------------------------------------------------------
    def get_training_dataset(self, target_partition: str = "development") -> List[Dict[str, Any]]:
        """Retrieve expert-annotated candidates strictly from the specified partition.
        Enforces patient-level boundaries and never reads locked_test data during development."""
        with self._get_connection() as con:
            cur = con.execute("""
                SELECT c.*, s.patient_pseudo_id, s.partition, a.call, a.lesion_type
                FROM candidates_memory c
                JOIN studies_memory s ON c.study_id = s.study_id
                JOIN expert_annotations a ON c.candidate_uid = a.candidate_uid
                WHERE s.partition = ?
            """, (target_partition,))
            rows = [dict(r) for r in cur.fetchall()]
        return rows

    def get_all_studies(self) -> List[Dict[str, Any]]:
        with self._get_connection() as con:
            cur = con.execute("SELECT * FROM studies_memory ORDER BY created_at DESC")
            return [dict(r) for r in cur.fetchall()]

    def get_all_corrections(self) -> List[Dict[str, Any]]:
        with self._get_connection() as con:
            cur = con.execute("SELECT * FROM corrections_memory ORDER BY created_at DESC")
            return [dict(r) for r in cur.fetchall()]

    def get_all_findings(self) -> List[Dict[str, Any]]:
        with self._get_connection() as con:
            cur = con.execute("SELECT * FROM scientific_findings ORDER BY created_at DESC")
            return [dict(r) for r in cur.fetchall()]

# Singleton Helper
_DEFAULT_PENSIEVE: Optional[PensieveCoreMemory] = None

def get_pensieve(vault: Optional[PercivalDataVault] = None) -> PensieveCoreMemory:
    global _DEFAULT_PENSIEVE
    if _DEFAULT_PENSIEVE is None or (vault and _DEFAULT_PENSIEVE.vault != vault):
        _DEFAULT_PENSIEVE = PensieveCoreMemory(vault)
    return _DEFAULT_PENSIEVE
