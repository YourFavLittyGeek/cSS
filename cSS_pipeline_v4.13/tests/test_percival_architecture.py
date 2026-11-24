"""PERCIVAL architecture integration tests (synthetic data only; isolated - tests/_isolation.py):
LUMOS = the trained Percival CNN (honest 'untrained' otherwise); the candidate contract (explicit states, missing never negative, no patient
id, CORE separate, pairwise disagreement); component version records + report; PENSIEVE per-project index (reproducible digest, idempotent,
no duplicates on repeated reviewer saves, blind provenance kept, expert vs prediction separation, false positives attributed to the ALBUS
detector version, failures recorded not swallowed, legacy DB per project); SHADOW governance (development only, locked discovery /
confirmation patients, label-like variables refused, PERCIVAL-only one-shot confirmation, no self-approval, synthetic evidence stamped,
versioned approval + rollback); ALBUS detection framework (sensitivity includes expert-marked missed lesions, non-inferiority gate)."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__))); import _isolation; _isolation.activate()  # Phase 0: test isolation (must stay first)
import json
import os
import sqlite3
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
S = os.path.join(ROOT, "scripts")
for p in (S, os.path.join(ROOT, "app"), os.path.join(ROOT, "unified_engine"), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)
import review_io as RIO                                                   # noqa: E402
import review_roles as RR                                                 # noqa: E402
from uengine.percival import architecture as AR, component_registry as CR  # noqa: E402
from uengine import pensieve_index as PI, shadow_governed as SG, albus_detection as AD  # noqa: E402

FP = ["vox_i", "vox_j", "vox_k", "volume_mm3"]
COLS = ["cand_id", "call", "comment", "reviewer", "time"] + FP + ["fine_code"]


def project(n=4, sid="S1"):
    b = tempfile.mkdtemp(prefix="arch_", dir=os.environ["CSS_BASE"])
    for d in ("review", "home", "percival"): os.makedirs(os.path.join(b, d), exist_ok=True)
    cand = pd.DataFrame([dict(cand_id=i, hemi="L" if i % 2 else "R", vox_i=10 * i, vox_j=5, vox_k=5, volume_mm3=20.0 + i, darkness_z=-2.0 - i,
                              score_v4=1.0 + i / 10) for i in range(1, n + 1)])
    cand.to_csv(os.path.join(b, "review", f"{sid}_candidates.csv"), index=False)
    json.dump(dict(build="abc123def456", detect=dict(pipeline_version="v4.18", parameters=dict(z_thr=-2.5), anatomy="T1", run_at="2026-11-24T10:00:00")),
              open(os.path.join(b, "review", f"{sid}_manifest.json"), "w"))
    return b, cand


def write(b, cand, rev, calls, sid="S1", phase="initial", vis=False):
    rows = [dict(cand_id=c, call=v, comment="", reviewer=rev, time=f"2026-11-24 10:00:{c:02d}", **cand.set_index("cand_id").loc[c, FP].to_dict(), fine_code="")
            for c, v in calls.items()]
    p = os.path.join(b, "review", f"{sid}_calls_{RR.slug(rev)}.csv")
    with RIO.study_lock(b, sid):
        RIO.ensure_table(b, sid, rev, "calls", p)
        RIO.write_table(b, sid, rev, "calls", p, pd.DataFrame(rows, columns=COLS), ["cand_id"] + FP, "call", read_phase=phase, ai_visible=vis)


def experts(b, *names, sid="S1"):
    for n in names:
        RR.set_role(b, n, "expert", "admin", "fixture", RR.CONFIRM_ROLE)
        with RIO.study_lock(b, sid): RIO.journal_append(b, sid, n, "initial_completed", n_candidates=0, n_called=0)


def missed(b, rev, mid=1, sid="S1", phase="initial", vis="False"):
    pd.DataFrame([dict(missed_id=mid, reviewer=rev, time="t", vox_i=3, vox_j=3, vox_k=3, x_mm=3, y_mm=3, z_mm=3, can_i=3, can_j=3, can_k=3, comment="",
                       plane="axial", slice=3, shape="point", points="[]", detector_fate="not generated", context="", read_phase=phase, ai_visible=vis,
                       source="reviewer")]).to_csv(os.path.join(b, "review", f"{sid}_missed.csv"), index=False)


def tiny_model(with_image=True, version="v001"):
    from uengine.percival.cnn import SmallCNN
    comps = dict(kinds=dict(char="logistic", image="cnn", fusion="feature"), math=dict(a=0.1, b=1.0, eps=1e-3), unified=None, char=dict(x=1), fusion=dict(x=2),
                 image=SmallCNN(3).to_json() if with_image else None)
    return dict(version=version, components=comps, meta=dict(kind="stack_logit"), calibration=dict(a=0.0, b=1.0), data=dict(dataset="ds001"),
                intelligence=dict(disagreement=[dict(a="math", b="image", patterns=dict(both_high=dict(n=10, css_rate=0.8, ci=[0.5, 0.9]),
                                                                                        both_low=dict(n=20, css_rate=0.05, ci=[0, 0.2]),
                                                                                        math_only=dict(n=5, css_rate=0.4, ci=[0.1, 0.8]),
                                                                                        image_only=dict(n=4, css_rate=0.5, ci=[0.2, 0.8])))]),
                component_metrics=dict(math=dict(auc=0.7), char=dict(auc=0.6), unified=None, image=dict(auc=0.65), fusion=dict(auc=0.66)))


# ------------------------------------------------------------------------------------------------------------------------------- LUMOS
class TestLumos(unittest.TestCase):
    def patch(self):
        sw = np.ones((49, 25, 16), np.float32); sw[:, :, 8:] = 0.2
        return {"image_swi": sw, "valid_swi": np.ones(sw.shape, bool), "object_mask": sw < 0.5}

    def test_untrained_lumos_never_reports_a_probability(self):
        from uengine.lumos import LumosImageIntelligence
        L = LumosImageIntelligence.from_percival_model(None)
        r = L.analyze_patch("S1", 1, self.patch())
        self.assertEqual((r.status, r.prob, r.has_visual_evidence), ("untrained", None, False))
        self.assertGreater(r.depth_gradient, 0.4)                                   # measurements still reported

    def test_lumos_uses_the_registry_cnn_weights(self):
        from uengine.lumos import LumosImageIntelligence
        from uengine.percival.learners import image_model_from
        M = tiny_model(); L = LumosImageIntelligence.from_percival_model(M)
        self.assertEqual((L.checkpoint_status, L.version), ("registry_trained", "lumos@v001"))
        ref = image_model_from(M["components"]["image"])
        self.assertTrue(all(np.array_equal(L.net.p[k], ref.p[k]) for k in ref.p))   # the SAME weights, no second network
        r = L.analyze_patch("S1", 1, self.patch()); self.assertEqual(r.status, "ok"); self.assertIsNotNone(r.prob)

    def test_model_without_image_network_is_untrained(self):
        self.assertEqual(AR.lumos_state(tiny_model(with_image=False))["state"], "untrained")
        self.assertEqual(AR.lumos_state(None)["state"], "untrained")


# -------------------------------------------------------------------------------------------------------------------- contract / report
class TestContract(unittest.TestCase):
    def test_states_missing_never_negative_no_patient_core_separate(self):
        M = tiny_model()
        scored = dict(cand_id=3, percival_score=72.0, band="green", status="reliable", components=dict(math=80.0, char=None, unified=None, image=70.0, fusion=None),
                      experimental_core=dict(score=40, band="Gray", status="ok"))
        row = dict(math=1.3, char={"darkness_z": -2.5, "tube_ratio": None}, pred={}, maps=np.zeros(2), patient="PATIENT-SECRET")
        c = AR.candidate_contract("S1", scored, row, M, dict(state="valid", version="albus:v4.18:x:y"))
        self.assertEqual(c["nox"]["predictors_x1_x5"]["state"], "missing"); self.assertIsNone(c["nox"]["predictors_x1_x5"]["component_pct"])
        self.assertEqual(c["nox"]["measurements"]["n_available"], 1)
        self.assertEqual((c["lumos"]["state"], c["lumos"]["component_pct"]), ("valid", 70.0))
        self.assertNotIn("PATIENT-SECRET", json.dumps(c, default=str))
        self.assertEqual(c["core"]["role"], "comparison only - never the PERCIVAL prediction"); self.assertEqual(c["percival"]["score"], 72.0)
        pw = {p["pair"]: p for p in c["percival"]["pairwise"]}
        self.assertEqual(len(pw), 1); p = list(pw.values())[0]
        self.assertEqual((p["pattern"], p["css_rate"], p["agree"]), ("both_high", 0.8, True))
        c2 = AR.candidate_contract("S1", scored, row, tiny_model(with_image=False))          # untrained LUMOS: its number is never shown
        self.assertEqual((c2["lumos"]["state"], c2["lumos"]["component_pct"]), ("untrained", None))
        self.assertIn("patient", AR.candidate_contract("S1", scored, row, M, include_patient=True)["identity"])

    def test_component_versions_and_report(self):
        M = tiny_model(); v1, v2 = AR.component_versions(M), AR.component_versions(json.loads(json.dumps(M)))
        self.assertEqual(v1, v2); self.assertEqual(v1["image"]["owner"], "LUMOS"); self.assertEqual(v1["math"]["owner"], "ALBUS")
        R = AR.component_report(M)
        self.assertEqual(sorted(R["by_owner"]), ["ALBUS", "LUMOS", "NOX", "PERCIVAL"]); self.assertFalse(R["components"]["unified"]["available"])
        self.assertFalse(AR.component_report(None)["available"])


# ------------------------------------------------------------------------------------------------------------------------------ PENSIEVE
class TestPensieve(unittest.TestCase):
    def fixture(self):
        b, cand = project()
        write(b, cand, "Exp One", {1: "cSS", 2: "Vessel", 3: "Unsure"}); write(b, cand, "Exp Two", {1: "cSS", 2: "Vessel", 3: "Unsure"})
        write(b, cand, "Novice", {4: "cSS"}); experts(b, "Exp One", "Exp Two"); missed(b, "Exp One")
        os.makedirs(os.path.join(b, "percival", "ledger", "S1"))
        json.dump(dict(study="S1", model="v001", run="initial", created="2026-11-24 11:00:00", candidates=[dict(cand_id=1, percival_score=88.0, band="green",
                  status="reliable", components=dict(math=80.0))]), open(os.path.join(b, "percival", "ledger", "S1", "v001__initial.json"), "w"))
        return b, cand

    def test_rebuild_reproducible_separated_provenance_attribution(self):
        b, _ = self.fixture()
        r1 = PI.rebuild(b); r2 = PI.rebuild(b)
        self.assertTrue(r1["ok"], r1["errors"]); self.assertEqual(r1["digest"], r2["digest"])
        self.assertEqual(PI.path(b), os.path.join(b, "percival", "pensieve", "pensieve_index.db"))
        con = sqlite3.connect(PI.path(b))
        calls = con.execute("SELECT reviewer, role, call, read_phase, ai_visible, provenance_class, source_kind FROM expert_calls WHERE cand_id=1 ORDER BY reviewer").fetchall()
        self.assertEqual(calls, [("Exp One", "expert", "cSS", "initial", "False", "verified_blind_post_3A", "expert_human"),
                                 ("Exp Two", "expert", "cSS", "initial", "False", "verified_blind_post_3A", "expert_human")])
        self.assertEqual(con.execute("SELECT status, effective_call, primary_eligible FROM consensus WHERE cand_id=1").fetchone(), ("resolved", "cSS", 1))
        self.assertEqual(con.execute("SELECT status FROM consensus WHERE cand_id=3").fetchone(), ("abstained",))
        self.assertEqual(con.execute("SELECT status FROM consensus WHERE cand_id=4").fetchone(), ("no_expert",))
        self.assertEqual(con.execute("SELECT COUNT(*) FROM predictions").fetchone()[0], 1)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM expert_calls WHERE reviewer LIKE 'v00%' OR source LIKE '%ledger%'").fetchone()[0], 0)
        fp = con.execute("SELECT event_type, responsible_component, responsible_version, eligible FROM corrections WHERE event_type='false_positive_candidate'").fetchall()
        self.assertEqual(len(fp), 1); self.assertEqual(fp[0][1], "ALBUS"); self.assertTrue(fp[0][2].startswith("albus:v4.18:abc123def456"))
        ms = con.execute("SELECT eligible, responsible_component FROM corrections WHERE event_type='missed_lesion'").fetchall()
        self.assertEqual(ms, [(1, "ALBUS")]); con.close()
        self.assertTrue(PI.summary(b)["separation_ok"])

    def test_update_is_idempotent_and_matches_rebuild(self):
        b, _ = self.fixture(); r = PI.rebuild(b)
        for _ in range(3): u = PI.update_study(b, "S1")
        self.assertTrue(u["ok"], u); self.assertEqual(u["digest"], r["digest"])

    def test_failure_is_recorded_not_swallowed(self):
        b, _ = self.fixture(); PI.rebuild(b)
        os.remove(os.path.join(b, "review", "S1_candidates.csv"))
        u = PI.update_study(b, "S1")
        self.assertFalse(u["ok"]); self.assertIn("no candidate list", u["error"])
        st = json.load(open(PI.status_path(b))); self.assertFalse(st["last_update"]["ok"])
        r = PI.rebuild(b, studies=["S1"]); self.assertFalse(r["ok"]); self.assertEqual(len(r["errors"]), 1)

    def test_reviewer_saves_update_memory_without_duplicates(self):
        from test_phase3a2_blind import Server, build
        b = tempfile.mkdtemp(prefix="arch_rw_", dir=os.environ["CSS_BASE"]); build(b)
        RR.set_role(b, "Dr Blind", "expert", "admin", "fixture", RR.CONFIRM_ROLE)
        srv = Server(b)
        try:
            m = srv.get("/api/meta?study=S1&reviewer=Dr%20Blind"); first = m["cands"][0]["id"]
            for _ in range(3): srv.post("/api/call", dict(study="S1", reviewer="Dr Blind", cand_id=first, call="cSS", mode=""))
        finally: srv.stop()
        con = sqlite3.connect(PI.path(b))
        rows = con.execute("SELECT reviewer, call, read_phase, ai_visible FROM expert_calls WHERE reviewer='Dr Blind'").fetchall(); con.close()
        self.assertEqual(len(rows), 1, rows)                                         # three saves of the same call -> one memory row
        self.assertEqual(rows[0][1:], ("cSS", "initial", "False"))                   # blind first-read provenance preserved

    def test_legacy_database_is_per_project(self):
        from uengine.pensieve import PensieveCoreMemory, DurableLocalJournal
        b, _ = project(); old = os.environ.get("CSS_BASE")
        os.environ["CSS_BASE"] = b
        try:
            class _V:
                root_path = None
                def is_connected(self): return False
                def pensieve_dir(self): return None
            p = PensieveCoreMemory(vault=_V())
            self.assertEqual(p._db_path, os.path.join(b, "app_data", "pensieve.db"))
            self.assertEqual(DurableLocalJournal().db_path, os.path.join(b, "app_data", "pensieve_local_journal.db"))
        finally: os.environ["CSS_BASE"] = old


# -------------------------------------------------------------------------------------------------------------------------------- SHADOW
def synth_rows(n_pat=40, seed=1, partition="development"):
    rng = np.random.default_rng(seed); rows = []
    for q in range(n_pat):
        for c in range(6):
            y = int(rng.random() < 0.4); good = rng.normal(1.2 * y, 1.0); base = rng.normal(0.3 * y, 1.0)
            rows.append(dict(study=f"SYN{q:02d}", cand_id=c + 1, patient=f"SYNP{q:02d}", partition=partition, y=y,
                             features=dict(darkness_z=base, edge_contrast=rng.normal(), new_width_mm=good)))
    return rows


class TestShadow(unittest.TestCase):
    def store(self): return tempfile.mkdtemp(prefix="shadow_", dir=os.environ["CSS_BASE"])

    def test_governed_workflow(self):
        st = self.store(); rows = synth_rows(); base = ["darkness_z", "edge_contrast"]
        for bad in ("y", "expert_call", "percival_score", "patient_age"):
            with self.assertRaises(SG.ShadowError): SG.register(st, "NOX", "nox_measurement", [bad], "x")
        H = SG.register(st, "NOX", "nox_measurement", ["new_width_mm"], "cSS bands are wider on the surface")
        with self.assertRaises(SG.ShadowError): SG.run_discovery(st, H["id"], rows[:5] + [dict(rows[5], partition="test")], base)   # locked test refused
        D = SG.run_discovery(st, H["id"], rows, base, synthetic=True)["discovery"]
        S = SG.split_of(st, [])
        conf = {p for p, s in S["assignment"].items() if s == "confirmation"}
        self.assertTrue(conf and not (set(D["patients"]) & conf))                     # SHADOW never saw a confirmation patient
        self.assertGreater(D["result"]["delta_auc"], 0)
        with self.assertRaises(SG.ShadowError): SG.run_discovery(st, H["id"], rows, base)              # discovery is recorded once
        with self.assertRaises(SG.ShadowError): SG.approve(st, H["id"], "Dr Admin", "r", CR.CONFIRM)  # not confirmed yet
        with self.assertRaises(SG.ShadowError): SG.confirm(st, H["id"], rows, actor="SHADOW")          # the proposer cannot confirm
        C = SG.confirm(st, H["id"], rows)["confirmation"]
        self.assertEqual(sorted(C["patients"]), sorted(p for p in conf if any(r["patient"] == p for r in rows)))
        self.assertIn("passed", C)
        with self.assertRaises(SG.ShadowError): SG.confirm(st, H["id"], rows)                         # one-shot
        for who in ("SHADOW", "PERCIVAL", "system", ""):
            with self.assertRaises((SG.ShadowError, CR.RegistryError)): SG.approve(st, H["id"], who, "r", CR.CONFIRM, override=True, allow_synthetic=True)
        with self.assertRaises(SG.ShadowError): SG.approve(st, H["id"], "Dr Admin", "r", CR.CONFIRM, override=True)   # synthetic evidence
        with self.assertRaises(CR.RegistryError): SG.approve(st, H["id"], "Dr Admin", "r", "yes", override=True, allow_synthetic=True)
        Hn, V = SG.approve(st, H["id"], "Dr Admin", "infrastructure test", CR.CONFIRM, override=not C["passed"], allow_synthetic=True)
        self.assertEqual((V["version"], V["parent"], V["synthetic"]), ("v001", "v000", True))
        self.assertIn("new_width_mm", CR.active(st, "NOX")["config"]["feature_set"])
        self.assertEqual(CR.rollback(st, "NOX", "Dr Admin", "undo", CR.CONFIRM)["version"], "v000")
        self.assertNotIn("new_width_mm", CR.active(st, "NOX")["config"]["feature_set"])
        self.assertEqual([e["event"] for e in CR.history(st, "NOX")], ["approved_and_activated", "rolled_back"])

    def test_split_is_locked_and_unimplemented_kinds_never_pass(self):
        st = self.store(); a = SG.split_of(st, ["P1", "P2", "P3"])["assignment"]; b = SG.split_of(st, ["P3", "P2", "P1", "P4"])["assignment"]
        self.assertEqual({k: b[k] for k in a}, a)
        with self.assertRaises(SG.ShadowError): SG.register(st, "LUMOS", "lumos_pattern", [], "visual hypothesis")     # Stage 4: never empty
        H = SG.register(st, "LUMOS", "lumos_pattern", ["patch_minip_mean"], "visual hypothesis")
        H["implemented"] = False; SG._js(SG._dir(st, "hypotheses", f"{H['id']}.json"), H)          # a record written before its kind existed
        self.assertEqual(SG.run_discovery(st, H["id"], synth_rows(), ["darkness_z"])["status"], "not_implemented")


# --------------------------------------------------------------------------------------------------------------------------------- ALBUS
class TestAlbus(unittest.TestCase):
    def test_sensitivity_counts_missed_lesions_and_gate_protects_sensitivity(self):
        b, cand = project()
        write(b, cand, "Exp One", {1: "cSS", 2: "Vessel", 3: "Normal"}); experts(b, "Exp One"); missed(b, "Exp One")
        E = AD.evaluate(b, ["S1"]); v = [k for k in E if k != "unreadable"][0]; M = E[v]
        self.assertEqual((M["detected"], M["missed"], M["false_positives"], M["sensitivity"]), (1, 1, 2, 0.5))
        better_fp = dict(M, false_positives=0, fp_per_study=0.0, detected=0, missed=2, sensitivity=0.0)
        c = AD.compare(M, better_fp); self.assertEqual(c["verdict"], "rejected")       # fewer FPs never excuse lost lesions
        with self.assertRaises(CR.RegistryError): AD.propose_and_approve(b, "albus:new", c, "Dr Admin", "r", CR.CONFIRM)
        ok = AD.compare(M, dict(M, false_positives=1, fp_per_study=1.0)); self.assertEqual(ok["verdict"], "improved")
        V = AD.propose_and_approve(os.path.join(b, "percival"), "albus:new", ok, "Dr Admin", "fewer vessels", CR.CONFIRM)
        self.assertEqual((V["component"], V["version"]), ("ALBUS", "v001"))
        missed(b, "Novice", mid=2)                                                    # a non-expert mark is not ground truth
        self.assertEqual(AD.evaluate(b, ["S1"])[v]["missed"], 0)


# ----------------------------------------------------------------------------------------------------------------------------- app routes
class TestAppRoutes(unittest.TestCase):
    def test_architecture_endpoints(self):
        import css_app; css_app.pg_init()
        A = css_app.pg_get("architecture", {})
        self.assertEqual([c["key"] for c in A["components"]], ["ALBUS", "NOX", "LUMOS", "PERCIVAL", "CORE", "PENSIEVE", "SHADOW"])
        st = {c["key"]: c["state"] for c in A["components"]}
        self.assertEqual(st["LUMOS"], "untrained"); self.assertEqual(st["PERCIVAL"], "untrained"); self.assertEqual(st["CORE"], "off")
        self.assertFalse(css_app.pg_get("components_report", {})["available"])
        self.assertIn("legacy_note", css_app.pg_get("shadow_gov", {}))
        self.assertFalse(css_app.pg_post("shadow_gov_approve", dict(id="H999", by="SHADOW"))["ok"])
        self.assertTrue(css_app.pg_post("pensieve_rebuild", {})["ok"])
        self.assertTrue(css_app.pg_get("pensieve_index", {})["built"])
        self.assertIn("evaluation", css_app.pg_get("albus", {}))

    def test_new_ai_routes_respect_the_blind_gate(self):
        import css_app; css_app.pg_init(); B = css_app.B
        os.makedirs(os.path.join(B, "review"), exist_ok=True); os.makedirs(css_app.PG.P("scores"), exist_ok=True)
        pd.DataFrame([dict(cand_id=1, vox_i=1, vox_j=1, vox_k=1, volume_mm3=9.0)]).to_csv(os.path.join(B, "review", "BG1_candidates.csv"), index=False)
        json.dump(dict(model="v001", run="initial", candidates=[dict(cand_id=1, percival_score=99.0, components={})]), open(css_app.PG.P("scores", "BG1.json"), "w"))
        for op in ("contracts", "pensieve_history", "score"):
            r = css_app.pg_get(op, dict(code="BG1", cand="1"))
            self.assertTrue(r.get("hidden"), (op, r)); self.assertNotIn("99.0", json.dumps(r))


if __name__ == "__main__":
    unittest.main()
