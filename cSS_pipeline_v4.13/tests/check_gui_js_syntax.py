"""check_gui_js_syntax.py - every script of the GUI parses (the inline <script> of css_app.html and every app/*.js), using macOS's built-in
JavaScriptCore (osascript -l JavaScript; Node is not required). A syntax error in one script blanks the whole screen, so this runs in the suite.
usage: python tests/check_gui_js_syntax.py   (exit 1 on any FAIL)"""
import glob, os, re, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); F = []
def check(n, ok, info=""): print(f"{'PASS' if ok else 'FAIL'}  {n}  {info}"); (None if ok else F.append(n))
if sys.platform != "darwin": print("SKIP  not macOS (JavaScriptCore via osascript)"); print("ALL PASS"); sys.exit(0)
t = open(os.path.join(ROOT, "app", "css_app.html")).read()
tmp = tempfile.mkdtemp(); inline = os.path.join(tmp, "inline.js"); open(inline, "w").write("\n".join(re.findall(r"<script>(.*?)</script>", t, re.S)))
rw = os.path.join(tmp, "review_web_inline.js"); open(rw, "w").write("\n".join(re.findall(r"<script>(.*?)</script>", open(os.path.join(ROOT, "scripts", "review_web.html")).read(), re.S)))
for f in [inline, rw] + sorted(glob.glob(os.path.join(ROOT, "app", "*.js"))) + [os.path.join(ROOT, "scripts", "morph3d_view.js")]:
    if not os.path.exists(f): continue
    js = f"var s=$.NSString.stringWithContentsOfFileEncodingError({f!r},4,null).js; try{{new Function(s); 'ok'}}catch(e){{'SYNTAX: '+e}}"
    r = subprocess.run(["osascript", "-l", "JavaScript", "-e", js], capture_output=True, text=True, timeout=60)
    name = "css_app.html inline script" if f == inline else "review_web.html inline script" if f == rw else os.path.relpath(f, ROOT)
    check(f"parses: {name}", r.stdout.strip() == "ok", (r.stdout + r.stderr).strip()[:200])
for js in re.findall(r'<script src="/([\w.]+)"></script>', t):
    check(f"script tag has a file: {js}", os.path.exists(os.path.join(ROOT, "app", js)))
print(("ALL PASS" if not F else f"{len(F)} FAILED: {F}") + f" ({__file__})"); sys.exit(1 if F else 0)
