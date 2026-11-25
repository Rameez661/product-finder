"""Google results through SerpApi (needs your own key in config.json: {"serpapi_key": "..."}).

- International: Google Shopping (gl=us). One call returns offers from many stores
  (Amazon, Walmart, Best Buy, eBay, ...), each with store name, price, rating and link.
- Local: Google Shopping does not support Pakistan, so we run a normal Google search
  ("<product> price in Pakistan") on google.com.pk and keep only results from known
  Pakistani stores, reading the price from Google's rich snippet or the result text.
"""
import json
import re
import urllib.parse

from .common import JsonCache, http_get, parse_price
from .stores import LOCAL_STORES, store_for_url

API = "https://serpapi.com/search.json"
_cache = JsonCache("serp", 6 * 3600)  # every call costs one search from the monthly quota


def _call(params, key):
    ck = json.dumps(params, sort_keys=True)
    hit = _cache.get(ck)
    if hit is not None:
        return hit
    url = API + "?" + urllib.parse.urlencode({**params, "api_key": key})
    j = json.loads(http_get(url, timeout=40))
    if j.get("error"):
        raise RuntimeError(j["error"])
    _cache.put(ck, j)
    return j


def international(q, key):
    j = _call({"engine": "google_shopping", "q": q, "gl": "us", "hl": "en"}, key)
    items = []
    for r in j.get("shopping_results", []):
        price = r.get("extracted_price") or parse_price(r.get("price"))
        link = r.get("link") or r.get("product_link")
        if not link:
            continue
        items.append({
            "title": r.get("title"), "price": price, "currency": "USD",
            "store": r.get("source") or "Store", "store_id": (r.get("source") or "").lower(),
            "url": link, "image": r.get("thumbnail"),
            "rating": r.get("rating"), "reviews": r.get("reviews"),
            "delivery": r.get("delivery"), "via": "google",
            "old_price": r.get("extracted_old_price"),
        })
    return items, {"ok": True, "note": f"{len(items)} offers from Google Shopping"}


_PKR = re.compile(r"(?:Rs\.?|PKR|₨)\s*([\d][\d,]{2,})", re.I)


def _local_price(r):
    rs = r.get("rich_snippet") or {}
    for part in rs.values():
        ext = (part or {}).get("detected_extensions") or {}
        if ext.get("price"):
            return float(ext["price"])
        for k, v in ext.items():
            if "price" in k and isinstance(v, (int, float)):
                return float(v)
    for field in ("snippet", "title"):
        m = _PKR.search(r.get(field) or "")
        if m:
            return parse_price(m.group(1))
    for e in (rs.get("top") or {}).get("extensions") or []:
        m = _PKR.search(e)
        if m:
            return parse_price(m.group(1))
    return None


def _local_rating(r):
    for part in (r.get("rich_snippet") or {}).values():
        ext = (part or {}).get("detected_extensions") or {}
        if ext.get("rating"):
            return ext.get("rating"), ext.get("reviews")
    return None, None


def local(q, key, skip=()):
    j = _call({"engine": "google", "q": f"{q} price in Pakistan", "gl": "pk", "hl": "en",
               "google_domain": "google.com.pk", "num": 30}, key)
    items, found = [], set()
    rows = list(j.get("organic_results", []))
    rows += [{"title": r.get("title"), "link": r.get("link"), "snippet": r.get("price"),
              "source": r.get("source"), "thumbnail": r.get("thumbnail")}
             for r in j.get("inline_shopping_results", []) + j.get("shopping_results", [])]
    for r in rows:
        st = store_for_url(r.get("link") or "")
        if not st or st["id"] in skip:
            continue
        price = _local_price(r)
        rating, reviews = _local_rating(r)
        found.add(st["id"])
        items.append({
            "title": r.get("title"), "price": price, "currency": "PKR",
            "store": st["name"], "store_id": st["id"], "url": r["link"],
            "image": r.get("thumbnail"), "rating": rating, "reviews": reviews, "via": "google",
        })
    return items, {"ok": True, "found": sorted(found),
                   "note": f"{len(items)} results from {len(found)} Pakistani stores via Google"}
