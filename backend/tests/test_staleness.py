"""Freshness & coverage monitoring (MED-2).

Exercises ``compute_staleness`` against an isolated in-memory SQLite DB.
The production ``price_monitor.db`` is never touched.
"""
from datetime import datetime, timezone, timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine, select
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401  (register every model on the metadata)
from app.core.config import CRAWL_STALE_DAYS
from app.models.catalog import Sku
from app.models.channel import Channel
from app.models.price import Price
from app.models.ops import CrawlRun
from app.services.staleness import compute_staleness


@pytest.fixture
def db():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(eng)
    yield eng


def _seed_price(eng, ch_name, sku_suffix, captured_at_iso, amount=100.0):
    with Session(eng) as s:
        ch = s.exec(select(Channel).where(Channel.name == ch_name)).first()
        if ch is None:
            ch = Channel(id="ch-" + ch_name, name=ch_name, type="market", country="Finland")
            s.add(ch)
            s.commit()
            s.refresh(ch)
        sku = Sku(
            id=f"sku-{ch_name}-{sku_suffix}",
            channel_id=ch.id,
            model_id="m1",
            product_url="",
        )
        s.add(sku)
        s.commit()
        s.refresh(sku)
        s.add(
            Price(
                sku_id=sku.id,
                channel_id=ch.id,
                price_type="unlocked",
                price=amount,
                currency="EUR",
                amount_eur=amount,
                captured_at=captured_at_iso,
                in_stock=True,
            )
        )
        s.add(CrawlRun(channel_id=ch.id, started_at=captured_at_iso, status="success", items=1))
        s.commit()


def test_staleness_flags_old_prices(db):
    now = datetime.now(timezone.utc)
    fresh = (now - timedelta(hours=1)).isoformat()
    old = (now - timedelta(days=CRAWL_STALE_DAYS + 3)).isoformat()
    _seed_price(db, "FreshShop", "a", fresh)
    _seed_price(db, "StaleShop", "b", old)  # 该渠道唯一 SKU 已陈旧

    with Session(db) as s:
        data = compute_staleness(s)

    fresh_row = next(c for c in data["channels"] if c["channel"] == "FreshShop")
    stale_row = next(c for c in data["channels"] if c["channel"] == "StaleShop")
    assert fresh_row["stale_skus"] == 0 and fresh_row["status"] == "ok"
    assert stale_row["stale_skus"] == 1 and stale_row["status"] == "stale"
    assert data["summary"]["stale_skus"] == 1
    assert data["summary"]["problem_channels"] == 1


def test_staleness_coverage(db):
    now = datetime.now(timezone.utc)
    iso = (now - timedelta(hours=1)).isoformat()
    with Session(db) as s:
        ch = Channel(id="ch-cov", name="CovShop", type="market", country="Finland")
        s.add(ch)
        s.commit()
        s.add(Sku(id="sku-cov-1", channel_id=ch.id, model_id="m1"))
        s.add(Sku(id="sku-cov-2", channel_id=ch.id, model_id="m1"))
        s.add(
            Price(
                sku_id="sku-cov-1",
                channel_id=ch.id,
                price_type="unlocked",
                price=100.0,
                currency="EUR",
                amount_eur=100.0,
                captured_at=iso,
                in_stock=True,
            )
        )
        s.commit()

    with Session(db) as s:
        data = compute_staleness(s)

    row = next(c for c in data["channels"] if c["channel"] == "CovShop")
    assert row["total_skus"] == 2
    assert row["priced_skus"] == 1
    assert row["coverage_pct"] == 50.0
