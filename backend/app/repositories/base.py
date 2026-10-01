from sqlmodel import Session, func, select
from sqlmodel.sql.expression import Select
from typing import Any, List, Tuple


def paged(session: Session, stmt: Select, page: int = 1, limit: int = 20) -> Tuple[List[Any], int]:
    """Return (rows, total) applying offset/limit to the provided statement."""
    page = max(page, 1)
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = session.exec(count_stmt).one()
    rows = session.exec(stmt.offset((page - 1) * limit).limit(limit)).all()
    return rows, total


def page_meta(total: int, page: int, limit: int) -> dict:
    pages = (total + limit - 1) // limit if limit > 0 else 0
    return {"total": total, "page": page, "limit": limit, "pages": pages}
