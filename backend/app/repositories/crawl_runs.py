from datetime import datetime

from sqlmodel import Session, select

from app.models.ops import CrawlRun
from app.repositories.base import paged


def create_run(session: Session, channel_id: str, status="running"):
    run = CrawlRun(channel_id=channel_id, status=status)
    session.add(run)
    session.flush()
    return run


def update_run(
    session: Session,
    run: CrawlRun,
    status=None,
    items=None,
    error=None,
    finished=False,
):
    if status is not None:
        run.status = status
    if items is not None:
        run.items = items
    if error is not None:
        run.error = error
    if finished:
        run.finished_at = datetime.utcnow().isoformat()
    session.add(run)
    session.flush()
    return run


def list_by_channel(session: Session, channel_id: str, status=None, page=1, limit=20):
    stmt = select(CrawlRun).where(CrawlRun.channel_id == channel_id)
    if status:
        stmt = stmt.where(CrawlRun.status == status)
    stmt = stmt.order_by(CrawlRun.started_at.desc())
    rows, total = paged(session, stmt, page, limit)
    return [r.model_dump() for r in rows], total
