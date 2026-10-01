from sqlmodel import Session, select

from app.models.catalog import Model
from app.models.channel import Channel


def load_maps(session: Session):
    """Load id->dict maps for models and channels (used to enrich responses)."""
    models = session.exec(select(Model)).all()
    channels = session.exec(select(Channel)).all()
    return {m.id: m.model_dump() for m in models}, {c.id: c.model_dump() for c in channels}
