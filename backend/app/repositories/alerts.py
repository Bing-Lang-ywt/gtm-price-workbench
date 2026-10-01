from sqlmodel import Session, select

from app.models.ops import Alert
from app.models.catalog import Sku, Model
from app.models.channel import Channel
from app.repositories.base import paged

# 国家名 → 二字码（Channel.country 存的是国家名，如 "Hungary"；
# 前端 AlertEvent.country_code 需要二字码以配对 CountryBadge）。
COUNTRY_CODE = {
    "Serbia": "RS",
    "Croatia": "HR",
    "Hungary": "HU",
    "Romania": "RO",
    "Bulgaria": "BG",
    "Poland": "PL",
    "Finland": "FI",
    "Czech Republic": "CZ",
}


def _enrich(alert: Alert, model_name, model_id, channel_name, channel_id, country):
    """把 Alert 原始行富化为带有机型名/渠道名/国家码的事件字典。

    机型名等来自 sku→model/channel 连表，缺失时（SKU 已被删）留 None，
    前端会回落到占位文案，绝不臆造机型。
    """
    d = alert.model_dump()
    d["model"] = model_name
    d["model_id"] = model_id
    d["channel"] = channel_name
    d["channel_id"] = channel_id
    d["country"] = country
    d["country_code"] = COUNTRY_CODE.get(country) if country else None
    return d


def list_alerts(session: Session, type=None, status=None, sku_id=None, page=1, limit=20):
    stmt = (
        select(
            Alert,
            Model.display_name,
            Model.id,
            Channel.name,
            Channel.id,
            Channel.country,
        )
        .join(Sku, Sku.id == Alert.sku_id, isouter=True)
        .join(Model, Model.id == Sku.model_id, isouter=True)
        .join(Channel, Channel.id == Sku.channel_id, isouter=True)
    )
    if type:
        stmt = stmt.where(Alert.type == type)
    if status:
        stmt = stmt.where(Alert.status == status)
    if sku_id:
        stmt = stmt.where(Alert.sku_id == sku_id)
    stmt = stmt.order_by(Alert.triggered_at.desc())
    rows, total = paged(session, stmt, page, limit)
    return [
        _enrich(a, mname, mid, cname, cid, country)
        for a, mname, mid, cname, cid, country in rows
    ], total


def get_alert(session: Session, alert_id: str):
    row = session.exec(
        select(
            Alert,
            Model.display_name,
            Model.id,
            Channel.name,
            Channel.id,
            Channel.country,
        )
        .join(Sku, Sku.id == Alert.sku_id, isouter=True)
        .join(Model, Model.id == Sku.model_id, isouter=True)
        .join(Channel, Channel.id == Sku.channel_id, isouter=True)
        .where(Alert.id == alert_id)
    ).first()
    if not row:
        return None
    a, mname, mid, cname, cid, country = row
    return _enrich(a, mname, mid, cname, cid, country)


def get_alert_obj(session: Session, alert_id: str):
    """写路径（update/delete）专用：返回原始 Alert ORM 对象。"""
    return session.get(Alert, alert_id)


def create_alert(session: Session, **kwargs):
    a = Alert(**kwargs)
    session.add(a)
    session.flush()
    return a


def update_alert(session: Session, alert: Alert, **kwargs):
    for k, v in kwargs.items():
        if v is not None:
            setattr(alert, k, v)
    session.add(alert)
    session.flush()
    return alert


def delete_alert(session: Session, alert: Alert):
    session.delete(alert)
    session.flush()
