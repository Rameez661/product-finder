# Product Finder

Ek product search karein. App sab stores check karke batati hai ke woh **kahan sasta** aur **kahan behtar deal** par hai.
Card par tap karein to store ka product page khul jata hai. Phone mein us store ki app (jaise Daraz) installed ho
to aksar seedha app mein khulta hai. Screen (UI) English mein hai.

Do tabs:
- **Local (Pakistan):** Daraz, PriceOye, Telemart, Mega.pk, HomeShopping, iShopping, Symbios, Shophive, Czone, Naheed, Highfy, Paklap, Galaxy.pk, HumMart
- **International:** Google Shopping ke zariye Amazon, Walmart, Best Buy, eBay waghera (SerpApi key se). Price PKR mein bhi.

## Chalane ka tareeqa

`start.bat` par double-click, ya `py server.py`. Browser mein http://127.0.0.1:8060 khulega.
Koi library install nahi hoti (sirf Python ki built-in cheezein).

**Phone par:** computer aur phone ek hi Wi-Fi par hon to `py server.py --lan`. Terminal mein jo address aaye, phone ke
browser mein kholein aur **"Add to Home screen"** karein. (`--lan` se app aap ke network par khulti hai, sirf bharosemand Wi-Fi par.)

## Search kya samajhti hai

| Aap likhein | App samajhti hai |
|---|---|
| `iphon 16`, `samsang galaxy`, `logitec mouse` | spelling theek: iphone, samsung, logitech |
| `iphone16`, `galaxy a 56` | spacing theek: iphone 16, galaxy a56 |
| `mobile under 50k`, `laptop 1-1.5 lakh`, `3 lakh tak` | budget filter (Rs) |
| `pta approved`, `non pta` | PTA filter |
| `sasta`, `best`, `price`, `ka`, `chahiye` ... | faltu alfaaz hata diye jate hain |
| `mobile`, `laptop`, `tablet`, `watch`, `car`, `gari`, `bike` | category (store ke URL se, jaise `/mobiles_products/`, `/new-cars/`) |
| `alto car`, `honda city car`, `honda cd 70 bike` | nayi gaari / bike ki price (PakWheels) |
| `zah rtx 4060`, `pakwheels city`, `mega iphone` | store ka naam = sirf usi store mein search |

Jab koi product search ke har lafz se asli match kare ("civic" se Honda Civic), to sirf spelling-maafi wale milte julte (Xiaomi "Civi", BYD "Atto") hata diye jate hain.
Out-of-stock products "Out of stock" ke nishan ke saath aakhir mein aate hain, aur "Cheapest" / "Smart pick" mein nahi ginte.

Model numbers exact match hote hain (`m170` se `m171` nahi aata, `16` se `160` nahi). Agar har lafz match na ho to
ek lafz kam wale products **"Close match"** ke nishan ke saath aate hain.

Har product ke variant khud pehchane jate hain: storage, RAM, PTA / Non-PTA, single/dual SIM, used/open box.

## Local AI (`ml.py`, sirf Python + numpy, internet ya API key ke baghair)

| Kaam | Tareeqa |
|---|---|
| **Search ranking** | Product naamon ke character 3-gram **TF-IDF** vectors aur **cosine similarity**. Alfaaz ki tarteeb aur chhoti ghaltiyan bardasht ("galaxy samsung a56", "aple watch"). Word-match aur similarity mila kar ranking. |
| **Did you mean** | Koi product match na ho to sab se milte julte naam (similarity se) dikhaye jate hain |
| **Same product jodna** | Ek hi product ke offers (alag stores / listings) ek card mein: "+2 more offers · Rs X – Y". Shartein: naam milta ho, aur model number (A56 ≠ A36), edition (16 ≠ 16 Pro), storage, RAM aur PTA status bilkul same hon |
| **Price history** | Har dekhi gayi price yaad rehti hai (`data/price_history.json`): "Lowest seen", trend |
| **Deal ka faisla** | Isi product ki aam price (doosre offers ya apni history) se muqabla: "Good price", "Above typical", "Price dropped 5%" |
| **Smart pick** | Sab se upar ek recommendation, wajah ke saath (sab se sasta, achhi deal, PTA approved, rating) |

Price history waqt ke saath banti hai, is liye "Lowest seen" aur trend kuch din istemal ke baad behtar hote jayenge.
Claude jaisa bara AI model is mein nahi hai (aap ne local rakhne ka kaha); `ml.py` mein sab kuch is computer par chalta hai.

## Screen par

- **Sort:** Lowest price (default), Best deal, Highest price, Rating
- **Filters:** price range (Min/Max ya tayyar ranges), stores (ek se zyada), PTA, storage
- **Load more:** neeche scroll karne par har store se agle 16 products khud load hote hain. Har dafa saare loaded
  products ek saath rank hote hain, is liye "Cheapest" aur "Best deal" hamesha poori list mein se hain.
- Badi screen par cards kai columns mein (poora page istemal hota hai).

## Data kahan se aata hai

| Store | Tareeqa |
|---|---|
| Tamam Pakistani stores | **Seedha**, jahan network aur store ki robots.txt ijazat dein (neeche dekhein) |
| Jo store seedha na parha ja sake | Google (google.com.pk) ke zariye, SerpApi key se |
| Nayi gaariyan aur bikes | **PakWheels.com** (`/new-cars/` aur `/bikes/` model pages, robots.txt ijazat deta hai): price "from" base variant "up to" top variant. "Market price" ke nishan ke saath |
| Computer products | **Zah Computers** (zahcomputers.pk): seedha, sirf `/product/` pages |
| Market price (price guide) | **MobileMall.pk**: 11,000+ phones ki Pakistani market price (office se khulta hai, robots.txt ijazat deta hai). Yeh dukaan nahi, is liye "Market price" ke nishan ke saath aata hai, "Cheapest" / "Smart pick" mein nahi ginta, aur PTA approved offers ke liye "Good price" ka muqabla banta hai |
| International | Google Shopping (US), SerpApi key se |
| USD → PKR | ExchangeRate-API (open.er-api.com) |
| Tasveerein | Server khud la kar dikhata hai (`/img`), sirf list wale stores, un ki image CDN aur Google thumbnails se |

### Seedha parhna

1. Pehle store ki **robots.txt**. Jo pages store ne mana kiye hon, woh nahi khulte. Store ki apni search kabhi nahi chalti.
2. Store ke public **sitemap** se din mein ek dafa product list (background mein).
3. Search par list app ke andar match hoti hai; sirf behtareen match pages khulte hain, ek store par zyada se zyada
   2 requests saath, kam az kam 0.5 second ke faasle se (store ka Crawl-delay bhi mana jata hai).

## Store ki website badle to kya hota hai

App ko is tarah banaya gaya hai ke kisi store ki website badalne se app na toote:

- **Price nikalne ke 4 tareeqe**, ek na chale to agla: schema.org JSON-LD → product meta tags → microdata →
  page par likhi "Rs 12,345" (aakhri tareeqa, kam bharose wala, "Confirm price on store" ke nishan ke saath).
  Har store ka jo tareeqa chalta hai, agli dafa woh pehle try hota hai.
- **Jaanch:** price ki had (Rs 50 se 5 crore), aur page ka title product se milna chahiye. Kamzor tareeqe se aayi price
  pichli sahi price se 3 guna alag ho to nahi maani jati.
- **Purani sahi price:** page na khule ya price na mile to aakhri sahi price (30 din tak) **"Last known price"** ke
  nishan aur tareekh ke saath dikhti hai.
- **Hataye gaye products** (404) list se khud nikal jate hain; zyada hon to product list dobara banti hai.
- **Store ki sehat:** har store ke aakhri 40 page reads ka record. Zyada fail hon to store **"Site changed"** dikhata hai
  aur Google fallback istemal hota hai. Jis product ki store ne price hi nahi di (band / stock khatam), woh kharabi nahi gini jati.
  Haal dekhne ke liye: http://127.0.0.1:8060/api/health
- **Network:** ek page ka timeout store ko block nahi karta; lagatar 2 network failures par store 15 minute ke liye
  "Blocked on this network" (search tez rehti hai). Store 403/429 de to 1 ghanta ruk kar.

**Check karne ke liye:**

```
py selftest.py        # har store ke kuch asli pages parh kar batata hai: ok / PARTIAL / BROKEN
py -m unittest discover -s tests    # 25 tests: website badalne ki naqal, robots.txt, search ki ghaltiyan, local AI
```

Agar kisi store ka sitemap ya URL ka tareeqa badal jaye to `sources/stores.py` mein us store ka `sitemap_hint` /
`product_re` set karein.

Office network par abhi sirf Mega.pk khulta hai; baqi stores ghar ke Wi-Fi / mobile data par khud check honge
(yeh office se test nahi ho saka).

## SerpApi key (fallback aur International ke liye)

1. https://serpapi.com par apni email se free account (free plan mein har mahine kuch searches muft).
2. Dashboard se API key copy karein.
3. Is folder mein `config.json` (`config.example.json` ki copy): `{ "serpapi_key": "YOUR_KEY_HERE" }`

Har search ka nateeja 6 ghante cache hota hai taake limit jaldi khatam na ho.

## "Cheapest" aur "Best deal"

- Jo product baqiyon ki aam price ke 35% se bhi kam ho, us par **"Possibly accessory / other model"** aur woh
  "Cheapest" nahi ginta (500 rupay ka cover iPhone ki sasti price nahi banta).
- **Deal score (0-100):** price 65% + rating 35% (reviews ki tadaad ke saath). Rating na ho to sirf price.

Prices badalti rehti hain. Khareedne se pehle store par price aur PTA/warranty confirm karein.

## Files

- `server.py`: web server, paging ("Load more"), filters, ranking ka jor
- `smart.py`: search samajhna (spelling, budget, PTA, category), variant pehchanna
- `ml.py`: local AI (TF-IDF search, product grouping, price history, deal, smart pick)
- `rank.py`: relevance, accessory filter, deal score, badges
- `sources/direct.py`: har store ko seedha parhna (robots.txt, sitemap, fuzzy match, block handling, purani price)
- `sources/extract.py`: page se price nikalne ke 4 tareeqe + jaanch
- `sources/health.py`: har store ki sehat
- `sources/robots.py`: robots.txt (wildcards ke saath)
- `sources/serp.py`: SerpApi (Google Shopping, Google local)
- `sources/stores.py`: Pakistani stores ki list
- `selftest.py`, `tests/`: checks
- `static/`: screen (PWA: phone par install ho sakti hai)
- `data/`: cache (delete karne se sab dobara download hoga)

## Online version (GitHub Pages)

`.github/workflows/update.yml` har roz (Pakistan time subah 6 baje) GitHub ke servers par chalta hai:

1. `snapshot.py`: har store ke product pages parhta hai. robots.txt mana jata hai, ek store par zyada se zyada 2 requests saath,
   aur har store par had: 3,000 pages ya 40 minute (`SNAPSHOT_MAX_PAGES`, `SNAPSHOT_MAX_MINUTES`).
2. `hosted/build_data.py`: `data.json` banata hai (pichle 7 din mein parhi gayi prices).
3. `hosted/index.html` + `data.json` GitHub Pages par publish hote hain.

Website par search, filters, grouping aur Smart pick browser mein hi chalte hain. Yeh **live nahi**, roz ek dafa update hota hai.
Jo store GitHub ke servers ko rok de, woh website ke neeche "Stores checked" mein likha aata hai.

Haath se update: GitHub par **Actions → Update prices and publish site → Run workflow**.
