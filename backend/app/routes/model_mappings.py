from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.controllers import catalog as ctrl
from app.core.db import get_session
from app.core.response import ok
from app.core.security import get_current_user

router = APIRouter(prefix="/model-mappings", tags=["model-mappings"])


@router.get("")
def list_model_mappings(
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    return ok(ctrl.list_competitor_mappings_controller(session))
