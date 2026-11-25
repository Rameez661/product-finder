"""Simulated website changes: the same product page in many layouts. Run:  py -m unittest -v"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import smart  # noqa: E402
from sources import extract  # noqa: E402
from sources.robots import Robots  # noqa: E402

NAME = "samsung galaxy a56 8gb 256gb"
JSONLD = '''<script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"Product",
"name":"Samsung Galaxy A56 8GB 256GB","image":"https://cdn.x/a56.jpg",
"offers":{"@type":"Offer","price":"119999","priceCurrency":"PKR","availability":"https://schema.org/InStock"},
"aggregateRating":{"ratingValue":"4.6","reviewCount":"312"}}]}</script>'''
META = '<meta property="og:title" content="Samsung Galaxy A56 8GB 256GB | Store"><meta property="product:price:amount" content="119999.00">'
MICRO = '<h1>Samsung Galaxy A56 8GB 256GB</h1><span itemprop="price" content="119999">Rs. 119,999</span>'
TEXT = ('<h1>Samsung Galaxy A56 8GB 256GB</h1><div class="p">Rs. 119,999</div><p>Price: Rs. 119,999 only</p>'
        '<a>Mobiles Rs 10,000 to Rs 20,000</a>')


class Extraction(unittest.TestCase):
    def check(self, html, method, conf="high"):
        r, m, _ = extract.extract(html, NAME)
        self.assertIsNotNone(r, f"nothing extracted, expected {method}")
        self.assertEqual(m, method)
        self.assertEqual(r["price"], 119999)
        self.assertEqual(r["confidence"], conf)
        return r

    def test_original_layout(self):
        r = self.check(JSONLD + META, "jsonld")
        self.assertEqual((r["rating"], r["reviews"], r["in_stock"]), (4.6, 312, True))

    def test_jsonld_removed(self):          # site redesign drops JSON-LD
        self.check(META, "meta")

    def test_only_microdata(self):
        self.check(MICRO, "microdata")

    def test_only_visible_text(self):       # no structured data at all
        r = self.check(TEXT, "text", conf="low")
        self.assertIn("Samsung", r["title"])

    def test_broken_jsonld_falls_back(self):  # trailing comma / bad JSON
        self.check('<script type="application/ld+json">{"@type":"Product","offers":{"price":"119999",},}</script>', "jsonld")
        self.check('<script type="application/ld+json">{oops</script>' + META, "meta")

    def test_preferred_strategy_first(self):
        _, m, _ = extract.extract(JSONLD + META, NAME, prefer="meta")
        self.assertEqual(m, "meta")

    def test_rating_kept_when_price_from_meta(self):
        broken = JSONLD.replace('"price":"119999"', '"price":""')
        r, m, _ = extract.extract(broken + META, NAME)
        self.assertEqual((m, r["rating"]), ("meta", 4.6))

    def test_out_of_stock(self):
        r, _, _ = extract.extract(JSONLD.replace("InStock", "OutOfStock"), NAME)
        self.assertFalse(r["in_stock"])

    def test_no_price_returns_none(self):
        r, m, failed = extract.extract("<html><h1>Samsung Galaxy A56</h1>Coming soon</html>", NAME)
        self.assertIsNone(r)
        self.assertEqual(failed, list(extract.STRATEGIES))

    def test_insane_price_rejected(self):
        r, _, _ = extract.extract('<meta property="product:price:amount" content="1">', NAME)
        self.assertIsNone(r)

    def test_single_text_price_too_weak(self):  # one stray "Rs" on a page is not trusted
        r, _, _ = extract.extract("<h1>X</h1><p>Delivery Rs. 250</p>", NAME)
        self.assertIsNone(r)

    def test_wrong_page_title_replaced(self):   # redirect to an unrelated page
        r, _, _ = extract.extract('<meta property="og:title" content="Home | Store">'
                                  '<meta property="product:price:amount" content="119999">', NAME)
        self.assertEqual((r["title"], r["confidence"]), (NAME, "low"))


class Robots_(unittest.TestCase):
    def test_wildcards(self):
        rb = Robots("User-agent: *\nDisallow: /*?q=\nDisallow: /cart/\nAllow: /cart/public$\nCrawl-delay: 2\n"
                    "Sitemap: https://x/sitemap.xml")
        self.assertFalse(rb.allowed("/search/?q=x"))
        self.assertFalse(rb.allowed("/cart/a"))
        self.assertTrue(rb.allowed("/cart/public"))
        self.assertTrue(rb.allowed("/p/1.html"))
        self.assertEqual((rb.crawl_delay, rb.sitemaps), (2.0, ["https://x/sitemap.xml"]))


class Smart(unittest.TestCase):
    V = {"iphone": 50, "samsung": 40, "galaxy": 30, "mouse": 20, "logitech": 10}

    def test_budget_pta_spelling(self):
        u = smart.understand("iphon 16 pta approved 3 lakh tak", self.V)
        self.assertEqual((u["q"], u["budget_max"], u["pta"], u["fixes"]), ("iphone 16", 300000, True, [["iphon", "iphone"]]))

    def test_model_number_is_not_budget(self):
        self.assertIsNone(smart.understand("iphone 16", self.V)["budget_max"])

    def test_range_and_category(self):
        u = smart.understand("sasta mobile 40-60k", self.V)
        self.assertEqual((u["q"], u["category"], u["budget_min"], u["budget_max"]), ("", "mobiles", 40000, 60000))

    def test_attributes(self):
        self.assertEqual(smart.attributes("Infinix Hot 50 8/256 Non PTA"), {"pta": False, "ram": "8GB", "storage": "256GB"})


if __name__ == "__main__":
    unittest.main()


class FuzzySearch(unittest.TestCase):
    from sources import direct as D
    IDX = [{"url": f"https://x.pk/mobiles_products/{i}/{n.replace(' ', '-')}.html", "name": n, "n": n.lower()}
           for i, n in enumerate(["Samsung Galaxy A56 8GB RAM 256GB", "Samsung Galaxy A17 8GB RAM 256GB",
                                  "Apple iPhone 16", "Apple iPhone 16 Pro Max", "Logitech Wireless Mouse M170",
                                  "Logitech Wireless Mouse M171", "Apple iPhone 160 Case", "Apple iPhone 16e 128GB"])]

    def names(self, q):
        hits, _ = self.D._match(self.IDX, q, {})
        return [h["name"] for h in hits]

    def test_split_model_number(self):
        self.assertEqual(self.names("galaxy a 56"), ["Samsung Galaxy A56 8GB RAM 256GB"])

    def test_no_space(self):
        self.assertEqual(self.names("iphone16")[:2], ["Apple iPhone 16", "Apple iPhone 16 Pro Max"])
        self.assertNotIn("Apple iPhone 160 Case", self.names("iphone 16"))
        self.assertNotIn("Apple iPhone 16e 128GB", self.names("iphone 16"))
        self.assertEqual(self.names("iphone 16e"), ["Apple iPhone 16e 128GB"])

    def test_typos(self):
        self.assertIn("Samsung Galaxy A56 8GB RAM 256GB", self.names("samsang galaxy a56"))
        self.assertEqual(self.names("logitec mouse m170"), ["Logitech Wireless Mouse M170"])

    def test_close_matches_when_one_word_missing(self):
        hits, close = self.D._match(self.IDX, "apple iphone 16 ultra", {})
        self.assertTrue(close)
        self.assertEqual(hits[0]["name"], "Apple iPhone 16")


class LocalAI(unittest.TestCase):
    def groups(self, titles):
        import ml
        items = [{"title": t, "pkr": 1000 + n, "store": "S", "url": f"u{n}", "suspect": False,
                  "attrs": smart.attributes(t)} for n, t in enumerate(titles)]
        return sorted(sorted(items[i]["title"] for i in g["members"]) for g in ml.group_offers(items))

    def test_same_model_grouped(self):
        g = self.groups(["Samsung Galaxy A56 8GB RAM 256GB PTA", "Samsung Galaxy A56 (8GB/256GB) PTA", "Galaxy A56 8/256 PTA Black"])
        self.assertEqual(len(g), 1)

    def test_pta_and_non_pta_kept_apart(self):  # PTA tax: very different prices for the same phone
        g = self.groups(["Apple iPhone 16 128GB Single Sim NON PTA", "Apple iPhone 16 128GB Single Sim PTA Approved"])
        self.assertEqual(len(g), 2)

    def test_different_models_kept_apart(self):
        g = self.groups(["Samsung Galaxy A56 8GB 256GB", "Samsung Galaxy A36 8GB 256GB", "Samsung Galaxy A56 12GB 256GB",
                         "Apple iPhone 16 128GB", "Apple iPhone 16 Pro 128GB", "Logitech Mouse M170", "Logitech Mouse M171"])
        self.assertEqual(len(g), 7)

    def test_tfidf_word_order_and_typos(self):
        import ml
        m = ml.TfIdf(["Samsung Galaxy A56", "Apple Watch Series 10", "Logitech Mouse M170"])
        self.assertEqual(int(m.similar("galaxy samsung a56").argmax()), 0)
        self.assertEqual(int(m.similar("aple wach").argmax()), 1)
