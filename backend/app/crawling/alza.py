"""Alza.cz (Czech Republic market channel) crawl adapter.

Alza sits behind Cloudflare. Static httpx is blocked and a *plain* headless
browser is challenged, so every fetch goes through the stealth renderer in
``market_common`` (see its module docstring for the why).
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

log = logging.getLogger("crawl.alza")

SEARCH_URL = "https://www.alza.cz/search.htm?exps={q}"

# Canonical Alza product PDPs end in "-d<digits>.htm" (e.g.
# /demobrand-600-8gb-512gb-black-d13313294.htm). Search-result cards append a
# tracking query (?o=18), so we match "...-d<id>.htm" followed by end-of-string
# OR a "?". Category / brand-hub / recenze / levne pages look similar
# (/demobrand-600/18922171.htm, /demobrand-600-recenze, /levne-demobrand-600/...) but never
# carry the "-d<id>" token, so this is the reliable discriminator.
_ALZA_PDP = re.compile(r"-d\d{5,}\.htm(?:$|\?)", re.I)


def _is_product_link(href: str, text: str) -> bool:
    if not href or href.startswith(("javascript:", "#", "mailto:")):
        return False
    if not _ALZA_PDP.search(href):
        return False
    # Reject glass protectors / cases / chargers "for" the phone - searching
    # "DemoBrand 600 Smart" used to surface a 299 CZK tempered glass as the top hit.
    return not is_accessory(href, text)


def discover_pdp(query: str, timeout: float = 35) -> str | None:
    """Return the best Alza PDP URL for ``query``, or None if undiscovered."""
    return search_and_discover(SEARCH_URL, query, _is_product_link, timeout)


def fetch_gigatron_product(url: str, expected_currency: str | None = "CZK",
                           timeout: float = 35) -> dict:
    """Render + parse an Alza PDP. Returns the crawler's standard dict.

    Raises RuntimeError if the page yields no plausible price (so a bad parse
    never silently corrupts the comparison - the user explicitly cares about
    price correctness for strategy decisions).
    """
    data = _base_fetch(url, expected_currency=expected_currency, timeout=timeout)
    if not is_plausible(data["price"], data["currency"]):
        raise RuntimeError(
            f"Alza price {data['price']} {data['currency']} outside plausible "
            f"band for {url}"
        )
    data.setdefault("meta", {})
    data["meta"]["source"] = "alza.cz"
    return data
