from app.repositories import alerts as arepo
from app.repositories.base import page_meta


def list_alerts_service(session, type, status, sku_id, page, limit):
    items, total = arepo.list_alerts(
        session, type=type, status=status, sku_id=sku_id, page=page, limit=limit
    )
    return {"items": items, "meta": page_meta(total, page, limit)}


def get_alert_service(session, alert_id):
    # repository.get_alert 已返回富化后的 dict（含 model/channel/country_code）。
    return arepo.get_alert(session, alert_id)


def create_alert_service(session, payload):
    a = arepo.create_alert(session, **payload)
    return a.model_dump()


def update_alert_service(session, alert_id, payload):
    a = arepo.get_alert_obj(session, alert_id)
    if not a:
        return None
    a = arepo.update_alert(session, a, **payload)
    return a.model_dump()


def delete_alert_service(session, alert_id):
    a = arepo.get_alert_obj(session, alert_id)
    if not a:
        return False
    arepo.delete_alert(session, a)
    return True
