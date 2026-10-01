from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.controllers import catalog as ctrl
from app.core.db import get_session
from app.core.response import ok
from app.core.security import get_current_user

router = APIRouter(prefix="/skus", tags=["skus"])


@router.get("")
def list_skus(
    country: str = None,
    channel_id: str = None,
    model_id: str = None,
    segment: str = None,
    active: bool | None = None,
    page: int = 1,
    limit: int = 20,
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    return ok(
        ctrl.list_skus_controller(
            session, country, channel_id, model_id, segment, active, page, limit
        )
    )


@router.get("/{sku_id}")
def get_sku(
    sku_id: str,
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    data = ctrl.get_sku_controller(session, sku_id)
    if not data:
        raise HTTPException(status_code=404, detail="SKU not found")
    return ok(data)
