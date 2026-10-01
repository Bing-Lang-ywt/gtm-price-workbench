"""Browser pool multi-worker (MED-3) + status contract.

The existing ``test_p2_thirteen`` already locks the ``run_in_browser`` /
``browser_status`` public contract (old keys preserved). These tests pin the
NEW pool behaviour: the worker count is configurable and ``browser_status``
exposes pool size even when SPA crawl is disabled.
"""
import pytest

from app.crawling import browser_pool as bp


def test_browser_workers_configured():
    assert isinstance(bp.BROWSER_WORKERS, int)
    assert bp.BROWSER_WORKERS >= 1


def test_browser_status_exposes_pool_counts(monkeypatch):
    # SPA crawl is off in the test environment -> no workers are spawned, but
    # the new aggregate keys must still be present (backwards-compatible add).
    monkeypatch.setattr(bp, "ENABLE_SPA_CRAWL", False)
    status = bp.browser_status()
    assert "workers_total" in status
    assert "workers_alive" in status
    assert status["workers_total"] == 0
    assert status["enabled"] is False
    # legacy keys retained for /health consumers
    for legacy in ("alive", "launch_failures", "cooldown_seconds",
                   "jobs_run", "job_failures", "job_timeouts", "pool_unavailable"):
        assert legacy in status
