"""Datart.cz (Czech Republic market channel) crawl adapter.

Datart sits behind an F5 Shape / TSPD challenge. Like Alza, a plain httpx
fetch returns a JS challenge page and a *plain* headless browser is caught, so
every fetch goes through the stealth renderer in ``market_common``.
"""
from __future__ import annotations

import logging
import re

from app.crawling.currency import is_plausible
from app.crawling.market_common import (
    fetch_gigatron_product as _base_fetch,
    is_accessory,
    search_and_discover,
)

log = logging.getLogger("crawl.datart")

SEARCH_URL = "https://www.datart.cz/vyhledavani?q={q}"

_DATART_PDP = re.compile(r"/mobilni-telefon", re.I)


def _is_product_link(href: str, text: str) -> bool:
    if not href or "vyhledavani" in href or href.startswith(("javascript:", "#", "mailto:")):
        return False
    if not _DATART_PDP.search(href):
        return False
    return not is_accessory(href, text)


def discover_pdp(query: str, timeout: float = 35) -> str | None:
    """Return the best Datart PDP URL for ``query``, or None if undiscovered."""
    return search_and_discover(SEARCH_URL, query, _is_product_link, timeout)


def fetch_gigatron_product(url: str, expected_currency: str | None = "CZK",
                           timeout: float = 35) -> dict:
    """Render + parse a Datart PDP. Returns the crawler's standard dict.

    Raises RuntimeError if the page yields no plausible price so a bad parse
    never silently corrupts the comparison (price correctness is strategy-
    critical for the user).
    """
    data = _base_fetch(url, expected_currency=expected_currency, timeout=timeout)
    if not is_plausible(data["price"], data["currency"]):
        raise RuntimeError(
            f"Datart price {data['price']} {data['currency']} outside plausible "
            f"band for {url}"
        )
    data.setdefault("meta", {})
    data["meta"]["source"] = "datart.cz"
    return data
