"""Write crawl prices into the workbook as ONE COLUMN PER DAY (price history).

This module is owned by FEATURE 3. It is called once per full crawl by
``app.services.crawl.run_crawl`` (after that crawl's prices are already in the
DB). On the first call it copies the user's read-only competitor-links workbook
into the project data dir, then rebuilds the dated price columns from the DB.

USER DECISION (daily history, from 2026-08-08): every crawl REBUILDS the dated
price columns so that **one column per day is kept**, headed by that day's date
(e.g. "08月10日"), in chronological left-to-right order, starting from
``START_DATE``. Old days are NOT discarded — the table accumulates a daily price
series. This replaces the earlier single-column design that overwrote column G
and pruned previous days.

A-F (国家/渠道/渠道类型/品牌/产品/链接) are preserved; the 链接 column is
refreshed from the DB (skus.product_url) for the matching (渠道, 产品) key, since
the original Excel's 链接 column is known-corrupted and the DB is the source of
truth.
"""

import logging
import os
import re
import shutil
from datetime import date, datetime, timedelta

from openpyxl import load_workbook
from sqlmodel import Session, select

from app.core.db import engine
from app.models.catalog import Sku, Model
from app.models.channel import Channel
from app.models.price import Price

logger = logging.getLogger(__name__)

# Paths. ROOT_DIR = project root. price_excel.py sits at
# backend/app/services/ (one dir deeper than export.py at backend/app/routes/),
# so it needs 4 dirname levels: services -> app -> backend -> <project root>.
# This MUST match backend/app/routes/export.py's _ROOT (project root) so the
# file this module WRITES is exactly what the export endpoint READS.
ROOT_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
DATA_DIR = os.path.join(ROOT_DIR, "data")
TARGET = os.path.join(DATA_DIR, "price_history.xlsx")
SOURCE = os.getenv("PRICE_LINKS_XLSX_PATH", os.path.join(DATA_DIR, "demo_links.xlsx"))

# First price column. A-F are static (国家/渠道/渠道类型/品牌/产品/链接); all
# columns from DATE_START_COL rightward are dated price columns we manage.
DATE_START_COL = 7
_DATE_HEADER_RE = re.compile(r"^\d{1,2}月\d{1,2}日$")

# Daily history starts from this date (user request: "从8号开始").
START_DATE = date(2026, 8, 8)

# Column headers (matched by exact stripped text).
CHANNEL_HEADER = "渠道"
PRODUCT_HEADER = "产品"
LINK_HEADER = "链接"


def _is_date_header(text: str) -> bool:
    return bool(_DATE_HEADER_RE.match((text or "").strip()))


def _day_label(d: date) -> str:
    return d.strftime("%m月%d日")


def _date_columns(ws):
    """Return 1-based column indices (from DATE_START_COL rightward) whose header
    is a dated price column. Non-date columns (e.g. 状态) are left untouched."""
    return [
        c
        for c in range(DATE_START_COL, ws.max_column + 1)
        if _is_date_header(ws.cell(1, c).value)
    ]


def _parse_cap(cap) -> datetime:
    """Parse a captured_at value (ISO string or datetime) to a naive datetime."""
    if isinstance(cap, datetime):
        dt = cap
    else:
        dt = datetime.fromisoformat(str(cap))
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt


def _load_prices_since(start: date):
    """Load every price captured on/after ``start - 1 day`` once, grouped by sku.

    Returns {sku_id: [(cap_dt, price_type, price, currency, amount_eur), ...]}
    sorted ascending by captured_at, so as-of-day lookup is a cheap walk.
    """
    floor = _parse_cap((start - timedelta(days=1)).strftime("%Y-%m-%d") + "T00:00:00")
    with Session(engine) as session:
        rows = session.exec(
            select(
                Price.sku_id,
                Price.captured_at,
                Price.price_type,
                Price.price,
                Price.currency,
                Price.amount_eur,
            ).where(Price.captured_at >= floor.strftime("%Y-%m-%dT%H:%M:%S"))
        ).all()

    by_sku: dict = {}
    for sku_id, cap, ptype, price, cur, eur in rows:
        by_sku.setdefault(sku_id, []).append((_parse_cap(cap), ptype, price, cur, eur))
    for lst in by_sku.values():
        lst.sort(key=lambda t: t[0])  # ascending captured_at
    return by_sku


def _price_as_of(sku_prices, day_end_dt: datetime, want_type: str):
    """Latest price for a sku captured on/before ``day_end_dt``.

    Prefers the channel-correct price_type (operator -> subsidy_down_payment,
    market -> unlocked); falls back to any price type if that type has no row
    yet for the day. Returns the (price, currency, amount_eur) tuple or None.
    """
    best_typed = None
    best_any = None
    for cap_dt, ptype, price, cur, eur in sku_prices:
        if cap_dt > day_end_dt:
            break
        if best_any is None:
            best_any = (price, cur, eur)
        if ptype == want_type and best_typed is None:
            best_typed = (price, cur, eur)
    return best_typed or best_any


def _price_on_day(sku_prices, day_date: date, want_type: str):
    """Latest price for a sku as-of ``day_date``, with a 14-day tolerance.

    Strict "captured exactly on day_date" caused the download table to flicker
    '—' for one of the two operator price types whenever ``subsidy_down_payment``
    and ``contract_monthly`` were crawled on different days (the old "当日化"
    rule required *every* type to share the global max crawl day).

    New rule: each ``price_type`` independently takes its OWN most-recent row
    captured within the 14-day window ending at ``day_date`` (inclusive). A type
    whose latest row is older than 14 days is still shown as '—' -- we do NOT
    blindly inherit stale prices (preserves the 2026-08-11 "don't show if not
    recently captured" intent, just relaxed from strict-today to 14d-latest).

    Returns the (price, currency, amount_eur) tuple or None. Prefers the
    channel-correct ``want_type``; falls back to any type within the window.
    """
    window_start = day_date - timedelta(days=14)
    best_typed = None
    best_any = None
    for cap_dt, ptype, price, cur, eur in sku_prices:
        if cap_dt.date() > day_date:
            break  # sku_prices is ascending; nothing later can qualify.
        if cap_dt.date() < window_start:
            continue  # too old -- outside the 14-day window.
        # Keep overwriting so the LAST matching row (closest to day_date, i.e.
        # the most recent within the window) wins.
        best_any = (price, cur, eur)
        if ptype == want_type:
            best_typed = (price, cur, eur)
    return best_typed or best_any


def _build_day_lookups(start: date, end: date):
    """Build {(channel.name, model.display_name): {url, {day_label: price_str}}}
    for every day in [start, end] that has DB data.

    Prices come from the DB as-of each day, so each column reflects that day's
    real snapshot rather than the latest crawl only.
    """
    with Session(engine) as session:
        channels = {c.id: c for c in session.exec(select(Channel)).all()}
        models = {m.id: m for m in session.exec(select(Model)).all()}
        skus = session.exec(select(Sku)).all()

        # All candidate days: distinct DB capture-days within range.
        day_rows = session.exec(
            select(Price.captured_at)
            .where(Price.captured_at >= start.strftime("%Y-%m-%d"))
            .where(Price.captured_at <= (end + timedelta(days=1)).strftime("%Y-%m-%d"))
        ).all()
    day_set = sorted({r[0:10] if isinstance(r, str) else str(r)[:10] for r in day_rows})
    # Keep only days >= START_DATE.
    days = [d for d in day_set if datetime.strptime(d, "%Y-%m-%d").date() >= start]
    days.sort()

    by_sku = _load_prices_since(start)

    # (channel, product) -> {day_label: price_str}; also carry url (latest).
    lookup: dict = {}
    for sku in skus:
        channel = channels.get(sku.channel_id)
        model = models.get(sku.model_id)
        if channel is None or model is None:
            continue
        key = (channel.name, model.display_name)
        want_type = (
            "subsidy_down_payment" if channel.type == "operator" else "unlocked"
        )
        sku_prices = by_sku.get(sku.id, [])
        day_prices: dict = {}
        for d in days:
            d_date = datetime.strptime(d, "%Y-%m-%d").date()
            pa = _price_on_day(sku_prices, d_date, want_type)
            day_prices[_day_label(datetime.strptime(d, "%Y-%m-%d").date())] = (
                f"{pa[0]:.2f} {pa[1]} (€{pa[2]:.2f})" if pa else "—"
            )
        lookup[key] = {"url": sku.product_url, "days": day_prices}

    return lookup, [_day_label(datetime.strptime(d, "%Y-%m-%d").date()) for d in days]


def append_crawl_prices(crawl_date: str | None = None) -> str:
    """Rebuild the dated price columns of data/price_history.xlsx from the DB.

    One column per day from START_DATE to today, in chronological order, each
    headed by its date label and holding that day's as-of prices. Old days are
    preserved (history accumulates). ``crawl_date`` is accepted for API
    compatibility but the rebuild always reflects the full DB history so far.

    Returns the absolute path of the file.
    """
    today = date.today()
    if not os.path.exists(TARGET):
        os.makedirs(DATA_DIR, exist_ok=True)
        if not os.path.exists(SOURCE):
            raise FileNotFoundError(f"Source Excel not found: {SOURCE}")
        shutil.copy(SOURCE, TARGET)

    wb = load_workbook(TARGET, keep_vba=False)
    ws = wb.active

    # Locate static header columns by exact stripped text.
    ch_col = prod_col = link_col = None
    for c in range(1, ws.max_column + 1):
        val = ws.cell(1, c).value
        if val is None:
            continue
        name = str(val).strip()
        if name == CHANNEL_HEADER:
            ch_col = c
        elif name == PRODUCT_HEADER:
            prod_col = c
        elif name == LINK_HEADER:
            link_col = c

    if ch_col is None or prod_col is None:
        raise ValueError(
            "Required headers not found: 渠道 and/or 产品 missing in header row."
        )
    if link_col is None:
        logger.warning("链接 header not found; link refresh skipped.")
    if link_col is not None and link_col in (ch_col, prod_col):
        logger.warning("链接 header overlaps 渠道/产品; link refresh skipped.")
        link_col = None

    # Drop EVERYTHING from DATE_START_COL rightward (prior per-day date columns
    # *and* any leftover SOURCE reference columns like 能否打开/产品对应/价格 that
    # an earlier bug had overwritten with price values). This leaves A-F
    # (国家/渠道/渠道类型/品牌/产品/链接) intact and lets the daily price series
    # start from a clean, fixed column so headers and values stay aligned.
    for c in range(ws.max_column, DATE_START_COL - 1, -1):
        ws.delete_cols(c, 1)

    lookup, day_labels = _build_day_lookups(START_DATE, today)
    if not day_labels:
        logger.warning("No DB prices from %s onward; leaving price columns empty.",
                       START_DATE.isoformat())

    # Append one column per day, left-to-right in chronological order. Date
    # columns begin immediately after the last static column so the header row
    # and the value cells stay aligned. (Earlier code wrote values from the
    # fixed DATE_START_COL=7, which for the current 9-column source put them 3
    # columns left of their headers and silently dropped the most recent days.)
    first_date_col = ws.max_column + 1
    col = first_date_col
    for label in day_labels:
        ws.cell(1, col).value = label
        col += 1

    for r in range(2, ws.max_row + 1):
        key = (ws.cell(r, ch_col).value, ws.cell(r, prod_col).value)
        entry = lookup.get(key)
        if entry is not None and link_col is not None and entry["url"]:
            ws.cell(r, link_col).value = entry["url"]
        if entry is not None:
            for i, label in enumerate(day_labels):
                ws.cell(r, first_date_col + i).value = entry["days"].get(label, "—")
        else:
            for i in range(len(day_labels)):
                ws.cell(r, first_date_col + i).value = "—"

    wb.save(TARGET)
    logger.info("rebuilt price_history.xlsx: %d day column(s) from %s",
                len(day_labels), day_labels[0] if day_labels else "(none)")
    return os.path.abspath(TARGET)


if __name__ == "__main__":
    # SAFE DRY RUN: operate on a /tmp copy, never the real data/ file.
    import sys

    DRY_TARGET = "/tmp/price_history_test.xlsx"
    if os.path.exists(DRY_TARGET):
        os.remove(DRY_TARGET)
    shutil.copy(SOURCE, DRY_TARGET)
    saved = TARGET
    TARGET = DRY_TARGET  # noqa: N816  (override module constant for dry run)
    try:
        path = append_crawl_prices(sys.argv[1] if len(sys.argv) > 1 else None)
        print("DRY RUN OK ->", path)
    finally:
        TARGET = saved  # noqa: N816
        if os.path.exists(DRY_TARGET):
            os.remove(DRY_TARGET)
            print("cleaned up", DRY_TARGET)
