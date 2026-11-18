"""Experimental feature flags. ALL default 0. Read only by experimental/structural_detection/run_structural.py.
Production scripts (scripts/*.py) never import this package, so production output cannot change."""
import os
FLAGS = ("CSS_HESSIAN_FINGERPRINT", "CSS_SURFACE_COORDINATES", "CSS_VESSEL_GRAPH", "CSS_MULTIVIEW_SEEDING",
         "CSS_SULCUS_REFERENCE", "CSS_CANDIDATE_SPLITTING", "CSS_EXPERIMENTAL_FUSION")
# module dependencies: a module that needs another's output turns it on internally (recorded in the config)
DEPENDS = {"CSS_CANDIDATE_SPLITTING": ["CSS_HESSIAN_FINGERPRINT"], "CSS_EXPERIMENTAL_FUSION": []}

def read(env=None):
    env = os.environ if env is None else env
    return {f: env.get(f, "0") == "1" for f in FLAGS}

def any_on(fl):
    return any(fl.values())
