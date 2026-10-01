from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.controllers import alerts as ctrl
from app.core.db import get_session
from app.core.response import ok
from app.core.security import get_current_user

router = APIRouter(prefix="/alerts", tags=["alerts"])


class AlertBody(BaseModel):
    sku_id: str = None
    type: str = None
    before: float = None
    after: float = None
    currency: str = ""
    threshold_pct: float = 0.0
    message: str = ""
    status: str = None
    notify_target: str = ""


@router.get("")
def list_alerts(
    type: str = None,
    status: str = None,
    sku_id: str = None,
    page: int = 1,
    limit: int = 20,
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    return ok(ctrl.list_controller(session, type, status, sku_id, page, limit))


@router.post("")
def create_alert(
    body: AlertBody,
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    data = ctrl.create_controller(session, body.model_dump(exclude_none=True))
    return ok(data, "Alert created")


@router.get("/{alert_id}")
def get_alert(
    alert_id: str,
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    data = ctrl.get_controller(session, alert_id)
    if not data:
        raise HTTPException(status_code=404, detail="Alert not found")
    return ok(data)


@router.patch("/{alert_id}")
def update_alert(
    alert_id: str,
    body: AlertBody,
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    data = ctrl.update_controller(session, alert_id, body.model_dump(exclude_none=True))
    if not data:
        raise HTTPException(status_code=404, detail="Alert not found")
    return ok(data, "Alert updated")


@router.delete("/{alert_id}")
def delete_alert(
    alert_id: str,
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    ok_del = ctrl.delete_controller(session, alert_id)
    if not ok_del:
        raise HTTPException(status_code=404, detail="Alert not found")
    return ok(message="Alert deleted")
