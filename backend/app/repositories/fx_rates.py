from sqlmodel import Session, select

from app.models.price import FxRate


def get_latest_rate(session: Session, currency: str, as_of=None):
    stmt = select(FxRate).where(FxRate.currency == currency)
    if as_of:
        stmt = stmt.where(FxRate.date <= as_of)
    stmt = stmt.order_by(FxRate.date.desc())
    r = session.exec(stmt).first()
    return r.rate_to_eur if r else None


def list_rates(session: Session):
    stmt = select(FxRate).order_by(FxRate.date.desc(), FxRate.currency)
    return [r.model_dump() for r in session.exec(stmt).all()]


def upsert_rate(session: Session, date: str, currency: str, rate_to_eur: float):
    existing = session.exec(
        select(FxRate).where(FxRate.date == date, FxRate.currency == currency)
    ).first()
    if existing:
        existing.rate_to_eur = rate_to_eur
    else:
        session.add(FxRate(date=date, currency=currency, rate_to_eur=rate_to_eur))
    session.flush()
