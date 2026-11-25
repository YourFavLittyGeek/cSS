"""2026-11-25 reviewer 'After the final save': next patient immediately / after N typed seconds / manual (node, no project)."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import json
import os
import re
import shutil
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HTML = os.path.join(os.path.dirname(HERE), "scripts", "review_web.html")
NODE = shutil.which("node")


def grab(src, start):
    """source of one top-level function / const line starting with `start`"""
    i = src.index(start)
    if start.startswith("const "):
        return src[i:src.index("\n", i)]
    depth, j = 0, src.index("{", i)
    for k in range(j, len(src)):
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        if depth == 0:
            return src[i:k + 1]


@unittest.skipIf(NODE is None, "node is not installed")
class TestNextPatient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        src = open(HTML).read()
        cls.js = "\n".join([grab(src, "const clampSec="), grab(src, "const afMode="), grab(src, "function setAfter(")])
        cls.next_card = grab(src, "function nextCard(")

    def run_js(self, body):
        code = ("let autoPt=true,autoSec=10;const store={};const LSS=(k,v)=>store[k]=v;const $=()=>null;\n" + self.js +
                "\nconst out=(()=>{" + body + "})();process.stdout.write(JSON.stringify(out));")
        r = subprocess.run([NODE, "-e", code], capture_output=True, text=True, timeout=30)
        if r.returncode:
            raise RuntimeError(r.stderr)
        return json.loads(r.stdout)

    def test_modes_map_to_the_stored_keys(self):
        self.assertEqual(self.run_js('setAfter("now",5);return [autoPt,autoSec,store,afMode()]'),
                         [True, 0, {"autopt": True, "autosec": 0}, "now"])
        self.assertEqual(self.run_js('setAfter("after",45);return [autoPt,autoSec,afMode()]'), [True, 45, "after"])
        self.assertEqual(self.run_js('setAfter("manual",45);return [autoPt,afMode()]'), [False, "manual"])

    def test_typed_seconds_are_clamped(self):
        self.assertEqual(self.run_js('setAfter("after","7.6");return autoSec'), 8)
        self.assertEqual(self.run_js('setAfter("after",99999);return autoSec'), 600)
        self.assertEqual(self.run_js('setAfter("after","abc");return autoSec'), 10)    # nonsense -> the old default
        self.assertEqual(self.run_js('setAfter("after",0);return [autoSec,afMode()]'), [10, "after"])

    def test_countdown_has_no_hidden_10_second_fallback(self):
        self.assertNotIn("autoSec||10", self.next_card)                    # 0 s used to become 10 s inside the card
        self.assertIn("if(autoPt&&left<=0){go2();return}", self.next_card)

    def test_app_dialog_offers_the_three_choices(self):
        app = open(os.path.join(os.path.dirname(HERE), "app", "css_app.html")).read()
        dlg = grab(app, "async function vsetDlg(")
        for t in ('value="now"', 'value="after"', 'value="manual"', 'id="vsAfSec"'):
            self.assertIn(t, dlg)
        self.assertNotIn("Close the summary after", dlg)
        self.assertNotIn("Close the summary after", open(HTML).read())


if __name__ == "__main__":
    unittest.main()
