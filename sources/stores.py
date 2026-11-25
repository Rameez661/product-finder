"""Top Pakistani online stores the Local tab checks.

Every store is read directly (sources/direct.py) wherever the network allows it and its
robots.txt permits. Google (SerpApi key) is the fallback for stores that can't be read directly.
Optional per store: "sitemap_hint" (regex for product sitemaps), "product_re" (regex for
product URLs), "base" (site root if not https://www.<domain>).
"""
from urllib.parse import urlparse

LOCAL_STORES = [
    {"id": "daraz", "name": "Daraz", "domains": ["daraz.pk"]},
    {"id": "priceoye", "name": "PriceOye", "domains": ["priceoye.pk"], "base": "https://priceoye.pk"},
    {"id": "telemart", "name": "Telemart", "domains": ["telemart.pk"]},
    {"id": "megapk", "name": "Mega.pk", "domains": ["mega.pk"], "sitemap_hint": "product|accessor",
     "product_re": r"/\d+/"},
    {"id": "homeshopping", "name": "HomeShopping", "domains": ["homeshopping.pk"]},
    {"id": "ishopping", "name": "iShopping", "domains": ["ishopping.pk"]},
    {"id": "symbios", "name": "Symbios", "domains": ["symbios.pk"]},
    {"id": "shophive", "name": "Shophive", "domains": ["shophive.com"]},
    {"id": "czone", "name": "Czone", "domains": ["czone.com.pk"]},
    {"id": "naheed", "name": "Naheed", "domains": ["naheed.pk"]},
    {"id": "highfy", "name": "Highfy", "domains": ["highfy.pk"]},
    {"id": "paklap", "name": "Paklap", "domains": ["paklap.pk"]},
    {"id": "galaxy", "name": "Galaxy.pk", "domains": ["galaxy.pk"]},
    {"id": "hummart", "name": "HumMart", "domains": ["hummart.com"]},
    {"id": "zah", "name": "Zah Computers", "domains": ["zahcomputers.pk"], "product_re": r"/product/",
     "aliases": ["zah", "zahcomputers"]},
    # new cars and bikes: PakWheels model pages (price range from base to top variant); allowed by robots.txt
    {"id": "pakwheels", "name": "PakWheels", "domains": ["pakwheels.com"], "guide": True,
     "sitemaps": ["https://www.pakwheels.com/new_cars_sitemap.xml.gz", "https://www.pakwheels.com/new_bikes_sitemap.xml.gz"],
     "product_re": r"^https://www\.pakwheels\.com/(?:new-cars|bikes)/[^/]+/[^/]+/$", "name_segments": 2},
    # price guide (not a shop): Pakistani market price per phone; reachable and allowed by its robots.txt
    {"id": "mobilemall", "name": "MobileMall", "domains": ["mobilemall.pk"], "base": "https://mobilemall.pk",
     "guide": True, "product_re": r"-price-in-pakistan/?$"},
]


def store_for_url(url):
    host = (urlparse(url).hostname or "").lower()
    for s in LOCAL_STORES:
        if any(host == d or host.endswith("." + d) for d in s["domains"]):
            return s
    return None


def store_by_word(word):
    """'daraz' / 'mega' / 'zah' in a query -> that store (search only there)."""
    w = word.lower()
    for st in LOCAL_STORES:
        names = {st["id"], st["name"].lower().replace(" ", "").replace(".pk", ""), *st.get("aliases", [])}
        names |= {d.split(".")[0] for d in st["domains"]}
        if w in names:
            return st
    return None
