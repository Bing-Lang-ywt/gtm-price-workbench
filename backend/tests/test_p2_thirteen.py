"""P2-13: tell render failures apart from parse failures (audit B3, partial).

The full B3 ask was "multi-worker pool + per-host limit + distinguish render
failure from parse failure". Only the failure-classification half is
implemented (see docs/p2_implementation_report.md for why the pool rewrite was
deliberately deferred), so these tests cover exactly that half:

* ``operator_pdp._classify_pdp_result`` maps a fetch outcome onto
  pool / render / parse / ok, and ``fetch_operator_pdp`` tallies it.
* ``browser_pool`` counts breaker hits and job timeouts separately instead of
  lumping everything into ``job_failures``.

No network, no DB, no real browser: the browser is a hand-rolled fake.
"""
import types

from app.crawling import browser_pool as bp
from app.crawling import operator_pdp as op


# --------------------------------------------------------------- classifier
def test_classify_none_is_pool_failure():
    """run_in_browser returning None means the job never ran at all."""
    assert op._classify_pdp_result(None) == "pool"


def test_classify_render_sentinel():
    assert op._classify_pdp_result({"failure": "render"}) == "render"


def test_classify_parse_sentinel():
    assert op._classify_pdp_result({"failure": "parse"}) == "parse"


def test_classify_real_price_is_ok():
    assert op._classify_pdp_result({"price": 444.99}) == "ok"


# ------------------------------------------------------- fake browser plumbing
class _FakePage:
    """Minimal Playwright page stand-in.

    ``body_text`` is served for the ``document.body.innerText`` evaluate; every
    other evaluate returns a product name. Set ``explode=True`` to simulate a
    crashed/detached page (a *render* failure).
    """

    def __init__(self, body_text: str = "", explode: bool = False):
        self.body_text = body_text
        self.explode = explode
        self.closed = False

    def goto(self, url, timeout=None, wait_until=None):
        return None

    def evaluate(self, js):
        if self.explode:
            raise RuntimeError("Execution context was destroyed")
        if "document.body.innerText" in js and "h1" not in js:
            return self.body_text
        return "Samsung Galaxy S25"

    def wait_for_timeout(self, ms):
        return None

    def close(self):
        self.closed = True


class _FakeBrowser:
    def __init__(self, page):
        self._page = page

    def new_page(self):
        return self._page


def _run_pdp(monkeypatch, page):
    """Drive fetch_operator_pdp against a fake page, returning (result, page)."""
    monkeypatch.setattr(op, "ENABLE_SPA_CRAWL", True)
    monkeypatch.setattr(op, "PDP_FAILURES", {"pool": 0, "render": 0, "parse": 0})

    def fake_run_in_browser(fn, timeout=None, **kw):
        return fn(_FakeBrowser(page))

    monkeypatch.setattr(op, "run_in_browser", fake_run_in_browser)

    channel = types.SimpleNamespace(name="Yettel BG")
    sku = types.SimpleNamespace(product_url="https://yettel.bg/p/galaxy-s25")
    return op.fetch_operator_pdp(channel, sku, timeout=5)


def test_rendered_page_without_price_is_parse_failure(monkeypatch):
    """Page loaded fine, label missing -> 'parse' (extraction rules rotted)."""
    page = _FakePage(body_text="Разгледай нашите оферти. Няма цена тук.")
    assert _run_pdp(monkeypatch, page) is None
    assert op.PDP_FAILURES["parse"] == 1
    assert op.PDP_FAILURES["render"] == 0
    assert page.closed is True


def test_crashed_page_is_render_failure(monkeypatch):
    """Page blew up mid-render -> 'render', NOT a parse problem."""
    page = _FakePage(explode=True)
    assert _run_pdp(monkeypatch, page) is None
    assert op.PDP_FAILURES["render"] == 1
    assert op.PDP_FAILURES["parse"] == 0


def test_unavailable_browser_is_pool_failure(monkeypatch):
    """No browser at all -> 'pool'; says nothing about the channel's selectors."""
    monkeypatch.setattr(op, "ENABLE_SPA_CRAWL", True)
    monkeypatch.setattr(op, "PDP_FAILURES", {"pool": 0, "render": 0, "parse": 0})
    monkeypatch.setattr(op, "run_in_browser", lambda fn, timeout=None, **kw: None)

    channel = types.SimpleNamespace(name="Yettel BG")
    sku = types.SimpleNamespace(product_url="https://yettel.bg/p/x")
    assert op.fetch_operator_pdp(channel, sku, timeout=5) is None
    assert op.PDP_FAILURES["pool"] == 1
    assert op.PDP_FAILURES["parse"] == 0


def test_successful_extraction_still_returns_price(monkeypatch):
    """Regression guard: the sentinel refactor must not break the happy path."""
    page = _FakePage(body_text="Устройство 444.99 € 870.32 лв")
    out = _run_pdp(monkeypatch, page)
    assert out is not None
    assert out["price"] == 444.99
    assert out["currency"] == "EUR"
    assert op.PDP_FAILURES == {"pool": 0, "render": 0, "parse": 0}


# ------------------------------------------------------------- browser_pool
def test_job_timeout_is_a_browser_unavailable_subclass():
    """Existing `except BrowserUnavailable` handlers must keep catching it."""
    assert issubclass(bp.BrowserJobTimeout, bp.BrowserUnavailable)


def test_breaker_open_counts_pool_unavailable(monkeypatch):
    monkeypatch.setattr(bp, "ENABLE_SPA_CRAWL", True)
    monkeypatch.setattr(bp, "_acquire", lambda: None)
    monkeypatch.setattr(bp, "_pool_unavailable", 0)
    monkeypatch.setattr(bp, "_job_failures", 0)

    assert bp.run_in_browser(lambda browser: "x") is None
    assert bp._pool_unavailable == 1
    # Never got a browser, so this is not a *job* failure.
    assert bp._job_failures == 0


def test_job_timeout_counted_separately(monkeypatch):
    class _TimeoutWorker:
        def submit(self, fn, timeout):
            raise bp.BrowserJobTimeout("browser job exceeded 30s")

    monkeypatch.setattr(bp, "ENABLE_SPA_CRAWL", True)
    monkeypatch.setattr(bp, "_acquire", lambda: _TimeoutWorker())
    monkeypatch.setattr(bp, "_job_timeouts", 0)
    monkeypatch.setattr(bp, "_job_failures", 0)

    assert bp.run_in_browser(lambda browser: "x") is None
    assert bp._job_timeouts == 1
    assert bp._job_failures == 1


def test_plain_job_error_is_not_a_timeout(monkeypatch):
    class _BrokenWorker:
        def submit(self, fn, timeout):
            raise RuntimeError("selector blew up")

    monkeypatch.setattr(bp, "ENABLE_SPA_CRAWL", True)
    monkeypatch.setattr(bp, "_acquire", lambda: _BrokenWorker())
    monkeypatch.setattr(bp, "_job_timeouts", 0)
    monkeypatch.setattr(bp, "_job_failures", 0)

    assert bp.run_in_browser(lambda browser: "x") is None
    assert bp._job_failures == 1
    assert bp._job_timeouts == 0


def test_browser_status_keeps_old_keys_and_adds_split():
    """/health consumers must not break: additive keys only."""
    status = bp.browser_status()
    for legacy in (
        "enabled", "alive", "launch_failures",
        "cooldown_seconds", "jobs_run", "job_failures",
    ):
        assert legacy in status
    assert "job_timeouts" in status
    assert "pool_unavailable" in status
