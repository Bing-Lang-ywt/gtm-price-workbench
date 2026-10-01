"""Auto-derive operator device-financing totals from monthly installments.

Context
-------
Some operator channels (Telemach, MTS, Telekom HT) were historically not in
``OPERATOR_PDP_CONFIG`` (see ``app.crawling.operator_pdp``), so the generic
gigatron parser only ever sees the *monthly device installment*. The matrix
(``frontend/lib/rival-matrix.ts``) prefers ``subsidy_down_payment`` for
operators and only falls back to ``contract_monthly`` when that is absent — so
those channels would show the monthly as the "device price" (flagships at
9-16 EUR).

This module makes the fix permanent and part of the crawl pipeline: after every
crawl of an operator channel we ensure a ``subsidy_down_payment`` row exists by
deriving it from the latest ``contract_monthly`` (x ``TERM_MONTHS``, the
project's established contract term). A *natively* captured device total (from
``OPERATOR_PDP_CONFIG`` extractors or device-price channels like DNA) is never
overridden.

Idempotent: re-running recomputes only when the derived value is missing or has
drifted from the current monthly; native totals are left untouched.
"""
from __future__ import annotations

import json
import logging

from sqlmodel import select

from app.models.catalog import Sku
from app.models.price import Price
from app.services.prices import record_price

log = logging.getLogger("crawl.operator_device_total")

# The project's established operator contract term. A device-financing TOTAL is
# the monthly installment x this, matching the prior one-off backfill script.
# The default value is sourced from config (single source of truth); per-channel
# overrides come from ``Channel.contract_term_months`` (P2-12).
from app.core.config import DEFAULT_CONTRACT_TERM_MONTHS

TERM_MONTHS = DEFAULT_CONTRACT_TERM_MONTHS

# Plausibility band for a 2-year device financing TOTAL, in EUR. A derived total
# outside this is almost certainly a mis-parse, so we refuse to store it rather
# than poison the matrix.
EUR_BAND = (50.0, 3000.0)

# Plausibility band for a single monthly CONTRACT installment, in EUR. This is
# the reverse-synthesis target (subsidy_down_payment / TERM_MONTHS) and is a
# *much* smaller number than an outright handset, so it is independent of
# currency.py's PLAUSIBLE_BANDS["EUR"] (which covers whole-device prices). The
# check is performed on amount_eur (currency-agnostic), so non-EUR operators are
# covered too. A derived monthly outside (2, 300) EUR is implausible -> skip.
MONTHLY_BAND_EUR = (2.0, 300.0)


def _is_derived(price: Price) -> bool:
    """True when a row was computed by this module (vs. a natively crawled total)."""
    if not price.meta:
        return False
    try:
        m = json.loads(price.meta) if isinstance(price.meta, str) else price.meta
    except (ValueError, TypeError):
        return False
    return m.get("source") == "derived"


def _is_contaminated(monthly: Price, subsidy: Price, term: int = TERM_MONTHS) -> bool:
    """True when an existing monthly row is actually a mislabeled device price
    (the crawler wrote the handset total into ``contract_monthly``) rather than a
    real installment. A legitimate installment is ~1/term of the device
    total, so ``monthly >= subsidy`` — or ``monthly*term`` exceeding the
    device band — flags contamination (e.g. DNA storing 399/499/2299 as monthly).
    """
    if not monthly.amount_eur or not subsidy.amount_eur:
        return False
    if monthly.amount_eur >= subsidy.amount_eur:
        return True
    if monthly.amount_eur * term > EUR_BAND[1]:
        return True
    return False


def _latest(session, sku_id: str, channel_id: str, ptype: str) -> Price | None:
    rows = session.exec(
        select(Price)
        .where(
            Price.sku_id == sku_id,
            Price.channel_id == channel_id,
            Price.price_type == ptype,
        )
        .order_by(Price.captured_at.desc())
    ).all()
    return rows[0] if rows else None


def _delete_type(session, sku_id: str, channel_id: str, ptype: str) -> None:
    session.exec(
        Price.__table__.delete().where(
            Price.sku_id == sku_id,
            Price.channel_id == channel_id,
            Price.price_type == ptype,
        )
    )


def derive_operator_device_totals(session, channel) -> int:
    """Ensure every SKU of an operator channel has BOTH financing legs.

    Two idempotent branches, run after every crawl:

    * Branch A (monthly -> subsidy): when a SKU has a native ``contract_monthly``
      but no ``subsidy_down_payment`` (or only an outdated derived one), derive the
      device total = monthly x TERM_MONTHS. A natively crawled total (config
      operators) is never overwritten.
    * Branch B (subsidy -> monthly, NEW): when a SKU has a ``subsidy_down_payment``
      but no ``contract_monthly`` (DNA, config operators whose Plan A extractor
      omits the monthly, etc.), derive ``contract_monthly`` = subsidy / TERM_MONTHS
      and store it under the "derived" marker. This keeps both price types present
      so the matrix / download table never flickers "—".

    Returns the number of SKUs for which any derived row was created or refreshed.
    """
    term = int(getattr(channel, "contract_term_months", None) or TERM_MONTHS)
    skus = session.exec(select(Sku).where(Sku.channel_id == channel.id)).all()
    refreshed = 0
    for sku in skus:
        existing = _latest(session, sku.id, channel.id, "subsidy_down_payment")
        # Never override a natively crawled total. Native totals come from BOTH
        # config operators (OPERATOR_PDP_CONFIG) AND non-config device-price
        # channels (OPERATOR_DEVICE_PRICE_CHANNELS, e.g. DNA's Takuuhinta cash
        # price written by the generic gigatron parser). Restricting the guard
        # to config operators only let Branch A delete DNA's fresh native total
        # and replace it with a stale monthly x 24 (2026-09-03: A37 site 379 €,
        # DB stuck at 299.04 derived from an Aug-11 monthly).
        if existing and not _is_derived(existing):
            continue

        monthly = _latest(session, sku.id, channel.id, "contract_monthly")
        if not monthly or not monthly.amount_eur:
            continue
        # A real monthly installment is < EUR_BAND[1]/TERM_MONTHS (~125 EUR).
        # When it is larger, the crawler almost certainly wrote the *device
        # price* into contract_monthly (a mislabel). If there is no native
        # subsidy to protect, treat that value as the device TOTAL itself (not
        # monthly x 24, which would explode) and derive the real installment =
        # value / 24, filling BOTH legs in one shot.
        if monthly.amount_eur > EUR_BAND[1] / term:
            if existing and not _is_derived(existing):
                continue  # protect a genuine native total (any channel)
            total_eur = round(monthly.amount_eur, 2)
            if not (EUR_BAND[0] <= total_eur <= EUR_BAND[1]):
                log.info(
                    "skip relabel %s/%s: %.2f EUR out of band",
                    channel.name, sku.id, total_eur,
                )
                continue
            monthly_eur = round(total_eur / term, 2)
            if not (MONTHLY_BAND_EUR[0] <= monthly_eur <= MONTHLY_BAND_EUR[1]):
                log.info(
                    "skip relabel monthly %s/%s: %.2f EUR out of band",
                    channel.name, sku.id, monthly_eur,
                )
                continue
            currency = monthly.currency or "EUR"
            native_total = round(monthly.price, 2) if monthly.price else total_eur
            native_monthly = (
                round(monthly.price / term, 2) if monthly.price else monthly_eur
            )
            _delete_type(session, sku.id, channel.id, "subsidy_down_payment")
            record_price(
                session, sku.id, channel.id, "subsidy_down_payment",
                native_total, currency, in_stock=monthly.in_stock, evaluate=False,
                meta={"source": "derived", "method": "monthly_relabel_device",
                      "term_months": term, "base_price_id": monthly.id},
            )
            _delete_type(session, sku.id, channel.id, "contract_monthly")
            record_price(
                session, sku.id, channel.id, "contract_monthly",
                native_monthly, currency, in_stock=monthly.in_stock, evaluate=False,
                meta={"source": "derived", "method": "subsidy_div_24",
                      "term_months": term, "base_price_id": monthly.id},
            )
            refreshed += 1
            continue
        total_eur = round(monthly.amount_eur * term, 2)
        if not (EUR_BAND[0] <= total_eur <= EUR_BAND[1]):
            log.info(
                "skip derive %s/%s: total %.2f EUR out of band",
                channel.name, sku.id, total_eur,
            )
            continue

        # Already derived and unchanged -> nothing to do (also covers non-config
        # operators whose prior derivation still matches the current monthly).
        if existing and abs(existing.amount_eur - total_eur) < 0.01:
            continue

        native_price = (
            round(monthly.price * term, 2) if monthly.price else total_eur
        )
        currency = monthly.currency or "EUR"
        # Replace any prior derived row, then write one clean total.
        _delete_type(session, sku.id, channel.id, "subsidy_down_payment")
        record_price(
            session,
            sku.id,
            channel.id,
            "subsidy_down_payment",
            native_price,
            currency,
            in_stock=monthly.in_stock,
            evaluate=False,
            meta={
                "source": "derived",
                "method": "contract_monthly_x24",
                "term_months": term,
                "base_price_id": monthly.id,
            },
        )
        refreshed += 1

    # ---- Branch B: subsidy -> monthly (reverse synthesis, NEW) ----
    # Some operators expose only a device-financing TOTAL (subsidy_down_payment)
    # and never a monthly installment -- e.g. DNA (OPERATOR_DEVICE_PRICE_CHANNELS)
    # and config operators whose Plan A extractor writes subsidy_down_payment but
    # not contract_monthly. Without a monthly row those SKUs flicker as "—" in the
    # matrix / download table whenever the two price types are written on
    # different crawl days. Here we back-fill a derived contract_monthly =
    # round(subsidy / TERM_MONTHS) so every operator SKU carries both legs.
    # The existing monthly -> subsidy direction (branch A) is left untouched.
    for sku in skus:
        existing = _latest(session, sku.id, channel.id, "contract_monthly")
        subsidy = _latest(session, sku.id, channel.id, "subsidy_down_payment")
        if not subsidy or not subsidy.amount_eur:
            continue
        # Keep a *natively* crawled monthly ONLY when it is a plausible installment
        # (much smaller than the device total). The crawler historically wrote the
        # whole-device price into contract_monthly for several operators (e.g. DNA
        # stores 399/499/2299 as "monthly"), so we OVERRIDE those with
        # subsidy/TERM_MONTHS rather than leaving the contaminated device price.
        if existing and not _is_derived(existing) and not _is_contaminated(existing, subsidy, term):
            continue

        monthly_eur = round(subsidy.amount_eur / term, 2)
        # Plausibility guard against dirty data (mis-parsed totals). Checked on
        # the EUR-normalised figure so non-EUR channels are covered too.
        if not (MONTHLY_BAND_EUR[0] <= monthly_eur <= MONTHLY_BAND_EUR[1]):
            log.info(
                "skip derive monthly %s/%s: %.2f EUR out of band",
                channel.name, sku.id, monthly_eur,
            )
            continue

        # Already derived and unchanged -> nothing to do (idempotent).
        if existing and abs(existing.amount_eur - monthly_eur) < 0.01:
            continue

        native_monthly = (
            round(subsidy.price / term, 2) if subsidy.price else monthly_eur
        )
        currency = subsidy.currency or "EUR"
        # Replace any prior derived row, then write one clean monthly.
        _delete_type(session, sku.id, channel.id, "contract_monthly")
        record_price(
            session,
            sku.id,
            channel.id,
            "contract_monthly",
            native_monthly,
            currency,
            in_stock=subsidy.in_stock,
            evaluate=False,
            meta={
                "source": "derived",
                "method": "subsidy_div_24",
                "term_months": term,
                "base_price_id": subsidy.id,
            },
        )
        refreshed += 1

    return refreshed
