"""Task #11 常量值拦截的作用域：只能删本轮新建的行。

背景（2026-09-03 Yettel BG 实测）：``record_price`` 是 upsert 式去重，价格没变
时返回的是**已存在的历史行**。而常量值 guard 拿到 ``price_id`` 就 DELETE ——
于是「去重命中的历史行」被当成脏数据删掉，SKU 要么退回一条更早的陈旧价，要么
（若那是它唯一的行）整条从矩阵消失。

这个用例锁死 ``_fresh_run_prices`` 的界线：只有 captured_at 不早于本轮开始的
行才能进 guard。
"""
from __future__ import annotations

from app.services.crawl import _fresh_run_prices

RUN_STARTED = "2026-09-03T15:00:00.000000"


def _entry(price_id: str, captured_at: str, price: float = 999.0) -> dict:
    return {
        "price_id": price_id,
        "price_type": "subsidy_down_payment",
        "price": price,
        "currency": "EUR",
        "amount_eur": price,
        "captured_at": captured_at,
    }


def test_deduped_historical_rows_are_excluded():
    """去重命中的历史行（时间戳早于本轮开始）必须被排除。"""
    rows = [
        _entry("old-1", "2026-09-02T04:00:00.000000"),
        _entry("old-2", "2026-09-01T04:00:00.000000"),
    ]
    assert _fresh_run_prices(rows, RUN_STARTED) == []


def test_rows_written_this_run_are_kept():
    rows = [
        _entry("new-1", "2026-09-03T15:00:00.000000"),  # 正好等于界线 → 保留
        _entry("new-2", "2026-09-03T15:04:12.123456"),
    ]
    assert [e["price_id"] for e in _fresh_run_prices(rows, RUN_STARTED)] == [
        "new-1", "new-2",
    ]


def test_mixed_run_keeps_only_the_fresh_half():
    """真实一轮抓取是新旧混在一起的：只留新的那部分。"""
    rows = [
        _entry("old-1", "2026-09-02T04:00:00.000000"),
        _entry("new-1", "2026-09-03T15:02:00.000000"),
        _entry("old-2", "2026-08-30T04:00:00.000000"),
        _entry("new-2", "2026-09-03T15:03:00.000000"),
        _entry("new-3", "2026-09-03T15:04:00.000000"),
    ]
    assert [e["price_id"] for e in _fresh_run_prices(rows, RUN_STARTED)] == [
        "new-1", "new-2", "new-3",
    ]


def test_missing_captured_at_is_treated_as_historical():
    """拿不到时间戳就当历史行：宁可不删，也不要误删。"""
    rows = [{"price_id": "x", "price": 999.0, "currency": "EUR", "amount_eur": 999.0}]
    assert _fresh_run_prices(rows, RUN_STARTED) == []


def test_empty_run_started_keeps_everything():
    """没给界线时不做过滤（兼容旧调用方），行为与改动前一致。"""
    rows = [_entry("a", "2026-09-02T04:00:00.000000")]
    assert _fresh_run_prices(rows, "") == rows
