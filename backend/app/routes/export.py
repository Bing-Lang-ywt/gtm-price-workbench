import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.core.security import get_current_user

router = APIRouter(prefix="/export", tags=["export"])

# 4 dirname levels: routes -> app -> backend -> <project root>, so EXCEL_PATH
# resolves to <project root>/data/price_history.xlsx — MUST match
# backend/app/services/price_excel.py's TARGET (also project root/data/).
_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
EXCEL_PATH = os.path.join(_ROOT, "data", "price_history.xlsx")


@router.get("/price-excel")
def download_price_excel(_: dict = Depends(get_current_user)):
    if not os.path.exists(EXCEL_PATH):
        raise HTTPException(
            status_code=404,
            detail="尚未生成价格表，请先执行一次抓取",
        )
    return FileResponse(
        EXCEL_PATH,
        filename="竞品价格表.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
