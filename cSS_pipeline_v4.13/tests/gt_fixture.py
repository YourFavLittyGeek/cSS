"""gt_fixture.py - Phase 3A TEST FIXTURE (never used by the application).

Synthetic Percival / learning tests build their labels from plain reviewer calls files written by the test itself (no journal, no read phase).
Under Phase 3A such labels are pre-3A history: they count only when (1) the reviewer is a designated expert and (2) a documented blinding
verification exists. ground_truth() records exactly those two things through the real administration functions (typed confirmations, reasons,
append-only history), so the tests keep exercising learning without weakening any rule."""
import glob, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import review_roles as RR  # noqa: E402


def reviewer_names(base):
    import pandas as pd
    out = set()
    for p in glob.glob(os.path.join(base, "review", "*_calls_*.csv")):
        try:
            d = pd.read_csv(p); names = {str(x).strip() for x in d.get("reviewer", pd.Series(dtype=str)).dropna() if str(x).strip()}
        except Exception: names = set()
        out |= names or {os.path.basename(p).split("_calls_", 1)[1][:-4]}
    return sorted(out)


def ground_truth(base, reviewers=None, studies=None):
    reviewers = reviewer_names(base) if reviewers is None else reviewers
    for r in reviewers: RR.set_role(base, r, "expert", "test fixture", "synthetic expert reviewer (test)", RR.CONFIRM_ROLE)
    if studies is None:
        studies = sorted({os.path.basename(p).split("_calls_")[0] for p in glob.glob(os.path.join(base, "review", "*_calls_*.csv"))})
    for sid in studies:
        for r in reviewers:
            RR.verify_historical(base, sid, r, "test fixture", "synthetic labels of a test", "synthetic blind labels written by the test", RR.CONFIRM_VERIFY)
    return studies
