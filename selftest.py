"""Live health check: is every store still readable? Run any time, e.g. after a store redesign.

    py selftest.py            # 3 random product pages per store
    py selftest.py 6          # 6 pages per store

Prints, per store: reachable?, product list size, which reading method worked, sample prices.
"""
import random
import sys
from concurrent.futures import ThreadPoolExecutor

from sources import direct, extract
from sources.stores import LOCAL_STORES


def check(store, n):
    try:
        idx = direct.ensure_index(store, wait=True)
    except direct.StoreError as e:
        return store["name"], e.status, e.note, []
    rows = []
    for e in random.sample(idx, min(n, len(idx))):
        try:
            html = direct.fetch(e["url"]).decode("utf-8", "replace")
        except direct.StoreError as err:
            rows.append((e["name"][:40], err.status, None))
            continue
        r, method, failed = extract.extract(html, e["name"])
        rows.append((e["name"][:40], method or "FAIL (" + ",".join(failed) + ")", r and r["price"]))
    ok = sum(1 for _, m, p in rows if p)
    # a single page without a price is normal (discontinued / "call for price"); most pages failing is not
    verdict = "ok" if ok >= 0.6 * len(rows) else "BROKEN" if ok == 0 else "PARTIAL"
    return store["name"], verdict, f"{len(idx):,} products, {ok}/{len(rows)} pages readable", rows


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(lambda s: check(s, n), LOCAL_STORES))
    bad = 0
    for name, verdict, note, rows in results:
        print(f"{name:14} {verdict:9} {note}")
        for title, method, price in rows:
            print(f"    {method:22} {price or '-':>12}  {title}")
        bad += verdict in ("PARTIAL", "BROKEN")
    print("\n'-' wale page ka matlab aksar yeh hai ke store ne us product ki price hi nahi di (band / stock khatam).")
    print("\nBROKEN/PARTIAL ka matlab: store ki website badli hai. App purani prices aur Google se kaam chalati rahegi;"
          "\nzarurat ho to sources/stores.py mein us store ka sitemap_hint / product_re theek karein."
          if bad else "\nJo stores khulte hain, sab theek parhe ja rahe hain.")


if __name__ == "__main__":
    main()
