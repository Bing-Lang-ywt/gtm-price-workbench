import json

from sqlmodel import Session, select, func

from app.models.catalog import Sku
from app.models.channel import Channel
from app.models.price import Price
from app.repositories.base import paged


class PlausibilityError(ValueError):
    """Raised by add_price when the proposed (price, currency, price_type)
    falls outside the per-(currency, price_type) plausibility band. The error
    message carries enough context for the caller (crawler / manual price /
    cron) to log and surface without re-resolving the band themselves.
    """


def _installment_sig(meta) -> str | None:
    """meta 里只有 ``installment`` 需要参与去重比较。

    其余键（url / fetched_at / product_name…）每次抓取都可能微变，整体参与比较
    会让每次抓取都插一行，price 表就从「变更日志」退化成「快照流水」。
    但 installment 完全不参与也有坑：修好分期抽取器后若价格没变 → 不落新行 →
    旧的假分期会一直挂在「最新行」上（2026-09-03 Telekom HT 实测：
    机身尺寸误读出的 75.0×15 反复重抓也清不掉）。
    """
    if not meta:
        return None
    try:
        d = json.loads(meta) if isinstance(meta, str) else meta
    except (TypeError, ValueError):
        return None
    if not isinstance(d, dict):
        return None
    inst = d.get("installment")
    if not inst:
        return None
    return json.dumps(inst, sort_keys=True, ensure_ascii=False)


def count_samples(session: Session, model_id: str, price_type: str) -> int:
    """Number of DISTINCT SKUs carrying at least one price of ``price_type``
    for ``model_id``. Used as the sample-size gate for the cross-channel
    outlier guard — too few peers means the median is meaningless. One query.
    """
    stmt = (
        select(func.count(func.distinct(Price.sku_id)))
        .join(Sku, Sku.id == Price.sku_id)
        .where(Sku.model_id == model_id, Price.price_type == price_type)
    )
    return int(session.exec(stmt).one() or 0)


def add_price(
    session: Session,
    sku_id: str,
    channel_id: str,
    price_type: str,
    price: float,
    currency: str,
    amount_eur: float,
    in_stock: bool = True,
    captured_at=None,
    meta: str | None = None,
    original_price: float | None = None,
    gift: str | None = None,
    flag: str | None = None,
):
    # Hard write-path guard: reject prices that can't possibly be a handset
    # figure for (currency, price_type). price_audit stamps a *soft* flag on
    # the row when something looks off; here we refuse the row entirely so
    # the front-end never sees a 99999-EUR / -1 sentinel. Backfill / manual
    # price paths get the same treatment — there is no "bypass" code path
    # by design. We re-raise as PlausibilityError (a ValueError subclass)
    # so callers can `except ValueError` if they don't care about the type.
    #
    # Exception: bundle-only offers legitimately carry ``price == 0`` with
    # ``original_price > 0`` (the device is free with a plan). We let those
    # through with ``allow_zero=True``; price_audit stamps ``bundle_only``
    # flag so downstream consumers treat them correctly. A naked zero
    # without original_price is still rejected as a sentinel.
    from app.crawling.currency import is_plausible_for, PLAUSIBLE_BANDS_BY_TYPE

    is_bundle_zero = (
        price == 0 and original_price is not None and original_price > 0
    )
    if not is_plausible_for(
        price, currency, price_type, allow_zero=is_bundle_zero
    ):
        band = PLAUSIBLE_BANDS_BY_TYPE.get((currency or "", price_type or ""))
        band_str = f"{band}" if band else "no-band"
        raise PlausibilityError(
            f"price {price} {currency} for price_type={price_type!r} rejected: "
            f"outside plausibility band {band_str}. Likely scraper mis-parse "
            f"(wrong field grabbed) or sentinels like 0/99999."
        )

    # Upsert-style dedup: if the most recent existing price for this
    # (sku, channel, price_type) is identical in value + currency + stock +
    # strikethrough + gift + flag, skip appending a duplicate row. This keeps
    # the price table a clean change-log (one row per actual price change)
    # instead of bloating it with identical snapshots from repeated crawls.
    # The matrix only ever reads the latest snapshot, so behaviour is unchanged.
    latest = session.exec(
        select(Price)
        .where(
            Price.sku_id == sku_id,
            Price.channel_id == channel_id,
            Price.price_type == price_type,
        )
        .order_by(Price.captured_at.desc())
    ).first()
    if (
        latest is not None
        and latest.currency == currency
        and latest.price == price
        and latest.amount_eur == amount_eur
        and latest.in_stock == in_stock
        and latest.original_price == original_price
        and latest.gift == gift
        and latest.flag == flag
        # 分期方案变了就算一次变更：只比 installment，不比整个 meta。
        and _installment_sig(latest.meta) == _installment_sig(meta)
    ):
        return latest
    p = Price(
        sku_id=sku_id,
        channel_id=channel_id,
        price_type=price_type,
        price=price,
        currency=currency,
        amount_eur=amount_eur,
        original_price=original_price,
        gift=gift,
        flag=flag,
        in_stock=in_stock,
        captured_at=captured_at,
        meta=meta,
    )
    session.add(p)
    session.flush()
    return p


def get_skus_for_filter(session: Session, country=None, channel_id=None, model_id=None):
    stmt = select(Sku).join(Channel, Sku.channel_id == Channel.id)
    if country:
        stmt = stmt.where(Channel.country == country)
    if channel_id:
        stmt = stmt.where(Sku.channel_id == channel_id)
    if model_id:
        stmt = stmt.where(Sku.model_id == model_id)
    return session.exec(stmt).all()


def _is_manual(price) -> bool:
    if not getattr(price, "meta", None):
        return False
    try:
        m = json.loads(price.meta) if isinstance(price.meta, str) else price.meta
        return (m or {}).get("source") == "manual"
    except Exception:
        return False


def latest_snapshot(session: Session, sku_ids: list):
    """Return {(sku_id, price_type): Price} keeping the most recent capture per key.

    人工改价（meta.source='manual'）拥有最高优先级：一旦某 (sku, price_type)
    存在人工价，即便次日爬虫重新抓到价，也始终采用人工价——除非用户再次手动修改。
    否则按 captured_at 取最新一条。
    """
    if not sku_ids:
        return {}
    stmt = (
        select(Price)
        .where(Price.sku_id.in_(sku_ids))
        .order_by(Price.captured_at.desc())
    )
    latest = {}
    for p in session.exec(stmt).all():
        key = (p.sku_id, p.price_type)
        is_manual = _is_manual(p)
        ex = latest.get(key)
        if ex is None:
            latest[key] = p
            continue
        ex_manual = _is_manual(ex)
        if is_manual and not ex_manual:
            latest[key] = p
        elif is_manual == ex_manual and p.captured_at > ex.captured_at:
            latest[key] = p
    return latest


def latest_snapshot_as_of(session: Session, sku_ids: list, as_of_date: str, window_days: int = 14):
    """Return {(sku_id, price_type): Price} keeping the most recent capture whose
    captured_at falls within [as_of_date - window_days, as_of_date 23:59:59].

    Used by the calendar "see prices on this day" feature: anchors the snapshot to
    a chosen date instead of "now". Manual prices keep highest priority (same rule
    as latest_snapshot). captured_at is ISO (2026-08-12T10:13:06) so string
    comparison is chronological without datetime parsing.
    """
    if not sku_ids:
        return {}
    from datetime import date, timedelta

    try:
        ad = date.fromisoformat(as_of_date)
    except ValueError:
        ad = date.today()
    start = (ad - timedelta(days=max(0, int(window_days)))).isoformat()
    lo = start + "T00:00:00"
    hi = as_of_date + "T23:59:59.999999"
    stmt = (
        select(Price)
        .where(
            Price.sku_id.in_(sku_ids),
            Price.captured_at >= lo,
            Price.captured_at <= hi,
        )
        .order_by(Price.captured_at.desc())
    )
    latest = {}
    for p in session.exec(stmt).all():
        key = (p.sku_id, p.price_type)
        is_manual = _is_manual(p)
        ex = latest.get(key)
        if ex is None:
            latest[key] = p
            continue
        ex_manual = _is_manual(ex)
        if is_manual and not ex_manual:
            latest[key] = p
        elif is_manual == ex_manual and p.captured_at > ex.captured_at:
            latest[key] = p
    return latest


def price_history(
    session: Session,
    sku_id=None,
    channel_id=None,
    price_type=None,
    from_=None,
    to=None,
    page=1,
    limit=100,
):
    stmt = select(Price)
    if sku_id:
        stmt = stmt.where(Price.sku_id == sku_id)
    if channel_id:
        stmt = stmt.where(Price.channel_id == channel_id)
    if price_type:
        stmt = stmt.where(Price.price_type == price_type)
    if from_:
        from datetime import datetime

        try:
            stmt = stmt.where(Price.captured_at >= datetime.fromisoformat(from_))
        except ValueError:
            pass
    if to:
        from datetime import datetime

        try:
            stmt = stmt.where(Price.captured_at <= datetime.fromisoformat(to))
        except ValueError:
            pass
    stmt = stmt.order_by(Price.captured_at.desc())
    rows, total = paged(session, stmt, page, limit)
    return [r.model_dump() for r in rows], total
