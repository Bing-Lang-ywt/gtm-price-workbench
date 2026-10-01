"""Post-crawl price consistency audit.

After every price write we run a cheap, best-effort sanity pass and stamp a
``flag`` on the price row when something looks off. The frontend surfaces the
flag so an operator can eyeball the suspect cell instead of trusting a number
that the crawler may have mis-read (e.g. grabbed a strikethrough original, or a
page returned the wrong product).

Flags (semicolon-joined when several apply):
  - actual_gt_original        price > original_price (can't happen for a real sale)
  - product_mismatch          page self-reported model name != the SKU's model
  - out_of_band               amount_eur outside a sane band for the currency

Note: a bundled gift (赠品) WITHOUT a strikethrough original is completely
normal (e.g. "buy phone, get free earbuds") and is NOT flagged — the gift lives
in its own column and needs no discount to be valid.
"""

import json
import logging
import re

from sqlmodel import select, func

from app.core.config import OUTLIER_HI_RATIO, OUTLIER_LO_RATIO, OUTLIER_MIN_SAMPLES
from app.crawling.currency import PLAUSIBLE_BANDS
from app.models.catalog import Sku
from app.models.price import Price

log = logging.getLogger("services.price_audit")


# Price types whose value is driven by an OPERATOR SUBSIDY rather than by the
# open market. Their cross-channel spread is enormous *by design* — the device
# can be handed out for 0 Ft on a 24-month loyalty plan (Yettel HU H600 Lite:
# list 147 989 Ft, loyalty discount -147 989 Ft) or discounted 69% (Yettel HU
# DemoBrand 600: list 253 990 Ft, loyalty discount -175 000 Ft -> 28 990 Ft).
# Because every operator picks its own subsidy depth, "far BELOW the
# cross-channel median" is normal commercial behaviour, not a data error, and
# the LO side of the outlier guard produced nothing but false positives here.
# The HI side stays armed: a *higher-than-peers* subsidy is a parse failure
# (A1 Croatia / Redmi 15C once stored €2615 against a €143 median = 18x).
SUBSIDY_PRICE_TYPES = frozenset({"subsidy_down_payment", "contract_monthly"})


# Storage / RAM / network tokens that must NOT participate in the model-family
# comparison. "Galaxy A27 5G" normalises to `galaxya275g`; a correct PDP that
# self-reports "Galaxy A27 6/128GB" normalises to `galaxya276128gb`. Without
# stripping, the trailing storage digits (128) collide with the "5G" suffix and
# the substring check fails -> a false `product_mismatch`. We drop these tokens
# so the comparison reduces to the family token (a27), which is what must agree.
#
# IMPORTANT: strip the storage/network tokens *before* removing non-alnum chars.
# If we strip after, "Redmi Note 15 256GB" collapses to `note15256gb` and the old
# `\d{1,4}(gb|g)` regex greedily eats `5256gb` (the model's trailing "5" glued to
# "256gb") -> "note15" becomes "note1" -> false `product_mismatch`. Word-boundary
# matching on the still-space-separated text leaves the model number intact.
def _normalize_name(s: str | None) -> str:
    if not s:
        return ""
    s = s.lower()
    s = re.sub(r"\b(?:5g|4g|lte)\b", " ", s)
    s = re.sub(r"\b\d{1,4}\s*(?:gb|g)\b", " ", s)
    s = re.sub(r"[^a-z0-9]", "", s)
    return s


def _fuzzy_name_match(page_name: str, model_name: str) -> bool:
    """Loose match: true when the two names clearly refer to the same product.

    We avoid flagging on trivial differences (case, spaces, marketing codes)
    but DO flag when the page name and the expected model diverge (e.g. the
    operator crawler landed on the wrong product page).
    """
    a = _normalize_name(page_name)
    b = _normalize_name(model_name)
    if not a or not b:
        return True  # cannot compare -> never flag
    # A genuine product page title always carries a digit (model number or
    # storage size). A page that self-reports only a store/section name
    # (e.g. GIGATRON -> "Gigatron", One HU -> "Okostelefon vásárlás | One")
    # carries none -> the crawler failed to read the product name, so we cannot
    # compare -> never flag (same as "cannot compare" above). This removes false
    # product_mismatch hits on channels whose product_name extraction returns a
    # generic title instead of the SKU's real name. Real (wrong) product pages
    # always contain a digit and are still evaluated below.
    if not re.search(r"\d", a):
        return True
    if a == b:
        return True
    # allow the page name to contain the model token (model is usually shorter)
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    return shorter in longer


def compute_price_flag(
    *,
    price: float | None,
    original_price: float | None,
    gift: str | None,
    meta,
    currency: str | None,
    amount_eur: float | None,
    model_display_name: str | None,
    model_median_eur: float | None = None,
    price_type: str | None = None,
) -> str | None:
    flags: list[str] = []

    # 1) actual price can never exceed the strikethrough original
    if (
        original_price is not None
        and price is not None
        and price > original_price
    ):
        flags.append("actual_gt_original")

    # 2) page self-reported product name vs the SKU's expected model
    page_name = None
    if isinstance(meta, dict):
        page_name = meta.get("product_name")
    elif isinstance(meta, str):
        try:
            page_name = json.loads(meta).get("product_name")
        except Exception:
            page_name = None
    if page_name and model_display_name and not _fuzzy_name_match(
        page_name, model_display_name
    ):
        flags.append("product_mismatch")

    # 3) sanity band (catches absurd / zero / negative values)
    # `amount_eur` is already normalised to EUR, so it must be compared against
    # the EUR band. The old code looked up PLAUSIBLE_BANDS by the *local*
    # currency (e.g. HUF band 30k–1.2M) and compared it with the euro-valued
    # amount_eur, so the guard never fired for non-EUR channels — a mis-parse
    # amplified 1000x would still pass. (A2 audit fix.)
    if amount_eur is not None:
        _lo, _hi = PLAUSIBLE_BANDS.get("EUR", (0.0, 1e12))
        # A price of exactly 0 is normally a mis-parse. BUT some operator
        # channels give the device away free when taken with a subscription
        # bundle (Yettel HU "Kedvezményes készülék ár 0 Ft", list price kept
        # as `original_price`). That is a *legitimate* 0, not a data error, and
        # must not be conflated with `out_of_band` — otherwise 4 real bundle
        # SKUs (600 Lite / Magic8 Lite / Redmi Note 15 / A27) drown genuine
        # anomalies in noise. We tag it as its own semantic (`bundle_only`) and
        # skip the generic band check. Gated on the operator_pdp source so a
        # stray 0 from a market channel is still flagged out_of_band. (P2-14.)
        # Two independent ways to prove a 0 is a genuine give-away rather than
        # a mis-parse:
        #  (a) the crawler tagged itself as an operator PDP. Match on the
        #      PREFIX, not equality: manual repairs write suffixed sources such
        #      as "operator_pdp.yettel_hu.manual_fix", and an exact `==` made
        #      those 4 repaired rows fall through to `out_of_band`.
        #  (b) the row sits on an operator-only price type. A market channel
        #      can never emit subsidy_down_payment, so the type alone is sound
        #      evidence — this also covers rows whose meta was never stored.
        _src = meta.get("source") if isinstance(meta, dict) else None
        _operator_zero = bool(
            (_src and str(_src).startswith("operator_pdp"))
            or price_type == "subsidy_down_payment"
        )
        is_bundle_zero = (
            price is not None
            and price == 0
            and original_price is not None
            and original_price > 0
            and _operator_zero
        )
        if is_bundle_zero:
            flags.append("bundle_only")
        elif amount_eur <= 0 or amount_eur > _hi * 3:
            flags.append("out_of_band")

    # 4) cross-channel relative outlier (A1 Croatia / Redmi 15C = 18x the
    # same-model median slipped past the absolute band). Computed from the
    # median of this model's LATEST same-price-type prices across ALL channels;
    # if the current value is far above or below it, the number is suspect.
    # Only meaningful with enough peers, so cold-start channels (few samples)
    # are never flagged. A legitimate 0 (bundle) is excluded below by the
    # amount_eur > 0 guard, and we never delete / rewrite / guess — a human
    # verifies. Thresholds come from config (OUTLIER_*).
    #
    # Operator-subsidy price types are checked on the HIGH side only — see
    # SUBSIDY_PRICE_TYPES. A deep subsidy (device far cheaper than peers) is a
    # legitimate promotion; a subsidy far MORE expensive than peers means the
    # extractor grabbed the wrong number.
    if (
        model_median_eur is not None
        and amount_eur is not None
        and amount_eur > 0
        and model_median_eur > 0
    ):
        ratio = amount_eur / model_median_eur
        low_side_armed = price_type not in SUBSIDY_PRICE_TYPES
        if ratio > OUTLIER_HI_RATIO or (low_side_armed and ratio < OUTLIER_LO_RATIO):
            flags.append("cross_channel_outlier")

    return ";".join(flags) if flags else None


def model_median_latest(session, model_id: str, price_type: str) -> float | None:
    """Median of each SKU's latest ``amount_eur`` for one model + price type.

    One aggregation query builds a sku_id -> latest captured_at map (the
    de-duplication step), then we collect those latest amounts and return their
    median. ``None`` when there are no prices at all (so callers skip quietly).
    """
    sub = (
        select(
            Price.sku_id.label("sid"),
            func.max(Price.captured_at).label("last_seen"),
        )
        .join(Sku, Sku.id == Price.sku_id)
        .where(Sku.model_id == model_id, Price.price_type == price_type)
        .group_by(Price.sku_id)
    ).subquery()
    rows = session.exec(
        select(Price.amount_eur).join(sub, sub.c.sid == Price.sku_id).where(
            Price.captured_at == sub.c.last_seen
        )
    ).all()
    vals = [float(v) for v in rows if v is not None]
    if not vals:
        return None
    vals.sort()
    n = len(vals)
    mid = n // 2
    if n % 2:
        return vals[mid]
    return (vals[mid - 1] + vals[mid]) / 2.0
