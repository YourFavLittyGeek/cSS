"""_chrome.py - headless-Chrome harness for the GUI checks (Stage 7).

  * --headless=new with a TEMPORARY profile, no first run, no background networking / component updates / sync / extensions, a mock
    keychain and a basic password store (on macOS a keychain prompt can block a headless Chrome indefinitely - a likely cause of the
    earlier 120 s TimeoutExpired failures)
  * --virtual-time-budget per page, a longer budget and timeout for the first render after the app starts
  * a missing or unusable browser is reported as SKIPPED with the reason - never as passed (exit code SKIP_RC for the runner)
"""
import os
import shutil
import subprocess
import tempfile

SKIP_RC = 77
CANDIDATES = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Chromium.app/Contents/MacOS/Chromium",
              shutil.which("google-chrome") or "", shutil.which("chromium") or "", shutil.which("chromium-browser") or ""]
FLAGS = ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--disable-background-networking",
         "--disable-component-update", "--disable-sync", "--disable-extensions", "--disable-default-apps", "--mute-audio",
         "--use-mock-keychain", "--password-store=basic", "--disable-features=Translate,MediaRouter,OptimizationHints"]
_STATE = {}


def find():
    for c in CANDIDATES:
        if c and os.path.exists(c): return c
    return None


def usable(timeout=90):
    """(ok, reason) - can this computer render a page headlessly? (cached)"""
    if "usable" in _STATE: return _STATE["usable"]
    c = find()
    if not c: _STATE["usable"] = (False, "no Chrome / Chromium found"); return _STATE["usable"]
    prof = tempfile.mkdtemp(prefix="chrome_probe_")
    try:
        r = subprocess.run([c] + FLAGS + [f"--user-data-dir={prof}", "--virtual-time-budget=2000", "--dump-dom", "data:text/html,<p id=ok>ok</p>"],
                           capture_output=True, text=True, timeout=timeout)
        ok = 'id="ok"' in r.stdout
        _STATE["usable"] = (ok, "" if ok else f"headless Chrome rendered nothing (rc {r.returncode})")
    except subprocess.TimeoutExpired:
        _STATE["usable"] = (False, f"headless Chrome did not render a static page within {timeout} s")
    finally: shutil.rmtree(prof, ignore_errors=True)
    return _STATE["usable"]


def dump_dom(url, profile, budget=12000, timeout=180, extra=()):
    """-> (dom or None, reason). One retry with a doubled budget / timeout (first render after app start can be slow)."""
    ok, why = usable()
    if not ok: return None, why
    c = find()
    for b, t in ((budget, timeout), (budget * 2, timeout * 2)):
        try:
            r = subprocess.run([c] + FLAGS + [f"--user-data-dir={profile}", f"--virtual-time-budget={b}", "--enable-logging=stderr", "--v=0", *extra,
                                "--dump-dom", url], capture_output=True, text=True, timeout=t)
            if r.stdout.strip(): return r.stdout, r.stderr
        except subprocess.TimeoutExpired:
            continue
    return None, f"headless Chrome timed out on {url} (budgets {budget}/{budget * 2} ms)"


def screenshot(url, out, profile, w=1500, h=1500, budget=15000, timeout=180):
    ok, why = usable()
    if not ok: return False, why
    try:
        subprocess.run([find()] + FLAGS + [f"--user-data-dir={profile}", "--hide-scrollbars", f"--window-size={w},{h}", f"--virtual-time-budget={budget}",
                        f"--screenshot={out}", url], capture_output=True, timeout=timeout)
        return os.path.exists(out), ""
    except subprocess.TimeoutExpired: return False, "timeout"
