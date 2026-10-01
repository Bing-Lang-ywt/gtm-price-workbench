import jwt
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import (
    ACCESS_TOKEN_EXPIRE_HOURS,
    DEV_EMAIL,
    DEV_PASSWORD,
    DEV_ROLE,
    JWT_ALG,
    MARKET_ACCOUNTS,
    SECRET_KEY,
)

bearer = HTTPBearer(auto_error=False)


def create_token(
    email: str,
    role: str = DEV_ROLE,
    market: str | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {
        "sub": email,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    if market:
        payload["market"] = market
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALG)


def verify_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALG])
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )


def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
) -> dict:
    if creds is None or not creds.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )
    return verify_token(creds.credentials)


def authenticate(email: str, password: str) -> dict | None:
    if DEV_PASSWORD and email == DEV_EMAIL and password == DEV_PASSWORD:
        return {"sub": email, "role": DEV_ROLE}
    acct = MARKET_ACCOUNTS.get(email)
    if acct and password == acct.get("password"):
        return {
            "sub": email,
            "role": acct.get("role", "analyst"),
            "market": acct.get("market", ""),
        }
    return None
