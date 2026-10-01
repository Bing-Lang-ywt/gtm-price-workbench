from app.repositories import alert_rules as repo
from app.repositories.base import page_meta

ALLOWED_CONDITIONS = {"below", "above", "delta_pct", "new_entry"}
ALLOWED_SCOPES = {"model", "sku", "channel", "segment", "all"}
ALLOWED_PRICE_TYPES = {"unlocked", "contract_monthly", "subsidy_down_payment"}


class InvalidRuleError(ValueError):
    """Raised when an alert-rule payload violates business constraints."""


def _validate(payload: dict) -> None:
    scope = payload.get("scope_type")
    cond = payload.get("condition_type")
    ptype = payload.get("price_type")
    thr = payload.get("threshold")
    if scope is not None and scope not in ALLOWED_SCOPES:
        raise InvalidRuleError(f"scope_type must be one of {sorted(ALLOWED_SCOPES)}")
    if cond is not None and cond not in ALLOWED_CONDITIONS:
        raise InvalidRuleError(f"condition_type must be one of {sorted(ALLOWED_CONDITIONS)}")
    if ptype is not None and ptype not in ALLOWED_PRICE_TYPES:
        raise InvalidRuleError(f"price_type must be one of {sorted(ALLOWED_PRICE_TYPES)} or null")
    if cond is not None:
        # threshold is only valid for new_entry when it is null
        if cond == "new_entry" and thr is not None:
            raise InvalidRuleError("threshold must be null when condition_type is new_entry")
        if cond != "new_entry" and thr is None:
            raise InvalidRuleError("threshold is required when condition_type is not new_entry")


def list_alert_rules_service(session, scope_type=None, is_active=None, page=1, limit=20):
    items, total = repo.list_alert_rules(
        session, scope_type=scope_type, is_active=is_active, page=page, limit=limit
    )
    return {"items": items, "meta": page_meta(total, page, limit)}


def get_alert_rule_service(session, rule_id):
    r = repo.get_alert_rule(session, rule_id)
    return r.model_dump() if r else None


def create_alert_rule_service(session, payload):
    _validate(payload)
    r = repo.create_alert_rule(session, **payload)
    session.commit()
    session.refresh(r)
    return r.model_dump()


def update_alert_rule_service(session, rule_id, payload):
    r = repo.get_alert_rule(session, rule_id)
    if not r:
        return None
    # Validate the merged state so partial updates stay internally consistent.
    merged = {**r.model_dump(), **payload}
    _validate(merged)
    r = repo.update_alert_rule(session, r, **payload)
    session.commit()
    session.refresh(r)
    return r.model_dump()


def delete_alert_rule_service(session, rule_id):
    r = repo.get_alert_rule(session, rule_id)
    if not r:
        return False
    repo.delete_alert_rule(session, r)
    session.commit()
    return True
