"""Euro (Poland market channel) crawl adapter.

Euro sits behind Akamai. Static httpx is blocked (HTTP 403 on the egress IP),
so every fetch goes through the stealth renderer in ``market_common`` (the same
path that already works for Alza / Datart).
"""
from __future__ import annotations

import logging

from app.crawling.currency import is_plausible
from app.crawling.market_common import (
    fetch_gigatron_product as _base_fetch,
)

log = logging.getLogger("crawl.euro")


def fetch_gigatron_product(url: str, expected_currency: str | None = "PLN",
                           timeout: float = 35) -> dict:
    """Render + parse a Euro PDP. Returns the crawler's standard dict.

    Raises RuntimeError if the page yields no plausible price so a bad parse
    never silently corrupts the comparison.
    """
    data = _base_fetch(url, expected_currency=expected_currency, timeout=timeout)
    if not is_plausible(data["price"], data["currency"]):
        raise RuntimeError(
            f"Euro price {data['price']} {data['currency']} outside plausible "
            f"band for {url}"
        )
    data.setdefault("meta", {})
    data["meta"]["source"] = "euro.com.pl"
    return data
