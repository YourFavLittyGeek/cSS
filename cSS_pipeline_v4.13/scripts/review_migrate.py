#!/usr/bin/env python3
"""review_migrate.py - Phase 3A.6: migration of existing reviews to the protected ground-truth storage. Research software. Reads $CSS_BASE.

  review_migrate.py plan                                        READ-ONLY report (nothing is written)
  review_migrate.py apply --by NAME --confirm "MIGRATE REVIEWS" originals copied + checksummed + verified FIRST, then:
        - every reviewer calls file without a journal gets a 'baseline' journal event holding its exact content (provenance starts here)
        - a pre-3A shared missed-cSS file is kept unchanged as review/ID_missed_legacy.csv (read-only legacy source)
        - every reviewer of every study gets a recorded historical classification: historical_blinding_unknown (default); the evidence
          (final record read mode / meter visibility) is stored, but NOTHING is verified automatically - verification is a separate, explicit
          step (review_admin.py verify ...) and adjudication another
        - call_policy.json is rewritten as call-policy/2.0 (expert consensus; the old rules stay in its history and in the backup)
        - roles are NOT assigned: every reviewer stays 'unknown' until the administrator assigns roles
  review_migrate.py rollback TIMESTAMP --confirm "ROLL BACK MIGRATION"   originals restored byte-for-byte, files the migration created removed
Running apply again on a migrated project does nothing (idempotent). Original files are never edited: only new files / journal lines are added."""
import datetime, glob, hashlib, json, os, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import call_ledger as CL, review_io as RIO, review_roles as RR

CONFIRM, CONFIRM_ROLLBACK = "MIGRATE REVIEWS", "ROLL BACK MIGRATION"
MIGRATION = "(migration)"


def _sha(p):
    with open(p, "rb") as f: return hashlib.sha256(f.read()).hexdigest()


def studies(base):
    out = set()
    for p in glob.glob(os.path.join(base, "review", "*_candidates.csv")) + glob.glob(os.path.join(base, "review", "*_calls*.csv")):
        sid = os.path.basename(p).split("_candidates.csv")[0].split("_calls")[0]
        try: out.add(RIO.check_sid(sid))
        except ValueError: pass
    return sorted(out)


def _review_files(base):
    rd = os.path.join(base, "review")
    return sorted(p for p in glob.glob(os.path.join(rd, "*")) + glob.glob(os.path.join(base, "historical", "*", "review", "*"))
                  if os.path.isfile(p) and not os.path.basename(p).startswith(".")) if os.path.isdir(rd) else []


def _finals(base, sid):
    out = {}
    for p in glob.glob(os.path.join(base, "review", f"{sid}_final_*.json")):
        try: j = json.load(open(p))
        except Exception: continue
        out[RR.slug(j.get("reviewer") or os.path.basename(p)[len(sid) + 7:-5])] = dict(reviewer=j.get("reviewer", ""), read_mode=j.get("read_mode", ""),
                                                                                    meter_visible=j.get("meter_visible", ""), saved=j.get("saved", ""))
    return out


def _newest_count(E):
    return sum(1 for r in E["rows"] if r["history"])                         # what newest-wins made effective: every called candidate


def plan(base):
    """READ-ONLY: what apply would do, per study"""
    rep = dict(base=base, time=datetime.datetime.now().isoformat(timespec="seconds"), studies=[], files=[], roles=RR.current(base),
               policy_schema=(json.load(open(CL.policy_path(base))).get("schema") if os.path.exists(CL.policy_path(base)) else None), migrated=_state(base))
    for p in _review_files(base): rep["files"].append(dict(file=os.path.relpath(p, base), sha256=_sha(p), size=os.path.getsize(p)))
    for sid in studies(base):
        pre = os.path.join(base, "review", f"{sid}_calls_"); revs = []
        for p in sorted(glob.glob(pre + "*.csv")):
            fs = p[len(pre):-4]; st = RIO.check_table(base, sid, fs, "calls", p)
            revs.append(dict(file=os.path.basename(p), slug=fs, journal=st["status"], role=RR.role_of(base, fs)))
        fin = _finals(base, sid)
        for r in revs:
            f = fin.get(r["slug"], {}); r["final"] = f
            r["proposed_class"] = "historical_blinding_unknown"
            r["verification_candidate"] = bool(f) and f.get("read_mode") == "validation" and str(f.get("meter_visible")) in ("0", "False", "false")
        legacy_shared = os.path.exists(os.path.join(base, "review", f"{sid}_calls.csv")) and not revs
        mshared = os.path.join(base, "review", f"{sid}_missed.csv")
        try: E = CL.effective(base, sid); eff_new = sum(1 for r in E["rows"] if r["effective_call"]); eff_old = _newest_count(E); probs = E["problems"]
        except Exception as e: E, eff_new, eff_old, probs = None, None, None, [f"{type(e).__name__}: {e}"]
        rep["studies"].append(dict(study=sid, reviewers=revs, legacy_shared_calls_only=legacy_shared,
                                   missed_shared=os.path.exists(mshared), missed_legacy_exists=os.path.exists(os.path.join(base, "review", f"{sid}_missed_legacy.csv")),
                                   effective_before_newest=eff_old, effective_after_consensus=eff_new, problems=probs,
                                   note="effective calls after = with the CURRENT roles; assign expert roles to restore resolved ground truth"))
    rep["warnings"] = ["roles are not assigned by the migration: until experts are designated, no candidate is resolved",
                       "historical labels stay 'historical_blinding_unknown' (not primary training ground truth) until verified or adjudicated"]
    return rep


def _state(base):
    p = os.path.join(base, "review", "migration", "state.json")
    return json.load(open(p)) if os.path.exists(p) else dict(runs=[])


def apply(base, by, confirm):
    if confirm != CONFIRM: raise PermissionError(f"refused: type exactly '{CONFIRM}' to confirm")
    if not str(by or "").strip(): raise ValueError("refused: your name is required")
    st = _state(base)
    if any(r.get("status") == "complete" and not r.get("rolled_back") for r in st["runs"]): return dict(ok=True, noop=True, note="already migrated")
    with RIO.project_lock(base, "migration"):
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S"); md = os.path.join(base, "review", "migration", ts); od = os.path.join(md, "originals")
        before = {os.path.relpath(p, base) for p in _review_files(base)}
        man = []
        for p in _review_files(base):                                         # 1. originals first, verified
            rel = os.path.relpath(p, base); dst = os.path.join(od, rel); os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(p, dst)
            if _sha(dst) != _sha(p): raise RuntimeError(f"backup copy differs: {rel} - nothing migrated")
            man.append(dict(file=rel, sha256=_sha(p), size=os.path.getsize(p)))
        RIO.atomic_write_json(os.path.join(md, "manifest.json"), dict(time=ts, by=by, originals=man))
        report = dict(time=ts, by=by, studies=[])
        for sid in studies(base):
            with RIO.study_lock(base, sid):
                pre = os.path.join(base, "review", f"{sid}_calls_"); fin = _finals(base, sid); done = dict(study=sid, baselines=[], classified=[])
                for p in sorted(glob.glob(pre + "*.csv")):                    # 2. provenance starts with the exact content
                    fs = p[len(pre):-4]
                    if not any(e.get("table") == "calls" for e in RIO.read_journal(RIO.journal_path(base, sid, fs))[0]):
                        txt = open(p, "rb").read()
                        RIO.journal_append(base, sid, fs, "baseline", table="calls", file=os.path.relpath(p, base), snapshot=txt.decode("utf-8", "replace"),
                                           file_sha256=hashlib.sha256(txt).hexdigest(), note=f"migration {ts}: content before Phase 3A")
                        done["baselines"].append(os.path.basename(p))
                    f = fin.get(fs, {})
                    RIO.journal_append(base, sid, MIGRATION, "historical_classification", reviewer_slug=fs, klass="historical_blinding_unknown",
                                       evidence=f, verification_candidate=bool(f) and f.get("read_mode") == "validation" and str(f.get("meter_visible")) in ("0", "False", "false"),
                                       note="not verified: use review_admin.py verify (documented) or adjudication")
                    done["classified"].append(fs)
                ms, ml = os.path.join(base, "review", f"{sid}_missed.csv"), os.path.join(base, "review", f"{sid}_missed_legacy.csv")
                if os.path.exists(ms) and not os.path.exists(ml) and not os.path.exists(os.path.join(base, "review", f"{sid}_missed.derived.json")):
                    RIO.atomic_copy(ms, ml); done["missed_legacy"] = os.path.basename(ml)          # 3. legacy missed marks kept as recorded
                    RIO.journal_append(base, sid, MIGRATION, "missed_legacy_preserved", file=os.path.relpath(ml, base), file_sha256=_sha(ml))
                report["studies"].append(done)
        P = CL.load_policy(base)                                              # 4. policy file -> 2.0 (old rules in history + backup)
        if os.path.exists(CL.policy_path(base)) and json.load(open(CL.policy_path(base))).get("schema") != CL.POLICY_V2:
            P["history"].append(dict(time=CL._now(), scope="all", target="", rule=P["default"], by=by, note=f"migration {ts}: call-policy/1.0 -> 2.0"))
            RIO.atomic_write_json(CL.policy_path(base), P); report["policy"] = "migrated to call-policy/2.0"
        created = sorted({os.path.relpath(p, base) for p in _review_files(base)} - before - {os.path.relpath(p, base) for p in glob.glob(os.path.join(md, "**"), recursive=True)})
        report["created"] = created
        RIO.atomic_write_json(os.path.join(md, "report.json"), report)
        st["runs"].append(dict(time=ts, by=by, status="complete", created=created))
        RIO.atomic_write_json(os.path.join(base, "review", "migration", "state.json"), st)
    return dict(ok=True, time=ts, report=report)


def rollback(base, ts, confirm):
    if confirm != CONFIRM_ROLLBACK: raise PermissionError(f"refused: type exactly '{CONFIRM_ROLLBACK}' to confirm")
    md = os.path.join(base, "review", "migration", os.path.basename(ts)); man = json.load(open(os.path.join(md, "manifest.json")))
    st = _state(base); run = next((r for r in st["runs"] if r["time"] == man["time"]), None)
    with RIO.project_lock(base, "migration"):
        for rel in (run or {}).get("created", []):
            p = os.path.join(base, rel)
            if os.path.isfile(p): os.remove(p)
        for o in man["originals"]:
            src = os.path.join(md, "originals", o["file"])
            if _sha(src) != o["sha256"]: raise RuntimeError(f"backup damaged: {o['file']} - stopped")
            RIO.atomic_copy(src, os.path.join(base, o["file"]))
        if run: run["rolled_back"] = CL._now()
        RIO.atomic_write_json(os.path.join(base, "review", "migration", "state.json"), st)
    return dict(ok=True, restored=len(man["originals"]), removed=len((run or {}).get("created", [])))


if __name__ == "__main__":
    a = sys.argv[1:]; base = os.environ.get("CSS_BASE", os.path.expanduser("~/css_project"))
    arg = lambda k: a[a.index(k) + 1] if k in a and a.index(k) + 1 < len(a) else ""
    try:
        if a[:1] == ["plan"]: print(json.dumps(plan(base), indent=1, default=str))
        elif a[:1] == ["apply"]: print(json.dumps(apply(base, arg("--by"), arg("--confirm")), indent=1, default=str))
        elif a[:1] == ["rollback"] and len(a) > 1: print(json.dumps(rollback(base, a[1], arg("--confirm")), indent=1))
        else: sys.exit(__doc__)
    except (PermissionError, ValueError, RuntimeError) as e: sys.exit(str(e))
