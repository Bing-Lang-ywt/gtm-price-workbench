"""Read-only spread of latest per-SKU prices; no manual-price precedence."""
from datetime import datetime, timezone
import math
from sqlmodel import select
from app.models.catalog import Model, Sku
from app.models.channel import Channel
from app.models.price import Price
from app.services.price_preflight import SUPPORTED_PRICE_TYPES


def latest_price_spread(session, price_type='unlocked', model_id=None):
    if price_type not in SUPPORTED_PRICE_TYPES:
        raise ValueError('Unsupported price type')
    models_query = select(Model).order_by(Model.id)
    if model_id is not None:
        models_query = models_query.where(Model.id == model_id)
    models = session.exec(models_query).all()
    query = (select(Sku.model_id, Sku.id, Channel.id, Channel.name,
                    Price.id, Price.captured_at, Price.amount_eur)
             .join(Price, Price.sku_id == Sku.id)
             .join(Channel, Channel.id == Sku.channel_id)
             .where(Price.channel_id == Sku.channel_id, Price.price_type == price_type))
    if model_id is not None:
        query = query.where(Sku.model_id == model_id)
    latest = {}
    invalid_timestamps = 0
    for mid, sid, cid, name, pid, captured, amount in session.exec(query):
        try:
            timestamp = datetime.fromisoformat(captured.replace('Z', '+00:00'))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            timestamp = timestamp.astimezone(timezone.utc)
        except (ValueError, TypeError, AttributeError):
            invalid_timestamps += 1
            continue
        candidate = (timestamp, pid, mid, cid, name, amount)
        if sid not in latest or candidate[:2] > latest[sid][:2]:
            latest[sid] = candidate
    grouped = {}
    for sid, (_, _, mid, cid, name, amount) in latest.items():
        # Validate after selecting latest: never resurrect an older usable price.
        if amount is None or not math.isfinite(amount) or amount <= 0:
            continue
        channels = grouped.setdefault(mid, {})
        channel = channels.setdefault(cid, {'channel_id': cid, 'channel': name,
                                            'amount_eur': amount, 'sku_samples': 0})
        channel['amount_eur'] = min(channel['amount_eur'], amount)
        channel['sku_samples'] += 1
    items = []
    for model in models:
        channels = sorted(grouped.get(model.id, {}).values(), key=lambda row: row['channel_id'])
        amounts = [row['amount_eur'] for row in channels]
        low, high = (min(amounts), max(amounts)) if amounts else (None, None)
        items.append({'model_id': model.id, 'model': model.display_name,
                      'channel_count': len(channels), 'channels': channels,
                      'min_eur': low, 'max_eur': high,
                      'spread_eur': round(high-low, 2) if len(channels) >= 2 else None})
    return {'price_type': price_type, 'items': items,
            'skipped_invalid_timestamps': invalid_timestamps}
