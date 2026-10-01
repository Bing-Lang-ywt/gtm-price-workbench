"""P2-12: operator contract term is read per-channel from
``Channel.contract_term_len`` (default 24) instead of the old global
``TERM_MONTHS = 24`` constant.

The derivation ``subsidy_down_payment = contract_monthly x term`` must scale
with the channel setting. We exercise the real ``derive_operator_device_totals``
on an in-memory SQLite DB (no real DB, no network, no browser) and assert the
derived total matches ``monthly x term`` for term = 24, 36, and None(fallback).

Per the audit's "additive nullable column" rule the DB column already exists
(ALTER applied by team-lead); this test only proves the code path honours it.

Run: python -m pytest tests/test_p2_twelve.py -q
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import SQLModel, Session, create_engine, select  # noqa: E402

from app.models.catalog import Model, Sku  # noqa: E402
from app.models.channel import Channel  # noqa: E402
from app.models.price import Price  # noqa: E402
from app.services.operator_device_total import (  # noqa: E402
    derive_operator_device_totals,
)


def _make_engine_and_channel(term):
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        ch = Channel(
            id=str(uuid.uuid4()),
            country="Hungary",
            name="TestOp",
            type="operator",
            contract_term_months=term,
        )
        s.add(ch)
        s.commit()
        ch_id = ch.id
    return engine, ch_id


def _seed_and_derive(engine, ch_id, monthly_eur, currency="EUR"):
    sku_id = None
    with Session(engine) as s:
        ch = s.get(Channel, ch_id)
        model = Model(id=str(uuid.uuid4()), marketing_code="X", display_name="X")
        s.add(model)
        s.commit()
        sku = Sku(id=str(uuid.uuid4()), model_id=model.id, channel_id=ch.id)
        s.add(sku)
        s.commit()
        s.add(
            Price(
                sku_id=sku.id,
                channel_id=ch.id,
                price_type="contract_monthly",
                price=monthly_eur,
                currency=currency,
                amount_eur=monthly_eur,
                in_stock=True,
            )
        )
        s.commit()
        sku_id = sku.id
    with Session(engine) as s:
        ch = s.get(Channel, ch_id)
        n = derive_operator_device_totals(s, ch)
        s.commit()
        rows = s.exec(
            select(Price).where(
                Price.sku_id == sku_id,
                Price.price_type == "subsidy_down_payment",
            )
        ).all()
        return n, rows


def test_term_24_default_derives_monthly_x24():
    engine, ch_id = _make_engine_and_channel(24)
    n, rows = _seed_and_derive(engine, ch_id, 20.0)
    assert n == 1
    assert len(rows) == 1
    assert rows[0].amount_eur == 480.0  # 20 * 24


def test_term_36_uses_channel_setting():
    engine, ch_id = _make_engine_and_channel(36)
    n, rows = _seed_and_derive(engine, ch_id, 20.0)
    assert n == 1
    assert rows[0].amount_eur == 720.0  # 20 * 36


def test_term_none_falls_back_to_24():
    engine, ch_id = _make_engine_and_channel(None)
    n, rows = _seed_and_derive(engine, ch_id, 20.0)
    assert n == 1
    assert rows[0].amount_eur == 480.0  # None -> default 24


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
