"""Collect a full price snapshot from every store that this network can read, for the hosted (static) version.

    py snapshot.py            # writes data/snapshot.json

Same polite rules as the live app: robots.txt, sitemap only, max 2 requests at a time per store,
at least 0.5 s apart, cached pages reused. Stores that are blocked here are skipped.
"""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import smart
from sources import direct
from sources.common import DATA_DIR
from sources.stores import LOCAL_STORES

OUT = os.path.join(DATA_DIR, "snapshot.json")
# limits per store (GitHub Actions sets these; 0 = no limit)
MAX_PAGES = int(os.environ.get("SNAPSHOT_MAX_PAGES", "0") or 0)
MAX_MINUTES = float(os.environ.get("SNAPSHOT_MAX_MINUTES", "0") or 0)
PROGRESS = os.path.join(DATA_DIR, "snapshot_progress.txt")
_progress = {}


def _log():
    with open(PROGRESS, "w", encoding="utf-8") as f:
        for k, v in _progress.items():
            f.write(f"{k}: {v}\n")


def crawl(store):
    try:
        idx = direct.ensure_index(store, wait=True)
    except direct.StoreError as e:
        _progress[store["name"]] = f"skipped ({e.note})"
        _log()
        return []
    out, done = [], 0
    if MAX_PAGES:
        idx = idx[:MAX_PAGES]
    t_end = time.time() + MAX_MINUTES * 60 if MAX_MINUTES else None

    def one(e):
        try:
            return e, direct._page(store, e)
        except direct.StoreError as err:
            return e, err

    pool = ThreadPoolExecutor(max_workers=2)
    try:
        for e, r in pool.map(one, idx):
            done += 1
            if t_end and time.time() > t_end:
                _progress[store["name"]] = f"time limit at {done}/{len(idx)} pages, {len(out)} priced"
                _log()
                break
            if done % 50 == 0 or done == len(idx):
                _progress[store["name"]] = f"{done}/{len(idx)} pages, {len(out)} priced"
                _log()
            if isinstance(r, direct.StoreError):
                if r.status in ("blocked", "refused"):
                    _progress[store["name"]] = f"stopped at {done}/{len(idx)} ({r.note})"
                    _log()
                    break
                continue
            if not isinstance(r, dict) or not r.get("price"):
                continue
            a = smart.attributes(r.get("title") or e["name"])
            out.append({
                "t": r.get("title") or e["name"], "p": r["price"], "pm": r.get("price_max"),
                "c": r.get("currency") or "PKR", "s": store["name"], "u": e["url"],
                "i": r.get("image"), "r": r.get("rating"), "n": r.get("reviews"),
                "g": 1 if store.get("guide") else 0, "o": 1 if r.get("in_stock") is False else 0,
                "a": a, "k": direct._url_category(e["url"]).lower()[-60:],
            })
    finally:
        # map() queued every page up front: cancel what has not started once we stop early
        pool.shutdown(wait=True, cancel_futures=True)
    return out


def main():
    stores = [s for s in LOCAL_STORES if len(sys.argv) < 2 or s["id"] in sys.argv[1:]]
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=len(stores)) as ex:
        results = list(ex.map(crawl, stores))
    items = [x for r in results for x in r]
    snap = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "count": len(items),
            "stores": {k: v for k, v in _progress.items()}, "items": items}
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, OUT)
    print(f"{len(items)} products in {time.time() - t0:.0f}s -> {OUT}")
    for k, v in _progress.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
