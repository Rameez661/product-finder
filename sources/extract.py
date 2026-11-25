"""Read product data from a page in several independent ways, so one website change does not break it.

Strategies, tried in order (the store's last working strategy goes first):
  jsonld     schema.org Product data in <script type="application/ld+json">   (most reliable)
  meta       <meta property="product:price:amount"> / og:price / itemprop meta tags
  microdata  itemprop="price" on any element
  text       visible "Rs. 12,345" / "PKR 12,345" on the page (last resort, lower confidence)

Every result is validated (sane price, title that matches the product) before it is used.
"""
import html as htmllib
import json
import re
from collections import Counter

from .common import parse_price, tokens

STRATEGIES = ("jsonld", "meta", "microdata", "text")
MIN_PRICE, MAX_PRICE = 50, 500_000_000  # PKR (cars included); anything outside is a parsing mistake
_OOS = re.compile(r"out\s*of\s*stock|sold\s*out|discontinued|\boos\b|not\s*available", re.I)


# ------------------------------------------------------------------ helpers
def _meta(html, *props):
    for prop in props:
        for pat in (r'<meta[^>]+(?:property|name|itemprop)=["\']%s["\'][^>]*content=["\']([^"\']*)',
                    r'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name|itemprop)=["\']%s["\']'):
            m = re.search(pat % re.escape(prop), html, re.I)
            if m and m.group(1).strip():
                return htmllib.unescape(m.group(1).strip())
    return None


def _jsonld_products(html):
    out = []
    for block in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            j = json.loads(block.strip())
        except ValueError:
            try:  # some sites leave trailing commas / control chars
                j = json.loads(re.sub(r",\s*([}\]])", r"\1", block.strip()), strict=False)
            except ValueError:
                continue
        stack = [j]
        while stack:
            x = stack.pop()
            if isinstance(x, list):
                stack += x
            elif isinstance(x, dict):
                t = x.get("@type")
                if t in ("Product", "ProductGroup") or (isinstance(t, list) and ("Product" in t or "ProductGroup" in t)):
                    out.append(x)
                stack += [v for k, v in x.items() if k in ("@graph", "mainEntity", "itemListElement", "item", "hasVariant")]
    return out


def _first_image(img):
    if isinstance(img, list):
        img = img[0] if img else None
    if isinstance(img, dict):
        img = img.get("url") or img.get("contentUrl")
    return img if isinstance(img, str) and img.startswith("http") else None


def _visible_text(html):
    html = re.sub(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<[^>]+>", " ", html)
    return " ".join(htmllib.unescape(html).split())


def _title(html):
    t = _meta(html, "og:title", "twitter:title")
    if not t:
        m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S | re.I) or re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
        t = _visible_text(m.group(1)) if m else None
    if t:  # "Apple iPhone 16 Price in Pakistan | Store" -> "Apple iPhone 16"
        t = re.split(r"\s+[|–-]\s+|\s+price in pakistan", t, flags=re.I)[0].strip()
    return t or None


# ------------------------------------------------------------------ strategies
def _s_jsonld(html):
    prods = _jsonld_products(html)
    if not prods:
        return None
    p = prods[0]
    offers = p.get("offers") or {}
    if isinstance(offers, list):
        priced = [o for o in offers if isinstance(o, dict) and parse_price(o.get("price") or o.get("lowPrice"))]
        offers = min(priced, key=lambda o: parse_price(o.get("price") or o.get("lowPrice"))) if priced else {}
    if not isinstance(offers, dict):
        offers = {}
    price = parse_price(offers.get("price") or offers.get("lowPrice"))
    price_max = parse_price(offers.get("highPrice"))
    spec = offers.get("priceSpecification")
    if isinstance(spec, dict) and parse_price(spec.get("minPrice")):
        # a price range (e.g. a car from base to top variant): show "from" the lowest
        price, price_max = parse_price(spec.get("minPrice")), parse_price(spec.get("maxPrice")) or price
    if price is None:
        return None
    rating = p.get("aggregateRating") if isinstance(p.get("aggregateRating"), dict) else {}
    brand = p.get("brand")
    return {
        "title": p.get("name"), "price": price, "currency": offers.get("priceCurrency"),
        "price_max": price_max if price_max and price_max > price else None,
        "availability": offers.get("availability"),
        "rating": parse_price(rating.get("ratingValue")),
        "reviews": int(parse_price(rating.get("reviewCount") or rating.get("ratingCount")) or 0) or None,
        "image": _first_image(p.get("image")),
        "brand": brand.get("name") if isinstance(brand, dict) else brand,
    }


def _s_meta(html):
    price = parse_price(_meta(html, "product:price:amount", "og:price:amount", "product:sale_price:amount", "price"))
    if price is None:
        return None
    return {"price": price, "currency": _meta(html, "product:price:currency", "og:price:currency", "priceCurrency"),
            "availability": _meta(html, "product:availability", "og:availability", "availability")}


def _s_microdata(html):
    m = (re.search(r'itemprop=["\']price["\'][^>]*content=["\']([^"\']+)', html, re.I)
         or re.search(r'content=["\']([^"\']+)["\'][^>]*itemprop=["\']price["\']', html, re.I)
         or re.search(r'itemprop=["\']price["\'][^>]*>\s*([^<]{1,40})<', html, re.I))
    price = parse_price(m.group(1)) if m else None
    if price is None:
        return None
    cur = re.search(r'itemprop=["\']priceCurrency["\'][^>]*content=["\']([A-Za-z]{3})', html, re.I)
    return {"price": price, "currency": cur.group(1) if cur else None}


_RS = re.compile(r"(?:Rs\.?|PKR|₨)\s*([1-9][\d,]{2,})(?!\s*(?:to|-|–)\s*(?:Rs|PKR)?\s*\d)", re.I)


def _s_text(html):
    """The price that appears most often in the visible text (headline price is usually repeated)."""
    vals = [parse_price(m.group(1)) for m in _RS.finditer(_visible_text(html))]
    vals = [v for v in vals if v and MIN_PRICE <= v <= MAX_PRICE]
    if not vals:
        return None
    price, n = Counter(vals).most_common(1)[0]
    return {"price": price, "currency": "PKR", "weak": n < 2}


_FUNCS = {"jsonld": _s_jsonld, "meta": _s_meta, "microdata": _s_microdata, "text": _s_text}


# ------------------------------------------------------------------ main entry
def extract(html, expected_name=None, prefer=None):
    """Returns (result dict or None, method used, list of methods that failed)."""
    order = ([prefer] if prefer in _FUNCS else []) + [s for s in STRATEGIES if s != prefer]
    failed = []
    for name in order:
        try:
            r = _FUNCS[name](html)
        except Exception:
            r = None
        if r and _valid(r):
            out = {
                "title": r.get("title") or _title(html) or expected_name,
                "price": float(r["price"]), "price_max": r.get("price_max"),
                "currency": (r.get("currency") or "PKR").upper()[:3],
                "in_stock": None, "rating": r.get("rating"), "reviews": r.get("reviews"),
                "image": r.get("image") or _first_image(_meta(html, "og:image", "twitter:image")),
                "confidence": "low" if name == "text" else "high",
            }
            avail = str(r.get("availability") or _meta(html, "product:availability", "og:availability") or "")
            if avail:
                out["in_stock"] = not _OOS.search(avail)
            # keep the extra data (rating, image) from JSON-LD even when another strategy found the price
            if name != "jsonld":
                extra = _s_jsonld_extra(html)
                for k in ("rating", "reviews", "image", "title"):
                    out[k] = out[k] or extra.get(k)
            if expected_name and not _title_matches(out["title"], expected_name):
                out["title"] = expected_name  # page title looks wrong (redirect, layout change): trust the URL
                out["confidence"] = "low"
            return out, name, failed
        failed.append(name)
    return None, None, failed


def _s_jsonld_extra(html):
    prods = _jsonld_products(html)
    if not prods:
        return {}
    p = prods[0]
    rating = p.get("aggregateRating") if isinstance(p.get("aggregateRating"), dict) else {}
    return {"title": p.get("name"), "image": _first_image(p.get("image")),
            "rating": parse_price(rating.get("ratingValue")),
            "reviews": int(parse_price(rating.get("reviewCount") or rating.get("ratingCount")) or 0) or None}


def _valid(r):
    p = r.get("price")
    return isinstance(p, (int, float)) and MIN_PRICE <= p <= MAX_PRICE and not r.get("weak")


def _title_matches(title, expected):
    a, b = set(tokens(title)), set(tokens(expected))
    return bool(a & b) if a and b else True


def looks_like_product(html):
    """True when the page is clearly a product page (so a missing price means 'not listed', not 'layout changed')."""
    return bool(_jsonld_products(html)) or bool(re.search(
        r'og:type["\'][^>]*content=["\'](?:og:)?product|itemtype=["\']https?://schema\.org/Product', html, re.I))
