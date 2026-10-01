import logging
from datetime import datetime

from sqlmodel import Session, select

from app.core.config import ALERT_DROP_THRESHOLD_PCT
from app.alerting.notifier import notify
from app.models.catalog import Sku
from app.models.ops import Alert
from app.models.price import Price

log = logging.getLogger("alerting.evaluator")


def evaluate_price_change(
    session: Session,
    sku_id: str,
    price_type: str,
    amount_eur: float,
    currency: str,
    exclude_id=None,
):
    """Compare a new price to the previous capture and emit a drop/rise alert."""
    prev = _previous_price(session, sku_id, price_type, exclude_id)
    if prev is None or prev.amount_eur <= 0:
        return None
    delta_pct = (amount_eur - prev.amount_eur) / prev.amount_eur * 100.0
    if delta_pct <= -ALERT_DROP_THRESHOLD_PCT:
        return _create(
            session,
            sku_id,
            "price_drop",
            prev.amount_eur,
            amount_eur,
            currency,
            f"Price dropped {abs(delta_pct):.1f}% (threshold {ALERT_DROP_THRESHOLD_PCT:.0f}%)",
        )
    if delta_pct >= ALERT_DROP_THRESHOLD_PCT:
        return _create(
            session,
            sku_id,
            "price_up",
            prev.amount_eur,
            amount_eur,
            currency,
            f"Price rose {delta_pct:.1f}% (threshold {ALERT_DROP_THRESHOLD_PCT:.0f}%)",
        )
    return None


def evaluate_stock_change(session: Session, sku_id: str, in_stock: bool):
    """Emit a stock_out alert when a SKU leaves stock.

    NOTE: this used to pass a stray extra ``0`` (a leftover threshold_pct from
    before it moved into the Alert constructor), so every call raised
    ``TypeError: _create() takes 7 positional arguments but 8 were given``.
    The crawl loop catches that per SKU, which meant two silent regressions:
    no stock_out alert ever fired, AND the ``sku.in_stock = False`` write that
    follows this call in crawl.py never ran -- so a delisted / sold-out SKU kept
    showing in_stock=1 forever. Keyword args now pin the mapping.
    """
    if in_stock:
        return None
    return _create(
        session,
        sku_id,
        "stock_out",
        before=0,
        after=0,
        currency="",
        message="SKU transitioned to out of stock",
    )


def evaluate_all_skus(session: Session) -> int:
    """Backfill alerts by comparing the latest two captures per (sku, price_type)."""
    skus = session.exec(select(Sku)).all()
    created = 0
    for sku in skus:
        stmt = (
            select(Price)
            .where(Price.sku_id == sku.id)
            .order_by(Price.captured_at.desc())
        )
        rows = session.exec(stmt).all()
        by_type: dict = {}
        for p in rows:
            by_type.setdefault(p.price_type, []).append(p)
        for _pt, lst in by_type.items():
            if len(lst) < 2:
                continue
            latest, prev = lst[0], lst[1]
            if prev.amount_eur <= 0:
                continue
            delta_pct = (latest.amount_eur - prev.amount_eur) / prev.amount_eur * 100.0
            if delta_pct <= -ALERT_DROP_THRESHOLD_PCT:
                _create(
                    session,
                    sku.id,
                    "price_drop",
                    prev.amount_eur,
                    latest.amount_eur,
                    latest.currency,
                    f"Price dropped {abs(delta_pct):.1f}% (threshold {ALERT_DROP_THRESHOLD_PCT:.0f}%)",
                )
                created += 1
            elif delta_pct >= ALERT_DROP_THRESHOLD_PCT:
                _create(
                    session,
                    sku.id,
                    "price_up",
                    prev.amount_eur,
                    latest.amount_eur,
                    latest.currency,
                    f"Price rose {delta_pct:.1f}% (threshold {ALERT_DROP_THRESHOLD_PCT:.0f}%)",
                )
                created += 1
    session.commit()
    return created


def _previous_price(session: Session, sku_id: str, price_type: str, exclude_id):
    stmt = select(Price).where(
        Price.sku_id == sku_id, Price.price_type == price_type
    )
    if exclude_id:
        stmt = stmt.where(Price.id != exclude_id)
    stmt = stmt.order_by(Price.captured_at.desc())
    rows = session.exec(stmt).all()
    return rows[1] if len(rows) > 1 else None


def _create(
    session: Session,
    sku_id: str,
    atype: str,
    before: float,
    after: float,
    currency: str,
    message: str,
):
    alert = Alert(
        sku_id=sku_id,
        type=atype,
        before=before,
        after=after,
        currency=currency,
        threshold_pct=ALERT_DROP_THRESHOLD_PCT,
        message=message,
        status="pending",
        triggered_at=datetime.utcnow().isoformat(),
    )
    session.add(alert)
    session.flush()
    notify(alert)
    return alert
