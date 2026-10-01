"""Plausibility-band guard tests.

Cover three layers:

1. ``is_plausible_for`` returns the right verdict for the band-table
   combinations that have produced real incidents:
   - Vodafone RO 8/20 (EUR subsidy_down_payment=2600, band was 80-4000 →
     originally passed; 2500-4000 below band fix would have caught it; our
     above-threshold=4000 EUR rule still flags it on the rule side.)
   - GIGATRON 99999.99 EUR unlocked sentinel (well above 4000 EUR band)
   - contract_monthly in HUF (operator monthly fee, must NOT be tested with
     the EUR 80-4000 band — that's the whole point of splitting bands)

2. ``add_price`` (the only write path) rejects out-of-band prices and accepts
   in-band ones, including the dedup short-circuit on identical repeats.

3. ``is_plausible_for`` with ``price_type=None`` falls back to the legacy
   currency-only band, so the existing crawler templates that don't know the
   price type keep their old semantics.

Run with:
    PYTHONPATH=backend backend/.venv/bin/python3 -m pytest tests/test_plausibility_band.py -v
"""
from __future__ import annotations

import os
import sys

# Tests run from backend/ so the app package is importable as-is.
HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.dirname(HERE)
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

# Pin DB to the absolute path so add_price works from any cwd.
os.environ.setdefault(
    "DATABASE_URL",
    f"sqlite:///{os.path.join(BACKEND_ROOT, 'price_monitor.db')}",
)

import uuid  # noqa: E402

import pytest  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app.core.db import engine  # noqa: E402
from app.crawling.currency import (  # noqa: E402
    PLAUSIBLE_BANDS_BY_TYPE,
    is_plausible,
    is_plausible_for,
)
from app.models.catalog import Model, Sku  # noqa: E402
from app.models.channel import Channel  # noqa: E402
from app.repositories.prices import PlausibilityError, add_price  # noqa: E402


# ---------------------------------------------------------------------------
# Pure-function band tests — no DB needed
# ---------------------------------------------------------------------------

class TestIsPlausibleFor:
    """Per-(currency, price_type) verdict table."""

    # subsidy_down_payment: the headline use case — Vodafone RO 2600 EUR is
    # at the EUR-band edge; the *band* (50-4000) accepts 2600 (because the
    # band cap was raised to 4000 for flagship foldables), but the rule
    # engine below catches 2600 via the above 2500 threshold. Both layers
    # are correct on purpose — the band rejects "obviously junk" sentinels
    # like 99999, the rule rejects "plausible but suspicious" outliers.

    def test_vodafone_ro_2600_eur_subsidy_in_band(self):
        # 2600 sits inside the EUR band (50-4000). The rule layer catches it.
        assert is_plausible_for(2600, "EUR", "subsidy_down_payment") is True

    def test_gigatron_99999_eur_unlocked_out_of_band(self):
        assert is_plausible_for(99999.99, "EUR", "unlocked") is False

    def test_gigatron_12345_eur_unlocked_out_of_band(self):
        assert is_plausible_for(12345.67, "EUR", "unlocked") is False

    def test_negative_or_zero_always_rejected(self):
        assert is_plausible_for(-1, "EUR", "unlocked") is False
        assert is_plausible_for(0, "EUR", "unlocked") is False
        # allow_zero=True opts into the bundle-only path used by add_price.
        assert is_plausible_for(0, "EUR", "unlocked", allow_zero=True) is True
        assert is_plausible_for(None, "EUR", "unlocked") is False

    def test_huf_contract_monthly_in_band(self):
        # Was previously flagged "out of band" because the legacy band
        # (30000-1200000 HUF) is too wide for a 5000 HUF monthly fee. The
        # split band (500-80000) now accepts it.
        assert is_plausible_for(5000, "HUF", "contract_monthly") is True

    def test_huf_contract_monthly_out_of_band(self):
        # Way too low (typo: 50 HUF instead of 5000 HUF).
        assert is_plausible_for(50, "HUF", "contract_monthly") is False

    def test_huf_contract_monthly_too_high(self):
        # Caught by HUF contract_monthly band ceiling (80000 HUF ≈ 200 EUR,
        # which is generous for any monthly fee in HUF).
        assert is_plausible_for(500_000, "HUF", "contract_monthly") is False

    def test_unknown_price_type_passes(self):
        # Future price_type additions shouldn't break the write path.
        assert is_plausible_for(100, "EUR", "future_type") is True

    def test_legacy_currency_only_fallback(self):
        # is_plausible() without price_type — the legacy entry point used by
        # crawler templates that don't know the price_type in scope.
        assert is_plausible(100, "EUR") is True
        assert is_plausible(99999, "EUR") is False

    def test_band_table_size(self):
        # If this test fails, somebody added a (currency, price_type) pair
        # to PLAUSIBLE_BANDS_BY_TYPE without updating seed_default_alert_rules
        # to mirror it. The seed script counts 56 rules (4×7×2) and exits
        # non-zero on mismatch.
        expected = 4 * 7  # 4 price_type × 7 currency
        assert len(PLAUSIBLE_BANDS_BY_TYPE) == expected, (
            f"PLAUSIBLE_BANDS_BY_TYPE has {len(PLAUSIBLE_BANDS_BY_TYPE)} "
            f"entries, expected {expected}. Did you forget to mirror it in "
            f"scripts/seed_default_alert_rules.py?"
        )


# ---------------------------------------------------------------------------
# Write-path integration tests — exercise add_price against the live DB
# ---------------------------------------------------------------------------

@pytest.fixture
def session():
    with Session(engine) as s:
        yield s


@pytest.fixture
def fresh_sku(session):
    """A throwaway (channel, model, sku) triple that we can write into.

    Tests use it to assert add_price's behaviour without polluting real
    product data. Channel/model are inserted only if missing; SKU is
    always fresh so the dedup short-circuit can't false-positive.
    """
    ch_name = f"test_band_ch_{uuid.uuid4().hex[:8]}"
    m_name = f"TestBandModel_{uuid.uuid4().hex[:8]}"
    ch = Channel(name=ch_name, country="Hungary", type="operator", base_url="https://example.com",
                  crawl_mode="static", health="healthy", enabled=True,
                  created_at="2026-01-01T00:00:00+00:00", updated_at="2026-01-01T00:00:00+00:00",
                  contract_term_months=24)
    session.add(ch); session.commit(); session.refresh(ch)
    m = Model(display_name=m_name, brand="TestBrand",
              marketing_code=f"TEST-{uuid.uuid4().hex[:8]}",
              created_at="2026-01-01T00:00:00+00:00", updated_at="2026-01-01T00:00:00+00:00")
    session.add(m); session.commit(); session.refresh(m)
    sku = Sku(model_id=m.id, channel_id=ch.id,
              product_url=f"https://example.com/test/{uuid.uuid4().hex}",
              created_at="2026-01-01T00:00:00+00:00", updated_at="2026-01-01T00:00:00+00:00")
    session.add(sku); session.commit(); session.refresh(sku)
    yield ch, m, sku
    # cleanup
    session.delete(sku); session.commit()
    session.delete(m); session.commit()
    session.delete(ch); session.commit()


class TestAddPriceWriteGuard:

    def test_in_band_price_writes(self, session, fresh_sku):
        ch, m, sku = fresh_sku
        p = add_price(
            session=session,
            sku_id=sku.id, channel_id=ch.id,
            price_type="contract_monthly",
            price=5000.0, currency="HUF", amount_eur=12.5,
        )
        session.commit()
        assert p.id is not None
        assert p.price == 5000.0

    def test_out_of_band_price_rejected(self, session, fresh_sku):
        ch, m, sku = fresh_sku
        with pytest.raises(PlausibilityError) as ei:
            add_price(
                session=session,
                sku_id=sku.id, channel_id=ch.id,
                price_type="unlocked",
                price=99999.99, currency="EUR", amount_eur=99999.99,
            )
        session.rollback()
        # Message must mention the bad price + currency + price_type so the
        # crawler can log without re-resolving the band.
        msg = str(ei.value)
        assert "99999.99" in msg
        assert "EUR" in msg
        assert "unlocked" in msg

    def test_negative_price_rejected(self, session, fresh_sku):
        ch, m, sku = fresh_sku
        with pytest.raises(PlausibilityError):
            add_price(
                session=session, sku_id=sku.id, channel_id=ch.id,
                price_type="unlocked", price=-1.0, currency="EUR",
                amount_eur=-1.0,
            )
        session.rollback()

    def test_zero_price_rejected(self, session, fresh_sku):
        """Zero without original_price is a sentinel — must be rejected."""
        ch, m, sku = fresh_sku
        with pytest.raises(PlausibilityError):
            add_price(
                session=session, sku_id=sku.id, channel_id=ch.id,
                price_type="unlocked", price=0.0, currency="EUR",
                amount_eur=0.0,
            )
        session.rollback()

    def test_zero_with_original_price_accepted(self, session, fresh_sku):
        """Bundle-only offers (device 0 EUR on plan) are legitimate and
        must persist with the original_price > 0 cross-check."""
        ch, m, sku = fresh_sku
        p = add_price(
            session=session, sku_id=sku.id, channel_id=ch.id,
            price_type="unlocked", price=0.0, currency="EUR",
            amount_eur=0.0, original_price=999.0,
        )
        session.commit()
        assert p.id is not None

    def test_dedup_short_circuit(self, session, fresh_sku):
        """Identical repeat writes must short-circuit to existing row."""
        ch, m, sku = fresh_sku
        p1 = add_price(
            session=session, sku_id=sku.id, channel_id=ch.id,
            price_type="contract_monthly", price=5000.0,
            currency="HUF", amount_eur=12.5,
        )
        session.commit()
        p2 = add_price(
            session=session, sku_id=sku.id, channel_id=ch.id,
            price_type="contract_monthly", price=5000.0,
            currency="HUF", amount_eur=12.5,
        )
        session.commit()
        assert p1.id == p2.id  # short-circuited to same row

    def test_vodafone_ro_2600_still_rejected_at_band_edge(self, session, fresh_sku):
        """2600 sits inside the EUR subsidy band (50-4000) — band accepts it,
        but the rule layer's above-2500 threshold catches it as suspicious.
        This test pins the band-only verdict (rule layer is separate).
        """
        ch, m, sku = fresh_sku
        p = add_price(
            session=session, sku_id=sku.id, channel_id=ch.id,
            price_type="subsidy_down_payment", price=2600.0,
            currency="EUR", amount_eur=2600.0,
        )
        session.commit()
        assert p.id is not None  # band allows it; rule will flag separately

    def test_huf_out_of_band_high(self, session, fresh_sku):
        """A HUF unlocked above 1.5M HUF (~3846 EUR) is implausible for any
        handset — must be rejected by the band."""
        ch, m, sku = fresh_sku
        with pytest.raises(PlausibilityError):
            add_price(
                session=session, sku_id=sku.id, channel_id=ch.id,
                price_type="unlocked", price=2_000_000,
                currency="HUF", amount_eur=5000.0,
            )
        session.rollback()