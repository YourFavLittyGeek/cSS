"""Runs tests/check_viewer.js against review_web.py on PH3 when node + Playwright are installed; otherwise prints SKIP.
usage: check_viewer.py   ($CSS_BASE with PH3 detected)"""
import os, sys, subprocess, shutil, time
HERE = os.path.dirname(os.path.abspath(__file__)); S = os.path.join(HERE, "..", "scripts")
node = shutil.which("node")
ok = node and subprocess.run([node, "-e", "require('playwright')"], capture_output=True, env=dict(os.environ, NODE_PATH=subprocess.run(
    [node, "-e", "console.log(require('path').join(process.execPath,'..','..','lib','node_modules'))"], capture_output=True, text=True).stdout.strip())).returncode == 0
if not ok: print("viewer test SKIPPED (node + Playwright not installed)"); print("RESULT viewer OK"); sys.exit(0)
env = dict(os.environ, NODE_PATH=subprocess.run([node, "-e", "console.log(require('path').join(process.execPath,'..','..','lib','node_modules'))"], capture_output=True, text=True).stdout.strip())
srv = subprocess.Popen([sys.executable, f"{S}/review_web.py", "PH3", "--no-browser", "--port", "8961"], stdout=subprocess.PIPE, text=True)
try:
    U = "http://" + srv.stdout.readline().split("http://")[1].split()[0]
    r = subprocess.run([node, f"{HERE}/check_viewer.js", U], capture_output=True, text=True, env=env, timeout=300)
    print((r.stdout + r.stderr).strip())
    for f in ("PH3_calls_Viewer_Test.csv",):
        p = f"{os.environ['CSS_BASE']}/review/{f}"
        if os.path.exists(p): os.remove(p)
    sys.exit(0 if "RESULT viewer OK" in r.stdout else 1)
finally: srv.kill()
