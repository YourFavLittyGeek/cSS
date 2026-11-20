"""Automatic mode: writes review/ID_score_ai.json - the score of the detector's green-band candidates, computed exactly as the
reviewer's "AI score" (review_web.ai_score). NOT validated; the reader's own score files are never touched.
usage: python app/ai_score_cli.py ID"""
import sys, os, json
B = os.environ.get("CSS_BASE", os.path.expanduser("~/css_project")); sys.path.insert(0, os.path.join(B, "scripts"))
import review_web as rw
sid = sys.argv[1]; rw.IDS[:] = [sid]
r = rw.ai_score(rw.study(sid))
print(json.dumps({k: r.get(k) for k in ("L_score", "R_score", "multifocality_0_4", "n_green", "error")}))
sys.exit(1 if r.get("error") else 0)
