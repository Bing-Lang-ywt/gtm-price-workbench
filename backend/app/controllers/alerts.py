from app.services.alerts import (
    create_alert_service,
    delete_alert_service,
    get_alert_service,
    list_alerts_service,
    update_alert_service,
)


def list_controller(session, type, status, sku_id, page, limit):
    return list_alerts_service(session, type, status, sku_id, page, limit)


def get_controller(session, alert_id):
    return get_alert_service(session, alert_id)


def create_controller(session, payload):
    return create_alert_service(session, payload)


def update_controller(session, alert_id, payload):
    return update_alert_service(session, alert_id, payload)


def delete_controller(session, alert_id):
    return delete_alert_service(session, alert_id)
