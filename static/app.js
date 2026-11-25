"use strict";
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : null);
const rs = (v) => "Rs " + Math.round(v).toLocaleString("en-PK");
const money = (v, cur) => (cur === "USD" ? "$" + v.toLocaleString("en-US", { maximumFractionDigits: 2 }) : cur + " " + v.toLocaleString());

const EXAMPLES = {
  local: ["iPhone 16", "Samsung Galaxy A56", "Logitech mouse", "HP laptop", "mobile under 50k", "alto car", "honda 125 bike"],
  intl: ["iPhone 16", "PlayStation 5", "Kindle Paperwhite", "Logitech MX Master 3S", "AirPods Pro"],
};
let TAB = localStorage.getItem("pf-tab") || "local";
let DATA = null, SORT = "cheap", REQ = 0, LOADING = false, GROUP = localStorage.getItem("pf-group") !== "0";
// filters (client side, over everything loaded so far)
let STORES = new Set(), SIZE = "all", PTA = "all", PMIN = null, PMAX = null;
function resetFilters() { STORES = new Set(); SIZE = "all"; PTA = "all"; PMIN = null; PMAX = null; }

// ------------------------------------------------------------------ setup
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => setTab(b.dataset.tab)));
$("#form").addEventListener("submit", (e) => { e.preventDefault(); go($("#q").value); });
setTab(TAB, true);

const start = new URLSearchParams(location.search);
if (start.get("q")) { $("#q").value = start.get("q"); go(start.get("q")); }

fetch("api/stores").then((r) => r.json()).then((s) => {
  $("#storeList").innerHTML = `<b>Local stores:</b> ${s.local.map(esc).join(", ")}.` +
    (s.has_key ? "" : ` <br>Stores are read directly wherever your network allows. A SerpApi key adds a Google fallback and the International tab (see README).`);
}).catch(() => {});

if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});

function setTab(t, silent) {
  TAB = t;
  localStorage.setItem("pf-tab", t);
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === t)));
  $("#examples").innerHTML = EXAMPLES[t].map((x) => `<button class="chip" type="button">${esc(x)}</button>`).join("");
  $("#examples").querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => { $("#q").value = c.textContent; go(c.textContent); }));
  if (!silent && $("#q").value.trim().length >= 2) go($("#q").value);
}

// ------------------------------------------------------------------ search
async function go(q) {
  q = q.trim();
  if (q.length < 2) return;
  $("#q").blur();
  history.replaceState(null, "", "?q=" + encodeURIComponent(q));
  $("#home").hidden = true;
  const box = $("#results");
  box.hidden = false;
  box.innerHTML = `<p class="muted small">Checking stores…</p><div class="list">${"<div class='skel'></div>".repeat(4)}</div>`;
  const id = ++REQ;
  try {
    const r = await fetch(`api/search?q=${encodeURIComponent(q)}&tab=${TAB}`);
    const j = await r.json();
    if (id !== REQ) return;  // a newer search started meanwhile
    if (!r.ok) throw new Error(j.error || r.statusText);
    DATA = j; SORT = "cheap"; resetFilters();
    render();
  } catch (e) {
    if (id === REQ) box.innerHTML = `<div class="empty">Search failed: ${esc(e.message)}</div>`;
  }
}

async function loadMore() {
  if (!DATA || LOADING || !DATA.has_more) return;
  LOADING = true;
  render();
  const id = REQ;
  try {
    const r = await fetch(`api/search?q=${encodeURIComponent(DATA.query)}&tab=${DATA.tab}&page=${DATA.page + 1}`);
    const j = await r.json();
    if (id !== REQ) return;
    if (!r.ok) throw new Error(j.error || r.statusText);
    DATA = j;  // the server returns everything loaded so far, ranked together
  } catch (e) {
    DATA.loadError = e.message;
  } finally {
    LOADING = false;
    if (id === REQ) render();
  }
}

function passes(i) {
  const a = i.attrs || {};
  if (STORES.size && !STORES.has(i.store)) return false;
  if (SIZE !== "all" && a.storage !== SIZE) return false;
  if (PTA === "pta" && a.pta !== true) return false;
  if (PTA === "non" && a.pta !== false) return false;
  if ((PMIN != null || PMAX != null) && !i.pkr) return false;
  if (PMIN != null && i.pkr < PMIN) return false;
  if (PMAX != null && i.pkr > PMAX) return false;
  return true;
}
const activeFilters = () => (STORES.size ? 1 : 0) + (SIZE !== "all") + (PTA !== "all") + (PMIN != null || PMAX != null ? 1 : 0);

// ------------------------------------------------------------------ render
function render() {
  const d = DATA, box = $("#results");
  const view = d.items.filter(passes);
  // price guides are a reference, not an offer; use them for the summary only when no shop has a price
  const shopPriced = view.filter((i) => i.pkr && !i.suspect && !i.guide && !i.out_of_stock);
  const priced = shopPriced.length ? shopPriced : view.filter((i) => i.pkr && !i.suspect && !i.out_of_stock);
  const cheapest = priced.length ? priced.reduce((a, b) => (b.pkr < a.pkr ? b : a)) : null;
  const storesOk = d.stores.filter((s) => s.status === "ok").length;
  const needKey = d.stores.filter((s) => s.status === "need_key");
  const blocked = d.stores.filter((s) => s.status === "blocked");
  const indexing = d.stores.filter((s) => s.status === "indexing");
  const degraded = d.stores.filter((s) => s.status === "degraded");
  const storeCount = {};
  d.items.forEach((i) => { storeCount[i.store] = (storeCount[i.store] || 0) + 1; });
  const storeNames = Object.keys(storeCount).sort((a, b) => storeCount[b] - storeCount[a]);
  const hasPta = d.items.some((i) => i.attrs && i.attrs.pta != null);
  const sizes = [...new Set(d.items.map((i) => i.attrs && i.attrs.storage).filter(Boolean))]
    .sort((a, b) => sizeGb(a) - sizeGb(b));

  let items = view;
  // cheapest first, but accessories / unknown prices go last
  // in stock first; accessories and unknown prices last
  const oos = (x) => (x.out_of_stock ? 1 : 0);
  if (SORT === "cheap") items = [...items].sort((a, b) => (oos(a) - oos(b)) || (a.suspect - b.suspect) || (a.pkr ?? 1e18) - (b.pkr ?? 1e18));
  if (SORT === "costly") items = [...items].sort((a, b) => (a.suspect - b.suspect) || (b.pkr ?? -1) - (a.pkr ?? -1));
  if (SORT === "rating") items = [...items].sort((a, b) => (b.rating ?? 0) - (a.rating ?? 0) || (b.reviews ?? 0) - (a.reviews ?? 0));

  box.innerHTML = `
    ${understoodBar(d)}
    ${pickPanel(d)}
    ${degraded.length ? `<div class="notice"><b>${degraded.map((x) => esc(x.name)).join(", ")}:</b> the store website seems to have changed.
      Showing last known prices (marked "Last known price") and the Google fallback.</div>` : ""}
    ${indexing.length ? `<div class="notice"><b>${indexing.map((x) => esc(x.name)).join(", ")}:</b> building the product list.
      <button type="button" class="chip" id="retry">Search again</button></div>` : ""}
    ${blocked.length ? `<div class="notice"><b>${blocked.length} stores are blocked on this network</b> (${blocked.map((x) => esc(x.name)).slice(0, 4).join(", ")}${blocked.length > 4 ? "…" : ""}).
      They are checked automatically on home Wi-Fi or mobile data${d.has_key ? "" : ", or add a SerpApi key (Google fallback)"}.</div>` : ""}
    ${needKey.length ? `<div class="notice"><b>${needKey.length === 1 && TAB === "intl" ? "International stores" : needKey.length + " stores"} not checked.</b>
      They need a SerpApi key.</div>` : ""}
    ${priced.length ? `<div class="summary">
      <div class="stat"><div class="l">Cheapest</div><div class="v num">${rs(cheapest.pkr)}</div><div class="s">${esc(cheapest.store)}</div></div>
      <div class="stat"><div class="l">Price range</div><div class="v num">${rangeTxt(priced)}</div><div class="s">${priced.length} offers</div></div>
      <div class="stat"><div class="l">Stores</div><div class="v num">${storesOk} / ${d.stores.length}</div><div class="s">with results</div></div>
    </div>` : ""}
    ${d.items.length ? `
    <div class="bar">
      <span class="muted small">${view.length === d.items.length ? `${d.items.length} results` : `${view.length} / ${d.items.length} results`}</span>
      <button type="button" class="chip ${GROUP ? "on" : ""}" id="grp" title="Show each product once, with its other offers">Group same product</button>
      <div class="seg" role="group" aria-label="Sort">
        ${[["cheap", "Lowest price"], ["deal", "Best deal"], ["costly", "Highest price"], ["rating", "Rating"]].map(([k, l]) => `<button type="button" data-s="${k}" class="${SORT === k ? "on" : ""}">${l}</button>`).join("")}
      </div>
    </div>
    ${filterPanel(d, storeNames, storeCount, sizes, hasPta)}
    <div class="list">${items.length ? (GROUP ? groupedCards(d, items, cheapest) : items.map((i) => card(i, cheapest)).join("")) : `<div class="empty">Nothing matches these filters. <button type="button" class="chip" id="clearF">Clear filters</button></div>`}</div>
    ${d.has_more || LOADING ? `<button type="button" class="more" id="more" ${LOADING ? "disabled" : ""}>${LOADING ? "Loading more products…" : "Load more products"}</button>` : d.page > 1 ? `<p class="muted small center">All matching products are shown.</p>` : ""}
    ${d.loadError ? `<p class="muted small center">Could not load more: ${esc(d.loadError)}</p>` : ""}
    ${d.hidden ? `<p class="muted small">${d.hidden} results hidden because they did not match the search.</p>` : ""}`
    : `<div class="empty">${emptyText(d)}</div>`}
    ${storesPanel(d)}
    <p class="muted small">Prices were read from store websites at ${d.time.slice(11, 16)} and can change. Confirm on the store before buying.
      ${d.fx ? `International prices converted at ${rs(d.fx.usd_pkr)} = $1 (ExchangeRate-API), excluding customs and shipping.` : ""}</p>`;

  const retry = box.querySelector("#retry");
  if (retry) retry.addEventListener("click", () => go(d.query));
  box.querySelectorAll("[data-s]").forEach((b) => b.addEventListener("click", () => { SORT = b.dataset.s; render(); }));
  box.querySelectorAll("[data-st]").forEach((b) => b.addEventListener("click", () => {
    const s = b.dataset.st;
    if (s === "all") STORES = new Set(); else if (STORES.has(s)) STORES.delete(s); else STORES.add(s);
    render();
  }));
  box.querySelectorAll("[data-sz]").forEach((b) => b.addEventListener("click", () => { SIZE = b.dataset.sz; render(); }));
  box.querySelectorAll("[data-pta]").forEach((b) => b.addEventListener("click", () => { PTA = b.dataset.pta; render(); }));
  box.querySelectorAll("[data-pr]").forEach((b) => b.addEventListener("click", () => {
    const [lo, hi] = b.dataset.pr.split("-").map((x) => (x ? Number(x) : null));
    PMIN = lo; PMAX = hi; render();
  }));
  const pmin = box.querySelector("#pmin"), pmax = box.querySelector("#pmax");
  const readP = (el) => { const v = Number(String(el.value).replace(/[^\d]/g, "")); return v > 0 ? v : null; };
  if (pmin) pmin.addEventListener("change", () => { PMIN = readP(pmin); render(); });
  if (pmax) pmax.addEventListener("change", () => { PMAX = readP(pmax); render(); });
  box.querySelectorAll("#clearF, #clearF2").forEach((b) => b.addEventListener("click", () => { resetFilters(); render(); }));
  const grp = box.querySelector("#grp");
  if (grp) grp.addEventListener("click", () => { GROUP = !GROUP; localStorage.setItem("pf-group", GROUP ? "1" : "0"); render(); });
  const more = box.querySelector("#more");
  if (more) {
    more.addEventListener("click", loadMore);
    // infinite scroll: load the next batch automatically when the button comes into view
    if ("IntersectionObserver" in window && !LOADING && !DATA.loadError) {
      const io = new IntersectionObserver((es) => { if (es.some((x) => x.isIntersecting)) { io.disconnect(); loadMore(); } },
        { rootMargin: "600px 0px" });
      io.observe(more);
    }
  }
  const fd = box.querySelector("details.filt");
  if (fd) fd.addEventListener("toggle", () => { FILT_OPEN = fd.open; });
  box.querySelectorAll("[data-fix]").forEach((b) => b.addEventListener("click", () => { $("#q").value = b.dataset.fix; go(b.dataset.fix); }));
  // image: via our server first; if that fails try the store directly; then a letter placeholder
  box.querySelectorAll("img.thumb").forEach((img) => img.addEventListener("error", () => {
    if (img.dataset.direct && !img.dataset.tried) { img.dataset.tried = "1"; img.src = img.dataset.direct; }
    else img.replaceWith(placeholder(img.alt));
  }));
}

function rangeTxt(p) {
  const v = p.map((i) => i.pkr), lo = Math.min(...v), hi = Math.max(...v);
  const k = (x) => (x >= 1e5 ? (x / 1e3).toFixed(0) + "k" : Math.round(x).toLocaleString("en-PK"));
  return lo === hi ? rs(lo) : `${k(lo)}–${k(hi)}`;
}

function card(i, cheapest) {
  const url = safeUrl(i.url);
  const img = safeUrl(i.image);
  const extra = [];
  if (i.stale) extra.push(["warn", `Last known price${i.checked ? " · " + fmtDay(i.checked) : ""}`]);
  else if (i.confidence === "low") extra.push(["warn", "Confirm price on store"]);
  if (i.close) extra.push(["info", "Close match"]);
  if (i.out_of_stock) extra.unshift(["warn", "Out of stock", "Listed by the store but currently not available; price shown is the last listed one"]);
  if (i.guide) extra.unshift(["info", "Market price", "Price guide, not a shop: used as the reference price"]);
  if (i.deal) extra.unshift([i.deal.tone, i.deal.label, i.deal.why]);
  const badges = (i.badges || []).map((b) => `<span class="badge ${b.startsWith("Possibly") ? "warn" : b === "Top rated" ? "info" : "good"}">${esc(b)}</span>`).join("")
    + extra.map(([c, t, why]) => `<span class="badge ${c}"${why ? ` title="${esc(why)}"` : ""}>${esc(t)}</span>`).join("");
  const h = i.history;
  const hist = h && h.points >= 2 ? `<span class="hist num">Lowest seen ${rs(h.low)} · tracked since ${fmtDay(h.since)}</span>` : "";
  const a = i.attrs || {};
  const specs = [a.storage, a.ram && a.ram + " RAM", a.pta === true ? "PTA" : a.pta === false ? "Non-PTA" : null, a.sim, a.condition]
    .filter(Boolean).map((t) => `<span class="spec">${esc(t)}</span>`).join("");
  const diff = i.pkr && cheapest && i.pkr > cheapest.pkr && !i.suspect && !i.guide && !cheapest.guide
    ? `<span class="diff num">+${rs(i.pkr - cheapest.pkr)} vs cheapest (${((i.pkr / cheapest.pkr - 1) * 100).toFixed(0)}%)</span>` : "";
  const price = i.pkr
    ? `<div class="price num">${i.price_max ? `<span class="from">from</span> ` : ""}${rs(i.pkr)}${i.price_max ? `<span class="orig">up to ${rs(i.price_max)} (top variant)</span>` : ""}${i.currency !== "PKR" ? `<span class="orig">${esc(money(i.price, i.currency))}</span>` : ""}</div>`
    : `<div class="price none">No price listed</div>`;
  const rating = i.rating ? `<span>★ ${Number(i.rating).toFixed(1)}${i.reviews ? ` (${Number(i.reviews).toLocaleString()})` : ""}</span>` : "";
  const inner = `
    ${img ? `<img class="thumb" src="img?u=${encodeURIComponent(img)}" data-direct="${esc(img)}" alt="${esc(i.store)}" loading="lazy" referrerpolicy="no-referrer">` : placeholder(i.store).outerHTML}
    <div>
      <div class="title">${esc(i.title)}</div>
      <div class="meta"><span class="store">${esc(i.store)}</span>${rating}${i.delivery ? `<span>${esc(i.delivery)}</span>` : ""}</div>
      ${specs ? `<div class="specs">${specs}</div>` : ""}
      ${badges ? `<div class="badges">${badges}</div>` : ""}
      <div class="row"><div>${price}${diff}${hist}</div>${url ? `<span class="go">${i.guide ? "View price guide ›" : "Go to store ›"}</span>` : ""}</div>
      ${i.pkr && !i.guide ? `<div class="bar-meter" title="Deal score ${i.score}/100"><i style="width:${Math.max(4, i.score)}%"></i></div>` : ""}
    </div>`;
  const best = (i.badges || []).includes("Best deal") ? " best" : "";
  return url
    ? `<a class="card${best}" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${inner}</a>`
    : `<div class="card${best}">${inner}</div>`;
}

function placeholder(name) {
  const d = document.createElement("div");
  d.className = "thumb ph";
  d.textContent = (name || "?").trim().charAt(0).toUpperCase();
  return d;
}

function storesPanel(d) {
  const label = { ok: "Found", none: "Nothing found", need_key: "Key needed", error: "Error",
    blocked: "Blocked on this network", refused: "Store refused", robots: "Not allowed", indexing: "Preparing",
    degraded: "Site changed" };
  return `<details class="stores"${d.items.length ? "" : " open"}>
    <summary>Stores checked (${d.stores.filter((s) => s.status === "ok").length}/${d.stores.length})</summary>
    ${d.stores.map((s) => `<div class="st"><span class="dot ${s.status}" title="${label[s.status]}"></span><b>${esc(s.name)}</b>
      <span class="muted">${label[s.status]}${s.how ? " · " + esc(s.how) : ""}${s.note ? " · " + esc(s.note) : ""}</span></div>`).join("")}
  </details>`;
}

// ------------------------------------------------------------------ smart search helpers
function sizeGb(s) { const n = parseFloat(s); return /TB/i.test(s) ? n * 1024 : n; }
function fmtDay(iso) { return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" }); }

function understoodBar(d) {
  const u = d.understood;
  if (!u) return "";
  const chips = [];
  if (u.q && u.q !== u.raw.toLowerCase()) chips.push(`Searched: <b>${esc(u.q)}</b>`);
  if (u.category) chips.push(`Category: <b>${esc(u.category)}</b>`);
  if (u.store_name) chips.push(`Store: <b>${esc(u.store_name)}</b>`);
  (u.fixes || []).forEach(([a, b]) => chips.push(`Spelling: ${esc(a)} → <b>${esc(b)}</b>`));
  if (u.budget_min && u.budget_max) chips.push(`Budget: <b>${rs(u.budget_min)} – ${rs(u.budget_max)}</b>`);
  else if (u.budget_max) chips.push(`Budget: <b>up to ${rs(u.budget_max)}</b>`);
  else if (u.budget_min) chips.push(`Budget: <b>above ${rs(u.budget_min)}</b>`);
  if (u.pta === true) chips.push("<b>PTA approved</b>");
  if (u.pta === false) chips.push("<b>Non-PTA</b>");
  if (!chips.length) return "";
  const f = d.filtered || {};
  const out = [f.budget ? `${f.budget} outside budget` : "", f.pta ? `${f.pta} with a different PTA status` : ""].filter(Boolean).join(", ");
  return `<div class="understood"><span class="muted small">Understood:</span> ${chips.map((c) => `<span class="uchip">${c}</span>`).join("")}
    ${(u.fixes || []).length ? `<button type="button" class="chip" data-fix="${esc(u.raw)}" hidden></button>` : ""}
    ${out ? `<div class="muted small">${out} (hidden)</div>` : ""}</div>`;
}

function emptyText(d) {
  const u = d.understood || {}, f = d.filtered || {};
  if (!u.q && !u.category) return "Type a product name, e.g. \"Samsung A56\" or \"mobile under 50k\".";
  if (f.budget) return `No product within budget (${f.budget} were outside it). Try a higher budget.`;
  if (f.pta) return `Nothing with that PTA status (${f.pta} products differed).`;
  return "No products found. Try other words, e.g. just the model name.";
}

// ------------------------------------------------------------------ filters
let FILT_OPEN = false;

function priceBands(items) {
  // 3-4 quick ranges from the loaded prices (rounded), e.g. "under 50k", "50k–100k", "100k+"
  const v = items.filter((i) => i.pkr && !i.suspect).map((i) => i.pkr).sort((a, b) => a - b);
  if (v.length < 4) return [];
  const round = (x) => { const m = x >= 1e5 ? 1e4 : x >= 1e4 ? 1e3 : 100; return Math.round(x / m) * m; };
  const cuts = [...new Set([round(v[Math.floor(v.length / 3)]), round(v[Math.floor((2 * v.length) / 3)])])].filter((c) => c > v[0] && c < v[v.length - 1]);
  if (!cuts.length) return [];
  const k = (x) => (x >= 1e5 ? (x / 1e3).toFixed(0) + "k" : x >= 1e3 ? (x / 1e3).toFixed(x % 1e3 ? 1 : 0) + "k" : String(x));
  const bands = [[null, cuts[0], `under ${k(cuts[0])}`]];
  for (let n = 1; n < cuts.length; n++) bands.push([cuts[n - 1], cuts[n], `${k(cuts[n - 1])}–${k(cuts[n])}`]);
  bands.push([cuts[cuts.length - 1], null, `${k(cuts[cuts.length - 1])}+`]);
  return bands;
}

function filterPanel(d, storeNames, storeCount, sizes, hasPta) {
  if (!d.items.length) return "";
  const n = activeFilters();
  const bands = priceBands(d.items);
  const val = (x) => (x != null ? Math.round(x) : "");
  const storeChips = storeNames.length > 1
    ? `<div class="frow"><span class="fl">Stores</span><div class="filters">${[["all", "All"], ...storeNames.map((s) => [s, s])].map(([s, l]) =>
        `<button type="button" class="chip ${s === "all" ? (STORES.size ? "" : "on") : STORES.has(s) ? "on" : ""}" data-st="${esc(s)}">${esc(l)}${s !== "all" ? ` <span class="cnt">${storeCount[s]}</span>` : ""}</button>`).join("")}</div></div>` : "";
  return `<details class="filt"${FILT_OPEN || n ? " open" : ""}>
    <summary>Filters${n ? ` <span class="cnt on">${n}</span>` : ""}${n ? ` <button type="button" class="chip" id="clearF2">Clear</button>` : ""}</summary>
    <div class="frow"><span class="fl">Price (Rs)</span>
      <div class="prange"><input id="pmin" inputmode="numeric" placeholder="Min" value="${val(PMIN)}" aria-label="Minimum price">
      <span>–</span><input id="pmax" inputmode="numeric" placeholder="Max" value="${val(PMAX)}" aria-label="Maximum price"></div>
      ${bands.length ? `<div class="filters">${bands.map(([lo, hi, l]) => `<button type="button" class="chip ${PMIN === lo && PMAX === hi ? "on" : ""}" data-pr="${lo ?? ""}-${hi ?? ""}">${l}</button>`).join("")}</div>` : ""}
    </div>
    ${storeChips}
    ${hasPta ? `<div class="frow"><span class="fl">PTA</span><div class="filters">${[["all", "All"], ["pta", "PTA approved"], ["non", "Non-PTA"]].map(([k, l]) =>
      `<button type="button" class="chip ${PTA === k ? "on" : ""}" data-pta="${k}">${l}</button>`).join("")}</div></div>` : ""}
    ${sizes.length > 1 ? `<div class="frow"><span class="fl">Storage</span><div class="filters">${["all", ...sizes].map((s) =>
      `<button type="button" class="chip ${SIZE === s ? "on" : ""}" data-sz="${esc(s)}">${s === "all" ? "All" : esc(s)}</button>`).join("")}</div></div>` : ""}
  </details>`;
}

// ------------------------------------------------------------------ local AI: smart pick + grouped offers
function pickPanel(d) {
  const p = d.pick;
  if (!p) return "";
  const it = d.items.find((i) => i.url === p.url);
  if (!it || !passes(it)) return "";
  const url = safeUrl(it.url);
  return `<a class="pick" ${url ? `href="${esc(url)}" target="_blank" rel="noopener noreferrer"` : ""}>
    <div class="pick-h"><span class="badge good">Smart pick</span><span class="muted small">chosen by the local AI from price, match, rating and price history</span></div>
    <div class="pick-b"><div><div class="title">${esc(it.title)}</div><div class="meta"><span class="store">${esc(it.store)}</span></div>
      <ul>${p.why.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>
      <div class="pick-p"><div class="price num">${rs(it.pkr)}</div>${url ? `<span class="go">Go to store ›</span>` : ""}</div></div>
  </a>`;
}

function groupedCards(d, items, cheapest) {
  // one card per product (its best visible offer first), other offers listed under it
  const byUrl = Object.fromEntries(d.items.map((i) => [i.url, i]));
  const groupOf = {};
  (d.groups || []).forEach((g, n) => g.urls.forEach((u) => { groupOf[u] = n; }));
  const shown = new Set(), out = [];
  for (const i of items) {
    const n = groupOf[i.url];
    if (n === undefined) { out.push(card(i, cheapest)); continue; }
    if (shown.has(n)) continue;
    shown.add(n);
    const offers = d.groups[n].urls.map((u) => byUrl[u]).filter((x) => x && passes(x))
      .sort((a, b) => (a.pkr ?? 1e18) - (b.pkr ?? 1e18));
    const lead = SORT === "cheap" || SORT === "deal" ? offers[0] : i;
    const rest = offers.filter((x) => x !== lead);
    if (!rest.length) { out.push(card(lead, cheapest)); continue; }
    const prices = offers.map((x) => x.pkr).filter(Boolean);
    out.push(`<div class="gwrap">${card(lead, cheapest)}
      <details class="offers"><summary>+${rest.length} more offer${rest.length > 1 ? "s" : ""}${prices.length > 1 ? ` · ${rs(Math.min(...prices))} – ${rs(Math.max(...prices))}` : ""}</summary>
      ${rest.map((x) => { const u = safeUrl(x.url); return `<a class="offer" ${u ? `href="${esc(u)}" target="_blank" rel="noopener noreferrer"` : ""}>
        <span class="o-t">${esc(x.store)} · ${esc(x.title)}</span><span class="o-p num">${x.pkr ? rs(x.pkr) : "–"}</span></a>`; }).join("")}
      </details></div>`);
  }
  return out.join("");
}
