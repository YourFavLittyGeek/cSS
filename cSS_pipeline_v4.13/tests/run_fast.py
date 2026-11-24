"""run_fast.py - the fast targeted test profile (Stage 7): the tests that cover the PERCIVAL architecture, safety gates and the
consolidation stages, each through tests/run_isolated_suite.py (temporary HOME / CSS_BASE). Minutes, not the full hour of every suite.
  python tests/run_fast.py            the default profile
  python tests/run_fast.py PATTERN..  only these test files
Run the FULL suites (run_isolated_suite.py, run_tests.sh, run_uscore_tests.sh on a copy) at milestones."""
import os, re, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
PROFILE = ["test_stage1_retirement.py", "test_stage2_components.py", "test_stage3_model.py", "test_stage4_detection.py",
           "test_stage5_6_governance.py", "test_percival_architecture.py", "test_i0_safety.py", "test_phase3bcd_readiness.py",
           "test_phase3a3_ground_truth.py", "test_phase0_safety.py"]
pats = sys.argv[1:] or PROFILE; tot = dict(run=0, failures=0, errors=0, skipped=0); bad = []
for p in pats:
    if not os.path.exists(os.path.join(HERE, p)): print(f"--  {p}: not present"); continue
    r = subprocess.run([sys.executable, os.path.join(HERE, "run_isolated_suite.py"), p], capture_output=True, text=True)
    m = re.search(r"tests run (\d+), failures (\d+), errors (\d+), skipped (\d+)", r.stdout + r.stderr)
    if not m: print(f"??  {p}: no result (rc {r.returncode})"); bad.append(p); continue
    n, f, e, s = map(int, m.groups()); tot.update(run=tot["run"] + n, failures=tot["failures"] + f, errors=tot["errors"] + e, skipped=tot["skipped"] + s)
    ok = f == 0 and e == 0 and "ISOLATION RESULT: PASS" in r.stdout
    print(f"{'OK' if ok else 'XX'}  {p}: {n} run, {f} failures, {e} errors, {s} skipped"); (None if ok else bad.append(p))
print(f"fast profile: {tot['run']} run, {tot['failures']} failures, {tot['errors']} errors, {tot['skipped']} skipped" + (f"; failing: {bad}" if bad else ""))
sys.exit(1 if bad else 0)
