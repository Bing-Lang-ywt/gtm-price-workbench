"""Regression tests for price extractors, the price-consistency audit, and
currency resolution.

These pin the highest-value, purest failure modes so a refactor can't quietly
regress them:

  * market ``parse_price_page`` must fall back to the *channel* currency
    (expected_currency) instead of a hardcoded CZK (P1-6).
  * Telekom HT original_price must pair the SplitContractPrice by *tier index*,
    not by a magic ``actual + 10`` offset that broke whenever the tier spread
    wasn't exactly 10 EUR (P1-8).
  * ``compute_price_flag`` must still fire out_of_band on a 1000x mis-parse and
    catch actual > original / product mismatches.
  * ``resolve_currency`` always prefers the channel mapping.

No network, no DB, no browser — inline HTML fixtures only. Run with:
    python -m pytest tests/test_price_extractors.py -q
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.crawling.market_common import parse_price_page  # noqa: E402
from app.crawling.currency import resolve_currency  # noqa: E402
from app.services.price_audit import compute_price_flag  # noqa: E402


# --------------------------------------------------------------------------
# P1-6: market parse_price_page currency fallback
# --------------------------------------------------------------------------
# JSON-LD with a price but NO priceCurrency -> currency must come from the
# channel's expected_currency, never a hardcoded CZK.
_PRODUCT_NO_CCY = """
<html><head><script type="application/ld+json">
{"@type":"Product","name":"Test Phone 8GB/256GB",
 "offers":{"@type":"Offer","price":299}}
</script></head><body></body></html>
"""


def test_parse_price_page_uses_expected_currency():
    d = parse_price_page(_PRODUCT_NO_CCY, "https://shop.example/p", expected_currency="PLN")
    assert d["price"] == 299.0
    assert d["currency"] == "PLN"


def test_parse_price_page_defaults_to_czk_when_no_expected():
    d = parse_price_page(_PRODUCT_NO_CCY, "https://shop.example/p")
    assert d["currency"] == "CZK"


def test_parse_price_page_keeps_page_currency_over_expected():
    html = _PRODUCT_NO_CCY.replace('"price":299', '"price":299,"priceCurrency":"HUF"')
    d = parse_price_page(html, "https://shop.example/p", expected_currency="PLN")
    assert d["currency"] == "HUF"


# --------------------------------------------------------------------------
# P1-8: Telekom HT original_price = same-tier SplitContractPrice
# --------------------------------------------------------------------------
class _Page:
    def __init__(self, html: str):
        self._html = html

    def content(self):
        return self._html


# Three tiers, OneTimePrice and SplitContractPrice, with a NON-10 spread (15).
# Middle tier: OneTimePrice 410 -> SplitContractPrice 425.
_TELEKOM_HT_SPREAD15 = """
<script>
var a = {'OneTimePrice':400.00,'SplitContractPrice':415.00};
var b = {'OneTimePrice':410.00,'SplitContractPrice':425.00};
var c = {'OneTimePrice':420.00,'SplitContractPrice':435.00};
</script>
"""

# Real-world 10-EUR spread (verified against screenshot): middle tier
# OneTimePrice 409.76 -> SplitContractPrice 419.76.
_TELEKOM_HT_SPREAD10 = """
<script>
var a = {'OneTimePrice':399.76,'SplitContractPrice':409.76};
var b = {'OneTimePrice':409.76,'SplitContractPrice':419.76};
var c = {'OneTimePrice':429.76,'SplitContractPrice':439.76};
</script>
"""


def test_telekom_ht_pairs_by_tier_index_spread15():
    from app.crawling.operator_pdp import _extract_telekom_ht

    r = _extract_telekom_ht(_Page(_TELEKOM_HT_SPREAD15))
    assert r is not None
    # Middle OneTimePrice
    assert r["price"] == 410.0
    # The OLD logic (abs(v - (actual + 10)) < 5) would have returned 415.0
    # (the lower tier's split). Index pairing must return the middle tier 425.0.
    assert r["original_price"] == 425.0


def test_telekom_ht_pairs_by_tier_index_spread10():
    from app.crawling.operator_pdp import _extract_telekom_ht

    r = _extract_telekom_ht(_Page(_TELEKOM_HT_SPREAD10))
    assert r is not None
    assert r["price"] == 409.76
    assert r["original_price"] == 419.76


# --------------------------------------------------------------------------
# price_audit.compute_price_flag
# --------------------------------------------------------------------------
def test_audit_out_of_band_fires_on_1000x_misparse():
    flag = compute_price_flag(
        price=100000, original_price=None, gift=None, meta=None,
        currency="HUF", amount_eur=1_000_000.0, model_display_name=None,
    )
    assert flag == "out_of_band"


def test_audit_out_of_band_quiet_for_normal_huf():
    flag = compute_price_flag(
        price=100000, original_price=None, gift=None, meta=None,
        currency="HUF", amount_eur=250.0, model_display_name=None,
    )
    assert flag is None


def test_audit_actual_gt_original():
    flag = compute_price_flag(
        price=500.0, original_price=400.0, gift=None, meta=None,
        currency="EUR", amount_eur=500.0, model_display_name=None,
    )
    assert "actual_gt_original" in flag


def test_audit_product_mismatch():
    flag = compute_price_flag(
        price=100.0, original_price=None, gift=None,
        meta={"product_name": "Samsung Galaxy S26"}, currency="EUR",
        amount_eur=100.0, model_display_name="DemoBrand 600",
    )
    assert "product_mismatch" in flag


# --------------------------------------------------------------------------
# currency.resolve_currency — channel mapping always wins
# --------------------------------------------------------------------------
def test_resolve_currency_prefers_expected():
    assert resolve_currency("EUR", "USD", "https://x") == "EUR"


def test_resolve_currency_falls_back_to_sniffed():
    assert resolve_currency(None, "USD", "https://x") == "USD"


def test_resolve_currency_expected_when_matching():
    assert resolve_currency("EUR", "EUR", "https://x") == "EUR"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
