"""robots.txt rules with wildcard support (* and $), as Google reads them.

Python's urllib.robotparser ignores wildcards, so a rule like "Disallow: /*?q=" would be missed.
Rules: the group for our user-agent (or "*") applies; the longest matching rule wins;
on a tie Allow wins. No robots.txt (404) means everything is allowed.
"""
import re

AGENT = "price-finder"


class Robots:
    def __init__(self, text=""):
        self.rules, self.sitemaps, self.crawl_delay = [], [], None
        groups, cur, seen_rule = [], None, False
        for raw in (text or "").splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            k, v = (x.strip() for x in line.split(":", 1))
            k = k.lower()
            if k == "sitemap":
                self.sitemaps.append(v)
            elif k == "user-agent":
                if cur is None or seen_rule:
                    cur = {"agents": [], "rules": [], "delay": None}
                    groups.append(cur)
                    seen_rule = False
                cur["agents"].append(v.lower())
            elif cur is not None and k in ("allow", "disallow"):
                seen_rule = True
                if v:
                    cur["rules"].append((k == "allow", v))
            elif cur is not None and k == "crawl-delay":
                seen_rule = True
                try:
                    cur["delay"] = float(v)
                except ValueError:
                    pass
        mine = [g for g in groups if any(a != "*" and a in AGENT for a in g["agents"])]
        chosen = mine or [g for g in groups if "*" in g["agents"]]
        for g in chosen:
            self.rules += [(allow, len(p), _compile(p)) for allow, p in g["rules"]]
            if g["delay"] is not None:
                self.crawl_delay = g["delay"]

    def allowed(self, path):
        best = None  # (length, allow)
        for allow, n, rx in self.rules:
            if rx.match(path) and (best is None or n > best[0] or (n == best[0] and allow)):
                best = (n, allow)
        return True if best is None else best[1]


def _compile(pattern):
    end = pattern.endswith("$")
    body = re.escape(pattern.rstrip("$")).replace(r"\*", ".*")
    return re.compile(body + ("$" if end else ""))
