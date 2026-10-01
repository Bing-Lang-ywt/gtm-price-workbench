from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.controllers import feedback as ctrl
from app.core.db import get_session
from app.core.response import ok
from app.core.security import get_current_user

router = APIRouter(prefix="/feedbacks", tags=["feedbacks"])


class FeedbackBody(BaseModel):
    content: str
    author: str = ""


@router.get("")
def list_feedbacks(
    page: int = 1,
    limit: int = 50,
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    return ok(ctrl.list_controller(session, page, limit))


@router.post("")
def create_feedback(
    body: FeedbackBody,
    session: Session = Depends(get_session),
    user: dict = Depends(get_current_user),
):
    if not body.content or not body.content.strip():
        raise HTTPException(status_code=400, detail="留言内容不能为空")
    author = body.author or user.get("sub") or user.get("email") or "匿名"
    data = ctrl.create_controller(
        session,
        {
            "content": body.content.strip(),
            "author": author,
            "email": user.get("email", user.get("sub", "")),
        },
    )
    return ok(data, "Feedback created")


@router.delete("/{feedback_id}")
def delete_feedback(
    feedback_id: str,
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    ok_del = ctrl.delete_controller(session, feedback_id)
    if not ok_del:
        raise HTTPException(status_code=404, detail="Feedback not found")
    return ok(message="Feedback deleted")
