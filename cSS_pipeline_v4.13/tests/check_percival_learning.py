"""check_percival_learning.py (v5.24) - review-to-learning, eligibility, dataset versions, store migration and backward compatibility.
SYNTHETIC files only, in temporary project folders; no other project on this Mac is read (the 'earlier project' is a temp folder too).

  A legacy compatibility  a study reviewed with an older version (shared review/ID_calls.csv, call 'Vein', partly called, no final save) is
                          offered for learning with its labels; 'Vein' = Vessel = not cSS; uncalled candidates are not labels
  B re-detection          calls follow their lesion by fingerprint, never the candidate number
  C eligibility           positive / negative / Unsure / Near ICH / reviewer conflict / study left out / missing image or measurements,
                          per component, with reason codes; conflict setting 'effective' uses the effective call
  D revision              a revised call and a withdrawn call change the label and the dataset membership
  E historical reviews    reviews of the same examination in an earlier project are found by fingerprint, copied (verified, source
                          unchanged), used only where no current call exists, marked 'earlier version'
  F orphans               a reviewed study missing from the study list is offered, marked
  G datasets              snapshot is content-hashed: same inputs -> same id (not stored twice); a changed review -> a new version
  H store migration       v5.22/v5.23 store in unified_engine/percival -> <project>/percival: backup first, every file verified,
                          model / active version / ledger readable after it, old folder kept with MOVED.txt; a second update is a
                          no-op; a store from a NEWER app is refused untouched with a clear message
  I training message      too few labels -> clear message with development / locked-test counts and the dataset id
  J label table           the Training screen's label table (label_schema.build) reads the legacy shared file and the old name
  K learning engine       model status register (migrated, explicit promotion, override with reason, reject / restore, retire, rollback),
                          training-run records (failed / interrupted), persisted eligibility record (all 6 components, missing requirements,
                          dataset membership, rules, time), patient-level splits + validation folds, leakage / duplicate refusal, dataset
                          reproducibility, unrecognised calls never dropped silently, restart persistence"""
import glob, hashlib, json, os, shutil, sys, tempfile, time
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
for p in (os.path.join(ROOT, "app"), os.path.join(ROOT, "scripts")): sys.path.insert(0, p)
import percival_gui as PG, label_schema as LS
from uengine.percival import store as ST, datasets as DS

FAIL = []
def check(ok, name, info=""):
    print(("PASS  " if ok else "FAIL  ") + name + (f"  {info}" if info and not ok else "")); ok or FAIL.append(name)

TMP = tempfile.mkdtemp(prefix="pv_learning_")
def project(name):
    B = os.path.join(TMP, name); os.makedirs(os.path.join(B, "review")); return B
def cands(B, sid, rows):
    pd.DataFrame(rows, columns=["cand_id", "vox_i", "vox_j", "vox_k", "volume_mm3", "score_v4", "darkness_z"]).to_csv(os.path.join(B, "review", f"{sid}_candidates.csv"), index=False)
def calls(B, sid, rows, name="calls", reviewer=None, sub="review"):
    d = pd.DataFrame(rows, columns=["cand_id", "call", "vox_i", "vox_j", "vox_k", "volume_mm3"])
    if reviewer: d["reviewer"] = reviewer; d["time"] = time.strftime("%Y-%m-%d %H:%M:%S")
    os.makedirs(os.path.join(B, sub), exist_ok=True); d.to_csv(os.path.join(B, sub, f"{sid}_{name}.csv"), index=False)
C6 = [(i, 10 * i, 20, 30, 40.0 + i, 1.0, 2.0) for i in range(1, 7)]
def fp(i): return (10 * i, 20, 30, 40.0 + i)

# ------------------------------------------------------------------ fixture: a project made by older versions
B = project("main")
cands(B, "SYNOLD", C6)                                                           # v5.6-era: shared file, 'Vein', 4 of 6 called
calls(B, "SYNOLD", [(1, "cSS", *fp(1)), (2, "Vein", *fp(2)), (3, "cSS", *fp(3)), (5, "Normal", *fp(5))])
calls(B, "SYNRED", [(1, "cSS", *fp(1)), (2, "Artifact", *fp(2))]); time.sleep(0.05)
cands(B, "SYNRED", [(1, *fp(2), 1.0, 2.0), (2, *fp(1), 1.0, 2.0)])                # re-detected: numbers swapped
cands(B, "SYNMIX", C6)                                                           # two reviewers, all kinds of calls
calls(B, "SYNMIX", [(1, "cSS", *fp(1)), (2, "Vessel", *fp(2)), (3, "Unsure", *fp(3)), (4, "Near ICH", *fp(4)), (5, "cSS", *fp(5))], name="calls_Reader_A", reviewer="Reader A")
calls(B, "SYNMIX", [(5, "Artifact", *fp(5))], name="calls_Reader_B", reviewer="Reader B")
cands(B, "SYNHIST", C6)                                                          # processed here, reviewed only in the earlier project
cands(B, "SYNORPH", C6[:1]); calls(B, "SYNORPH", [(1, "cSS", *fp(1))])         # on disk, not in the study list
# earlier project (temp) with a review of SYNHIST's examination under another code
E = project("earlier"); cands(E, "M77", C6)
calls(E, "M77", [(1, "cSS", *fp(1)), (2, "Vessel", *fp(2)), (6, "cSS", *fp(6))], name="calls_Old_Reader", reviewer="Old Reader")
src_sha = hashlib.sha256(open(os.path.join(E, "review", "M77_calls_Old_Reader.csv"), "rb").read()).hexdigest()
# legacy Percival store (v5.23 layout inside the engine code folder)
LG = os.path.join(B, "unified_engine", "percival")
os.makedirs(os.path.join(LG, "registry", "v001")); os.makedirs(os.path.join(LG, "ledger", "SYNOLD")); os.makedirs(os.path.join(LG, "reviews", "SYNOLD"))
json.dump(dict(version="v001", engine="percival-engine/5.23", meta={"kind": "math_only"}, data={}), open(os.path.join(LG, "registry", "v001", "model.json"), "w"))
json.dump(dict(version="v001", previous=None), open(os.path.join(LG, "active.json"), "w"))
json.dump(dict(model="v001", created="2026-11-01 10:00:00", run="initial", candidates=[]), open(os.path.join(LG, "ledger", "SYNOLD", "v001__initial.json"), "w"))
json.dump(dict(kind="expert review"), open(os.path.join(LG, "reviews", "SYNOLD", "x.json"), "w"))
legacy_hash = ST._files(LG)

SET = dict(features={}, percival_test_fraction=0.2)
PAT = [dict(code=c, cohort="Old", fingerprint=f"fp-{c}") for c in ("SYNOLD", "SYNRED", "SYNMIX", "SYNHIST")]
def init(base, pat, other=None):
    PG.STORE.update(ok=True, error="", migration=None)
    PG.init(B=base, SC=os.path.join(ROOT, "scripts"), SET=SET, patients=lambda: list(pat), is_reviewed=lambda c: False, label=lambda c: c,
            patient_of=lambda c: c, fingerprint_of=lambda c: next((p["fingerprint"] for p in pat if p["code"] == c), ""),
            save_settings=lambda: None, notify=lambda *a: None, other_projects=other or (lambda: []))

# ------------------------------------------------------------------ H store migration
init(B, PAT, other=lambda: [dict(path=E, kind="previous Percival version", patients=[dict(code="M77", fingerprint="fp-SYNHIST")])])
mig = PG.STORE["migration"] or {}
moved = glob.glob(LG + ".moved_*")
check(PG.STORE["ok"] and mig.get("migrated") and mig.get("frm") == 2, "H1 v5.23 store detected (schema 2) and migrated to schema 3", str(PG.STORE))
check({k: v for k, v in ST._files(os.path.join(B, "percival")).items() if k not in ("STORE.json", os.path.join("registry", "status.json"))} == legacy_hash,
      "H2 every file of the old store arrived unchanged (sha256); only STORE.json and the schema-4 status register added")
check(mig.get("backup") and ST._files(mig["backup"]) == legacy_hash, "H3 backup taken before the migration and verified", str(mig.get("backup")))
check(len(moved) == 1 and os.path.exists(os.path.join(moved[0], "MOVED.txt")) and not os.path.exists(LG), "H4 old folder kept (renamed, MOVED.txt), not deleted")
check(PG.active_version() == "v001" and PG.load("v001") and PG.history_of("SYNOLD")[0]["model"] == "v001", "H5 model, active version and prediction ledger readable after migration")
st = json.load(open(os.path.join(B, "percival", "STORE.json")))
check(st["schema"] == ST.SCHEMA and st["history"][-1]["frm"] == 2, "H6 STORE.json records schema and migration history", str(st))
init(B, PAT, other=lambda: [dict(path=E, kind="previous Percival version", patients=[dict(code="M77", fingerprint="fp-SYNHIST")])])
check(PG.STORE["ok"] and not PG.STORE["migration"]["migrated"] and len(json.load(open(os.path.join(B, "percival", "STORE.json")))["history"]) == 1,
      "H7 second update: nothing migrated again, history unchanged")
NB = project("newer"); os.makedirs(os.path.join(NB, "percival")); json.dump(dict(schema=99), open(os.path.join(NB, "percival", "STORE.json"), "w"))
before = ST._files(os.path.join(NB, "percival")); init(NB, [])
check(not PG.STORE["ok"] and "newer" in PG.STORE["error"] and ST._files(os.path.join(NB, "percival")) == before and PG.state()["store"]["ok"] is False,
      "H8 store of a newer app refused, untouched, clear message", PG.STORE["error"])
init(B, PAT, other=lambda: [dict(path=E, kind="previous Percival version", patients=[dict(code="M77", fingerprint="fp-SYNHIST")])])

# ------------------------------------------------------------------ A / B legacy + re-detection
S0 = {s["code"]: s for s in PG.selection()}
check(not S0["SYNOLD"]["included"] and S0["SYNOLD"]["n_labelled"] == 4 and "switched off" in S0["SYNOLD"]["why"],
      "A0 before local learning is switched on: labels shown, not used, reason given", str(S0["SYNOLD"]))
PG.authorize(True)
S = {s["code"]: s for s in PG.selection()}
o = S.get("SYNOLD", {})
check(o.get("included") and o.get("n_css") == 2 and o.get("n_mimic") == 2 and o.get("n_eligible") == 4, "A1 older-version review is used: 2 cSS + 2 not cSS, 4 eligible", str(o))
check(PG._labels("SYNOLD")[0] == {1: 1, 2: 0, 3: 1, 5: 0}, "A2 'Vein' read as Vessel (not cSS); uncalled 4 and 6 are not labels", str(PG._labels("SYNOLD")))
check(PG._labels("SYNRED")[0] == {2: 1, 1: 0}, "B1 calls follow their lesion by fingerprint after re-detection", str(PG._labels("SYNRED")))

# ------------------------------------------------------------------ C eligibility
C = {c["cand_id"]: c for c in PG.candidates_of("SYNMIX")["candidates"]}
check(C[1]["status"] == "eligible" and C[1]["y"] == 1 and all(C[1]["components"].values()), "C1 positive: eligible for every component", str(C[1]))
check(C[2]["status"] == "eligible" and C[2]["y"] == 0, "C2 negative (Vessel): eligible as not cSS")
check(C[3]["status"] == "excluded" and C[3]["reasons"][0] == "UNCERTAIN", "C3 Unsure kept, excluded with reason UNCERTAIN")
check(C[4]["status"] == "excluded" and C[4]["reasons"][0] == "OUT_OF_SCOPE", "C4 Near ICH excluded as out of scope")
check(C[5]["status"] == "needs_adjudication" and C[5]["reasons"][0] == "CONFLICT" and C[5]["reasons_text"], "C5 reviewers disagree -> needs adjudication, with reason text", str(C[5]))
SET["percival_conflicts"] = "effective"; C5 = {c["cand_id"]: c for c in PG.candidates_of("SYNMIX")["candidates"]}[5]
check(C5["status"] == "eligible" and C5["y"] == 0, "C6 setting 'use the effective call': the newest call (Artifact) is used", str(C5)); SET["percival_conflicts"] = "exclude"
SET["learner_exclude"] = ["SYNMIX"]; S2 = {s["code"]: s for s in PG.selection()}
check(not S2["SYNMIX"]["included"] and S2["SYNMIX"]["excluded_why"] == "excluded by you", "C7 study left out by the user: not used, reason shown"); SET.pop("learner_exclude")
from uengine.percival import eligibility as EL
ev = EL.evaluate(dict(label_kind="css", has_image=False, n_char=0))
check(ev["status"] == "eligible" and not ev["components"]["image"]["ok"] and not ev["components"]["char"]["ok"] and not ev["components"]["fusion"]["ok"]
      and ev["components"]["meta"]["ok"] and ev["components"]["image"]["reasons"] == ["NO_IMAGE"], "C8 missing image / measurements: excluded per component only", str(ev))
check(EL.evaluate(dict(label_kind="css", duplicate=True))["reasons"][0] == "DUPLICATE_STUDY", "C9 duplicate examination contributes once (reason DUPLICATE_STUDY)")

# ------------------------------------------------------------------ D revision / withdrawal
calls(B, "SYNMIX", [(1, "cSS", *fp(1)), (2, "Vessel", *fp(2)), (3, "cSS", *fp(3)), (4, "Near ICH", *fp(4)), (5, "cSS", *fp(5))], name="calls_Reader_A", reviewer="Reader A")
C = {c["cand_id"]: c for c in PG.candidates_of("SYNMIX")["candidates"]}
check(C[3]["status"] == "eligible" and C[3]["y"] == 1, "D1 revised call (Unsure -> cSS) becomes an eligible positive", str(C[3]))
calls(B, "SYNMIX", [(1, "cSS", *fp(1)), (3, "cSS", *fp(3)), (4, "Near ICH", *fp(4)), (5, "cSS", *fp(5))], name="calls_Reader_A", reviewer="Reader A")
C = {c["cand_id"]: c for c in PG.candidates_of("SYNMIX")["candidates"]}
check(2 not in C, "D2 withdrawn call: the candidate is no longer a label", str(sorted(C)))

# ------------------------------------------------------------------ E historical reviews from an earlier project
R = PG.recoverable_reviews()
check(len(R) == 1 and R[0]["code"] == "SYNHIST" and R[0]["source_code"] == "M77", "E1 earlier-project review found by image fingerprint (different study code)", str(R))
PG.recover_reviews()
hist_f = os.path.join(B, "historical", "SYNHIST", "review", "M77_calls_Old_Reader.csv")
check(os.path.exists(hist_f) and hashlib.sha256(open(hist_f, "rb").read()).hexdigest() == src_sha
      and hashlib.sha256(open(os.path.join(E, "review", "M77_calls_Old_Reader.csv"), "rb").read()).hexdigest() == src_sha
      and json.load(open(os.path.join(B, "historical", "SYNHIST", "review", "SOURCE.json")))["copies"][0]["verified"] == "sha256",
      "E2 copied with verification; earlier project unchanged; provenance recorded")
H = {c["cand_id"]: c for c in PG.candidates_of("SYNHIST")["candidates"]}
check(H.get(1, {}).get("label_source") == "historical" and H[1]["y"] == 1 and "HISTORICAL_LABEL" in H[1]["reasons"] and H[6]["y"] == 1 and H[2]["y"] == 0,
      "E3 earlier-version labels used, matched by fingerprint, marked as such", str(H))
calls(B, "SYNHIST", [(1, "Artifact", *fp(1))], name="calls_Reader_A", reviewer="Reader A")
H = {c["cand_id"]: c for c in PG.candidates_of("SYNHIST")["candidates"]}
check(H[1]["label_source"] == "review" and H[1]["y"] == 0 and H[6]["label_source"] == "historical", "E4 a current call always wins over an earlier-version call", str(H[1]))
check(PG.recoverable_reviews() == [], "E5 nothing recovered twice")

# ------------------------------------------------------------------ F orphan
S = {s["code"]: s for s in PG.selection()}
check(S.get("SYNORPH", {}).get("included") and S["SYNORPH"]["not_in_study_list"], "F1 reviewed study missing from the study list is offered and marked")
rep = PG.compat_report()
check(rep["n_orphans"] == 1 and any("not in the study list" in i for r in rep["studies"] for i in r["issues"]) and rep["store"]["schema"] == ST.SCHEMA
      and any(r["review_format"].startswith("legacy shared") for r in rep["studies"]), "F2 Data integrity report: orphan, legacy format, store schema", json.dumps(rep["store"])[:300])

# ------------------------------------------------------------------ G datasets
ex = [e for s in PG.selection() for e in PG._examples(s["code"], {})]
m1 = DS.build(ex, EL.RULES_VERSION, PG.P()); m2 = DS.build(ex, EL.RULES_VERSION, PG.P())
check(m1["id"] == m2["id"] and len(glob.glob(PG.P("datasets", "ds*.json"))) == 1, "G1 same reviews -> same dataset id, stored once", m1["id"])
calls(B, "SYNORPH", [(1, "Vessel", *fp(1))]); ex2 = [e for s in PG.selection() for e in PG._examples(s["code"], {})]
m3 = DS.build(ex2, EL.RULES_VERSION, PG.P())
check(m3["id"] != m1["id"] and m3["content_hash"] != m1["content_hash"] and m3["components"]["meta"], "G2 a changed review -> a new dataset version", f"{m1['id']} {m3['id']}")
check(all(k in m3 for k in ("rules_version", "feature_schema", "patch_spec", "label_sources", "excluded_by_reason")), "G3 manifest records rules, feature schema, patch spec, label sources, exclusions")

# ------------------------------------------------------------------ I training message / J label table
PG._train("test")
err = PG.JOB.get("error", "")
check(PG.JOB["state"] == "failed" and "not enough expert labels" in err and "locked test cohort" in err and "Dataset ds" in err, "I1 too few labels -> clear message with counts and dataset id", err)
d = LS.build(B); old = d[d.study_id == "SYNOLD"]
check(len(old) == 4 and (old.primary_class == "definite_css").sum() == 2 and "vein_unspecified" in set(old.mimic_subtype), "J1 label table reads the legacy shared file and 'Vein'")

# ------------------------------------------------------------------ K learning engine
from uengine.percival import eligibility as EL2
R = PG.runs()
check(R and R[-1]["state"] == "failed" and "not enough expert labels" in R[-1].get("error", "") and R[-1].get("dataset", "").startswith("ds"),
      "K1 every training run recorded, a failed one with its error and dataset", json.dumps(R[-1:])[:300])
json.dump(dict(id="run999", state="running", started="2026-11-21 09:00:00"), open(PG.P("runs", "run999.json"), "w"))
init(B, PAT)
check(json.load(open(PG.P("runs", "run999.json")))["state"] == "interrupted", "K2 a run left 'running' (app closed) is recorded as interrupted at the next start")
st0 = PG.status_all()
check(st0.get("v001", {}).get("status") == "active", "K3 migrated model status register: the active v001 is 'active'", str(st0))
os.makedirs(PG.P("registry", "v002"))
json.dump(dict(version="v002", engine="percival-engine/5.24", meta={"kind": "math_only"}, data={}, acceptance=dict(passed=False, reasons=["below the minimum data"])),
          open(PG.P("registry", "v002", "model.json"), "w"))
check(PG.status_all()["v002"]["status"] == "experimental", "K4 a version that did not pass is 'experimental' (never active by itself)")
r = PG.promote("v002")
check(not r["ok"] and r.get("needs_override") and PG.active_version() == "v001", "K5 promotion of a version that did not pass refused without an override", str(r))
check(not PG.promote("v002", override=True)["ok"], "K6 override without a reason refused")
check(not PG.set_status("v002", "rejected")["ok"] and PG.set_status("v002", "rejected", why="test: poor calibration")["ok"]
      and not PG.promote("v002", why="x", override=True)["ok"], "K7 reject needs a reason; a rejected version cannot be made active")
check(PG.set_status("v002", "restore")["ok"] and PG.status_all()["v002"]["status"] == "experimental", "K8 restore returns it to experimental")
check(not PG.set_status("v001", "rejected", why="x")["ok"], "K9 the active model cannot be rejected or retired")
r = PG.promote("v002", why="test: research use", override=True); stA = PG.status_all()
check(r["ok"] and PG.active_version() == "v002" and stA["v002"]["status"] == "active" and stA["v001"]["status"] == "retired",
      "K10 explicit approval with a reason -> active; the replaced version is retired", str(stA))
r = PG.rollback(); stB = PG.status_all()
check(r["ok"] and PG.active_version() == "v001" and stB["v001"]["status"] == "active" and stB["v002"]["status"] == "retired"
      and len(stB["v002"]["history"]) >= 4, "K11 rollback: v001 active again, v002 retired, full status history kept")
REG = {x["version"]: x for x in PG.registry()}
check(all(k in REG["v002"] for k in ("id", "status", "dataset", "feature_schema", "configuration", "metrics", "validation", "artifact", "components")),
      "K12 registry entry: identity, status, dataset, configuration, schema, metrics, validation, artifact, components")
calls(B, "SYNOLD", [(1, "cSS", *fp(1)), (2, "Vein", *fp(2)), (3, "cSS", *fp(3)), (5, "Normal", *fp(5)), (6, "Calcification?", *fp(6))])
lab = PG.label_summary("SYNOLD"); c6 = next(c for c in PG.candidates_of("SYNOLD")["candidates"] if c["cand_id"] == 6)
check(lab["unrecognised"] == ["Calcification?"] and c6["status"] == "unrecognised" and "UNRECOGNISED_CALL" in c6["reasons"]
      and "Calcification?" in PG.state()["unrecognised"], "K13 an unrecognised call is kept, reported (Data integrity), never silently dropped", str(lab.get("unrecognised")))
E1 = EL2.evaluate(dict(label_kind="css", authorized=True, has_image=False, n_char=True, has_predictors=False, test=True))
check(set(EL2.COMPONENTS) == {"char", "image", "fusion", "meta", "predictor", "shadow"} and not E1["components"]["image"]["ok"] and E1["components"]["char"]["ok"]
      and not E1["components"]["predictor"]["ok"] and E1["components"]["shadow"]["ok"] and E1["components"]["image"]["missing"] and E1["components"]["predictor"]["missing"],
      "K14 eligibility per component incl. predictor + shadow; missing requirements in words; eligible for one, not another", json.dumps(E1)[:300])
c1 = next(c for c in PG.candidates_of("SYNOLD")["candidates"] if c["cand_id"] == 1)
check(c1["rules"] == EL2.RULES_VERSION and c1["evaluated"] and "missing" in c1, "K15 each candidate carries rules version and evaluation time")
ER = PG.eligibility_record(); ERf = json.load(open(PG.P("eligibility", "current.json")))
check(ER["n"] > 0 and ERf["rules"] == EL2.RULES_VERSION and all(k in ERf["candidates"][0] for k in ("components", "reasons", "missing", "datasets", "evaluated", "partition"))
      and any(x["datasets"] for x in ERf["candidates"]), "K16 eligibility record persisted with dataset membership", json.dumps(ER)[:300])
PG.eligibility_record()
check(len(glob.glob(PG.P("eligibility", "*.json"))) >= 2, "K17 a new evaluation keeps the previous record")
pts = [dict(study=f"S{i}", cand_id=1, patient=f"P{i}", y=i % 2, label_source="review", partition="development", components={k: True for k in EL2.COMPONENTS}, reasons=[]) for i in range(12)]
pts += [dict(study="T1", cand_id=1, patient="PT", y=1, label_source="review", partition="test", components={k: True for k in EL2.COMPONENTS}, reasons=["LOCKED_TEST"])]
mK = DS.build(pts, EL2.RULES_VERSION, os.path.join(TMP, "dsK"))
fo = {e["patient"]: e["validation_fold"] for e in mK["examples"]}
check(mK["integrity"]["errors"] == [] and all(fo[f"P{i}"] for i in range(12)) and fo["PT"] is None and len(set(fo[f"P{i}"] for i in range(12))) >= 2
      and next(e for e in mK["examples"] if e["patient"] == "PT")["split"] == "test" and mK["splits"]["patients"] == dict(train=12, test=1),
      "K18 patient-level train (validation folds) / test assignment recorded", json.dumps(mK["splits"]))
try: DS.build(pts + [dict(pts[0], study="X", partition="test")], EL2.RULES_VERSION, os.path.join(TMP, "dsK")); leak = False
except DS.DatasetError as e: leak = "leakage" in str(e)
try: DS.build(pts + [dict(pts[0])], EL2.RULES_VERSION, os.path.join(TMP, "dsK")); dup = False
except DS.DatasetError as e: dup = "twice" in str(e)
check(leak and dup and len(glob.glob(os.path.join(TMP, "dsK", "datasets", "*.json"))) == 1, "K19 patient leakage and duplicate candidates refused (no dataset written)")
PG._train("K20 dataset snapshot")                                  # too few labels to train, but the dataset snapshot is made first
dsl = DS.listing(PG.P())[-1]["id"]; RP = PG.reproduce_dataset(dsl)
calls(B, "SYNOLD", [(1, "Vessel", *fp(1)), (2, "Vein", *fp(2)), (3, "cSS", *fp(3)), (5, "Normal", *fp(5)), (6, "Calcification?", *fp(6))])
RP2 = PG.reproduce_dataset(dsl)
check(RP["ok"] and RP["identical"] is True and not RP2["identical"] and RP2["changes"].get("expert label changed") and any(d["study"] == "SYNOLD" and d["cand_id"] == 1 for d in RP2["differences"]),
      "K20 dataset reproducibility check: a revised review is reported as the difference", json.dumps(RP2)[:300])
init(B, PAT)
check(PG.active_version() == "v001" and PG.status_all()["v002"]["status"] == "retired" and len(PG.runs()) >= 2 and os.path.exists(PG.P("eligibility", "current.json"))
      and DS.listing(PG.P()), "K21 restart: models, status register, runs, eligibility record and datasets persist")

shutil.rmtree(TMP, ignore_errors=True)
print("ALL PASS" if not FAIL else f"{len(FAIL)} FAILED: {FAIL}")
sys.exit(1 if FAIL else 0)
