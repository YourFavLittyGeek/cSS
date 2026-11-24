"""event_log.py - append-only, hash-chained project events (Stage 5: data authority and provenance).

<store>/events/events.jsonl   one JSON object per line: seq, type, at, actor, payload, prev (sha256 of the previous line), hash
Event types: detection_run, training_run, approval, component_change, rollback, split_created, config_changed.
Derived files are rebuilt FROM the events (replay) and checked against what is on disk (verify): the component registry's active pointers
are reconstructed from component_change / rollback events, so a hand-edited or lost active.json is detected and can be restored.
Nothing here is a source of expert labels - those stay in the reviewer journals (PENSIEVE indexes them; it never becomes a source of truth).
"""
import hashlib
import json
import os
import threading
import time

TYPES = ("detection_run", "training_run", "approval", "component_change", "rollback", "split_created", "config_changed")
_LOCK = threading.Lock()


def _path(store): return os.path.join(store, "events", "events.jsonl")


def _h(s): return hashlib.sha256(s.encode()).hexdigest()


def read(store):
    p = _path(store)
    if not os.path.exists(p): return []
    with open(p) as f: return [json.loads(x) for x in f if x.strip()]


def append(store, etype, actor, **payload):
    """append one event (fsync); never rewrites earlier lines"""
    if etype not in TYPES: raise ValueError(f"unknown event type {etype}")
    p = _path(store); os.makedirs(os.path.dirname(p), exist_ok=True)
    with _LOCK:
        prev = "0" * 64; seq = 0
        if os.path.exists(p):
            with open(p, "rb") as f:
                lines = [x for x in f.read().splitlines() if x.strip()]
            if lines: last = json.loads(lines[-1]); prev, seq = last["hash"], last["seq"] + 1
        ev = dict(seq=seq, type=etype, at=time.strftime("%Y-%m-%d %H:%M:%S"), actor=str(actor or ""), payload=payload, prev=prev)
        ev["hash"] = _h(json.dumps({k: v for k, v in ev.items() if k != "hash"}, sort_keys=True, default=str))
        with open(p, "a") as f: f.write(json.dumps(ev, sort_keys=True, default=str) + "\n"); f.flush(); os.fsync(f.fileno())
    return ev


def verify_chain(store):
    """-> dict(ok, n, broken_at) - every line's hash and link to its predecessor"""
    prev = "0" * 64
    for i, ev in enumerate(read(store)):
        h = _h(json.dumps({k: v for k, v in ev.items() if k != "hash"}, sort_keys=True, default=str))
        if ev.get("prev") != prev or ev.get("hash") != h or ev.get("seq") != i: return dict(ok=False, n=i, broken_at=i)
        prev = ev["hash"]
    return dict(ok=True, n=len(read(store)), broken_at=None)


def replay_registry(store):
    """the component registry's active versions reconstructed from the events: {component: version}"""
    act = {}
    for ev in read(store):
        p = ev["payload"]
        if ev["type"] == "component_change": act[p["component"]] = p["version"]
        elif ev["type"] == "rollback": act[p["component"]] = p["now_active"]
    return act


def verify(store):
    """chain integrity + derived files equal their replay (component registry active pointers)"""
    from uengine.percival import component_registry as CR
    ch = verify_chain(store); rep = replay_registry(store); diffs = []
    for c in CR.COMPONENTS:
        disk = CR.active(store, c)["version"]; ev = rep.get(c, "v000")
        if disk != ev: diffs.append(dict(component=c, on_disk=disk, from_events=ev))
    return dict(chain=ch, registry_matches_events=not diffs, differences=diffs, events=ch["n"],
                types={t: sum(1 for e in read(store) if e["type"] == t) for t in TYPES})


def rebuild_registry(store, by, reason):
    """restore the registry's active pointers from the events (the events are authoritative); logged as a rollback-type correction"""
    from uengine.percival import component_registry as CR
    out = {}
    for c, v in replay_registry(store).items():
        if CR.active(store, c)["version"] != v:
            CR._js(os.path.join(CR._d(store, c), "active.json"), dict(version=v, by=str(by), at=time.strftime("%Y-%m-%d %H:%M:%S"), rebuilt_from_events=True))
            CR._log(store, c, event="rebuilt_from_events", version=v, by=str(by), reason=str(reason)); out[c] = v
    return out
