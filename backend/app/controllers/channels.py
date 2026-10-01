from sqlmodel import Session

from app.core.db import engine
from app.models.channel import Channel
from app.services import channels as svc


def list_channels_controller(session, country, type, page, limit):
    return svc.list_channels_service(session, country, type, page, limit)


def get_channel_controller(session, channel_id):
    return svc.get_channel_service(session, channel_id)


def list_crawl_runs_controller(session, channel_id, status, page, limit):
    return svc.list_crawl_runs_service(session, channel_id, status, page, limit)


def trigger_channel_controller(channel_id):
    from app.services.crawl import run_crawl

    with Session(engine) as s:
        ch = s.get(Channel, channel_id)
        if not ch:
            return None
    return run_crawl(channel_ids=[channel_id])
