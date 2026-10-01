from app.repositories import feedback as frepo
from app.repositories.base import page_meta


def list_feedbacks_service(session, page: int = 1, limit: int = 50):
    items, total = frepo.list_feedbacks(session, page=page, limit=limit)
    return {"items": items, "meta": page_meta(total, page, limit)}


def create_feedback_service(session, payload: dict):
    return frepo.create_feedback(session, **payload).model_dump()


def delete_feedback_service(session, feedback_id: str):
    f = frepo.get_feedback(session, feedback_id)
    if not f:
        return False
    frepo.delete_feedback(session, f)
    return True
