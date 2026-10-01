from sqlmodel import Session, select

from app.models.channel import Channel
from app.models.ops import CrawlRun
from app.repositories.base import paged, page_meta


def latest_run_map(session: Session) -> dict:
    """每渠道最新一次抓取运行（按 started_at 倒序取首条）。

    返回 {channel_id: {"started_at": str, "status": str, "items": int}}。
    这是「渠道是否仍在被监控」的真源信号——价格去重跳过（值未变不落库）
    会让 prices.captured_at 停在旧日，从而误判渠道停滞；crawl_runs 记录每次
    抓取尝试，无论价格是否变化都会更新，因此用它判定健康更准确。
    `items` 是本次运行**新落库**的价格行数（去重后），用于区分「价稳定导致
    零新增」与「被反爬拦到零产出」：健康但价未变的渠道 status=success、
    items 可能很小；被封禁的渠道 status=partial/degraded 且 items≈0。
    """
    rows = session.exec(
        select(
            CrawlRun.channel_id,
            CrawlRun.started_at,
            CrawlRun.status,
            CrawlRun.items,
        ).order_by(CrawlRun.started_at.desc())
    ).all()
    out: dict = {}
    for channel_id, started_at, status, items in rows:
        if channel_id not in out:
            out[channel_id] = {
                "started_at": started_at,
                "status": status,
                "items": items,
            }
    return out


def list_channels(session: Session, country=None, type=None, page=1, limit=20):
    stmt = select(Channel)
    if country:
        stmt = stmt.where(Channel.country == country)
    if type:
        stmt = stmt.where(Channel.type == type)
    stmt = stmt.order_by(Channel.country, Channel.name)
    rows, total = paged(session, stmt, page, limit)
    run_map = latest_run_map(session)
    result = []
    for r in rows:
        d = r.model_dump()
        run = run_map.get(r.id)
        d["last_crawl_at"] = run["started_at"] if run else None
        d["last_crawl_status"] = run["status"] if run else None
        result.append(d)
    return result, total


def get_channel(session: Session, channel_id: str):
    return session.get(Channel, channel_id)


def list_crawl_runs(session: Session, channel_id: str, status=None, page=1, limit=20):
    stmt = select(CrawlRun).where(CrawlRun.channel_id == channel_id)
    if status:
        stmt = stmt.where(CrawlRun.status == status)
    stmt = stmt.order_by(CrawlRun.started_at.desc())
    rows, total = paged(session, stmt, page, limit)
    return [r.model_dump() for r in rows], total
