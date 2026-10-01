"""Crawl freshness & coverage monitoring (MED-2).

The crawler used to fail *silently*: a channel could go N days without a single
price land in the DB, or a whole channel could drop to near-zero coverage, and
nobody would notice until a human eyeballed the dashboard. This module answers
two questions per channel:

* **Freshness** — how many of the channel's SKUs have *no* price newer than
  ``CRAWL_STALE_DAYS`` (or no price at all)? Those are "stale" and the data
  shown for them is stale.
* **Coverage** — what fraction of the channel's SKUs actually have a price?

The result is exposed via ``GET /api/v1/crawl/staleness`` and can also be run
standalone with ``scripts/check_staleness.py`` for a cron/heartbeat check.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from sqlmodel import func, select

from app.core.config import CRAWL_LOW_COVERAGE_PCT, CRAWL_STALE_DAYS
from app.models.catalog import Sku
from app.models.channel import Channel
from app.models.price import Price
from app.repositories.channels import latest_run_map

log = logging.getLogger("services.staleness")

_STALE_DAYS = CRAWL_STALE_DAYS
_LOW_COVERAGE_PCT = CRAWL_LOW_COVERAGE_PCT


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        s = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:  # noqa: BLE001 - a malformed timestamp == unknown == stale
        return None


def compute_staleness(session) -> dict:
    """Return freshness + coverage stats for every channel.

    ``summary`` carries roll-ups; ``channels`` is the per-channel breakdown.
    Safe to call on a live DB (read-only SELECTs).
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=_STALE_DAYS)
    channels = session.exec(
        select(Channel).order_by(Channel.type, Channel.name)
    ).all()
    # 每渠道最新抓取运行（started_at + status）。价格去重跳过会让
    # prices.captured_at 停在旧日，必须用 crawl_runs 判定渠道是否仍在被监控。
    run_map = latest_run_map(session)

    channel_rows: list[dict] = []
    totals = {
        "skus": 0,
        "priced_skus": 0,
        "stale_skus": 0,
        "channels": 0,
        "problem_channels": 0,
    }

    for ch in channels:
        skus = session.exec(select(Sku).where(Sku.channel_id == ch.id)).all()
        total = len(skus)
        if total == 0:
            run = run_map.get(ch.id)
            channel_rows.append(
                {
                    "channel_id": ch.id,
                    "channel": ch.name,
                    "type": ch.type,
                    "total_skus": 0,
                    "priced_skus": 0,
                    "stale_skus": 0,
                    "coverage_pct": 0.0,
                    "last_crawl_at": run["started_at"] if run else None,
                    "last_crawl_status": run["status"] if run else None,
                    "status": "empty",
                }
            )
            totals["channels"] += 1
            continue

        sku_ids = [s.id for s in skus]
        rows = session.exec(
            select(Price.sku_id, func.max(Price.captured_at))
            .where(Price.sku_id.in_(sku_ids))
            .group_by(Price.sku_id)
        ).all()
        latest = {sid: ts for sid, ts in rows}
        priced = len(latest)

        stale = 0
        for sid in sku_ids:
            ts = latest.get(sid)
            if ts is None:
                stale += 1
                continue
            dt = _parse_ts(ts)
            if dt is None:
                stale += 1
                continue
            if dt < cutoff:
                stale += 1

        coverage = round(priced / total * 100, 1) if total else 0.0

        # --- 渠道级健康度：以「最近一次抓取运行」为准，而非价格 captured_at ---
        # 价格去重会让 captured_at 停在旧日（价未变即不落新行），所以「价陈旧」
        # 不等于「渠道死」。判定顺序：
        #   1) 久未抓取（last_crawl_at 超阈值）        -> 渠道死
        #   2) 上次运行整体 failed                       -> 渠道死
        #   3) 上次 partial/degraded 且新落库行数 << SKU 数 -> 被反爬封/选择器烂
        #   4) 覆盖率低于下限                            -> 数据缺口（独立成类）
        #   否则                                         -> ok（价稳定也属正常）
        run = run_map.get(ch.id)
        last_crawl_at = run["started_at"] if run else None
        last_crawl_status = run["status"] if run else None
        last_crawl_items = run["items"] if run else 0
        run_dt = _parse_ts(last_crawl_at)
        recent = run_dt is not None and run_dt >= cutoff
        if not recent:
            health = "stale"
        elif last_crawl_status == "failed":
            health = "stale"
        elif last_crawl_status in ("partial", "degraded") and (last_crawl_items or 0) < 0.3 * total:
            health = "stale"
        else:
            health = "ok"

        status = health
        if coverage < _LOW_COVERAGE_PCT and total > 0:
            status = "low_coverage"

        channel_rows.append(
            {
                "channel_id": ch.id,
                "channel": ch.name,
                "type": ch.type,
                "total_skus": total,
                "priced_skus": priced,
                "stale_skus": stale,
                "coverage_pct": coverage,
                "last_crawl_at": last_crawl_at,
                "last_crawl_status": last_crawl_status,
                "last_crawl_items": last_crawl_items,
                "crawl_fresh": recent,
                "status": status,
            }
        )
        totals["skus"] += total
        totals["priced_skus"] += priced
        totals["stale_skus"] += stale
        totals["channels"] += 1
        if status in ("stale", "low_coverage"):
            totals["problem_channels"] += 1

    return {
        "stale_days_threshold": _STALE_DAYS,
        "low_coverage_pct": _LOW_COVERAGE_PCT,
        "generated_at": now.isoformat(),
        "summary": totals,
        "channels": channel_rows,
    }
