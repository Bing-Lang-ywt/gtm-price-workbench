from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.controllers import dashboard as ctrl
from app.core.db import get_session
from app.core.response import ok
from app.core.security import get_current_user

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
def summary(
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    return ok(ctrl.summary_controller(session))
