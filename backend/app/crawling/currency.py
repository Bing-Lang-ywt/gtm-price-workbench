"""Authoritative currency resolution for crawled prices.

Why this exists
---------------
The generic parser used to *guess* the currency by scanning the whole page
text for tokens like ``EUR|€``, ``RON|lei``, ``BGN|лв`` and falling back to
``RSD``. Three ways that goes wrong, all observed in production data:

* **No word boundaries.** ``lei`` matched inside unrelated words, so Polish
  retailers (Mediaexpert, Plus) were labelled ``RON``. Their prices were then
  converted with the RON rate and under-reported by ~40%.
* **Any stray token wins.** A cookie banner, footer or currency-switcher
  mentioning "EUR" outranked the actual price currency.
* **Wrong default.** Unknown pages fell back to ``RSD``, so Bulgarian sites
  were labelled Serbian dinar.

Currency is a property of the **market a channel sells in**, not something to
infer from page copy. So the channel's country is the source of truth; page
sniffing is only a cross-check that logs a mismatch, and a last resort for
channels we have not mapped.
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger("crawl.currency")

# Country -> ISO-4217 code the channel actually charges in.
COUNTRY_CURRENCY = {
    "Serbia": "RSD",
    "Hungary": "HUF",
    "Croatia": "EUR",   # eurozone since 2023
    "Romania": "RON",
    "Poland": "PLN",
    "Finland": "EUR",
    # Bulgaria adopted the euro; shops still dual-display BGN alongside EUR,
    # and the EUR figure is the one we compare on.
    "Bulgaria": "EUR",
    # Czech Republic charges in koruna; ~25 CZK to the euro.
    "Czech Republic": "CZK",
}

# Per-channel override for anything that deviates from its country default.
CHANNEL_CURRENCY: dict[str, str] = {}

# Bulgaria's euro changeover fixed rate. Not a floating FX rate — it is the
# legally fixed conversion the shops themselves print on the dual-price tag.
BGN_PER_EUR = 1.95583

# Matches the dual price tag Bulgarian shops print, e.g.
#   "1,073.75 лв./ 549.00 €"   "1 953.87 лв. / 999.00 €"
_BG_DUAL_RE = re.compile(
    r"([\d][\d\s.,]{1,12}?)\s*лв\.?\s*/?\s*([\d][\d\s.,]{1,12}?)\s*€",
    re.I,
)


def _num(raw: str) -> float | None:
    """Parse '1,073.75' / '1 953.87' / '549.00' -> float."""
    s = re.sub(r"[\s\u00a0]", "", raw or "")
    if not s:
        return None
    # Both separators present: the last one is the decimal point.
    if "," in s and "." in s:
        s = s.replace(",", "") if s.rfind(".") > s.rfind(",") else \
            s.replace(".", "").replace(",", ".")
    elif "," in s:
        # A lone comma is a decimal comma only when it fences 1-2 digits.
        s = s.replace(",", ".") if len(s.split(",")[-1]) <= 2 else s.replace(",", "")
    try:
        return float(re.sub(r"[^0-9.]", "", s))
    except ValueError:
        return None


def bg_dual_price_eur(page_text: str, parsed_price: float) -> float | None:
    """Correct a Bulgarian dual-priced page that was parsed in lev.

    Bulgaria adopted the euro but shops still print both figures side by side
    ("1,073.75 лв./ 549.00 €"). The generic parser reads structured data
    (JSON-LD / meta tags) which on several BG sites still carries the *lev*
    number, while the channel currency map labels it EUR. Nothing converts it,
    so the price lands in the DB 1.9558x too high — observed on technomarket
    for 17 of 18 products (DemoBrand 600 stored as 1073.75 EUR; the page says
    549.00 €).

    Returns the euro figure when the page shows a lev/euro pair whose ratio is
    the fixed changeover rate *and* ``parsed_price`` is the lev side. Returns
    None when there is no reliable pair — a wrong price is worse than no
    correction, so we never guess.
    """
    if not page_text or not parsed_price:
        return None
    for m in _BG_DUAL_RE.finditer(page_text):
        lev, eur = _num(m.group(1)), _num(m.group(2))
        if not lev or not eur:
            continue
        # The pair must actually be the same amount at the fixed rate.
        if abs(lev / eur - BGN_PER_EUR) > 0.01:
            continue
        # ...and the number we parsed must be the lev side of that pair.
        if abs(parsed_price - lev) <= max(0.02, lev * 0.001):
            log.warning(
                "BG dual-price: parsed %.2f is the lev figure; using %.2f EUR",
                parsed_price, eur,
            )
            return eur
    return None

# Plausibility bands for an outright handset price in local currency - not a
# monthly installment and not a 2-year contract total. Anything outside is
# treated as a mis-parse and rejected rather than stored.
#
# 2026-08-21: split into per-(currency, price_type) bands below. The flat
# currency-only band is kept for the legacy is_plausible(price, currency)
# callers (used by crawler templates that don't carry price_type in scope)
# but add_price (the only write path that can persist bad data) routes
# through is_plausible_for() with the price_type and the new bands.
PLAUSIBLE_BANDS = {
    # 2026 flagship foldables (Samsung Galaxy Z Fold8 2719 EUR, Z Fold8 Ultra
    # ~2900-3000 EUR) sit above the old 2500 ceiling, so the cap is raised to
    # 4000 — still well below any sane single-handset price, rejecting mis-parses.
    "EUR": (80, 4_000),
    "HUF": (30_000, 1_200_000),
    "RSD": (15_000, 400_000),
    "RON": (300, 15_000),
    "BGN": (150, 5_000),
    "PLN": (300, 12_000),
    # Czech handsets: entry Redmi/realme sit around 2k CZK on promo, flagships
    # (Z Fold class) reach ~37k. 1_500 lower bound still rejects any stray
    # non-phone number (a 79_990 TV) which the 60_000 ceiling also rejects.
    "CZK": (1_500, 60_000),
}

# Per-(currency, price_type) plausibility bands.
#
# 同一货币下不同 price_type 区间差距巨大（subsidy_down_payment 是设备融资总价
# vs contract_monthly 是月费），旧 PLAUSIBLE_BANDS 不区分导致 contract_monthly
# 用 80-4000 EUR 过宽、月费 1-30 EUR 全部"合理"，反过来 subsidy_down_payment
# 用 80-4000 EUR 又过紧、旗舰 2500-4000 EUR 会误判。
#
# 设计参考：
# - subsidy_down_payment: 运营商设备融资总价（首付+24/30/36 期合计），100-3000 EUR
# - contract_monthly:     运营商月费，欧元区 5-200 EUR，东欧本币更低
# - unlocked:             公开市场裸机价，100-3500 EUR（flagship + 顶配）
# - list_price:           与 unlocked 同（"定价" = "裸机市场价"）
#
# 上限放宽裕量：考虑旗舰 1TB ROM、顶配 Z Fold8 Ultra、汇率波动、土耳其高溢价等。
# 下限收紧：入门机促销也可能低至 band 下限附近，低于下限几乎都是 scraper 抓错。
PLAUSIBLE_BANDS_BY_TYPE: dict[tuple[str, str], tuple[float, float]] = {
    # EUR (欧元区: Croatia/Finland/Bulgaria; Vodafone RO/Telekom HT/etc.)
    ("EUR", "subsidy_down_payment"): (50, 4_000),
    ("EUR", "contract_monthly"):     (1, 200),
    ("EUR", "unlocked"):             (80, 4_000),
    ("EUR", "list_price"):           (80, 4_000),
    # HUF (匈牙利, 1 EUR ≈ 390 HUF)
    ("HUF", "subsidy_down_payment"): (20_000, 1_500_000),
    ("HUF", "contract_monthly"):     (500, 80_000),
    ("HUF", "unlocked"):             (30_000, 1_500_000),
    ("HUF", "list_price"):           (30_000, 1_500_000),
    # RSD (塞尔维亚, 1 EUR ≈ 117 RSD)
    ("RSD", "subsidy_down_payment"): (5_000, 500_000),
    ("RSD", "contract_monthly"):     (100, 15_000),
    ("RSD", "unlocked"):             (10_000, 500_000),
    ("RSD", "list_price"):           (10_000, 500_000),
    # RON (罗马尼亚, 1 EUR ≈ 5 RON)
    ("RON", "subsidy_down_payment"): (200, 20_000),
    ("RON", "contract_monthly"):     (5, 1_000),
    ("RON", "unlocked"):             (300, 20_000),
    ("RON", "list_price"):           (300, 20_000),
    # BGN (保加利亚 dual-price 但 channel.currency 已统一 EUR；BGN 仅作兼容)
    ("BGN", "subsidy_down_payment"): (100, 8_000),
    ("BGN", "contract_monthly"):     (5, 400),
    ("BGN", "unlocked"):             (150, 8_000),
    ("BGN", "list_price"):           (150, 8_000),
    # PLN (波兰, 1 EUR ≈ 4.3 PLN)
    ("PLN", "subsidy_down_payment"): (200, 18_000),
    ("PLN", "contract_monthly"):     (10, 1_000),
    ("PLN", "unlocked"):             (300, 18_000),
    ("PLN", "list_price"):           (300, 18_000),
    # CZK (捷克, 1 EUR ≈ 25 CZK)
    ("CZK", "subsidy_down_payment"): (1_000, 80_000),
    ("CZK", "contract_monthly"):     (50, 3_000),
    ("CZK", "unlocked"):             (1_500, 80_000),
    ("CZK", "list_price"):           (1_500, 80_000),
}

# Word-boundary-anchored detection. Order matters only for currencies that can
# legitimately co-occur; the country map normally settles it first.
_SNIFF_PATTERNS = [
    ("PLN", r"\bPLN\b|\bzł\b|\bzl\b"),
    ("RSD", r"\bRSD\b|\bдин\b"),
    ("HUF", r"\bHUF\b|\bFt\b"),
    ("RON", r"\bRON\b|\blei\b"),
    ("BGN", r"\bBGN\b|\bлв\b"),
    ("CZK", r"\bCZK\b|\bKč\b"),
    ("EUR", r"\bEUR\b|€"),
]


def currency_for_channel(channel) -> str | None:
    """Authoritative currency for a channel, or None when unmapped."""
    if channel is None:
        return None
    name = getattr(channel, "name", None)
    if name and name in CHANNEL_CURRENCY:
        return CHANNEL_CURRENCY[name]
    country = getattr(channel, "country", None)
    return COUNTRY_CURRENCY.get(country) if country else None


def sniff_currency(text: str) -> str | None:
    """Best-effort currency detection from page text. None when ambiguous."""
    if not text:
        return None
    for code, pattern in _SNIFF_PATTERNS:
        if re.search(pattern, text, re.I):
            return code
    return None


def resolve_currency(expected: str | None, sniffed: str | None,
                     url: str = "") -> str | None:
    """Reconcile the channel's currency with what the page shows.

    The channel mapping wins; a disagreement is logged so a genuinely wrong
    mapping surfaces instead of silently corrupting data.
    """
    if expected and sniffed and expected != sniffed:
        log.info("currency sniff %s != channel currency %s for %s; using %s",
                 sniffed, expected, url or "page", expected)
    return expected or sniffed


def is_plausible(price: float, currency: str | None) -> bool:
    """Backward-compatible plausibility check using currency-only band.

    Used by crawler templates that don't carry price_type in scope. The write
    path (repositories.prices.add_price) calls is_plausible_for() instead so
    the per-(currency, price_type) bands above actually catch bad data.
    """
    band = PLAUSIBLE_BANDS.get(currency or "")
    if band is None:
        return True
    return band[0] <= price <= band[1]


def is_plausible_for(price: float, currency: str | None,
                      price_type: str | None,
                      allow_zero: bool = False) -> bool:
    """Per-(currency, price_type) plausibility. The hard write-path guard.

    Reject negative prices up-front so we never persist junk. By default
    zero is also rejected — most price points should be > 0. The write path
    (``add_price``) opts into zero via ``allow_zero=True`` only when the
    row carries an `` ``original_price > 0`` to prove the zero is a real
    bundle-only offer (e.g. operator PDP "device 0 EUR on plan X") and not
    a scraper sentinel where the parser simply found no price.

    Unknown (currency, price_type) combinations (e.g. future price_type
    additions) are accepted (True) to avoid breaking future extensions —
    operators can extend PLAUSIBLE_BANDS_BY_TYPE in code without touching
    the write path.
    """
    if price is None or price < 0:
        return False
    if price == 0 and not allow_zero:
        return False
    if price == 0 and allow_zero:
        # Bundle-only offers are a legitimate "device 0 EUR on plan X" shape;
        # skip the band check entirely since the caller has already proven
        # it's not a sentinel by supplying an original_price > 0.
        return True
    if price_type:
        band = PLAUSIBLE_BANDS_BY_TYPE.get((currency or "", price_type))
        if band is None:
            return True
        return band[0] <= price <= band[1]
    # Fall back to currency-only band when price_type isn't supplied.
    return is_plausible(price, currency)
