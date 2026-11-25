"""Read any store directly, politely and safely. One generic reader for every store.

For each store:
  1. robots.txt is read first. If the site can't be reached (blocked network, down), the store
     is skipped for a while (circuit breaker) instead of slowing every search.
  2. A product list is built from the store's public sitemap(s), once a day, in the background.
     Only URLs that robots.txt allows are kept. The store's own search is never called.
  3. On a search, the query is matched against that list locally, and only a few best-matching
     product pages are opened, one host at a time with a delay (Crawl-delay is respected).
  4. Price, rating, stock and image come from the page's standard schema.org data (JSON-LD)
     or its product meta tags, so no per-store HTML scraping is needed.
"""
import gzip
import json
import re
import socket
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

from . import extract, health
from .common import UA, JsonCache, norm, tokens
from .robots import Robots

PAGES_PER_SEARCH = 8
MAX_SITEMAPS = 40          # sitemap files read per store per day
MAX_URLS = 80000           # product URLs kept per store
MIN_DELAY, MAX_DELAY = 0.5, 3.0
RETRY_BLOCKED_S = 15 * 60  # network can't reach the site
RETRY_REFUSED_S = 60 * 60  # the site answered 403/429 (bot protection, rate limit)

_index = JsonCache("direct_index", 24 * 3600)
_pages = JsonCache("direct_pages", 6 * 3600)
_robots = JsonCache("direct_robots", 24 * 3600)
_lastgood = JsonCache("direct_lastgood", 30 * 24 * 3600)  # last good reading per page, kept 30 days
_SM = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
_PRODUCT_HINT = re.compile(r"product|item|pdp|/p/|/dp/|catalog", re.I)
_SKIP_HINT = re.compile(r"blog|news|article|categor|brand|tag|page|image|video|author|store-locator|cms", re.I)


class StoreError(Exception):
    def __init__(self, status, note):
        super().__init__(note)
        self.status, self.note = status, note


# ------------------------------------------------------------------ per-host politeness + circuit breaker
class Host:
    _all = {}
    _lock = threading.Lock()

    def __init__(self):
        self.lock = threading.Lock()
        self.slots = threading.Semaphore(2)  # at most 2 requests in flight per store
        self.last = 0.0
        self.delay = MIN_DELAY
        self.down_until = 0.0
        self.down = None  # (status, note)
        self.fails = 0    # consecutive network failures

    @classmethod
    def get(cls, host):
        with cls._lock:
            return cls._all.setdefault(host, cls())

    def check(self):
        if self.down and time.time() < self.down_until:
            raise StoreError(*self.down)

    def trip(self, status, note, for_s):
        self.down, self.down_until = (status, note), time.time() + for_s

    def reset(self):
        self.down, self.down_until, self.fails = None, 0.0, 0


def fetch(url, timeout=15):
    """GET with per-host spacing. Network failures and refusals trip the host's breaker."""
    host = urlparse(url).hostname or ""
    h = Host.get(host)
    h.check()
    with h.slots:
        with h.lock:  # requests start at least `delay` seconds apart
            wait = h.last + h.delay - time.time()
            if wait > 0:
                time.sleep(wait)
            h.last = time.time()
        try:
            req = urllib.request.Request(url, headers={**UA, "Accept-Encoding": "gzip"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read(25 * 1024 * 1024)
                if r.headers.get("Content-Encoding") == "gzip" or body[:2] == b"\x1f\x8b":
                    body = gzip.decompress(body)
            h.fails = 0
            return body
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 429, 503):
                h.trip("refused", f"Store refused automated requests (HTTP {e.code})", RETRY_REFUSED_S)
                raise StoreError("refused", f"Store refused the request (HTTP {e.code})")
            if e.code in (404, 410):
                raise StoreError("gone", "Product page no longer exists")
            raise StoreError("error", f"HTTP {e.code}")
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as e:
            reason = getattr(e, "reason", e)
            h.fails += 1
            if h.fails >= 2:  # one slow page is not a blocked site; two network failures in a row are
                h.trip("blocked", f"Site not reachable from this network ({type(reason).__name__})", RETRY_BLOCKED_S)
                raise StoreError("blocked", "Site not reachable from this network")
            raise StoreError("neterror", f"Network problem ({type(reason).__name__})")
        finally:
            h.last = time.time()


def base_url(store):
    return store.get("base") or f"https://www.{store['domains'][0]}"


def robots_for(store):
    base = base_url(store)
    cached = _robots.get(base)
    if cached is not None:
        rb = Robots(cached)
    else:
        try:
            try:
                text = fetch(base + "/robots.txt", timeout=10).decode("utf-8", "replace")
            except StoreError as e:
                if e.status != "neterror":
                    raise
                text = fetch(base + "/robots.txt", timeout=10).decode("utf-8", "replace")
        except StoreError as e:
            if e.status == "error":  # 404 etc: no robots.txt means no restrictions
                text = ""
            else:
                raise
        _robots.put(base, text)
        rb = Robots(text)
    Host.get(urlparse(base).hostname).delay = min(MAX_DELAY, max(MIN_DELAY, rb.crawl_delay or 0))
    return rb


# ------------------------------------------------------------------ product index from sitemaps
def _slug_name(url, name_segments=None):
    path = urlparse(url).path.rstrip("/")
    segs = [s for s in path.split("/") if s]
    if not segs:
        return None
    if name_segments:  # e.g. PakWheels /new-cars/suzuki/alto/ -> "suzuki alto"
        name = re.sub(r"[-_+]+", " ", " ".join(segs[-name_segments:])).strip()
        return name if re.search(r"[a-zA-Z]{2,}", name) else None
    ids = [i for i, s in enumerate(segs) if s.isdigit()]
    if ids and ids[-1] + 1 < len(segs):
        seg = segs[ids[-1] + 1]  # /category/12345/Product-Name.html
    else:
        seg = segs[-1]  # usually the slug is the last part
        if sum(c.isalpha() for c in seg) < 4:
            seg = max(segs, key=lambda s: sum(c.isalpha() for c in s))
    seg = re.sub(r"\.(html?|php|aspx?)$", "", seg, flags=re.I)
    seg = re.sub(r"[-_]price[-_]in[-_]pakistan$", "", seg, flags=re.I)  # price-guide style slugs
    seg = re.sub(r"-i\d+(-s\d+)?$", "", seg)          # daraz style ids
    seg = re.sub(r"[-_]p?\d{5,}$", "", seg)           # trailing numeric ids
    name = re.sub(r"[-_+]+", " ", seg).strip()
    return name if len(re.findall(r"[a-zA-Z]{2,}", name)) >= 2 else None


def build_index(store):
    rb = robots_for(store)
    base = base_url(store)
    queue = list(store.get("sitemaps") or rb.sitemaps) or [base + "/sitemap.xml"]
    hint = re.compile(store["sitemap_hint"], re.I) if store.get("sitemap_hint") else _PRODUCT_HINT
    seen_maps, items, seen = set(), [], set()
    disallowed = 0
    while queue and len(seen_maps) < MAX_SITEMAPS and len(items) < MAX_URLS:
        sm = queue.pop(0)
        if sm in seen_maps:
            continue
        seen_maps.add(sm)
        try:
            root = ET.fromstring(fetch(sm, timeout=40))
        except StoreError as e:
            if e.status in ("blocked", "refused"):
                raise
            continue
        except ET.ParseError:
            continue
        if root.tag.endswith("sitemapindex"):
            kids = [e.text.strip() for e in root.iter(_SM + "loc") if e.text]
            good = [k for k in kids if hint.search(k)]
            rest = [k for k in kids if not hint.search(k) and not _SKIP_HINT.search(k)]
            queue = good + queue + rest  # product sitemaps first
            continue
        for e in root.iter(_SM + "loc"):
            u = (e.text or "").strip()
            p = urlparse(u)
            if not u or "?" in u or u in seen:
                continue
            if not rb.allowed(p.path or "/"):
                disallowed += 1
                continue
            if store.get("product_re") and not re.search(store["product_re"], u):
                continue
            name = _slug_name(u, store.get("name_segments"))
            if name:
                seen.add(u)
                items.append({"url": u, "name": name, "n": norm(name)})
    if not items:
        if disallowed:
            raise StoreError("robots", "Store's robots.txt does not allow reading product pages")
        raise StoreError("none", "No products found in the store's sitemap")
    _index.put(store["id"], items)
    return items


_building = {}
_build_lock = threading.Lock()


def ensure_index(store, wait=False):
    """Return the index if ready; otherwise start building it in the background."""
    idx = _index.get(store["id"])
    if idx:
        return idx
    with _build_lock:
        t = _building.get(store["id"])
        if not t or not t.is_alive():
            box = {}
            t = threading.Thread(target=_build_into, args=(store, box), daemon=True)
            t.box = box
            _building[store["id"]] = t
            t.start()
    if wait:
        t.join()
    if "error" in t.box:
        raise t.box["error"]
    idx = _index.get(store["id"])
    if idx:
        return idx
    raise StoreError("indexing", "Building the product list, search again in a moment")


def _build_into(store, box):
    try:
        build_index(store)
    except StoreError as e:
        box["error"] = e
    except Exception as e:
        box["error"] = StoreError("error", str(e)[:120])


# ------------------------------------------------------------------ product pages (resilient)
def _forget(store, url):
    """A product page that no longer exists is removed from the store's list."""
    idx = _index.get(store["id"])
    if idx:
        _index.update(store["id"], [e for e in idx if e["url"] != url])
    health.gone(store["id"])


def _stale(url, why):
    lg = _lastgood.get(url)
    if not lg:
        return None
    return dict(lg, stale=True, stale_why=why)


def _page(store, e):
    """Returns a product dict (possibly an old one marked stale), or None.
    Raises StoreError only for blocked/refused (the whole store is unreachable)."""
    url = e["url"]
    hit = _pages.get(url)
    if hit is not None:
        return hit
    try:
        html = fetch(url).decode("utf-8", "replace")
    except StoreError as err:
        if err.status == "gone":
            _forget(store, url)
            return "gone"
        if err.status in ("blocked", "refused"):
            raise
        health.record(store["id"], False, reason="network" if err.status == "neterror" else "http")
        return _stale(url, "page could not be opened")
    res, method, failed = extract.extract(html, e["name"], health.preferred(store["id"]))
    if not res:
        if extract.looks_like_product(html):
            return None  # a real product page without a price (discontinued / "call for price"): normal
        health.record(store["id"], False, reason="no_price")
        return _stale(url, "no price on the page (site may have changed)")
    lg = _lastgood.get(url)
    if lg and lg.get("price") and res["confidence"] == "low" and not (lg["price"] / 3 <= res["price"] <= lg["price"] * 3):
        # a weak reading that disagrees wildly with the last good price is more likely a parsing mistake
        health.record(store["id"], False, reason="price_mismatch")
        return _stale(url, "new price looked wrong")
    health.record(store["id"], True, method=method)
    res["method"] = method
    res["checked"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _pages.put(url, res)
    _lastgood.put(url, res)
    import ml  # local AI module (project root); imported here to keep sources/ importable on its own
    ml.record_price(url, res["price"])
    return res


# ------------------------------------------------------------------ search
_W = r"(?<![a-z])%s(?![a-z])"
CATEGORY_URL = {"mobiles": _W % r"(?:mobiles?|smartphones?|mobile-phones?)",
                "laptop": _W % r"(?:laptops?|notebooks?)", "tablet": _W % r"(?:tablets?|ipads?)",
                "watch": _W % r"(?:watch(?:es)?|smartwatch(?:es)?)", "headphones": _W % r"(?:headphones?|headsets?)",
                "earbuds": _W % r"(?:earbuds?|airpods?|buds)", "led": _W % r"(?:led|leds|tvs?|television)", "cars": _W % r"(?:new-cars|cars?)",
                "bikes": _W % r"(?:bikes?|motorcycles?)"}


def _close(a, b, limit):
    """True when the edit distance between a and b is at most `limit` (small, early-exit Levenshtein)."""
    if abs(len(a) - len(b)) > limit:
        return False
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > limit:
            return False
        prev = cur
    return prev[-1] <= limit


def _word_score(t, words, squashed):
    """How well one query word matches a product name, forgiving small mistakes.
    1.0 exact word · 0.9 start of a word · 0.8 inside the name without spaces ("iphone16", "a 56")
    · 0.7 one/two letters wrong ("samsang", "logitec") · 0 no match."""
    if t in words:
        return 1.0
    if t.isdigit():
        # numbers are model numbers: "16" matches "16", "a56"-style "56" or "16gb", never "160", "256" or "16e"
        rx = re.compile(r"[a-z]*%s(?:gb|tb|mp|mah|hz|w|inch|in|mm|k)?" % t)  # "16gb" yes, "16e" (another model) no
        return 0.9 if any(rx.fullmatch(w) for w in words) else 0.0
    if any(w.startswith(t) for w in words):
        return 0.9
    if len(t) >= 3 and t in squashed:  # "iphone16" written without a space
        return 0.8
    if len(t) >= 4 and not any(c.isdigit() for c in t):  # model numbers must match exactly
        limit = 1 if len(t) < 8 else 2
        if any(_close(t, w, limit) for w in words if w[0] == t[0] or len(t) >= 6):
            return 0.7
    return 0.0


def _join_model_tokens(qt):
    """"galaxy a 56" -> ["galaxy", "a56"]; "iphone16" -> ["iphone", "16"] (model numbers written loosely)."""
    out, i = [], 0
    while i < len(qt):
        t = qt[i]
        if len(t) == 1 and t.isalpha() and i + 1 < len(qt) and qt[i + 1].isdigit():
            out.append(t + qt[i + 1])
            i += 2
            continue
        m = re.fullmatch(r"([a-z]{3,})(\d{1,3})", t)  # "iphone16" but not "a56" / "m170"
        out += [m.group(1), m.group(2)] if m else [t]
        i += 1
    return out


def _url_category(url):
    return urlparse(url).path.rsplit("/", 1)[0]


def _match(idx, q, want=None):
    """Products ranked by how well their name matches the query (small mistakes forgiven).
    Every query word must match; if nothing matches that way, products missing one word are
    returned as close matches. A category narrows by the store's URL path (e.g. /mobiles_products/).
    Products whose last known price fits the budget come first."""
    want = want or {}
    qt = _join_model_tokens(tokens(q))
    cat = CATEGORY_URL.get(want.get("category"))
    cat_rx = re.compile(cat, re.I) if cat else None
    if not qt and not cat_rx:
        return []
    if cat_rx:
        in_cat = [e for e in idx if cat_rx.search(_url_category(e["url"]))]
        if not in_cat:  # store URLs carry no category: fall back to the product name
            in_cat = [e for e in idx if cat_rx.search(e["n"])]
        idx = in_cat
    full, partial = [], []
    for e in idx:
        words = e["n"].split()
        if not qt:
            full.append([0, len(words), e])
            continue
        squashed = "".join(words)
        scores = [_word_score(t, words, squashed) for t in qt]
        hit = sum(1 for x in scores if x > 0)
        if hit == len(qt):
            full.append([-sum(scores) / len(qt), len(words), e])
        elif len(qt) >= 2 and hit == len(qt) - 1:
            partial.append([-sum(scores) / len(qt), len(words), e])
    out = full or partial
    lo, hi = want.get("budget_min"), want.get("budget_max")
    if lo or hi:
        for row in out:
            lg = _lastgood.get(row[2]["url"])
            p = lg.get("price") if lg else None
            # 0 = known and inside the budget, 1 = unknown, 2 = known and outside
            row[0] = (1 if p is None else 0 if (not lo or p >= lo) and (not hi or p <= hi) else 2, row[0])
    out.sort(key=lambda x: (x[0], x[1]))
    return [e for _, _, e in out], bool(not full and partial)


def search(store, q, want=None, offset=0, limit=PAGES_PER_SEARCH):
    """Returns (items, status dict). Never raises: every failure becomes a status.
    want: optional {"category", "budget_min", "budget_max"} from smart.understand()."""
    try:
        Host.get(urlparse(base_url(store)).hostname).check()
        idx = ensure_index(store)
        hits, close_only = _match(idx, q, want)
        import ml
        suggested = False
        if hits and q and not (want and (want.get("budget_min") or want.get("budget_max"))):
            hits = ml.rerank(store["id"], idx, hits, q)          # AI similarity re-ranking
        if not hits and q and not (want and want.get("category")):
            hits = ml.suggest(store["id"], idx, q)               # "Did you mean" by similarity
            close_only = suggested = bool(hits)
        if not hits:
            return [], {"status": "none", "note": f"no match among {len(idx):,} products"}
        items, missing, gone, stale = [], 0, 0, 0
        n_pages = limit + (6 if want and (want.get("budget_max") or want.get("budget_min")) else 0)
        if offset >= len(hits):
            return [], {"status": "ok", "note": "no more products", "more": False}
        batch = hits[offset:offset + n_pages]

        def read(e):
            try:
                return _page(store, e), None
            except StoreError as err:
                return None, err

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(read, batch))
        for e, (r, err) in zip(batch, results):
            if err is not None:
                if err.status in ("blocked", "refused"):
                    if not items and all(x[0] is None for x in results):
                        raise err
                    break
                continue
            if r == "gone":
                gone += 1
                continue
            if r is None:  # product page without a listed price
                missing += 1
                continue
            stale += 1 if r.get("stale") else 0
            items.append({
                "title": r["title"] or e["name"], "price": r["price"], "currency": r["currency"],
                "store": store["name"], "store_id": store["id"], "url": e["url"], "image": r.get("image"),
                "rating": r.get("rating"), "reviews": r.get("reviews"), "via": "direct",
                "guide": bool(store.get("guide")), "price_max": r.get("price_max"),
                "out_of_stock": r.get("in_stock") is False,
                "stale": bool(r.get("stale")), "checked": r.get("checked"),
                "confidence": r.get("confidence", "high"),
            })
        if gone >= 3:
            _index.drop(store["id"])  # many product pages gone (404): the sitemap changed, rebuild the list
        note = f"{len(hits)} matching products, {min(len(hits), offset + n_pages)} checked"
        if gone:
            note += f", {gone} no longer listed"
        if missing:
            note += f", {missing} without a listed price"
        if stale:
            note += f", {stale} showing last known price"
        status = "ok" if items else "none"
        if health.state(store["id"]) == "degraded":
            status = "degraded" if not items or stale else status
            note += " · store website seems to have changed, using fallbacks"
        if suggested:
            note += " · no exact match, showing similar products"
        elif close_only:
            note += " · close matches (one search word not found)"
            for it in items:
                it["close"] = True
        return items, {"status": status, "note": note, "more": len(hits) > offset + n_pages,
                       "total": len(hits)}
    except StoreError as e:
        return [], {"status": "error" if e.status == "neterror" else e.status, "note": e.note}
    except Exception as e:
        return [], {"status": "error", "note": str(e)[:120]}


def ready_indexes():
    """{store_id: product list} for every store whose list is built (used for spelling fixes)."""
    from .stores import LOCAL_STORES
    return {st["id"]: _index.get(st["id"]) for st in LOCAL_STORES if _index.get(st["id"])}


def warm(stores):
    """Start robots checks + index builds for every store, in parallel, in the background."""
    def one(s):
        try:
            ensure_index(s, wait=True)
        except Exception:
            pass
    ex = ThreadPoolExecutor(max_workers=6)
    for s in stores:
        ex.submit(one, s)
