#!/usr/bin/env python3
"""Unified Score engine CLI (SHADOW MODE; research software). The app calls it in a SUBPROCESS so an engine failure can never stop the app.

  run_engine.py shadow SID [--base B] [--model PATH]   shadow result -> B/unified_engine/shadow/SID.json (prints a one-line summary)
  run_engine.py models [--base B]                       installed models with health status (JSON)
  run_engine.py verify                                  pinned production sources unchanged? (JSON; exit 1 if not)
  run_engine.py demo-base DIR [--n N] [--seed S]        write a SYNTHETIC demonstration base (refuses a non-synthetic base)
  run_engine.py train-synthetic OUT.json [--seed S]     train the SYNTHETIC demo model (never overwrites; synthetic data only)
A study is treated as synthetic only if its code starts with SYN AND the base carries the SYNTHETIC_BASE marker."""
import argparse, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["shadow", "models", "verify", "demo-base", "train-synthetic"]); ap.add_argument("arg", nargs="?")
    ap.add_argument("--base", default=os.environ.get("CSS_BASE", "")); ap.add_argument("--model", default=None)
    ap.add_argument("--n", type=int, default=8); ap.add_argument("--seed", type=int, default=None)
    a = ap.parse_args(argv)
    if os.environ.get("CSS_ENGINE_FAIL") == "1": raise RuntimeError("CSS_ENGINE_FAIL=1 (test hook: simulated engine crash)")
    from uengine import shadow, registry, provenance as pv, demo_base
    if a.cmd == "verify":
        p = pv.verify_sources(); print(json.dumps(dict(ok=not p, problems=p))); return 0 if not p else 1
    if a.cmd == "models":
        print(json.dumps([{k: v for k, v in m.items() if k != "card"} | dict(card=m.get("card")) for m in registry.list_models(a.base or None)], default=str)); return 0
    if a.cmd == "demo-base":
        codes = demo_base.write(a.arg, n_patients=a.n, seed=900 if a.seed is None else a.seed); print(json.dumps(dict(ok=True, studies=codes))); return 0
    if a.cmd == "train-synthetic":
        from uengine import train_demo
        h = train_demo.train(a.arg, seed=500 if a.seed is None else a.seed); print(json.dumps(dict(ok=h["status"] == "ok", health=h), default=str)); return 0
    if not a.base: sys.exit("--base (or CSS_BASE) is required")
    syn = a.arg.startswith("SYN") and demo_base.is_synthetic_base(a.base)
    r = shadow.run_study(a.base, a.arg, synthetic=syn, model_path=a.model)
    print(json.dumps(dict(ok=True, study=a.arg, synthetic=syn, ml_applied=r["ml_applied"], ml_status=r["ml_status"], n=r["n_candidates"],
                          counts=r["category_counts"], unchanged=r["original_outputs_unchanged"])))
    return 0 if r["original_outputs_unchanged"] else 3


if __name__ == "__main__":
    sys.exit(main())
