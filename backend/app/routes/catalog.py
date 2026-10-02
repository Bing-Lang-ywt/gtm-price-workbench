from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session
from typing import Optional, Union

from app.controllers import catalog as ctrl
from app.core.db import get_session
from app.core.response import ok
from app.core.security import get_current_user

router = APIRouter(prefix="/models", tags=["models"])


class ModelPatchBody(BaseModel):
    display_name: Optional[str] = None
    # Accepts either a category string (e.g. "mid") or a numeric EUR anchor.
    # strings are mapped to EUR midpoints in the service layer.
    price_band_anchor: Optional[Union[str, float]] = None
    is_target: Optional[bool] = None
    aliases: Optional[list] = None  # list of {"alias": str} or bare strings


@router.get("")
def list_models(
    is_target: bool = None,
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    return ok(ctrl.list_models_controller(session, is_target))


@router.get("/integrity")
def catalog_integrity(
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    from app.services.catalog_integrity import diagnose_catalog

    return ok(diagnose_catalog(session))


@router.get("/{model_id}")
def get_model(
    model_id: str,
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    data = ctrl.get_model_controller(session, model_id)
    if not data:
        raise HTTPException(status_code=404, detail="Model not found")
    return ok(data)


@router.get("/{model_id}/skus")
def model_skus(
    model_id: str,
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    return ok(ctrl.list_model_skus_controller(session, model_id))


@router.patch("/{model_id}")
def update_model(
    model_id: str,
    body: ModelPatchBody,
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    data = ctrl.update_model_controller(session, model_id, body.model_dump(exclude_none=True))
    if not data:
        raise HTTPException(status_code=404, detail="Model not found")
    return ok(data, "Model updated")
