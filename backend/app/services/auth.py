from app.core.security import authenticate, create_token


def login(email: str, password: str):
    principal = authenticate(email, password)
    if not principal:
        return None
    token = create_token(
        principal["sub"],
        principal.get("role", "analyst"),
        principal.get("market"),
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in_hours": 720,
        "user": principal,
    }
