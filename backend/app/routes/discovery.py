from fastapi import APIRouter, Depends, status
from sqlmodel import Session

from app.core.db import get_session
from app.core.response import ok
from app.core.security import get_current_user

router = APIRouter(prefix="/discovery", tags=["discovery"])


@router.post("/scan", status_code=status.HTTP_202_ACCEPTED)
def scan(
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    # P1: same price-band competitor discovery. Accepted for MVP.
    return ok(
        {
            "status": "accepted",
            "note": "Same price-band SKU discovery is scheduled for P1.",
        }
    )
