from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.controllers import comparison as ctrl
from app.core.db import get_session
from app.core.response import ok
from app.core.security import get_current_user

router = APIRouter(prefix="/comparison", tags=["comparison"])


@router.get("")
def comparison(
    model_id: str = None,
    segment: str = None,
    country: str = None,
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    return ok(ctrl.comparison_controller(session, model_id, segment, country))
