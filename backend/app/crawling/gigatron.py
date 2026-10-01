import atexit
import json
import logging
import os
import re
import time

import httpx
from bs4 import BeautifulSoup

from app.crawling.browser_pool import run_in_browser, shutdown_browser
from app.crawling.currency import (
    PLAUSIBLE_BANDS,
    bg_dual_price_eur,
    is_plausible,
    resolve_currency,
    sniff_currency,
)
from app.crawling.gift import extract_gift_from_soup

log = logging.getLogger("crawl.gigatron")

# When ENABLE_SPA_CRAWL=1 and Playwright+Chromium are available, a headless
# browser render is used as a fallback whenever the static HTML fetch fails to
# yield a price (e.g. JS-rendered SPA product pages that return an empty shell
# to httpx). Off by default so the MVP static path is unchanged.
ENABLE_SPA_CRAWL = os.getenv("ENABLE_SPA_CRAWL", "0") == "1"

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,hu;q=0.8,fi;q=0.7",
}


# Browser lifecycle is owned by browser_pool: one Chromium per process, run on
# a dedicated thread so the sync Playwright API works even when the caller sits
# inside an asyncio event loop (FastAPI handler / APScheduler job).
_close_browser = shutdown_browser
atexit.register(_close_browser)


def _render_with_browser(url: str, timeout: float = 30) -> str | None:
    """Render a URL with headless Chromium and return the full HTML.

    Returns None if the browser is unavailable or rendering fails. Heavy
    static assets (images/fonts/css/media) are aborted to speed up SPA
    hydration so the price text is in the DOM faster.
    """

    def _abort_heavy(route, request):
        if route.request.resource_type in ("image", "stylesheet", "font", "media"):
            try:
                route.abort()
            except Exception:
                pass
        else:
            try:
                route.continue_()
            except Exception:
                pass

    def job(browser):
        page = browser.new_page()
        try:
            page.route("**/*", _abort_heavy)
            page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
            # Give the SPA time to fetch + paint the price.
            page.wait_for_timeout(5000)
            return page.content()
        except Exception as exc:
            log.warning("browser render failed for %s: %s", url, exc)
            return None
        finally:
            try:
                page.close()
            except Exception:
                pass

    return run_in_browser(job, timeout=timeout + 45)


def fetch_gigatron_product(url: str, timeout: float = 10, retries: int = 3,
                           expected_currency: str | None = None) -> dict:
    """Fetch a product page and extract the unlocked price.

    Phase 1 (fast path): static httpx fetch + parse. Works for server-rendered
    pages. Phase 2 (fallback): if the static HTML yields no price, render the
    page with a headless browser and re-run the same parser. This recovers
    prices from JS-rendered SPA product pages that return an empty shell to
    httpx.

    ``expected_currency`` is the channel's authoritative currency. Pass it
    whenever it is known - page-text sniffing is unreliable and previously
    mislabelled whole markets (Polish shops read as RON, Bulgarian as RSD).

    Returns {"price": float, "currency": str, "in_stock": bool, "meta": dict}.
    The ``meta`` block carries original_price / current_price / method / url so
    downstream price verification can tell a promo price from the regular one.
    Raises RuntimeError if neither phase finds a price.
    """
    html = None
    last_exc = None
    # ---- Phase 1: static fetch ----
    # altex.ro refuses non-browser TLS fingerprints outright (curl/httpx get
    # connection resets) AND counts every refused attempt against the IP's
    # rate window - so the 3 static retries only burn quota before the render.
    # Skip straight to the browser for hosts known to block static fetches.
    _static_blocked = any(
        host in url for host in ("altex.ro",)
    ) if url else False
    if not _static_blocked:
        for attempt in range(retries):
            try:
                resp = httpx.get(url, headers=UA, timeout=timeout, follow_redirects=True)
                if resp.status_code in (429, 503) or resp.status_code >= 500:
                    retry_after = resp.headers.get("retry-after")
                    wait = float(retry_after) if (retry_after and retry_after.isdigit()) else (2 ** attempt)
                    log.warning("rate-limited/5xx on %s (HTTP %s), backing off %ss (attempt %d/%d)",
                                url, resp.status_code, wait, attempt + 1, retries)
                    time.sleep(wait)
                    last_exc = RuntimeError(f"HTTP {resp.status_code} for {url}")
                    continue
                resp.raise_for_status()
                html = resp.text
                break
            except Exception as exc:  # network / HTTP errors
                last_exc = exc
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
    if html:
        try:
            return _wrap_price_meta(
                parse_gigatron_html(html, url, expected_currency), url, "static_http"
            )
        except Exception as exc:
            log.info("static parse failed for %s, trying browser render: %s", url, exc)

    # ---- Phase 2: headless browser render fallback ----
    if ENABLE_SPA_CRAWL:
        rendered = _render_with_browser(url, timeout=max(timeout, 30))
        if rendered:
            try:
                return _wrap_price_meta(
                    parse_gigatron_html(rendered, url, expected_currency),
                    url, "browser_render",
                )
            except Exception as exc:
                log.warning("browser-rendered parse failed for %s: %s", url, exc)

    raise RuntimeError(
        f"fetch failed for {url}: price not found (static+render); last_exc={last_exc}"
    )


def _wrap_price_meta(data: dict, url: str, method: str) -> dict:
    """Attach a ``meta`` block (original vs current price, gift, provenance) so
    promo pricing is never mistaken for the normal price downstream."""
    data.setdefault("meta", {})
    data["meta"].update({
        "original_price": data.get("original_price"),
        "current_price": data["price"],
        "gift": data.get("gift"),
        "product_name": data.get("product_name"),
        "currency": data["currency"],
        "url": url,
        "method": method,
    })
    return data


# Plausibility bands live in app.crawling.currency so every extractor shares
# one definition. Alias kept for callers that imported it from here.
_PLAUSIBLE_BANDS = PLAUSIBLE_BANDS


def parse_gigatron_html(html: str, url: str = "",
                        expected_currency: str | None = None) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    price = None
    original_price = None
    # DNA Finland (kauppa.dna.fi) advertises a "Takuuhinta" guarantee / price-
    # match selling price that is the real amount the customer pays, alongside a
    # higher "norm." (regular / manufacturer) price. The generic extractor below
    # reads the struck-through "norm." regular price from JSON-LD, so for DNA we
    # anchor on the Takuuhinta label instead of the regular price.
    anchor = None
    if "kauppa.dna.fi" in (url or "").lower():
        _cur, _orig = _dna_price(soup)
        if _cur:
            price = _cur
            original_price = _orig
    if price is None:
        price, anchor = _extract_price(soup)
    in_stock = _extract_stock(soup)
    if price is None:
        raise RuntimeError(f"could not parse price from {url or 'page'}")

    # Channel currency wins; the page is only a cross-check. Guessing from page
    # text mislabelled entire markets (see app/crawling/currency.py).
    currency = resolve_currency(expected_currency, _extract_currency(soup), url)
    if currency is None:
        raise RuntimeError(
            f"currency unknown for {url or 'page'}; refusing to store an "
            f"unlabelled price"
        )
    # Bulgaria dual-price correction: several BG shops still print both the lev
    # and euro figures side by side ("1,073.75 лв. / 549.00 €"). The structured
    # price the generic parser reads is the lev number, but the channel currency
    # map labels the row EUR — so it would otherwise land 1.9558x too high. If
    # the parsed figure is the lev side of a fixed-rate lev/euro pair on the
    # page, swap in the euro value. Never guesses when no reliable pair exists.
    if currency == "EUR":
        corrected = bg_dual_price_eur(soup.get_text(" ", strip=True), price)
        if corrected is not None:
            price = corrected
    _assert_plausible(price, currency, url)
    # 划线价：DNA 已在上面给出 original；其它渠道从「实际价所在价格容器」内的
    # 删除线元素取。仅在「原價 > 实际价 且差距合理(<3x)」时采纳，避免把推荐位/
    # 捆绑包的原价误当本商品划线价（technomarket 同页会印其它商品的促销块）。
    gen_orig = _extract_original_price(soup, anchor, price)
    if original_price is None:
        original_price = gen_orig
    if original_price is not None and (
        original_price <= price or original_price > price * 5
    ):
        original_price = None
    gift = _extract_gift(soup)
    product_name = _extract_product_name(soup)
    return {
        "price": price,
        "currency": currency,
        "in_stock": in_stock,
        "original_price": original_price,
        "gift": gift,
        "product_name": product_name,
    }


def _assert_plausible(price: float, currency: str, url: str) -> None:
    if is_plausible(price, currency):
        return
    lo, hi = PLAUSIBLE_BANDS[currency]
    raise RuntimeError(
        f"price {price} {currency} outside plausible band [{lo},{hi}] for {url or 'page'}"
    )


def _dna_price(soup: BeautifulSoup) -> tuple[float | None, float | None]:
    """Return (current, original) for a DNA Finland PDP, or (None, None).

    DNA (kauppa.dna.fi) shows a "Takuuhinta" guarantee / price-match selling
    price that is the real amount the customer pays, next to a higher "norm."
    (regular / manufacturer) price. The generic JSON-LD extractor keeps the
    higher "norm." figure, so we anchor strictly on the Takuuhinta label for the
    current price and on "norm." for the original. Decimal comma ("299,00") is
    handled by :func:`_to_float`. Returns (None, None) when the expected labels
    are absent so the caller falls back to the generic parse (covers page
    structure changes without silently storing a wrong price).
    """
    text = soup.get_text(" ")
    text = re.sub(r"\s+", " ", text)
    cur = None
    m = re.search(r"Takuuhinta\s+nyt[^0-9]{0,20}?([\d\s.,]{2,9}?)\s*€", text)
    if not m:
        m = re.search(r"DNA\s+Takuuhinta[^0-9]{0,20}?([\d\s.,]{2,9}?)\s*€", text)
    if m:
        cur = _to_float(m.group(1))
    orig = None
    mo = re.search(r"norm\.\s*([\d\s.,]{2,9}?)\s*€", text)
    if mo:
        orig = _to_float(mo.group(1))
    if cur and 1 < cur < 5000:
        return cur, orig
    return None, None


# ---------------------------------------------------------------------------
# 划线价 / 赠品 / 机型名 提取（促销场景正确性）
# ---------------------------------------------------------------------------
# 跨语言「删除线 / 原价」类选择器（class 或内联 style 命中即视为划线价元素）。
_STRIKE_CLASS = re.compile(
    r"\b(old|was|regular|strike|cross|compare.?at|pret-vechi|stara-cena|veca-cena|"
    r"rrp|list|previous|before|line-through|preco-antigo|preco-tachado|del)\b",
    re.I,
)


def _is_strike(tag) -> bool:
    """True if the element (or its parent) is a struck-through / old-price node."""
    if tag is None or not hasattr(tag, "get"):
        return False
    cls = " ".join(tag.get("class", []) or []).lower()
    if _STRIKE_CLASS.search(cls):
        return True
    style = (tag.get("style") or "").lower().replace(" ", "")
    if "line-through" in style or "text-decoration:line-through" in style:
        return True
    parent = tag.parent
    if parent is not None and hasattr(parent, "get"):
        pcls = " ".join(parent.get("class", []) or []).lower()
        pstyle = (parent.get("style") or "").lower().replace(" ", "")
        if _STRIKE_CLASS.search(pcls) or "line-through" in pstyle:
            return True
    return False


def _extract_price(soup: BeautifulSoup):
    """Return (price, source_element) so callers can scope the strikethrough
    (original) price to the same product price block. Skips struck elements so
    the actual selling price is returned, never the crossed-out one."""
    # 1. Structured meta tags (most reliable when present)
    for selector in [
        'meta[property="product:price:amount"]',
        'meta[property="og:price:amount"]',
        'meta[itemprop="price"]',
    ]:
        tag = soup.select_one(selector)
        if tag and tag.get("content") and not _is_strike(tag):
            val = _to_float(tag.get("content"))
            if val:
                return val, tag
    # 2. Schema.org price element
    tag = soup.select_one("[itemprop='price']")
    if tag and not _is_strike(tag):
        val = _to_float(tag.get_text())
        if val:
            return val, tag
    # 2b. Main product price block. technomarket.bg renders the canonical price
    #     inside a ``.price-block`` element carrying BOTH the lev and the euro
    #     figure (e.g. "1,999 лв. / 1,022.07 €"). The first "€" value is the
    #     current selling price. We prefer this over JSON-LD, whose
    #     offers.price is frequently the mislabelled local-currency number
    #     (e.g. "4496.45 BGN" for a real 1,022.07 EUR product) and would
    #     otherwise poison the row. The first .price-block in document order is
    #     the main product (related-product carousels sit further down the page,
    #     and their small header widgets like "54€" are NOT .price-blocks).
    for tag in soup.select(".price-block"):
        t = tag.get_text()
        m = re.search(r"([\d\.,\s]{2,})\s*€", t)
        if m:
            val = _to_float(m.group(1))
            if val and val < 10_000_000:
                return val, tag
        # No € (unlikely on BG): take the first number; bg_dual_price_eur in
        # parse_gigatron_html swaps a lev pair for its euro value.
        val = _to_float(t)
        if val and val < 10_000_000:
            return val, tag
    # 3. JSON-LD structured data (walk every block recursively)
    for ld in soup.find_all("script", type="application/ld+json"):
        val = _price_from_jsonld(ld.string or ld.get_text())
        if val:
            return val, ld
    # 4. Any element whose class hints at price — 跳过删除线（取实际到手价）
    for tag in soup.find_all(class_=re.compile(r"price", re.I)):
        if _is_strike(tag):
            continue
        val = _to_float(tag.get_text())
        if val and val < 10_000_000:
            return val, tag
    # 5. Currency-anchored fallback (covers RSD/EUR/RON/HUF/BGN across EU retailers)
    for m in re.finditer(
        r"([\d\.,\s]{3,})\s*(RSD|дин|EUR|€|RON|lei|HUF|Ft|BGN|лв|HRK)",
        soup.get_text(),
        re.I,
    ):
        val = _to_float(m.group(1))
        if val and val < 10_000_000:
            return val, None
    return None, None


_PRICE_CONTAINER = re.compile(
    r"price-block|price-wrapper|product-price|price-box|price-container|"
    r"offer-price|price-info|product-price",
    re.I,
)


def _is_price_container(node) -> bool:
    if node is None or not hasattr(node, "get"):
        return False
    return bool(_PRICE_CONTAINER.search(" ".join(node.get("class", []) or [])))


# Old / comparison price labels (the "was" / strikethrough price). technomarket
# prints it as "ПЦ: 1,758.29 лв. / 899 €" (ПЦ = стара цена / old price); other
# shops use "old-price", "was", "RRP", ... — not always a <strike> element.
# We match only the *label*; the euro figure is taken separately (see
# _extract_original_price) so we never capture the lev side of a lev/€ pair.
_OLD_PRICE = re.compile(
    r"(?:ПЦ|стара\s+цена|old[-\s]?price|was|rrp|reduced\s+from|compare\s+at|"
    r"prev\.?\s*price|антамен\s+цена)\b",
    re.I,
)


def _extract_original_price(soup: BeautifulSoup, anchor, current: float) -> float | None:
    """Find the product's own strikethrough original price.

    Scoped to the price container that holds the actual ``anchor`` element so we
    never pick up a *recommendation / bundle* block's old price elsewhere on the
    page (technomarket prints other products' promo blocks with their own
    ПЦ/old-price). Accepts a value from either a struck element OR an explicit
    "old price" label (ПЦ / old-price / was / RRP ...), as long as it is
    strictly greater than ``current`` and within 3x of it — a genuine original
    is always > sale price and rarely >3x.
    """
    if anchor is None or current is None:
        return None
    node = anchor
    for _ in range(6):
        if node is None:
            break
        if _is_price_container(node):
            # (a) struck elements
            for tag in node.find_all(True):
                if tag is anchor:
                    continue
                if _is_strike(tag):
                    val = _euro_or_float(tag.get_text())
                    if val and val > current and val < current * 3:
                        return val
            # (b) explicit old-price label (ПЦ / old-price / was / RRP ...).
            # Take the euro figure that follows the label so a "lev / €" pair
            # (technomarket prints both) yields the euro old price, not the lev.
            block_text = node.get_text(" ")
            for m in _OLD_PRICE.finditer(block_text):
                after = block_text[m.end(): m.end() + 40]
                val = _euro_or_float(after)
                if val and val > current and val < current * 3:
                    return val
        node = node.parent
    return None


def _jsonld_blobs(ld) -> list:
    """Parse a JSON-LD <script> into a list of dict blobs (best-effort)."""
    text = ld.string or ld.get_text() or ""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    try:
        return [json.loads(text)]
    except Exception:
        out = []
        for m in re.finditer(r"\{.*\}", text, re.S):
            try:
                out.append(json.loads(m.group()))
            except Exception:
                continue
        return out


# 赠品探测统一走 app/crawling/gift.py（全渠道共用一套词表与护栏）。
# 之前这里的版本常年产出两类垃圾：波兰站 banner 图的 alt 描述文案、以及
# "Dwie raty gratis i 30 rat 0% *RRSO 0%" 这类免息分期话术。
def _extract_gift(soup: BeautifulSoup) -> str | None:
    """Detect a bundled gift (赠品) and return a concise label, or None.

    Delegates to :mod:`app.crawling.gift` so every channel shares one set of
    rules: image badge (most reliable — the file name / alt usually is the gift
    model) first, then a gift announcement next to a real product noun. Both
    paths must clear the same guardrails (delivery / instalment / warranty
    wording rejected, label must stay short and start with a real word).
    Returns None when the page simply has no gift — an honest parse failure
    beats a plausible-looking value.
    """
    try:
        return extract_gift_from_soup(soup)
    except Exception as exc:  # noqa: BLE001 - 赠品是增强字段，绝不能拖垮抓取主流程
        log.debug("gift scan failed: %s", exc)
        return None


# JSON-LD @type values that carry the SHOP name, not a product name. Treating
# them as the self-reported product name is what caused Gigatron (and similar
# shops) to be false-flagged product_mismatch on every row.
_ORG_JSONLD_TYPES = {
    "organization", "website", "webpage", "breadcrumblist",
    "itemlist", "listitem", "searchresults", "searchresults",
}


def _extract_product_name(soup: BeautifulSoup) -> str | None:
    """Best-effort page self-reported model name (for product_mismatch audit).

    Many shops embed an Organization/WebSite JSON-LD blob whose ``name`` is the
    shop itself (Gigatron's first blob is ``name: "Gigatron"``). We must prefer
    the *Product*-typed structured data, otherwise the audit compares the shop
    name against the SKU's model and false-flags every row as product_mismatch.
    """
    product_name: str | None = None
    any_non_org_name: str | None = None
    for ld in soup.find_all("script", type="application/ld+json"):
        for blob in _jsonld_blobs(ld):
            if not isinstance(blob, dict):
                continue
            name = blob.get("name")
            if not (isinstance(name, str) and name.strip()):
                continue
            name = name.strip()
            t = blob.get("@type")
            types = [t] if isinstance(t, str) else (t if isinstance(t, list) else [])
            lowered = [str(x).lower() for x in types]
            is_product = "product" in lowered
            is_org = any(x in _ORG_JSONLD_TYPES for x in lowered)
            if is_product and product_name is None:
                product_name = name
            if not is_org and any_non_org_name is None:
                any_non_org_name = name
    if product_name:
        return product_name
    if any_non_org_name:
        return any_non_org_name
    t = soup.find("title")
    if t and t.get_text(strip=True):
        return t.get_text(strip=True)
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(strip=True)
    return None


def _price_from_jsonld(text):
    """Recursively walk JSON-LD for any price-like field."""
    if not text:
        return None
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    candidates = []
    try:
        blobs = [json.loads(text)]
    except Exception:
        blobs = []
        for m in re.finditer(r"\{.*\}", text, re.S):
            try:
                blobs.append(json.loads(m.group()))
            except Exception:
                continue
    if not blobs:
        return None

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(k, str) and k.lower() in (
                    "price", "lowprice", "highprice", "priceamount", "pricecurrency"
                ):
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        candidates.append(float(v))
                    elif isinstance(v, str):
                        f = _to_float(v)
                        if f:
                            candidates.append(f)
                else:
                    walk(v)
        elif isinstance(o, list):
            for it in o:
                walk(it)

    for blob in blobs:
        walk(blob)
    # Prefer a plausible consumer-price magnitude; avoid huge/tiny noise.
    for f in candidates:
        if 1 < f < 10_000_000:
            return f
    return None


def _euro_or_float(text) -> float | None:
    """Extract a price value from text, preferring an explicit "€" figure.

    Some shops print a local-currency (lev/ron) figure alongside the euro one
    (e.g. "1,758.29 лв. / 899 €"); when a "€" number is present we take it so
    the euro-side value (the channel's authoritative amount) is used rather
    than the raw first number which would be the lev. Falls back to the first
    number when no euro symbol is present.
    """
    s = text if isinstance(text, str) else (text.get_text() if hasattr(text, "get_text") else str(text))
    em = re.search(r"([\d\.,]+)\s*€", s)
    if em:
        return _to_float(em.group(1))
    return _to_float(s)


def _extract_currency(soup: BeautifulSoup) -> str | None:
    """Sniff the currency from the page. None when nothing conclusive.

    Structured data is checked first because it is explicit; free-text symbol
    matching is the weaker signal and is word-boundary anchored so "lei" no
    longer matches inside unrelated words. Never defaults to a guess - the
    caller supplies the channel's real currency.
    """
    for ld in soup.find_all("script", type="application/ld+json"):
        m = re.search(r'"priceCurrency"\s*:\s*"([A-Z]{3})"',
                      ld.string or ld.get_text() or "")
        if m:
            return m.group(1)
    for selector in ('meta[property="product:price:currency"]',
                     'meta[itemprop="priceCurrency"]'):
        tag = soup.select_one(selector)
        if tag and tag.get("content"):
            return tag["content"].strip().upper()
    return sniff_currency(soup.get_text())


def _extract_stock(soup: BeautifulSoup) -> bool:
    text = soup.get_text().lower()
    if re.search(r"nema na stanju|rasprodato|out of stock|sold out|nenije dostupno", text):
        return False
    return True


def _to_float(value) -> float | None:
    if value is None:
        return None
    s = str(value).strip().replace("\xa0", "").replace(" ", "")
    if not s or s in (".", ","):
        return None
    # Mixed text ("3.299 lei", "7 016,- bez DPH") -> isolate the numeric token
    # FIRST so the separator rules below apply to DOM text as well. (The old
    # code tokenised just before float(), so "3.299 lei" parsed as 3.299
    # instead of 3 299.)
    if not re.fullmatch(r"[\d.,]+", s):
        m = re.search(r"\d[\d\.,]*\d|\d", s)
        if not m:
            return None
        s = m.group()
    if "," in s and "." in s:
        # Both separators present: the last one is the decimal separator.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        # Comma only: thousands group if pattern is N,NNN else decimal comma.
        if re.fullmatch(r"\d{1,3}(,\d{3})+", s):
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    elif "." in s:
        # Dot only: treat N.NNN groups as thousands separators (e.g. "47.764"->47764).
        if re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
            s = s.replace(".", "")
        # otherwise keep as a genuine decimal (e.g. "0.41")
    if not s or s in (".", ","):
        return None
    try:
        return float(s)
    except ValueError:
        return None
