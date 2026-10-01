"""Regression tests for market-channel product matching (Alza / Datart).

These guard the single most expensive failure mode in the whole system: a
sibling model's price silently landing on the wrong row. It happened three
times during the Alza rollout -

  * "DemoBrand 600"        resolved to the *Pro* PDP   (13990 -> 20490, +6500 CZK)
  * "Samsung Galaxy S26" resolved to the *Ultra*   (23990 -> 35690, +11700 CZK)
  * "Xiaomi 17"        resolved to the *17T*       ("17" is a substring of "17T")

Each bug is pinned below. Run with:
    python -m pytest tests/test_market_matching.py -q
(or plain `python tests/test_market_matching.py` - it self-checks.)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.crawling.market_common import (  # noqa: E402
    is_accessory,
    pick_best_result,
    verify_product_name,
)

A = "https://www.alza.cz/"


# --------------------------------------------------------------------------
# verify_product_name - the final authority before a price is written
# --------------------------------------------------------------------------
NAME_CASES = [
    # (query, page product name, expected ok)
    ("Xiaomi 17", "Xiaomi 17T 12GB/256GB Black", False),   # substring trap
    ("Xiaomi 17", "Xiaomi 17 12GB/512GB Black", True),
    ("Xiaomi 17T", "Xiaomi 17T 12GB/256GB Black", True),
    ("DemoBrand 600", "DemoBrand 600 Pro 12GB/512GB Golden White", False),
    ("DemoBrand 600", "DemoBrand 600 8GB/512GB Orange", True),
    ("DemoBrand 600 Pro", "DemoBrand 600 Pro 12GB/512GB Golden White", True),
    ("Samsung Galaxy S26", "Samsung Galaxy S26 Ultra 12GB/256GB Black", False),
    ("Samsung Galaxy S26 Ultra", "Samsung Galaxy S26 Ultra 12GB/256GB Black", True),
    ("Samsung Galaxy Z Fold8", "Samsung Galaxy Z Fold8 Ultra 12GB/512GB Graphite", False),
    ("Samsung Galaxy Z Fold8", "Samsung Galaxy Z Fold8 12GB/256GB Graphite", True),
    ("Redmi Note 15", "Xiaomi Redmi Note 15 4G 6GB/128GB Black", True),
    ("Redmi 15C", "Xiaomi Redmi 15C 4GB/128GB Moonlight Blue", True),
    ("DemoBrand 600 Smart", "DemoBrand 600 8GB/512GB Black", False),
]


def test_verify_product_name():
    for query, name, expected in NAME_CASES:
        ok, reason = verify_product_name(query, name)
        assert ok is expected, f"{query!r} vs {name!r}: got {ok} ({reason})"


def test_missing_name_does_not_block():
    # No metadata is not evidence of a mismatch; we only block on conflict.
    ok, reason = verify_product_name("Xiaomi 17", None)
    assert ok and reason == "unverified"


# --------------------------------------------------------------------------
# is_accessory - a 299 CZK screen protector must never be priced as a phone
# --------------------------------------------------------------------------
def test_accessory_rejection():
    assert is_accessory(A + "tempered-glass-protector-pro-demobrand-600-smart-d13495243.htm")
    assert is_accessory(A + "pouzdro-pro-samsung-galaxy-s26-d1234567.htm")
    assert is_accessory(A + "nabijecka-usb-c-65w-d1234567.htm")
    assert not is_accessory(A + "demobrand-600-8gb-512gb-orange-d13313293.htm")
    assert not is_accessory(A + "samsung-galaxy-z-fold8-12gb-256gb-graphite-d13438221.htm")


# --------------------------------------------------------------------------
# pick_best_result - variant penalty + entry-config tie-break
# --------------------------------------------------------------------------
XIAOMI_LINKS = [
    (A + "xiaomi-17t-12gb-256gb-black-d13360858.htm", "Xiaomi 17T 12GB/256GB Black"),
    (A + "xiaomi-17-12gb-512gb-black-d13237297.htm", "Xiaomi 17 12GB/512GB Black"),
    (A + "xiaomi-17-12gb-256gb-white-d13237290.htm", "Xiaomi 17 12GB/256GB White"),
]

DemoBrand_LINKS = [
    (A + "demobrand-600-pro-12gb-512gb-golden-white-d13313287.htm", "DemoBrand 600 Pro"),
    (A + "demobrand-600-8gb-512gb-orange-d13313293.htm", "DemoBrand 600 8GB/512GB"),
    (A + "demobrand-600-8gb-256gb-black-d13313291.htm", "DemoBrand 600 8GB/256GB"),
]


def test_variant_sibling_is_not_picked():
    assert pick_best_result(XIAOMI_LINKS, "Xiaomi 17").endswith("d13237290.htm")
    assert pick_best_result(XIAOMI_LINKS, "Xiaomi 17T").endswith("d13360858.htm")
    assert "600-pro" not in pick_best_result(DemoBrand_LINKS, "DemoBrand 600")
    assert "600-pro" in pick_best_result(DemoBrand_LINKS, "DemoBrand 600 Pro")


def test_entry_config_wins_ties():
    # Same model, two capacities -> the comparison anchors on the lower one.
    assert pick_best_result(DemoBrand_LINKS, "DemoBrand 600").endswith("d13313291.htm")


if __name__ == "__main__":
    failures = 0
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL  {fn.__name__}: {exc}")
    print(f"--- {failures} failure(s) ---")
    sys.exit(1 if failures else 0)
