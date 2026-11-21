"""known_projects.py - v5.20 studies already processed in another project on this Mac (e.g. the previous Percival version). Read only.

candidates()  the project folders found on this Mac (the previous Percival version ~/cSS_experimental, the production ~/css_project,
              other ~/Percival_project* folders) plus folders the user added; for each: studies, processed studies, already here.
match()       is an examination being imported the SAME examination as a study processed in one of the enabled projects? Compared by the
              image fingerprint of the chosen SWI in every form earlier versions recorded it (v5.15+ full-content 'c2:' / 'uid:',
              pre-v5.15 64 KB 'v1', DICOM SeriesInstanceUID). Only the other project's app_data/patients.json is read - no image is opened.
A match lets the import bring in the processed results (verified copy, processing_manager.import_study) instead of processing again.
"""
import glob, json, os

DEFAULTS = ["~/cSS_experimental", "~/css_project"]
_CACHE = {}


def _pats(path):
    f = os.path.join(path, "app_data", "patients.json")
    try:
        m = os.path.getmtime(f)
        if _CACHE.get(f, (None,))[0] != m:
            with open(f) as fh: _CACHE[f] = (m, json.load(fh))
        return _CACHE[f][1]
    except Exception: return []


def candidates(B, SET, studies_on_disk):
    here = os.path.realpath(B); here_codes = set(studies_on_disk(B))
    paths = [os.path.expanduser(p) for p in DEFAULTS] + sorted(glob.glob(os.path.expanduser("~/Percival_project*"))) + list(SET.get("known_projects_extra", []))
    off = set(SET.get("known_projects_off", [])); out = []; seen = set()
    for p in paths:
        rp = os.path.realpath(p)
        if rp in seen or rp == here or not os.path.isdir(p): continue
        seen.add(rp)
        codes = studies_on_disk(p) if os.path.isdir(os.path.join(p, "review")) or os.path.isdir(os.path.join(p, "runs")) else []
        proc = [c for c in codes if os.path.exists(os.path.join(p, "review", f"{c}_candidates.csv"))]
        kind = "previous Percival version" if rp.endswith("cSS_experimental") else "production project" if rp.endswith("css_project") else "Percival project"
        out.append(dict(path=p, kind=kind, n_studies=len(codes), n_processed=len(proc), n_here=len([c for c in proc if c in here_codes]),
                        enabled=rp not in off and p not in off))
    return out


def fingerprints_of(e, v1_of):
    """every form of the fingerprint of the examination's chosen SWI"""
    fps = set(); fp = e.get("fingerprint", "")
    if fp: fps.add(fp)
    if fp.startswith("uid:"): fps.add(fp[4:][:40]); fps.add(fp[4:])
    swi = next((s for s in e.get("series", []) if s["path"] == e.get("chosen", {}).get("SWI")), None)
    if swi:
        if swi.get("fingerprint"): fps.add(swi["fingerprint"])
        if os.path.isfile(swi["path"]):
            try: fps.add(v1_of(swi["path"]))
            except Exception: pass
    return {x for x in fps if x}


def match(e, B, SET, studies_on_disk, v1_of):
    """-> dict(project, kind, code, processed) for the first enabled project holding the same examination, or {}"""
    fps = fingerprints_of(e, v1_of)
    if not fps: return {}
    for c in candidates(B, SET, studies_on_disk):
        if not c["enabled"]: continue
        for p in _pats(c["path"]):
            if {str(p.get("fingerprint", "")), str(p.get("fingerprint_v1", ""))} & fps:
                code = p.get("code", "")
                return dict(project=c["path"], kind=c["kind"], code=code, processed=os.path.exists(os.path.join(c["path"], "review", f"{code}_candidates.csv")))
    return {}
