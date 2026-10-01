from typing import Any


def ok(data: Any = None, message: str = "") -> dict:
    return {"code": 0, "data": data, "message": message}


def fail(code: int, message: str, data: Any = None) -> dict:
    return {"code": code, "data": data, "message": message}
