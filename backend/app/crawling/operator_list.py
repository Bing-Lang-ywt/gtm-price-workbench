import logging

import httpx
from bs4 import BeautifulSoup

from app.models.catalog import Sku
from app.models.channel import Channel

log = logging.getLogger("crawl.operator")

UA = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; PriceMonitorBot/0.1; +internal-competitive-intel)"
    )
}


def fetch_operator_list(channel: Channel, sku: Sku, timeout: float = 10):
    """Parse an operator channel for one SKU.

    If SPA headless crawling is enabled and available (Playwright + Chromium
    present and the channel has a SPA config), delegate to the real headless
    adapter. Otherwise fall back to a best-effort static list fetch, which
    returns [] for SPA sites (MVP reality) so the crawl degrades gracefully.
    """
    from app.crawling import operator_spa

    if operator_spa.is_spa_available() and channel.name in operator_spa.SPA_CONFIG:
        try:
            # Headless page loads need a longer budget than CRAWL_TIMEOUT.
            result = operator_spa.fetch_operator_spa(channel, sku, timeout=30)
            if result:
                return result
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("SPA crawl failed for %s, using static fallback: %s",
                        channel.name, exc)

    return _static_fetch(channel, timeout)


def _static_fetch(channel: Channel, timeout: float = 10):
    """Best-effort static list fetch. Returns [] when no price is parseable."""
    if not channel.base_url:
        return []
    try:
        resp = httpx.get(
            channel.base_url, headers=UA, timeout=timeout, follow_redirects=True
        )
        resp.raise_for_status()
    except Exception as exc:
        log.warning("operator list fetch failed %s: %s", channel.base_url, exc)
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    return _try_parse(soup, channel)


def _try_parse(soup: BeautifulSoup, channel: Channel):
    """Heuristic hook for list pages. Returns [] for MVP (SPA content absent)."""
    return []
