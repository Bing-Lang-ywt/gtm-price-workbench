import logging
import time
from threading import Lock
from sqlmodel import Session, select

from app.core.db import engine
from app.models.channel import Channel
from app.services.crawl import run_crawl

log = logging.getLogger("api.crawl")

# Idempotency guard for triggerCrawl. The front-end retry path (apiFetch retries
# on 5xx / network errors) or a double-click could otherwise fire two full
# crawls. We de-dupe identical scopes within this window inside the single
# backend process (the deployment runs exactly one backend). A scoped crawl
# keyed by its channel-name set; a full crawl by the sentinel "__all__".
_TRIGGER_DEDUP_SECONDS = 300
_trigger_lock = Lock()
_last_triggers: dict = {}


def trigger_controller(channel_ids=None):
    """Trigger a crawl.

    ``channel_ids`` are channel *names* (e.g. ["DNA"]); they are resolved to
    DB primary keys before calling ``run_crawl`` so a scoped crawl works.
    Omit to run a full crawl across all enabled channels.
    """
    key = frozenset(channel_ids) if channel_ids else ("__all__",)
    now = time.monotonic()
    with _trigger_lock:
        last = _last_triggers.get(key)
        if last is not None and (now - last) < _TRIGGER_DEDUP_SECONDS:
            log.info(
                "duplicate crawl trigger ignored (key=%s, %.0fs < %ds)",
                key, now - last, _TRIGGER_DEDUP_SECONDS,
            )
            return {
                "triggered": False,
                "skipped": "duplicate",
                "within_seconds": _TRIGGER_DEDUP_SECONDS,
            }
        _last_triggers[key] = now

    if channel_ids:
        with Session(engine) as s:
            ids = [
                c.id
                for c in s.exec(
                    select(Channel).where(Channel.name.in_(channel_ids))
                ).all()
            ]
        return run_crawl(channel_ids=ids)
    return run_crawl()
