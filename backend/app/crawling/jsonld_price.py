"""Shared JSON-LD price extraction for market channels whose PDP embeds a
structured ``Offer`` / ``Product`` price in ``application/ld+json``.

Media Markt (HU) and Mediaexpert (PL) both return server-rendered HTML with the
price inside JSON-LD, so a plain static httpx fetch is enough — no stealth
browser required (unlike the Akamai/Cloudflare/F5 bot-wall channels). The
generic gigatron soup-parser keys off gigatron.rs markup and misses these two,
which is why they failed 100% of crawls. This module recovers them.

A headless render is used only as a fallback when the static HTML yields no
price (e.g. a future SPA switch), keeping the path robust without depending on
the flaky browser pool for the common case.
"""
from __future__ import annotations

import json
import logging
import re
import time

import httpx
from bs4 import BeautifulSoup

from app.crawling.currency import is_plausible
from app.crawling.gigatron import UA, _render_with_browser

log = logging.getLogger("crawl.jsonld")

_RETRY_STATUS = (429, 500, 502, 503, 504)


def _to_float(v: object) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    m = re.search(r"\d+(?:\.\d+)?", s)
    return float(m.group(0)) if m else None


def _extract_node(node: object, out: list[tuple]) -> None:
    """Collect (price, original, currency, in_stock, name) from any JSON-LD
    node (recursively) that carries a price + currency."""
    if isinstance(node, dict):
        price = node.get("price")
        pcurr = node.get("priceCurrency")
        if price is not None and pcurr is not None:
            pf = _to_float(price)
            if pf is not None:
                original = None
                spec = node.get("priceSpecification")
                specs = spec if isinstance(spec, list) else ([spec] if isinstance(spec, dict) else [])
                for sp in specs:
                    if not isinstance(sp, dict):
                        continue
                    ptype = str(sp.get("priceType") or sp.get("@type") or "")
                    if "StrikethroughPrice" in ptype:
                        original = _to_float(sp.get("price"))
                        break
                avail = str(node.get("availability") or "").lower()
                in_stock = "instock" in avail
                out.append((pf, original, pcurr, in_stock, node.get("name")))
        for v in node.values():
            _extract_node(v, out)
    elif isinstance(node, list):
        for v in node:
            _extract_node(v, out)


def parse_jsonld(html: str, expected_currency: str | None, url: str) -> dict | None:
    """Return the crawler's standard dict, or None when no plausible price."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[tuple] = []
    for b in soup.find_all("script", type="application/ld+json"):
        txt = b.string or b.get_text()
        try:
            obj = json.loads(txt)
        except Exception:
            continue
        for item in (obj if isinstance(obj, list) else [obj]):
            _extract_node(item, out)
    if not out:
        return None
    # Prefer a node that carries an original (strikethrough) price — that marks
    # the main product, not a recommendation/cross-sell card.
    out.sort(key=lambda r: r[1] is not None, reverse=True)
    price, original, pcurr, in_stock, name = out[0]
    currency = expected_currency or pcurr
    if not is_plausible(price, currency):
        log.warning("jsonld price %s %s outside plausible band for %s", price, currency, url)
        return None
    return {
        "price": price,
        "original_price": original if (original and original > price) else None,
        "currency": currency,
        "in_stock": in_stock,
        "gift": None,
        "product_name": name,
    }


def _static_fetch(url: str, timeout: float) -> str | None:
    last_exc = None
    for attempt in range(3):
        try:
            resp = httpx.get(url, headers=UA, timeout=timeout, follow_redirects=True)
            if resp.status_code in _RETRY_STATUS:
                wait = float(resp.headers.get("retry-after") or 2 ** attempt)
                time.sleep(min(wait, 8))
                last_exc = RuntimeError(f"HTTP {resp.status_code}")
                continue
            resp.raise_for_status()
            return resp.text
        except Exception as exc:  # network / HTTP
            last_exc = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
    log.info("static fetch failed for %s: %s", url, last_exc)
    return None


def fetch_jsonld_product(url: str, expected_currency: str | None = None,
                         timeout: float = 40) -> dict:
    """Fetch + parse a JSON-LD-backed PDP. Raises RuntimeError if no price."""
    html = _static_fetch(url, timeout)
    data = parse_jsonld(html, expected_currency, url) if html else None
    if data is None:
        rendered = _render_with_browser(url, timeout=max(timeout, 30))
        if rendered:
            data = parse_jsonld(rendered, expected_currency, url)
    if data is None:
        raise RuntimeError(f"no price found on {url or 'page'} (jsonld)")
    data.setdefault("meta", {})
    data["meta"]["method"] = "jsonld_static"
    return data
