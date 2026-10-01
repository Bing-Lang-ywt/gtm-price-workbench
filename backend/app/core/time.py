from datetime import datetime, timezone


def utcnow() -> datetime:
    """Naive UTC datetime (SQLite stores naive timestamps)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
