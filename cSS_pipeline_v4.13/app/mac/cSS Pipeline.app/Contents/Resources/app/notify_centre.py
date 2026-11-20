"""Local notification centre (v5.14.2-rc4, sketch v2/v3). app_data/notifications.json - nothing leaves the Mac.
Levels: urgent (action required, urgent) | action (action required) | done (finished & changes). "Running" items are not stored:
the app builds them live from the jobs in progress. Every item can be removed (kept in the log) or snoozed."""
import os, json, time, threading, uuid
_LOCK = threading.Lock()
DEFAULTS = dict(snooze_min=5, sections=dict(urgent=True, action=True, running=True, done=True),
                sources=dict(processing=True, imports=True, training=True, exports=True, reviews=True),
                badge="action", banner="urgent", clear_days=7, hover=True)

def _p(B): return os.path.join(B, "app_data", "notifications.json")
def _load(B):
    try: return json.load(open(_p(B)))
    except Exception: return []
def _save(B, items):
    t = _p(B) + ".tmp"; os.makedirs(os.path.dirname(t), exist_ok=True); json.dump(items, open(t, "w"), indent=1); os.replace(t, _p(B))

def add(B, level, source, title, text="", actions=None, key=None, study=None):
    """key: one live item per recurring condition (e.g. 'stale:M05'); an existing undismissed item with the same key is updated, a
    removed one comes back only after its snooze period (urgent conditions that still hold)"""
    with _LOCK:
        items = _load(B); now = time.time()
        if key:
            for it in items:
                if it.get("key") == key and not it.get("resolved"):
                    if it.get("removed") and it.get("level") == "urgent" and now >= it.get("snooze_until", 0):
                        it["removed"] = False
                    it.update(title=title, text=text, actions=actions or [], t_update=now); _save(B, items); return it["id"]
        it = dict(id=uuid.uuid4().hex[:12], t=now, level=level, source=source, title=title, text=text, actions=actions or [], key=key, study=study,
                  read=False, removed=False, snooze_until=0)
        items.append(it); _save(B, items); return it["id"]

def resolve(B, key):
    """the condition behind a keyed item no longer holds"""
    with _LOCK:
        items = _load(B); ch = False
        for it in items:
            if it.get("key") == key and not it.get("resolved"): it["resolved"] = True; it["removed"] = True; ch = True
        if ch: _save(B, items)

def visible(B, settings):
    S = dict(DEFAULTS, **(settings or {})); now = time.time(); keep = S["clear_days"]
    with _LOCK:
        items = _load(B)
        if keep and keep != "never":
            items2 = [i for i in items if not (i["level"] == "done" and now - i["t"] > float(keep) * 86400)]
            if len(items2) != len(items): _save(B, items2); items = items2
    out = [i for i in items if not i.get("removed") and now >= i.get("snooze_until", 0) and S["sections"].get(i["level"], True)
           and S["sources"].get(i.get("source", ""), True)]
    return sorted(out, key=lambda i: -i.get("t_update", i["t"]))

def act(B, nid, op, minutes=None):
    with _LOCK:
        items = _load(B)
        for it in items:
            if it["id"] == nid or nid == "*":
                if op == "remove": it["removed"] = True; it["snooze_until"] = time.time() + 60 * float(minutes or 5)
                elif op == "snooze": it["snooze_until"] = time.time() + 60 * float(minutes or 5)
                elif op == "read": it["read"] = True
        _save(B, items)

def log(B): return sorted(_load(B), key=lambda i: -i["t"])

def clear_removed(B):
    with _LOCK: _save(B, [i for i in _load(B) if not i.get("removed")])
