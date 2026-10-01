"""Media Markt (Hungary market channel) crawl adapter.

Media Markt HU now sits behind a captcha / 403 bot wall (verified 2026-09-15):
a plain static httpx fetch returns a challenge page, so the old ``jsonld_price``
path failed 100% of crawls and left the comparison frozen on stale August prices
(e.g. H600 showed 214999 vs the real 179999). We render through the shared
stealth headless-Chromium renderer in ``market_common`` (the same one Alza /
Datart use) which passes the challenge, then parse the server-rendered JSON-LD.

The renderer's offer-walk keeps the *first* product offer — the handset's own
price (InStock) — and ignores the accessory / warranty offers that share the
page (screen-protector, "Garancia Plusz" extensions), so no price poisoning.
"""
from __future__ import annotations

import logging

from app.crawling.market_common import fetch_gigatron_product as _market_fetch

log = logging.getLogger("crawl.mediamarkt")


def fetch_gigatron_product(url: str, expected_currency: str | None = "HUF",
                           timeout: float = 40) -> dict:
    """Render + parse a Media Markt HU PDP. Returns the crawler's standard dict."""
    data = _market_fetch(url, expected_currency=expected_currency, timeout=timeout)
    data.setdefault("meta", {})
    data["meta"]["source"] = "mediamarkt.hu"
    return data
