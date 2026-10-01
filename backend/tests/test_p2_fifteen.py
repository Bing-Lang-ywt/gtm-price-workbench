"""P2-15: ``gigantti_main_price`` must return the FIRST ``inc-vat`` value that
falls inside the plausible handset band, not the LAST parsed value.

The old loop overwrote ``v`` each iteration and only checked the band on the
final value, so a footer/accessory ``inc-vat`` price could displace the header
device price. The fixture carries three matches: a plausible device price
(699), a tiny implausible one (39.90, e.g. a shipping fee), and a larger
plausible one (1299, e.g. a cross-sell). The fix returns 699; the bug returned
1299.

The spans use the literal ``inc-vat":"children":"<num> €`` shape the
extractor's regex expects (the ``\\"`` are backslash-quotes).

Run: python -m pytest tests/test_p2_fifteen.py -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.crawling.market_common import gigantti_main_price  # noqa: E402


# Three inc-vat spans: device (699), tiny fee (39.90), larger cross-sell (1299).
_HTML = r"""
<p>header inc-vat\":{\"children\":\"699,00 € promotion</p>
<p>ship inc-vat\":{\"children\":\"39,90 € fee</p>
<p>cross inc-vat\":{\"children\":\"1299,00 € sell</p>
"""


def test_returns_first_plausible_not_last():
    assert gigantti_main_price(_HTML, "EUR") == 699.0


def test_skips_implausible_then_finds_plausible():
    html = r'<p>x inc-vat\":{\"children\":\"1299,00 € y</p>'
    assert gigantti_main_price(html, "EUR") == 1299.0


def test_no_plausible_returns_none():
    html = r'<p>a inc-vat\":{\"children\":\"39,90 € b inc-vat\":{\"children\":\"5,00 € c</p>'
    assert gigantti_main_price(html, "EUR") is None


def test_non_eur_band_respected():
    html = r'<p>a inc-vat\":{\"children\":\"699,00 € b</p>'
    assert gigantti_main_price(html, "HUF") is None


def test_skips_per_month_financing_then_returns_device_price():
    # Real-world (2026-08-18 DemoBrand 600 Pro on Gigantti): an "alk. 149 €/kk"
    # installment inc-vat span precedes the real 799 € device price. The
    # first-match rule used to return 149; it must now skip the /kk figure and
    # return 799.
    html = (
        r'fin inc-vat\":{\"children\":\"149,00 €</span>'
        r'<span class="ml-1 text-2xl">/kk</span>'
        r'dev inc-vat\":{\"children\":\"799,00 €</span>'
    )
    assert gigantti_main_price(html, "EUR") == 799.0


def test_financing_skip_does_not_false_skip_device_price():
    # A /kk marker that sits beyond the 80-char after-window of the device
    # price span must NOT skip the device price (financing widget lower on the
    # page must not displace the header price).
    html = (
        r'dev inc-vat\":{\"children\":\"799,00 €</span>'
        r'<span class="ex-vat">636,65 €</span>'
        + ('x' * 90)
        + r'<span>/kk</span>'
    )
    assert gigantti_main_price(html, "EUR") == 799.0


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
