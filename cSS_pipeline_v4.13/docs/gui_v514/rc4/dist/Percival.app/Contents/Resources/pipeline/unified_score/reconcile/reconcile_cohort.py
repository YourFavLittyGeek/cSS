"""reconcile_cohort.py - identifier-level reconciliation of the container test data against the provisional manifest.
READ-ONLY on the container test bases; writes only unified_score/reconcile/{reconciliation.csv, container_ids.csv} and
unified_score/cohort_manifest_RECONCILED.csv. No patient data exists in this container: every container identifier is a
phantom, synthetic test case or app-test fixture (M-named fixtures are random-noise images, checked below).
usage: python unified_score/reconcile/reconcile_cohort.py"""
import os, csv, glob, json
import numpy as np
H = os.path.dirname(os.path.abspath(__file__)); U = os.path.dirname(H)
prov = list(csv.DictReader(open(f"{U}/cohort_manifest_PROVISIONAL.csv")))
P = {r["study_id"]: r for r in prov}
ADDED_REV3 = {i for i, r in P.items() if "test phantom variant created by tests/run_tests.sh" in r["exclusion_reason"]}
ORIG74 = set(P) - ADDED_REV3

# ---- container identifiers: every test base that has review/ outputs, plus app-test input folders
roots = sorted({os.path.dirname(os.path.dirname(f)) for f in glob.glob("/tmp/**/review/*_candidates.csv", recursive=True)}
               | {os.path.dirname(os.path.dirname(f)) for f in glob.glob("/tmp/**/review/*_qc.json", recursive=True)})
where = {}
def add(i, kind, path): where.setdefault(i, {}).setdefault(kind, set()).add(path)
for b in roots:
    for f in glob.glob(f"{b}/review/*_candidates.csv"): add(os.path.basename(f).rsplit("_candidates", 1)[0], "review", b)
    for f in glob.glob(f"{b}/review/*_qc.json"): add(os.path.basename(f).rsplit("_qc", 1)[0], "review", b)
    for f in glob.glob(f"{b}/data/*_swi.nii*"): add(os.path.basename(f).split("_swi")[0], "data", b)
    for d in glob.glob(f"{b}/raw/*/"): add(os.path.basename(d.rstrip("/")), "raw", b)
for d in glob.glob("/tmp/**/data/*/SWI", recursive=True) + glob.glob("/tmp/**/data/*/T1", recursive=True):
    add(os.path.basename(os.path.dirname(d)), "app_input", os.path.dirname(os.path.dirname(d)))

def fixture_check(i):
    """M-named container items: are they random-noise fixtures? (uniform [0,1) values, tiny volume)"""
    import nibabel as nib
    fs = glob.glob(f"/tmp/**/data/{i}/*/*.nii*", recursive=True) + glob.glob(f"/tmp/**/data/{i}_swi.nii*", recursive=True)
    for f in fs:
        a = np.asarray(nib.load(f).dataobj, np.float32)
        return f"{a.shape}, values {a.min():.2f}..{a.max():.2f}, mean {a.mean():.2f} -> " + (
            "uniform random-noise fixture" if a.min() >= 0 and a.max() < 1 and abs(a.mean() - 0.5) < 0.02 else "NOT a plain noise fixture: inspect")
    return "no image (review / QC outputs of an app fake-run only)"

def kind_of(i):
    if i.startswith("M"): return "app-test fixture with a patient-like name (not a patient)"
    if i.startswith("PH") or i in ("PX",): return "phantom"
    if i in ("Q00", "Q01"): return "synthetic ranker-test case"
    if i in ("S1", "S2", "S3"): return "synthetic evaluate-test case"
    if i == "T1S": return "synthetic v5.2 T1-mask test case"
    if i.startswith("VG"): return "synthetic vessel-gate test case"
    return "synthetic"

C = set(where); M = set(P)
rows = []
for i in sorted(C | M):
    inC, inM = i in C, i in M
    rows.append(dict(study_id=i, in_container=int(inC), in_provisional_95=int(inM), in_original_74=int(i in ORIG74),
                     added_in_rev3=int(i in ADDED_REV3), container_kind=kind_of(i) if inC else "",
                     container_sources=";".join(sorted(where.get(i, {}))) if inC else "",
                     n_container_bases=len(set().union(*where[i].values())) if inC else 0,
                     fixture_check=fixture_check(i) if inC and i.startswith("M") else "",
                     manifest_decision=P[i]["decision"] if inM else "", manifest_role=P[i]["role"] if inM else "",
                     manifest_reason=P[i]["exclusion_reason"] if inM else ""))
with open(f"{H}/reconciliation.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

# ---- reconciled manifest: provisional 95 + container-only identifiers (excluded); M fixtures never alter a real M row
rec = [dict(r) for r in prov]
for r in rec:
    r["container_name_collision"] = "yes: container holds a random-noise app fixture with this name (ignored)" if r["study_id"] in C and r["study_id"].startswith("M") else ""
for i in sorted(C - M):
    rec.append(dict(study_id=i, starts_with_M="yes" if i.startswith("M") else "no", decision="exclude", role="excluded",
                    exclusion_reason=f"does not start with M ({kind_of(i)}; container test data, found in reconciliation)",
                    scoreability="not applicable", source="container test bases", note="added by reconcile_cohort.py",
                    container_name_collision=""))
with open(f"{U}/cohort_manifest_RECONCILED.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rec[0])); w.writeheader(); w.writerows(rec)

inc = [r for r in rec if r["decision"] == "include"]
print(f"reconcile: container {len(C)} ids, provisional {len(M)} (original 74 + {len(ADDED_REV3)} added), both {len(C & M)},"
      f" container-only {len(C - M)}, manifest-only {len(M - C)}; reconciled manifest {len(rec)} ids, {len(inc)} included"
      f" (development {sum(r['role'] == 'development' for r in inc)}, held-out {sum(r['role'] == 'held-out' for r in inc)})")
print("  both:", " ".join(sorted(C & M)))
print("  container only:", " ".join(sorted(C - M)))
print("  manifest only:", " ".join(sorted(M - C)))
print("  original-74 ∩ container:", " ".join(sorted(ORIG74 & C)))
print("  added-21 ∩ container:", len(ADDED_REV3 & C), "of", len(ADDED_REV3))
for r in rows:
    if r["fixture_check"]: print(f"  {r['study_id']}: {r['fixture_check']}  [{r['container_sources']}]")
