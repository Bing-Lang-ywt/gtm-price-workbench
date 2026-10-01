"""Shared headless-Chromium pool for every crawler that needs a real browser.

Why this module exists
----------------------
Playwright's **sync** API refuses to run inside a thread that owns a running
asyncio event loop::

    It looks like you are using Playwright Sync API inside the asyncio loop.
    Please use the Async API instead.

Both FastAPI request handlers and APScheduler jobs execute inside an event
loop, so any crawl triggered from the API or the nightly scheduler hit that
error. The previous per-module implementations then latched a module-level
``_BROWSER_OK = False`` flag, which **permanently** disabled browser crawling
for the rest of the process lifetime - one request in an event loop poisoned
every later crawl until the service was restarted.

Two fixes, both applied here:

1. **Thread confinement.** All Playwright work is marshalled onto one
   dedicated daemon thread that never runs an event loop. This satisfies the
   sync API and also respects Playwright's thread-affinity rule (its objects
   may only be touched from the thread that created them).
2. **Recoverable breaker.** A launch failure now sets an exponential-backoff
   cooldown instead of a permanent kill-switch, so a transient failure (cold
   start, OOM, missing display) heals itself on the next attempt.

Callers never touch Playwright directly; they hand a callable to
``run_in_browser`` which receives the live ``browser`` object::

    def job(browser):
        page = browser.new_page()
        try:
            page.goto(url)
            return page.content()
        finally:
            page.close()

    html = run_in_browser(job, timeout=60)   # None when unavailable
"""
from __future__ import annotations

import atexit
import logging
import os
import queue
import threading
import time
from concurrent.futures import Future

log = logging.getLogger("crawl.browser")

ENABLE_SPA_CRAWL = os.getenv("ENABLE_SPA_CRAWL", "0") == "1"

LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    # Critical for market channels behind bot walls (Alza/Cloudflare,
    # Datart/F5 Shape): hiding the automation flag is what lets a headless
    # Chromium pass their challenges. Verified 2026-08-03 - headless + this
    # arg + a real UA + the navigator.webdriver patch (see adapters) succeeds
    # where plain headless was caught with "Just a moment...".
    "--disable-blink-features=AutomationControlled",
]
# Drop Playwright's default --enable-automation so sites can't fingerprint the
# browser as controlled. The adapters additionally patch navigator.webdriver
# per-context for defence in depth.
LAUNCH_KWARGS = {"ignore_default_args": ["--enable-automation"]}
# Optional: point the SPA crawler at a system Chromium/Chrome when the bundled
# Playwright browser cannot be downloaded (offline/sandboxed hosts).
CHROME_EXECUTABLE_PATH = os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH") or None
LAUNCH_TIMEOUT = 90          # seconds to wait for Chromium cold start
DEFAULT_JOB_TIMEOUT = 120    # seconds a single browser job may take
BACKOFF_STEPS = (30, 60, 300)  # cooldown after 1st / 2nd / 3rd+ launch failure


def _resolve_proxy() -> "dict | None":
    """Build a Playwright proxy dict from HTTP(S)_PROXY env, or None.

    Playwright's bundled Chromium does NOT read the HTTPS_PROXY env var on
    its own, so the SPA/stealth crawlers would silently ignore a proxy unless
    we hand it to ``chromium.launch(proxy=...)``. This lets operators route
    the browser through a clean egress (VPN / residential proxy / VPS) to dodge
    Akamai / Vercel / Cloudflare IP bans without touching crawler code.
    """
    raw = (
        os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
        or os.getenv("https_proxy") or os.getenv("http_proxy")
    )
    if not raw:
        return None
    server = raw if "://" in raw else "http://" + raw
    from urllib.parse import urlparse
    parsed = urlparse(server)
    # Never treat a loopback / private proxy as a real egress route. The agent
    # sandbox and some dev setups export HTTP_PROXY=127.0.0.1:<port> for their
    # own transparent proxying; handing that to Chromium would make every
    # outbound request fail. Only a non-private host is a valid crawl egress.
    host = (parsed.hostname or "").lower()
    if (
        host == "localhost" or host == "127.0.0.1" or host == "::1"
        or host.startswith("192.168.") or host.startswith("10.")
        or host.startswith("172.16.") or host.startswith("172.17.")
        or host.startswith("172.18.") or host.startswith("172.19.")
        or host.startswith("172.2") or host.startswith("172.3")
        or host.endswith(".internal") or host.endswith(".localhost")
    ):
        return None
    proxy: dict = {"server": server, "bypass": "localhost,127.0.0.1"}
    if parsed.username:
        proxy["username"] = parsed.username
        proxy["password"] = parsed.password or ""
    return proxy


# MED-3: a small pool of workers instead of one. A single render that hangs
# (slow bot-wall challenge, detached page) used to poison the ONLY worker and
# serialise every other channel's SPA behind it. With N workers a hung job only
# takes one slot; the pool tops itself back up so the rest keep crawling.
# Raise BROWSER_WORKERS on memory-rich hosts (each worker is a full Chromium).
BROWSER_WORKERS = int(os.getenv("BROWSER_WORKERS", "2"))
_WORKERS: list = []
_NEXT = 0
_LOCK = threading.RLock()
_launch_failures = 0
_cooldown_until = 0.0
_job_failures = 0
_jobs_run = 0
_pool_unavailable = 0
_job_timeouts = 0


class BrowserUnavailable(RuntimeError):
    """The Playwright worker could not provide a usable browser."""


class BrowserJobTimeout(BrowserUnavailable):
    """A job outlived its deadline; the worker was retired mid-render.

    Distinct from a plain launch failure so callers (and /health) can tell
    "the site never finished rendering" from "we never had a browser at all".
    Subclasses BrowserUnavailable so existing handlers keep working.
    """


class _PlaywrightWorker:
    """Owns a sync Playwright driver + Chromium on one dedicated thread."""

    def __init__(self) -> None:
        self._jobs: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._pw = None
        self._browser = None
        self._poisoned = False
        self._thread = threading.Thread(
            target=self._run, name="playwright-worker", daemon=True
        )
        self._thread.start()

    # -- worker thread ----------------------------------------------------
    def _run(self) -> None:
        try:
            from playwright.sync_api import sync_playwright

            self._pw = sync_playwright().start()
            proxy = _resolve_proxy()
            launch_kwargs = {
                "headless": True,
                "args": LAUNCH_ARGS,
                **({"executable_path": CHROME_EXECUTABLE_PATH}
                   if CHROME_EXECUTABLE_PATH else {}),
                **LAUNCH_KWARGS,
            }
            if proxy:
                launch_kwargs["proxy"] = proxy
                log.info("headless browser proxy enabled: %s", proxy["server"])
            self._browser = self._pw.chromium.launch(**launch_kwargs)
        except BaseException as exc:  # noqa: BLE001 - report, never crash
            self._error = exc
            self._ready.set()
            return
        self._ready.set()

        while True:
            item = self._jobs.get()
            if item is None:
                break
            fn, fut = item
            if not fut.set_running_or_notify_cancel():
                continue
            try:
                fut.set_result(fn(self._browser))
            except BaseException as exc:  # noqa: BLE001 - surface to caller
                fut.set_exception(exc)
        self._teardown()

    def _teardown(self) -> None:
        # Close the browser *and* stop the driver; the old code leaked the
        # driver subprocess because it never called pw.stop().
        for closer in (
            getattr(self._browser, "close", None),
            getattr(self._pw, "stop", None),
        ):
            if closer is None:
                continue
            try:
                closer()
            except Exception:  # noqa: BLE001
                pass
        self._browser = None
        self._pw = None

    # -- public -----------------------------------------------------------
    def wait_ready(self, timeout: float = LAUNCH_TIMEOUT) -> None:
        if not self._ready.wait(timeout):
            raise BrowserUnavailable(f"Chromium launch timed out after {timeout}s")
        if self._error is not None:
            raise BrowserUnavailable(str(self._error).strip().splitlines()[0])
        if self._browser is None:
            raise BrowserUnavailable("Chromium launch produced no browser")

    @property
    def alive(self) -> bool:
        return (
            not self._poisoned
            and self._thread.is_alive()
            and self._error is None
            and self._browser is not None
        )

    def submit(self, fn, timeout: float):
        fut: Future = Future()
        self._jobs.put((fn, fut))
        try:
            return fut.result(timeout=timeout)
        except TimeoutError:
            # The worker thread is still stuck on this job and is single
            # threaded, so it can never serve anyone else. Retire it.
            self._poisoned = True
            raise BrowserJobTimeout(f"browser job exceeded {timeout}s") from None

    def stop(self) -> None:
        self._poisoned = True
        self._jobs.put(None)
        self._thread.join(timeout=15)


# ---------------------------------------------------------------- lifecycle
def _acquire() -> "_PlaywrightWorker | None":
    """Return the next live worker (round-robin), or None while the breaker is
    cooling down. Maintains a pool of ``BROWSER_WORKERS`` Chromium instances:
    dead ones are retired (without a blocking join — the daemon thread exits on
    its own once the stuck render times out) and the pool is topped back up.
    """
    global _WORKERS, _NEXT, _launch_failures, _cooldown_until

    with _LOCK:
        alive = []
        for w in _WORKERS:
            if w.alive:
                alive.append(w)
            else:
                # Poisoned/retired: drop the reference; the daemon thread and its
                # Chromium wind down on their own. No blocking join here so a
                # hung worker can never stall the whole acquisition path.
                w._poisoned = True
        _WORKERS = alive

        cooling = _cooldown_until - time.monotonic()
        if cooling > 0:
            log.debug("browser breaker cooling down, %.0fs left", cooling)
            return None

        while len(_WORKERS) < BROWSER_WORKERS:
            worker = _PlaywrightWorker()
            try:
                worker.wait_ready()
            except BaseException as exc:  # noqa: BLE001
                _launch_failures += 1
                backoff = BACKOFF_STEPS[min(_launch_failures, len(BACKOFF_STEPS)) - 1]
                _cooldown_until = time.monotonic() + backoff
                log.warning(
                    "headless browser unavailable (failure #%d, retry in %ds): %s",
                    _launch_failures, backoff, exc,
                )
                worker._poisoned = True
                break
            _launch_failures = 0
            _cooldown_until = 0.0
            _WORKERS.append(worker)
            log.info(
                "headless Chromium launched (%d/%d workers ready)",
                len(_WORKERS), BROWSER_WORKERS,
            )

        if not _WORKERS:
            return None
        w = _WORKERS[_NEXT % len(_WORKERS)]
        _NEXT = (_NEXT + 1) % len(_WORKERS)
        return w


def browser_available() -> bool:
    """True when SPA crawling is enabled and a browser can be obtained."""
    if not ENABLE_SPA_CRAWL:
        return False
    return _acquire() is not None


def run_in_browser(fn, timeout: float = DEFAULT_JOB_TIMEOUT, *, required: bool = False):
    """Run ``fn(browser)`` on the Playwright thread.

    Returns the callable's result, or ``None`` when the browser is unavailable
    or the job raised. Set ``required=True`` to re-raise instead.
    """
    global _job_failures, _jobs_run, _pool_unavailable, _job_timeouts

    if not ENABLE_SPA_CRAWL:
        if required:
            raise BrowserUnavailable("ENABLE_SPA_CRAWL is not set")
        return None

    worker = _acquire()
    if worker is None:
        _pool_unavailable += 1
        if required:
            raise BrowserUnavailable("browser unavailable (breaker open)")
        return None

    try:
        result = worker.submit(fn, timeout=timeout)
    except BaseException as exc:  # noqa: BLE001
        _job_failures += 1
        if isinstance(exc, BrowserJobTimeout):
            _job_timeouts += 1
        log.warning("browser job failed: %s", exc)
        if required:
            raise
        return None
    _jobs_run += 1
    return result


def shutdown_browser() -> None:
    """Tear down every worker; the next call transparently relaunches the pool."""
    global _WORKERS, _launch_failures, _cooldown_until
    with _LOCK:
        for w in _WORKERS:
            w._poisoned = True
            try:
                w.stop()
            except Exception:  # noqa: BLE001
                pass
        _WORKERS = []
        _launch_failures = 0
        _cooldown_until = 0.0


def browser_status() -> dict:
    """Snapshot for health endpoints and diagnostics."""
    with _LOCK:
        cooldown = max(0.0, _cooldown_until - time.monotonic())
        alive_count = sum(1 for w in _WORKERS if w.alive)
        return {
            "enabled": ENABLE_SPA_CRAWL,
            "alive": alive_count > 0,
            "launch_failures": _launch_failures,
            "cooldown_seconds": round(cooldown, 1),
            "jobs_run": _jobs_run,
            "job_failures": _job_failures,
            # Split of job_failures so a red /health can be read without logs:
            # timeouts mean pages that never finished rendering, pool_unavailable
            # means we never even got a browser (breaker open / SPA disabled).
            "job_timeouts": _job_timeouts,
            "pool_unavailable": _pool_unavailable,
            # MED-3: the pool now holds N workers; surface the counts so a
            # partially-degraded pool (e.g. 1/2 alive after a hang) is visible.
            "workers_total": len(_WORKERS),
            "workers_alive": alive_count,
        }


atexit.register(shutdown_browser)
