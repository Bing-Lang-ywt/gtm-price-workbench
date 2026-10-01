from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy import event, text

from app.core.config import DB_URL

connect_args = {"check_same_thread": False} if DB_URL.startswith("sqlite") else {}

engine = create_engine(DB_URL, echo=False, connect_args=connect_args)

# P0-1: enable WAL + busy_timeout on every sqlite connection. The background
# scheduler writes (crawl job) and API requests (manual price / triggerCrawl)
# hit the same SQLite file concurrently; the default DELETE journal deadlocks
# on "database is locked". WAL lets readers proceed during a write, and
# busy_timeout makes concurrent writers wait instead of erroring out.
if DB_URL.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, conn_record):
        cur = dbapi_conn.cursor()
        try:
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=30000")
        finally:
            cur.close()


def _migrate() -> None:
    """Add columns introduced after the initial schema.

    SQLModel's ``create_all`` only creates *missing tables*, never alters
    existing ones, so a new column on a live database (e.g. ``CrawlRun.error_detail``)
    must be added explicitly here or it silently never exists on prod DBs.
    """
    with engine.connect() as conn:
        existing = {
            r[1] for r in conn.execute(text("PRAGMA table_info(crawl_runs)")).fetchall()
        }
        if "error_detail" not in existing:
            conn.execute(
                text(
                    "ALTER TABLE crawl_runs ADD COLUMN error_detail TEXT NOT NULL DEFAULT ''"
                )
            )
            conn.commit()


def init_db() -> None:
    """Create all tables. Importing models registers them on SQLModel.metadata."""
    from app import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    _migrate()


def get_session():
    with Session(engine) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
