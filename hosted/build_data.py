"""Build hosted/data.json for the hosted page from everything the app has read so far
(the per-page "last good" cache), so the page can be published or refreshed at any time.

    py hosted/build_data.py
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import smart  # noqa: E402
from sources import direct  # noqa: E402
from sources.common import DATA_DIR  # noqa: E402
from sources.stores import LOCAL_STORES  # noqa: E402

MAX_AGE_DAYS = 7  # older readings are left out of the hosted page


def load(name):
    try:
        with open(os.path.join(DATA_DIR, name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def main():
    pages = load("direct_lastgood.json")   # url -> [time, product]
    index = load("direct_index.json")      # store_id -> [time, [entries]]
    now = time.time()
    by_url = {}
    for st in LOCAL_STORES:
        for e in (index.get(st["id"]) or [0, []])[1]:
            by_url[e["url"]] = (st, e)
    items, per_store = [], {}
    for url, (ts, r) in pages.items():
        if url not in by_url or not r.get("price") or now - ts > MAX_AGE_DAYS * 86400:
            continue
        st, e = by_url[url]
        title = r.get("title") or e["name"]
        items.append({
            "t": title, "p": r["price"], "pm": r.get("price_max"), "s": st["name"], "u": url,
            "i": r.get("image") if str(r.get("image") or "").startswith("https://") else None,
            "r": r.get("rating"), "n": r.get("reviews"), "g": 1 if st.get("guide") else 0,
            "o": 1 if r.get("in_stock") is False else 0, "a": smart.attributes(title),
            "k": direct._url_category(url).lower()[-60:],
        })
        per_store[st["name"]] = per_store.get(st["name"], 0) + 1
    items.sort(key=lambda d: (d["s"], d["t"]))
    # which stores were read, skipped or blocked in the last snapshot run
    status = {}
    try:
        with open(os.path.join(DATA_DIR, "snapshot_progress.txt"), encoding="utf-8") as f:
            for line in f:
                if ": " in line:
                    k, v = line.rstrip("\n").split(": ", 1)
                    status[k] = v
    except OSError:
        pass
    out = os.path.join(sys.argv[1] if len(sys.argv) > 1 else HERE, "data.json")
    with open(out, "w", encoding="utf-8") as f:
        f.write('{"time":%s,"stores":%s,"status":%s,"items":[\n' % (
            json.dumps(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())), json.dumps(per_store), json.dumps(status)))
        f.write(",\n".join(json.dumps(d, ensure_ascii=False, separators=(",", ":")) for d in items))
        f.write("\n]}\n")
    print(f"{len(items)} products -> {out}", per_store, f"{os.path.getsize(out) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
