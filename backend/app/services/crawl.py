import inspect
import logging
import os
import random
import time
import json
from datetime import datetime

from sqlmodel import Session, select, func

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import (
    BOTWALL_ABORT_STREAK,
    CRAWL_CHANNEL_RATES,
    CRAWL_RATE_PER_SEC,
    CRAWL_TIMEOUT,
    SPA_CRAWL_TIMEOUT,
)
from app.core.db import engine
from app.core.time import utcnow
from app.alerting.evaluator import evaluate_stock_change
from app.crawling.currency import currency_for_channel
from app.crawling.operator_pdp import (  # noqa: E402
    ENABLE_SPA_CRAWL,
    OPERATOR_PDP_CONFIG,
    fetch_operator_pdp,
)
from app.crawling.registry import adapter_for
from app.crawling.market_common import BotWallBlocked
from app.models.catalog import Sku
from app.models.channel import Channel
from app.models.ops import CrawlRun
from app.models.price import Price
from app.repositories import crawl_runs as crrepo
from app.services.prices import record_price

log = logging.getLogger("crawl")

scheduler = BackgroundScheduler(timezone="UTC")

# Market channels behind bot walls (Alza/Cloudflare, Datart/F5 Shape) that are
# crawled on a slower weekly cadence - the user asked for "once a week" for
# these, and a full browser render per SKU is heavier than the static path.
WEEKLY_MARKET_CHANNELS = ["Alza", "Datart"]

# Operators whose PDP exposes only an OUTRIGHT device price (no monthly
# installment) - e.g. Finnish carrier DNA. Its single price is a device price,
# not a per-month fee. The generic gigatron parser would otherwise store it as
# ``contract_monthly`` (mislabeling a device price as a monthly charge and
# feeding a bogus x24 derivation downstream). So for these channels we record
# the extracted price as ``subsidy_down_payment`` (device price), matching how
# vivacom/Yettel expose their "price without subscription" line.
# NOTE: Elisa is the same Finnish pattern and should likely join this set once
# its PDP price structure is verified (see project doc).
OPERATOR_DEVICE_PRICE_CHANNELS = {"DNA"}

# When a market PDP returns a bot-wall challenge (Akamai/F5/Cloudflare), the
# egress IP is in a risk window. Hammering it only deepens the ban, so after a
# hit we pause to let the window cool before the next SKU. 25s is long enough
# to reset most per-IP rate windows without making the daily job absurd.
BOTWALL_BACKOFF = 25.0

# --- Scheduling jitter -------------------------------------------------------
# All jobs fire near a fixed UTC time but with a random offset so every
# deployment (and every day) lands at a slightly different instant. This avoids
# a synchronized thundering-herd hit on the target sites at exactly 03:00 and is
# friendlier to their rate limiters. The cadence is unchanged (still daily /
# weekly / self-heal), only the *instant* within the window is randomized.
SCHEDULE_JITTER = int(os.getenv("CRAWL_SCHEDULE_JITTER", "1800"))  # seconds (±30min)

# --- Optional UA / proxy rotation hooks --------------------------------------
# Opt-in. Populate via env to rotate egress identity per request:
#   CRAWL_UA_POOL="UA1|UA2|UA3"   CRAWL_PROXY_POOL="http://p1|http://p2"
# Adapters are only ever passed headers=/proxies= when their signature accepts
# them (inspected at call time), so rotation is a transparent no-op until the
# crawler adapters expose those kwargs - no adapter code needs to change today.
CRAWL_UA_POOL = [u for u in os.getenv("CRAWL_UA_POOL", "").split("|") if u] or None
CRAWL_PROXY_POOL = [p for p in os.getenv("CRAWL_PROXY_POOL", "").split("|") if p] or None


def select_user_agent() -> str | None:
    return random.choice(CRAWL_UA_POOL) if CRAWL_UA_POOL else None


def select_proxy() -> str | None:
    return random.choice(CRAWL_PROXY_POOL) if CRAWL_PROXY_POOL else None


def _request_kwargs(adapter_func) -> dict:
    """Build headers=/proxies= kwargs for an adapter call.

    Only includes a kwarg when ``adapter_func`` declares it, so enabling
    rotation can never raise a TypeError on adapters that don't support it yet.
    """
    sig = inspect.signature(adapter_func)
    kw: dict = {}
    if "headers" in sig.parameters:
        ua = select_user_agent()
        if ua:
            kw["headers"] = {"User-Agent": ua}
    if "proxies" in sig.parameters:
        proxy = select_proxy()
        if proxy:
            kw["proxies"] = {"http": proxy, "https": proxy}
    return kw


def _ordered_skus(session, ch: Channel):
    """SKUs for a channel, ordered so the LEAST recently crawled come first.

    Drives a self-healing crawl: a bot-wall block (or any early abort) skips the
    tail of the list, so next run we must resume from the oldest-stale SKU — not
    re-crawl the same head that just failed. Ordering by ``MAX(prices.captured_at)``
    across all price types means a SKU with a recent successful crawl sorts last,
    and SKUs that have NEVER been priced (NULL) sort first.

    Built from ONE aggregation query that maps sku_id -> latest captured_at,
    then sorted in Python. No per-SKU lookup, so it is O(1) queries (the old
    code would have been N+1 had we sorted inside the loop).
    """
    # Group THIS channel's prices by sku_id, taking the latest captured_at per
    # SKU. One aggregation query -> O(1) DB round-trips (no N+1). ``Price``
    # carries ``channel_id`` directly, so we filter on that rather than a nested
    # ``IN (subselect)`` — the subselect form mis-compiled/returned empty under
    # the StaticPool in-memory DB used by the tests (a SQLAlchemy quirk), which
    # would have reintroduced the starvation bug in CI even though it works on
    # the real SQLite file.
    # LEFT semantics: SKUs with no price rows must still appear (with a NULL
    # last_seen -> crawled first on a self-healing pass). We build the
    # sku_id -> latest captured_at map, then read the full SKU list separately
    # and merge in Python. An INNER join would silently drop price-less SKUs —
    # exactly the starvation bug we are fixing.
    sub = (
        select(
            Price.sku_id.label("sid"),
            func.max(Price.captured_at).label("last_seen"),
        )
        .where(Price.channel_id == ch.id)
        .group_by(Price.sku_id)
    )
    newest = {row.sid: row.last_seen for row in session.exec(sub).all()}
    skus = session.exec(select(Sku).where(Sku.channel_id == ch.id)).all()
    # NULL (never crawled) first, then oldest last_seen first. captured_at is a
    # string (ISO) so lexical order == chronological; NULL sorts before any value.
    return sorted(
        skus, key=lambda s: (s.id in newest, newest.get(s.id) or "")
    )


# Task #11: constant-value false-positive guard. A mis-routed or regressed
# extractor can match shared boilerplate (an insurance footnote, a single tariff
# shard, a "from X€" promo line) and write the SAME value for many SKUs in one
# channel run. That is exactly how Vodafone RO was silently poisoned with a
# constant 2600 EUR (per-SKU `price` fields differed, but `amount_eur` was the
# constant) and how Orange RO used to emit a constant "30.0 RON" shard for every
# SKU. We detect + reject such batches so a regression can never again poison the
# matrix unnoticed. See _detect_constant_value_rejects for the two signatures.
CONSTANT_VALUE_MIN = 3


def _fresh_run_prices(run_prices, run_started: str) -> list[dict]:
    """只保留**本轮新建**的价格行。

    ``record_price`` 命中去重时返回的是已存在的那一行，它的 ``captured_at``
    早于本轮开始时间。若连同本轮新行一起交给 ``_detect_constant_value_rejects``，
    命中「恒定值」判定的那一批会被 DELETE —— 于是历史数据被当成脏数据删掉：
    该 SKU 要么退回一条更早的陈旧价，要么（若那是它唯一的行）整条从矩阵消失。
    2026-09-03 Yettel BG 实测命中 3 行，所幸那几个 SKU 还有更早的行兜底。

    恒定值但价格没变（所以没落新行）的情况由 ``_channel_price_variance``
    （Task #12）在渠道层面兜住，这里只筛新建行不会漏报。
    """
    if not run_started:
        return list(run_prices)
    return [e for e in run_prices if (e.get("captured_at") or "") >= run_started]


def _detect_constant_value_rejects(run_prices):
    """Return the set of Price ids to delete from THIS run.

    Groups the run's written prices by ``price_type`` and flags two signatures:
      * A (Vodafone RO): one ``amount_eur`` shared by >=CONSTANT_VALUE_MIN SKUs
        whose raw (price, currency) values DIFFER. Same EUR but different local
        prices is impossible for a real extractor => boilerplate / FX corruption.
        (If the raw prices are also identical, the models are genuinely priced
        alike, so we KEEP them — signature A only fires when prices disagree.)
      * B (Orange RO): one (price, currency) shared by >=CONSTANT_VALUE_MIN SKUs.
        A constant raw value across many DISTINCT models is itself a red flag
        (vendors don't price N different handsets identically), so reject it.
    """
    by_type = {}
    for e in run_prices:
        by_type.setdefault(e["price_type"], []).append(e)
    reject = set()
    for entries in by_type.values():
        by_amt = {}
        by_raw = {}
        for e in entries:
            by_amt.setdefault(round(float(e["amount_eur"]), 2), []).append(e)
            by_raw.setdefault((round(float(e["price"]), 2), e["currency"]), []).append(e)
        for grp in by_amt.values():
            if len(grp) >= CONSTANT_VALUE_MIN:
                raws = {(round(float(e["price"]), 2), e["currency"]) for e in grp}
                if len(raws) > 1:  # signature A: same EUR, differing local prices
                    reject.update(e["price_id"] for e in grp)
        for grp in by_raw.values():
            if len(grp) >= CONSTANT_VALUE_MIN:  # signature B: constant raw value
                reject.update(e["price_id"] for e in grp)
    return reject


# Task #12: channel-level credibility / variance check. The per-run #11 guard
# rejects constant rows WITHIN a single run; this catches the cross-SKU /
# persistent case (the SAME price shared by >=CONSTANT_VALUE_MIN distinct
# models across the channel's CURRENT price snapshot) and is what makes a
# silent false-positive self-expose in the health panel instead of reading
# "healthy" forever. This is exactly the Vodafone RO 2600-EUR class: five days
# of an identical value would otherwise never trip the run-status logic because
# every run still "parsed" and wrote items.
def _channel_price_variance(session, ch: Channel, price_type: str) -> bool:
    """True when the channel's latest price snapshot looks like a boilerplate
    false-positive: >=CONSTANT_VALUE_MIN SKUs share one price.

    Restricted to the channel's PRIMARY price_type (operator ->
    subsidy_down_payment, market -> unlocked) so a model-invariant tariff
    monthly can never contaminate the comparison basis. Takes the LATEST price
    per SKU (prices are de-duped on unchanged values, so captured_at tracks the
    real last-seen), then applies the same two signatures as #11.
    """
    rows = session.exec(
        select(Price).where(
            Price.channel_id == ch.id, Price.price_type == price_type
        )
    ).all()
    latest: dict = {}
    for p in rows:
        cur = latest.get(p.sku_id)
        if cur is None or (p.captured_at or "") > (cur.captured_at or ""):
            latest[p.sku_id] = p
    pts = list(latest.values())
    if len(pts) < CONSTANT_VALUE_MIN:
        return False
    by_amt: dict = {}
    by_raw: dict = {}
    for p in pts:
        by_amt.setdefault(round(float(p.amount_eur or 0), 2), []).append(p)
        by_raw.setdefault((round(float(p.price or 0), 2), p.currency), []).append(p)
    for grp in by_amt.values():
        if len(grp) >= CONSTANT_VALUE_MIN:
            raws = {(round(float(p.price or 0), 2), p.currency) for p in grp}
            if len(raws) > 1:  # signature A: same EUR, differing local prices
                return True
    for grp in by_raw.values():
        if len(grp) >= CONSTANT_VALUE_MIN:  # signature B: constant raw value
            return True
    return False


def _assess_channel_health(session, ch: Channel, variance: bool | None = None) -> str:
    """Compute + return the channel's health from crawl outcome + credibility.

    healthy  : last run succeeded (or partially) and prices vary per model.
    degraded : last run degraded (constant rejected) OR the current snapshot
               shows an identical price across >=N models (silent false-positive).
    down     : last run failed (channel not yielding data).
    unknown  : never crawled (no run record at all).
    """
    if variance is None:
        pt = "subsidy_down_payment" if ch.type == "operator" else "unlocked"
        variance = _channel_price_variance(session, ch, pt)
    last = session.exec(
        select(CrawlRun)
        .where(CrawlRun.channel_id == ch.id)
        .order_by(CrawlRun.started_at.desc())
    ).first()
    if last is None:
        return "degraded" if variance else "unknown"
    st = last.status
    if st == "failed":
        return "down"
    if st == "degraded" or variance:
        return "degraded"
    return "healthy"


def reassess_all_channels():
    """One-shot: recompute + persist health for every channel (run after a
    crawler/guard change so the panel reflects reality immediately, without
    waiting for each channel's next scheduled crawl)."""
    from sqlmodel import select as _select

    with Session(engine) as session:
        changed = []
        for ch in session.exec(_select(Channel)).all():
            pt = "subsidy_down_payment" if ch.type == "operator" else "unlocked"
            variance = _channel_price_variance(session, ch, pt)
            new_h = _assess_channel_health(session, ch, variance=variance)
            if ch.health != new_h:
                ch.health = new_h
                ch.updated_at = datetime.now().isoformat()
                session.add(ch)
                changed.append((ch.name, new_h))
        session.commit()
        return changed


def run_crawl(channel_ids=None, exclude_names=None):
    """Crawl all enabled channels (or a subset). Returns per-channel results.

    ``exclude_names`` skips channels by name (used to keep the daily job off the
    weekly market channels).

    Each channel gets its OWN database session inside ``_crawl_channel`` so a
    failure or a stuck transaction in one channel cannot leak into or abort the
    others, and every session is closed deterministically (proper cleanup).
    """
    with Session(engine) as session:
        stmt = select(Channel).where(Channel.enabled == True)  # noqa: E712
        if channel_ids:
            stmt = stmt.where(Channel.id.in_(channel_ids))
        channels = session.exec(stmt).all()
    if exclude_names:
        channels = [c for c in channels if c.name not in exclude_names]
    results = []
    for i, ch in enumerate(channels):
        if i > 0:
            # Breathing room between channels to avoid cross-domain rate-limiting.
            # Small random jitter so channels don't march in perfect lockstep.
            time.sleep(3.0 + random.uniform(0, 2.0))
        results.append(_crawl_channel(ch))
    # Snapshot this crawl's prices into the dated Excel price-history sheet.
    try:
        from app.services.price_excel import append_crawl_prices
        append_crawl_prices(datetime.now().strftime("%m月%d日"))
    except Exception as exc:  # noqa: BLE001
        log.warning("price-history excel append failed: %s", exc)
    return results


def _crawl_channel(ch: Channel):
    # Own session per channel: isolates failures and guarantees cleanup even if
    # a channel's loop raises (the outer try/except rolls back + closes it).
    with Session(engine) as session:
        run = crrepo.create_run(session, ch.id, "running")
        session.commit()
        items = 0
        error = ""
        error_detail = ""  # 完整失败明细（JSON），不截断
        status = "success"
        failed = 0
        failures = []  # (sku_id, error_type) accumulated for the run summary
        # Consecutive bot-wall hits. A single block no longer aborts the channel;
        # we only give up once we hit BOTWALL_ABORT_STREAK in a row, and ANY
        # successfully crawled SKU resets the counter (so a one-off block that
        # clears on retry never starves the rest of the list). (Euro anti-crawl fix.)
        botwall_streak = 0
        # Task #11 buffer: every Price written this run, for the post-loop
        # constant-value guard. (price_id lets us delete precisely, no
        # captured_at guesswork.)
        #
        # run_started pins「本轮新建」的界线，见下面 guard 调用处的说明 ——
        # 去重命中时 record_price 返回的是**已有历史行**，不能拿它当本轮产物删掉。
        run_started = utcnow().isoformat()
        run_prices = []
        try:
            adapter = adapter_for(ch)
            skus = _ordered_skus(session, ch)
            for sku in skus:
                # Per-channel rate override: altex.ro tolerates occasional
                # requests but refuses rapid-fire streams with
                # ERR_HTTP2_PROTOCOL_ERROR, so it needs ~20s spacing.
                _rate = CRAWL_CHANNEL_RATES.get(ch.name, CRAWL_RATE_PER_SEC)
                time.sleep(1.0 / max(_rate, 0.1))
                try:
                    # Initialized up-front so the `if data is None:` test below can
                    # never raise UnboundLocalError for SKUs whose product_url is empty
                    # or for list-mode channels (which never touch `data`).
                    data = None
                    used_generic = False
                    if ch.crawl_mode == "static":
                        if not sku.product_url:
                            # Nothing to crawl for this SKU; leave prices empty.
                            continue
                        # Plan A: validated operator channels use a dedicated
                        # device-price extractor (browser render + per-site label)
                        # because the generic parser grabs monthly/contract totals.
                        if ENABLE_SPA_CRAWL and ch.name in OPERATOR_PDP_CONFIG:
                            try:
                                data = fetch_operator_pdp(ch, sku, timeout=SPA_CRAWL_TIMEOUT)
                            except BotWallBlocked:
                                # MUST propagate to the per-SKU handler below so the
                                # bot-wall streak counter / abort logic (see line ~302)
                                # actually runs for OPERATOR_PDP_CONFIG channels. If we
                                # swallowed it here (data=None -> continue), a sustained
                                # block would silently skip the channel tail and the run
                                # would still report "success" with the streak never
                                # incrementing. (Euro/Akamai anti-crawl fix.)
                                raise
                            except Exception as exc:  # noqa: BLE001
                                log.warning("operator pdp failed %s: %s", sku.id, exc)
                                data = None
                        if data is None:
                            if ch.name in OPERATOR_PDP_CONFIG:
                                # configured but unextractable -> skip, keep DB clean
                                continue
                            # Pin the currency from the channel's market; the
                            # page-text guess used to mislabel entire countries.
                            # UA/proxy rotation hook is applied only if the adapter
                            # accepts those kwargs (no-op otherwise).
                            data = adapter.fetch_gigatron_product(
                                sku.product_url,
                                timeout=SPA_CRAWL_TIMEOUT,
                                expected_currency=currency_for_channel(ch),
                                **_request_kwargs(adapter.fetch_gigatron_product),
                            )
                            # Non-config operator: the generic parser only ever sees the
                            # monthly installment, so store it as contract_monthly and let
                            # the post-crawl derivation fill subsidy_down_payment.
                            used_generic = True
                        prev_stock = sku.in_stock
                        # Operator channels captured via the dedicated extractor expose a
                        # real device total -> store as subsidy_down_payment. The generic
                        # gigatron parser only ever sees the monthly installment for the
                        # non-configured operators, so that path stores contract_monthly;
                        # derive_operator_device_totals() then fills subsidy_down_payment
                        # (= monthly x 24). Market channels always use unlocked.
                        if ch.type == "operator":
                            # Operators with only an outright device price
                            # (no monthly installment) store that price as
                            # subsidy_down_payment; all other operators use the
                            # generic monthly figure and get a derived x24 total.
                            if used_generic and ch.name not in OPERATOR_DEVICE_PRICE_CHANNELS:
                                price_type = "contract_monthly"
                            else:
                                price_type = "subsidy_down_payment"
                        else:
                            price_type = "unlocked"
                        new_price = record_price(
                            session,
                            sku.id,
                            ch.id,
                            price_type,
                            data["price"],
                            data["currency"],
                            data["in_stock"],
                            evaluate=True,
                            meta=data.get("meta"),
                            original_price=data.get("original_price"),
                            gift=data.get("gift"),
                        )
                        if new_price is not None:
                            run_prices.append({
                                "price_id": new_price.id,
                                "price_type": price_type,
                                "price": data["price"],
                                "currency": data["currency"],
                                "amount_eur": new_price.amount_eur,
                                "captured_at": new_price.captured_at,
                            })
                        # A config operator extractor MAY return a native monthly, but
                        # ONLY if it is a genuine DEVICE INSTALMENT (varies per model).
                        # A plan-inclusive total bill must NOT come through here: this
                        # column is compared across channels, so a tariff-laden figure
                        # would make that operator look several times more expensive
                        # (Yettel HU's "Havonta fizetendő" is exactly that case -> it
                        # goes to meta.monthly_payable and is rendered as an annotation).
                        # derive_operator_device_totals() leaves a plausible native
                        # monthly untouched: Branch A skips config subsidies, Branch B
                        # keeps non-contaminated native monthlies (and skips 0 subsidy).
                        _monthly = data.get("contract_monthly")
                        if ch.type == "operator" and _monthly:
                            new_price2 = record_price(
                                session,
                                sku.id,
                                ch.id,
                                "contract_monthly",
                                _monthly,
                                data["currency"],
                                data["in_stock"],
                                evaluate=False,
                                meta=data.get("meta"),
                            )
                            if new_price2 is not None:
                                run_prices.append({
                                    "price_id": new_price2.id,
                                    "price_type": "contract_monthly",
                                    "price": _monthly,
                                    "currency": data["currency"],
                                    "amount_eur": new_price2.amount_eur,
                                    "captured_at": new_price2.captured_at,
                                })
                        if prev_stock and not data["in_stock"]:
                            evaluate_stock_change(session, sku.id, False)
                        sku.in_stock = data["in_stock"]
                        session.add(sku)
                        items += 1
                        botwall_streak = 0  # a successful fetch clears the streak
                    elif ch.crawl_mode == "list":
                        data = adapter.fetch_operator_list(ch, sku, timeout=SPA_CRAWL_TIMEOUT)
                        if data:
                            for price_type, price, currency in data:
                                record_price(
                                    session,
                                    sku.id,
                                    ch.id,
                                    price_type,
                                    price,
                                    currency,
                                    True,
                                    evaluate=True,
                                )
                            items += 1
                            botwall_streak = 0  # a successful fetch clears the streak
                        # No parseable data -> leave empty (MVP SPA fallback).
                except Exception as exc:  # noqa: BLE001
                    failures.append((sku.id, type(exc).__name__))
                    log.warning(
                        "crawl sku failed",
                        extra={
                            "channel": ch.name,
                            "sku": str(sku.id),
                            "error_type": type(exc).__name__,
                        },
                    )
                    if isinstance(exc, BotWallBlocked):
                        log.info(
                            "bot wall hit on %s; backing off %.0fs to cool egress IP",
                            ch.name, BOTWALL_BACKOFF,
                        )
                        time.sleep(BOTWALL_BACKOFF)
                        botwall_streak += 1
                        # A *run* of blocks means the egress IP is in a sustained
                        # risk window; stop hammering before we deepen the ban.
                        # One or two isolated hits are tolerated and we keep going,
                        # so the tail of the channel is no longer starved. Only a
                        # consecutive run (>= BOTWALL_ABORT_STREAK) flips the run to
                        # partial; a tolerated hit that later clears is reported as
                        # success once a SKU crawls. (Euro anti-crawl fix.)
                        if botwall_streak >= BOTWALL_ABORT_STREAK:
                            error = (
                                f"botwall abort after {botwall_streak} consecutive"
                            )
                            break
                    else:
                        # A real (non-bot-wall) SKU failure: timeout, selector rot,
                        # parse crash. `failed` drives the post-loop status/error
                        # summary and was previously NEVER incremented, so
                        # `elif failed:` below was dead code and a channel where
                        # most SKUs threw still reported status="success",
                        # error=None. That silent degradation is exactly how
                        # low-coverage channels rotted unnoticed.
                        failed += 1
            # A tolerated (non-aborting) bot-wall hit is deliberately NOT counted
            # in `failed`: it does not downgrade the run on its own. The post-loop
            # block derives status from failed/error/items.
            #
            # Operators: make sure every SKU has a device-financing total. Channels
            # with a native total keep it; the rest get subsidy_down_payment derived
            # from their monthly installment (x24). Runs after each crawl so the fix
            # is permanent, not a one-off backfill.
            if ch.type == "operator":
                try:
                    from app.services.operator_device_total import (
                        derive_operator_device_totals,
                    )
                    n = derive_operator_device_totals(session, ch)
                    if n:
                        log.info("derived device totals for %s: %d sku(s)", ch.name, n)
                except Exception as exc:  # noqa: BLE001
                    log.warning("device-total derivation failed for %s: %s", ch.name, exc)

            # Task #11: constant-value false-positive guard. Runs after the
            # per-SKU loop + device-total derivation. Deletes any Price rows that
            # match a constant-value signature in THIS run, so a regressed
            # extractor can never silently poison the matrix again (the Vodafone
            # RO 2600-EUR / Orange RO 30.0-RON class of silent false-positive).
            constant_rejected = 0
            try:
                # 只把**本轮新建**的行交给 guard —— 去重命中的历史行绝不能删，
                # 详见 _fresh_run_prices 的说明。
                rejected_ids = _detect_constant_value_rejects(
                    _fresh_run_prices(run_prices, run_started)
                )
                if rejected_ids:
                    stale = session.exec(
                        select(Price).where(Price.id.in_(rejected_ids))
                    ).all()
                    for r in stale:
                        session.delete(r)
                    items -= len(stale)
                    constant_rejected = len(stale)
                    log.warning(
                        "constant-value guard deleted %d poisoned price row(s) for %s",
                        len(stale), ch.name,
                    )
            except Exception as exc:  # noqa: BLE001
                log.warning("constant-value guard failed (non-fatal): %s", exc)

            if error:
                # An explicit abort / captured error means the run did not
                # complete cleanly -> report partial (never success).
                status = "partial"
            elif failed:
                # Compact, queryable failure summary instead of only the last
                # error (the old behaviour). All SKUs failed => hard failure;
                # some succeeded => partial. Tolerated bot-wall hits are NOT
                # counted in `failed`, so a run that hit a block then recovered
                # is reported as success.
                status = "failed" if items == 0 else "partial"
                summary = ", ".join(f"{sid}:{et}" for sid, et in failures[:8])
                error = f"{failed} failed [{summary}]"
                # LOW: 完整明细（不止前 8 条）供排查，JSON 序列化。
                error_detail = json.dumps(failures, ensure_ascii=False)
            elif items == 0:
                status = "partial"
            # Task #11: a constant-value rejection downgrades the run even when
            # every SKU technically "parsed" — a channel that emitted a shared
            # constant is NOT healthy.
            if constant_rejected:
                error = (error + "; " if error else "") + (
                    f"constant_value guard rejected {constant_rejected} poisoned row(s)"
                )
                status = "degraded" if items > 0 else "failed"
            # Task #12: channel-level variance / credibility check. The per-run
            # #11 guard deletes constant rows WITHIN a run; this catches the
            # cross-SKU / persistent case (same price shared by >=N models across
            # the channel's current snapshot) and downgrades health so a silent
            # false-positive can never again read "healthy".
            ch_price_type = "subsidy_down_payment" if ch.type == "operator" else "unlocked"
            variance = _channel_price_variance(session, ch, ch_price_type)
            if variance:
                error = (error + "; " if error else "") + (
                    "channel variance: identical price across multiple SKUs"
                )
                if status not in ("failed",):
                    status = "degraded" if items > 0 else "failed"
            # Persist channel health from crawl outcome + credibility. This is
            # the field the health panel reads — previously it was only ever set
            # at seed time, so dead/fake channels kept showing their stale value.
            new_health = _assess_channel_health(session, ch, variance=variance)
            # ch 可能是别的 session 取来的游离对象：直接 session.add(ch) 会被
            # 当成 INSERT 并撞 UNIQUE 约束（channels.id），整个 run 因此崩进
            # except 分支。按主键重新取一次，确保走的是 UPDATE。
            db_ch = session.get(Channel, ch.id)
            if db_ch is not None:
                db_ch.health = new_health
                db_ch.updated_at = datetime.now().isoformat()
                session.add(db_ch)
            run.error_detail = error_detail
            crrepo.update_run(
                session, run, status=status, items=items, error=error, finished=True
            )
            session.commit()
            return {"channel_id": ch.id, "status": status, "items": items, "error": error}
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            # 只写库不落日志的话，这个分支等于把异常吞掉：run.error_detail 在
            # 内存库 / 被 stub 的场景下永远读不到，排查时完全看不到堆栈。
            log.exception("crawl channel %s crashed", getattr(ch, "name", ch.id))
            run.error_detail = f"{type(exc).__name__}: {exc}"
            crrepo.update_run(
                session,
                run,
                status="failed",
                error=f"{type(exc).__name__}: {exc}"[:500],
                finished=True,
            )
            session.commit()
            return {"channel_id": ch.id, "status": "failed", "error": str(exc)[:200]}


def _daily_job():
    try:
        # Daily job covers everything EXCEPT the weekly market channels.
        run_crawl(exclude_names=WEEKLY_MARKET_CHANNELS)
    except Exception as exc:  # noqa: BLE001
        log.exception("scheduled crawl failed: %s", exc)


def _weekly_market_job():
    """Weekly pass over Alza/Datart: discovers newly added models *and*
    refreshes prices. Plain ``run_crawl`` would only refresh existing SKUs, so a
    model added mid-quarter would never show up on these channels."""
    try:
        from app.services.market_seed import seed_market_channels

        results = seed_market_channels(WEEKLY_MARKET_CHANNELS)
        for r in results:
            log.info("weekly market %s: recorded=%d missing=%d",
                     r["channel"], r["recorded"], len(r["missing"]))
    except Exception as exc:  # noqa: BLE001
        log.exception("weekly market crawl failed: %s", exc)


def _market_retry_job():
    """Daily self-heal for the weekly channels.

    Datart sits behind F5 Shape, which hard-blocks an IP for a while once it
    sees volume. Waiting a full week to retry would leave a hole in the
    comparison matrix, so every day we re-run *only* the channels whose data is
    stale or whose coverage is incomplete. Healthy channels are untouched, so
    this adds no load in the normal case.
    """
    try:
        from app.services.market_seed import (
            seed_market_channels,
            stale_market_channels,
        )

        stale = stale_market_channels(WEEKLY_MARKET_CHANNELS)
        if not stale:
            return
        log.info("market self-heal retry for: %s", stale)
        for r in seed_market_channels(stale):
            log.info("retry %s: recorded=%d missing=%d",
                     r["channel"], r["recorded"], len(r["missing"]))
    except Exception as exc:  # noqa: BLE001
        log.exception("market retry failed: %s", exc)


def _all_channel_names():
    with Session(engine) as session:
        return [c.name for c in session.exec(select(Channel)).all()]


def start_scheduler():
    if not scheduler.running:
        # All jobs keep their fixed UTC anchor but fire at a randomized instant
        # within +/- SCHEDULE_JITTER seconds, so every deployment and every day
        # avoids a synchronized hit on the target sites. Cadence is unchanged.
        scheduler.add_job(
            _daily_job, "cron", hour=3, minute=0, id="daily_crawl",
            jitter=SCHEDULE_JITTER,
        )
        # Weekly market channels (Alza/Datart) - every Monday 03:00 UTC.
        scheduler.add_job(
            _weekly_market_job, "cron", day_of_week="mon", hour=3, minute=0,
            id="weekly_market_crawl", jitter=SCHEDULE_JITTER,
        )
        # Self-heal: retry only the weekly channels that are stale/incomplete.
        scheduler.add_job(
            _market_retry_job, "cron", hour=4, minute=30, id="market_retry",
            jitter=SCHEDULE_JITTER,
        )
        scheduler.start()
        log.info("crawler scheduler started "
                 "(daily 03:00±jitter, weekly-mon 03:00±jitter, self-heal 04:30±jitter UTC)")


def shutdown_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
