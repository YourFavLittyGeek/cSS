# PERCIVAL v5.25-dev — SCIENTIFIC AUDIT OF IMAGE ML ARCHITECTURE

**Document ID:** `AUDIT-IMG-v525`  
**Date:** 2026-11-22  
**Auditor:** Principal Neuroimaging Scientist & Deep Learning Architect  
**Scope:** `unified_engine/uengine/percival/cnn.py`, `imaging/patches.py`, `imaging/surface_aligned_patch.py`, `learners.py`  
**Classification:** Independent Forensic Audit Report  

---

## 1. Executive Summary & Scientific Findings

The Percival Image ML subsystem is designed to classify candidate cerebral superficial siderosis (cSS) lesions directly from MRI pixel arrays rather than extracted scalar feature tables.

### Key Audit Conclusions:
1. **Physical Surface-Aligned Coordinate System:** The extraction pipeline uses an anatomically defined local Darboux-like frame $(u, v, n)$ anchored to the pial/cortical surface. Patches are sampled in physical millimeter space ($24 \times 12 \times 8\text{ mm}$ at $0.5\text{ mm}$ isotropic spacing), guaranteeing voxel-spacing invariance across varying clinical acquisition protocols.
2. **2.5D Projection Maps vs. Full 3D Convolutions:** The 3D patch ($49 \times 25 \times 17$) is compressed along the cortical normal axis $n$ into three 2D maps of size $3 \times 49 \times 25$:
   - Channel 0: Minimum-Intensity Projection (MinIP) along $n$ (capturing dark hemosiderin blooming).
   - Channel 1: Mean intensity along $n$.
   - Channel 2: Binary object footprint fraction along $n$.
   *Scientific Implication:* While computationally lightweight and robust, this projection collapses through-plane laminar depth information, preventing the network from distinguishing whether hypointensities lie strictly in the subpial space versus entering adjacent sulcal CSF.
3. **Pure NumPy Architecture & Determinism:** The CNN is implemented in raw NumPy using explicit `im2col` / `col2im` matrix operations. It requires zero external deep learning frameworks (PyTorch, TensorFlow, JAX), preserving strict compatibility with the locked Apple Silicon / CPU runtime environment.
4. **Test-Time Augmentation (TTA) Uncertainty:** TTA evaluates both the standard patch and its $u$-flipped reflection. The half-gap $\frac{1}{2} |\text{logit}(X) - \text{logit}(X_{\text{flip}})|$ serves as an explicit image-level epistemic uncertainty metric.

---

## 2. Coordinate Geometry & Sampling Protocol

### 2.1 The Surface-Aligned Frame $(u, v, n)$
In standard scanner space $(x, y, z)$, cortical gyri have arbitrary orientations. A fixed Euclidean bounding box fails because a lesion curved along a sulcus cannot be aligned across subjects.
Percival solves this by constructing a local curvilinear orthonormal frame at the candidate centroid $\mathbf{c}_0$:
- **$\mathbf{n}$ (Cortical Normal):** Unit vector orthogonal to the local cortical surface mesh / signed distance gradient $\nabla \Phi_{\text{pial}}(\mathbf{c}_0)$, pointing outward toward CSF.
- **$\mathbf{u}$ (Longitudinal Candidate Tangent):** The primary eigenvector of the candidate inertia tensor projected onto the cortical tangent plane ($\mathbf{u} \perp \mathbf{n}$). This aligns with the direction of elongation along the sulcus.
- **$\mathbf{v}$ (Transverse Tangent):** $\mathbf{v} = \mathbf{n} \times \mathbf{u}$, completing the right-handed orthonormal triad.

### 2.2 Physical Discretization
The sampling volume covers:
- $u \in [-12, +12]\text{ mm}$ ($24\text{ mm}$ total span, 49 points at $\Delta u = 0.5\text{ mm}$)
- $v \in [-6, +6]\text{ mm}$ ($12\text{ mm}$ total span, 25 points at $\Delta v = 0.5\text{ mm}$)
- $n \in [-4, +4]\text{ mm}$ ($8\text{ mm}$ total span, 17 points at $\Delta n = 0.5\text{ mm}$)

Trilinear interpolation resamples the raw SWI volume into the grid $(49, 25, 17)$.
Normalization is anchored to the candidate patch median intensity:
$$z(u, v, n) = \frac{\text{SWI}(u, v, n)}{\text{median}(\text{SWI}_{\text{valid}})}$$
This step eliminates scanner gain drift and multi-coil B1 receive field inhomogeneity without requiring global bias-field correction.

---

## 3. Map Reduction & CNN Architecture

### 3.1 3-Map Formulation
```
Input: 3D Array (49, 25, 17) -> Reduction along normal axis n -> Output Tensor (3, 49, 25)
Channel 0: MinIP  = clip( min_n(z), 0, 2 ) - 1
Channel 1: Mean   = clip( mean_n(z), 0, 2 ) - 1
Channel 2: Mask   = mean_n( object_mask )
```
Zero or invalid voxels (outside skull or FOV) are handled by `np.nanmin` and filled with neutral background values ($1.0 \to 0$ post-subtraction).

### 3.2 Network Topology (`SmallCNN`)
The network is parameterized by:
1. **Layer 1:** Conv2D ($3 \times 3$, 8 filters, stride 1, padding 1) $\to$ ReLU $\to$ MaxPool ($2 \times 2$, stride 2).
   - Input: $(N, 3, 49, 25)$
   - Conv1 output: $(N, 8, 49, 25)$
   - MaxPool1 output: $(N, 8, 24, 12)$
2. **Layer 2:** Conv2D ($3 \times 3$, 16 filters, stride 1, padding 1) $\to$ ReLU.
   - Conv2 output: $(N, 16, 24, 12)$
3. **Pooling Layer:** Dual Global Pooling (Global Average Pooling + Global Max Pooling concatenated):
   $$\mathbf{f} = [\text{GAP}(\mathbf{A}_2), \text{GMP}(\mathbf{A}_2)] \in \mathbb{R}^{32}$$
   *Design Rationale:* GAP captures diffuse, extensive hemosiderin staining, while GMP detects sharp, focal hypointense cores.
4. **Classification Head:** Linear dense layer $\mathbf{W}_3 \in \mathbb{R}^{32 \times 1}, b_3 \in \mathbb{R}^1 \to \text{logit}$.

Total trainable parameters:
- $W_1$: $3 \times 3 \times 3 \times 8 = 216$ weights, 8 biases.
- $W_2$: $3 \times 3 \times 8 \times 16 = 1,152$ weights, 16 biases.
- $W_3$: $32 \times 1 = 32$ weights, 1 bias.
- **Total Parameters:** $1,425$ floating-point weights.

*Scientific Appraisal:* With only 1,425 parameters, the network is deliberately proportioned to prevent catastrophic overfitting on small neuroimaging cohorts (e.g., $N = 30-100$ patients, $200-800$ candidates).

---

## 4. Training Dynamics & Regularization

1. **Loss Function:** Class-balanced binary cross-entropy with L2 weight decay ($\lambda_{\text{reg}} = 10^{-4}$).
2. **Optimization:** Adam optimizer ($\beta_1 = 0.9, \beta_2 = 0.999, \epsilon = 10^{-8}$) with analytical backpropagation through `_col2im`.
3. **Symmetry Augmentation:** Flip along $u$ ($X \to X[:, :, ::-1, :]$). Augmentation along $v$ or $n$ is scientifically impermissible because cortical depth ($n$) and sulcal wall morphology ($v$) are biologically asymmetric.
4. **Early Stopping:** Monitored against an out-of-fold patient validation split; stops if validation loss fails to improve for 6 epochs.

---

## 5. Scientific Limitations & Recommendations

1. **Loss of Lamina Stratification:** By computing MinIP along $n$, a hypointense sulcal vein running parallel to the cortex at $+2\text{ mm}$ in CSF cannot be distinguished from a subpial cSS deposit at $-0.5\text{ mm}$ in parenchyma if both project onto the same $(u, v)$ coordinates.
   - *Recommendation for future major release:* Implement a lightweight 3D CNN (e.g., 3D conv with separable spatial/depth filters) to preserve the $n$-depth profile without projecting.
2. **Out-of-Distribution (OOD) Guard:** In v5.24/v5.25, `meta.py` includes `patch_stats(M)` (mean, SD, and mean absolute gradient along patch axes) to compute Mahalanobis distance against the training patch manifold. When a clinical scan exhibits extreme motion or metal artifacts, `image_ood` triggers `"insufficient"`. This is a vital clinical safety mechanism.

---

## 6. Audit Verdict

**Image ML Architecture: PASS WITH SCIENTIFIC DISTINCTION**  
The surface-aligned physical coordinate system and lightweight 1,425-parameter pure NumPy CNN represent an exemplary, mathematically sound neuroimaging solution that avoids external dependencies while guaranteeing spatial scale invariance.
