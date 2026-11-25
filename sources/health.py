"""Per-store health: notices when a store's website changes, and keeps the app working meanwhile.

For each store we remember the last 40 page reads (worked / failed), which reading strategy works,
and when it last worked. A store whose recent reads mostly fail is marked "degraded": the app then
shows last known prices (marked as old) and leans on the Google fallback, instead of breaking.
"""
import json
import os
import threading
import time

from .common import DATA_DIR

PATH = os.path.join(DATA_DIR, "health.json")
WINDOW = 40
_lock = threading.Lock()
try:
    with open(PATH, encoding="utf-8") as f:
        _d = json.load(f)
except Exception:
    _d = {}
_dirty = [0.0]


def _s(store_id):
    return _d.setdefault(store_id, {"recent": [], "methods": {}, "last_ok": None, "last_fail": None,
                                    "fail_reasons": {}, "gone": 0})


def record(store_id, ok, method=None, reason=None):
    with _lock:
        s = _s(store_id)
        s["recent"] = (s["recent"] + [1 if ok else 0])[-WINDOW:]
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        if ok:
            s["last_ok"] = now
            if method:
                s["methods"][method] = s["methods"].get(method, 0) + 1
        else:
            s["last_fail"] = now
            if reason:
                s["fail_reasons"][reason] = s["fail_reasons"].get(reason, 0) + 1
        _save()


def gone(store_id):
    with _lock:
        _s(store_id)["gone"] += 1
        _save()


def preferred(store_id):
    """The strategy that has worked most for this store (tried first next time)."""
    m = _d.get(store_id, {}).get("methods") or {}
    return max(m, key=m.get) if m else None


def state(store_id):
    s = _d.get(store_id)
    if not s or len(s["recent"]) < 8:
        return "ok"
    rate = sum(s["recent"]) / len(s["recent"])
    return "degraded" if rate < 0.5 else "ok"


def summary():
    out = {}
    for k, s in _d.items():
        r = s["recent"]
        out[k] = {"state": state(k), "success": round(sum(r) / len(r), 2) if r else None, "reads": len(r),
                  "method": preferred(k), "last_ok": s["last_ok"], "last_fail": s["last_fail"],
                  "fail_reasons": s["fail_reasons"], "gone": s["gone"]}
    return out


def _save():
    # at most every 5 seconds; health is advisory, losing the last few reads is fine
    if time.time() - _dirty[0] < 5:
        return
    _dirty[0] = time.time()
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_d, f)
    os.replace(tmp, PATH)
