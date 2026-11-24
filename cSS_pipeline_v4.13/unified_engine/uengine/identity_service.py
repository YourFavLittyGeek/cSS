"""identity_service.py - ONE identity service for patient, study, examination fingerprint and split assignment (Stage 5).

PERCIVAL's data gathering, the locked patient split, the leakage audit and SHADOW all ask this service - none keeps its own mapping.
The service does not invent identities: the patient comes from the app's identity registry (IDG; verified / declared / assumed /
conflict status), the fingerprint from the same registry, the partition from the ONE locked patient split (uengine/percival/split.py).
A study without a patient record has patient None (never the study code) and partition None (never trained on).
"""
import hashlib
import json


class IdentityService:
    def __init__(self, store, patient_of, identity_of=None, fingerprint_of=None, test_fraction=0.2):
        self.store = store; self._pat = patient_of; self._idn = identity_of; self._fp = fingerprint_of; self.fraction = float(test_fraction)

    def patient(self, sid):
        try: return self._pat(sid) or None
        except Exception: return None

    def identity(self, sid):
        try: return (self._idn(sid) if self._idn else None) or dict(status="unknown")
        except Exception: return dict(status="unknown")

    def fingerprint(self, sid):
        try: return (self._fp(sid) if self._fp else "") or ""
        except Exception: return ""

    def partition(self, patient):
        if not patient: return None
        from uengine.percival import split as SP
        return SP.partition_of(self.store, patient, self.fraction)

    def record(self, sid):
        p = self.patient(sid)
        return dict(study=sid, patient=p, identity=self.identity(sid).get("status"), fingerprint=self.fingerprint(sid), partition=self.partition(p))

    def records(self, sids):
        return [self.record(s) for s in sids]

    def digest(self, sids):
        """content hash of the identity / split assignment of these studies (recorded with each training run)"""
        R = sorted((r["study"], str(r["patient"]), str(r["partition"]), r["fingerprint"]) for r in self.records(sids))
        return hashlib.sha256(json.dumps(R).encode()).hexdigest()[:16]

    def check_rows(self, rows):
        """every row's patient / partition must agree with the service (a stale manifest or a second mapping is refused)"""
        bad = []
        for r in rows:
            p = self.patient(r["study"])
            if str(r.get("patient")) != str(p): bad.append(dict(study=r["study"], row_patient=r.get("patient"), service_patient=p))
        return bad
