"""Altex.ro (Romania market channel) crawl adapter.

Altex refuses non-browser TLS fingerprints (httpx gets connection resets)
and rejects Playwright's *default* fingerprint with ``ERR_HTTP2_PROTOCOL_ERROR``
on ``page.goto`` - so the plain gigatron browser render (Windows UA, no
automation-patch) fails immediately. The stealth renderer in ``market_common``
(Mac UA + AutomationControlled disabled + navigator.webdriver patch) passes
Altex's checks for single requests when they are spaced out (the crawler
already throttles Altex to ~20s/request via CRAWL_CHANNEL_RATES), so every
fetch goes through it - exactly like Alza / Datart.
"""
from __future__ import annotations

import logging

from app.crawling.currency import is_plausible
from app.crawling.market_common import (
    fetch_gigatron_product as _base_fetch,
)

log = logging.getLogger("crawl.altex")

SEARCH_URL = "https://altex.ro/catalog/search?q={q}"


def _normalize_altex_url(url: str) -> str:
    """Altex's edge 301-redirects a ``/cpd/<id>`` path that lacks a trailing
    slash and the redirect resets the HTTP/2 connection (ERR_HTTP2_PROTOCOL_ERROR),
    so every such stored link silently fails to render. Normalise the slash once
    here so a slashless URL still crawls.
    """
    if url and "/cpd/" in url and not url.endswith("/"):
        return url + "/"
    return url


def fetch_gigatron_product(url: str, expected_currency: str | None = "RON",
                           timeout: float = 35) -> dict:
    """Render + parse an Altex PDP via the stealth renderer.

    Returns the crawler's standard dict. Raises RuntimeError if the page yields
    no plausible price so a bad parse never silently corrupts the comparison.
    """
    url = _normalize_altex_url(url)
    data = _base_fetch(url, expected_currency=expected_currency, timeout=timeout)
    if not is_plausible(data["price"], data["currency"]):
        raise RuntimeError(
            f"Altex price {data['price']} {data['currency']} outside plausible "
            f"band for {url}"
        )
    data.setdefault("meta", {})
    data["meta"]["source"] = "altex.ro"
    return data
