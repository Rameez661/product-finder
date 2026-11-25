"""Product Finder: search one product, see where it is cheapest and best, tap to open the store.

    py server.py            # http://127.0.0.1:8060
    py server.py --lan      # also reachable from your phone on the same Wi-Fi
"""
import json
import os
import socket
import sys
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.request
from urllib.parse import parse_qs, urlparse

import ml
import rank
import smart
from sources import direct, health, serp
from sources.common import JsonCache, http_get, load_config
from sources.common import norm
from sources.stores import LOCAL_STORES, store_by_word

PORT = 8060
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".json": "application/json",
        ".webmanifest": "application/manifest+json"}
_fx_cache = JsonCache("fx", 6 * 3600)
RESULT_TTL = 20 * 60
DIRECT_LABEL = {"degraded": "site changed", "blocked": "blocked on this network", "refused": "store refused", "robots": "not allowed by robots.txt",
                "indexing": "building list", "error": "error"}
# image proxy: only product thumbnails from these hosts (never an open proxy)
IMG_HOSTS = tuple(d for st in LOCAL_STORES for d in st["domains"]) + (
    "gstatic.com", "googleusercontent.com", "serpapi.com", "lazcdn.com", "slatic.net")
IMG_MAX = 3 * 1024 * 1024
_img_cache = {}
_img_lock = threading.Lock()


def fetch_image(u):
    p = urlparse(u)
    host = (p.hostname or "").lower()
    if p.scheme != "https" or not any(host == h or host.endswith("." + h) for h in IMG_HOSTS):
        raise ValueError("host not allowed")
    with _img_lock:
        hit = _img_cache.get(u)
    if hit:
        return hit
    req = urllib.request.Request(u, headers={"User-Agent": "price-finder/1.0 (personal price comparison)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        body = r.read(IMG_MAX + 1)
    if len(body) > IMG_MAX:
        raise ValueError("too large")
    sig = body[:12]
    ctype = ("image/webp" if sig[:4] == b"RIFF" and sig[8:12] == b"WEBP" else
             "image/jpeg" if sig[:3] == bytes([0xFF, 0xD8, 0xFF]) else
             "image/png" if sig[:4] == bytes([0x89, 0x50, 0x4E, 0x47]) else
             "image/gif" if sig[:4] == b"GIF8" else None)
    if not ctype:
        raise ValueError("not an image")
    with _img_lock:
        if len(_img_cache) > 400:
            _img_cache.clear()
        _img_cache[u] = (ctype, body)
    return ctype, body


def fx_rates():
    """USD-based rates from ExchangeRate-API (open.er-api.com)."""
    r = _fx_cache.get("usd")
    if r:
        return r
    j = json.loads(http_get("https://open.er-api.com/v6/latest/USD"))
    r = {"rates": j["rates"], "time": j.get("time_last_update_utc")}
    _fx_cache.put("usd", r)
    return r


def to_pkr_fn(fx):
    def f(cur):
        cur = (cur or "PKR").upper()
        if cur == "PKR":
            return 1.0
        if not fx or cur not in fx["rates"]:
            return 0.0
        return fx["rates"]["PKR"] / fx["rates"][cur]
    return f


PER_PAGE = 16   # product pages opened per store for each "Load more"
MAX_PAGE = 10
_raw = {}       # (query, tab, page) -> (time, items, stores, has_more); raw, before filtering/ranking
_raw_lock = threading.Lock()


def collect(u, tab, page, key):
    """Raw results of one page: every store in parallel; Google fills in on the first page only."""
    words, text = u["q"], u["q_text"]
    want = {k: u[k] for k in ("category", "budget_min", "budget_max")}
    items, stores, more = [], [], False
    only = u.get("store")  # "zah rtx 4060": search that store only
    with ThreadPoolExecutor(max_workers=len(LOCAL_STORES) + 2) as ex:
        if tab == "local":
            # every store is tried directly, in parallel; each failure becomes a status, never an error
            direct_jobs = {s["id"]: ex.submit(direct.search, s, words, want, (page - 1) * PER_PAGE, PER_PAGE)
                           for s in LOCAL_STORES if not only or s["id"] == only}
            g_job = ex.submit(serp.local, text, key, ()) if key and page == 1 else None
            g_items, g_err = [], None
            if g_job:
                try:
                    g_items, _ = g_job.result()
                except Exception as e:
                    g_err = str(e)[:160]
            for s in LOCAL_STORES:
                if s["id"] not in direct_jobs:
                    continue
                d_items, d_st = direct_jobs[s["id"]].result()
                more = more or bool(d_st.get("more"))
                # Google only fills in for stores that could not be read directly
                use_g = d_st["status"] not in ("ok", "none")
                s_g = [i for i in g_items if i["store_id"] == s["id"]] if use_g else []
                items += d_items + s_g
                status, how, note = d_st["status"], "Direct", d_st["note"]
                if use_g and page == 1:
                    if s_g:
                        status, how = "ok", "via Google"
                        note = f"{len(s_g)} results via Google (direct: {DIRECT_LABEL.get(d_st['status'], d_st['status'])})"
                    elif key and not g_err:
                        note += " · no Google results either"
                    elif g_err:
                        note += f" · Google: {g_err}"
                    else:
                        note += " · a SerpApi key is needed for the fallback"
                stores.append({"name": s["name"], "status": status, "how": how, "note": note,
                               "total": d_st.get("total")})
        elif page == 1:
            if key:
                try:
                    its, st = serp.international(text, key)
                    items += its
                    names = sorted({i["store"] for i in its})
                    stores = [{"name": n, "status": "ok", "how": "Google Shopping",
                               "note": f"{sum(1 for i in its if i['store'] == n)} offers"} for n in names]
                    if not names:
                        stores = [{"name": "Google Shopping", "status": "none", "how": "", "note": st["note"]}]
                except Exception as e:
                    stores = [{"name": "Google Shopping", "status": "error", "how": "", "note": str(e)[:160]}]
            else:
                stores = [{"name": "Amazon, Walmart, Best Buy, eBay, ...", "status": "need_key",
                           "how": "Google Shopping", "note": "SerpApi key needed (see README)"}]
    return items, stores, more


def search(q, tab, page=1, fresh=False):
    """Results for pages 1..page together, filtered and ranked as one list
    (so "Sab se sasta" and "Best deal" are always across everything loaded so far)."""
    key = (load_config().get("serpapi_key") or "").strip()
    t0 = time.time()
    try:
        fx = fx_rates()
    except Exception:
        fx = None
    # a store name in the query ("zah rtx 4060", "pakwheels city") means: search that store only.
    # Found before the spelling fixer runs, so a store name is never "corrected" into a product word.
    only, rest = None, []
    raw_words = q.split()
    for w in raw_words:
        st = store_by_word(norm(w)) if not only and len(raw_words) > 1 else None
        if st:
            only = st
        else:
            rest.append(w)
    u = smart.understand(" ".join(rest) if only else q, smart.vocabulary(direct.ready_indexes()))
    if only:
        u["raw"], u["store"], u["store_name"] = q, only["id"], only["name"]
    base = {"query": q, "tab": tab, "understood": u, "has_key": bool(key),
            "fx": {"usd_pkr": fx["rates"]["PKR"], "time": fx["time"]} if fx else None,
            "time": time.strftime("%Y-%m-%dT%H:%M:%S")}
    if not u["q_text"]:
        return {**base, "items": [], "hidden": 0, "stores": [], "filtered": {}, "page": 1, "has_more": False,
                "took_ms": 0}

    items, stores, has_more, loaded = [], [], False, 0
    for p in range(1, page + 1):
        ck = (q.lower(), tab, p)
        with _raw_lock:
            hit = _raw.get(ck)
        if hit and not fresh and time.time() - hit[0] < RESULT_TTL:
            p_items, p_stores, p_more = hit[1:]
        else:
            p_items, p_stores, p_more = collect(u, tab, p, key)
            if not any(st["status"] == "indexing" for st in p_stores):
                with _raw_lock:
                    _raw[ck] = (time.time(), p_items, p_stores, p_more)
        items += p_items
        stores = stores or p_stores  # page 1 carries the store statuses
        has_more, loaded = p_more, p
        if not p_more:
            break

    # copies: ranking adds badges/scores, the cached raw items must stay untouched
    seen, uniq = set(), []
    for it in items:
        if it["url"] not in seen:
            seen.add(it["url"])
            uniq.append(dict(it))

    # exact matches win: if some offers match every search word exactly (or by prefix), drop the
    # typo-tolerant look-alikes ("civic" finds Honda Civic, so Xiaomi "Civi" goes; "alto" drops BYD "Atto")
    qt = direct._join_model_tokens(u["q"].split())
    if qt:
        for it in uniq:
            tw = norm(it.get("title")).split()
            sq = "".join(tw)
            it["match"] = min(direct._word_score(t, tw, sq) for t in qt)
        if any(it["match"] >= 0.8 for it in uniq):
            before = len(uniq)
            uniq = [it for it in uniq if it["match"] >= 0.8]
            fuzzy_dropped = before - len(uniq)
        else:
            fuzzy_dropped = 0
    else:
        fuzzy_dropped = 0

    # budget / PTA wishes from the query (before ranking, so "Sab se sasta" is always a valid choice)
    conv = to_pkr_fn(fx)
    filtered = {"budget": 0, "pta": 0}
    kept = []
    for it in uniq:
        it["attrs"] = smart.attributes(it.get("title"))
        pkr = it["price"] * conv(it.get("currency")) if it.get("price") else None
        if (u["budget_max"] or u["budget_min"]) and (
                pkr is None or (u["budget_max"] and pkr > u["budget_max"]) or (u["budget_min"] and pkr < u["budget_min"])):
            filtered["budget"] += 1
            continue
        if u["pta"] is not None and it["attrs"].get("pta") is not None and it["attrs"]["pta"] != u["pta"]:
            filtered["pta"] += 1
            continue
        kept.append(it)
    ranked, hidden = rank.rank(kept, u["q"], conv)
    # local AI: group offers of the same product, judge each price, pick one recommendation
    groups = ml.group_offers(ranked)
    ml.assess(ranked, groups)
    pick = ml.smart_pick(ranked, groups, u["pta"])
    group_out = [{"urls": [ranked[i]["url"] for i in g["members"]], "best": ranked[g["best"]]["url"],
                  "stores": g["stores"], "min": g["min"], "max": g["max"]} for g in groups]
    return {**base, "items": ranked, "hidden": hidden + fuzzy_dropped, "stores": stores, "filtered": filtered,
            "groups": group_out, "pick": pick,
            "page": loaded, "has_more": has_more and loaded < MAX_PAGE, "took_ms": int((time.time() - t0) * 1000)}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if not isinstance(body, (bytes, bytearray)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/api/search":
            p = parse_qs(u.query)
            q = " ".join((p.get("q", [""])[0]).split())[:80]
            tab = "intl" if p.get("tab", ["local"])[0] == "intl" else "local"
            if len(q) < 2:
                return self._send(400, {"error": "Type at least 2 characters"})
            try:
                try:
                    page = max(1, min(MAX_PAGE, int(p.get("page", ["1"])[0])))
                except ValueError:
                    page = 1
                return self._send(200, search(q, tab, page, fresh=p.get("fresh", ["0"])[0] == "1"))
            except Exception as e:
                return self._send(500, {"error": str(e)[:200]})
        if u.path == "/img":
            try:
                ctype, body = fetch_image(parse_qs(u.query).get("u", [""])[0])
            except Exception:
                return self._send(404, b"", "text/plain")
            return self._send(200, body, ctype)
        if u.path == "/api/health":
            return self._send(200, health.summary())
        if u.path == "/api/stores":
            return self._send(200, {"local": [s["name"] for s in LOCAL_STORES],
                                    "has_key": bool((load_config().get("serpapi_key") or "").strip())})
        path = "index.html" if u.path in ("/", "") else u.path.lstrip("/")
        full = os.path.normpath(os.path.join(STATIC, path))
        if not full.startswith(STATIC + os.sep) or not os.path.isfile(full):
            return self._send(404, b"not found", "text/plain")
        with open(full, "rb") as f:
            self._send(200, f.read(), MIME.get(os.path.splitext(full)[1], "application/octet-stream"))


class Server(ThreadingHTTPServer):
    allow_reuse_address = sys.platform != "win32"
    daemon_threads = True


def main():
    lan = "--lan" in sys.argv
    host = "0.0.0.0" if lan else "127.0.0.1"
    url = f"http://127.0.0.1:{PORT}"
    try:
        srv = Server((host, PORT), Handler)
    except OSError:
        print(f"Port {PORT} is already in use; the app is probably running already: {url}")
        if "--no-browser" not in sys.argv:
            webbrowser.open(url)
        return
    # check every store and build product lists in the background, so searches are quick
    direct.warm(LOCAL_STORES)
    print(f"Product Finder is running: {url}   (Ctrl+C to stop)")
    if lan:
        try:
            ip = socket.gethostbyname(socket.gethostname())
            print(f"From your phone (same Wi-Fi): http://{ip}:{PORT}")
        except Exception:
            pass
    if "--no-browser" not in sys.argv:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
