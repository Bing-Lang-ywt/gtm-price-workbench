from sqlmodel import Session, select

from app.core.time import utcnow
from app.models.ops import AlertRule
from app.repositories.base import paged


def list_alert_rules(
    session: Session,
    scope_type: str = None,
    is_active: bool = None,
    page: int = 1,
    limit: int = 20,
):
    stmt = select(AlertRule)
    if scope_type:
        stmt = stmt.where(AlertRule.scope_type == scope_type)
    if is_active is not None:
        stmt = stmt.where(AlertRule.is_active == is_active)
    stmt = stmt.order_by(AlertRule.created_at.desc())
    rows, total = paged(session, stmt, page, limit)
    return [r.model_dump() for r in rows], total


def get_alert_rule(session: Session, rule_id: str):
    return session.get(AlertRule, rule_id)


def create_alert_rule(session: Session, **kwargs):
    r = AlertRule(**kwargs)
    session.add(r)
    session.flush()
    return r


def update_alert_rule(session: Session, rule: AlertRule, **kwargs):
    for k, v in kwargs.items():
        if v is not None:
            setattr(rule, k, v)
    rule.updated_at = utcnow().isoformat()
    session.add(rule)
    session.flush()
    return rule


def delete_alert_rule(session: Session, rule: AlertRule):
    session.delete(rule)
    session.flush()
