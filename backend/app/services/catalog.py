from app.models.catalog import Model
from app.repositories import catalog as repo
from app.repositories.base import page_meta
from app.services.common import load_maps

# Canonical price-band category strings returned by `segment_of`. The GET side
# always emits one of these (it runs the float anchor through segment_of), so the
# PATCH side must accept exactly these labels for a stable round-trip.
#
# Midpoints are chosen so each maps back to its own bucket:
#   lite<=300, mid<=500, upper_mid<=800, flagship>800
# Front-end also sends "entry" (synonym of lite) and "foldable" (closest bucket is
# flagship); we accept them so the edit never 422s.
PRICE_BAND_MIDPOINTS = {
    "lite": 150.0,
    "entry": 150.0,
    "mid": 400.0,
    "upper_mid": 600.0,
    "flagship": 850.0,
    "foldable": 1500.0,
}


def anchor_from_price_band(value):
    """Normalize a PATCH `price_band_anchor` value to a EUR float anchor.

    - numeric -> returned as float
    - numeric string -> parsed as float
    - known category string -> mapped via PRICE_BAND_MIDPOINTS
    - unknown -> None (caller skips the field, leaving the column untouched)
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip().lower()
        if s in PRICE_BAND_MIDPOINTS:
            return PRICE_BAND_MIDPOINTS[s]
        try:
            return float(s)
        except ValueError:
            return None
    return None


def list_models_service(session, is_target=None):
    rows = repo.list_models(session, is_target)
    for r in rows:
        r["price_band_anchor"] = repo.segment_of(r["price_band_anchor"])
    return rows


def get_model_service(session, model_id):
    m = repo.get_model(session, model_id)
    if not m:
        return None
    return _model_with_aliases(session, m)


def _model_with_aliases(session, model: Model) -> dict:
    d = model.model_dump()
    d["price_band_anchor"] = repo.segment_of(d["price_band_anchor"])
    d["aliases"] = repo.get_model_aliases(session, model.id)
    return d


def update_model_service(session, model_id: str, payload: dict):
    """Update scalar model fields and (optionally) upsert aliases.

    `payload` is a plain dict (already stripped of None via exclude_none).
    If the `aliases` key is present it is replaced wholesale; if absent the
    existing aliases are left untouched.

    `price_band_anchor` may arrive as a category string from the front-end; it is
    converted to the EUR float anchor before persisting into the float column.
    """
    m = repo.get_model(session, model_id)
    if not m:
        return None
    aliases = payload.pop("aliases", None)
    # Convert a possible category-string anchor into the float the column holds.
    if "price_band_anchor" in payload:
        converted = anchor_from_price_band(payload["price_band_anchor"])
        if converted is None:
            payload.pop("price_band_anchor")  # invalid string -> leave column as-is
        else:
            payload["price_band_anchor"] = converted
    alias_strings: list[str] = []
    if aliases is not None:
        for a in aliases:
            if isinstance(a, dict):
                alias_strings.append(a.get("alias"))
            elif isinstance(a, str):
                alias_strings.append(a)
    repo.update_model(session, m, **payload)
    if aliases is not None:
        repo.replace_model_aliases(session, model_id, alias_strings)
    session.commit()
    m2 = repo.get_model(session, model_id)
    return _model_with_aliases(session, m2)


def list_model_skus_service(session, model_id):
    return repo.list_model_skus(session, model_id)


def list_skus_service(session, country, channel_id, model_id, segment, active, page, limit):
    seg_ids = None
    if segment:
        models = repo.list_models(session)
        seg_ids = [
            m["id"] for m in models if repo.segment_of(m["price_band_anchor"]) == segment
        ]
    items, total = repo.list_skus(
        session,
        country=country,
        channel_id=channel_id,
        model_id=model_id,
        segment_ids=seg_ids,
        active=active,
        page=page,
        limit=limit,
    )
    model_map, channel_map = load_maps(session)
    out = []
    for s in items:
        m = model_map.get(s["model_id"], {})
        c = channel_map.get(s["channel_id"], {})
        out.append(
            {
                **s,
                "model": {
                    k: m.get(k)
                    for k in ("id", "marketing_code", "display_name", "brand", "is_target")
                },
                "segment": repo.segment_of(m.get("price_band_anchor", 0)),
                "channel": {
                    k: c.get(k) for k in ("id", "name", "country", "type", "health")
                },
            }
        )
    return {"items": out, "meta": page_meta(total, page, limit)}


def list_competitor_mappings_service(session):
    """Return one flat row per (DemoBrand model, competitor) pair.

    Frontend groups by `model_id` to build competitor columns. `position`
    orders rivals and identifies the primary rival (0).
    """
    model_map, _ = load_maps(session)
    rows = repo.list_competitor_mappings(session)
    out = []
    for r in rows:
        m = model_map.get(r["model_id"], {})
        comp = model_map.get(r.get("competitor_id") or "", {})
        out.append(
            {
                "id": r["id"],
                "model_id": r["model_id"],
                "model_marketing_code": m.get("marketing_code"),
                "model_display_name": m.get("display_name"),
                "competitor_id": r.get("competitor_id"),
                "competitor_marketing_code": comp.get("marketing_code"),
                "competitor_display_name": comp.get("display_name"),
                "competitor_brand": comp.get("brand"),
                "position": r.get("position", 0),
            }
        )
    out.sort(
        key=lambda x: (x["model_marketing_code"] or "", x["position"])
    )
    return {"items": out, "meta": page_meta(len(out), 1, len(out) or 1)}
