from app.repositories import channels as crepo, crawl_runs as crrepo
from app.repositories.base import page_meta


def list_channels_service(session, country, type, page, limit):
    items, total = crepo.list_channels(
        session, country=country, type=type, page=page, limit=limit
    )
    return {"items": items, "meta": page_meta(total, page, limit)}


def get_channel_service(session, channel_id):
    c = crepo.get_channel(session, channel_id)
    return c.model_dump() if c else None


def list_crawl_runs_service(session, channel_id, status, page, limit):
    items, total = crrepo.list_by_channel(
        session, channel_id, status=status, page=page, limit=limit
    )
    return {"items": items, "meta": page_meta(total, page, limit)}
