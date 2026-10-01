"""P2-14: operator ``in_stock`` detection + ``out_of_band`` exemption for
legitimate "subscription bundle" 0-prices (Yettel HU "Kedvezményes készülék ár
0 Ft").

The 0-price case must NOT be flagged as ``out_of_band`` (that would bury real
anomalies); instead it gets its own ``bundle_only`` semantic. A genuine broken
0 on a market channel (no operator_pdp source) must still be out_of_band.

in_stock detection must catch clear not-sold copy ("nem értékesítjük",
"elfogyott", "out of stock", ...) and mis-linked accessory pages
("/tartozekok/"), while failing open (in-stock) on unreadable render.

No network / DB / browser — inline fixtures + a fake Playwright page.
Run: python -m pytest tests/test_p2_fourteen.py -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.crawling.operator_pdp import _is_out_of_stock_text, _operator_in_stock  # noqa: E402
from app.services.price_audit import compute_price_flag  # noqa: E402


# --------------------------------------------------------------------------
# bundle_only vs out_of_band (price_audit)
# --------------------------------------------------------------------------
def test_bundle_zero_is_bundle_only_not_out_of_band():
    # Yettel HU: price 0 HUF with a real list price, operator_pdp source.
    flag = compute_price_flag(
        price=0,
        original_price=251990,
        gift=None,
        meta={"product_name": "DemoBrand 600 Lite", "source": "operator_pdp"},
        currency="HUF",
        amount_eur=0.0,
        model_display_name=None,
    )
    assert flag == "bundle_only"
    assert "out_of_band" not in flag


def test_bundle_zero_without_operator_source_stays_out_of_band():
    # A stray 0 on a market channel (no operator_pdp source) is a real error.
    flag = compute_price_flag(
        price=0,
        original_price=251990,
        gift=None,
        meta={"source": "gigatron"},
        currency="HUF",
        amount_eur=0.0,
        model_display_name=None,
    )
    assert flag == "out_of_band"


def test_zero_without_original_stays_out_of_band():
    # 0 with no list price: ambiguous -> still an anomaly.
    flag = compute_price_flag(
        price=0,
        original_price=None,
        gift=None,
        meta={"source": "operator_pdp"},
        currency="HUF",
        amount_eur=0.0,
        model_display_name=None,
    )
    assert flag == "out_of_band"


def test_negative_price_still_out_of_band():
    # Negative is always an error, never a bundle.
    flag = compute_price_flag(
        price=-5,
        original_price=251990,
        gift=None,
        meta={"source": "operator_pdp"},
        currency="HUF",
        amount_eur=-0.01,
        model_display_name=None,
    )
    assert flag == "out_of_band"


# --------------------------------------------------------------------------
# operator in_stock detection
# --------------------------------------------------------------------------
class _FakePage:
    """Minimal stand-in for a Playwright Page: returns canned innerText."""

    def __init__(self, text: str):
        self._text = text

    def evaluate(self, js):
        # Only the body.innerText query is exercised by the detector.
        return self._text


def test_out_of_stock_hungarian_nem_ertesitjuk():
    assert _is_out_of_stock_text("A terméket nem értékesítjük") is True


def test_out_of_stock_hungarian_elfogyott():
    assert _is_out_of_stock_text("A készülék elfogyott, Nincs készleten.") is True


def test_out_of_stock_english_and_serbian():
    assert _is_out_of_stock_text("This device is out of stock") is True
    assert _is_out_of_stock_text("Artikal je rasprodan") is True


def test_in_stock_normal_text():
    assert _is_out_of_stock_text("Kedvezményes készülék ár 0 Ft Teljes ár") is False


def test_operator_in_stock_true_when_sold():
    page = _FakePage("Teljes ár: 53 990 Ft Készülék listaár 251 990 Ft")
    assert _operator_in_stock(page, "https://yettel.hu/telefon/demobrand-600") is True


def test_operator_in_stock_false_when_not_sold():
    page = _FakePage("Ez a készülék nem értékesítjük jelenleg.")
    assert _operator_in_stock(page, "https://yettel.hu/telefon/demobrand-600") is False


def test_operator_in_stock_false_on_accessory_mislink():
    # Yettel HU device review page wrongly linked under /tartozekok/.
    page = _FakePage("Kedvezményes készülék ár 0 Ft")
    assert _operator_in_stock(page, "https://yettel.hu/tartozekok/demobrand-600") is False


def test_operator_in_stock_fails_open_on_render_error():
    class _BoomPage:
        def evaluate(self, js):
            raise RuntimeError("render died")

    assert _operator_in_stock(_BoomPage(), "https://yettel.hu/x") is True


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
