"""Local-only verification: (1) static scan - no network library / external host in app, pipeline or scoring code;
(2) runtime - the app, Processing Manager and unified-score app tests run with every non-loopback connection blocked and logged."""
import os, re, sys, glob, subprocess, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..")); F = []
def ok(c, m): print(("PASS " if c else "FAIL ") + m); c or F.append(m)
ALLOWED = {"scripts/run_lemon.sh"}       # optional public-dataset downloader (OpenNeuro LEMON); sends no local data, never called by the app
files = [p for d in ("app", "scripts", "unified_score") for p in glob.glob(f"{ROOT}/{d}/**/*", recursive=True)
         if p.endswith((".py", ".sh", ".js", ".html", ".command")) and "/mac/" not in p]
bad = []
for p in files:
    rel = os.path.relpath(p, ROOT); t = open(p, errors="replace").read()
    if rel in ALLOWED: continue
    if re.search(r"\bimport (requests|httpx|urllib3|aiohttp|smtplib|ftplib|paramiko)\b|http\.client|urllib\.request|\bcurl\b|\bwget\b", t) and "tests/" not in rel:
        bad.append(rel + ": network library")
    for u in re.findall(r"https?://([A-Za-z0-9.\-]+)", t):
        if u not in ("127.0.0.1", "localhost", "www.w3.org", "schemas.openxmlformats.org", "purl.org", "schemas.microsoft.com"): bad.append(f"{rel}: {u}")
    if re.search(r"<script[^>]+src=[\"']https?:", t): bad.append(rel + ": external script")
ok(not bad, "static scan: no network code or external host" + ("" if not bad else " -> " + "; ".join(sorted(set(bad))[:10])))
ok(all(re.search(r'ThreadingHTTPServer\(\("127\.0\.0\.1"', open(f"{ROOT}/{p}").read()) for p in ("app/css_app.py", "scripts/review_web.py")), "servers bind to 127.0.0.1 only")
log = tempfile.mktemp(); env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "tests", "netguard") + os.pathsep + os.environ.get("PYTHONPATH", ""), CSS_NETGUARD_LOG=log)
for t in ("check_processing_manager.py", "check_app_unified.py"):
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tests", t)], env=env, capture_output=True, text=True, timeout=3000)
    ok(r.returncode == 0, f"{t} passes with the network blocked")
ok(not os.path.exists(log) or not open(log).read().strip(), "no process attempted a non-loopback connection" + ("" if not os.path.exists(log) else ": " + open(log).read()[:300]))
sys.path.insert(0, f"{ROOT}/app")
sys.path.insert(0, f"{ROOT}/app/guard"); import css_writeguard as WG
ok(not WG.check_dest("~/Library/Mobile Documents/com~apple~CloudDocs")[0] and not WG.check_dest("/Users/x/Dropbox")[0] and WG.check_dest(tempfile.mkdtemp())[0], "backup refused in cloud-synced folders, allowed on a local disk")
print("ALL PASS" if not F else f"{len(F)} FAILED"); sys.exit(1 if F else 0)
