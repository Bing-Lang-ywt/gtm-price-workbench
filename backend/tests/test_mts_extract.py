"""MTS SPA extraction fixes (space-insensitive card matching + safe monthly parse).

Pure unit tests — no browser, no network, no DB. Card dicts are fed straight
to ``_assign_cards``; page text is fed straight to ``_parse_spa_prices``.

Two regressions are pinned here:

  * A. ``_assign_cards`` must match MTS list-page card names (rendered WITH
    spaces, e.g. "Galaxy Z Fold 8 Ultra") against the space-free keywords in
    ``SPA_CONFIG["MTS"]``. The most-specific (longest normalized keyword) code
    must win, so a card is never stolen by a shorter sibling code.
  * B/C. ``_parse_spa_prices`` must extract the DEVICE monthly installment from
    the "Rata za uređaj ... RSD/mes" anchor and must NOT fall through to a
    "smallest RSD/mes" guess that grabs the trade-in (reklaža) or the flat plan
    fee. Only the two recrawl-confirmed values are asserted (Z Fold 8 = 9325,
    Z Fold 8 Ultra = 10225); other SKU numbers are not asserted because they
    were not recrawl-confirmed.
"""
import pytest

from app.crawling import operator_spa as spmod

# Mirror fetch_operator_spa's normalization so the tests bind to the real MTS
# keyword map. NOTE: fetch_operator_spa uppercases the kw_map keys
# (operator_spa.py:131), so the codes _assign_cards returns are UPPERCASE
# (e.g. "GALAXYS26U", "GALAXYZFOLD8ULTRA"). The SPA_CONFIG keys are written
# mixed-case only for readability; the runtime values are uppercase.
MTS_KW = {k.upper(): v for k, v in spmod.SPA_CONFIG["MTS"]["keywords"].items()}


def _assign(name: str):
    """Return the code ``_assign_cards`` binds to a single card named ``name``."""
    assigned = spmod._assign_cards([{"name": name, "href": "#"}], MTS_KW)
    for code, cards in assigned.items():
        if cards and cards[0]["name"] == name:
            return code
    return None


# --- A. space-insensitive, most-specific-wins -------------------------------
@pytest.mark.parametrize(
    "name,expected",
    [
        # Fold8 Ultra must stay with GalaxyZFold8Ultra, not GalaxyZFold8.
        ("Galaxy Z Fold 8 Ultra", "GALAXYZFOLD8ULTRA"),
        ("Galaxy Z Fold 8", "GALAXYZFOLD8"),
        # S26 Ultra must stay with GalaxyS26U, not GalaxyS26.
        ("Galaxy S26 Ultra", "GALAXYS26U"),
        # DemoBrand 600 Lite must win via the longer "demobrand 600 lite" key (12 chars,
        # normalized), not H600's "demobrand 600" (8) or H600L's "600 lite" (7).
        ("DemoBrand 600 Lite", "H600L"),
        ("DemoBrand 600 Pro", "H600P"),
        ("DemoBrand 600", "H600"),
    ],
)
def test_assign_cards_space_insensitive(name, expected):
    assert _assign(name) == expected


def test_assign_cards_h600l_not_stolen_by_h600():
    # Explicit guard: H600L must win over H600 for "DemoBrand 600 Lite". The win is
    # driven by the longer "demobrand 600 lite" keyword (normalized length 12),
    # proving the space-normalized specificity ranking is what selects it.
    code = _assign("DemoBrand 600 Lite")
    assert code == "H600L"
    assert code != "H600"
    assert code != "H600P"


# --- B/C. monthly parse: explicit anchor, no smallest-RSD/mes guess ----------
def test_parse_monthly_zfold8_excludes_reklaža_and_plan():
    # recrawl-confirmed real values: device 9.325 / trade-in 8.700 / plan 4.199.
    txt = (
        "Rata za uređaj 9.325 RSD/mes uz reciklažu 8.700 RSD/mes "
        "Odabrani paket 4.199 RSD/mes"
    )
    total, monthly = spmod._parse_spa_prices(txt, spmod.SPA_CONFIG["MTS"])
    assert monthly == 9325          # device installment, never reklaža/plan
    assert monthly != 8700
    assert monthly != 4199
    assert total is None            # MTS publishes no one-time total


def test_parse_monthly_zfold8_ultra():
    # recrawl-confirmed: device 10.225 (x24 = 245,400 RSD, the correct total).
    txt = (
        "Rata za uređaj 10.225 RSD/mes uz reciklažu 9.600 RSD/mes "
        "Odabrani paket 4.199 RSD/mes"
    )
    total, monthly = spmod._parse_spa_prices(txt, spmod.SPA_CONFIG["MTS"])
    assert monthly == 10225
    assert total is None
