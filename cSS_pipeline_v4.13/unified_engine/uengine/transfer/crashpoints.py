"""uengine/transfer/crashpoints.py - Phase 1c/1d test support: SIGKILL (and 1d: delays) at named boundaries.

crash("commit.after_publish") kills the current process with SIGKILL when PERCIVAL_TEST_CRASH_AT names that point
("name" = first time it is reached, "name:N" = the N-th time; several separated by commas). It is honoured ONLY when
PERCIVAL_TEST_ISOLATION=1 (set by tests/_isolation.py) - the application never kills itself.
"""
import os
import signal

_COUNTS = {}
REACHED = []          # names reached in this process (for tests that list the boundaries)


def crash(name: str) -> None:
    if os.environ.get("PERCIVAL_TEST_ISOLATION") != "1":
        return                                              # production: a no-op (nothing recorded, nothing slowed)
    REACHED.append(name)
    slow = os.environ.get("PERCIVAL_TEST_SLOW_AT")          # 1d: "name=seconds,..." - hold a job at a boundary
    if slow:
        for item in slow.split(","):
            n, _, sec = item.strip().partition("=")
            if n == name:
                import time
                time.sleep(float(sec or 0.1))
    fail = os.environ.get("PERCIVAL_TEST_FAIL_AT")          # audit: "name[:N]=errno" raise OSError at that point
    if fail:
        for item in fail.split(","):
            point, _, eno = item.strip().partition("=")
            n, _, k = point.partition(":")
            if n == name:
                key = "fail:" + name
                _COUNTS[key] = _COUNTS.get(key, 0) + 1
                if _COUNTS[key] == int(k or 1):
                    import errno as _e
                    code = int(eno) if eno.isdigit() else getattr(_e, eno or "EIO")
                    raise OSError(code, os.strerror(code) + " (injected by test)")
    spec = os.environ.get("PERCIVAL_TEST_CRASH_AT")
    if not spec:
        return
    for item in spec.split(","):
        n, _, k = item.strip().partition(":")
        if n == name:
            _COUNTS[name] = _COUNTS.get(name, 0) + 1
            if _COUNTS[name] == int(k or 1):
                os.kill(os.getpid(), signal.SIGKILL)
