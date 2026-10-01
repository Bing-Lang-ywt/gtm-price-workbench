import logging
import threading
from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.controllers import crawl as ctrl
from app.core.db import get_session
from app.core.response import ok
from app.core.security import get_current_user

log = logging.getLogger("api.crawl")
router = APIRouter(prefix="/crawl", tags=["crawl"])


@router.post("/trigger")
def trigger_crawl(
    channel_ids: list[str] | None = Query(
        None, description="可选：仅爬指定渠道名列表；省略则全量爬取"
    ),
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    """Trigger a crawl. Runs in a background thread so the HTTP request returns
    immediately even for a full (~30 min) crawl across all channels.
    """

    def _run():
        try:
            ctrl.trigger_controller(channel_ids=channel_ids)
        except Exception as exc:  # noqa: BLE001
            log.exception("background crawl failed: %s", exc)

    threading.Thread(target=_run, daemon=True).start()
    return ok({"triggered": True, "scope": channel_ids or "all"}, "Crawl triggered")


@router.get("/staleness")
def crawl_staleness(
    session: Session = Depends(get_session),
    _: dict = Depends(get_current_user),
):
    """Freshness + coverage report (MED-2).

    Surfaces channels whose crawler has gone quiet: SKUs with no price newer
    than ``CRAWL_STALE_DAYS`` or coverage below ``CRAWL_LOW_COVERAGE_PCT``.
    Pair with a cron that pokes this endpoint and alerts on ``summary.problem_channels > 0``.
    """
    from app.services.staleness import compute_staleness

    return ok(compute_staleness(session), "staleness")
