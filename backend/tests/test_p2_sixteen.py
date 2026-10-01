"""P2-16: Hungarian operator extractors (One HU, Yettel HU) gain a structured-
data (JSON-LD) fallback so a copy re-word / SPA relayout that breaks the text
anchors no longer silently drops the SKU.

The primary text anchor must keep winning when it works; the fallback only runs
when the primary returns None and the rendered page carries a band-plausible
JSON-LD device price. No network / browser — a fake Playwright page supplies
both innerText (primary path) and page HTML (fallback path).

Run: python -m pytest tests/test_p2_sixteen.py -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.crawling.operator_pdp import _extract_one_hu, _extract_yettel_hu  # noqa: E402


class _FakePage:
    """Supplies canned innerText (primary path) and page HTML (fallback)."""

    def __init__(self, inner_text, content_html=""):
        self._inner = inner_text
        self._content = content_html

    def evaluate(self, js):
        return self._inner

    def content(self):
        return self._content


# --- One HU ---------------------------------------------------------------
def test_one_hu_primary_text_anchor_wins():
    # Anchors present in innerText; content is empty so a fallback call would
    # yield None — proving the primary result is what's returned.
    inner = (
        "Készülék teljes ára bla Összesen 81 000 Ft - 30 000 Ft 51 000 Ft"
    )
    page = _FakePage(inner, content_html="")
    r = _extract_one_hu(page)
    assert r is not None
    assert r["price"] == 51000.0
    assert r["original_price"] == 81000.0


def test_one_hu_fallback_recovers_from_jsonld():
    # Anchors gone (copy re-worded) but JSON-LD Product price survives.
    inner = "Ez egy telefon oldal, nincs kedvezmény szoveg."
    html = (
        '<html><head><script type="application/ld+json">'
        '{"@type":"Product","name":"DemoBrand 600",'
        '"offers":{"@type":"Offer","price":51000,"priceCurrency":"HUF"}}'
        "</script></head><body></body></html>"
    )
    page = _FakePage(inner, content_html=html)
    r = _extract_one_hu(page)
    assert r is not None
    assert r["price"] == 51000.0


def test_one_hu_no_anchor_no_jsonld_still_none():
    # Old behaviour preserved: nothing to extract -> None, not a wrong price.
    inner = "Ez egy telefon oldal."
    html = "<html><body>nothing here</body></html>"
    page = _FakePage(inner, content_html=html)
    assert _extract_one_hu(page) is None


# --- Yettel HU ------------------------------------------------------------
def test_yettel_hu_fallback_recovers_from_jsonld():
    inner = "Nincs Teljes ár szoveg ezen az oldalon."
    html = (
        '<html><head><script type="application/ld+json">'
        '{"@type":"Product","name":"DemoBrand 600 Lite",'
        '"offers":{"@type":"Offer","price":103990,"priceCurrency":"HUF"}}'
        "</script></head><body></body></html>"
    )
    page = _FakePage(inner, content_html=html)
    r = _extract_yettel_hu(page)
    assert r is not None
    assert r["price"] == 103990.0


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
