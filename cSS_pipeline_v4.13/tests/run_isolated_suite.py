"""Phase 0: run the PERCIVAL unittest suite under test isolation and PROVE that no live file changed.

    python tests/run_isolated_suite.py [pattern]        (default pattern: test_*.py)

1. fingerprints the live research files (SHA-256, size, mtime) and folder listings - reading only;
2. activates tests/_isolation.py (temporary HOME / CSS_BASE / volumes root + write-refusing audit hook) BEFORE any
   application module is imported, then runs unittest discovery on tests/;
3. fingerprints again and fails (exit 1) if any live fingerprint changed, if any write was refused by the guard (even if
   the code under test swallowed the refusal), or if any test failed. The evidence is printed.
"""
import hashlib
import json
import os
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT, os.path.join(ROOT, "unified_engine")]

import _isolation  # noqa: E402  (no application import before this point)

H = _isolation.REAL_HOME
LIVE_FILES = [os.path.join(H, "Percival_project", "app_data", n) for n in (
    "settings.json", "setup_state.json", "setup_done.json", "setup_report.json", "wizard_state.json", "patients.json",
    "pensieve.db", "transfer_queue.json", "transfer_policies.json", "notifications.json", "cohorts.json", "timings.json",
    "review_groups.json", "study_workspace_ledger.json", "sequential_study_queue.json", "sync_policy.json")] + [
    os.path.join(H, ".percival_vault_config.json"), os.path.join(H, ".percival_local_journal.db"),
    os.path.join(H, "Library", "Application Support", "Percival Dev", "project_path"),
    os.path.join(H, "Library", "Application Support", "Percival Dev", "setup.log")]
LIVE_DIRS = [os.path.join(H, "Percival_project", d) for d in ("", "app_data", "raw", "review", "data", "percival", "work", "subjects")] + \
            [H, os.path.join(H, "Library", "Application Support", "Percival Dev"), "/Volumes"]


def _sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def fingerprint():
    fp = {}
    for p in LIVE_FILES:
        if os.path.isfile(p):
            st = os.stat(p)
            fp[p] = dict(size=st.st_size, mtime_ns=st.st_mtime_ns, sha256=_sha(p))
        else:
            fp[p] = None
    for d in LIVE_DIRS:
        if os.path.isdir(d):
            try:
                names = sorted(os.listdir(d))
            except OSError:
                names = ["<unreadable>"]
            if d in (H, "/Volumes"):   # unrelated activity touches these folders' mtimes: compare their entry names only
                fp[d + "/"] = dict(entries=names)
            else:
                fp[d + "/"] = dict(mtime_ns=os.stat(d).st_mtime_ns, entries=names)
        else:
            fp[d + "/"] = None
    return fp


def main():
    pattern = sys.argv[1] if len(sys.argv) > 1 else "test_*.py"
    before = fingerprint()
    st = _isolation.activate()
    os.chdir(ROOT)
    import unittest
    suite = unittest.defaultTestLoader.discover(HERE, pattern=pattern, top_level_dir=HERE)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    after = fingerprint()
    changed = {k: dict(before=before[k], after=after.get(k)) for k in before if before[k] != after.get(k)}
    print("\n=========== PERCIVAL test-isolation evidence ===========")
    print(f"real home (pwd)      : {H}")
    print(f"HOME during tests    : {os.environ.get('HOME')}")
    print(f"CSS_BASE during tests: {os.environ.get('CSS_BASE')}")
    print(f"volumes root (tests) : {os.environ.get('PERCIVAL_VOLUMES_ROOT')}")
    print(f"live files/dirs fingerprinted: {len(before)} ({sum(1 for v in before.values() if v)} present)")
    print(f"live fingerprints changed    : {len(changed)}")
    for k, v in changed.items():
        print(f"  CHANGED {k}: {json.dumps(v, default=str)[:400]}")
    print(f"writes refused by the guard  : {len(st['violations'])}")
    for v in st["violations"][:20]:
        print(f"  REFUSED {v}")
    print(f"tests run {result.testsRun}, failures {len(result.failures)}, errors {len(result.errors)}, skipped {len(result.skipped)}")
    ok = result.wasSuccessful() and not changed and not st["violations"]
    print("ISOLATION RESULT:", "PASS - no live file changed" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
