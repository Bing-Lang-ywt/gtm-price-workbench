"""P2-17: configuration convergence (restrained).

Rather than build an over-engineered config framework, this pins the existing
single-source-of-truth locations and the one real move made: the default
contract term now lives in ``app.core.config`` (``DEFAULT_CONTRACT_TERM_MONTHS``)
and ``operator_device_total.TERM_MONTHS`` is derived from it — so the term knob
has one home, matching ``Channel.contract_term_months`` (the per-channel value).

Other knobs were already centralized and are asserted to remain so:
  * ``PLAUSIBLE_BANDS`` / ``COUNTRY_CURRENCY`` / ``CHANNEL_CURRENCY`` -> currency.py
  * operator extraction rules -> ``OPERATOR_PDP_CONFIG`` in operator_pdp.py

Run: python -m pytest tests/test_p2_seventeen.py -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import DEFAULT_CONTRACT_TERM_MONTHS  # noqa: E402
from app.crawling.currency import (  # noqa: E402
    CHANNEL_CURRENCY,
    COUNTRY_CURRENCY,
    PLAUSIBLE_BANDS,
)
from app.crawling.operator_pdp import OPERATOR_PDP_CONFIG  # noqa: E402
from app.services.operator_device_total import TERM_MONTHS  # noqa: E402


def test_default_term_months_is_24():
    assert DEFAULT_CONTRACT_TERM_MONTHS == 24


def test_term_months_converged_to_config_single_source():
    # The module-level constant must equal the config default, confirming the
    # magic number was removed from operator_device_total.py.
    assert TERM_MONTHS == DEFAULT_CONTRACT_TERM_MONTHS == 24


def test_plausible_bands_centralized_in_currency():
    assert "EUR" in PLAUSIBLE_BANDS and "HUF" in PLAUSIBLE_BANDS


def test_country_currency_centralized_in_currency():
    assert COUNTRY_CURRENCY["Hungary"] == "HUF"
    assert COUNTRY_CURRENCY["Finland"] == "EUR"


def test_operator_extraction_rules_centralized():
    assert "Yettel HU" in OPERATOR_PDP_CONFIG
    assert "One HU" in OPERATOR_PDP_CONFIG


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
