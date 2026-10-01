"""AlertRule evaluation engine.

The CRUD layer and the ``AlertRule`` model already existed, but nothing
consumed the rules at ingest time. This module closes that gap: whenever a
price is recorded, active ``AlertRule`` rows (scoped by ``all`` / ``channel``
/ ``model`` / ``sku`` and filtered by ``price_type``) are evaluated for the
``below`` / ``above`` / ``new_entry`` conditions and an :class:`Alert` is
emitted + notified.

This is the "price reasonableness" guard. The seeded defaults flag any
``subsidy_down_payment`` below 80 EUR (the classic monthly-installment stored
as device price) or above 2500 EUR -- directly encoding the EUR plausibility
band as an auto-alert.
"""

import logging
from datetime import datetime

from sqlmodel import Session, select

from app.alerting.notifier import notify
from app.models.catalog import Sku
from app.models.channel import Channel
from app.models.ops import Alert, AlertRule
from app.models.price import Price

log = logging.getLogger("alerting.rule_engine")

CONDITION_ALERT_TYPE = {
    "below": "rule_below",
    "above": "rule_above",
    "new_entry": "rule_new_entry",
    "delta_pct": "rule_delta_pct",
}


def _previous_price(session: Session, sku_id: str, price_type: str):
    """Return the price captured *before* the latest one for this (sku, price_type)."""
    from app.models.price import Price

    stmt = (
        select(Price)
        .where(Price.sku_id == sku_id, Price.price_type == price_type)
        .order_by(Price.captured_at.desc())
    )
    rows = session.exec(stmt).all()
    return rows[1] if len(rows) > 1 else None


def _legacy_scope_matches(rule: AlertRule, sku: Sku, channel: Channel) -> bool:
    scope = rule.scope_type
    sid = (rule.scope_id or "").strip()
    if scope == "all":
        return True
    if scope == "channel":
        return sid == str(channel.id)
    if scope == "model":
        return sid == str(sku.model_id)
    if scope == "sku":
        return sid == str(sku.id)
    # segment without a concrete id => treat as global
    if scope == "segment":
        return sid == ""
    return False


def _rule_matches(rule: AlertRule, sku: Sku, channel: Channel, price_type: str) -> bool:
    if not rule.is_active:
        return False
    if rule.price_type is not None and rule.price_type != price_type:
        return False
    # 复合维度（精确绑定）：任一字段被设置时必须精确匹配。
    if rule.channel_id and rule.channel_id != str(channel.id):
        return False
    if rule.model_id and rule.model_id != str(sku.model_id):
        return False
    if rule.sku_id and rule.sku_id != str(sku.id):
        return False
    # 使用了复合维度则不再退回旧单一作用域；否则兼容历史规则。
    if rule.channel_id or rule.model_id or rule.sku_id:
        return True
    return _legacy_scope_matches(rule, sku, channel)


def _has_pending(session: Session, sku_id: str, price_type: str, atype: str) -> bool:
    """Avoid spamming duplicate alerts for a chronically-bad price: skip if a
    still-open (pending) alert of the same kind already exists."""
    existing = session.exec(
        select(Alert).where(
            Alert.sku_id == sku_id,
            Alert.type == atype,
            Alert.status == "pending",
        )
    ).first()
    return existing is not None


def _build_message(cond, threshold, amount_eur, currency, channel, sku, price_type, before=0.0):
    if cond == "below":
        cmp_txt = f"< {threshold:g} EUR"
    elif cond == "above":
        cmp_txt = f"> {threshold:g} EUR"
    elif cond == "delta_pct":
        delta = ((amount_eur - before) / before * 100.0) if before else 0.0
        cmp_txt = f"|Δ| ≥ {threshold:g}% (实测 {delta:+.1f}%，{before:.2f}→{amount_eur:.2f})"
    else:
        cmp_txt = "first observed"
    return (
        f"[{cond}] {channel.name} / sku={sku.id} {price_type} = "
        f"{amount_eur:.2f} {currency} ({cmp_txt})"
    )


def evaluate_rules_for_price(
    session: Session,
    sku: Sku,
    channel: Channel,
    price_type: str,
    amount_eur: float,
    currency: str,
) -> int:
    """Evaluate active AlertRules against a freshly recorded price.

    Returns the number of alerts created. Safe to call on every price insert;
    only ``below`` / ``above`` / ``new_entry`` conditions are handled here.
    (Delta change detection is covered by the legacy evaluator.)
    """
    rules = session.exec(select(AlertRule).where(AlertRule.is_active == True)).all()  # noqa: E712
    if not rules:
        return 0

    created = 0
    for rule in rules:
        if not _rule_matches(rule, sku, channel, price_type):
            continue
        cond = rule.condition_type
        thr = rule.threshold
        fire = False
        before_val = 0.0
        if cond == "below":
            fire = thr is not None and amount_eur < thr
        elif cond == "above":
            fire = thr is not None and amount_eur > thr
        elif cond == "delta_pct":
            # 价格变动超阈值：与上一笔同 (sku, price_type) 抓取对比，涨跌幅绝对值达阈值即触发。
            prev = _previous_price(session, sku.id, price_type)
            if prev is not None and prev.amount_eur > 0:
                before_val = round(float(prev.amount_eur), 2)
                delta_pct = (amount_eur - prev.amount_eur) / prev.amount_eur * 100.0
                fire = thr is not None and abs(delta_pct) >= thr
        elif cond == "new_entry":
            # the just-recorded price is already in the table; if it is the only
            # one of this (sku, price_type), it is the first ever observed.
            cnt = session.exec(
                select(Price).where(
                    Price.sku_id == sku.id, Price.price_type == price_type
                )
            ).all()
            fire = len(cnt) <= 1
        else:
            continue

        if not fire:
            continue
        atype = CONDITION_ALERT_TYPE.get(cond)
        if atype is None:
            continue
        if _has_pending(session, sku.id, price_type, atype):
            continue

        alert = Alert(
            sku_id=sku.id,
            type=atype,
            before=before_val,
            after=round(float(amount_eur), 2),
            currency=currency,
            threshold_pct=float(thr) if thr is not None else 0.0,
            triggered_at=datetime.utcnow().isoformat(),
            status="pending",
            notify_target="",
            message=_build_message(cond, thr, amount_eur, currency, channel, sku, price_type, before_val),
        )
        session.add(alert)
        session.flush()
        notify(alert)
        created += 1
    return created
