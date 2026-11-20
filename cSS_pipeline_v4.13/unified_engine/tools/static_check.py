#!/usr/bin/env python3
"""Minimal static analysis of the Unified Score engine (ruff / pyflakes / mypy are NOT installed in the css environment and nothing was downloaded):
  1. every .py file in src/, tests/, tools/ byte-compiles
  2. unused imports (AST: imported name never referenced; '# noqa' on the line exempts it)
  3. names used but never bound anywhere in the module (AST approximation of 'undefined name'; builtins excluded)
  4. every package module imports with warnings turned into errors
Exit code = number of findings."""
import ast, builtins, importlib, os, py_compile, sys, warnings

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIRS = ("uengine", "uengine/prototype", "tests", "tools", ".", "../app")


APP_FILES = ("shadow_engine_gui.py",)          # only the app files this work added (the rest of the app is not ours to lint)


def files():
    for d in DIRS:
        for f in sorted(os.listdir(os.path.join(ROOT, d))):
            if f.endswith(".py") and (d != "../app" or f in APP_FILES): yield os.path.join(ROOT, d, f)


def check(path):
    out = []
    try: py_compile.compile(path, doraise=True)
    except py_compile.PyCompileError as e: return [f"{path}: does not compile: {e.msg}"]
    with open(path) as fh: src = fh.read()
    t = ast.parse(src); lines = src.splitlines()
    imported = {}
    for n in ast.walk(t):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                nm = (a.asname or a.name).split(".")[0]
                if "noqa" not in lines[n.lineno - 1]: imported[nm] = n.lineno
    used = {n.id for n in ast.walk(t) if isinstance(n, ast.Name)} | {n.value.id for n in ast.walk(t) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)}
    allx = set()
    for n in t.body:
        if isinstance(n, ast.Assign) and any(getattr(x, "id", "") == "__all__" for x in n.targets): allx = set(ast.literal_eval(n.value))
    for nm, ln in imported.items():
        if nm not in used and nm not in allx and nm != "*": out.append(f"{os.path.relpath(path, ROOT)}:{ln}: unused import {nm}")
    bound = set(dir(builtins)) | set(imported) | {"__file__", "__name__", "__doc__"}
    for n in ast.walk(t):
        if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)): bound.add(n.name)
        if isinstance(n, ast.arg): bound.add(n.arg)
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)): bound.add(n.id)
        if isinstance(n, ast.ExceptHandler) and n.name: bound.add(n.name)
        if isinstance(n, (ast.Global, ast.Nonlocal)): bound |= set(n.names)
        if isinstance(n, ast.alias): bound.add((n.asname or n.name).split(".")[0])
    for n in ast.walk(t):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in bound:
            out.append(f"{os.path.relpath(path, ROOT)}:{n.lineno}: name {n.id!r} is never bound")
    return out


def main():
    F = []
    for p in files(): F += check(p)
    sys.path.insert(0, ROOT)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        for pkg in ("uengine", "uengine.prototype"):
            for f in sorted(os.listdir(os.path.join(ROOT, *pkg.split(".")))):
                if f.endswith(".py") and f != "__init__.py":
                    try: importlib.import_module(f"{pkg}.{f[:-3]}")
                    except Exception as e: F.append(f"{pkg}.{f[:-3]}: import failed under warnings-as-errors: {type(e).__name__}: {e}")
    for x in F: print(x)
    print(f"static check: {sum(1 for _ in files())} files, {len(F)} finding(s)")
    return len(F)


if __name__ == "__main__":
    sys.exit(main())
