from app.repositories.catalog import get_sku, segment_of
from app.repositories.prices import latest_snapshot
from app.services.catalog import (
    get_model_service,
    list_competitor_mappings_service,
    list_model_skus_service,
    list_models_service,
    list_skus_service,
    update_model_service,
)
from app.services.common import load_maps


def list_models_controller(session, is_target):
    return list_models_service(session, is_target)


def get_model_controller(session, model_id):
    return get_model_service(session, model_id)


def update_model_controller(session, model_id, payload):
    return update_model_service(session, model_id, payload)


def list_model_skus_controller(session, model_id):
    return list_model_skus_service(session, model_id)


def list_skus_controller(session, country, channel_id, model_id, segment, active, page, limit):
    return list_skus_service(
        session, country, channel_id, model_id, segment, active, page, limit
    )


def list_competitor_mappings_controller(session):
    return list_competitor_mappings_service(session)


def get_sku_controller(session, sku_id):
    sku = get_sku(session, sku_id)
    if not sku:
        return None
    snap = latest_snapshot(session, [sku.id])
    model_map, channel_map = load_maps(session)
    m = model_map.get(sku.model_id, {})
    c = channel_map.get(sku.channel_id, {})
    prices = [p.model_dump() for (_, pt), p in snap.items()]
    return {
        **sku.model_dump(),
        "model": {
            k: m.get(k)
            for k in ("id", "marketing_code", "display_name", "brand", "is_target")
        },
        "segment": segment_of(m.get("price_band_anchor", 0)),
        "channel": {k: c.get(k) for k in ("id", "name", "country", "type")},
        "latest_prices": prices,
    }
