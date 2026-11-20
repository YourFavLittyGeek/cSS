"""patient_split.py - patient keys, repeat examinations and patient-grouped partitions.

Rules enforced here:
  - the unit of every split is the PATIENT (patient_key), never the examination or the candidate;
  - an examination -> patient mapping must be supplied explicitly. Without one, splitting is refused unless the caller passes
    assume_one_exam_per_patient=True, which is recorded in the assignment as an UNVERIFIED assumption (a Gate B blocker);
  - a protected test set is a frozen list of patient keys with a hash; no development fold may contain one of them;
  - every assignment is an explicit table patient -> (repeat, fold), reproducible from the seed.
Partitions are stratified on the patient-level reference (positive / negative patient) when it is given, so that every fold has
both kinds of patients where possible."""
import hashlib, json
from dataclasses import dataclass, field
import numpy as np


class SplitError(RuntimeError): pass


@dataclass
class PatientKeyMap:
    exam_to_patient: dict
    verified: bool
    note: str = ""

    @staticmethod
    def from_table(rows, exam_col="exam_id", patient_col="patient_key"):
        m = {}
        for r in rows:
            e, p = str(r[exam_col]), str(r[patient_col])
            if not p or p.lower() in ("nan", "none"): raise SplitError(f"exam {e}: empty patient key")
            if e in m and m[e] != p: raise SplitError(f"exam {e} mapped to two patients ({m[e]}, {p})")
            m[e] = p
        return PatientKeyMap(m, True, "explicit mapping")

    @staticmethod
    def assume_one_exam_per_patient(exams):
        return PatientKeyMap({str(e): f"ASSUMED:{e}" for e in exams}, False,
                             "UNVERIFIED ASSUMPTION: every examination is a different patient (no patient-key mapping supplied)")

    def patients(self, exams):
        miss = sorted({str(e) for e in exams} - set(self.exam_to_patient))
        if miss: raise SplitError(f"examinations without a patient key: {miss[:10]}{' ...' if len(miss) > 10 else ''}")
        return np.array([self.exam_to_patient[str(e)] for e in exams])

    def repeat_exams(self):
        inv = {}
        for e, p in self.exam_to_patient.items(): inv.setdefault(p, []).append(e)
        return {p: sorted(es) for p, es in inv.items() if len(es) > 1}


def keymap_or_refuse(exams, mapping=None, assume_one_exam_per_patient=False):
    if mapping is not None: return mapping
    if assume_one_exam_per_patient: return PatientKeyMap.assume_one_exam_per_patient(sorted(set(map(str, exams))))
    raise SplitError("no examination -> patient mapping: repeat examinations could cross partitions. Supply a PatientKeyMap, or pass "
                     "assume_one_exam_per_patient=True knowingly (recorded as an unverified assumption).")


@dataclass
class ProtectedTestSet:
    patients: tuple
    sha256: str = ""

    def __post_init__(self):
        self.patients = tuple(sorted(set(map(str, self.patients))))
        h = hashlib.sha256(json.dumps(self.patients).encode()).hexdigest()
        if self.sha256 and self.sha256 != h: raise SplitError("protected test set: hash does not match the patient list (list edited)")
        self.sha256 = h


@dataclass
class Assignment:
    """explicit patient -> fold table for R repeats of K-fold grouped CV"""
    folds: dict                        # (repeat, patient) -> fold index
    n_splits: int
    n_repeats: int
    seed: int
    keymap_verified: bool
    keymap_note: str
    protected: str = ""                # sha256 of the protected test set kept out of every fold ('' = none)
    notes: list = field(default_factory=list)

    def table(self):
        return [dict(repeat=r, patient_key=p, fold=f) for (r, p), f in sorted(self.folds.items())]

    def digest(self):
        return hashlib.sha256(json.dumps(self.table(), sort_keys=True).encode()).hexdigest()


def grouped_folds(patients, n_splits=5, n_repeats=1, seed=0, patient_label=None, protected: ProtectedTestSet = None,
                  keymap_verified=True, keymap_note=""):
    """patient-level K-fold, stratified on patient_label (dict patient -> 0/1) when given; repeated with seeds seed, seed+1, ..."""
    pats = sorted(set(map(str, patients)))
    if protected is not None:
        clash = sorted(set(pats) & set(protected.patients))
        if clash: raise SplitError(f"protected test patients present in the development data: {clash[:5]}")
    if len(pats) < n_splits: raise SplitError(f"{len(pats)} patients < {n_splits} folds")
    folds, notes = {}, []
    for r in range(n_repeats):
        rng = np.random.default_rng(seed + r)
        strata = {}
        for p in pats: strata.setdefault(int(patient_label.get(p, 0)) if patient_label else 0, []).append(p)
        k = 0
        for s in sorted(strata):
            g = list(strata[s]); rng.shuffle(g)
            for p in g: folds[(r, p)] = k % n_splits; k += 1
        if patient_label:
            for f in range(n_splits):
                labs = {int(patient_label.get(p, 0)) for (rr, p), ff in folds.items() if rr == r and ff == f}
                if len(labs) < 2: notes.append(f"repeat {r} fold {f}: only {'positive' if labs == {1} else 'negative'} patients")
    return Assignment(folds, n_splits, n_repeats, seed, keymap_verified, keymap_note, protected.sha256 if protected else "", notes)


def fold_indices(assignment, row_patients, repeat):
    """-> list of (train_idx, test_idx) for one repeat; asserts no patient is on both sides"""
    rp = np.asarray(row_patients).astype(str); f = np.array([assignment.folds[(repeat, p)] for p in rp])
    out = []
    for k in range(assignment.n_splits):
        te = np.where(f == k)[0]; tr = np.where(f != k)[0]
        if set(rp[te]) & set(rp[tr]): raise SplitError("a patient is in both the training and the test part")
        out.append((tr, te))
    return out


def inner_folds(row_patients, n_splits, seed, patient_label=None):
    """patient-grouped folds INSIDE a training part (for nested selection)"""
    pats = sorted(set(map(str, row_patients)))
    k = min(n_splits, len(pats))
    a = grouped_folds(pats, k, 1, seed, {p: patient_label[p] for p in pats} if patient_label else None)
    return fold_indices(a, row_patients, 0)
