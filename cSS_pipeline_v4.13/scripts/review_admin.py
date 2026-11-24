#!/usr/bin/env python3
"""review_admin.py - Phase 3A: local administration of the expert ground truth (roles, adjudication, documented verification, policy).
Every change needs the typed confirmation phrase and a reason, and is kept in an append-only, hash-chained history. Reads $CSS_BASE.

  review_admin.py roles
  review_admin.py role "NAME" expert|trainee|other|unknown --by ADMIN --reason TEXT --confirm "ASSIGN ROLE"
  review_admin.py adjudicator "NAME" on|off --by ADMIN --reason TEXT --confirm "GRANT ADJUDICATION"
  review_admin.py status STUDY                      per-candidate status / provenance / eligibility (read only)
  review_admin.py adjudicate STUDY CAND CALL --adjudicator "NAME" --reason TEXT
  review_admin.py verify STUDY "REVIEWER" --by ADMIN --reason TEXT --evidence TEXT --confirm "VERIFY BLINDING"
  review_admin.py policy consensus [--quorum N] | reference "EXPERT" [--fallback none|consensus]  [--scope all|cohort|study --target X] --by ADMIN"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import call_ledger as CL, review_roles as RR


def arg(a, k, d=""):
    return a[a.index(k) + 1] if k in a and a.index(k) + 1 < len(a) else d


def main(a):
    base = os.environ.get("CSS_BASE", os.path.expanduser("~/css_project"))
    if not a: sys.exit(__doc__)
    c = a[0]
    if c == "roles": print(json.dumps(RR.current(base), indent=1)); return
    if c == "role": r = RR.set_role(base, a[1], a[2], arg(a, "--by"), arg(a, "--reason"), arg(a, "--confirm")); print(f"{a[1]}: {a[2]} (recorded)"); return r
    if c == "adjudicator":
        r = RR.set_adjudicator(base, a[1], a[2] == "on", arg(a, "--by"), arg(a, "--reason"), arg(a, "--confirm")); print(f"{a[1]}: adjudication {a[2]} (recorded)"); return r
    if c == "status":
        E = CL.effective(base, a[1])
        print(f"{a[1]}: {E['rule_text']}" + (f"  PROBLEMS: {E['problems']}" if E["problems"] else ""))
        for r in E["rows"]:
            print(f"  #{r['cand_id']:>4} {r['status']:<13} {r['effective_call'] or '-':<10} {r['provenance_class'] or '-':<30} primary={'yes' if r['primary_eligible'] else 'no'}  "
                  + ", ".join(f"{e['reviewer']}({e['role']}{',pre-filled' if e['prefilled'] else ''}):{e['call']}" for e in r["history"]))
        return E
    if c == "adjudicate":
        r = CL.adjudicate(base, a[1], int(a[2]), a[3], arg(a, "--adjudicator"), arg(a, "--reason")); CL.materialize(base, a[1], by=arg(a, "--adjudicator"))
        print(f"{a[1]} #{a[2]}: adjudicated {a[3]} (recorded)"); return r
    if c == "verify":
        r = RR.verify_historical(base, a[1], a[2], arg(a, "--by"), arg(a, "--reason"), arg(a, "--evidence"), arg(a, "--confirm")); print(f"{a[1]} {a[2]}: blinding verified (recorded)"); return r
    if c == "policy":
        rule = dict(mode="consensus", quorum=int(arg(a, "--quorum", "1"))) if a[1] == "consensus" else dict(mode="reference", reviewer=a[2], fallback=arg(a, "--fallback", "none"))
        P = CL.set_policy(base, arg(a, "--scope", "all"), arg(a, "--target"), rule, by=arg(a, "--by")); print(CL.describe_rule(rule)); return P
    sys.exit(__doc__)


if __name__ == "__main__":
    try: main(sys.argv[1:])
    except (PermissionError, ValueError) as e: sys.exit(str(e))
