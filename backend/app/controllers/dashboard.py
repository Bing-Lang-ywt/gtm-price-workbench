from datetime import timedelta

from sqlmodel import Session, func, select

from app.core.time import utcnow
from app.models.catalog import Model, Sku
from app.models.channel import Channel
from app.models.ops import Alert, CrawlRun
from app.models.price import FxRate, Price
from app.repositories.catalog import segment_of
from app.repositories.prices import latest_snapshot
from app.services.common import load_maps
from app.services.prices import COUNTRY_CODE_BY_NAME


def summary_controller(session: Session):
    """Dashboard 顶部 KPI 与 Config 页全局状态条数据源。

    返回字段严格对齐前端 ``DashboardSummary`` 接口，避免 KPI 显示 "—"。
    同时保留 ``totals`` / ``countries`` / ``target_model_avg_eur`` 做向后兼容。
    """
    total_skus = session.exec(select(func.count()).select_from(Sku)).one()
    total_channels = session.exec(select(func.count()).select_from(Channel)).one()
    active_channels = session.exec(
        select(func.count()).select_from(Channel).where(Channel.enabled == True)  # noqa: E712
    ).one()

    # 昨夜异动：最近 24 小时内触发的告警数
    cutoff = (utcnow() - timedelta(hours=24)).isoformat()
    last_night_changes = session.exec(
        select(func.count()).select_from(Alert).where(Alert.triggered_at >= cutoff)
    ).one()

    total_alerts = session.exec(select(func.count()).select_from(Alert)).one()
    open_alerts = session.exec(
        select(func.count()).select_from(Alert).where(Alert.status == "pending")
    ).one()
    drop_alerts = session.exec(
        select(func.count()).select_from(Alert).where(Alert.type == "price_drop")
    ).one()

    countries = sorted(set(session.exec(select(Channel.country)).all()))

    target_models = session.exec(select(Model).where(Model.is_target == True)).all()  # noqa: E712
    _model_map, _channel_map = load_maps(session)

    # 目标机型均价（保留旧字段）
    avg_prices = []
    for m in target_models:
        skus = session.exec(select(Sku).where(Sku.model_id == m.id)).all()
        snap = latest_snapshot(session, [s.id for s in skus])
        eurs = [
            p.amount_eur for (_, pt), p in snap.items() if pt == "unlocked" and p.amount_eur > 0
        ]
        avg = round(sum(eurs) / len(eurs), 2) if eurs else None
        avg_prices.append(
            {
                "model_id": m.id,
                "code": m.marketing_code,
                "name": m.display_name,
                "segment": segment_of(m.price_band_anchor),
                "avg_unlocked_eur": avg,
                "samples": len(eurs),
            }
        )

    # 最大区域价差：对每个目标机型，取各国最低裸机价，计算 max - min
    max_spread = 0.0
    spread_model = None
    spread_country_max = None
    spread_country_min = None

    for m in target_models:
        stmt = (
            select(Channel.country, func.min(Price.amount_eur))
            .join(Sku, Price.sku_id == Sku.id)
            .join(Channel, Sku.channel_id == Channel.id)
            .where(
                Sku.model_id == m.id,
                Price.price_type == "unlocked",
                Price.amount_eur > 0,
            )
            .group_by(Channel.country)
        )
        rows = session.exec(stmt).all()
        if len(rows) < 2:
            continue

        amounts = [float(r[1]) for r in rows]
        country_names = [r[0] for r in rows]
        lo, hi = min(amounts), max(amounts)
        spread = round(hi - lo, 2)
        if spread > max_spread:
            max_spread = spread
            spread_model = m.marketing_code
            spread_country_min = COUNTRY_CODE_BY_NAME.get(
                country_names[amounts.index(lo)], country_names[amounts.index(lo)]
            )
            spread_country_max = COUNTRY_CODE_BY_NAME.get(
                country_names[amounts.index(hi)], country_names[amounts.index(hi)]
            )

    # 上次全量抓取：最近一次 CrawlRun 的结束/开始时间
    last_crawl = session.exec(select(CrawlRun).order_by(CrawlRun.started_at.desc())).first()
    last_crawl_at = None
    if last_crawl:
        last_crawl_at = last_crawl.finished_at or last_crawl.started_at
        if not last_crawl_at:
            last_crawl_at = None

    # FX 汇率日期：最新汇率日期
    fx = session.exec(select(FxRate).order_by(FxRate.date.desc())).first()
    fx_date = fx.date if fx else None

    return {
        # 前端 DashboardSummary 契约字段
        "monitored_skus": total_skus,
        "active_channels": active_channels,
        "last_night_changes": last_night_changes,
        "max_regional_spread": max_spread if max_spread > 0 else None,
        "spread_model": spread_model,
        "spread_country_max": spread_country_max,
        "spread_country_min": spread_country_min,
        "last_crawl_at": last_crawl_at,
        "fx_date": fx_date,
        # 向后兼容：旧形状
        "totals": {
            "skus": total_skus,
            "channels": total_channels,
            "active_channels": active_channels,
            "alerts": total_alerts,
            "open_alerts": open_alerts,
            "price_drop_alerts": drop_alerts,
        },
        "countries": countries,
        "target_model_avg_eur": avg_prices,
    }
