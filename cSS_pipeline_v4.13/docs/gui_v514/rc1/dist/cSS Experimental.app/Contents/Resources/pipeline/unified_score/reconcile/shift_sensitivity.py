"""shift_sensitivity.py - synthetic (NOT patient) test: how a rigid label shift of d mm changes (a) the signed pial distance
and (b) the sulcal direction (pial-distance gradient) at cortical points, on a folded synthetic cortex (sinusoidal pial
surface, sulcal period 12 mm, depth 10 mm). Direction of the shift: along the surface normal on average (S-I), along the
sulcus (A-P, the invariant axis), and oblique. Output: median / p90 error per shift. Used to judge M18 / M23 (3.16 / 4.25 mm)."""
import numpy as np
from scipy import ndimage as ndi
v = 0.5; nx, ny, nz = 120, 40, 80
x, y, z = np.meshgrid(np.arange(nx) * v, np.arange(ny) * v, np.arange(nz) * v, indexing="ij")
surf = 25 + 5 * np.cos(2 * np.pi * x / 12)                  # pial height; sulci run along y
tissue = z < surf
def sdist(t): return ndi.distance_transform_edt(t, sampling=v) * -1 + ndi.distance_transform_edt(~t, sampling=v)
D = sdist(tissue); g = np.stack(np.gradient(D, v), -1); g /= np.linalg.norm(g, axis=-1, keepdims=True) + 1e-9
cortex = tissue & (D > -2.5) & (x > 12) & (x < nx * v - 12) & (z > 8)
print(f"shift_sensitivity (synthetic folded cortex, {cortex.sum()} cortex points)")
for name, u in (("S-I (across surface)", (0, 0, 1)), ("A-P (along sulcus)", (0, 1, 0)), ("L-R (across sulci)", (1, 0, 0)), ("oblique", (1, 1, 1))):
    u = np.array(u, float); u /= np.linalg.norm(u)
    for d in (1.0, 2.0, 3.16, 4.25):
        sh = u * d / v
        Ds = ndi.shift(D, sh, order=1, mode="nearest"); gs = np.stack([ndi.shift(g[..., i], sh, order=1, mode="nearest") for i in range(3)], -1)
        gs /= np.linalg.norm(gs, axis=-1, keepdims=True) + 1e-9
        e = np.abs(Ds - D)[cortex]; flip = (np.sign(Ds) != np.sign(D))[cortex].mean()
        ang = np.degrees(np.arccos(np.clip(np.abs((gs * g).sum(-1)), 0, 1)))[cortex]
        print(f"  {name:22s} {d:4.2f} mm: pial-dist error median {np.median(e):4.2f} p90 {np.percentile(e, 90):4.2f} mm, sign flip {flip:4.2f};"
              f"  sulcal-direction error median {np.median(ang):5.1f} p90 {np.percentile(ang, 90):5.1f} deg")
