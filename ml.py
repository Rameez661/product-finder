"""Local AI for Product Finder (Python + numpy only, no internet, no API keys).

1. Text similarity     character 3-gram TF-IDF vectors + cosine similarity.
                       Robust to typos, missing spaces and word order ("galaxy samsung a56" ~ "Samsung Galaxy A56").
2. Search ranking      blends the word-match score with TF-IDF similarity, and suggests
                       "Did you mean" names when nothing matches.
3. Product matching    offers of the same product (same model + storage + RAM) are grouped,
                       across stores and listings, by similarity clustering.
4. Price history       every price seen is remembered; trend, lowest seen, change since last time.
5. Deal assessment     price vs. the typical price of the same product (other offers + its own history).
6. Smart pick          one recommended offer with plain reasons.
"""
import json
import math
import os
import re
import statistics
import threading
import time
from collections import Counter

import numpy as np

from smart import attributes
from sources.common import DATA_DIR, norm


# ------------------------------------------------------------------ 1. character n-gram TF-IDF
def grams(text, n=3):
    s = " " + norm(text) + " "
    return [s[i:i + n] for i in range(len(s) - n + 1)] if len(s) >= n else [s]


class TfIdf:
    """Character 3-gram TF-IDF over a list of names. Vectors are L2-normalised rows of a dense matrix."""

    def __init__(self, names, max_features=4096):
        docs = [Counter(grams(t)) for t in names]
        df = Counter(g for d in docs for g in d)
        vocab = [g for g, _ in df.most_common(max_features)]
        self.index = {g: i for i, g in enumerate(vocab)}
        n = max(1, len(docs))
        self.idf = np.array([math.log((1 + n) / (1 + df[g])) + 1 for g in vocab], dtype=np.float32)
        self.matrix = self._rows(docs)

    def _rows(self, docs):
        m = np.zeros((len(docs), len(self.index)), dtype=np.float32)
        for r, d in enumerate(docs):
            for g, c in d.items():
                j = self.index.get(g)
                if j is not None:
                    m[r, j] = 1 + math.log(c)
        m *= self.idf
        norms = np.linalg.norm(m, axis=1, keepdims=True)
        norms[norms == 0] = 1
        return m / norms

    def query(self, text):
        return self._rows([Counter(grams(text))])[0]

    def similar(self, text):
        """Cosine similarity of `text` to every name."""
        return self.matrix @ self.query(text)


_tfidf_cache = {}
_tfidf_lock = threading.Lock()


def store_model(store_id, idx):
    """TF-IDF model of one store's product names (rebuilt when the list changes)."""
    key = (store_id, len(idx), idx[0]["url"] if idx else "")
    with _tfidf_lock:
        hit = _tfidf_cache.get(store_id)
        if hit and hit[0] == key:
            return hit[1]
    model = TfIdf([e["name"] for e in idx])
    with _tfidf_lock:
        _tfidf_cache[store_id] = (key, model)
    return model


# ------------------------------------------------------------------ 2. search ranking + suggestions
def rerank(store_id, idx, hits, q, keep_order_of=None):
    """Order matched products by a blend of word-match rank and TF-IDF similarity to the query."""
    if len(hits) < 2 or not q:
        return hits
    model = store_model(store_id, idx)
    pos = {e["url"]: i for i, e in enumerate(idx)}
    sims = model.similar(q)
    n = len(hits)
    scored = []
    for rank_i, e in enumerate(hits):
        word = 1 - rank_i / n                     # the word matcher's own order (exact words, short names)
        sim = float(sims[pos[e["url"]]]) if e["url"] in pos else 0.0
        scored.append((0.55 * word + 0.45 * sim, rank_i, e))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [e for _, _, e in scored]


def suggest(store_id, idx, q, k=12, min_sim=0.32):
    """'Did you mean': the closest product names when no word match was found."""
    if not idx or not q:
        return []
    model = store_model(store_id, idx)
    sims = model.similar(q)
    top = np.argsort(-sims)[:k]
    return [idx[i] for i in top if sims[i] >= min_sim]


# ------------------------------------------------------------------ 3. product matching (grouping offers)
_NOISE = set("""pta non approved official warranty single dual sim esim e sim storage ram gb tb with and new
box pack brand price in pakistan mobile phone smartphone black white blue red green gold silver grey gray purple
pink yellow orange titanium natural midnight starlight graphite cream mint lavender""".split())


EDITION_WORDS = set("pro max plus ultra mini lite fe air se neo edge fold flip prime power note".split())


def core_name(title):
    """The model part of a title: "Samsung Galaxy A56 8GB RAM 256GB PTA Black" -> "samsung galaxy a56"."""
    words = [w for w in norm(title).split() if w not in _NOISE and not re.fullmatch(r"\d+(gb|tb)?", w)]
    return " ".join(words[:6])


def group_offers(items, threshold=0.6):
    """Cluster offers of the same product. Same storage/RAM is required; names must be similar.
    Adds item["group"] (int) and returns a list of groups (best offer first)."""
    if not items:
        return []
    cores = [core_name(i.get("title")) or norm(i.get("title")) for i in items]
    # model numbers ("a56", "16", "m170") must be identical: "Galaxy A56" is never "Galaxy A36"
    models = [frozenset(w for w in c.split() if any(ch.isdigit() for ch in w)) for c in cores]
    # ...and so must the edition words: "iPhone 16" is not "iPhone 16 Pro"
    editions = [frozenset(w for w in c.split() if w in EDITION_WORDS) for c in cores]
    attrs = [i.get("attrs") or attributes(i.get("title")) for i in items]
    model = TfIdf(cores, max_features=3000)
    sim = model.matrix @ model.matrix.T
    parent = list(range(len(items)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a in range(len(items)):
        for b in range(a + 1, len(items)):
            if sim[a, b] < threshold:
                continue
            if (models[a] != models[b] and models[a] and models[b]) or editions[a] != editions[b]:
                continue
            sa, sb = attrs[a].get("storage"), attrs[b].get("storage")
            ra, rb = attrs[a].get("ram"), attrs[b].get("ram")
            if items[a].get("guide") or items[b].get("guide"):
                continue  # price guides never merge groups; they are attached as a reference below
            if sa != sb or ra != rb:  # strict: an unlabelled listing must not chain 128GB and 512GB together
                continue
            if attrs[a].get("pta") != attrs[b].get("pta"):  # PTA tax makes these different offers
                continue
            if items[a].get("suspect") != items[b].get("suspect"):
                continue
            parent[find(a)] = find(b)

    clusters = {}
    for i in range(len(items)):
        clusters.setdefault(find(i), []).append(i)
    groups = []
    for members in clusters.values():
        priced = [i for i in members if items[i].get("pkr") and not items[i].get("out_of_stock")] or \
            [i for i in members if items[i].get("pkr")]
        best = min(priced, key=lambda i: items[i]["pkr"]) if priced else members[0]
        prices = [items[i]["pkr"] for i in priced]
        groups.append({
            "best": best, "members": members,
            "stores": sorted({items[i]["store"] for i in members}),
            "min": min(prices) if prices else None, "max": max(prices) if prices else None,
            "median": statistics.median(prices) if prices else None,
        })
    # attach each price-guide entry as the reference price of every matching product group
    for gi in [i for i in range(len(items)) if items[i].get("guide") and items[i].get("pkr")]:
        for g in groups:
            if gi in g["members"]:
                continue
            if any(sim[gi, m] >= threshold and models[gi] == models[m] and editions[gi] == editions[m]
                   for m in g["members"]):
                g.setdefault("refs", []).append(gi)
    groups.sort(key=lambda g: (g["min"] is None, g["min"] or 0))
    for gid, g in enumerate(groups):
        for i in g["members"]:
            items[i]["group"] = gid
    return groups


# ------------------------------------------------------------------ 4. price history
_HIST_PATH = os.path.join(DATA_DIR, "price_history.json")
_hist_lock = threading.Lock()
try:
    with open(_HIST_PATH, encoding="utf-8") as f:
        _hist = json.load(f)
except Exception:
    _hist = {}
_hist_saved = [0.0]


def record_price(url, price, when=None):
    """Remember a price (one point per day; a change on the same day replaces it)."""
    if not price:
        return
    day = (when or time.strftime("%Y-%m-%d"))[:10]
    with _hist_lock:
        pts = _hist.setdefault(url, [])
        if pts and pts[-1][0] == day:
            pts[-1][1] = price
        else:
            pts.append([day, price])
        del pts[:-120]  # keep ~4 months
        if time.time() - _hist_saved[0] > 5:
            _hist_saved[0] = time.time()
            tmp = _HIST_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(_hist, f)
            os.replace(tmp, _HIST_PATH)


def history(url):
    with _hist_lock:
        pts = list(_hist.get(url, []))
    if not pts:
        return None
    prices = [p for _, p in pts]
    out = {"points": len(pts), "since": pts[0][0], "low": min(prices), "high": max(prices),
           "first": prices[0], "last": prices[-1]}
    prev = next((p for _, p in reversed(pts[:-1]) if p != prices[-1]), None)
    if prev:
        out["prev"] = prev
        out["change"] = prices[-1] / prev - 1
    if len(pts) >= 4:
        # linear trend per 30 days over the stored points (least squares on day index)
        days = np.array([(time.mktime(time.strptime(d, "%Y-%m-%d")) - time.mktime(time.strptime(pts[0][0], "%Y-%m-%d"))) / 86400
                         for d, _ in pts], dtype=float)
        if days[-1] > 0:
            slope = np.polyfit(days, np.array(prices, dtype=float), 1)[0]
            out["trend_30d"] = float(slope * 30 / statistics.mean(prices))
    return out


# ------------------------------------------------------------------ 5. deal assessment + 6. smart pick
def assess(items, groups):
    """Adds item["deal"] (label + reason) and item["history"]."""
    for it in items:
        h = history(it["url"]) if it.get("via") == "direct" else None
        if h:
            it["history"] = h
        if not it.get("pkr") or it.get("suspect"):
            continue
        g = groups[it["group"]] if "group" in it else None
        typical = None
        guide = [items[m] for m in g.get("refs", [])] if g else []
        if it.get("guide"):
            continue  # the guide price is the reference itself
        from_guide = False
        if guide and (it.get("attrs") or {}).get("pta") is True:
            # guides quote the PTA-approved base variant: compare only offers marked PTA approved, and only to say "good"
            typical, basis, from_guide = guide[0]["pkr"], f"market price on {guide[0]['store']}", True
        elif g and len(g["members"]) >= 2 and g["median"]:
            typical, basis = g["median"], f"{len(g['members'])} offers for this model"
        elif h and h["points"] >= 3:
            typical, basis = statistics.median([h["low"], h["high"], h["last"]]), "its own price history"
        label = None
        if typical:
            r = it["pkr"] / typical - 1
            if r <= -0.05:
                label = ("good", "Good price", f"{abs(r) * 100:.0f}% below typical ({basis})")
            elif r >= 0.08 and not from_guide:
                label = ("warn", "Above typical", f"{r * 100:.0f}% above typical ({basis})")
        if h and h.get("change") is not None and abs(h["change"]) >= 0.02:
            if h["change"] < 0 and not label:
                label = ("good", f"Price dropped {abs(h['change']) * 100:.0f}%", f"was Rs {h['prev']:,.0f}")
            elif h["change"] > 0 and not label:
                label = ("warn", f"Price up {h['change'] * 100:.0f}%", f"was Rs {h['prev']:,.0f}")
        if h and h["points"] >= 3 and it["pkr"] <= h["low"] and not label:
            label = ("good", "Lowest seen", f"since {h['since']}")
        if label:
            it["deal"] = {"tone": label[0], "label": label[1], "why": label[2]}


def smart_pick(items, groups, query_pta=None):
    """One recommendation: good value for the most relevant product, with reasons."""
    cands = [i for i in items if i.get("pkr") and not i.get("suspect") and not i.get("close") and not i.get("guide")
             and not i.get("out_of_stock")]
    if len(cands) < 2:
        return None

    def score(it):
        s = it.get("score", 0) / 100                       # price + rating (rank.py)
        s += 0.25 * it.get("relevance", 0)
        if it.get("deal", {}).get("tone") == "good":
            s += 0.15
        if it.get("deal", {}).get("tone") == "warn":
            s -= 0.15
        a = it.get("attrs") or {}
        if a.get("pta") is True and query_pta is not False:
            s += 0.1                                        # PTA approved works with local SIMs
        if it.get("stale") or it.get("confidence") == "low":
            s -= 0.2
        return s

    best = max(cands, key=score)
    why = []
    g = groups[best["group"]] if "group" in best else None
    if g and len(g["members"]) > 1 and best["pkr"] <= (g["min"] or best["pkr"]):
        why.append(f"Lowest of {len(g['members'])} offers for this model")
    elif best["pkr"] == min(i["pkr"] for i in cands):
        why.append("Lowest price in these results")
    if best.get("deal", {}).get("tone") == "good":
        why.append(f"{best['deal']['label']}: {best['deal']['why']}")
    a = best.get("attrs") or {}
    if a.get("pta") is True:
        why.append("PTA approved")
    if best.get("rating"):
        why.append(f"Rated {best['rating']:.1f}" + (f" ({best['reviews']:,} reviews)" if best.get("reviews") else ""))
    if not why:
        why.append("Best balance of price and match to your search")
    return {"url": best["url"], "why": why}
