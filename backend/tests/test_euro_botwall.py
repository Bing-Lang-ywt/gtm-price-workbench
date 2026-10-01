"""Euro anti-crawl fixes: bot-wall streak + stale-first SKU ordering.

Strategy: the SKU loop's DB writes are stubbed (`record_price` + the
`crawl_runs` bookkeeping), and `_ordered_skus` runs against a real, isolated
in-memory SQLite DB (one read query, no writes to price_monitor.db). The
per-SKU fetch is mocked to simulate bot-wall hits and successes. No network,
no real browser, no production DB writes.

Key test gotcha (caught while writing): `Sku` has NO `captured_at` column.
The ordering key is `prices.captured_at` (seeded via `Price` rows), so the
`_sku` helper must pass `captured_at=` as a keyword and must NOT let it clobber
`channel_id` (the helper's 2nd positional is `channel_id`, not `captured_at`).
"""
import types

import pytest
from sqlmodel import Session as Sess, SQLModel, create_engine
from sqlalchemy.pool import StaticPool

from app.crawling.market_common import BotWallBlocked
from app.services import crawl as crawlmod
from app.models.catalog import Sku as SkuModel
from app.models.channel import Channel as ChannelModel


@pytest.fixture
def eng():
    e = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(e)
    yield e


def _patch_loop(monkeypatch, eng):
    """Stub the loop's DB-writing calls; route session creation to the in-memory DB.

    Also neutralizes the production sleeps (25s bot-wall backoff, per-SKU rate
    limiter) so the tests run in milliseconds instead of minutes, and points the
    channel's PDP fetch at our mock.
    """
    monkeypatch.setattr(crawlmod, "Session", lambda engine=None: Sess(eng))
    monkeypatch.setattr(crawlmod.crrepo, "create_run", lambda *a, **k: types.SimpleNamespace())
    monkeypatch.setattr(crawlmod.crrepo, "update_run", lambda *a, **k: None)
    monkeypatch.setattr(crawlmod, "record_price", lambda *a, **k: None)
    monkeypatch.setattr(crawlmod, "BOTWALL_BACKOFF", 0.0)
    monkeypatch.setattr(crawlmod, "CRAWL_RATE_PER_SEC", 100.0)


def _channel():
    # "Telekom HU" is a key in OPERATOR_PDP_CONFIG, so the static crawl path
    # routes through `fetch_operator_pdp` (which we mock) rather than the real
    # generic gigatron adapter.
    return ChannelModel(
        id="ch-euro", name="Telekom HU", country="HU", type="market",
        crawl_mode="static", enabled=True, base_url="https://x",
    )


def _sku(sid, channel_id="ch-euro", captured_at=None):
    # NOTE: `captured_at` is intentionally NOT a Sku column. It is accepted here
    # only so callers can pass it as a keyword without error; the real ordering
    # key comes from the Price rows seeded alongside (see the ordered-skus tests).
    return SkuModel(
        id=sid, model_id="m-x", channel_id=channel_id,
        product_url="https://x/{}".format(sid), in_stock=True,
    )


def test_streak_resets_on_success(monkeypatch, eng):
    """Bot-wall hits must NOT abort the run once a later SKU crawls.

    Order: A bot-wall, B ok, C bot-wall, D ok -> streak 1,0,1,0, never >= 3.
    The run completes (all 4 SKUs attempted, no early break), tolerated
    bot-wall hits are not hard failures, so status stays 'success'.
    """
    _patch_loop(monkeypatch, eng)
    monkeypatch.setattr(crawlmod, "ENABLE_SPA_CRAWL", True)
    monkeypatch.setattr(crawlmod, "BOTWALL_ABORT_STREAK", 3)
    hits = {"A": True, "C": True}  # bot-wall on A and C only
    attempted = []

    def fake_fetch(ch, sku, timeout=None):
        attempted.append(sku.id)
        if hits.get(sku.id):
            raise BotWallBlocked("cloudflare")
        return {"price": 100.0, "currency": "EUR", "in_stock": True}

    monkeypatch.setattr(crawlmod, "fetch_operator_pdp", fake_fetch)
    skus = [_sku("A"), _sku("B"), _sku("C"), _sku("D")]
    with Sess(eng) as s:
        s.add(_channel())
        for sk in skus:
            s.add(sk)
        s.commit()
        result = crawlmod._crawl_channel(_channel())
    # No early abort: every SKU was attempted in order.
    assert attempted == ["A", "B", "C", "D"]
    # A and C were bot-walled (no price recorded); B and D succeeded.
    assert result["items"] == 2
    assert result["status"] == "success"


def test_streak_abort_only_when_threshold_reached(monkeypatch, eng):
    """Four bot-walls in a row with threshold=1 -> abort after the first,
    status='partial' with the right error string."""
    _patch_loop(monkeypatch, eng)
    monkeypatch.setattr(crawlmod, "ENABLE_SPA_CRAWL", True)
    monkeypatch.setattr(crawlmod, "BOTWALL_ABORT_STREAK", 1)
    attempted = []

    def fake_fetch(ch, sku, timeout=None):
        attempted.append(sku.id)
        raise BotWallBlocked("akamai")

    monkeypatch.setattr(crawlmod, "fetch_operator_pdp", fake_fetch)
    skus = [_sku("A"), _sku("B"), _sku("C"), _sku("D")]
    with Sess(eng) as s:
        s.add(_channel())
        for sk in skus:
            s.add(sk)
        s.commit()
        result = crawlmod._crawl_channel(_channel())
    # Aborts immediately at the first hit; the tail is never attempted.
    assert attempted == ["A"]
    assert result["status"] == "partial"
    assert "botwall abort after 1 consecutive" in result["error"]
    assert result["items"] == 0


def test_ordered_skus_stale_first(monkeypatch, eng):
    """End-to-end: SKUs are crawled NULL -> oldest -> newest, so a partial run
    resumes from the least-recently-crawled tail next time. The real
    `_ordered_skus` drives the traversal; we record the fetch order."""
    _patch_loop(monkeypatch, eng)
    monkeypatch.setattr(crawlmod, "ENABLE_SPA_CRAWL", True)
    monkeypatch.setattr(crawlmod, "fetch_operator_pdp",
                        lambda ch, sku, timeout=None:
                        {"price": 100.0, "currency": "EUR", "in_stock": True})
    order = []

    # Wrap the mock so we capture the traversal order (real _ordered_skus feeds
    # the SKUs in staleness order to the loop, which fetches in that order).
    def tracing_fetch(ch, sku, timeout=None):
        order.append(sku.id)
        return {"price": 100.0, "currency": "EUR", "in_stock": True}

    monkeypatch.setattr(crawlmod, "fetch_operator_pdp", tracing_fetch)
    yesterday = "2026-08-10T00:00:00+00:00"
    today = "2026-08-12T00:00:00+00:00"
    with Sess(eng) as s:
        s.add(_channel())
        # `captured_at=` is a keyword here; it does NOT clobber channel_id and
        # is ignored by Sku. The ordering key is the Price rows below.
        s.add(_sku("never"))
        s.add(_sku("old", captured_at=yesterday))
        s.add(_sku("new", captured_at=today))
        s.commit()
        from app.models.price import Price

        # Seed one price each for old/new so they have a captured_at; `never`
        # stays price-less (NULL) and must sort first.
        s.add(Price(sku_id="old", channel_id="ch-euro", price_type="unlocked",
                    price=1.0, currency="EUR", amount_eur=1.0, captured_at=yesterday))
        s.add(Price(sku_id="new", channel_id="ch-euro", price_type="unlocked",
                    price=1.0, currency="EUR", amount_eur=1.0, captured_at=today))
        s.commit()
        crawlmod._crawl_channel(_channel())
    assert order == ["never", "old", "new"]


def test_ordered_skus_uses_single_aggregation_query(monkeypatch, eng):
    """`_ordered_skus` orders by MAX(prices.captured_at); NULL (never crawled)
    first, then oldest. Verified with real rows + one price each. The price-less
    SKU must NOT be dropped (that was the original starvation bug)."""
    ch = _channel()
    with Sess(eng) as s:
        s.add(ch)
        s.add(_sku("never"))
        s.add(_sku("old", captured_at="2026-08-10T00:00:00+00:00"))
        s.add(_sku("new", captured_at="2026-08-12T00:00:00+00:00"))
        s.commit()
        from app.models.price import Price

        s.add(Price(sku_id="old", channel_id="ch-euro", price_type="unlocked",
                    price=1.0, currency="EUR", amount_eur=1.0,
                    captured_at="2026-08-10T00:00:00+00:00"))
        s.add(Price(sku_id="new", channel_id="ch-euro", price_type="unlocked",
                    price=1.0, currency="EUR", amount_eur=1.0,
                    captured_at="2026-08-12T00:00:00+00:00"))
        s.commit()
        out = crawlmod._ordered_skus(s, ch)
    assert [o.id for o in out] == ["never", "old", "new"]


# --- Hardened streak tests (euroverify follow-up) -------------------------
# The original test_streak_resets_on_success above uses BOTWALL_ABORT_STREAK=3
# with only 2 bot-wall hits (A, C). Even if the streak NEVER reset, the max
# streak is 2 < 3, so the run never aborts and the test stays green either way.
# That made it a "fake green": it could not tell whether the reset logic existed.
# The two tests below ARE sensitive to the reset mechanism (threshold lowered to
# 2 so a broken reset would push the streak to the limit and abort).


def test_streak_resets_on_success_threshold2(monkeypatch, eng):
    """Threshold=2, hits A(block)/B(ok)/C(block). The streak MUST clear on B.

    If reset works: A=1, B=0, C=1 -> never >= 2 -> all 4 attempted, success.
    If reset were broken: A=1, B=1, C=2 -> abort at C (2 >= 2) -> FAIL.
    """
    _patch_loop(monkeypatch, eng)
    monkeypatch.setattr(crawlmod, "ENABLE_SPA_CRAWL", True)
    monkeypatch.setattr(crawlmod, "BOTWALL_ABORT_STREAK", 2)
    hits = {"A": True, "C": True}
    attempted = []

    def fake_fetch(ch, sku, timeout=None):
        attempted.append(sku.id)
        if hits.get(sku.id):
            raise BotWallBlocked("cloudflare")
        return {"price": 100.0, "currency": "EUR", "in_stock": True}

    monkeypatch.setattr(crawlmod, "fetch_operator_pdp", fake_fetch)
    skus = [_sku("A"), _sku("B"), _sku("C"), _sku("D")]
    with Sess(eng) as s:
        s.add(_channel())
        for sk in skus:
            s.add(sk)
        s.commit()
        result = crawlmod._crawl_channel(_channel())
    assert attempted == ["A", "B", "C", "D"]
    assert result["status"] == "success"
    assert result["items"] == 2


def test_streak_abort_consecutive_threshold2(monkeypatch, eng):
    """Two CONSECUTIVE bot-walls at threshold=2 must abort right after B."""
    _patch_loop(monkeypatch, eng)
    monkeypatch.setattr(crawlmod, "ENABLE_SPA_CRAWL", True)
    monkeypatch.setattr(crawlmod, "BOTWALL_ABORT_STREAK", 2)
    attempted = []

    def fake_fetch(ch, sku, timeout=None):
        attempted.append(sku.id)
        raise BotWallBlocked("akamai")

    monkeypatch.setattr(crawlmod, "fetch_operator_pdp", fake_fetch)
    skus = [_sku("A"), _sku("B"), _sku("C"), _sku("D")]
    with Sess(eng) as s:
        s.add(_channel())
        for sk in skus:
            s.add(sk)
        s.commit()
        result = crawlmod._crawl_channel(_channel())
    assert attempted == ["A", "B"]
    assert result["status"] == "partial"
    assert "botwall abort after 2 consecutive" in result["error"]
    assert result["items"] == 0


# --- Bug2 regression: non-bot-wall failures MUST be counted ---------------
# Uses a generic (non OPERATOR_PDP_CONFIG) channel so a raised exception reaches
# the per-SKU except handler where `failed += 1` lives. (On an OPERATOR_PDP_CONFIG
# channel a non-bot-wall error is swallowed by the inner except -> continue and
# would NOT increment `failed`; that residual gap is out of scope here.)


class _FakeGigatronAdapter:
    def __init__(self, block_ids):
        self._block = set(block_ids)

    def fetch_gigatron_product(self, url, timeout=None, expected_currency=None, **kw):
        # url is f"https://x/{sku_id}"
        sid = url.rstrip("/").rsplit("/", 1)[-1]
        if sid in self._block:
            raise RuntimeError("selector rot")
        return {"price": 100.0, "currency": "EUR", "in_stock": True}


def _generic_channel():
    return ChannelModel(
        id="ch-mkt", name="Alza", country="CZ", type="market",
        crawl_mode="static", enabled=True, base_url="https://x",
    )


def test_non_botwall_failure_reported_partial(monkeypatch, eng):
    """2 of 4 SKUs throw a non-bot-wall error -> failed=2, items=2 ->
    status='partial' with a '2 failed [...]' summary. Before the Bug2 fix
    `failed` was never incremented, so this run reported success/None."""
    _patch_loop(monkeypatch, eng)
    monkeypatch.setattr(crawlmod, "adapter_for",
                        lambda ch: _FakeGigatronAdapter({"A", "C"}))
    skus = [_sku("A", channel_id="ch-mkt"), _sku("B", channel_id="ch-mkt"),
            _sku("C", channel_id="ch-mkt"), _sku("D", channel_id="ch-mkt")]
    with Sess(eng) as s:
        s.add(_generic_channel())
        for sk in skus:
            s.add(sk)
        s.commit()
        result = crawlmod._crawl_channel(_generic_channel())
    assert result["items"] == 2
    assert result["status"] == "partial"
    assert result["error"] is not None
    assert "2 failed" in result["error"]


def test_all_non_botwall_failures_reported_failed(monkeypatch, eng):
    """Every SKU throws a non-bot-wall error -> failed=4, items=0 ->
    status='failed' (hard failure). Before the Bug2 fix this reported
    status='success', error=None — the silent degradation root cause."""
    _patch_loop(monkeypatch, eng)
    monkeypatch.setattr(crawlmod, "adapter_for",
                        lambda ch: _FakeGigatronAdapter({"A", "B", "C", "D"}))
    skus = [_sku("A", channel_id="ch-mkt"), _sku("B", channel_id="ch-mkt"),
            _sku("C", channel_id="ch-mkt"), _sku("D", channel_id="ch-mkt")]
    with Sess(eng) as s:
        s.add(_generic_channel())
        for sk in skus:
            s.add(sk)
        s.commit()
        result = crawlmod._crawl_channel(_generic_channel())
    assert result["items"] == 0
    assert result["status"] == "failed"
    assert result["error"] is not None
    assert "failed" in result["error"]
