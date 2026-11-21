"""check_identity.py - Percival identification core (v5.16), synthetic data only: encrypted vault (wrong passphrase refused, identifiers
not readable at rest, backups), permanent uuids / file keys, unique study identifiers, generated de-identified codes (unique, persistent),
audited patient- and study-level edits (uuid / file key never change, patient edit covers all examinations), Standard / Incognito views
(no MRN / name / accession in Incognito or while locked), examination-level duplicate classification, additive migration of existing
studies, Excel template (four columns, order), manifest validation, import wizard (multi-examination patient, missing codes generated
once, re-import recognised, Incognito preview without identifiers or folder names).
usage: python tests/check_identity.py   (exit 1 on any FAIL)"""
import json, os, shutil, sys, tempfile
import numpy as np, nibabel as nib
H = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(H); sys.path.insert(0, os.path.join(ROOT, "app"))
import identity as IDM, manifest as MF, import_wizard as IW   # noqa: E402
F = []
def check(n, ok, info=""): print(f"{'PASS' if ok else 'FAIL'}  {n}  {info}"); (None if ok else F.append(n))
def raises(fn, exc):
    try: fn(); return False
    except exc: return True
def blob(p):
    with open(p, "rb") as f: return f.read()

T = tempfile.mkdtemp(prefix="ident_"); B = os.path.join(T, "base"); os.makedirs(B)
ID = IDM.Identity(B); PW = "correct horse battery"
check("vault: short passphrase refused", raises(lambda: ID.create_vault("short"), IDM.IdentityError))
ID.create_vault(PW)
pu = ID.add_patient(mrn="123456", name="John Smith", by="tester")
s1 = ID.add_study(pu, "PCVKEY1", "STUDY-001", display_name="Brain MRI - SWI", accession="ACC-001", institution="Hosp", fingerprint="c2:aaa", by="tester")
s2 = ID.add_study(pu, "PCVKEY2", "STUDY-002", accession="ACC-002", institution="Hosp", fingerprint="c2:bbb", by="tester"); ID.commit()
for secret in (b"123456", b"John Smith", b"ACC-001"):
    check(f"identifier {secret.decode()} not readable in the vault file or the registry", secret not in blob(ID.vpath) and secret not in blob(ID.rpath))
ID2 = IDM.Identity(B)
check("wrong passphrase refused", raises(lambda: ID2.unlock("wrong passphrase!"), IDM.VaultLocked))
check("locked vault: identifier lookup refused", raises(lambda: ID2.by_accession("ACC-001"), IDM.VaultLocked))
v = ID2.view(s1, "standard"); check("locked + Standard: only the de-identified code is shown", v["study_id"] == "STUDY-001" and "patient_name" not in v and v["locked"])
v = ID2.view(s1, "incognito"); check("Incognito: no MRN / name / accession", not any(k in v for k in ("mrn", "patient_name", "accession")) and v["study_id"] == "STUDY-001")
ID2.unlock(PW); v = ID2.view(s1, "standard")
check("unlocked Standard: accession is the study id, MRN and name shown", v["study_id"] == "ACC-001" and v["mrn"] == "123456" and v["patient_name"] == "John Smith")
check("one patient, two examinations", v["n_exams_of_patient"] == 2)
v = ID2.view(s1, "incognito"); check("unlocked but Incognito: still no identifiers", not any(k in v for k in ("mrn", "patient_name", "accession")))
check("duplicate deid code refused", raises(lambda: ID2.add_study(pu, "PCVKEY3", "STUDY-001"), IDM.IdentityError))
check("duplicate accession (same institution) refused", raises(lambda: ID2.add_study(pu, "PCVKEY3", "STUDY-003", accession="acc-001", institution="hosp"), IDM.IdentityError))
check("duplicate file key refused", raises(lambda: ID2.add_study(pu, "PCVKEY1", "STUDY-009"), IDM.IdentityError))
codes = {ID2.unique_code() for _ in range(500)}
check("generated codes: unique, long, unambiguous alphabet", len(codes) == 500 and all(len(c) == 18 and not set(c) & set("01OILU") for c in codes))
# edits
uu, fk = s1, ID2.study(s1)["file_key"]
ID2.edit_study(s1, by="tester", reason="typo", accession="ACC-001A")
check("accession edit: only this examination", ID2.view(s1, "standard")["accession"] == "ACC-001A" and ID2.view(s2, "standard")["accession"] == "ACC-002")
check("edit refused when the new accession belongs to another examination", raises(lambda: ID2.edit_study(s1, by="t", accession="ACC-002"), IDM.IdentityError))
ID2.edit_study(s1, by="tester", deid_code="STUDY-001X", display_name="Brain MRI")
check("deid code edit refused if used elsewhere", raises(lambda: ID2.edit_study(s2, by="t", deid_code="STUDY-001X"), IDM.IdentityError))
check("uuid and file key never change on edits", ID2.study(uu)["file_key"] == fk and uu in ID2.R["studies"])
ID2.edit_patient(pu, by="tester", reason="correction", mrn="123457", name="John A Smith")
check("patient edit applies to all examinations of the patient", ID2.view(s1, "standard")["mrn"] == "123457" and ID2.view(s2, "standard")["patient_name"] == "John A Smith")
pu2 = ID2.add_patient(mrn="789012", name="Mary Jones"); ID2.commit()
check("MRN edit refused if it belongs to another patient (no silent merge)", raises(lambda: ID2.edit_patient(pu2, by="t", mrn="123457"), IDM.IdentityError))
h = ID2.history(); hs = ID2.history(include_sensitive=True)
check("audit: non-sensitive history has old/new, sensitive history only in the vault", any(x["field"] == "deid_code" and x["old"] == "STUDY-001" for x in h)
      and all("old" not in x for x in h if x.get("sensitive")) and any(x["field"] == "accession" and x["old"] == "ACC-001" and x["new"] == "ACC-001A" for x in hs))
check("audit records who, when and why", all(x.get("time") and "by" in x for x in hs) and any(x.get("reason") == "typo" for x in hs))
check("registry never holds the sensitive values", b"ACC-001A" not in blob(ID2.rpath) and b"123457" not in blob(ID2.rpath))
check("vault backups kept before every write", len(os.listdir(os.path.join(B, "private", "vault_backups"))) >= 3)
# duplicate classification
check("same image content -> same examination (re-import / moved)", ID2.classify(fingerprint="c2:aaa")["kind"] == "same_exam")
check("same accession, different images -> conflict", ID2.classify(fingerprint="c2:zzz", accession="ACC-002", institution="Hosp")["kind"] == "conflict")
check("accession of another patient -> conflict", "DIFFERENT patient" in ID2.classify(fingerprint="c2:zzz", accession="ACC-002", institution="Hosp", mrn="789012")["why"])
check("same patient, new examination", ID2.classify(fingerprint="c2:new", mrn="123457")["kind"] == "same_patient_new_exam")
check("genuinely new examination", ID2.classify(fingerprint="c2:new2")["kind"] == "new")
# backup / restore
out = ID2.backup_vault(os.path.join(T, "vb")); check("vault backup validates with the passphrase", ID2.validate_vault_file(out, PW)["studies"] >= 2)
check("vault backup refuses a wrong passphrase", raises(lambda: ID2.validate_vault_file(out, "nope nope nope"), IDM.VaultLocked))
# migration of existing studies (additive)
B2 = os.path.join(T, "base2"); os.makedirs(B2); I3 = IDM.Identity(B2); I3.create_vault(PW)
PAT = [dict(code="P001", fingerprint="c2:x1"), dict(code="P002", fingerprint="")]
n = I3.migrate_existing(PAT, names={"P001": "Old Name"}); u1 = I3.by_file_key("P001")
check("migration: one uuid per study, code kept as file key and deid code", n == 2 and I3.study(u1)["deid_code"] == "P001")
check("migration copies names into the vault", I3.view(u1, "standard")["patient_name"] == "Old Name")
check("migration is idempotent", I3.migrate_existing(PAT) == 0 and len(I3.R["studies"]) == 2)
check("existing study without accession is flagged in Standard mode", I3.view(u1, "standard")["accession_missing"] is True)
# template + manifest
xl = os.path.join(T, "Percival_Import_Template.xlsx")
with open(xl, "wb") as f: f.write(MF.template_bytes())
import pandas as pd
df = pd.read_excel(xl, dtype=str)
check("template: exactly the four columns, in order", list(df.columns) == MF.COLUMNS and len(df) == 3)
rows, prob = MF.read(xl); check("template reads back", not prob and rows[1]["accession"] == "ACC-002")
v = MF.validate(rows, "standard"); check("example manifest valid in Standard; one patient with two examinations",
                                         v["ok"] and any(p["n_exams"] == 2 for p in v["patients"]))
bad = [dict(r) for r in rows]; bad[1]["accession"] = "ACC-001"; bad[2]["patient_name"] = ""; bad[2]["accession"] = ""
v = MF.validate(bad, "standard"); msgs = " | ".join(e["msg"] for e in v["errors"])
check("Standard: duplicate and missing accession flagged", "also on row 2" in msgs and "accession_number is required" in msgs)
bad = [dict(r) for r in rows]; bad[1]["patient_name"] = "Jon Smith"
check("conflicting names on one MRN flagged, not merged", "different patient names" in " ".join(e["msg"] for e in MF.validate(bad, "standard")["errors"]))
inc = [dict(r, code="") for r in rows]
check("Incognito: missing codes are errors unless generation is allowed", not MF.validate(inc, "incognito")["ok"] and MF.validate(inc, "incognito", generate_codes=True)["ok"])
check("Incognito redaction of manifest rows", all(set(r) == {"row", "code", "has_identifiers"} for r in MF.redact(rows, "incognito")))
# import wizard on synthetic folders
D = os.path.join(T, "incoming")
def swi(folder, seed):
    os.makedirs(folder, exist_ok=True); rng = np.random.default_rng(seed); v_ = np.zeros((48, 48, 20), np.int16); v_[8:40, 8:40, 4:16] = rng.integers(200, 900, (32, 32, 12))
    nib.save(nib.Nifti1Image(v_, np.diag([0.8, 0.8, 1.2, 1])), os.path.join(folder, "SWI_mag.nii"))
    with open(os.path.join(folder, "SWI_mag.json"), "w") as f: json.dump(dict(SeriesDescription="SWI", ImageType=["ORIGINAL", "PRIMARY", "M", "SWI"]), f)
swi(os.path.join(D, "123456", "STUDY-001"), 1); swi(os.path.join(D, "123456", "STUDY-002"), 2); swi(os.path.join(D, "789012"), 3)
B3 = os.path.join(T, "base3"); os.makedirs(B3); I4 = IDM.Identity(B3); I4.create_vault(PW)
plan = IW.new_plan(D, "mrn", "standard", xl, ID=I4)
check("wizard: patient folders and examinations found (multi-exam patient)", len(plan["patients"]) == 2 and len(plan["exams"]) == 3)
check("wizard: every examination matched to its manifest row", all(e["row"] for e in plan["exams"]) and plan["ok"], str([(e["eid"], e["row"], e.get("matched_by")) for e in plan["exams"]]) + str(plan["errors"]))
Q = []
def fake_queue(items, st): Q.extend(items); return dict(ok=True, added=[i["code"] for i in items])
res = IW.commit(plan["id"], I4, fake_queue, {}, by="tester")
check("commit: three studies, two patients, accessions in the vault", len(I4.R["studies"]) == 3 and len(I4.R["patients"]) == 2
      and sorted(I4.view(x["study_uuid"], "standard")["accession"] for x in res["imported"]) == ["ACC-001", "ACC-002", "ACC-003"])
check("file keys are not accession numbers", not any(it["code"].startswith("ACC") for it in Q))
plan2 = IW.new_plan(D, "mrn", "standard", xl, ID=I4)
check("re-import of the same folder: every examination recognised and left out", all(not e["include"] and "re-import" in e.get("excluded_why", "") for e in plan2["exams"]) and not plan2["ok"])
# incognito with missing codes
B4 = os.path.join(T, "base4"); os.makedirs(B4); I5 = IDM.Identity(B4)
pi = IW.new_plan(D, "mrn", "incognito", "", generate_codes=True, ID=I5); vv = IW.view(pi)
txt = json.dumps(vv)
check("Incognito preview: no folder names, MRN, names, accession or paths", "123456" not in txt and "789012" not in txt and D not in txt and "John" not in txt, txt[:200])
check("Incognito preview marks codes to be generated", all(e["code_generated"] for e in vv["exams"]) and pi["ok"])
r = IW.commit(pi["id"], I5, lambda it, st: dict(ok=True, added=[x["code"] for x in it]), {}, by="t")
gen = [x["deid_code"] for x in r["imported"]]
check("codes generated once, unique, persisted", len(set(gen)) == 3 and all(I5.by_deid(c) for c in gen) and IDM.Identity(B4).by_deid(gen[0]))
pi2 = IW.new_plan(D, "mrn", "incognito", "", generate_codes=True, ID=IDM.Identity(B4))
check("re-import keeps the codes (examinations recognised, no new codes)", all(not e["include"] for e in pi2["exams"]) and not any(e.get("generated_code") for e in pi2["exams"]))
check("Incognito import without a vault stored no identifiers", not os.path.exists(os.path.join(B4, "private", "identity_vault.enc")))
shutil.rmtree(T, ignore_errors=True)
print(("ALL PASS" if not F else f"{len(F)} FAILED: {F}") + f" ({__file__})"); sys.exit(1 if F else 0)
