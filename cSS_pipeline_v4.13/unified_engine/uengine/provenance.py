"""provenance.py - repository-local source access for the Unified Score engine.

MATH is executed from the repository's OWN production code text (scripts/detect_css.py, scripts/css_tiers.py), never from a copy.
PINNED holds the sha256 of every source file the engine executes verbatim or imports, as recorded from commit 6f0ca44
(experimental/unified-gui, Percival v5.14.2-rc5; identical to the production install for detect_css.py). verify_sources() reports any
difference: a changed detector must be reviewed (and the regression tests re-pinned) before the engine trusts it.
Legacy modules are imported under private names ('legacy_*') so they cannot shadow anything."""
import ast, hashlib, importlib, importlib.util, os, sys, textwrap

ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))           # .../unified_engine
ROOT = os.path.dirname(ENGINE)                                                  # .../cSS_pipeline_v4.13
SCRIPTS = os.path.join(ROOT, "scripts")
UNIFIED = os.path.join(ROOT, "unified_score")
DETECTOR = os.path.join(SCRIPTS, "detect_css.py")
DETECTOR_SHA256 = "c15b29f69af7af29aae408810ad859f5ba900b7c85ce9ffb7b2970685aee73bf"
PINNED = {
    "scripts/detect_css.py": DETECTOR_SHA256,
    "scripts/css_tiers.py": "ae88423bdf3b581fd3ef546771690f85bdbc877dff75d1f1386d21efa08cdc2a",
    "scripts/css_common.py": "4b8362eb0f25773bd88aaf3de8ec667d6f051f731a7905dfeaf0d475410e813b",
    "scripts/css_features.py": "539f0a56c15d130feb02cfa28a7f47b5e7b05621ba9323b5d9904e157dc5b48e",
    "scripts/css_confidence.py": "46ddbeb5fdfb7e28ef708e1dd233035052ea2b56dd3e4138e95aaa43216179c7",
    "scripts/css_model.py": "6ff8ee522dc1c6d038f0cea67e472cdab634115ae093462d6882acec888b2f08",
    "scripts/train_ranker.py": "27add19e93bc69ec87a4d7e1658401b4889b714f8bb3be825c3dc518f44bb677",
    "unified_score/uscore/model.py": "4d045e20bd813da60957ac85d5fce42b2761d5b00be8215f62352286bc95eb0a",
    "unified_score/uscore/common.py": "7c52e83a33fe36c14e648fdb38f1335adfff5444e98d897aaf8ca6c89d247819",
}


class ProvenanceError(RuntimeError): pass


def sha256_file(p):
    with open(p, "rb") as f: return hashlib.sha256(f.read()).hexdigest()


def sha256_text(t): return hashlib.sha256(t.encode()).hexdigest()


def verify_sources():
    """-> list of (path, problem); empty = every pinned source is byte-identical to the recorded production / rc5 code"""
    bad = []
    for rel, h in PINNED.items():
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p): bad.append((rel, "missing"))
        elif sha256_file(p) != h: bad.append((rel, "sha256 differs from the pinned value"))
    return bad


def detector_sha_prefix_ok():
    return os.path.exists(DETECTOR) and sha256_file(DETECTOR) == DETECTOR_SHA256


def provenance_record():
    return dict(root=ROOT, pinned=PINNED, problems=verify_sources())


_LOADED = {}


def load_legacy(module, sub="scripts"):
    key = (sub, module)
    if key in _LOADED: return _LOADED[key]
    d = os.path.join(ROOT, sub); path = os.path.join(d, module.replace(".", os.sep) + ".py")
    if not os.path.exists(path): raise ProvenanceError(f"{path} not found")
    if d not in sys.path: sys.path.insert(0, d)
    if "." in module: m = importlib.import_module(module)
    else:
        spec = importlib.util.spec_from_file_location(f"legacy_{module}", path)
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); sys.modules.setdefault(module, m)
    _LOADED[key] = m
    return m


def source(path=DETECTOR):
    with open(path) as f: return f.read()


def extract_lines(start_contains, end_contains, path=DETECTOR, include_end=False):
    L = source(path).splitlines()
    s = [i for i, l in enumerate(L) if start_contains in l]
    if len(s) != 1: raise ProvenanceError(f"start marker {start_contains!r} found {len(s)} times")
    e = [i for i in range(s[0] + 1, len(L)) if end_contains in L[i]]
    if not e: raise ProvenanceError(f"end marker {end_contains!r} not found after the start marker")
    return textwrap.dedent("\n".join(L[s[0]:e[0] + (1 if include_end else 0)]))


def function_source(name, path=DETECTOR):
    txt = source(path); t = ast.parse(txt)
    for n in t.body:
        if isinstance(n, ast.FunctionDef) and n.name == name: return ast.get_source_segment(txt, n)
    raise ProvenanceError(f"function {name} not found in {path}")


def module_constants(path=DETECTOR, names=None):
    import numpy as np
    txt = source(path); t = ast.parse(txt); ns = dict(np=np, os=os, sys=sys)
    for n in t.body:
        if not isinstance(n, (ast.Assign, ast.AugAssign)): continue
        tg = n.targets if isinstance(n, ast.Assign) else [n.target]
        ids = [x.id for x in tg if isinstance(x, ast.Name)] + [e.id for x in tg if isinstance(x, ast.Tuple) for e in x.elts if isinstance(e, ast.Name)]
        if not ids or not all(i.isupper() or i.replace("_", "").isupper() for i in ids): continue
        if names is not None and not set(ids) & set(names): continue
        try: exec(compile(ast.Module([n], []), path, "exec"), ns)
        except Exception: pass
    return {k: v for k, v in ns.items() if k not in ("np", "os", "sys", "__builtins__")}


def list_assignment(name, path=DETECTOR):
    t = ast.parse(source(path))
    for n in ast.walk(t):
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and getattr(n.targets[0], "id", None) == name and isinstance(n.value, ast.List):
            return ast.literal_eval(n.value)
    raise ProvenanceError(f"list {name} not found")


def detector_columns():
    return list_assignment("cols") + list_assignment("V50_COLS")
