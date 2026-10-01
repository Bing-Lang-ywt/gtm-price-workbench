from app.repositories import prices as prepo, catalog as crepo
from app.services.common import load_maps


def comparison_service(session, model_id, segment, country):
    if model_id:
        target = [crepo.get_model(session, model_id)]
        target = [t for t in target if t]
    else:
        target = [m for m in crepo.list_models(session) if m["is_target"]]

    seg = segment
    if not seg and target:
        seg = crepo.segment_of(target[0]["price_band_anchor"])

    all_models = crepo.list_models(session)
    if seg:
        seg_model_ids = {
            m["id"] for m in all_models if crepo.segment_of(m["price_band_anchor"]) == seg
        }
    else:
        seg_model_ids = {m["id"] for m in all_models}

    skus = prepo.get_skus_for_filter(session, country=country)
    seg_skus = [s for s in skus if s.model_id in seg_model_ids]
    latest = prepo.latest_snapshot(session, [s.id for s in seg_skus])
    model_map, channel_map = load_maps(session)

    rows = []
    for (sku_id, pt), p in latest.items():
        if pt != "unlocked":
            continue
        sku = next((s for s in seg_skus if s.id == sku_id), None)
        if not sku:
            continue
        m = model_map.get(sku.model_id, {})
        c = channel_map.get(sku.channel_id, {})
        rows.append(
            {
                "model_id": m.get("id"),
                "marketing_code": m.get("marketing_code"),
                "display_name": m.get("display_name"),
                "brand": m.get("brand"),
                "is_target": m.get("is_target"),
                "segment": crepo.segment_of(m.get("price_band_anchor", 0)),
                "channel_id": c.get("id"),
                "channel_name": c.get("name"),
                "country": c.get("country"),
                "amount_eur": p.amount_eur,
                "price": p.price,
                "currency": p.currency,
                "in_stock": p.in_stock,
                "captured_at": p.captured_at,
            }
        )
    rows.sort(key=lambda r: (r["country"], r["display_name"], r["channel_name"]))

    return {
        "segment": seg,
        "country": country,
        "target_models": [
            {
                "id": m["id"],
                "code": m["marketing_code"],
                "name": m["display_name"],
                "brand": m["brand"],
                "segment": crepo.segment_of(m["price_band_anchor"]),
            }
            for m in target
        ],
        "rows": rows,
    }
