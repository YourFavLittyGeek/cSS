"""I0 safety review: (1) the separate experimental uScore scorer cannot train on labels that bypass the Phase 3A provenance / eligibility
gates, while x1-x5 feature extraction (an input of the Percival Score) keeps working; (2) the label / review-state / gather caches are keyed
by file CONTENT: a source rewritten within the same clock tick (same size, same mtime) is never mistaken for the unchanged file, unchanged
content reuses the cache, and dataset reproducibility detects the change. Synthetic data only. Isolated (tests/_isolation.py)."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
S = os.path.join(ROOT, "scripts")
for p in (S, os.path.join(ROOT, "app"), os.path.join(ROOT, "unified_engine"), os.path.join(ROOT, "unified_score"), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)
import review_io as RIO                                                   # noqa: E402
import review_roles as RR                                                 # noqa: E402

FP = ["vox_i", "vox_j", "vox_k", "volume_mm3"]
COLS = ["cand_id", "call", "comment", "reviewer", "time"] + FP + ["fine_code"]


def same_stat_rewrite(path, text):
    """rewrite a file with content of the SAME size and restore the exact nanosecond mtime (what a rewrite inside one clock tick looks like)"""
    st = os.stat(path); assert len(text.encode()) == st.st_size, (len(text.encode()), st.st_size)
    with open(path, "w") as f: f.write(text)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert os.stat(path).st_mtime_ns == st.st_mtime_ns and os.stat(path).st_size == st.st_size


# ---------------------------------------------------------------------------------------------------------------- 1 uScore training gate
class TestUScoreTrainingGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import uscore_synthbase as sb
        from uscore import common as cm, pipeline as pl
        cls.cm, cls.pl = cm, pl
        cls.B = tempfile.mkdtemp(prefix="i0_us_", dir=os.environ["CSS_BASE"])
        cls.man = sb.write_base(cls.B, n_dev=4, n_ho=2)
        cls.C = cm.Cohort(cls.man, eligible_prefix="SYN", synthetic_test=True)
        cls.out = os.path.join(cls.B, "uscore")
        for s in cls.C.studies("development") + cls.C.studies("held-out"): pl.extract_study(cls.B, s, cls.C, cls.out, do_perturb=False)

    def test_fixture_labels_are_ineligible(self):
        # the synthetic base carries a shared ID_calls.csv with no reviewer, no designated expert, no journal -> not Phase 3A ground truth
        import call_ledger as CL
        sid = self.C.studies("development")[0]
        self.assertTrue(os.path.exists(os.path.join(self.B, "review", f"{sid}_calls.csv")))
        rows = CL.effective(self.B, sid)["rows"]
        self.assertFalse(any(r.get("primary_eligible") for r in rows))

    def test_train_refused_before_any_label_is_read_and_nothing_written(self):
        seen = []; real = self.cm._read_calls
        self.cm._read_calls = lambda base, sid, tab: (seen.append(sid), real(base, sid, tab))[1]
        try:
            out = os.path.join(self.B, "uscore_refused")
            with self.assertRaises(self.pl.TrainingDisabled) as e: self.pl.train(self.B, self.C, out)
            self.assertIn("DISABLED", str(e.exception))
            self.assertEqual(seen, [])                                               # no label crossed the boundary
            self.assertFalse(os.path.exists(os.path.join(out, "model_trained.json")))
            self.assertFalse(os.path.exists(os.path.join(out, "development_report.json")))
        finally: self.cm._read_calls = real

    def test_cli_refused_without_the_flag(self):
        env = dict(os.environ, CSS_BASE=self.B, CSS_USCORE_DEMO="1", CSS_USCORE_MANIFEST=self.man)
        out = os.path.join(self.B, "uscore_cli")
        r = subprocess.run([sys.executable, os.path.join(ROOT, "unified_score", "run_unified.py"), "train", "--out", out], env=env,
                           capture_output=True, text=True, timeout=300)
        self.assertNotEqual(r.returncode, 0); self.assertIn("REFUSED", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(out, "model_trained.json")))

    def test_app_entry_refused_without_starting_a_job(self):
        os.environ["CSS_BASE"] = self.B
        import unified_gui as UG
        r = UG.train()
        self.assertEqual((r["ok"], r["disabled"]), (False, True)); self.assertIn("DISABLED", r["error"])
        self.assertEqual(UG.job("train").get("status"), "idle")

    def test_research_run_is_stamped_and_hash_consistent(self):
        from uscore import model as md
        out = self.out                                                               # the folder holding the extracted features
        M, _ = self.pl.train(self.B, self.C, out, research_unverified=True)
        F = json.load(open(os.path.join(out, "model_trained.json")))
        self.assertTrue(F["research_only_unverified"]); self.assertIn("NOT Phase 3A", F["label_provenance"])
        self.assertEqual(md.model_hash(F), F["model_hash"])                         # the held-out boundary recomputes this hash

    def test_feature_extraction_still_works(self):
        sid = self.C.studies("development")[0]
        F = json.load(open(os.path.join(self.out, "features", f"{sid}.json")))
        self.assertEqual(len(F["records"]), 4)
        from uengine.percival.meta import PREDICTORS
        self.assertTrue(all(k in F["records"][0]["F"] for k in PREDICTORS))      # x1-x5 present: the Percival 'unified' component input

    def test_only_entry_to_uscore_training_is_the_flagged_cli(self):
        # source tree only: frozen app bundles / release snapshots (*.app/Contents, docs/gui_v514/*/dist) are reported separately
        callers = []
        for f in glob.glob(os.path.join(ROOT, "**", "*.py"), recursive=True):
            r = os.path.relpath(f, ROOT)
            if r.startswith(("tests" + os.sep, "docs" + os.sep)) or ".app" + os.sep + "Contents" in r or "__pycache__" in r: continue
            t = open(f, errors="ignore").read()
            for m in re.finditer(r"\bpl\.train\(|pipeline\.train\(|PL\.train\(|_cli\(\"train\", \[\"train\"", t): callers.append((r, m.group(0)))
        self.assertEqual(sorted(set(callers)), [("unified_score/run_unified.py", "pl.train(")], callers)
        src = open(os.path.join(ROOT, "unified_score", "run_unified.py")).read()
        self.assertRegex(src, r'if "--research-unverified" not in rest: sys\.exit')


# ---------------------------------------------------------------------------------------------------------------- 2 content-keyed caches
class TestContentKeyedCaches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import css_app; css_app.pg_init(); cls.PG = css_app.PG; cls.B = css_app.B
        cls.sid = "CK1"; rd = os.path.join(cls.B, "review"); os.makedirs(rd, exist_ok=True)
        cls.cand = pd.DataFrame([dict(cand_id=i, vox_i=10 * i, vox_j=5, vox_k=5, volume_mm3=20.0 + i) for i in range(1, 5)])
        cls.cand.to_csv(os.path.join(rd, f"{cls.sid}_candidates.csv"), index=False)
        for rev, calls in (("Exp One", {1: "cSS", 2: "Vessel"}), ("Exp Two", {1: "cSS", 2: "Vessel"})):
            rows = [dict(cand_id=c, call=v, comment="", reviewer=rev, time="2026-11-24 10:00:00", **cls.cand.set_index("cand_id").loc[c, FP].to_dict(), fine_code="")
                    for c, v in calls.items()]
            p = os.path.join(rd, f"{cls.sid}_calls_{RR.slug(rev)}.csv")
            with RIO.study_lock(cls.B, cls.sid):
                RIO.write_table(cls.B, cls.sid, rev, "calls", p, pd.DataFrame(rows, columns=COLS), ["cand_id"] + FP, "call", read_phase="initial", ai_visible=False)
        for n in ("Exp One", "Exp Two"):
            RR.set_role(cls.B, n, "expert", "admin", "fixture", RR.CONFIRM_ROLE)
            with RIO.study_lock(cls.B, cls.sid): RIO.journal_append(cls.B, cls.sid, n, "initial_completed", n_candidates=0, n_called=0)
        cls.calls = os.path.join(rd, f"{cls.sid}_calls_{RR.slug('Exp Two')}.csv")

    def setUp(self):
        self.PG._LCACHE.clear()

    def test_1_unchanged_content_reuses_the_cache(self):
        a = self.PG.label_summary(self.sid); self.assertEqual(a["labels"], {1: 1, 2: 0})
        self.assertIs(self.PG.label_summary(self.sid), a)                          # same object: cache hit
        os.utime(self.calls)                                                         # touched, content unchanged -> still valid
        self.assertIs(self.PG.label_summary(self.sid), a)

    def test_2_same_size_same_mtime_rewrite_is_detected(self):
        a = self.PG.label_summary(self.sid); orig = open(self.calls).read()
        try:
            same_stat_rewrite(self.calls, orig.replace("Vessel", "Normal"))        # same length, same nanosecond mtime
            b = self.PG.label_summary(self.sid)
            self.assertIsNot(b, a)
            self.assertNotEqual(b["labels"], a["labels"])                           # file differs from its journal -> withheld (repair)
        finally:
            same_stat_rewrite(self.calls, orig)
        self.assertEqual(self.PG.label_summary(self.sid)["labels"], {1: 1, 2: 0})

    def test_3_rapid_successive_rewrites_are_each_detected(self):
        orig = open(self.calls).read(); alt = orig.replace("Vessel", "Normal"); seen = []
        try:
            for i in range(12):
                same_stat_rewrite(self.calls, alt if i % 2 == 0 else orig)
                seen.append(self.PG.label_summary(self.sid)["labels"])
        finally: same_stat_rewrite(self.calls, orig)
        self.assertEqual([x == {1: 1, 2: 0} for x in seen], [i % 2 == 1 for i in range(12)])

    def test_4_role_revocation_invalidates_the_cache(self):
        self.assertEqual(self.PG.label_summary(self.sid)["labels"], {1: 1, 2: 0})
        try:
            RR.set_role(self.B, "Exp Two", "trainee", "admin", "fixture: revoke", RR.CONFIRM_ROLE)
            self.assertEqual(self.PG.label_summary(self.sid)["labels"], {1: 1, 2: 0}, "Exp One alone still resolves (quorum 1)")
            RR.set_role(self.B, "Exp One", "trainee", "admin", "fixture: revoke", RR.CONFIRM_ROLE)
            self.assertEqual(self.PG.label_summary(self.sid)["labels"], {}, "no designated expert left -> no labels")
        finally:
            for n in ("Exp One", "Exp Two"): RR.set_role(self.B, n, "expert", "admin", "fixture: restore", RR.CONFIRM_ROLE)
        self.assertEqual(self.PG.label_summary(self.sid)["labels"], {1: 1, 2: 0})

    def test_5_review_state_cache_detects_same_stat_rewrite_and_roles(self):
        import review_calls_gui as RCG
        k0 = RCG._key(self.B, self.sid, ""); orig = open(self.calls).read()
        try:
            same_stat_rewrite(self.calls, orig.replace("Vessel", "Normal")); self.assertNotEqual(RCG._key(self.B, self.sid, ""), k0)
        finally: same_stat_rewrite(self.calls, orig)
        self.assertEqual(RCG._key(self.B, self.sid, ""), k0)
        try:
            RR.set_role(self.B, "Exp Two", "trainee", "admin", "fixture", RR.CONFIRM_ROLE); self.assertNotEqual(RCG._key(self.B, self.sid, ""), k0)
        finally: RR.set_role(self.B, "Exp Two", "expert", "admin", "fixture: restore", RR.CONFIRM_ROLE)

    def test_6_gather_cache_rebuilds_on_same_stat_candidate_rewrite(self):
        cp = os.path.join(self.B, "review", f"{self.sid}_candidates.csv"); orig = open(cp).read()
        k0 = json.load(open(self.PG.P("cache", f"{self.sid}.json")))["key"] if self.PG.gather(self.sid, labelled=False) is not None else None
        try:
            same_stat_rewrite(cp, orig.replace("21.0", "29.0"))
            self.PG.gather(self.sid, labelled=False)
            C = json.load(open(self.PG.P("cache", f"{self.sid}.json")))
            self.assertNotEqual(C["key"], k0)
        finally: same_stat_rewrite(cp, orig)
        self.PG.gather(self.sid, labelled=False)
        self.assertEqual(json.load(open(self.PG.P("cache", f"{self.sid}.json")))["key"], k0)   # deterministic: same content -> same key

    def test_7_dataset_reproducibility_detects_the_same_stat_rewrite(self):
        from uengine.percival import datasets as DS, eligibility as EL
        meta = dict(excluded=False, archived_out=False)
        ex = self.PG._examples(self.sid, meta); src = {self.sid: self.PG._sources(self.sid)}
        h1 = DS.content_hash(sorted(ex, key=DS._cid_sort), EL.RULES_VERSION, src)
        self.PG._LCACHE.clear()
        h2 = DS.content_hash(sorted(self.PG._examples(self.sid, meta), key=DS._cid_sort), EL.RULES_VERSION, {self.sid: self.PG._sources(self.sid)})
        self.assertEqual(h1, h2)                                                     # deterministic for unchanged inputs
        m = DS.build(ex, EL.RULES_VERSION, self.PG.P(), sources=src)
        self.assertTrue(DS.reproduce(self.PG.P(), m["id"], self.PG._examples(self.sid, meta), EL.RULES_VERSION, sources=src)["identical"])
        orig = open(self.calls).read()
        try:
            same_stat_rewrite(self.calls, orig.replace("Vessel", "Normal"))
            now = {self.sid: self.PG._sources(self.sid)}
            R = DS.reproduce(self.PG.P(), m["id"], self.PG._examples(self.sid, meta), EL.RULES_VERSION, sources=now)
            self.assertFalse(R["identical"])
            self.assertTrue(R["changes"] and R["n_differences"] >= 1, R["changes"])   # labels withheld (file differs from journal)
            self.assertNotEqual(now[self.sid], src[self.sid])                        # source-file hash differs too
        finally: same_stat_rewrite(self.calls, orig)


if __name__ == "__main__":
    unittest.main()
