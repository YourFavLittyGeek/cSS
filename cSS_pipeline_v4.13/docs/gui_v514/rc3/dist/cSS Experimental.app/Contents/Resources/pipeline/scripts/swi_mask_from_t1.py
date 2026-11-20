#!/usr/bin/env python3
"""Skull-strip the SWI with the T1 brain labels instead of SynthStrip (v5.2.5). Research software.
usage: swi_mask_from_t1.py SUBJECT [--dilate-mm 5]
Why: SynthStrip peaked at 31 GB (T1) and 64 GB (SWI) on the user's 36 GB Mac and froze it. With a T1, run_css.sh now
imports the SWI whole-head; prep_anat.sh registers T1 / FLAIR to it (bbregister or mri_coreg on whole-head images)
and puts the T1 labels on the SWI grid (work/ID_t1seg_swispace.nii.gz). This script then
  mask = every labelled voxel (brain, ventricles, cerebellum, brainstem), holes filled, grown by --dilate-mm, largest
         connected piece, holes filled again. Default 5 mm: detect_css.py ignores a 3 mm rim inside the mask edge, so
         candidates keep 2 mm of CSF beyond the label boundary (cSS lies on the cortical surface; known P006 cSS have
         pial_dist <= -0.57 mm); dark objects further out in the CSF fall into the rim (veins, not cSS)
and writes work/ID_brainmask.nii.gz, the masked SWI (data/ID_swi.nii, rewritten in place with its ORIGINAL modification
time, so files derived from it are not marked stale) and the masked FLAIR on the SWI grid (if present, same rule).
A mask volume outside 900-2300 cm3 is reported (registration or label problem): check in freeview before reading."""
import sys, os, argparse, numpy as np, nibabel as nib
from scipy import ndimage as ndi
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from css_common import base as _base


def brain_mask(labels, vox, dilate_mm):
    m = ndi.binary_fill_holes(labels > 0)
    if dilate_mm > 0:
        m = ndi.distance_transform_edt(~m, sampling=vox) <= dilate_mm
    lab, n = ndi.label(m)
    if n > 1: m = lab == (np.argmax(np.bincount(lab.ravel())[1:]) + 1)
    return ndi.binary_fill_holes(m)


def mask_in_place(path, m):
    """multiply the image by the mask, keep header, dtype and modification time"""
    st = os.stat(path); im = nib.load(path); a = np.asanyarray(im.dataobj)
    out = np.where(m.reshape(m.shape + (1,) * (a.ndim - 3)), a, 0).astype(a.dtype)
    nib.save(nib.Nifti1Image(out, im.affine, im.header), path)
    os.utime(path, (st.st_atime, st.st_mtime))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("subject"); ap.add_argument("--dilate-mm", type=float, default=5.0)
    a = ap.parse_args(); s = a.subject; B = _base()
    swi_p, lab_p = f"{B}/data/{s}_swi.nii", f"{B}/work/{s}_t1seg_swispace.nii.gz"
    for p in (swi_p, lab_p):
        if not os.path.exists(p): sys.exit(f"{s}: {p} missing - prep_anat.sh must run first (T1 labels on the SWI grid)")
    swi, L = nib.load(swi_p), nib.load(lab_p)
    if L.shape[:3] != swi.shape[:3] or not np.allclose(L.affine, swi.affine, atol=1e-3):
        sys.exit(f"{s}: T1 labels are not on the SWI grid - re-run prep_anat.sh")
    vox = np.array(swi.header.get_zooms()[:3], float)
    m = brain_mask(np.asanyarray(L.dataobj), vox, a.dilate_mm)
    cc = float(m.sum() * vox.prod() / 1000)
    nib.save(nib.Nifti1Image(m.astype(np.uint8), swi.affine), f"{B}/work/{s}_brainmask.nii.gz")
    mask_in_place(swi_p, m)
    fl = f"{B}/work/{s}_flair_swispace.nii.gz"
    done = ["SWI"]
    if os.path.exists(fl) and nib.load(fl).shape[:3] == m.shape: mask_in_place(fl, m); done.append("FLAIR")
    warn = "" if 900 <= cc <= 2300 else f"  WARNING: unusual brain volume - check {s} in freeview before reading"
    print(f"{s}: brain mask from the T1 labels (+{a.dilate_mm:g} mm) {cc:.0f} cm3 -> {' + '.join(done)} skull-stripped, "
          f"work/{s}_brainmask.nii.gz (no SynthStrip){warn}")
