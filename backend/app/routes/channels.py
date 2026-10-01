from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.controllers import channels as ctrl
from app.core.db import get_session
from app.core.response import ok
from app.core.security import get_current_user

router = APIRouter(prefix="/channels", tags=["channels"])


@router.get("")
def list_channels(
    country: str = None,
    type: str = None,
    page: int = 1,
    limit: int = 20,
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    return ok(ctrl.list_channels_controller(session, country, type, page, limit))


@router.get("/{channel_id}")
def get_channel(
    channel_id: str,
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    data = ctrl.get_channel_controller(session, channel_id)
    if not data:
        raise HTTPException(status_code=404, detail="Channel not found")
    return ok(data)


@router.get("/{channel_id}/crawl-runs")
def crawl_runs(
    channel_id: str,
    status: str = None,
    page: int = 1,
    limit: int = 20,
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    return ok(ctrl.list_crawl_runs_controller(session, channel_id, status, page, limit))


@router.post("/{channel_id}/trigger-crawl")
def trigger_crawl(
    channel_id: str,
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    result = ctrl.trigger_channel_controller(channel_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    return ok(result, "Crawl triggered")
