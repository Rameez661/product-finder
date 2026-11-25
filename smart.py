"""Local "smart" layer (no internet, no extra libraries):

understand(q)   Roman Urdu / English query -> search words + budget + PTA wish + spelling fixes
                "iphon 16 pta approved 3 lakh tak" -> words "iphone 16", PTA yes, max Rs 300,000
attributes(t)   product title -> storage, RAM, PTA, SIM, condition (for chips and filters)
"""
import difflib
import re
import threading
from collections import Counter

from sources.common import norm

# words that carry no product meaning in a shopping query
FILLER = set("""sasta sasti saste cheap cheapest best acha achi achha accha achay behtar price prices rate rates
ka ki ke ko wala wali wale chahiye chaiye chahye mein me mai main kitne kitna kitni kahan kaha se sy
new naya nayi original buy kharidna khareedna lena lene pakistan pk in for the a an of with and
online deal deals offer offers kaunsa konsa kon sa""".split())
# category words: kept for ranking, but not required in the product name
CATEGORY = {"mobile": "mobiles", "mobiles": "mobiles", "phone": "mobiles", "phones": "mobiles",
            "smartphone": "mobiles", "laptop": "laptop", "laptops": "laptop", "notebook": "laptop",
            "tablet": "tablet", "tab": "tablet", "watch": "watch", "headphone": "headphones",
            "headphones": "headphones", "earbuds": "earbuds", "led": "led", "tv": "led",
            "car": "cars", "cars": "cars", "gari": "cars", "gaari": "cars", "gadi": "cars", "gaadi": "cars",
            "bike": "bikes", "bikes": "bikes", "motorcycle": "bikes", "motorbike": "bikes"}
UNITS = {"k": 1e3, "hazar": 1e3, "hazaar": 1e3, "hzar": 1e3, "thousand": 1e3, "h": 1e3,
         "lac": 1e5, "lakh": 1e5, "lakhs": 1e5, "lacs": 1e5, "lk": 1e5, "m": 1e6, "million": 1e6}
MAX_WORDS = r"(?:tak|tk|under|below|upto|up to|se kam|sy kam|max|maximum|budget|within|andar|less than|<)"
MIN_WORDS = r"(?:se zyada|se ziada|sy zyada|above|over|more than|minimum|min|>)"
NUM = r"(\d+(?:[.,]\d+)?)\s*(k|hazar|hazaar|hzar|thousand|lac|lacs|lakh|lakhs|lk|million|m)?\b"


def _amount(num, unit):
    v = float(num.replace(",", "")) if num.count(",") and len(num.split(",")[-1]) == 3 else float(num.replace(",", "."))
    return v * UNITS.get((unit or "").lower(), 1)


def understand(q, vocab=None):
    raw = " ".join(q.split())
    text = raw.lower()
    out = {"raw": raw, "budget_min": None, "budget_max": None, "pta": None, "fixes": [], "category": None}

    # ---- PTA wish
    if re.search(r"\bnon[\s-]*pta\b", text):
        out["pta"] = False
        text = re.sub(r"\bnon[\s-]*pta\b", " ", text)
    elif re.search(r"\bpta(\s*approved)?\b", text):
        out["pta"] = True
        text = re.sub(r"\bpta(\s*approved)?\b", " ", text)

    # ---- budget: "50-70k", "50k tak", "under 50000", "1.5 lakh se kam", "rs 40000 se zyada"
    m = re.search(r"(\d+(?:\.\d+)?)\s*(k|hazar|lakh|lac)?\s*(?:-|to|se)\s*" + NUM + r"\s*(?:tak|tk|ke darmiyan|between)?", text)
    if m and (m.group(2) or m.group(4)):
        unit = m.group(4) or m.group(2)
        lo, hi = _amount(m.group(1), m.group(2) or unit), _amount(m.group(3), unit)
        if 0 < lo < hi:
            out["budget_min"], out["budget_max"] = lo, hi
            text = text.replace(m.group(0), " ")
    if out["budget_max"] is None:
        for rx, key in ((MAX_WORDS + r"\s*(?:rs\.?|pkr)?\s*" + NUM, "budget_max"),
                        (r"(?:rs\.?|pkr)?\s*" + NUM + r"\s*" + MAX_WORDS, "budget_max"),
                        (MIN_WORDS + r"\s*(?:rs\.?|pkr)?\s*" + NUM, "budget_min"),
                        (r"(?:rs\.?|pkr)?\s*" + NUM + r"\s*" + MIN_WORDS, "budget_min"),
                        (r"(?:rs\.?|pkr)\s*" + NUM, "budget_max")):
            mm = re.search(rx, text)
            if mm:
                val = _amount(mm.group(1), mm.group(2))
                if val >= 500:  # "16" in "iphone 16" is never a budget
                    out[key] = val
                    text = text.replace(mm.group(0), " ")
    # bare "50k" / "2 lakh" with a unit is a budget too
    if out["budget_max"] is None and out["budget_min"] is None:
        mm = re.search(r"\b(\d+(?:\.\d+)?)\s*(k|hazar|hazaar|lakh|lac|lakhs)\b", text)
        if mm and _amount(mm.group(1), mm.group(2)) >= 1000:
            out["budget_max"] = _amount(mm.group(1), mm.group(2))
            text = text.replace(mm.group(0), " ")

    # ---- words
    words = []
    for w in norm(text).split():
        if w in FILLER or w in ("rs", "pkr", "tak", "tk", "se", "kam", "zyada"):
            continue
        if w in CATEGORY:
            out["category"] = out["category"] or CATEGORY[w]
            continue
        words.append(w)

    # ---- spelling: unknown words snapped to the closest word that really appears in store product names
    if vocab:
        fixed = []
        for w in words:
            if w in vocab or w.isdigit() or len(w) < 3:
                fixed.append(w)
                continue
            cand = difflib.get_close_matches(w, vocab.keys(), n=5, cutoff=0.78)
            if cand:
                best = max(cand, key=lambda c: (difflib.SequenceMatcher(None, w, c).ratio(), vocab[c]))
                out["fixes"].append([w, best])
                fixed.append(best)
            else:
                fixed.append(w)
        words = fixed
    out["q"] = " ".join(words)
    # text for search engines (Google fallback): keep the category word when it is all we have
    out["q_text"] = out["q"] or next((k for k, v in CATEGORY.items() if v == out["category"]), "")
    return out


# ------------------------------------------------------------------ product attributes
COLORS = set("black white blue red green gold silver grey gray purple pink yellow orange titanium natural midnight starlight graphite".split())


def attributes(title):
    t = (title or "").lower()
    a = {}
    if re.search(r"\bnon[\s-]*pta\b", t):
        a["pta"] = False
    elif re.search(r"\bpta\b", t):
        a["pta"] = True
    # "8/256", "8gb+256gb", "8gb ram 256gb", "256gb"
    m = re.search(r"\b(\d{1,2})\s*(?:gb)?\s*[/+]\s*(\d{2,4})\s*(gb|tb)?\b", t)
    if m:
        a["ram"], a["storage"] = f"{m.group(1)}GB", f"{m.group(2)}{(m.group(3) or 'gb').upper()}"
    else:
        sizes = [(int(n), u.upper()) for n, u in re.findall(r"\b(\d{1,4})\s*(gb|tb)\b", t)]
        ram = re.search(r"\b(\d{1,2})\s*gb\s*ram\b", t)
        if ram:
            a["ram"] = f"{ram.group(1)}GB"
            sizes = [s for s in sizes if not (s[0] == int(ram.group(1)) and s[1] == "GB")]
        if sizes:
            n, u = max(sizes, key=lambda s: s[0] * (1024 if s[1] == "TB" else 1))
            if u == "TB" or n >= 32:
                a["storage"] = f"{n}{u}"
            if len(sizes) >= 2 and "ram" not in a:
                small = min(sizes, key=lambda s: s[0])
                if small[1] == "GB" and small[0] <= 24:
                    a["ram"] = f"{small[0]}GB"
    if re.search(r"\bdual\s*sim\b", t):
        a["sim"] = "Dual SIM"
    elif re.search(r"\bsingle\s*sim\b|\be-?sim\b", t):
        a["sim"] = "Single SIM"
    if re.search(r"\bused\b|\brefurb", t):
        a["condition"] = "Used/Refurbished"
    elif re.search(r"\bopen\s*box\b", t):
        a["condition"] = "Open box"
    return a


# ------------------------------------------------------------------ vocabulary from the store lists
_vocab = {"key": None, "v": {}}
_vlock = threading.Lock()


def vocabulary(indexes):
    """Word -> frequency over every product name we know (rebuilt when the lists change)."""
    key = tuple((k, len(v)) for k, v in sorted(indexes.items()))
    with _vlock:
        if _vocab["key"] != key:
            c = Counter()
            for items in indexes.values():
                for e in items:
                    c.update(w for w in e["n"].split() if len(w) >= 3 and not w.isdigit())
            _vocab["v"], _vocab["key"] = dict(c), key
        return _vocab["v"]
