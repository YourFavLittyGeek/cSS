#!/usr/bin/env python3
"""run_imaging.py - Stage 2 P1-P2 command line (image index + geometry gate, css-patch/2.0 patches). SYNTHETIC data only; research software.
usage:
  run_imaging.py verify                               pinned production sources used by the imaging package
  run_imaging.py demo DIR [--n 3]                     write SYNTHETIC studies SYN01.. (refuses a non-synthetic folder)
  run_imaging.py index SID --base DIR [--write]       index one synthetic study; --write stores DIR/unified_engine/image_index/SID.json
  run_imaging.py patches SID --base DIR [--write]     css-patch/2.0 patches of every object; --write stores DIR/unified_engine/patches/SID/
exit codes: 0 ok, 1 problems, 3 refused (not synthetic)"""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uengine.imaging import NotSynthetic, verify_sources, index as X, patches as PT, synthetic_images as S   # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("verify")
    d = sp.add_parser("demo"); d.add_argument("dir"); d.add_argument("--n", type=int, default=3)
    i = sp.add_parser("index"); i.add_argument("sid"); i.add_argument("--base", required=True); i.add_argument("--write", action="store_true")
    i.add_argument("--json", action="store_true")
    q = sp.add_parser("patches"); q.add_argument("sid"); q.add_argument("--base", required=True); q.add_argument("--write", action="store_true")
    a = ap.parse_args()
    if a.cmd == "verify":
        bad = verify_sources(); print("ok, 0 problems" if not bad else "\n".join(f"{p}: {m}" for p, m in bad)); return 1 if bad else 0
    if a.cmd == "demo":
        variants = [dict(), dict(flair_shift_mm=(0, 0, 2.4)), dict(axcodes="LPS", rot_deg=(25, 0, 0)), dict(axcodes="SAR")]
        for k in range(a.n):
            sid = f"SYN{k + 1:02d}"; S.write_study(a.dir, sid, seed=k, **variants[k % len(variants)]); print(f"{sid}: written to {a.dir}")
        return 0
    try:
        if a.cmd == "patches":
            r = PT.extract_study(a.base, a.sid, write=a.write); ok = [x for x in r["rows"] if x["status"] == "ok"]
            print(f"{a.sid}: {len(ok)} patches, {len(r['rows']) - len(ok)} skipped" + (f" ({r['blocked']})" if r["blocked"] else ""))
            for x in r["rows"]:
                if x["status"] != "ok": print(f"  {x['list']} {x['obj_id']}: skipped - {x['skip_reason']}")
            return 0
        r = X.index_study(a.base, a.sid, write=a.write)
    except NotSynthetic as e:
        print(f"refused: {e}", file=sys.stderr); return 3
    if a.json: print(json.dumps(r, indent=1, default=float))
    else:
        print(f"{a.sid}: {r['status']}  usable {', '.join(r['usable_channels']) or '-'}  inputs unchanged {r['inputs_unchanged']}")
        for c, v in r["channels"].items():
            print(f"  {c:8s} {v['status']:20s} {'; '.join(v.get('reasons', []))}")
        if a.write: print(f"  -> {r['path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
