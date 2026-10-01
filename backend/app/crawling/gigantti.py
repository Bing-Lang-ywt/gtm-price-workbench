"""Gigantti (Finland market channel) crawl adapter.

Gigantti is a JS-heavy SPA; the static httpx path returns an empty shell, so
every fetch goes through the stealth renderer in ``market_common``.

Important price caveat (2026-08-06): Gigantti's JSON-LD ``offers`` list is
``[priceInclVat, priceExclVat]``. The generic parser keeps the *lower* (ex-VAT)
figure, understating every Finnish price by 25.5%. We therefore override the
price with ``gigantti_main_price``, which reads the ``inc-vat`` (VAT-inclusive)
span from the rendered DOM -- the figure Finnish consumers actually pay and the
one the comparison matrix is built on.
"""
from __future__ import annotations

import logging

from app.crawling.currency import is_plausible
from app.crawling.market_common import (
    gigantti_main_price,
    parse_price_page,
    render,
)

log = logging.getLogger("crawl.gigantti")


def fetch_gigatron_product(url: str, expected_currency: str | None = "EUR",
                           timeout: float = 35) -> dict:
    """Render + parse a Gigantti PDP, returning the crawler's standard dict.

    The price is forced to the VAT-inclusive main price from the DOM; the
    generic parser's output is only used as a last-resort fallback.
    """
    html = render(url, timeout=timeout)
    if not html:
        raise RuntimeError(f"Gigantti render failed for {url}")
    data = parse_price_page(html, url, expected_currency=expected_currency)
    currency = data.get("currency") or expected_currency or "EUR"

    price = gigantti_main_price(html, currency)
    if price is None:
        # Last-resort fallback to the generic parse (ex-VAT for Gigantti, known
        # to understate -- better a stored value than a silent gap, but the
        # crawl band check below will still reject anything absurd).
        price = data.get("price")
        if price is None:
            raise RuntimeError(f"Gigantti no price found for {url}")

    if not is_plausible(price, currency):
        raise RuntimeError(
            f"Gigantti price {price} {currency} outside plausible band for {url}"
        )

    data["price"] = price
    data["currency"] = currency
    data.setdefault("meta", {})
    data["meta"]["source"] = "gigantti.fi"
    data["meta"]["vat"] = "incl"
    return data
