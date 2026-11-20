#!/usr/bin/env python3
"""run_imaging.py - Stage 2 command line (image index, geometry gate, patches, synthetic cohort, Image ML). SYNTHETIC data only; research software.
usage:
  run_imaging.py verify                               pinned production sources used by the imaging package
  run_imaging.py demo DIR [--n 3]                     write SYNTHETIC studies SYN01.. (refuses a non-synthetic folder)
  run_imaging.py index SID --base DIR [--write]       index one synthetic study; --write stores DIR/unified_engine/image_index/SID.json
  run_imaging.py patches SID --base DIR [--write]     css-patch/2.0 patches of every object; --write stores DIR/unified_engine/patches/SID/
  run_imaging.py cohort DIR [--n 8] [--seed 0] [--signal 1]   P3 synthetic cohort (acquisition variability, mimics, simulated readers)
  run_imaging.py models [--base DIR]                  image models and their health (JSON)
  run_imaging.py infer SID --base DIR [--model F] [--write]   local Image ML inference; --write stores DIR/unified_engine/image_ml/SID.json
  run_imaging.py train-synthetic OUT.json [--n-train 48]      train + evaluate the SYNTHETIC demonstration image model (never overwrites)
exit codes: 0 ok, 1 problems, 3 refused (not synthetic), 4 inference failed (nothing written)"""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uengine.imaging import NotSynthetic, verify_sources, index as X, patches as PT, synthetic_images as S   # noqa: E402
from uengine.imaging import image_infer as INF, synthetic_cohort as SC   # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("verify")
    d = sp.add_parser("demo"); d.add_argument("dir"); d.add_argument("--n", type=int, default=3)
    i = sp.add_parser("index"); i.add_argument("sid"); i.add_argument("--base", required=True); i.add_argument("--write", action="store_true")
    i.add_argument("--json", action="store_true")
    q = sp.add_parser("patches"); q.add_argument("sid"); q.add_argument("--base", required=True); q.add_argument("--write", action="store_true")
    c = sp.add_parser("cohort"); c.add_argument("dir"); c.add_argument("--n", type=int, default=8); c.add_argument("--seed", type=int, default=0)
    c.add_argument("--signal", type=int, default=1, choices=(0, 1))
    m = sp.add_parser("models"); m.add_argument("--base", default=None)
    f = sp.add_parser("infer"); f.add_argument("sid"); f.add_argument("--base", required=True); f.add_argument("--model", default=None)
    f.add_argument("--write", action="store_true")
    t = sp.add_parser("train-synthetic"); t.add_argument("out"); t.add_argument("--n-train", type=int, default=48); t.add_argument("--seed", type=int, default=500)
    a = ap.parse_args()
    if a.cmd == "verify":
        bad = verify_sources(); print("ok, 0 problems" if not bad else "\n".join(f"{p}: {m}" for p, m in bad)); return 1 if bad else 0
    if a.cmd == "demo":
        variants = [dict(), dict(flair_shift_mm=(0, 0, 2.4)), dict(axcodes="LPS", rot_deg=(25, 0, 0)), dict(axcodes="SAR")]
        for k in range(a.n):
            sid = f"SYN{k + 1:02d}"; S.write_study(a.dir, sid, seed=k, **variants[k % len(variants)]); print(f"{sid}: written to {a.dir}")
        return 0
    if a.cmd == "cohort":
        r = SC.write_cohort(a.dir, n=a.n, seed=a.seed, signal=a.signal)
        print(f"{len(r['profiles'])} SYNTHETIC studies ({', '.join(r['profiles'])}) written to {a.dir}; truth in unified_engine/image_truth/"); return 0
    if a.cmd == "models":
        print(json.dumps(INF.list_models(a.base), default=str)); return 0
    if a.cmd == "train-synthetic":
        from uengine.imaging import train_image_model as TR
        r = TR.train(a.out, n_train=a.n_train, seed=a.seed); ev = r["card"]["evaluation"]
        print(json.dumps(dict(path=r["path"], model_hash=r["model_hash"], cv=ev["cv_train_cohort"], test=ev["independent_synthetic_test"],
                              negative_control=ev["negative_control_independent"]), default=float)); return 0
    try:
        if a.cmd == "infer":
            try: r = INF.run_study(a.base, a.sid, model_path=a.model, write=a.write)
            except NotSynthetic: raise
            except Exception as e:
                print(f"inference failed: {type(e).__name__}: {e}", file=sys.stderr); return 4
            print(json.dumps(dict(study=a.sid, model_applied=r["model"]["applied"], model_status=r["model"]["status"], counts=r["category_counts"],
                                  unchanged=r["original_inputs_unchanged"], path=r.get("path")))); return 0
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
