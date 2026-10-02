from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session
from typing import Optional

from app.controllers import alert_rules as ctrl
from app.controllers.alert_rules import InvalidRuleError
from app.core.db import get_session
from app.core.response import ok
from app.core.security import get_current_user

router = APIRouter(prefix="/alert-rules", tags=["alert-rules"])


class AlertRuleCreate(BaseModel):
    scope_type: str = "all"
    scope_id: str = ""
    channel_id: Optional[str] = None
    model_id: Optional[str] = None
    sku_id: Optional[str] = None
    price_type: Optional[str] = None
    condition_type: str
    threshold: Optional[float] = None
    notify_target: Optional[str] = None
    is_active: bool = True


class AlertRulePatch(BaseModel):
    scope_type: Optional[str] = None
    scope_id: Optional[str] = None
    channel_id: Optional[str] = None
    model_id: Optional[str] = None
    sku_id: Optional[str] = None
    price_type: Optional[str] = None
    condition_type: Optional[str] = None
    threshold: Optional[float] = None
    notify_target: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("")
def list_rules(
    scope_type: str = None,
    is_active: bool = None,
    page: int = 1,
    limit: int = 20,
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    return ok(ctrl.list_controller(session, scope_type, is_active, page, limit))


@router.post("")
def create_rule(
    body: AlertRuleCreate,
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    try:
        data = ctrl.create_controller(session, body.model_dump(exclude_none=True))
    except InvalidRuleError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return ok(data, "Alert rule created")


class AlertPreviewBody(BaseModel):
    rules: list[dict] = Field(min_length=1, max_length=50)
    samples: list[dict] = Field(min_length=1, max_length=100)


@router.post("/preview")
def preview_alert_rules(
    body: AlertPreviewBody,
    _: dict = Depends(get_current_user),
):
    from app.services.alert_preview import preview_rules

    try:
        return ok(preview_rules(body.rules, body.samples))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/{rule_id}")
def get_rule(
    rule_id: str,
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    data = ctrl.get_controller(session, rule_id)
    if not data:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    return ok(data)


@router.patch("/{rule_id}")
def update_rule(
    rule_id: str,
    body: AlertRulePatch,
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    try:
        data = ctrl.update_controller(session, rule_id, body.model_dump(exclude_none=True))
    except InvalidRuleError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not data:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    return ok(data, "Alert rule updated")


@router.delete("/{rule_id}")
def delete_rule(
    rule_id: str,
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    ok_del = ctrl.delete_controller(session, rule_id)
    if not ok_del:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    return ok(message="Alert rule deleted")
