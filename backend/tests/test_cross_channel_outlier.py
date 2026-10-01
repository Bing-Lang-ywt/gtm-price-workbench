"""Cross-channel outlier guard (`cross_channel_outlier`).

Exercises the REAL write path through `record_price` -> `compute_price_flag`,
but against an isolated in-memory SQLite database (the production
`price_monitor.db` is never touched and no rows are written to it). The engine
used by the repositories is monkeypatched to that in-memory DB for the duration
of each test.
"""
import uuid

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.config import OUTLIER_MIN_SAMPLES
from app.models.catalog import Model
from app.models.channel import Channel
from app.models.price import Price
from app.repositories import prices as prepo
from app.services import prices as prices_svc


@pytest.fixture
def db():
    """Isolated in-memory engine; every repo write in the test lands here, and
    the production ``price_monitor.db`` is never touched. ``record_price`` takes
    the session we hand it, so binding that session to this engine keeps the
    whole path isolated — no global monkeypatching needed.
    """
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    yield eng


def _seed(eng, model_id, price_type, amounts, currency="EUR"):
    """Create one SKU+channel per amount; each SKU gets one price."""
    channels = []
    skus = []
    with Session(eng) as s:
        model = Model(id=model_id, marketing_code="RM" + model_id[-4:],
                      display_name="Redmi " + model_id[-4:],
                      brand="Xiaomi")
        s.add(model)
        for i, amt in enumerate(amounts):
            ch = Channel(id=str(uuid.uuid4()), name="ch%d" % i, country="FI",
                         type="market", crawl_mode="static", enabled=True,
                         base_url="https://x")
            from app.models.catalog import Sku
            sku = Sku(id=str(uuid.uuid4()), model_id=model_id, channel_id=ch.id,
                      product_url="https://x/%d" % i)
            s.add(ch)
            s.add(sku)
            channels.append(ch)
            skus.append(sku)
        s.commit()
        for i, amt in enumerate(amounts):
            prepo.add_price(
                s, skus[i].id, channels[i].id, price_type, float(amt),
                currency, float(amt), True, meta=None,
            )
        s.commit()
        last_sku_id = skus[-1].id
        last_ch_id = channels[-1].id
    # (sku_id, channel_id, model_id) of the LAST sku so the test can re-price it
    return last_sku_id, last_ch_id, model_id


def test_outlier_18x_is_flagged(db, monkeypatch):
    """A1 Croatia / Redmi 15C: €2615 vs €143 median = 18.3x -> flagged."""
    monkeypatch.setattr(
        "app.services.prices.OUTLIER_MIN_SAMPLES", 5
    )
    model_id = "model-" + uuid.uuid4().hex[:6]
    sku_id, ch_id, mid = _seed(
        db, model_id, "subsidy_down_payment",
        [143.0, 143.0, 143.0, 143.0, 2615.0],
    )
    with Session(db) as s:
        p = prices_svc.record_price(
            s, sku_id, ch_id, "subsidy_down_payment", 2615.0, "EUR",
            in_stock=True, evaluate=False, model_id=mid,
        )
        assert p.flag is not None
        assert "cross_channel_outlier" in p.flag


def test_legal_subsidy_0_35x_not_flagged(db, monkeypatch):
    """0.35x the median is a real operator subsidy (Yettel HU / Telemach
    pattern), must NOT be flagged. All five at 143 (= median), re-price one at
    0.35x to prove the lower bound 0.25 is not triggered."""
    monkeypatch.setattr(
        "app.services.prices.OUTLIER_MIN_SAMPLES", 5
    )
    model_id = "model-" + uuid.uuid4().hex[:6]
    sku_id, ch_id, mid = _seed(
        db, model_id, "subsidy_down_payment",
        [143.0, 143.0, 143.0, 143.0, 143.0],
    )
    with Session(db) as s:
        p = prices_svc.record_price(
            s, sku_id, ch_id, "subsidy_down_payment",
            round(143.0 * 0.35, 2), "EUR", in_stock=True, evaluate=False,
            model_id=mid,
        )
        assert p.flag is None or "cross_channel_outlier" not in (p.flag or "")


def test_deep_subsidy_0_16x_not_flagged(db, monkeypatch):
    """Yettel HU / DemoBrand 600 regression: a 69% loyalty discount (list 253 990
    Ft, -175 000 Ft -> 28 990 Ft = €72 against a ~€450 cross-channel median,
    0.16x) is a REAL promotion, not a parse error. Subsidy price types must not
    be flagged on the LOW side (only `unlocked` is)."""
    monkeypatch.setattr(
        "app.services.prices.OUTLIER_MIN_SAMPLES", 5
    )
    model_id = "model-" + uuid.uuid4().hex[:6]
    sku_id, ch_id, mid = _seed(
        db, model_id, "subsidy_down_payment",
        [450.0, 450.0, 450.0, 450.0, 450.0],
    )
    with Session(db) as s:
        p = prices_svc.record_price(
            s, sku_id, ch_id, "subsidy_down_payment", 72.48, "EUR",
            in_stock=True, evaluate=False, model_id=mid,
            original_price=634.98,
        )
        assert "cross_channel_outlier" not in (p.flag or "")


def test_unlocked_low_side_still_flagged(db, monkeypatch):
    """An open-market price at 0.22x the cross-channel median is still a genuine
    anomaly (retailers cannot sell 78% below the market). The LO guard must stay
    armed for `unlocked` — only subsidy types are exempt. 100 EUR stays inside
    the (80, 4000) plausibility band."""
    monkeypatch.setattr(
        "app.services.prices.OUTLIER_MIN_SAMPLES", 5
    )
    model_id = "model-" + uuid.uuid4().hex[:6]
    sku_id, ch_id, mid = _seed(
        db, model_id, "unlocked",
        [450.0, 450.0, 450.0, 450.0, 450.0],
    )
    with Session(db) as s:
        p = prices_svc.record_price(
            s, sku_id, ch_id, "unlocked", 100.0, "EUR",
            in_stock=True, evaluate=False, model_id=mid,
        )
        assert "cross_channel_outlier" in (p.flag or "")


def test_few_samples_not_flagged(db, monkeypatch):
    """Cold-start channel: 4 samples < OUTLIER_MIN_SAMPLES(5) -> the median is
    not even consulted, an 18x spread is NOT flagged."""
    monkeypatch.setattr(
        "app.services.prices.OUTLIER_MIN_SAMPLES", 5
    )
    model_id = "model-" + uuid.uuid4().hex[:6]
    sku_id, ch_id, mid = _seed(
        db, model_id, "subsidy_down_payment",
        [143.0, 143.0, 143.0, 2615.0],  # only 4 samples
    )
    with Session(db) as s:
        p = prices_svc.record_price(
            s, sku_id, ch_id, "subsidy_down_payment", 2615.0, "EUR",
            in_stock=True, evaluate=False, model_id=mid,
        )
        assert "cross_channel_outlier" not in (p.flag or "")


def test_bundle_zero_not_double_flagged(db, monkeypatch):
    """A legitimate bundle 0 (price 0, original > 0, source operator_pdp) must
    be tagged `bundle_only` but NOT `cross_channel_outlier` (its ratio is 0,
    excluded by the amount_eur > 0 guard)."""
    monkeypatch.setattr(
        "app.services.prices.OUTLIER_MIN_SAMPLES", 5
    )
    model_id = "model-" + uuid.uuid4().hex[:6]
    sku_id, ch_id, mid = _seed(
        db, model_id, "subsidy_down_payment",
        [143.0, 143.0, 143.0, 143.0, 143.0],
    )
    with Session(db) as s:
        p = prices_svc.record_price(
            s, sku_id, ch_id, "subsidy_down_payment", 0.0, "EUR",
            in_stock=True, evaluate=False, model_id=mid,
            original_price=999.0,
            meta={"source": "operator_pdp", "product_name": "Redmi X"},
        )
        assert "bundle_only" in (p.flag or "")
        assert "cross_channel_outlier" not in (p.flag or "")


def test_compute_price_flag_pure():
    """Unit check of the pure function (no DB) for the deviance math."""
    from app.services.price_audit import compute_price_flag

    # 18.3x over a 143 median -> flag
    f = compute_price_flag(
        price=2615.0, original_price=None, gift=None, meta=None,
        currency="EUR", amount_eur=2615.0, model_display_name="Redmi",
        model_median_eur=143.0,
    )
    assert "cross_channel_outlier" in f

    # 0.35x -> no flag (within the loose lower bound)
    f2 = compute_price_flag(
        price=50.0, original_price=None, gift=None, meta=None,
        currency="EUR", amount_eur=50.0, model_display_name="Redmi",
        model_median_eur=143.0,
    )
    assert "cross_channel_outlier" not in (f2 or "")

    # bundle 0 with median present -> bundle_only, never cross_channel_outlier
    f3 = compute_price_flag(
        price=0.0, original_price=999.0, gift=None,
        meta={"source": "operator_pdp"}, currency="EUR", amount_eur=0.0,
        model_display_name="Redmi", model_median_eur=143.0,
    )
    assert "bundle_only" in (f3 or "")
    assert "cross_channel_outlier" not in (f3 or "")
