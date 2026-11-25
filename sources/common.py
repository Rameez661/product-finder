"""Shared helpers: HTTP (stdlib only), small file cache, text normalisation."""
import json
import os
import re
import threading
import time
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# A plain, honest client name. No browser imitation.
UA = {"User-Agent": "price-finder/1.0 (personal price comparison)"}


def http_get(url, timeout=25, retries=1):
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            last = e
            time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"{url.split('?')[0]}: {last}")


def load_config():
    path = os.path.join(BASE, "config.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


class JsonCache:
    """Tiny key -> (time, value) cache persisted to data/<name>.json."""

    def __init__(self, name, max_age_s):
        self.path = os.path.join(DATA_DIR, name + ".json")
        self.max_age = max_age_s
        self.lock = threading.Lock()
        try:
            with open(self.path, encoding="utf-8") as f:
                self.d = json.load(f)
        except Exception:
            self.d = {}

    def get(self, key):
        with self.lock:
            hit = self.d.get(key)
        if hit and time.time() - hit[0] < self.max_age:
            return hit[1]
        return None

    def update(self, key, value):
        """Change a value but keep its original age (so it still expires on schedule)."""
        with self.lock:
            ts = self.d.get(key, [time.time()])[0]
        self.put(key, value, ts)

    def drop(self, key):
        with self.lock:
            self.d.pop(key, None)

    def put(self, key, value, ts=None):
        with self.lock:
            self.d[key] = [ts or time.time(), value]
            now = time.time()
            self.d = {k: v for k, v in self.d.items() if now - v[0] < self.max_age}
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.d, f)
            os.replace(tmp, self.path)


def norm(s):
    """lower-case words: 'Apple iPhone-16 Pro/Max' -> 'apple iphone 16 pro max'"""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).split())


def tokens(s):
    return norm(s).split()


def parse_price(text):
    """'Rs. 319,999' / 'PKR 1,250' / '$1,099.99' -> float, or None."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text) if text > 0 else None
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)", str(text))
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return v if v > 0 else None
