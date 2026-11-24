"""uengine/lumos.py - LUMOS: 3D MRI Image Appearance Intelligence Engine

The visual analytical component in the Percival pipeline:
  MRI -> ALBUS -> LUMOS + NOX -> PERCIVAL CORE -> PERCIVAL SCORE

Responsibilities:
  1. Analyzes actual 3D MRI appearance in surface-aligned physical Darboux space (u, v, n).
  2. Pure NumPy lightweight CNN (1,425 parameters) optimized for sample-efficient neuroimaging.
  3. Test-time augmentation (TTA) along symmetric anatomical axes to produce uncertainty estimates.
  4. Integration with PENSIEVE memory (visual patterns of confirmed lesions vs vessel mimics).
  5. Outputs standardized LumosInference contract objects.
  6. Checkpoint persistence in the authoritative Percival Data Vault (models/LUMOS/).
"""

import os
import json
import shutil
import hashlib
import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from uengine.contracts import LumosInference
from uengine.percival.cnn import SmallCNN, patch_maps, IN_SHAPE
from uengine.pensieve import get_pensieve, PensieveCoreMemory
from uengine.vault import get_vault, PercivalDataVault

class LumosImageIntelligence:
    def __init__(self, weights: Optional[Dict[str, np.ndarray]] = None,
                 pensieve: Optional[PensieveCoreMemory] = None,
                 vault: Optional[PercivalDataVault] = None):
        self.pensieve = pensieve or get_pensieve()
        self.vault = vault or get_vault()
        self.version = "lumos-5.25.0"
        self.net = SmallCNN()
        self.checkpoint_status = "uncalibrated_baseline"
        self.checkpoint_hash = ""
        self.checkpoint_source = ""
        self.checkpoint_error = ""

        if weights is not None:
            self.net.p = weights
            self.checkpoint_status = "explicit_weights"
        else:
            self._load_active_checkpoint()

    @classmethod
    def from_percival_model(cls, model: Optional[Dict[str, Any]], pensieve=None, vault=None) -> "LumosImageIntelligence":
        """Architecture integration: LUMOS = the Percival Decision Engine's trained image network (the SAME weights; no second CNN).
        model: a registry model.json (dict). Without a trained image component LUMOS reports 'untrained' and returns no prediction."""
        self = cls.__new__(cls)
        self.pensieve, self.vault = pensieve, vault
        self.version = "lumos-5.25.0"; self.checkpoint_hash = ""; self.checkpoint_error = ""; self.checkpoint_source = ""
        self.net = SmallCNN(); self.checkpoint_status = "uncalibrated_baseline"
        im = ((model or {}).get("components") or {}).get("image")
        if im is not None and im.get("type", "cnn") == "cnn" and im.get("params"):
            self.net = SmallCNN.from_json(im)
            self.checkpoint_status = "registry_trained"
            self.checkpoint_source = f"percival registry {model.get('version')}"
            self.checkpoint_hash = hashlib.sha256(json.dumps(im.get("params"), sort_keys=True).encode()).hexdigest()[:16]
            self.version = f"lumos@{model.get('version')}"
        elif im is not None:
            self.checkpoint_status = "not_cnn"; self.checkpoint_error = f"image component is {im.get('type')} (no CNN weights)"
        return self

    @property
    def trained(self) -> bool:
        return self.checkpoint_status in ("registry_trained", "loaded", "recovered_from_backup", "explicit_weights")

    def _load_active_checkpoint(self) -> None:
        """Attempt to load latest model weights from Data Vault with integrity verification & recovery."""
        if not self.vault.is_connected():
            return

        weights_file = self.vault.path("models", "LUMOS", "lumos_active_weights.npz")
        backup_file = self.vault.path("models", "LUMOS", "lumos_backup_weights.npz")

        def _try_load(path: str) -> Optional[Dict[str, np.ndarray]]:
            if not os.path.exists(path):
                return None
            try:
                loaded = np.load(path)
                required = {"W1", "b1", "W2", "b2", "W3", "b3"}
                if not required.issubset(set(loaded.files)):
                    return None
                return {k: loaded[k] for k in loaded.files}
            except Exception:
                return None

        if os.path.exists(weights_file):
            p = _try_load(weights_file)
            if p is not None:
                self.net.p = p
                self.checkpoint_status = "loaded"
                self.checkpoint_source = weights_file
                with open(weights_file, "rb") as f:
                    self.checkpoint_hash = hashlib.sha256(f.read()).hexdigest()
                return

            # Active checkpoint exists but is corrupted -> attempt recovery from backup
            p_bk = _try_load(backup_file)
            if p_bk is not None:
                self.net.p = p_bk
                self.checkpoint_status = "recovered_from_backup"
                self.checkpoint_source = backup_file
                with open(backup_file, "rb") as f:
                    self.checkpoint_hash = hashlib.sha256(f.read()).hexdigest()
                return

            # Both failed: mark corrupted and refuse silent un-trained inference
            self.checkpoint_status = "checkpoint_corrupted"
            self.checkpoint_error = f"Active checkpoint corrupted at {weights_file} and backup recovery failed."

    def save_checkpoint(self, tag: str = "active") -> str:
        """Save current weights to the authoritative Percival Data Vault with backup redundancy."""
        if not self.vault.is_connected():
            raise RuntimeError("Cannot save LUMOS checkpoint: Data Vault is disconnected.")
        dest = self.vault.path("models", "LUMOS", f"lumos_{tag}_weights.npz")
        np.savez_compressed(dest, **self.net.p)
        if tag == "active":
            backup = self.vault.path("models", "LUMOS", "lumos_backup_weights.npz")
            shutil.copyfile(dest, backup)
        with open(dest, "rb") as f:
            self.checkpoint_hash = hashlib.sha256(f.read()).hexdigest()
        self.checkpoint_status = "loaded"
        self.checkpoint_source = dest
        return dest

    def analyze_patch(self, study_id: str, cand_id: int,
                      patch_arrays: Optional[Dict[str, np.ndarray]] = None) -> LumosInference:
        """Evaluate actual 3D MRI appearance of a candidate region.
        
        Uses test-time augmentation across the symmetric axis to quantify prediction
        uncertainty alongside calibrated probability.
        """
        if self.checkpoint_status == "checkpoint_corrupted":
            return LumosInference(
                cand_id=cand_id,
                study_id=study_id,
                prob=None,
                logit=None,
                uncertainty=1.0,
                patch_shape=(0, 0, 0),
                model_version=self.version,
                has_visual_evidence=False,
                depth_gradient=None,
                depth_gradient_status="unavailable",
                status="checkpoint_unavailable",
                error=self.checkpoint_error or "Checkpoint corrupted; refusing inference."
            )

        if patch_arrays is None or not patch_arrays.get("valid_swi", np.zeros(1)).any():
            return LumosInference(
                cand_id=cand_id,
                study_id=study_id,
                prob=None,
                logit=None,
                uncertainty=1.0,
                patch_shape=(0, 0, 0),
                model_version=self.version,
                has_visual_evidence=False,
                depth_gradient=None,
                depth_gradient_status="unavailable",
                status="unavailable",
                error="No valid 3D SWI patch data for candidate"
            )

        M = patch_maps(patch_arrays)
        if M is None:
            return LumosInference(
                cand_id=cand_id,
                study_id=study_id,
                prob=None,
                logit=None,
                uncertainty=1.0,
                patch_shape=(0, 0, 0),
                model_version=self.version,
                has_visual_evidence=False,
                depth_gradient=None,
                depth_gradient_status="unavailable",
                status="degraded",
                error="Invalid voxels in cortical normal projection"
            )

        # Compute transverse subpial depth gradient along normal axis n (dim 2 of 3D patch)
        # Coordinate convention in Darboux frame: n=0 is deep fundus; n=N-1 is superficial subpial surface.
        # Siderosis: superficial cortex is dark, deep parenchyma brighter -> (deep - superficial) > 0.
        # Sulcal vessel: deep sulcus is dark, superficial brighter -> (deep - superficial) < 0.
        swi = patch_arrays["image_swi"]
        depth_grad = 0.0
        depth_grad_status = "unavailable"
        if swi.ndim == 3:
            if swi.shape[2] >= 4:
                mid = swi.shape[2] // 2
                deep_signal = float(np.nanmedian(swi[:, :, :mid]))
                superficial_signal = float(np.nanmedian(swi[:, :, mid:]))
                ref = float(np.nanmedian(swi))
                if ref > 1e-4 and np.isfinite(ref):
                    depth_grad = float(np.clip((deep_signal - superficial_signal) / ref, -2.0, 2.0))
                    depth_grad_status = "reliable"
                else:
                    depth_grad_status = "unreliable_reference"
            else:
                depth_grad_status = "insufficient_depth"

        if not self.trained:                       # architecture integration: random initial weights are not evidence
            return LumosInference(cand_id=cand_id, study_id=study_id, prob=None, logit=None, uncertainty=1.0, patch_shape=swi.shape,
                                  model_version=self.version, has_visual_evidence=False, depth_gradient=depth_grad,
                                  depth_gradient_status=depth_grad_status, status="untrained",
                                  error="no trained LUMOS weights (train PERCIVAL, or connect a verified checkpoint)")
        # Test-Time Augmentation (TTA) along symmetric u axis via logit_tta
        logits, unc_logits = self.net.logit_tta(M[np.newaxis])
        mean_logit = float(logits[0])
        unc_logit = float(unc_logits[0])

        prob = 1.0 / (1.0 + np.exp(-np.clip(mean_logit, -15.0, 15.0)))
        # Map uncertainty into probability scale: |sigmoid(mean + unc) - sigmoid(mean - unc)|
        prob_hi = 1.0 / (1.0 + np.exp(-np.clip(mean_logit + unc_logit, -15.0, 15.0)))
        prob_lo = 1.0 / (1.0 + np.exp(-np.clip(mean_logit - unc_logit, -15.0, 15.0)))
        tta_uncertainty = float(abs(prob_hi - prob_lo))

        return LumosInference(
            cand_id=cand_id,
            study_id=study_id,
            prob=float(prob),
            logit=float(mean_logit),
            uncertainty=tta_uncertainty,
            patch_shape=swi.shape,
            model_version=self.version,
            has_visual_evidence=True,
            depth_gradient=depth_grad,
            depth_gradient_status=depth_grad_status,
            status="ok"
        )

    def learn_from_pensieve(self) -> Dict[str, Any]:
        """Consult PENSIEVE for visual patterns of expert-confirmed lesions."""
        lumos_mem = self.pensieve.ask_lumos_memory(limit=25)
        return {
            "component": "LUMOS",
            "model_architecture": "Pure NumPy SmallCNN (1,425 parameters)",
            "input_representation": "Darboux frame (u, v, n) 3-map projection (MinIP, Mean, Footprint)",
            "expert_confirmed_samples": lumos_mem.get("expert_confirmed_cSS_count", 0),
            "guidance": lumos_mem.get("guidance", "")
        }
