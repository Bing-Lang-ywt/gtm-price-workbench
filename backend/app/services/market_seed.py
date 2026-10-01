"""Discovery + pricing for market channels behind bot walls (Alza, Datart).

Why this is a service and not just a script: the ordinary weekly crawl only
*refreshes SKUs that already exist*, so a newly added model would never appear
on Alza/Datart. This module does discovery **and** pricing in one pass, and is
shared by:

  * ``scripts/backfill_alza_datart_all.py`` - manual/one-off runs
  * the weekly scheduler job                - keeps coverage complete over time
  * the daily self-heal retry               - recovers from temporary IP blocks

Correctness gates (the user's explicit requirement: a wrong price is worse than
no price, because it drives a wrong pricing decision):

  1. discovery rejects accessories (glass/case/charger "for" the phone)
  2. discovery penalises variant siblings (Pro / Ultra / Lite)
  3. the fetched price must sit inside the currency's plausible band
  4. the page's own Product name must match the model  <- final authority

A pair that fails any gate is reported as *missing*, never written.
"""
from __future__ import annotations

import logging
import time

from sqlmodel import Session, select

from app.crawling.market_common import verify_product_name
from app.crawling.registry import adapter_for
from app.models.catalog import Model, Sku
from app.models.channel import Channel
from app.models.price import Price
from app.services.prices import record_price

log = logging.getLogger("market_seed")


def seed_market_channel(
    session: Session,
    channel: Channel,
    models: list[Model],
    *,
    rediscover: bool = False,
    only_codes: set[str] | None = None,
    pause: float = 1.0,
) -> dict:
    """Discover + price every model on ``channel``. Returns a result summary."""
    adapter = adapter_for(channel)
    recorded, missing = 0, []

    for model in models:
        if only_codes and model.marketing_code not in only_codes:
            continue

        existing = session.exec(
            select(Sku).where(
                Sku.model_id == model.id, Sku.channel_id == channel.id
            )
        ).first()
        query = model.display_name

        # 1) Resolve a PDP url.
        if existing and existing.product_url and not rediscover:
            pdp_url = existing.product_url
        else:
            try:
                pdp_url = adapter.discover_pdp(query, timeout=35)
            except Exception as exc:  # noqa: BLE001
                log.warning("%s / %s discover failed: %s",
                            channel.name, model.marketing_code, exc)
                pdp_url = None
        if not pdp_url:
            missing.append((model.marketing_code, "no PDP found"))
            continue

        # 2) Fetch + plausibility band (raises inside the adapter).
        try:
            data = adapter.fetch_gigatron_product(pdp_url, timeout=35)
        except Exception as exc:  # noqa: BLE001
            missing.append((model.marketing_code, f"fetch failed: {exc}"))
            continue

        # 3) Independent model verification from the page's own product name.
        ok, reason = verify_product_name(query, data.get("name"))
        if not ok:
            missing.append((model.marketing_code, reason))
            continue

        # 4) Persist.
        if not existing:
            sku = Sku(
                model_id=model.id,
                channel_id=channel.id,
                slug=f"{model.marketing_code}_{channel.name.lower()}",
                product_url=pdp_url,
                in_stock=data["in_stock"],
                note=f"auto-discovered {time.strftime('%Y-%m-%d')}",
            )
            session.add(sku)
            session.commit()
            session.refresh(sku)
        else:
            sku = existing
            if sku.product_url != pdp_url:
                # Old rows priced a different listing (another memory config or
                # a sibling model); keeping them would fake a price drop.
                for row in session.exec(
                    select(Price).where(Price.sku_id == sku.id)
                ).all():
                    session.delete(row)
                sku.product_url = pdp_url
                session.add(sku)
            sku.in_stock = data["in_stock"]
            session.add(sku)

        record_price(
            session, sku.id, channel.id, "unlocked",
            data["price"], data["currency"], data["in_stock"],
            evaluate=True, meta=data.get("meta"),
            original_price=data.get("original_price"),
            gift=data.get("gift"),
        )
        session.commit()
        recorded += 1
        log.info("%s / %-14s %8.0f %s  <- %s", channel.name,
                 model.marketing_code, data["price"], data["currency"],
                 data.get("name"))
        time.sleep(pause)

    return {
        "channel": channel.name,
        "recorded": recorded,
        "missing": missing,
    }


def seed_market_channels(channel_names: list[str], *, rediscover: bool = False,
                         only_codes: set[str] | None = None) -> list[dict]:
    """Run :func:`seed_market_channel` for several channels in one session."""
    from app.core.db import engine

    out = []
    with Session(engine) as session:
        channels = session.exec(
            select(Channel).where(Channel.name.in_(channel_names))
        ).all()
        models = session.exec(
            select(Model).order_by(Model.brand, Model.display_name)
        ).all()
        for ch in channels:
            out.append(seed_market_channel(
                session, ch, models,
                rediscover=rediscover, only_codes=only_codes,
            ))
    return out


def stale_market_channels(channel_names: list[str], max_age_days: int = 8) -> list[str]:
    """Names of weekly channels whose coverage is stale or incomplete.

    Used by the daily self-heal job: Datart's F5 wall can block this IP for a
    while, and waiting a full week to retry would leave a hole in the matrix.
    """
    from datetime import datetime, timedelta, timezone

    from app.core.db import engine

    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
    stale = []
    with Session(engine) as session:
        total_models = len(session.exec(select(Model)).all())
        for name in channel_names:
            ch = session.exec(
                select(Channel).where(Channel.name == name)
            ).first()
            if not ch:
                continue
            skus = session.exec(
                select(Sku).where(Sku.channel_id == ch.id)
            ).all()
            if len(skus) < total_models:
                stale.append(name)          # coverage still incomplete
                continue
            fresh = session.exec(
                select(Price).where(
                    Price.channel_id == ch.id, Price.captured_at >= cutoff
                )
            ).first()
            if not fresh:
                stale.append(name)          # nothing recent -> retry
    return stale
