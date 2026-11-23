"""uengine/transfer/crashpoints.py - Phase 1c test support: deterministic SIGKILL at named write-ahead boundaries.

crash("commit.after_publish") kills the current process with SIGKILL when PERCIVAL_TEST_CRASH_AT names that point
("name" = first time it is reached, "name:N" = the N-th time; several separated by commas). It is honoured ONLY when
PERCIVAL_TEST_ISOLATION=1 (set by tests/_isolation.py) - the application never kills itself.
"""
import os
import signal

_COUNTS = {}
REACHED = []          # names reached in this process (for tests that list the boundaries)


def crash(name: str) -> None:
    REACHED.append(name)
    spec = os.environ.get("PERCIVAL_TEST_CRASH_AT")
    if not spec or os.environ.get("PERCIVAL_TEST_ISOLATION") != "1":
        return
    for item in spec.split(","):
        n, _, k = item.strip().partition(":")
        if n == name:
            _COUNTS[name] = _COUNTS.get(name, 0) + 1
            if _COUNTS[name] == int(k or 1):
                os.kill(os.getpid(), signal.SIGKILL)
