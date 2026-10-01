from sqlmodel import Session, select

from app.core.time import utcnow
from app.models.catalog import Model, ModelAlias, ModelCompetitorMap, Sku
from app.models.channel import Channel
from app.repositories.base import paged

# (label, max EUR anchor). Used for same price-band competitor matching.
SEGMENT_BUCKETS = [
    ("lite", 300),
    ("mid", 500),
    ("upper_mid", 800),
    ("flagship", 10**12),
]


def segment_of(anchor: float) -> str:
    for label, cap in SEGMENT_BUCKETS:
        if anchor <= cap:
            return label
    return "flagship"


def list_models(session: Session, is_target=None):
    stmt = select(Model)
    if is_target is not None:
        stmt = stmt.where(Model.is_target == is_target)
    stmt = stmt.order_by(Model.price_band_anchor)
    return [m.model_dump() for m in session.exec(stmt).all()]


def get_model(session: Session, model_id: str):
    return session.get(Model, model_id)


def list_model_skus(session: Session, model_id: str):
    stmt = select(Sku).where(Sku.model_id == model_id)
    return [s.model_dump() for s in session.exec(stmt).all()]


def list_skus(
    session: Session,
    country=None,
    channel_id=None,
    model_id=None,
    segment_ids=None,
    active=None,
    page=1,
    limit=20,
):
    stmt = select(Sku).join(Channel, Sku.channel_id == Channel.id)
    if country:
        stmt = stmt.where(Channel.country == country)
    if channel_id:
        stmt = stmt.where(Sku.channel_id == channel_id)
    if model_id:
        stmt = stmt.where(Sku.model_id == model_id)
    if segment_ids is not None:
        stmt = stmt.where(Sku.model_id.in_(segment_ids))
    if active is not None:
        stmt = stmt.where(Sku.in_stock == active)
    stmt = stmt.order_by(Sku.created_at.desc())
    rows, total = paged(session, stmt, page, limit)
    return [r.model_dump() for r in rows], total


def get_sku(session: Session, sku_id: str):
    return session.get(Sku, sku_id)


def get_model_aliases(session: Session, model_id: str):
    stmt = select(ModelAlias).where(ModelAlias.model_id == model_id)
    return [a.model_dump() for a in session.exec(stmt).all()]


def update_model(session: Session, model: Model, **kwargs):
    for k, v in kwargs.items():
        if v is not None:
            setattr(model, k, v)
    model.updated_at = utcnow().isoformat()
    session.add(model)
    session.flush()
    return model


def list_competitor_mappings(session: Session):
    stmt = select(ModelCompetitorMap)
    rows = session.exec(stmt).all()
    return [r.model_dump() for r in rows]


def replace_model_aliases(session: Session, model_id: str, alias_strings: list[str]):
    """Upsert aliases by replacing the whole set for a model (delete-then-insert).

    Empty/duplicate/whitespace-only entries are dropped. Passing an empty list
    clears all aliases for the model.
    """
    existing = session.exec(
        select(ModelAlias).where(ModelAlias.model_id == model_id)
    ).all()
    for a in existing:
        session.delete(a)
    seen: set[str] = set()
    for raw in alias_strings:
        s = (raw or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        session.add(ModelAlias(model_id=model_id, alias=s))
    session.flush()
