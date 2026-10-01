from sqlmodel import Session, select

from app.models.ops import Feedback
from app.repositories.base import paged


def list_feedbacks(session: Session, page: int = 1, limit: int = 50):
    stmt = select(Feedback).order_by(Feedback.created_at.desc())
    rows, total = paged(session, stmt, page, limit)
    return [r.model_dump() for r in rows], total


def get_feedback(session: Session, feedback_id: str):
    return session.get(Feedback, feedback_id)


def create_feedback(session: Session, **kwargs):
    f = Feedback(**kwargs)
    session.add(f)
    session.flush()
    return f


def delete_feedback(session: Session, feedback: Feedback):
    session.delete(feedback)
    session.flush()
