"""Decide which results are the same product, which are cheap, and which are a good deal."""
import statistics

from sources.common import tokens
from sources.direct import _word_score

# words that usually mean "an accessory for the product", not the product itself
ACCESSORY = {"case", "cover", "protector", "glass", "charger", "cable", "adapter", "skin", "pouch",
             "holder", "stand", "strap", "film", "tempered", "back", "battery", "replacement", "mount",
             "sticker", "box", "dummy", "lens"}


def relevance(title, q):
    qt, tt = tokens(q), tokens(title)
    if not tt:
        return 0.0
    if not qt:  # category browse ("mobile 50k tak"): every product of the category is relevant
        return 1.0
    sq = "".join(tt)
    hit = sum(1 for t in qt if _word_score(t, tt, sq) > 0) / len(qt)
    acc = [w for w in tt if w in ACCESSORY and w not in qt]
    return hit * (0.5 if acc else 1.0)


def _bayes_rating(r, n, prior=4.0, weight=20):
    """A 5.0 from 2 reviews should not beat a 4.7 from 2,000."""
    n = n or 0
    return (r * n + prior * weight) / (n + weight)


def rank(items, q, to_pkr):
    """Adds pkr, relevance, deal score and badges. Returns (kept, hidden_count)."""
    for it in items:
        it["relevance"] = relevance(it.get("title"), q)
        p = it.get("price")
        it["pkr"] = p * to_pkr(it.get("currency", "PKR")) if p else None
    # close matches (one word missing) were already chosen on purpose by the store matcher
    kept = [it for it in items if it["relevance"] >= 0.75 or (it.get("close") and it["relevance"] >= 0.5)]
    hidden = len(items) - len(kept)

    priced = [it for it in kept if it["pkr"]]
    if priced:
        med = statistics.median(it["pkr"] for it in priced)
        for it in priced:
            # far below the typical price: probably an accessory or a different variant
            it["suspect"] = it["pkr"] < 0.35 * med
        buyable = [it for it in priced if not it.get("out_of_stock")] or priced
        good = [it for it in buyable if not it["suspect"] and not it.get("guide")] or \
            [it for it in buyable if not it.get("guide")] or buyable
        lo, hi = min(it["pkr"] for it in good), max(it["pkr"] for it in good)
        rated = [it for it in good if it.get("rating")]
        for it in priced:
            ps = 1.0 if hi == lo else 1 - (it["pkr"] - lo) / (hi - lo)
            ps = max(0.0, min(1.0, ps))
            if rated:
                rs = (_bayes_rating(it["rating"], it.get("reviews")) - 3.0) / 2.0 if it.get("rating") else 0.4
                score = 0.65 * ps + 0.35 * max(0.0, min(1.0, rs))
            else:
                score = ps
            it["score"] = round(score * 100 * it["relevance"] * (0.4 if it["suspect"] else 1.0))
        in_stock = any(not it.get("out_of_stock") for it in priced)
        if in_stock:  # never call something "Cheapest" / "Best deal" when it cannot be bought
            cheapest = min(good, key=lambda it: it["pkr"])
            cheapest.setdefault("badges", []).append("Cheapest")
            best = max(good, key=lambda it: it["score"])
            best.setdefault("badges", []).append("Best deal")
        if rated and in_stock:
            top = max(rated, key=lambda it: _bayes_rating(it["rating"], it.get("reviews")))
            top.setdefault("badges", []).append("Top rated")
        for it in priced:
            if it["suspect"]:
                it.setdefault("badges", []).append("Possibly accessory / other model")
    for it in kept:
        it.setdefault("score", 0)
        it.setdefault("badges", [])
        it.setdefault("suspect", False)
    kept.sort(key=lambda it: (bool(it.get("out_of_stock")), -it["score"], it["pkr"] or 1e18))
    return kept, hidden
