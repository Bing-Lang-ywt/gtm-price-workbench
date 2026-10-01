from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlmodel import Session

from app.controllers import auth as ctrl
from app.core.db import get_session
from app.core.response import ok
from app.core.security import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginReq(BaseModel):
    email: EmailStr
    password: str


@router.post("/login")
def login(body: LoginReq):
    # OpenAPI: this endpoint is public (no bearer required).
    result = ctrl.login_controller(body.email, body.password)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    return ok(result)


@router.get("/me")
def me(principal: dict = Depends(get_current_user)):
    return ok(ctrl.me_controller(principal))
