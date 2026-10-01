"""Shared helpers for market channels that sit behind bot walls (Alza /
Cloudflare, Datart / F5 Shape).

The only reliable way to read these pages is a real browser. Plain httpx is
blocked, and a *plain* headless Chromium is fingerprinted ("Just a moment...").
The fix (verified 2026-08-03) is a headless Chromium launched with
``--disable-blink-features=AutomationControlled`` (see browser_pool) plus, per
context here, a realistic Mac UA and a ``navigator.webdriver`` patch. That
combination passes both vendors' challenges while staying fully automatable
(no display / xvfb needed).
"""
from __future__ import annotations

import json
import logging
import re
from urllib.parse import quote_plus, urljoin

from app.crawling.browser_pool import run_in_browser

log = logging.getLogger("crawl.market")

# A genuine desktop UA. Bot walls key off the default Playwright UA.
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
# Hide the automation flag at the JS level too (defence in depth).
WEBDRIVER_PATCH = (
    "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
)

# Generic browser headers every market PDP needs. Without a real Accept /
# Accept-Language / Sec-CH-UA set, Akamai (euro.com.pl) serves its "Blokada"
# block page instead of the product - the page is gated on header shape, not
# just the automation flag. These are harmless for the sites that already pass
# (Alza/Cloudflare, Gigantti/SPA) and necessary for Euro/Akamai.
GEN_HEADERS = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Encoding": "gzip, deflate, br",
    "Upgrade-Insecure-Requests": "1",
    "Sec-CH-UA": (
        '"Chromium";v="126", "Not:A-Brand";v="24", "Google Chrome";v="126"'
    ),
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"macOS"',
}


def _locale_for(url: str) -> str:
    """Per-host locale + Accept-Language.

    euro.com.pl is Polish (pl-PL); Gigantti is Finnish (fi-FI); Altex is
    Romanian (ro-RO); the Czech market sites (Alza, Datart) stay cs-CZ. Sending
    the wrong locale to a site is itself a bot tell that Akamai/F5 pounces on.
    """
    u = url.lower()
    if "euro.com.pl" in u:
        return "pl-PL"
    if "gigantti" in u:
        return "fi-FI"
    if "altex.ro" in u:
        return "ro-RO"
    return "cs-CZ"


# Unambiguous bot-wall challenge markers. NOTE: Euro's *valid* 1.5MB product
# page embeds "captcha-label" strings in its inline security JS, so we must
# NOT key off a bare "captcha" substring - that would false-positive on every
# successful Euro render. Only flag real challenge pages.
_BOTWALL_MARKERS = (
    "enable javascript to view the page content",  # F5 Shape / TSPD
    "just a moment",                                # Cloudflare
)


class BotWallBlocked(RuntimeError):
    """Raised when a market PDP returns a bot-wall challenge (Akamai / F5
    Shape / Cloudflare) instead of the product. Distinct from a plain parse
    failure so the crawler can back off (cool the IP's risk window) rather than
    hammer the wall and get the egress banned harder."""


def _is_block_page(html: str) -> bool:
    """True when ``html`` is a bot-wall challenge rather than a real PDP."""
    low = html.lower()
    for marker in _BOTWALL_MARKERS:
        if marker in low:
            return True
    # Euro's "Blokada" block page carries the word in its <title>; a valid
    # Euro page never does.
    title_i = low.find("<title>")
    if title_i != -1:
        title = low[title_i:title_i + 200]
        if "blokada" in title:
            return True
    return False


def _state_path_for(url: str) -> str:
    """Per-host storage-state file path (auto-managed session cookies).

    Normalised on the bare host (www. stripped) so www.datart.cz and datart.cz
    share one state file. The directory lives under the backend root and is a
    runtime artifact (not committed).
    """
    import os
    from urllib.parse import urlparse

    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    out_dir = os.path.join(root, ".crawl_state")
    os.makedirs(out_dir, exist_ok=True)
    return os.path.join(out_dir, f"{host}.json")


def render(url: str, timeout: float = 35) -> str | None:
    """Render ``url`` with a stealth headless Chromium; return HTML or None.

    Returns None when the browser is unavailable OR the page is a bot-wall
    challenge (Akamai / F5 Shape / Cloudflare) - callers then skip the SKU
    instead of mis-parsing a challenge page as "no price".

    Session cookies are auto-persisted on a successful render and reloaded on
    the next render for the same host. Bot-wall vendors (F5 Shape on Datart)
    set a TSPD/session cookie once a request slips through; reusing it lets the
    rest of that channel's SKUs (and future runs) pass instead of being
    challenged SKU-by-SKU. This turns an IP-risk window from "every SKU fails"
    into "first SKU that clears the window unlocks the rest".
    """
    # Optional per-host storage state (cookies). Datart sits behind F5 Shape
    # which hard-captchas this IP after volume; a warmed TSPD cookie (exported
    # from a headed session once the block relaxes, or auto-saved on a
    # successful render below) lets the headless crawler pass. Drop the JSON at
    # DATART_STORAGE_STATE (or backend/.datart_state.json) and it is picked up
    # automatically - no code change needed. Auto-managed per-host state is the
    # fallback.
    import os

    storage_state = None
    if "datart.cz" in url:
        for cand in (
            os.getenv("DATART_STORAGE_STATE"),
            os.path.join(os.path.dirname(__file__), "..", ".datart_state.json"),
        ):
            if cand and os.path.exists(cand):
                storage_state = cand
                break
    if storage_state is None:
        sp = _state_path_for(url)
        if os.path.exists(sp):
            storage_state = sp

    locale = _locale_for(url)

    def job(browser):
        ctx_headers = {**GEN_HEADERS, "Accept-Language": locale}
        ctx_kwargs = {
            "user_agent": UA,
            "locale": locale.split(",")[0],
            "extra_http_headers": ctx_headers,
        }
        if storage_state:
            ctx_kwargs["storage_state"] = storage_state
        ctx = browser.new_context(**ctx_kwargs)
        try:
            ctx.add_init_script(WEBDRIVER_PATCH)
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
            # Let the SPA hydrate the price + offers.
            page.wait_for_timeout(4500)
            html = page.content()
            # F5 Shape (Datart) serves an *async* challenge: it sets the TSPD
            # cookie and client-side-redirects to the real page a few seconds
            # after load - but only for a browser deemed "real" once the egress
            # IP's risk window cools. If we bail the instant we see the
            # challenge, the self-heal cookie never gets a chance to land. Give
            # it a second settle window and re-read; if the real page is now
            # there, proceed (and persist the cookie below).
            if "datart.cz" in url and _is_block_page(html):
                page.wait_for_timeout(12000)
                html = page.content()
            # Capture the full storage state (cookies + origins) so a reused
            # session survives the next render.
            return html, ctx.storage_state()
        except Exception as exc:  # noqa: BLE001
            log.warning("render failed for %s: %s", url, exc)
            return None
        finally:
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass

    res = run_in_browser(job, timeout=timeout + 45)
    if res is None:
        return None
    html, state = res
    if html and _is_block_page(html):
        log.warning(
            "bot-wall challenge detected for %s (Akamai/F5/Cloudflare) - "
            "skipping (needs clean egress IP or warmed cookie)",
            url,
        )
        raise BotWallBlocked(f"bot wall challenge on {url}")
    # Persist the session cookies on a clean render so the next request reuses
    # them (Datart F5 Shape self-heal, plus faster/stable repeats elsewhere).
    if html and state:
        try:
            with open(_state_path_for(url), "w", encoding="utf-8") as f:
                json.dump(state, f)
        except Exception as exc:  # noqa: BLE001
            log.debug("could not persist storage state for %s: %s", url, exc)
    return html


# --------------------------------------------------------------------------
# JSON-LD / DOM price extraction
# --------------------------------------------------------------------------
_PRICE_KEYS = ("price", "lowprice", "highprice", "priceamount")
_CURRENCY_KEYS = ("pricecurrency", "priceCurrency")

# CSS classes whose price is NOT the product's own price. A PDP shows bundled
# accessory prices ("accessoryGroupPrice: 1 019,-"), the ex-VAT figure
# ("js-secondary-price: bez DPH 7 016,-") and financing instalments - any of
# which the DOM fallback would happily mistake for the phone's price.
_DECOY_PRICE_RE = re.compile(
    r"accessor|secondary|instalment|splatk|mesicn|monthly|saving|usetri|"
    r"shipping|doprava|bonus|voucher|kupon|related|similar|recommend",
    re.I,
)


def _walk_offers(blob):
    """Yield every Offer-like dict found inside a JSON-LD blob."""
    if isinstance(blob, dict):
        otype = str(blob.get("@type", "")).lower()
        if "offer" in otype or "product" in otype:
            offers = blob.get("offers")
            if isinstance(offers, list):
                for o in offers:
                    if isinstance(o, dict):
                        yield o
            elif isinstance(offers, dict):
                yield offers
        for v in blob.values():
            yield from _walk_offers(v)
    elif isinstance(blob, list):
        for it in blob:
            yield from _walk_offers(it)


def _to_float(value):
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    s = str(value).strip().replace("\xa0", "").replace(" ", "")
    if not s:
        return None
    # Mixed text ("3.299 lei", "7 016,- bez DPH") -> isolate the numeric token
    # FIRST so the separator rules below apply to DOM text as well, not only
    # to clean numeric strings. (The old code tokenised just before float(),
    # so "3.299 lei" parsed as 3.299 instead of 3 299.)
    if not re.fullmatch(r"[\d.,]+", s):
        m = re.search(r"\d[\d.,]*\d|\d", s)
        if not m:
            return None
        s = m.group()
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".") if not re.fullmatch(r"\d{1,3}(,\d{3})+", s) else s.replace(",", "")
    elif not s.startswith("0.") and re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        # Dot-only grouping ("3.299", "12.345.678"): RO/FI/DE display format
        # where the dot is the thousands separator. Money in this domain never
        # carries three decimals; "0.999"-style decimals are kept via the guard.
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def _offer_price(offer: dict) -> tuple[float | None, str | None]:
    """Read a price and optional currency from an Offer node.

    Altex-style offers keep the machine price only under
    ``priceSpecification.price`` (schema.org UnitPriceSpecification) with the
    top-level ``price`` key absent; read both, top-level first.
    """
    cur = None
    for ck in _CURRENCY_KEYS:
        if offer.get(ck):
            cur = str(offer[ck]).upper()
            break
    p = _to_float(offer.get("price"))
    if p:
        return p, cur
    spec = offer.get("priceSpecification")
    for doc in (spec if isinstance(spec, list) else [spec]):
        if isinstance(doc, dict):
            sp = _to_float(doc.get("price"))
            if sp:
                if not cur:
                    for ck in _CURRENCY_KEYS:
                        if doc.get(ck):
                            cur = str(doc[ck]).upper()
                            break
                return sp, cur
    return None, cur


def parse_price_page(html: str, url: str = "",
                     expected_currency: str | None = None) -> dict:
    """Extract current + original price, currency, stock, sku from a PDP.

    Returns {price, original_price, currency, in_stock, sku, name}. Raises
    RuntimeError if no current price can be found.

    ``expected_currency`` is the channel's authoritative currency. When the
    page's JSON-LD omits a currency we fall back to it instead of a hardcoded
    CZK — market channels span CZ/PL/FI/etc., so guessing CZK silently
    mislabels non-Czech prices (see app/crawling/currency.py).
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")

    blobs = []
    for ld in soup.find_all("script", type="application/ld+json"):
        txt = ld.string or ld.get_text()
        if not txt:
            continue
        txt = re.sub(r"<!--.*?-->", "", txt, flags=re.S)
        try:
            blobs.append(json.loads(txt))
        except Exception:
            for m in re.finditer(r"\{.*\}", txt, re.S):
                try:
                    blobs.append(json.loads(m.group()))
                except Exception:
                    continue

    price = None
    original_price = None
    currency = None
    in_stock = True
    sku = None
    name = None
    for blob in blobs:
        for offer in _walk_offers(blob):
            p, cur = _offer_price(offer)
            if p and price is None:
                price = p
                currency = cur or currency
            if not sku and offer.get("sku"):
                sku = str(offer.get("sku"))
            avail = str(offer.get("availability", "")).lower()
            if "outofstock" in avail or "outsidestore" in avail:
                in_stock = False
        # Product-level fields
        if isinstance(blob, dict):
            if blob.get("sku") and not sku:
                sku = str(blob.get("sku"))
            # Some schemas nest the old price under offers as a second Offer.
            offs = blob.get("offers")
            if isinstance(offs, list):
                prices = [_offer_price(o)[0] for o in offs if isinstance(o, dict)]
                prices = [p for p in prices if p]
                if len(prices) > 1:
                    original_price = max(prices)
                    price = min(prices)

    # The product NAME must come from a Product-typed node. Taking the first
    # "name" in any blob grabs the Organization / WebSite node instead (Alza's
    # first JSON-LD block is literally {"name": "Alza.cz"}), which would break
    # the model-verification gate downstream.
    name = _find_product_name(blobs) or _dom_product_name(soup)

    if price is None:
        # Fallback: any number near a price-looking class - but a PDP is full
        # of *other* prices (bundled accessories, the ex-VAT figure, monthly
        # instalments). Picking one of those would be worse than failing.
        for tag in soup.find_all(class_=re.compile(r"price|cena", re.I)):
            cls = " ".join(tag.get("class") or []).lower()
            if _DECOY_PRICE_RE.search(cls):
                continue
            p = _to_float(tag.get_text())
            if p and 1 < p < 10_000_000:
                price = p
                break
    if price is None:
        raise RuntimeError(f"no price found on {url or 'page'}")

    # DOM-level original/strikethrough price (not always in JSON-LD).
    if original_price is None:
        original_price = _extract_strikethrough(soup, price)

    if currency is None:
        # Prefer the channel's authoritative currency over a hardcoded CZK.
        # A mismatch is still logged by the caller (fetch_gigatron_product),
        # so a genuinely wrong mapping surfaces instead of corrupting data.
        currency = expected_currency or "CZK"

    return {
        "price": price,
        "original_price": original_price,
        "currency": currency,
        "in_stock": in_stock,
        "sku": sku,
        "name": name,
        # 赠品是全渠道共用的增强字段，探测规则统一在 app/crawling/gift.py。
        # 拿不到就是 None（页面本来没送），绝不猜。
        "gift": _extract_gift(soup),
    }


def _find_product_name(blobs) -> str | None:
    """Return the ``name`` of the first Product-typed JSON-LD node."""
    def walk(blob):
        if isinstance(blob, dict):
            otype = str(blob.get("@type", "")).lower()
            if "product" in otype and blob.get("name"):
                return str(blob["name"])
            for v in blob.values():
                found = walk(v)
                if found:
                    return found
        elif isinstance(blob, list):
            for it in blob:
                found = walk(it)
                if found:
                    return found
        return None

    for b in blobs:
        found = walk(b)
        if found:
            return found
    return None


def _dom_product_name(soup) -> str | None:
    """Fallback product name: og:title, then the page H1."""
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        return og["content"].strip()
    h1 = soup.find("h1")
    if h1:
        txt = h1.get_text(" ", strip=True)
        if txt:
            return txt
    return None


def _extract_gift(soup) -> str | None:
    """Detect a bundled gift (赠品). Delegates to the shared rules in
    ``app.crawling.gift`` so market channels and operator PDPs behave identically.

    赠品只是增强字段，任何异常都不能拖垮价格抓取主流程 —— 所以这里吞掉异常
    并返回 None（= 本页没有识别到赠品），而不是抛出。
    """
    try:
        from app.crawling.gift import extract_gift_from_soup

        return extract_gift_from_soup(soup)
    except Exception as exc:  # noqa: BLE001
        log.debug("gift scan failed: %s", exc)
        return None


def _extract_strikethrough(soup, current_price: float) -> float | None:
    """Find a struck-through / 'was' price that is higher than the current one."""
    candidates = []
    for tag in soup.find_all(["del", "s"]):
        p = _to_float(tag.get_text())
        if p:
            candidates.append(p)
    # Class hints commonly used for the old price. "p.vodn" tolerates the Czech
    # "Původní cena" with or without its diacritic.
    old_re = re.compile(r"old|before|was|strike|cross|original|p.vodn", re.I)
    for tag in soup.find_all(class_=old_re):
        cls = " ".join(tag.get("class") or []).lower()
        if _DECOY_PRICE_RE.search(cls):
            continue
        p = _to_float(tag.get_text())
        if p:
            candidates.append(p)
    for c in candidates:
        if c and c > current_price * 1.02:  # must be plausibly higher
            return c
    return None


# --------------------------------------------------------------------------
# Accessory rejection
# --------------------------------------------------------------------------
# Search for "DemoBrand 600 Smart" on Alza and the top hit is a tempered-glass
# protector *for* that phone. Its price (299 CZK) would poison the comparison,
# so accessories are rejected structurally, not just by price band.
_ACCESSORY_TOKENS = {
    # screen protection
    "sklo", "skla", "skel", "folie", "folia", "tempered", "protector",
    "protectors", "screen", "chranic", "chranice", "ochranne", "ochranna",
    "ochranny", "displeje",
    # cases
    "pouzdro", "pouzdra", "kryt", "kryty", "case", "flip", "book", "penezenka",
    # power
    "nabijecka", "nabijecky", "nabijeci", "nabijeni", "charger", "adapter",
    "adaptery", "kabel", "kabely", "cable", "powerbank", "autonabijecka",
    "baterie", "battery",
    # mounts / holders
    "drzak", "drzaky", "holder", "stojan", "stand", "stativ", "tripod",
    "selfie", "tyc",
    # wearables / audio bundles
    "pasek", "pasky", "strap", "sluchatka", "headphones", "earbuds", "buds",
    # services
    "pojisteni", "zaruka", "sluzba", "sluzby", "instalace", "montaz",
    "predplatne",
}
# Czech "pro" = "for": "<accessory>-pro-demobrand-600" is an accessory, whereas a
# phone named "... Pro" reads "demobrand-magic8-pro-12gb-...".
_ACCESSORY_PHRASES = (
    "-pro-demobrand", "-pro-samsung", "-pro-xiaomi", "-pro-apple", "-pro-google",
    "-pro-motorola", "-pro-oppo", "-pro-realme", "-pro-nothing", "-pro-vivo",
    "-pro-iphone", "-pro-mobil",
)
# A phone PDP almost always carries its memory spec ("-8gb-256gb-").
_SPEC_RE = re.compile(r"\d{1,2}\s?gb[-\s]\d{2,4}\s?gb", re.I)

# Variant qualifiers. If a slug carries one that the query does NOT, it is a
# *different* model: searching "DemoBrand 600" must not land on "DemoBrand 600 Pro",
# and "Galaxy S26" must not land on "Galaxy S26 Ultra". Getting this wrong is
# the single most dangerous failure mode here - a flagship price silently
# attributed to the mid-tier model would skew every pricing decision.
_VARIANT_TOKENS = {
    "pro", "ultra", "lite", "plus", "max", "mini", "fe", "edge", "neo",
    "turbo", "smart", "air", "fold", "flip", "note",
}
_STORAGE_RE = re.compile(r"(\d{2,4})\s?gb", re.I)
_TB_RE = re.compile(r"(\d)\s?tb", re.I)


def _storage_gb(blob: str) -> int:
    """Largest capacity mentioned in the slug (proxy for the storage tier)."""
    tb = _TB_RE.search(blob)
    if tb:
        return int(tb.group(1)) * 1024
    nums = [int(n) for n in _STORAGE_RE.findall(blob)]
    return max(nums) if nums else 0


def is_accessory(href: str, text: str = "") -> bool:
    """True when the link points at an accessory / service, not a handset."""
    blob = f"{href} {text}".lower()
    if any(p in blob for p in _ACCESSORY_PHRASES):
        return True
    toks = set(re.split(r"[^a-z0-9]+", blob))
    return bool(toks & _ACCESSORY_TOKENS)


# --------------------------------------------------------------------------
# Generic search-result discovery
# --------------------------------------------------------------------------
def pick_best_result(links: list[tuple[str, str]], query: str) -> str | None:
    """Given [(href, text)] product candidates, return the best-matching URL.

    Scoring, in order of weight:
      + one point per query token found
      + 3 when *every* query token is present
      + 2 when the slug carries a memory spec (a real handset PDP)
      - 6 per variant qualifier the slug has but the query does not
        ("DemoBrand 600" must never resolve to "DemoBrand 600 Pro")
    Ties break toward the *lowest* storage tier, i.e. the entry configuration,
    which is the config price comparisons are normally anchored on.
    """
    q = query.lower().replace("  ", " ")
    tokens = [t for t in re.split(r"[\s\-]+", q) if len(t) > 1]
    qtoks = set(re.split(r"[^a-z0-9]+", q))

    def score_all(whole_token: bool):
        out = []
        for href, text in links:
            blob = (href + " " + text).lower()
            # Only the slug decides variants; anchor text often carries
            # "recommended" siblings from the same card.
            slug = href.rsplit("/", 1)[-1].lower()
            slug_toks = set(re.split(r"[^a-z0-9]+", slug))
            if whole_token:
                blob_toks = slug_toks | set(re.split(r"[^a-z0-9]+", text.lower()))
                score = sum(1 for t in tokens if t in blob_toks)
            else:
                score = sum(1 for t in tokens if t in blob)
            if score == 0:
                continue
            # Every query token present -> the model itself, not a sibling.
            if score == len(tokens):
                score += 3
            # Memory spec in the slug: a real handset PDP.
            if _SPEC_RE.search(blob):
                score += 2
            extra_variants = (slug_toks & _VARIANT_TOKENS) - qtoks
            score -= 6 * len(extra_variants)
            out.append((score, _storage_gb(slug), href))
        return out

    # Whole-token matching first. Substring matching silently equates "17" with
    # "17T", which put the 17T's price on the Xiaomi 17 row. Only if nothing
    # matches at all do we fall back to substrings - the product-name gate
    # downstream still catches a wrong pick.
    scored = score_all(whole_token=True) or score_all(whole_token=False)
    if not scored:
        return None
    # Highest score first; among equals, the smallest storage tier (the entry
    # configuration, i.e. the starting price a comparison should anchor on).
    scored.sort(key=lambda x: (-x[0], x[1]))
    return scored[0][2]


def verify_product_name(query: str, name: str | None) -> tuple[bool, str]:
    """Second, URL-independent check that a PDP really is ``query``'s model.

    The URL heuristics can be fooled (Alza's "DemoBrand 600" search once returned
    the Pro's PDP). The page's own JSON-LD product name is authoritative, so we
    re-check it: every meaningful query token must appear, and the name must not
    add a variant qualifier the query never asked for.

    Returns (ok, reason). ``ok`` is True with reason "unverified" when the page
    exposed no name - we do not block on missing metadata, only on conflict.
    """
    if not name:
        return True, "unverified"
    n = name.lower()
    q = query.lower()
    qtoks = {t for t in re.split(r"[^a-z0-9]+", q) if t}
    ntoks = {t for t in re.split(r"[^a-z0-9]+", n) if t}
    # Whole-token comparison, never substring: "17" is a substring of "17T",
    # which let the Xiaomi 17T PDP pass as the Xiaomi 17.
    missing = {t for t in qtoks if len(t) > 1 and t not in ntoks}
    if missing:
        return False, f"name {name!r} missing query tokens {sorted(missing)}"
    extra = (ntoks & _VARIANT_TOKENS) - qtoks
    if extra:
        return False, f"name {name!r} is the {'/'.join(sorted(extra))} variant"
    return True, "ok"


def search_and_discover(search_url: str, query: str,
                        link_filter, timeout: float = 35) -> str | None:
    """Render a market channel's search page and return the best PDP URL.

    ``link_filter(href, text) -> bool`` decides whether an anchor is a product.

    NOTE: we never treat the search page itself as a PDP. A results page can
    accidentally parse a price (a range, an ad, a footer) which would make a
    naive ``parse_price_page`` check pass; that spawned a bogus SKU whose
    ``product_url`` was the search URL. Always extract real product anchors.
    """
    url = search_url.format(q=quote_plus(query))
    try:
        html = render(url, timeout)
    except BotWallBlocked:
        return None
    if not html:
        return None
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    cands = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = (a.get_text() or "").strip()
        # Join to the REAL search URL so relative ("/x.htm") and bare ("x.htm")
        # hrefs both resolve correctly. (The old "https://x/" base produced
        # dead URLs like https://x/demobrand-600/18922171.htm.)
        abs_href = urljoin(url, href)
        # Drop tracking query strings (?o=18) so we store a clean PDP url.
        abs_href = abs_href.split("?", 1)[0]
        if link_filter(abs_href, text):
            cands.append((abs_href, text))
    return pick_best_result(cands, query)


def fetch_gigatron_product(url: str, expected_currency: str | None = "CZK",
                           timeout: float = 35) -> dict:
    """Canonical entry the crawler calls. Renders ``url`` with the stealth
    browser, parses JSON-LD (+ strikethrough) and returns the standard dict::

        {price, original_price, currency, in_stock, sku, name, meta}

    ``meta`` carries the extra dimensions the user explicitly asked for
    (original vs current price split, provenance) so promo pricing is never
    mistaken for the normal price downstream.
    """
    html = render(url, timeout)
    if not html:
        raise RuntimeError(f"stealth render returned nothing for {url}")
    data = parse_price_page(html, url, expected_currency=expected_currency)
    if expected_currency and data["currency"] != expected_currency:
        # Defensive: market channels here are CZ-based. A mismatched currency
        # usually means the parser grabbed an unrelated node.
        log.warning(
            "currency mismatch on %s: got %s expected %s",
            url, data["currency"], expected_currency,
        )
    data["meta"] = {
        "original_price": data.pop("original_price", None),
        "current_price": data["price"],
        "currency": data["currency"],
        "sku": data.get("sku"),
        # The full product name carries the memory config ("12GB/256GB"), which
        # is what makes a cross-channel price comparable. Without it a 1TB
        # flagship price looks like a plain price drop.
        "product_name": data.get("name"),
        "in_stock": data.get("in_stock"),
        "gift": data.get("gift"),
        "url": url,
        "fetched_at": _now_iso(),
        "method": "stealth_browser_jsonld",
    }
    return data


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------
# Gigantti (Finland) specific price extraction
# --------------------------------------------------------------------------
# Gigantti (Elkjøp Nordic) emits a JSON-LD ``offers`` list of the form
# ``[priceInclVat, priceExclVat]``. The generic parser in ``parse_price_page``
# keeps the *lower* (ex-VAT) figure via its min/max logic, which understates
# every Finnish price by 25.5%. The real selling price -- what consumers pay
# and what the comparison matrix is built on -- is the ``inc-vat`` span rendered
# in the DOM. Pull that instead.
_GIGANTTI_INC_VAT_RE = re.compile(r'inc-vat(?:\\.|[^"\\])*?children\\":\\"([\d\s,]+)\s*€')

# Rendered per-month marker. Gigantti prints an installment figure next to a
# "/kk" (kuukautta = per month) sibling span, e.g.
# ``149,00 €</span><span class="ml-1 text-2xl">/kk</span>``. Such an inc-vat
# value is a monthly payment, not the device's outright price, and must not
# win the first-plausible race. We look only at the chars immediately after
# the matched span, so a financing widget further down the page cannot
# false-skip the real device price. (2026-08-18: DemoBrand 600 Pro PDP exposed an
# "alk. 149 €/kk" span ahead of the real 799 € device price; the old
# first-match rule returned 149 and tripped the cross-channel outlier flag.)
_GIGANTTI_PER_MONTH_RE = re.compile(r'/kk')


def gigantti_main_price(html: str, currency: str = "EUR") -> float | None:
    """Return Gigantti's main ``inc-vat`` (VAT-inclusive) price from the DOM.

    The first ``inc-vat`` span in document order is the product's own price
    (the header block); later ones belong to accessory / shipping / cross-sell
    widgets. So we return the *first* value that falls inside the plausible
    handset band — a later ``inc-vat`` shipping/accessory fee (or a larger
    cross-sell price) must never override the device price. The old code kept
    only the *last* parsed value, so a footer price could displace the header
    price and under/over-state the phone. (P2-15.)

    Financing guard (2026-08-18): a per-month installment figure can itself be
    rendered in an ``inc-vat`` span ("alk. 149 €/kk") and, plausible as a raw
    number, win the first-match race and displace the real outright price.
    Any ``inc-vat`` value whose immediately-following text carries the ``/kk``
    per-month marker is now skipped. Only a short window after the match is
    scanned, so a financing widget lower on the page cannot false-skip the
    genuine device price.
    """
    from app.crawling.currency import is_plausible

    for m in _GIGANTTI_INC_VAT_RE.finditer(html):
        s = m.group(1).replace(" ", "").replace(",", ".")
        try:
            v = float(s)
        except ValueError:
            continue
        if not is_plausible(v, currency):
            continue
        # Skip per-month financing figures (€/kk).
        if _GIGANTTI_PER_MONTH_RE.search(html, m.end(), m.end() + 80):
            continue
        return v
    return None
