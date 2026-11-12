#!/usr/bin/env python3
"""Export every candidate as images for external review (v5.2.8). Research software.
usage: export_candidates.py --ids M02,M03,... [--excluded] [--fov-mm 40] [--out review/candidate_export]
       [--zip review/candidate_export.zip]
Output (one folder per patient, one folder per candidate, then one zip):
  ID/overview.png              whole-head projections + axial montage (same as qc_figures.py)
  ID/cand_NN/candidate.png     axial / coronal / sagittal close-ups of the SWI with the object outline (red),
                               brain-mask edge (yellow); the reader's call and the tier are in the title
  ID/cand_NN/info.txt          the same facts as text
  ID/excl_NN/excluded.png      with --excluded: the same for objects removed by an exclusion rule
  summary.csv                  one row per candidate: pipeline tier and reason, reader's call, accepted or not,
                               volume, slices, region, folder
  excluded.csv                 one row per excluded object: rule, region, volume (no reader call)
  README.txt                   what is in the zip
Contains study codes only (no names, MRNs or DICOM headers). Reads only; changes no result."""
import sys, os, argparse, zipfile, datetime, warnings, numpy as np, pandas as pd
from scipy import ndimage as ndi
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
warnings.simplefilter("ignore", pd.errors.PerformanceWarning)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from css_common import base as _base
from qc_figures import load, window, objects, short_rule, rule_colour, overview, show, outline, plane


def reader_calls(B, s):
    """{cand_id: call} from review/ID_calls.csv (written by review_css.py / mark_css.py); {} if missing"""
    p = f"{B}/review/{s}_calls.csv"
    if not os.path.exists(p): return {}
    d = pd.read_csv(p)
    call = next((c for c in ("call", "label", "decision") if c in d.columns), None)
    if call is None or "cand_id" not in d.columns: return {}
    return {int(r.cand_id): str(r[call]) for _, r in d.iterrows()}


def render(I, Mk, m, vox, fov_mm, title, path, dpi):
    ijk = np.argwhere(m); com = ijk.mean(0)
    c = ijk[np.argmin(((ijk - com) ** 2).sum(1))]                 # a voxel OF the object
    r_ = np.maximum((fov_mm / 2 / vox).astype(int), 4)
    lo = np.maximum(c - r_, 0); hi = np.minimum(c + r_ + 1, I.shape)
    crop = tuple(slice(a, b) for a, b in zip(lo, hi)); cc = c - lo
    fig, axs = plt.subplots(1, 3, figsize=(9, 3.4))
    for j, (ax_, nm) in enumerate(((2, "axial"), (1, "coronal"), (0, "sagittal"))):
        img = plane(I[crop], ax_, cc[ax_]); mm = plane(m[crop], ax_, cc[ax_]); mk = plane(Mk[crop], ax_, cc[ax_])
        asp = {2: vox[1] / vox[0], 1: vox[2] / vox[0], 0: vox[2] / vox[1]}[ax_]
        show(axs[j], img, asp, nm); outline(axs[j], mk, "yellow", lw=0.8); outline(axs[j], mm, "red", lw=1.3)
    fig.suptitle(title, fontsize=8)
    fig.subplots_adjust(left=0.02, right=0.98, top=0.8, bottom=0.03, wspace=0.06)
    fig.savefig(path, dpi=dpi); plt.close(fig)


def export_patient(B, s, root, include_excl, fov_mm, dpi):
    folder = os.path.join(root, s); os.makedirs(folder, exist_ok=True)
    swi = f"{B}/data/{s}_swi.nii"
    if not os.path.exists(swi) or not os.path.exists(f"{B}/review/{s}_candidates.csv"):
        print(f"{s}: no detection output - skipped"); return [], []
    I, vox = load(swi); I = I.astype(np.float32)
    mp = f"{B}/work/{s}_brainmask.nii.gz"
    Mk = load(mp)[0] > 0 if os.path.exists(mp) else ndi.binary_fill_holes(I > 0)
    In = window(I, Mk)
    overview(B, s, folder)
    calls = reader_calls(B, s)
    C, dc = objects(B, s, "candidates")
    rows = []
    for _, r in dc.sort_values("oid").iterrows():
        cid = int(r.oid); m = C == cid
        if not m.any(): continue
        call = calls.get(cid, "")
        accepted = int(r.get("accept", 0) or 0) if not call else int(call == "cSS")
        cdir = os.path.join(folder, f"cand_{cid:02d}"); os.makedirs(cdir, exist_ok=True)
        tier = r.get("review_priority_rank", ""); reason = str(r.get("review_priority_reason", ""))
        region = str(r.get("region", "")); vol = float(r.get("volume_mm3", 0)); nsl = r.get("n_slices", "")
        title = (f"{s}  candidate {cid}  |  {r.get('hemi', '')} {region.replace('ctx-', '')}  |  {vol:.0f} mm3, {nsl} slices  |  "
                 f"tier {tier}: {reason[:70]}\nreader call: {call or 'not decided'}   (red = object, yellow = brain-mask edge, "
                 f"{fov_mm:.0f} mm field, image left = subject left)")
        render(In, Mk, m, vox, fov_mm, title, os.path.join(cdir, "candidate.png"), dpi)
        with open(os.path.join(cdir, "info.txt"), "w") as f:
            f.write(f"study {s}, candidate {cid}\nhemisphere {r.get('hemi', '')}, region {region}\n"
                    f"volume {vol:.1f} mm3, slices {nsl}, score_v4 {r.get('score_v4', '')}\n"
                    f"pipeline tier {tier}: {reason}\nreader call {call or 'not decided'}\n"
                    f"accepted as cSS {accepted}\nmimic class {r.get('mimic_class', '')}, artifact zone {r.get('artifact_zone', '')}\n")
        rows.append(dict(study_id=s, cand_id=cid, folder=f"{s}/cand_{cid:02d}", hemi=r.get("hemi", ""), region=region,
                         volume_mm3=round(vol, 1), n_slices=nsl, score_v4=r.get("score_v4", ""),
                         pipeline_tier=tier, pipeline_reason=reason, reader_call=call, accepted_cSS=accepted,
                         mimic_class=r.get("mimic_class", ""), artifact_zone=r.get("artifact_zone", "")))
    erows = []
    if include_excl:
        X, dx = objects(B, s, "excluded")
        for _, r in dx.sort_values("oid").iterrows() if len(dx) else []:
            eid = int(r.oid); m = X == eid
            if not m.any(): continue
            edir = os.path.join(folder, f"excl_{eid:02d}"); os.makedirs(edir, exist_ok=True)
            reason = str(r.get("reason", "")); region = str(r.get("region", "")); vol = float(r.get("volume_mm3", 0))
            title = (f"{s}  EXCLUDED object {eid}  |  {r.get('hemi', '')} {region.replace('ctx-', '')}  |  {vol:.0f} mm3\n"
                     f"removed by rule: {reason[:110]}   (red = object, yellow = brain-mask edge, {fov_mm:.0f} mm field)")
            render(In, Mk, m, vox, fov_mm, title, os.path.join(edir, "excluded.png"), dpi)
            erows.append(dict(study_id=s, excl_id=eid, folder=f"{s}/excl_{eid:02d}", hemi=r.get("hemi", ""), region=region,
                              volume_mm3=round(vol, 1), removed_by=reason))
    print(f"{s}: {len(rows)} candidates" + (f", {len(erows)} excluded" if include_excl else "") + " -> images written")
    return rows, erows


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ids", required=True, help="comma-separated study codes, e.g. M02,M03,M04")
    ap.add_argument("--excluded", action="store_true"); ap.add_argument("--fov-mm", type=float, default=40.0)
    ap.add_argument("--dpi", type=int, default=80)
    ap.add_argument("--out", default=""); ap.add_argument("--zip", default="")
    a = ap.parse_args(); B = _base()
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    root = a.out or f"{B}/review/candidate_export"
    zpath = a.zip or f"{B}/review/candidate_export_{stamp}.zip"
    os.makedirs(root, exist_ok=True)
    ids = [s.strip() for s in a.ids.split(",") if s.strip()]
    allc, alle = [], []
    for s in ids:
        c, e = export_patient(B, s, root, a.excluded, a.fov_mm, a.dpi)
        allc += c; alle += e
    pd.DataFrame(allc).to_csv(os.path.join(root, "summary.csv"), index=False)
    if a.excluded: pd.DataFrame(alle).to_csv(os.path.join(root, "excluded.csv"), index=False)
    with open(os.path.join(root, "README.txt"), "w") as f:
        f.write(f"Candidate export {stamp}. Patients: {', '.join(ids)}. Study codes only; no names, MRNs or DICOM headers.\n"
                "summary.csv: one row per candidate. pipeline_tier / pipeline_reason = the detector's own tier;\n"
                "reader_call = the reader's decision (cSS, Vessel, Normal, Artifact, Near ICH, Unsure); accepted_cSS = 1 if cSS.\n"
                "ID/overview.png: whole head, brain-mask edge, all candidates and excluded objects.\n"
                "ID/cand_NN/candidate.png: close-up of one candidate in three planes.\n"
                + ("excluded.csv / ID/excl_NN: objects removed by an exclusion rule (no reader call).\n" if a.excluded else "")
                + "Research software. Images are for review of the detector, not for diagnosis.\n")
    n = 0
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for dp, _, fn in os.walk(root):
            for f in sorted(fn):
                full = os.path.join(dp, f); z.write(full, os.path.relpath(full, root)); n += 1
    print(f"-> {zpath}  ({n} files, {os.path.getsize(zpath) / 1e6:.1f} MB; {len(allc)} candidates from {len(ids)} patients)")
