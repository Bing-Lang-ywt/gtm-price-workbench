"""triggerCrawl idempotency (audit C12).

A repeated trigger (double-click / front-end retry on a lost 5xx response)
must NOT fire a second full crawl inside the de-dup window.
"""
import app.controllers.crawl as ctrl


def test_trigger_dedup_within_window(monkeypatch):
    calls = []

    def fake_run_crawl(channel_ids=None):
        calls.append(channel_ids)
        return {"channel_id": "x", "status": "running"}

    monkeypatch.setattr(ctrl, "run_crawl", fake_run_crawl)
    ctrl._last_triggers.clear()

    r1 = ctrl.trigger_controller()
    r2 = ctrl.trigger_controller()

    assert "skipped" not in r1
    assert r2.get("skipped") == "duplicate"
    assert len(calls) == 1  # 第二次被去重，未真正触发


def test_trigger_different_scope_not_deduped(monkeypatch):
    calls = []

    def fake_run_crawl(channel_ids=None):
        calls.append(channel_ids)
        return {"channel_id": "x", "status": "running"}

    monkeypatch.setattr(ctrl, "run_crawl", fake_run_crawl)
    ctrl._last_triggers.clear()

    ctrl.trigger_controller()                 # 全量
    ctrl.trigger_controller(["DNA"])          # 指定渠道 -> 不同 key

    assert len(calls) == 2
