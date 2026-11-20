"""Share / export / backup destinations: explicit, verified local folders only; warning + confirmation before any export (synthetic base)."""
import os, sys, json, glob, socket, tempfile, subprocess, time, urllib.request
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..")); F = []
def ok(c, m): print(("PASS " if c else "FAIL ") + m); c or F.append(m)
HOME = os.path.realpath(tempfile.mkdtemp()); B = os.path.realpath(tempfile.mkdtemp())   # canonical: macOS /var -> /private/var (the app reports real paths)
for d in ("Desktop", "Documents", "Library/Mobile Documents/com~apple~CloudDocs", "Library/CloudStorage/Dropbox", "lab_exports"): os.makedirs(f"{HOME}/{d}")
os.makedirs(f"{B}/app_data"); os.makedirs(f"{B}/review")
sys.path.insert(0, f"{ROOT}/app/guard"); import css_writeguard as WG      # the app's verify_local_dest is css_writeguard.check_dest (rc2)
os.environ["HOME"] = HOME; v = WG.check_dest
for p, want, m in (("", False, "empty"), (f"{HOME}/Desktop", False, "~/Desktop"), (f"{HOME}/Documents/x", False, "inside ~/Documents"),
                   (f"{HOME}/Library/Mobile Documents/com~apple~CloudDocs", False, "iCloud Drive"), (f"{HOME}/Library/CloudStorage/Dropbox", False, "CloudStorage"),
                   (f"{HOME}/nope", False, "missing folder"), (f"{HOME}/lab_exports", True, "local folder")):
    ok(v(p)[0] is want, f"destination {m}: {'accepted' if want else 'refused'} ({v(p)[1]})")
os.symlink(f"{HOME}/Desktop", f"{HOME}/sneaky"); ok(not v(f"{HOME}/sneaky")[0], "a symlink to ~/Desktop is refused (real path checked)")
s_ = socket.socket(); s_.bind(("127.0.0.1", 0)); port = s_.getsockname()[1]; s_.close()
app = subprocess.Popen([sys.executable, f"{ROOT}/app/css_app.py", "--port", str(port), "--no-window"], env=dict(os.environ, HOME=HOME, CSS_BASE=B),
                       stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
U = f"http://127.0.0.1:{port}"
def post(p, d):
    r = urllib.request.Request(U + p, data=json.dumps(d).encode(), headers={"Content-Type": "application/json", "X-CSS-App": "1"})
    return json.load(urllib.request.urlopen(r, timeout=60))
try:
    for _ in range(100):
        try: urllib.request.urlopen(U + "/", timeout=2); break
        except Exception: time.sleep(0.2)
    r = post("/api/share", dict(codes=[])); ok(not r["ok"] and r.get("needs_confirm") and "never uploaded" in r["warning"], "share without confirmation: refused, warning returned")
    r = post("/api/share", dict(codes=[], confirm_clinical=True)); ok(not r["ok"] and "no destination" in r["error"], "share with no export folder chosen: refused (no Desktop fallback)")
    ok(not post("/api/settings", dict(export_dir=f"{HOME}/Desktop"))["ok"], "settings: Desktop refused as export folder")
    ok(not post("/api/settings", dict(backup_dir=f"{HOME}/Library/Mobile Documents/com~apple~CloudDocs"))["ok"], "settings: iCloud refused as backup folder")
    ok(post("/api/settings", dict(export_dir=f"{HOME}/lab_exports")).get("ok", True) is not False, "settings: local folder accepted")
    r = post("/api/share", dict(codes=[], confirm_clinical=True)); ok(r["ok"] and r["path"].startswith(f"{HOME}/lab_exports/"), "confirmed share written to the verified folder only")
    r = post("/api/export", dict(fmt="csv", confirm_clinical=True)); ok(r["ok"] and r["path"].startswith(f"{HOME}/lab_exports/"), "confirmed export written to the verified folder only")
    ok(not os.listdir(f"{HOME}/Desktop"), "nothing written to ~/Desktop")
finally: app.terminate(); app.wait()
print("ALL PASS" if not F else f"{len(F)} FAILED"); sys.exit(1 if F else 0)
