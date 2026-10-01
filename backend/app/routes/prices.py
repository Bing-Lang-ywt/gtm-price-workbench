from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.controllers import prices as ctrl
from app.core.db import get_session
from app.core.response import ok
from app.core.security import get_current_user

router = APIRouter(prefix="/prices", tags=["prices"])


class ManualPriceCreate(BaseModel):
    sku_id: str
    channel_id: str
    price_type: str  # unlocked | contract_monthly | subsidy_down_payment
    price: float
    currency: str  # EUR | RSD | HUF | RON | BGN | PLN | CZK
    in_stock: bool = True


@router.post("/manual")
def create_manual(
    body: ManualPriceCreate,
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    """人工补录价格（看板「填价」入口）。落库+FX归一化+告警评估，meta.source='manual'。"""
    try:
        data = ctrl.create_manual_controller(
            session,
            body.sku_id,
            body.channel_id,
            body.price_type,
            body.price,
            body.currency,
            in_stock=body.in_stock,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return ok(data, "价格已补录")


@router.get("/latest")
def latest(
    channel_id: str = None,
    model_id: str = None,
    country: str = None,
    price_type: str = None,
    page: int = 1,
    limit: int = 20,
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    return ok(
        ctrl.latest_controller(
            session, channel_id, model_id, country, price_type, page, limit
        )
    )


@router.get("")
def history(
    sku_id: str = None,
    channel_id: str = None,
    price_type: str = None,
    from_: str = Query(None, alias="from"),
    to: str = Query(None, alias="to"),
    page: int = 1,
    limit: int = 100,
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    return ok(
        ctrl.history_controller(
            session, sku_id, channel_id, price_type, from_, to, page, limit
        )
    )


@router.get("/by-date")
def by_date(
    date: str = Query(..., description="快照锚定日期 YYYY-MM-DD"),
    channel_id: str = None,
    model_id: str = None,
    country: str = None,
    price_type: str = None,
    window_days: int = Query(14, description="锚定日前回看窗口(天)，超窗不展示"),
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    """日历用：返回锚定到指定日期的当日价格快照（每个 渠道×机型×价格类型 取窗口内最新价）。"""
    return ok(
        ctrl.snapshot_by_date_controller(
            session, date, channel_id, model_id, country, price_type, window_days
        )
    )


@router.get("/dates")
def dates(
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    """日历用：返回所有有抓取数据的日期及条数（升序）。"""
    return ok(ctrl.date_counts_controller(session))


@router.get("/promotions")
def promotions(
    from_: str = Query(None, alias="from"),
    to: str = Query(None, alias="to"),
    threshold: float = Query(0.03, description="促销判定降幅阈值(如0.03=降价3%)"),
    max_drop: float = Query(0.6, description="单次降幅上限，超过视为数据异常跳过"),
    channel_id: str = None,
    model_id: str = None,
    country: str = None,
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    """促销起点检测：返回各 (机型×渠道×价格类型) 首次显著降价的事件（按时间倒序）。"""
    return ok(
        ctrl.promotions_controller(
            session, from_, to, threshold, channel_id, model_id, country, max_drop
        )
    )


@router.get("/trend")
def trend(
    model_id: str = Query(..., description="机型 id"),
    price_type: str = None,
    country: str = None,
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    """单品生命周期走势：按渠道分组返回该机型的价格时间序列。"""
    return ok(ctrl.model_trend_controller(session, model_id, price_type, country))
