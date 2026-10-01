from app.services.alert_rules import (
    InvalidRuleError,
    create_alert_rule_service,
    delete_alert_rule_service,
    get_alert_rule_service,
    list_alert_rules_service,
    update_alert_rule_service,
)


def list_controller(session, scope_type, is_active, page, limit):
    return list_alert_rules_service(session, scope_type, is_active, page, limit)


def get_controller(session, rule_id):
    return get_alert_rule_service(session, rule_id)


def create_controller(session, payload):
    return create_alert_rule_service(session, payload)


def update_controller(session, rule_id, payload):
    return update_alert_rule_service(session, rule_id, payload)


def delete_controller(session, rule_id):
    return delete_alert_rule_service(session, rule_id)
