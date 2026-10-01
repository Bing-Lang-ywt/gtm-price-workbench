import logging
import os
import threading
import time
from typing import Any

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.core.db import get_session
from app.core.response import ok
from app.core.security import get_current_user

logger = logging.getLogger("params")

router = APIRouter(prefix="/params", tags=["params"])

# 参数表数据真源：桌面 Excel（用户指定）。
# 真源 = 环境变量覆盖 / PARAMS_XLSX_PATH；
# 项目内 backend/data 副本仅作兜底（部署环境无桌面读权限时），绝非第二真源。
# 关键健康约束：真源不可读时只允许用兜底副本，并标记 stale，杜绝「静默陈旧数据」。
STALE_DAYS = 7  # 兜底副本超过该天数未同步即视为陈旧


def _truth_paths() -> list[str]:
    path = os.getenv("PARAMS_XLSX_PATH")
    return [path] if path else []


def _fallback_paths() -> list[str]:
    here = os.path.dirname(os.path.abspath(__file__))
    return [os.path.join(here, "..", "..", "data", "demo_parameters.xlsx")]


def _is_url(v: Any) -> bool:
    return isinstance(v, str) and v.strip().lower().startswith("http")


# 按文件 mtime 缓存解析结果，避免每个请求都重读 Excel（仅文件变更时重新解析）。
_CACHE: dict[str, Any] = {"mtime": 0.0, "products": [], "chips": [], "source": None}
_CACHE_LOCK = threading.Lock()


def _parse_products(ws) -> list[dict]:
    rows = [r for r in ws.iter_rows(values_only=True)]
    if not rows:
        return []
    # 第一行是表头，数据从第二行起
    out: list[dict] = []
    for r in rows[1:]:
        brand = r[0] if len(r) > 0 else None
        product = r[1] if len(r) > 1 else None
        # 跳过品牌/产品均为空的行（尾随空行）
        if not brand and not product:
            continue
        chip_raw = r[7] if len(r) > 7 else None
        chip_name = None
        if isinstance(chip_raw, str):
            chip_name = chip_raw.split("\n", 1)[0].strip() or None
        official_url = None
        # col17 = "点击查看官网" 文本标签，col18 = 真实 URL
        if len(r) > 18 and _is_url(r[18]):
            official_url = str(r[18]).strip()
        elif len(r) > 17 and _is_url(r[17]):
            official_url = str(r[17]).strip()

        def cell(i: int) -> Any:
            return r[i] if len(r) > i else None

        out.append(
            {
                "brand": brand,
                "product": product,
                "category": cell(2),
                "release_time": cell(3),
                "price_rmb": cell(4),
                "price_eur": cell(5),
                "screen": cell(6),
                "chip": chip_raw,
                "chip_name": chip_name,
                "front_camera": cell(8),
                "rear_camera": cell(9),
                "battery": cell(10),
                "wired_charging_w": cell(11),
                "wireless_charging_w": cell(12),
                "dimensions": cell(13),
                "ip_rating": cell(14),
                "colors": cell(15),
                "top_selling_point": cell(16),
                "official_url": official_url,
            }
        )
    return out


def _parse_chips(ws) -> list[dict]:
    rows = [r for r in ws.iter_rows(values_only=True)]
    if not rows:
        return []
    out: list[dict] = []
    for r in rows[1:]:
        name = r[1] if len(r) > 1 else None
        if not name:
            continue

        rank = None
        try:
            if len(r) > 0 and r[0] is not None:
                rank = int(float(r[0]))
        except (ValueError, TypeError):
            rank = None

        score = None
        try:
            if len(r) > 2 and r[2] is not None:
                score = float(r[2])
        except (ValueError, TypeError):
            score = None

        in_use = False
        if len(r) > 6 and r[6] is not None:
            in_use = str(r[6]).strip() == "是"

        out.append(
            {
                "rank": rank,
                "chip_name": name,
                "score": score,
                "vendor": r[3] if len(r) > 3 else None,
                "tier": r[4] if len(r) > 4 else None,
                "source": r[5] if len(r) > 5 else None,
                "in_use": in_use,
            }
        )

    # 天梯图：分数高者居首（分数相同按排名升序）
    out.sort(key=lambda c: (-(c["score"] or 0), c["rank"] or 9e9))
    return out


def _parse_and_cache(path: str, stale: bool) -> tuple[list[dict], list[dict], str, bool]:
    """解析并写入 mtime 缓存；stale 由调用方根据真源/兜底判定。"""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return [], [], path, stale
    with _CACHE_LOCK:
        if _CACHE["mtime"] == mtime and _CACHE["source"] == path and _CACHE["products"]:
            return _CACHE["products"], _CACHE["chips"], path, stale
        import openpyxl

        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        products = _parse_products(wb["东北欧产品参数表"])
        chips = _parse_chips(wb["芯片天梯图"])
        _CACHE["mtime"] = mtime
        _CACHE["products"] = products
        _CACHE["chips"] = chips
        _CACHE["source"] = path
        return products, chips, path, stale


def _load() -> tuple[list[dict], list[dict], str | None, bool]:
    """返回 (products, chips, source_path, stale)。

    stale=True 仅当：桌面真源不可读，且被迫使用项目内兜底副本（可能过期）。
    真源可读时一律 stale=False，即便兜底副本也存在。
    """
    for p in _truth_paths():
        if os.path.exists(p):
            return _parse_and_cache(p, stale=False)
    for p in _fallback_paths():
        if os.path.exists(p):
            try:
                age_days = (time.time() - os.path.getmtime(p)) / 86400.0
            except OSError:
                age_days = 9e9
            stale = age_days > STALE_DAYS
            if stale:
                logger.warning(
                    "参数表使用兜底副本(已约 %d 天未同步桌面真源)，数据可能非最新: %s",
                    int(age_days), p,
                )
            return _parse_and_cache(p, stale=stale)
    logger.warning("参数表 Excel 未找到（桌面真源与兜底副本均缺失）")
    return [], [], None, False


@router.get("/products")
def list_products(
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    """参数对比：东北欧产品参数表全部机型（19 列），数据以桌面 Excel 为准。"""
    products, _chips, source, stale = _load()
    return ok(
        {
            "items": products,
            "source": os.path.basename(source) if source else None,
            "count": len(products),
            "stale": stale,
        }
    )


@router.get("/chips")
def list_chips(
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    """芯片天梯图：按综合性能分数排序（高者居首），数据以桌面 Excel 为准。"""
    _products, chips, source, stale = _load()
    return ok(
        {
            "items": chips,
            "source": os.path.basename(source) if source else None,
            "count": len(chips),
            "stale": stale,
        }
    )
