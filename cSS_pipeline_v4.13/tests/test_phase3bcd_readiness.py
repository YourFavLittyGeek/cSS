"""Phase 3B-3D tests: one-to-one candidate matching (adversarial), deterministic dataset manifests, the single locked patient-level split,
the leakage audit, legacy labels/ tools refused without the research flag, Shadow Lab no longer claims an audit, the 'insufficient data'
training state. Synthetic data only. Isolated (tests/_isolation.py). The end-to-end synthetic training run is in tests/check_percival.py."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import json
import os
import subprocess
import sys
import tempfile
import unittest

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
S = os.path.join(ROOT, "scripts")
for p in (S, os.path.join(ROOT, "app"), os.path.join(ROOT, "unified_engine"), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)
import call_ledger as CL                                                  # noqa: E402
import css_common as CC                                                   # noqa: E402
import review_io as RIO                                                   # noqa: E402
import review_roles as RR                                                 # noqa: E402
from uengine.percival import datasets as DS, split as SP                 # noqa: E402

FP = ["vox_i", "vox_j", "vox_k", "volume_mm3"]


def cands(rows): return pd.DataFrame([dict(cand_id=c, vox_i=i, vox_j=j, vox_k=k, volume_mm3=v, hemi=h) for c, i, j, k, v, h in rows])
def recs(rows): return [dict(vox_i=i, vox_j=j, vox_k=k, volume_mm3=v, hemi=h, call=c) for i, j, k, v, h, c in rows]
def st(d): return [(x["status"], x["cand_id"]) for x in d]


class TestMatcher(unittest.TestCase):
    def test_two_records_competing_for_one_candidate_are_both_unresolved(self):
        C = cands([(1, 10, 10, 10, 30.0, "L")])
        d = CC.match_one_to_one(C, recs([(10, 10, 10, 30.0, "L", "cSS"), (11, 10, 10, 30.0, "L", "cSS")]))
        self.assertEqual(st(d), [("contested", None), ("contested", None)])            # even with identical calls: never merged
        m, dropped = CC.match_calls(C, pd.DataFrame(recs([(10, 10, 10, 30.0, "L", "cSS"), (11, 10, 10, 30.0, "L", "Vessel")])))
        self.assertEqual((m, dropped), ({}, 2))

    def test_one_record_between_two_candidates_is_ambiguous(self):
        C = cands([(1, 10, 10, 10, 30.0, "L"), (2, 11, 10, 10, 30.0, "L")])
        self.assertEqual(st(CC.match_one_to_one(C, recs([(10.5, 10, 10, 30.0, "L", "cSS")]))), [("ambiguous", None)])

    def test_nearby_but_distinguishable_lesions_map_one_to_one(self):
        C = cands([(1, 10, 10, 10, 30.0, "L"), (2, 13, 10, 10, 30.0, "L")])
        self.assertEqual(st(CC.match_one_to_one(C, recs([(10, 10, 10, 30.0, "L", "cSS"), (13, 10, 10, 30.0, "L", "Vessel")]))), [("matched", 1), ("matched", 2)])

    def test_split_merge_disappear_new_and_hemisphere(self):
        C = cands([(1, 10, 10, 10, 14.0, "L"), (2, 12, 10, 10, 14.0, "L"), (3, 40, 40, 10, 60.0, "R"), (4, 70, 70, 10, 20.0, "R")])
        d = CC.match_one_to_one(C, recs([(11, 10, 10, 30.0, "L", "cSS"),             # split: one 30 mm3 lesion -> two 14 mm3 pieces
                                          (40, 40, 10, 30.0, "R", "cSS"), (41, 40, 10, 28.0, "R", "Vessel"),   # merge: two -> one 60 mm3
                                          (90, 90, 10, 20.0, "R", "cSS"),             # disappeared
                                          (70, 70, 10, 20.0, "L", "cSS")]))           # same place, other hemisphere
        self.assertEqual([x["status"] for x in d], ["no_candidate"] * 5)              # all unresolved, never transferred
        self.assertNotIn(4, [x["cand_id"] for x in d])                                # the newly detected #4 inherits nothing

    def test_reordered_candidates_follow_the_lesion(self):
        C = cands([(1, 70, 70, 10, 20.0, "R"), (2, 10, 10, 10, 30.0, "L")])          # numbers swapped after re-detection
        self.assertEqual(st(CC.match_one_to_one(C, recs([(10, 10, 10, 30.0, "L", "cSS"), (70, 70, 10, 20.0, "R", "Vessel")]))), [("matched", 2), ("matched", 1)])

    def test_redetection_after_annotation_keeps_history_and_audit(self):
        b = tempfile.mkdtemp(dir=os.environ["CSS_BASE"]); os.makedirs(os.path.join(b, "review"))
        old = cands([(1, 10, 10, 10, 30.0, "L"), (2, 40, 40, 10, 30.0, "R")])
        old.to_csv(os.path.join(b, "review", "S1_candidates.csv"), index=False)
        rows = [dict(cand_id=c, call=v, comment="", reviewer="Dr A", time="2026-11-24 10:00:00", **old.set_index("cand_id").loc[c, FP].to_dict(), fine_code="", hemi=old.set_index("cand_id").loc[c, "hemi"])
                for c, v in ((1, "cSS"), (2, "Vessel"))]
        p = os.path.join(b, "review", "S1_calls_Dr_A.csv")
        with RIO.study_lock(b, "S1"): RIO.write_table(b, "S1", "Dr A", "calls", p, pd.DataFrame(rows), ["cand_id"] + FP, "call", read_phase="initial", ai_visible=False)
        RR.set_role(b, "Dr A", "expert", "admin", "fixture", RR.CONFIRM_ROLE)
        with RIO.study_lock(b, "S1"): RIO.journal_append(b, "S1", "Dr A", "initial_completed", n_candidates=2, n_called=2)
        cands([(1, 40.5, 40, 10, 31.0, "R"), (2, 10, 10, 10, 30.0, "L"), (3, 39.7, 40, 10, 30.0, "R")]).to_csv(os.path.join(b, "review", "S1_candidates.csv"), index=False)
        E = CL.effective(b, "S1"); s_ = {r["cand_id"]: r for r in E["rows"]}
        self.assertEqual((s_[2]["effective_call"], s_[1]["effective_call"], s_[3]["effective_call"]), ("cSS", "", ""))   # #1 of old -> #2 of new; the R lesion is now ambiguous
        self.assertEqual(E["stale"][0]["match"]["status"], "ambiguous")
        CL.materialize(b, "S1", rescore=False)
        audit = json.load(open(os.path.join(b, "review", "S1_matching.json")))
        self.assertEqual(audit["summary"], {"matched": 1, "ambiguous": 1}); self.assertEqual(audit["unresolved"][0]["call"], "Vessel")


    def test_ledger_never_attaches_two_calls_of_one_file_to_one_candidate(self):
        b = tempfile.mkdtemp(dir=os.environ["CSS_BASE"]); os.makedirs(os.path.join(b, "review"))
        cands([(1, 10, 10, 10, 30.0, "L")]).to_csv(os.path.join(b, "review", "S1_candidates.csv"), index=False)     # after a merge: one object
        pd.DataFrame([dict(cand_id=1, call="cSS", reviewer="Dr A", time="t", vox_i=10, vox_j=10, vox_k=10, volume_mm3=30.0),
                      dict(cand_id=2, call="cSS", reviewer="Dr A", time="t", vox_i=11, vox_j=10, vox_k=10, volume_mm3=30.0)]).to_csv(os.path.join(b, "review", "S1_calls_Dr_A.csv"), index=False)
        hist, stale, _ = CL.ledger(b, "S1")
        self.assertEqual(hist, {}); self.assertEqual(sorted(e["match"]["status"] for e in stale), ["contested", "contested"])


class TestDataset(unittest.TestCase):
    EX = [dict(study="S2", cand_id="missed_3", patient="p2", y=1, label_source="expert_missed_lesion", partition="development", components={"meta": True}, reasons=[], gt_class="verified_blind_post_3A", gt_status="expert_mark"),
          dict(study="S1", cand_id=10, patient="p1", y=0, label_source="review", partition="development", components={"meta": True}, reasons=[], gt_class="verified_blind_post_3A", gt_status="resolved"),
          dict(study="S2", cand_id="missed_12", patient="p2", y=1, label_source="expert_missed_lesion", partition="development", components={"meta": True}, reasons=[], gt_class="historical_blinding_verified", gt_status="expert_mark"),
          dict(study="S1", cand_id=2, patient="p1", y=1, label_source="review", partition="development", components={"meta": True}, reasons=[], gt_class="verified_blind_post_3A", gt_status="resolved")]

    def test_identical_inputs_give_identical_hash_and_order_across_processes(self):
        code = ("import sys, json; sys.path[:0] = %r\nfrom uengine.percival import datasets as DS\nex = json.loads(%r)\n"
                "print(DS.content_hash(sorted(ex, key=DS._cid_sort), 'r', {'S1': {'a': '1'}}, {'version': 'v001'}), [str(e['cand_id']) for e in sorted(ex, key=DS._cid_sort)])"
                % ([os.path.join(ROOT, "unified_engine")], json.dumps(self.EX)))
        outs = {subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=dict(os.environ, PYTHONHASHSEED=str(k))).stdout for k in (1, 2, 3)}
        self.assertEqual(len(outs), 1, outs)                                  # 3C: no hash()-dependent order
        h0 = DS.content_hash(sorted(self.EX, key=DS._cid_sort), "r", {"S1": {"a": "1"}}, {"version": "v001"})
        self.assertNotEqual(h0, DS.content_hash(sorted(self.EX, key=DS._cid_sort), "r", {"S1": {"a": "2"}}, {"version": "v001"}))   # a changed input file
        self.assertNotEqual(h0, DS.content_hash(sorted(self.EX, key=DS._cid_sort), "r", {"S1": {"a": "1"}}, {"version": "v002"}))   # another split

    def test_readiness_refuses_non_eligible_or_non_expert_labels(self):
        self.assertEqual(DS.readiness(self.EX), [])
        bad = [dict(self.EX[1], gt_class="historical_blinding_unknown"), dict(self.EX[3], label_source="model_prediction"), dict(self.EX[0], gt_class="historical_adjudicated")]
        self.assertEqual(len(DS.readiness(bad)), 3)


class TestSplit(unittest.TestCase):
    def setUp(self): self.store = tempfile.mkdtemp(dir=os.environ["CSS_BASE"])

    def test_locked_reproducible_and_versioned(self):
        from uengine.percival.meta import test_assignment
        pats = [f"pt{i:03d}" for i in range(200)]
        parts = {p: SP.partition_of(self.store, p, 0.2) for p in pats}
        self.assertEqual(parts, {p: ("test" if test_assignment(p, 0.2) else "development") for p in pats})     # same rule as before
        S1 = SP.current(self.store); self.assertTrue(S1["locked"]); self.assertEqual(len(S1["additions"]), 200)
        self.assertEqual({p: SP.partition_of(self.store, p, 0.4) for p in pats}, parts)                  # a different fraction changes nothing
        with self.assertRaises(PermissionError): SP.new_version(self.store, 0.1, "me", "smaller test set", "yes")
        S2 = SP.new_version(self.store, 0.1, "me", "smaller test set", SP.CONFIRM_NEW)
        self.assertTrue(all(S2["assignment"][p] == "test" for p, v in parts.items() if v == "test"))     # test patients never move back
        self.assertEqual(S2["version"], "v002"); self.assertTrue(os.path.exists(os.path.join(self.store, "split", "v001.json")))

    def test_app_refuses_fraction_change_once_the_split_exists(self):
        import css_app; css_app.pg_init()
        SP.partition_of(css_app.PG.P(), "pX", 0.2)
        r = css_app.pg_post("settings", dict(percival_test_fraction=0.05)); self.assertFalse(r["ok"]); self.assertIn("locked", r["error"])
        r = css_app.pg_post("split_new_version", dict(fraction=0.3, by="me", reason="r", confirm="no")); self.assertFalse(r["ok"])


class TestReadiness(unittest.TestCase):
    def test_readiness_endpoint_and_training_center_card(self):
        import css_app; css_app.pg_init()
        R = css_app.pg_get("readiness", {})
        names = [c["name"] for c in R["checks"]]
        self.assertFalse(R["ready"])                                          # an empty project is never ready
        for k in ("designated experts", "locked patient-level split", "leakage audit"):
            self.assertTrue(any(k in n for n in names), (k, names))
        self.assertIn("verified_blind_post_3A, historical_blinding_verified", R["policy"])
        js = open(os.path.join(ROOT, "app", "percival_view.js")).read()
        self.assertIn('api("/api/percival/readiness")', js); self.assertIn('data-pv="readiness"', js)


class TestLeakageAudit(unittest.TestCase):
    def e(self, st, cid, pat, part, src="review"): return dict(study=st, cand_id=cid, patient=pat, partition=part, label_source=src, y=1)

    def test_audit(self):
        ok = [self.e("A", 1, "p1", "development"), self.e("B", 1, "p2", "test")]
        self.assertTrue(SP.leakage_audit(ok)["passed"])
        cases = {"patient leakage": ok + [self.e("C", 1, "p1", "test")],
                 "examination leakage": ok + [self.e("C", 1, "p3", "development")],
                 "held out by another split tool": ok,
                 "not from expert review": ok + [self.e("D", 1, "p4", "development", "model")],
                 "without a patient": ok + [self.e("E", 1, None, "development")],
                 "listed twice": ok + [self.e("A", 1, "p1", "development")]}
        for what, ex in cases.items():
            r = SP.leakage_audit(ex, fingerprint_of=(lambda s: "F" if s in ("B", "C") else "") if what == "examination leakage" else None,
                                 held_out={"A"} if what.startswith("held out") else ())
            self.assertFalse(r["passed"], what); self.assertTrue(any(what in x for x in r["errors"]), (what, r["errors"]))


class TestLegacyPathsAndFlags(unittest.TestCase):
    def test_labels_tools_refused_without_the_research_flag(self):
        b = tempfile.mkdtemp(dir=os.environ["CSS_BASE"])
        for cmd in (["train_ranker.py"], ["evaluate.py"], ["classify_surface_patches.py", "train"], ["classify_surface_patches.py", "lopo-manifest", "x.csv"]):
            r = subprocess.run([sys.executable, os.path.join(S, cmd[0])] + cmd[1:], capture_output=True, text=True, env=dict(os.environ, CSS_BASE=b))
            self.assertNotEqual(r.returncode, 0, cmd); self.assertIn("refused", r.stdout + r.stderr, cmd)


    def test_insufficient_data_is_a_valid_training_end_state(self):
        import percival_gui as PG
        self.assertIn("insufficient_data", PG.TRANSITIONS["preparing"]); self.assertIn("insufficient_data", PG.TERMINAL_STATES)


if __name__ == "__main__":
    unittest.main()
