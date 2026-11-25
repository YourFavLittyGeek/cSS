"""Background jobs with live progress (setup Finish, study import): the work runs in a thread so the window never freezes, and the
front-end polls GET /api/job?id=... for state / done/total / current step label / elapsed / estimated remaining time.

A job is created with start(kind, total, fn, title=...); fn(rep) does the work and calls rep(done, label[, total]) after each step and returns
a JSON-serialisable result dict. Remaining time = average time of the finished steps x steps left (None until one step has finished).
Jobs are kept in memory only (they describe this app session); the last 30 are retained."""
import threading
import time
import traceback
import uuid

LOCK = threading.Lock()
JOBS = {}
_ORDER = []


def _public(j):
    now = time.time(); el = round((j.get("ended") or now) - j["started"], 1)
    done, total = j["done"], max(j["total"], 1)
    eta = None
    if j["state"] == "running" and done > 0:
        eta = round(max(0.0, (now - j["started"]) / done * (total - done)), 1)
    return dict(id=j["id"], kind=j["kind"], title=j["title"], state=j["state"], done=done, total=j["total"], label=j["label"],
                elapsed_s=el, eta_s=eta, pct=round(100.0 * min(done, total) / total, 1) if j["state"] != "done" else 100.0,
                result=j.get("result"), error=j.get("error", ""), steps=list(j["steps"][-12:]))


def start(kind, total, fn, title=""):
    jid = f"{kind}-{uuid.uuid4().hex[:10]}"
    j = dict(id=jid, kind=kind, title=title or kind, state="running", done=0, total=int(total), label="starting…",
             started=time.time(), ended=None, steps=[])
    with LOCK:
        JOBS[jid] = j; _ORDER.append(jid)
        while len(_ORDER) > 30: JOBS.pop(_ORDER.pop(0), None)

    def rep(done, label="", total=None, log=True):
        with LOCK:
            if total is not None: j["total"] = int(total)
            j["done"] = int(done)
            if label:
                j["label"] = label
                if log: j["steps"].append(dict(t=round(time.time() - j["started"], 1), done=int(done), label=label))

    def run():
        try:
            res = fn(rep)
            with LOCK:
                j["result"] = res
                failed = isinstance(res, dict) and res.get("ok") is False
                j["state"] = "failed" if failed else "done"; j["error"] = (res or {}).get("error", "") if failed else ""
                if not failed: j["done"] = j["total"]; j["label"] = (res or {}).get("summary") or "finished"
        except Exception as e:
            with LOCK:
                j["state"] = "failed"; j["error"] = f"{type(e).__name__}: {e}"[-400:]; j["trace"] = traceback.format_exc()[-2000:]
        finally:
            with LOCK: j["ended"] = time.time()

    threading.Thread(target=run, daemon=True, name=f"job-{jid}").start()
    return jid


def get(jid):
    with LOCK:
        j = JOBS.get(jid)
        return _public(j) if j else dict(id=jid, state="unknown", error="no such job (the app was restarted?)")


def running(kind=None):
    with LOCK:
        return [_public(j) for j in JOBS.values() if j["state"] == "running" and (kind is None or j["kind"] == kind)]
