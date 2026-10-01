"""Mediaexpert (Poland market channel) crawl adapter.

Mediaexpert PL returns server-rendered HTML with the price in
``application/ld+json`` (a ``Product`` Offer) plus ``product:price:amount``
OG meta. The generic gigatron soup-parser keys off gigatron.rs markup and never
finds it, so the channel failed 100% of crawls. We parse JSON-LD instead — no
stealth browser needed.
"""
from __future__ import annotations

import logging

from app.crawling.jsonld_price import fetch_jsonld_product

log = logging.getLogger("crawl.mediaexpert")


def fetch_gigatron_product(url: str, expected_currency: str | None = "PLN",
                           timeout: float = 40) -> dict:
    """Parse a Mediaexpert PL PDP. Returns the crawler's standard dict."""
    data = fetch_jsonld_product(url, expected_currency=expected_currency, timeout=timeout)
    data.setdefault("meta", {})
    data["meta"]["source"] = "mediaexpert.pl"
    return data
