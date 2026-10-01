import os
import secrets
import sys
from pathlib import Path

# Load deployment secrets from deploy/.env (gitignored, never committed). This
# is the single source of truth for SECRET_KEY / DEV_PASSWORD in production.
# Real credentials MUST NOT live in source code.
_DOTENV_PATH = Path(__file__).resolve().parents[3] / "deploy" / ".env"


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (no third-party dep). Sets vars only if unset."""
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())
    except FileNotFoundError:
        pass


_load_dotenv(_DOTENV_PATH)

DB_URL = os.getenv("DATABASE_URL", "sqlite:///./price_monitor.db")

# SECRET_KEY: required. Falls back to a freshly generated ephemeral key (with a
# warning) so the process never runs on a shared, hardcoded literal.
SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY:
    SECRET_KEY = secrets.token_hex(32)
    print(
        "WARNING: SECRET_KEY not set; generated an ephemeral key (JWTs reset on "
        "restart). Set SECRET_KEY in deploy/.env for production.",
        file=sys.stderr,
    )
JWT_ALG = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = int(os.getenv("ACCESS_TOKEN_EXPIRE_HOURS", "8"))

DEV_EMAIL = os.getenv("DEV_EMAIL", "analyst@example.com")
# DEV_PASSWORD: sourced from deploy/.env. No real password lives in source — if
# unset, login is disabled rather than falling back to a known credential.
DEV_PASSWORD = os.getenv("DEV_PASSWORD", "")
if not DEV_PASSWORD:
    print(
        "WARNING: DEV_PASSWORD not set; login disabled. Set DEV_PASSWORD in deploy/.env.",
        file=sys.stderr,
    )
DEV_ROLE = "analyst"

# 按市场拆分的分析师账号。真实凭据只存 deploy/.env 的 MARKET_ACCOUNTS_JSON
# （gitignored），格式：{"email": {"password": "...", "role": "analyst", "market": "塞尔维亚"}}
# 解析失败或未配置时为空 dict（不影响现有 DEV_EMAIL 登录）。
_MARKET_JSON = os.getenv("MARKET_ACCOUNTS_JSON", "")
MARKET_ACCOUNTS: dict[str, dict] = {}
if _MARKET_JSON:
    try:
        import json as _json

        _parsed = _json.loads(_MARKET_JSON)
        if isinstance(_parsed, dict):
            MARKET_ACCOUNTS = {
                str(k): {
                    "password": str(v.get("password", "")),
                    "role": str(v.get("role", "analyst")),
                    "market": str(v.get("market", "")),
                }
                for k, v in _parsed.items()
                if isinstance(v, dict) and v.get("password")
            }
    except Exception as _e:  # noqa: BLE001 - config must never crash on bad input
        print(
            f"WARNING: MARKET_ACCOUNTS_JSON parse failed: {_e}",
            file=sys.stderr,
        )

ALERT_DROP_THRESHOLD_PCT = float(os.getenv("ALERT_DROP_THRESHOLD_PCT", "3.0"))

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

CRAWL_RATE_PER_SEC = float(os.getenv("CRAWL_RATE_PER_SEC", "0.7"))
CRAWL_TIMEOUT = float(os.getenv("CRAWL_TIMEOUT", "10"))

# Per-channel crawl-rate overrides (requests/second). altex.ro rate-limits
# rapid-fire requests with ERR_HTTP2_PROTOCOL_ERROR while tolerating
# occasional ones, so it needs ~20s spacing (0.05 rps) instead of the global
# 0.7 rps. Keyed on Channel.name; unknown names fall back to the global rate.
#
# Media Markt (HU) sits behind a Cloudflare challenge and silently rate-limits
# a fast burst: a 0.7 rps pass trips its risk window partway through a 20-SKU
# channel and leaves the tail (incl. H600 / H600 Pro) frozen on stale August
# prices. ~16s spacing (0.06 rps) keeps every SKU under the limit. (2026-09-07)
CRAWL_CHANNEL_RATES: dict[str, float] = {
    "Altex": float(os.getenv("ALTEX_CRAWL_RATE_PER_SEC", "0.05")),
    "Media Markt": float(os.getenv("MEDIAMARKT_CRAWL_RATE_PER_SEC", "0.06")),
}

# SPA / stealth-rendered channels (Alza/Datart/Euro/Gigantti bot-walls and
# operator PDPs) need a far longer timeout than static pages to get past
# Cloudflare/Akamai/F5. Feeding them the generic 10s CRAWL_TIMEOUT starves the
# render and yields systematic data gaps (B2 audit finding).
SPA_CRAWL_TIMEOUT = float(os.getenv("SPA_CRAWL_TIMEOUT", "40"))

# SPA headless crawling (P1). Off by default; requires playwright + Chromium.
# Set ENABLE_SPA_CRAWL=1 and run `playwright install chromium` to activate.
ENABLE_SPA_CRAWL = os.getenv("ENABLE_SPA_CRAWL", "0") == "1"

# Default operator contract term (months) used to derive device-financing
# TOTALS from monthly installments. This is the single source of truth for the
# *default* term; the per-channel override lives in ``Channel.contract_term_months``
# (P2-12). Kept here so every term-related knob has one home rather than a
# magic number buried in operator_device_total.py.
DEFAULT_CONTRACT_TERM_MONTHS = int(os.getenv("DEFAULT_CONTRACT_TERM_MONTHS", "24"))

# Bot-wall resilience (Euro / Alza / Datart anti-crawl). When a market PDP
# returns a bot-wall challenge the egress IP enters a risk window; we back off
# to let it cool. A *single* hit used to `break` the whole SKU loop, which
# permanently starved the tail of the channel's SKU list (Euro lost its last 8
# SKUs every run). Now we count *consecutive* bot-wall hits and only abort when
# the streak reaches this threshold; any successful SKU resets it to 0, so a
# one-off block no longer kills the channel.
BOTWALL_ABORT_STREAK = int(os.getenv("BOTWALL_ABORT_STREAK", "3"))

# Cross-channel outlier guard (price_audit). An absolute band (PLAUSIBLE_BANDS)
# is not enough: a Redmi 15C priced €2 615 still sits inside the (50, 3000) EUR
# band while the same model's cross-channel median is €143 — 18x off, a clear
# mis-parse. We flag a price as `cross_channel_outlier` when it deviates from
# its model's same-price-type median by more than these ratios. Only stamp the
# flag (never delete / rewrite / guess the correct value); a human verifies it.
# The LOWER bound is deliberately loose: legitimate operator subsidies land at
# 0.3–0.4x the median (Yettel HU DemoBrand 600 €135 vs €499, several Telemach SKUs
# at 0.3x) and must NOT be flagged.
OUTLIER_HI_RATIO = float(os.getenv("OUTLIER_HI_RATIO", "3.0"))
OUTLIER_LO_RATIO = float(os.getenv("OUTLIER_LO_RATIO", "0.25"))
# Minimum number of same-model/same-price-type samples before we trust the
# median. Too few -> the median is statistically meaningless and cold-start
# channels would be flagged on a single lopsided comparison.
OUTLIER_MIN_SAMPLES = int(os.getenv("OUTLIER_MIN_SAMPLES", "5"))

ENABLE_SCHEDULER = os.getenv("ENABLE_SCHEDULER", "0") == "1"

# 爬虫新鲜度 / 覆盖率监控 (MED-2)。过去爬虫静默挂掉、某渠道 N 天没抓到价、
# 或覆盖率过低都无人告警。/api/v1/crawl/staleness 暴露这些指标，配合定时巡检
# 即可第一时间发现"爬虫已死但看板还在显示旧数据"的情况。
CRAWL_STALE_DAYS = int(os.getenv("CRAWL_STALE_DAYS", "2"))
# 覆盖率低于该百分比视为异常（该渠道大量 SKU 长期无价）。
CRAWL_LOW_COVERAGE_PCT = float(os.getenv("CRAWL_LOW_COVERAGE_PCT", "50"))
