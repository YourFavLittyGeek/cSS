"""2026-11-25 identity on the reviewer image (bottom right, under the reviewer name, yellow): Standard with the vault readable = patient
name, MRN, accession; Incognito or locked = study code only; saved snapshots never carry the identifiers. App side (viewer_ident), the
reviewer server (asks the app live, passes only the known keys, falls back to the study code) and the page (identLines, node).
Synthetic values only. Isolated (tests/_isolation.py)."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import json
import os
import shutil
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "app"), os.path.join(ROOT, "scripts"), os.path.join(ROOT, "unified_engine")):
    if p not in sys.path: sys.path.insert(0, p)
HTML = os.path.join(ROOT, "scripts", "review_web.html")
NODE = shutil.which("node")
STD = dict(deid_code="Study-901", patient_name="TEST^PATIENT", mrn="000111", accession="ACC123")


def grab(src, start):
    i = src.index(start); depth, j = 0, src.index("{", i)
    for k in range(j, len(src)):
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        if depth == 0: return src[i:k + 1]


class TestAppSide(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import css_app
        cls.A = css_app

    def test_standard_incognito_locked(self):
        A = self.A
        with mock.patch.object(A.IDG, "mode", return_value="standard"), mock.patch.object(A.IDG, "ident", return_value=dict(STD)):
            self.assertEqual(A.viewer_ident("K1"), dict(mode="standard", code="Study-901", name="TEST^PATIENT", mrn="000111", accession="ACC123"))
        with mock.patch.object(A.IDG, "mode", return_value="incognito"), mock.patch.object(A.IDG, "ident", return_value=dict(deid_code="Study-901", study_id="Study-901")):
            self.assertEqual(A.viewer_ident("K1"), dict(mode="incognito", code="Study-901"))
        with mock.patch.object(A.IDG, "mode", return_value="standard"), mock.patch.object(A.IDG, "ident", return_value=dict(deid_code="Study-901", locked=True)):
            self.assertEqual(A.viewer_ident("K1"), dict(mode="locked", code="Study-901"))
        with mock.patch.object(A.IDG, "ident", side_effect=RuntimeError("x")):
            self.assertEqual(A.viewer_ident("K1"), dict(mode="incognito", code="K1"))


class TestReviewerServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import review_web as RW
        cls.RW = RW
        reply = {"d": {}}
        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                b = json.dumps(reply["d"]).encode(); self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
            def log_message(self, *a): pass
        cls.reply = reply; cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls): cls.srv.shutdown()

    def test_route_is_classified(self):
        self.assertEqual(self.RW.ROUTES[("GET", "/api/ident")], "settings")

    def test_only_known_keys_and_fallbacks(self):
        RW = self.RW; port = str(self.srv.server_address[1])
        self.reply["d"] = dict(mode="standard", code="Study-901", name="TEST^PATIENT", mrn="000111", accession="ACC123", extra="never passed on")
        with mock.patch.dict(os.environ, {"CSS_APP_PORT": port}):
            self.assertEqual(RW.viewer_ident("K1"), dict(mode="standard", code="Study-901", name="TEST^PATIENT", mrn="000111", accession="ACC123"))
            self.reply["d"] = dict(mode="incognito", code="Study-901", name="TEST^PATIENT")
            self.assertEqual(RW.viewer_ident("K1"), dict(mode="incognito", code="Study-901"))      # Incognito: identifiers dropped even if sent
        with mock.patch.dict(os.environ, {"CSS_APP_PORT": ""}):
            self.assertEqual(RW.viewer_ident("K1"), dict(mode="incognito", code="K1"))             # no app: the study code
        with mock.patch.dict(os.environ, {"CSS_APP_PORT": "1"}):
            self.assertEqual(RW.viewer_ident("K1"), dict(mode="incognito", code="K1"))             # app not reachable


@unittest.skipIf(NODE is None, "node is not installed")
class TestPage(unittest.TestCase):
    def lines(self, ident, live):
        src = open(HTML).read()
        code = (f"let M={{study:'K1'}};let IDENT={{K1:{json.dumps(ident)}}};\n" + grab(src, "function identLines(") +
                f"\nprocess.stdout.write(JSON.stringify(identLines({'true' if live else 'false'})));")
        r = subprocess.run([NODE, "-e", code], capture_output=True, text=True, timeout=30)
        if r.returncode: raise RuntimeError(r.stderr)
        return json.loads(r.stdout)

    def test_lines(self):
        std = dict(mode="standard", code="Study-901", name="TEST^PATIENT", mrn="000111", accession="ACC123")
        self.assertEqual(self.lines(std, True), ["TEST^PATIENT · MRN 000111", "Acc ACC123"])
        self.assertEqual(self.lines(std, False), ["Study Study-901"])                                # snapshot: never the identifiers
        self.assertEqual(self.lines(dict(mode="incognito", code="Study-901"), True), ["Study Study-901"])
        self.assertEqual(self.lines(dict(std, accession=""), True), ["TEST^PATIENT · MRN 000111", "Acc (none)"])

    def test_snapshots_draw_not_live_and_top_left_uses_the_code(self):
        src = open(HTML).read()
        self.assertIn("live:false", grab(src, "function snapCanvas("))
        self.assertIn("identLines(o.live)", src)
        self.assertIn("o.live?studyLabel(M.study):M.study", src)


if __name__ == "__main__":
    unittest.main()
