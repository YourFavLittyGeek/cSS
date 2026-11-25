"""Which processing method (pathway) suits a study, which were tried, and which one to try next (2026-11-25).

Requirements (FreeSurfer documentation / mailing list, checked 2026-11-25; summary in docs/engineering/PATHWAY_REQUIREMENTS.md):
  synthseg      SynthSeg --parc --robust on the T1 + mri_coreg      any T1 (SynthSeg is contrast- and resolution-agnostic)
  coreg_masked  same labels, T1 masked by its labels, mri_coreg      any T1
  synthmorph    mri_synthmorph register -m rigid                    T1; mri_synthmorph + models/synthmorph.rigid.*.h5 installed;
                                                                    whole-brain SWI (resamples to 1 mm, needs the full head:
                                                                    partial slabs are not supported)
  recon         recon-all (classic, -no-v8) + bbregister --t2       3-D T1 with every voxel side <= 1.3 mm (Fischl: below that
                                                                    recon-all is unreliable); recon-all + bbregister installed; ~2-3 h
  swi_only      SynthSeg on the SWI                                  SWI only; a partial slab works but is low confidence

Statuses per method: "worked" (finished with it), "failed" (tried, with the reason), "untried", "unsuitable" (why).
Next method: first suitable, untried one in ORDER. If two T1 methods both missed the alignment check by more than 2 mm the T1
is probably from another session (or the patient moved), so SWI-only is recommended instead of more T1 methods.
Pure functions on plain data (header facts are read by facts()); no side effects."""
import glob
import json
import os

ORDER = ["synthseg", "coreg_masked", "synthmorph", "recon", "swi_only"]
T1_METHODS = ("synthseg", "coreg_masked", "synthmorph", "recon")
FAST_AUTO = ("coreg_masked", "synthmorph")     # retried automatically after a misregistration (minutes, no extra risk)
RECON_MAX_VOX_MM = 1.3
SLAB_MIN_MM = 90.0                              # SWI extent along the slice axis below this = partial slab
MISMATCH_MM = 2.0
ICON = {"worked": "✓", "failed": "✗", "untried": "○", "unsuitable": "🚫"}


def _nifti_geom(folder):
    """voxel sizes / extent (mm) / shape of the LARGEST volume in folder (dcm2niix can split off a 1-slice localizer,
    e.g. *_i00001 512x512x1 next to the real 52-slice SWI), via nibabel headers; None when unreadable / absent"""
    fs = sorted(glob.glob(os.path.join(folder, "*.nii.gz")) + glob.glob(os.path.join(folder, "*.nii")))
    best = None
    try:
        import nibabel as nib
    except ImportError:
        return None
    for fp in fs:
        try:
            h = nib.load(fp).header
            sh = [int(x) for x in h.get_data_shape()[:3]] + [1] * (3 - len(h.get_data_shape()[:3]))
            z = [float(x) for x in h.get_zooms()[:3]] + [1.0] * (3 - len(h.get_zooms()[:3]))
        except Exception:
            continue
        n = sh[0] * sh[1] * sh[2]
        if best is None or n > best[0]: best = (n, dict(vox=z, extent=[a * b for a, b in zip(z, sh)], shape=sh))
    return best[1] if best else None


def tools(fs_home):
    """which FreeSurfer pieces are installed (file checks only)"""
    fs_home = fs_home or os.environ.get("FREESURFER_HOME", "")
    b = lambda n: bool(fs_home) and os.access(os.path.join(fs_home, "bin", n), os.X_OK)
    models = glob.glob(os.path.join(fs_home, "models", "synthmorph.rigid*.h5")) if fs_home else []
    return dict(synthseg=b("mri_synthseg"), synthmorph=b("mri_synthmorph") and bool(models), synthmorph_tool=b("mri_synthmorph"),
                synthmorph_model=bool(models), recon=b("recon-all") and b("bbregister"), coreg=b("mri_coreg"))


def facts(B, p, fs_home=""):
    """what the checks need for one study: T1 / SWI geometry from raw/<code>/ (converted NIfTI), tools"""
    code = p.get("code", "")
    has_t1 = bool((p.get("series") or {}).get("T1") or (p.get("series_t1") or {}).get("T1")
                  or glob.glob(os.path.join(B, "raw", code, "T1", "*.nii*")))
    return dict(has_t1=has_t1, has_swi=bool((p.get("series") or {}).get("SWI") or glob.glob(os.path.join(B, "raw", code, "SWI", "*.nii*"))),
                t1=_nifti_geom(os.path.join(B, "raw", code, "T1")), swi=_nifti_geom(os.path.join(B, "raw", code, "SWI")),
                tools=tools(fs_home))


def suitability(f):
    """{method: (ok, reason)} - reason explains a refusal, or adds a caution to an ok"""
    out, tl = {}, f.get("tools") or {}
    t1, swi = f.get("t1"), f.get("swi")
    slab = bool(swi and swi["extent"][2] < SLAB_MIN_MM)          # SWI is axial (detect stops otherwise): array axis 2 = slices
    no_t1 = "no usable T1"
    out["synthseg"] = (True, "") if f.get("has_t1") else (False, no_t1)
    out["coreg_masked"] = out["synthseg"]
    if not f.get("has_t1"): out["synthmorph"] = (False, no_t1)
    elif tl and not tl.get("synthmorph_tool", True): out["synthmorph"] = (False, "mri_synthmorph is not installed")
    elif tl and not tl.get("synthmorph_model", True): out["synthmorph"] = (False, "SynthMorph model files are missing ($FREESURFER_HOME/models)")
    elif slab: out["synthmorph"] = (False, f"the SWI is a partial slab ({swi['extent'][2]:.0f} mm high) - SynthMorph needs the whole head")
    else: out["synthmorph"] = (True, "")
    if not f.get("has_t1"): out["recon"] = (False, no_t1)
    elif t1 and max(t1["vox"]) > RECON_MAX_VOX_MM:
        out["recon"] = (False, f"the T1 is not fine enough for recon-all ({'x'.join(f'{v:.1f}' for v in t1['vox'])} mm; needs <= {RECON_MAX_VOX_MM} mm in every direction)")
    elif t1 and min(t1["shape"]) < 40: out["recon"] = (False, "the T1 is a 2-D / thin stack, not a 3-D volume")
    elif tl and not tl.get("recon", True): out["recon"] = (False, "recon-all / bbregister are not installed")
    else: out["recon"] = (True, "takes about 2-3 hours" + ("" if t1 else "; T1 resolution not checked yet"))
    out["swi_only"] = (True, "partial slab: results are low confidence" if slab else "") if f.get("has_swi") else (False, "no SWI")
    return out


def history(p):
    """{method: [attempt dicts]} from p['tried'] (registration misses, crashes); the current pathway when done = worked"""
    h = {}
    for t in p.get("tried", []) or []:
        h.setdefault(t.get("pathway", ""), []).append(t)
    return h


def statuses(p, suit):
    h = history(p); cur = p.get("pathway") or "synthseg"; out = {}
    for m in ORDER:
        ok, why = suit.get(m, (True, ""))
        if p.get("status") == "done" and m == cur: out[m] = dict(state="worked", why="")
        elif m in h:
            last = h[m][-1]
            out[m] = dict(state="failed", why=last.get("reason") or (f"still misaligned ({last.get('shift')} mm)" if last.get("shift") not in (None, "") else "failed"))
        elif not ok: out[m] = dict(state="unsuitable", why=why)
        else: out[m] = dict(state="untried", why=why)
    return out


def t1_mismatch(p):
    """two T1 methods that both missed the alignment check by more than MISMATCH_MM -> the T1 probably does not match"""
    big = set()
    for t in p.get("tried", []) or []:
        try:
            if t.get("pathway") in T1_METHODS and float(t.get("shift")) > MISMATCH_MM: big.add(t["pathway"])
        except (TypeError, ValueError):
            pass
    return len(big) >= 2


def next_method(p, suit):
    """(method, reason) for the next attempt; method '' when nothing suitable is left"""
    st = statuses(p, suit); cur = p.get("pathway") or "synthseg"
    left = [m for m in ORDER if st[m]["state"] == "untried" and m != cur]
    if t1_mismatch(p) and "swi_only" in left:
        return "swi_only", f"two T1 methods missed by more than {MISMATCH_MM:g} mm: the T1 is probably from another session or the patient moved"
    if left: return left[0], ""
    return "", "every suitable method was tried"


def summary(B, p, fs_home=""):
    """everything the GUI shows for one study"""
    suit = suitability(facts(B, p, fs_home))
    st = statuses(p, suit); nxt, why = next_method(p, suit)
    return dict(methods=[dict(key=m, state=st[m]["state"], why=st[m]["why"], icon=ICON[st[m]["state"]]) for m in ORDER],
                next=nxt, next_why=why)
