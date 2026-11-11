"""css_sheet3d.plate_filter on synthetic dark structures: a thin sheet at 0 / 45 / 90 degrees to the axial plane, a tube, a blob. Also measures how the
2-D axial Sato filter of the detector depends on the orientation (audit finding F2). usage: check_sheet3d.py"""
import os, sys, numpy as np
from skimage.filters import sato
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import css_sheet3d as c3
def fail(m): print("FAIL:", m); sys.exit(1)
vox = (0.8, 0.8, 0.8); n = 56; rng = np.random.default_rng(2)
ax = (np.arange(n) - n / 2 + 0.5) * vox[0]; X, Y, Z = np.meshgrid(ax, ax, ax, indexing="ij")


def volume(dark):
    v = np.ones((n, n, n), np.float32) + rng.normal(0, 0.02, (n, n, n)).astype(np.float32); v[dark] = 0.3; return v


def sheet(theta_deg):
    th = np.radians(theta_deg); nrm = np.array([0.0, np.sin(th), np.cos(th)])       # theta 0: normal along z = parallel to the axial slices
    u = np.array([1.0, 0, 0]); w = np.cross(nrm, u)
    d = X * nrm[0] + Y * nrm[1] + Z * nrm[2]; pu = X * u[0] + Y * u[1] + Z * u[2]; pw = X * w[0] + Y * w[1] + Z * w[2]
    return (np.abs(d) <= 0.8) & (np.abs(pu) <= 12) & (np.abs(pw) <= 12), (np.abs(d) <= 0.4) & (np.abs(pu) <= 5) & (np.abs(pw) <= 5)


zone = np.ones((n, n, n), bool); S3, S2, ang = {}, {}, {}
for th in (0, 45, 90):
    dark, core = sheet(th); v = volume(dark)
    S, NZ = c3.plate_filter(v, vox, zone & (np.abs(X) < 14) & (np.abs(Y) < 14) & (np.abs(Z) < 14))
    S3[th] = float(S[core].mean()); ang[th] = float(np.median(c3.orientation_angle(NZ[core])))
    R = np.zeros_like(v)
    for k in range(n): R[:, :, k] = sato(v[:, :, k], sigmas=[1.0, 1.5, 2.0], black_ridges=True)
    S2[th] = float(R[core].mean())
r3 = min(S3.values()) / max(S3.values()); r2 = min(S2.values()) / max(S2.values())
if not r3 >= 0.6: fail(f"3-D plate measure must be nearly orientation-free: {S3} (min/max {r3:.2f})")
if not r2 <= 0.5: fail(f"2-D axial Sato should depend on orientation (a sheet parallel to the slices is not a ridge): {S2} (min/max {r2:.2f})")
for th, want in ((0, 0), (45, 45), (90, 90)):
    if abs(ang[th] - want) > 12: fail(f"sheet orientation {th}: measured {ang[th]:.0f} degrees")
tube = (Y ** 2 + Z ** 2 <= 0.8 ** 2) & (np.abs(X) <= 12); blob = X ** 2 + Y ** 2 + Z ** 2 <= 2.4 ** 2
St, _ = c3.plate_filter(volume(tube), vox, zone & (np.abs(X) < 6) & (np.abs(Y) < 4) & (np.abs(Z) < 4)); Sb, _ = c3.plate_filter(volume(blob), vox, zone & (np.abs(X) < 5) & (np.abs(Y) < 5) & (np.abs(Z) < 5))
core_t = (Y ** 2 + Z ** 2 <= 0.6 ** 2) & (np.abs(X) <= 6); core_b = X ** 2 + Y ** 2 + Z ** 2 <= 1.2 ** 2
ref = max(S3.values()); t_, b_ = float(St[core_t].mean()), float(Sb[core_b].mean())
# a thin tube is NOT removed completely (a 1.6 mm tube on a 0.8 mm grid keeps ~0.4 of the sheet response): the measure suppresses tubes by about 2x and blobs by >5x
if not (t_ <= 0.5 * ref and b_ <= 0.2 * ref): fail(f"tube {t_:.3f} (limit 0.5) and blob {b_:.3f} (limit 0.2) must be suppressed vs a sheet {ref:.3f}")
print(f"sheet response 3-D plate {{0: {S3[0]:.3f}, 45: {S3[45]:.3f}, 90: {S3[90]:.3f}}} min/max {r3:.2f}; 2-D axial Sato {{0: {S2[0]:.3f}, 45: {S2[45]:.3f}, 90: {S2[90]:.3f}}} min/max {r2:.2f}")
print(f"orientation recovered {ang[0]:.0f} / {ang[45]:.0f} / {ang[90]:.0f} degrees; tube {t_ / ref:.2f} and blob {b_ / ref:.2f} of the sheet response")
print("RESULT sheet3d OK")
