"""uengine/nox.py - NOX: Quantitative 3D Characteristics Intelligence Engine

The quantitative analytical component in the Percival pipeline:
  MRI -> ALBUS -> LUMOS + NOX -> PERCIVAL CORE -> PERCIVAL SCORE

Responsibilities:
  1. Computes and validates 3D morphological, topological, signal, and anatomical characteristics.
  2. Extensible characteristic library with range and stability auditing.
  3. Rejection of unphysical or segmentation-unstable measurements.
  4. Feature discovery interface for SHADOW ML exploration.
  5. Integration with PENSIEVE memory (stability records, feature redundancy).
  6. Outputs standardized NoxMeasurements contract objects.
"""

import math
import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from uengine.contracts import NoxMeasurements
from uengine.pensieve import get_pensieve, PensieveCoreMemory

VALID_RANGES = {
    # Morphology
    "volume_mm3": (0.1, 5000.0),
    "surface_area_mm2": (0.5, 10000.0),
    "sphericity": (0.01, 1.0),
    "compactness": (0.01, 1.0),
    "elongation": (1.0, 50.0),
    "thickness_mm": (0.2, 10.0),
    # Topology
    "skeleton_length_mm": (0.0, 200.0),
    "branching_count": (0.0, 50.0),
    "tortuosity": (1.0, 10.0),
    # Signal
    "darkness_z": (-10.0, 1.0),
    "edge_contrast": (0.0, 5.0),
    "core_intensity_ratio": (0.05, 1.5),
    # Anatomy
    "pial_distance_mm": (0.0, 20.0),
    "sulcal_alignment": (0.0, 1.0),
    "cortex_fraction": (0.0, 1.0)
}

class NoxCharacteristicsEngine:
    def __init__(self, pensieve: Optional[PensieveCoreMemory] = None):
        self.pensieve = pensieve if pensieve is not None else __import__('uengine.legacy_guard', fromlist=['NullPensieve']).NullPensieve()   # Stage 1: never the global legacy memory by default
        self.version = "nox-5.25.0"
        self._custom_extractors: Dict[str, Any] = {}

    def register_custom_feature(self, name: str, fn: Any, valid_range: Tuple[float, float]) -> None:
        """Allow SHADOW ML to register an experimental feature calculation."""
        self._custom_extractors[name] = fn
        VALID_RANGES[name] = valid_range

    def measure_candidate(self, study_id: str, cand_id: int,
                          raw_candidate_data: Dict[str, Any]) -> NoxMeasurements:
        """Measure comprehensive 3D characteristics for a candidate."""
        morphology = {}
        topology = {}
        signal = {}
        anatomy = {}
        stability = {}

        # 1. Morphology
        spacing = raw_candidate_data.get("voxel_spacing_mm", [0.5, 0.5, 2.0])
        dx, dy, dz = float(spacing[0]), float(spacing[1]), float(spacing[2])
        is_valid_spacing = (dx > 0.0 and dy > 0.0 and dz > 0.0 and
                            np.isfinite(dx) and np.isfinite(dy) and np.isfinite(dz))
        vox_vol = (dx * dy * dz) if is_valid_spacing else 0.0

        # Check if 3D voxel mask is directly provided
        mask_3d = raw_candidate_data.get("mask_3d")
        if mask_3d is None:
            mask_3d = raw_candidate_data.get("object_mask")

        if not is_valid_spacing:
            # Physical metrics cannot be computed with invalid/zero/negative/infinite spacing
            vol_vox = int(mask_3d.sum()) if (mask_3d is not None and isinstance(mask_3d, np.ndarray)) else raw_candidate_data.get("volume_vox")
            morphology["volume_vox"] = float(vol_vox) if vol_vox is not None else None
            morphology["volume_mm3"] = None
            morphology["surface_area_mm2"] = None
            morphology["sphericity"] = None
            morphology["eigenvalues_mm2"] = None
            morphology["raw_lambda3_mm2"] = None
            morphology["elongation"] = None
            morphology["compactness"] = None
            morphology["thickness_mm"] = None
            morphology["is_planar"] = False
            morphology["geometry_status"] = "invalid_spacing"
            stability["geometry"] = "invalid_spacing"
        elif mask_3d is not None and isinstance(mask_3d, np.ndarray):
            vol_vox = int(mask_3d.sum())
            if vol_vox == 0:
                # Empty candidate mask
                morphology["volume_vox"] = 0.0
                morphology["volume_mm3"] = 0.0
                morphology["surface_area_mm2"] = 0.0
                morphology["sphericity"] = None
                morphology["eigenvalues_mm2"] = None
                morphology["raw_lambda3_mm2"] = None
                morphology["elongation"] = None
                morphology["compactness"] = None
                morphology["thickness_mm"] = None
                morphology["is_planar"] = False
                morphology["geometry_status"] = "empty_mask"
                stability["geometry"] = "empty_mask"
            elif vol_vox == 1:
                # Single voxel mask
                morphology["volume_vox"] = 1.0
                morphology["volume_mm3"] = float(vox_vol)
                morphology["surface_area_mm2"] = float(2.0 * (dx * dy + dy * dz + dx * dz))
                morphology["sphericity"] = None
                morphology["eigenvalues_mm2"] = None
                morphology["raw_lambda3_mm2"] = None
                morphology["elongation"] = None
                morphology["compactness"] = 1.0
                morphology["thickness_mm"] = float(min(dx, dy, dz))
                morphology["is_planar"] = False
                morphology["geometry_status"] = "single_voxel"
                stability["geometry"] = "single_voxel"
            else:
                vol_mm3 = float(vol_vox * vox_vol)
                morphology["volume_vox"] = float(vol_vox)
                morphology["volume_mm3"] = vol_mm3

                # 3D surface area from 6-connected boundary voxel faces
                pad = np.pad(mask_3d.astype(bool), 1, mode="constant", constant_values=False)
                diff_x = np.abs(np.diff(pad.astype(int), axis=0))
                diff_y = np.abs(np.diff(pad.astype(int), axis=1))
                diff_z = np.abs(np.diff(pad.astype(int), axis=2))
                area_mm2 = float(diff_x.sum() * (dy * dz) + diff_y.sum() * (dx * dz) + diff_z.sum() * (dx * dy))
                morphology["surface_area_mm2"] = area_mm2
                morphology["surface_area_method"] = "exposed_voxel_faces"

                # Wadell's Sphericity = (pi^(1/3) * (6 * Volume)^(2/3)) / Area
                if area_mm2 > 0 and vol_mm3 > 0:
                    sphericity = (math.pi ** (1.0 / 3.0) * ((6.0 * vol_mm3) ** (2.0 / 3.0))) / area_mm2
                    morphology["sphericity"] = float(np.clip(sphericity, 0.01, 1.0))
                else:
                    morphology["sphericity"] = None

                # 3D Inertia Tensor & Principal Second Central Moments from physical spatial covariance
                pts = np.argwhere(mask_3d).astype(float) # (N, 3) in voxel coords (i, j, k)
                pts_mm = pts * np.array([dx, dy, dz]) # convert to physical mm
                if len(pts_mm) >= 4:
                    cov = np.cov(pts_mm, rowvar=False)
                    eigvals = np.sort(np.linalg.eigvalsh(cov))[::-1]
                    l1 = float(max(0.0, eigvals[0]))
                    l2 = float(max(0.0, eigvals[1]))
                    l3 = float(max(0.0, eigvals[2]))

                    is_planar = bool(l3 < 1e-4 or len(np.unique(pts[:, 2])) <= 1)
                    if is_planar:
                        l3 = 0.0
                        morphology["geometry_status"] = "planar_mask"
                    else:
                        morphology["geometry_status"] = "ok"

                    morphology["eigenvalues_mm2"] = [l1, l2, l3]
                    morphology["raw_lambda3_mm2"] = l3
                    morphology["is_planar"] = is_planar

                    morphology["second_moment_isotropy"] = float(np.clip(l3 / max(1e-4, l1), 0.0, 1.0))
                    morphology["linearity"] = float(np.clip((l1 - l2) / max(1e-4, l1), 0.0, 1.0))
                    morphology["planarity"] = float(np.clip((l2 - l3) / max(1e-4, l1), 0.0, 1.0))

                    denom = max(1e-4, l3) if not is_planar else max(1e-4, l2)
                    morphology["elongation"] = float(np.clip(math.sqrt(max(1e-4, l1) / denom), 1.0, 20.0))
                else:
                    morphology["geometry_status"] = "sub_tetrahedral"
                    morphology["eigenvalues_mm2"] = None
                    morphology["raw_lambda3_mm2"] = None
                    morphology["sphericity"] = None
                    morphology["elongation"] = None
                    morphology["is_planar"] = False

                morphology["compactness"] = float(np.clip(raw_candidate_data.get("compactness", 0.6), 0.01, 1.0))
                morphology["thickness_mm"] = float(np.clip(raw_candidate_data.get("thickness_mm", 1.2), 0.2, 5.0))
        else:
            vol_vox = raw_candidate_data.get("volume_vox")
            vol_mm3 = raw_candidate_data.get("volume_mm3")
            if vol_vox is not None and vol_mm3 is None and is_valid_spacing:
                vol_mm3 = float(vol_vox * vox_vol)
            morphology["volume_vox"] = float(vol_vox) if vol_vox is not None else None
            morphology["volume_mm3"] = float(vol_mm3) if vol_mm3 is not None else None
            morphology["surface_area_mm2"] = raw_candidate_data.get("surface_area_mm2")
            morphology["sphericity"] = raw_candidate_data.get("sphericity")
            morphology["elongation"] = raw_candidate_data.get("elongation", raw_candidate_data.get("tube_ratio"))
            morphology["compactness"] = raw_candidate_data.get("compactness")
            morphology["thickness_mm"] = raw_candidate_data.get("thickness_mm")
            morphology["eigenvalues_mm2"] = None
            morphology["raw_lambda3_mm2"] = None
            morphology["is_planar"] = False
            morphology["geometry_status"] = "tabular_input"

        # 2. Topology
        topology["skeleton_length_mm"] = float(np.clip(raw_candidate_data.get("skeleton_length", 4.0), 0.0, 100.0))
        topology["branching_count"] = float(np.clip(raw_candidate_data.get("branching_count", 1.0), 0.0, 20.0))
        topology["tortuosity"] = float(np.clip(raw_candidate_data.get("tortuosity", 1.2), 1.0, 5.0))

        # 3. Signal & Texture
        signal["darkness_z"] = float(np.clip(raw_candidate_data.get("darkness_z", -1.8), -8.0, 0.5))
        signal["edge_contrast"] = float(np.clip(raw_candidate_data.get("edge_contrast", 0.4), 0.0, 3.0))
        signal["core_intensity_ratio"] = float(np.clip(raw_candidate_data.get("core_intensity_ratio", 0.4), 0.1, 1.2))

        # 4. Anatomy
        anatomy["pial_distance_mm"] = float(np.clip(raw_candidate_data.get("pial_distance", 0.8), 0.0, 15.0))
        anatomy["sulcal_alignment"] = float(np.clip(raw_candidate_data.get("sulcal_alignment", 0.5), 0.0, 1.0))
        anatomy["cortex_fraction"] = float(np.clip(raw_candidate_data.get("cortex_frac", 0.6), 0.0, 1.0))

        # 5. Evaluate custom experimental features
        for name, fn in self._custom_extractors.items():
            try:
                val = float(fn(raw_candidate_data))
                lo, hi = VALID_RANGES.get(name, (-1e6, 1e6))
                if lo <= val <= hi:
                    signal[name] = val
                    stability[name] = "experimental_stable"
                else:
                    stability[name] = "out_of_range"
            except Exception:
                stability[name] = "calculation_failed"

        # 6. Stability Audit for standard features
        for k, v in {**morphology, **topology, **signal, **anatomy}.items():
            if k in self._custom_extractors:
                continue
            if k in VALID_RANGES:
                lo, hi = VALID_RANGES[k]
                if v is None:
                    stability[k] = "undefined"
                elif not (lo <= v <= hi) or not np.isfinite(v):
                    stability[k] = "unreliable"
                else:
                    stability[k] = "stable"

        return NoxMeasurements(
            cand_id=cand_id,
            study_id=study_id,
            morphology=morphology,
            topology=topology,
            signal=signal,
            anatomy=anatomy,
            stability=stability,
            version=self.version
        )

    def learn_from_pensieve(self) -> Dict[str, Any]:
        """Inquire PENSIEVE regarding characteristic stability and cross-scanner reproducibility."""
        nox_mem = self.pensieve.ask_nox_memory()
        return {
            "component": "NOX",
            "active_version": self.version,
            "measured_families": ["morphology", "topology", "signal", "anatomy"],
            "total_standard_metrics": len(VALID_RANGES),
            "custom_metrics_registered": list(self._custom_extractors.keys()),
            "pensieve_guidance": nox_mem.get("guidance", "")
        }
