from app.crawling import gigatron, operator_list
from app.crawling import alza as alza_adapter
from app.crawling import datart as datart_adapter
from app.crawling import euro as euro_adapter
from app.crawling import gigantti as gigantti_adapter
from app.crawling import altex as altex_adapter
from app.crawling import mediamarkt as mediamarkt_adapter
from app.crawling import mediaexpert as mediaexpert_adapter
from app.models.channel import Channel

# Channels behind bot walls / JS-heavy SPAs that require the stealth browser
# renderer. They are still "static" crawl_mode in the DB but must NOT go through
# the httpx-based gigatron adapter (which is blocked or sees an empty shell).
#
#   Alza / Datart  -> Cloudflare / F5 Shape (verified stealth pass)
#   Euro           -> Akamai (stealth browser is the only path that can pass)
#   Gigantti       -> JS SPA, static httpx returns an empty shell
#   Altex          -> rejects Playwright's default fingerprint with
#                     ERR_HTTP2_PROTOCOL_ERROR; stealth renderer passes
_MARKET_BOTWALL = {
    "Alza": alza_adapter,
    "Datart": datart_adapter,
    "Euro": euro_adapter,
    "Gigantti": gigantti_adapter,
    "Altex": altex_adapter,
    # Media Markt (HU) gained a captcha/403 bot wall in 2026-09; the plain
    # httpx JSON-LD path failed 100% of crawls and froze prices on stale
    # August values. Its adapter now routes through market_common's stealth
    # renderer (same as Alza/Datart) which passes the challenge.
    "Media Markt": mediamarkt_adapter,
}

# Market channels that serve the price in server-rendered JSON-LD
# (application/ld+json) and are NOT bot-walled, so a plain static httpx fetch
# suffices. The generic gigatron soup-parser keys off gigatron.rs markup and
# misses them, which is why they failed 100% of crawls.
#   Mediaexpert (PL) -> Product Offer price
_MARKET_JSONLD = {
    "Mediaexpert": mediaexpert_adapter,
}


def adapter_for(channel: Channel):
    """Return the crawl adapter module for a channel based on its crawl_mode."""
    if channel.name in _MARKET_BOTWALL:
        return _MARKET_BOTWALL[channel.name]
    if channel.name in _MARKET_JSONLD:
        return _MARKET_JSONLD[channel.name]
    if channel.crawl_mode == "static":
        return gigatron
    return operator_list
