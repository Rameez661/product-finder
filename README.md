# Product Finder

Search for a product once and see where it is **cheapest** and where it is the **best deal** across Pakistani online
stores and price guides. Tap a result to open the product on the store's site (on a phone, that often opens the
store's own app).

- **Website:** https://rameez661.github.io/product-finder/ (updated daily, no login)
- **Local app:** live search on your own computer (see [Run it locally](#run-it-locally))

Prices change. Always confirm the price, PTA status and warranty on the store before buying.

## What the search understands

| You type | It understands |
|---|---|
| `iphon 16`, `samsang galaxy`, `logitec mouse` | spelling fixed: iphone, samsung, logitech |
| `iphone16`, `galaxy a 56` | spacing fixed: iphone 16, galaxy a56 |
| `mobile under 50k`, `laptop 1-1.5 lakh`, `3 lakh tak` | budget filter (Rs), English or Roman Urdu |
| `pta approved`, `non pta` | PTA filter |
| `sasta`, `best`, `price`, `ka`, `chahiye` ... | filler words are ignored |
| `mobile`, `laptop`, `tablet`, `watch`, `car`, `gari`, `bike` | category, taken from the store's URL (e.g. `/mobiles_products/`, `/new-cars/`) |
| `alto car`, `honda city car`, `honda cd 70 bike` | new car / bike prices (PakWheels) |
| `zah rtx 4060`, `pakwheels city`, `mega iphone` | a store name searches that store only |

- **Exact matches win:** when some products match every search word ("civic" → Honda Civic), typo-tolerant
  look-alikes (Xiaomi "Civi", BYD "Atto") are dropped.
- **Model numbers match exactly:** `m170` does not return `m171`, `16` does not return `160` or `16e`.
- **Close matches:** if no product matches every word, products missing one word are shown with a "Close match" badge.
- **Variants** are recognised from titles: storage, RAM, PTA / Non-PTA, single / dual SIM, used / open box.
- **Out-of-stock** products are shown last with an "Out of stock" badge and never count as "Cheapest" or "Smart pick".

## Local AI (`ml.py`: Python + numpy, no internet, no API key)

| Feature | How |
|---|---|
| **Search ranking** | Character 3-gram **TF-IDF** vectors and **cosine similarity** over product names, blended with the word match. Tolerates word order and small typos ("galaxy samsung a56", "aple watch"). |
| **Did you mean** | When nothing matches, the most similar product names are suggested. |
| **Same-product grouping** | Offers of one product (across stores and listings) become one card: "+2 more offers · Rs X – Y". Names must be similar, and model number (A56 ≠ A36), edition (16 ≠ 16 Pro), storage, RAM and PTA status must be identical. |
| **Price history** | Every price seen is remembered (`data/price_history.json`): "Lowest seen", trend. |
| **Deal check** | Price compared with the typical price of the same product (other offers, its own history, or a price guide): "Good price", "Above typical", "Price dropped 5%". |
| **Smart pick** | One recommendation at the top, with reasons (lowest price, good deal, PTA approved, rating). |

Price history builds up over time, so "Lowest seen" and trends improve after some days of use.

## Where the data comes from

| Source | How |
|---|---|
| Pakistani stores (Daraz, PriceOye, Telemart, Mega.pk, HomeShopping, iShopping, Symbios, Shophive, Czone, Naheed, Highfy, Paklap, Galaxy.pk, HumMart) | Read **directly** wherever the network and the store's robots.txt allow it (see below) |
| **Zah Computers** (zahcomputers.pk) | Read directly, `/product/` pages only |
| **PakWheels** (new cars and bikes) | `/new-cars/` and `/bikes/` model pages, allowed by its robots.txt. Price shown "from" the base variant "up to" the top variant, marked "Market price" |
| **MobileMall** (phone price guide) | Pakistani market price per phone. Not a shop: marked "Market price", never counted as "Cheapest" or "Smart pick", used as the reference for "Good price" on PTA-approved offers |
| Stores that cannot be read directly | Google search (google.com.pk) through SerpApi, if a key is configured |
| International tab | Google Shopping (US) through SerpApi, if a key is configured |
| USD → PKR | ExchangeRate-API (open.er-api.com) |

### How stores are read

1. The store's **robots.txt** comes first. Pages it disallows are never opened, and the store's own search is never used.
2. A product list is built from the store's public **sitemap**, once a day, in the background.
3. A search is matched against that list inside the app, and only the best-matching product pages are opened:
   at most 2 requests at a time per store, at least 0.5 s apart (a longer Crawl-delay is respected).
4. Price, rating, stock and image come from the page's standard **schema.org** data or product meta tags.

## When a store's website changes

The app is built so that a change on a store's site does not break it:

- **Four ways to read a price**, each tried if the previous one fails: schema.org JSON-LD → product meta tags →
  microdata → a visible "Rs 12,345" on the page (last resort, marked "Confirm price on store").
  The method that works for a store is tried first next time.
- **Checks:** the price must be within a sane range (Rs 50 to Rs 50 crore) and the page title must match the product.
  A weak reading that is more than 3× away from the last good price is not trusted.
- **Last known price:** if a page cannot be read, the last good price (up to 30 days old) is shown, marked
  "Last known price" with its date.
- **Removed products** (404) are dropped from the list; if many disappear, the list is rebuilt.
- **Store health:** the last 40 page reads per store are tracked. If most fail, the store shows "Site changed" and the
  Google fallback is used. A product the store lists without a price (discontinued, out of stock) does not count as a failure.
  Live status: http://127.0.0.1:8060/api/health
- **Network:** one slow page does not block a store; two network failures in a row mark it
  "Blocked on this network" for 15 minutes so searches stay fast. A 403/429 answer pauses the store for an hour.

**Checks:**

```
py selftest.py                     # reads a few real pages per store: ok / PARTIAL / BROKEN
py -m unittest discover -s tests   # 25 tests: simulated site changes, robots.txt, search mistakes, local AI
```

If a store changes its sitemap or URL scheme, set its `sitemap_hint` / `product_re` in `sources/stores.py`.

## Run it locally

Double-click `start.bat`, or run `py server.py`, then open http://127.0.0.1:8060.
Nothing to install apart from Python and numpy.

**On a phone:** with the computer and phone on the same Wi-Fi, run `py server.py --lan` and open the address it prints
in the phone's browser, then use **"Add to Home screen"**. `--lan` makes the app reachable by everyone on that network,
so use it only on a trusted Wi-Fi.

The local app searches live. Stores that the current network blocks are shown as "Blocked on this network".

### Screen

- **Sort:** Lowest price (default), Best deal, Highest price, Rating
- **Filters:** price range (min/max or quick ranges), stores (several at once), PTA, storage
- **Load more:** scrolling down loads the next 16 products per store. Everything loaded is ranked together,
  so "Cheapest" and "Best deal" always refer to the whole list.

### SerpApi key (optional: Google fallback and International tab)

1. Create a free account at https://serpapi.com with your own email.
2. Copy your API key from the dashboard.
3. Create `config.json` in this folder (copy `config.example.json`): `{ "serpapi_key": "YOUR_KEY_HERE" }`

`config.json` is in `.gitignore` and is never uploaded. Each search result is cached for 6 hours to save quota.

## "Cheapest" and "Best deal"

- A product priced below 35% of the typical price of the others is marked **"Possibly accessory / other model"** and
  is not counted as "Cheapest" (a Rs 500 cover is not a cheap iPhone).
- **Deal score (0-100):** price 65% + rating 35% (weighted by the number of reviews). Without ratings, price only.

## Online version (GitHub Pages)

`.github/workflows/update.yml` runs every day at 06:00 Pakistan time on GitHub's servers:

1. `snapshot.py` reads every store's product pages with the same polite rules, limited per store to
   3,000 pages or 40 minutes (`SNAPSHOT_MAX_PAGES`, `SNAPSHOT_MAX_MINUTES`).
2. `hosted/build_data.py` writes `data.json` (prices read in the last 7 days).
3. `hosted/index.html` and `data.json` are published to GitHub Pages.

Search, filters, grouping and Smart pick run in the browser. The website is **not live**: it is refreshed once a day.
Stores that refuse GitHub's servers are listed under "Stores checked" at the bottom of the page.

Manual refresh: **Actions → Update prices and publish site → Run workflow**.

## Files

- `server.py`: web server, paging ("Load more"), filters, ties the pieces together
- `smart.py`: query understanding (spelling, budget, PTA, category), variant detection
- `ml.py`: local AI (TF-IDF search, product grouping, price history, deal check, Smart pick)
- `rank.py`: relevance, accessory filter, deal score, badges
- `sources/direct.py`: reading stores directly (robots.txt, sitemaps, fuzzy matching, blocking, last known prices)
- `sources/extract.py`: the four price-reading methods and their checks
- `sources/health.py`: per-store health
- `sources/robots.py`: robots.txt with wildcard support
- `sources/serp.py`: SerpApi (Google Shopping, Google local)
- `sources/stores.py`: list of stores and price guides
- `snapshot.py`, `hosted/`: daily snapshot and the static website
- `selftest.py`, `tests/`: checks
- `static/`: the local app's screen (installable as a PWA)
- `data/`: caches (not uploaded; delete to download everything again)
