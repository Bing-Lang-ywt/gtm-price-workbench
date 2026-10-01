"""Regression tests for the Hungarian operator PDP extractors.

契约（2026-09-03 改版，配合「直接购买 / 分期购买」两行展示）
--------------------------------------------------------
运营商 PDP 同时给出两个设备数字：

  * ``listaár``        = 无合约的官方标价（**原价**）-> ``original_price``
  * ``kedvezményes ár`` / ``Teljes ár`` = 客户实际一次性付的折后价（**折后**）
                                                            -> ``price``

展示层把前者划掉、后者当头部价，所以 ``price`` 必须是**折后**而不是标价，
否则「分期购买」那行的总额（等于折后）会和「直接购买」对不上。

两个渠道曾经的坑（以下用例逐条锁死）：

  * **Telekom HU** 一度把 ``Egy összegben`` 标签后的**月付**（32 478 Ft）当成
    设备总价，直接低了 22 倍 —— 现在显式总价锚点优先，且任何等于月付腿的候选
    都会被拒。页面上的 ``N Ft/hó`` 是**套餐费**（全机型同值），绝不是设备分期，
    因此绝不能写进 ``contract_monthly``。

  * **Yettel HU** 的 ``Teljes ár`` 是签约价（53 990 Ft），而 ``Készülék
    listaár`` 才是标价（251 990 Ft）。改版前它是头部价取标价、Telekom 取标价，
    两个渠道口径不一致；现在统一为「折后 = 头部价」。赠机（``Kedvezményes
    készülék ár 0 Ft``）没有正的折后价，此时退回标价当头部价（不能是 0），
    签约价 0 留在 ``meta.contract_device_price`` 供单元格标注「签约赠机」。
    ``Havonta fizetendő 26 609 Ft/hó`` 是含资费的整单账单（0 Ft 赠机和
    710 990 Ft 的 Z Fold8 Ultra 上读数完全一样），只能进 meta 做注解。

Fixtures are the real rendered ``innerText`` (trimmed) captured from the live
PDPs on 2026-08-13, kept in **NFD** form -- Hungarian pages ship decomposed
accents, and forgetting to normalize was a previous bug class, so the tests pin
that too.

No network, no DB, no browser -- a stub page object only. Run with:
    python -m pytest tests/test_hu_operator_extractors.py -q
"""

import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.crawling.operator_pdp import (  # noqa: E402
    _extract_telekom_hu,
    _extract_yettel_hu,
)


class _StubPage:
    """Minimal Playwright page stand-in: innerText + content() only."""

    def __init__(self, text: str, html: str = ""):
        # Mimic the browser: Hungarian PDPs deliver decomposed accents.
        self._text = unicodedata.normalize("NFD", text)
        self._html = html

    def evaluate(self, js: str):
        if "innerText" in js:
            return self._text
        return None

    def content(self):
        return self._html


# --------------------------------------------------------------------------
# Telekom HU
# --------------------------------------------------------------------------
_TELEKOM_HU_600 = """
Kedvezménnyel vagy listaáron
Szolgáltatás nélkül, listaáron
Készülék kedvezményes ára
230 780 Ft listaár helyett
Kedvezményes készülékár: 163 630 Ft
18 590 Ft/hó
19 090 Ft/hó helyett
Kedvezményed: 500 Ft/hó
"""


def test_telekom_hu_stores_the_discounted_price_as_headline():
    """头部价 = 客户实际支付的折后价 163 630 Ft（不是标价 230 780）。

    「分期购买」那行的总额就是折后价，若头部价取标价，两行会对不上。"""
    d = _extract_telekom_hu(_StubPage(_TELEKOM_HU_600))
    assert d["price"] == 163630.0


def test_telekom_hu_keeps_the_list_price_as_original():
    """标价进 original_price，且必须 original > price（否则会触发
    actual_gt_original 审计 flag）。"""
    d = _extract_telekom_hu(_StubPage(_TELEKOM_HU_600))
    assert d["original_price"] == 230780.0
    assert d["original_price"] > d["price"]


def test_telekom_hu_never_captures_the_plan_fee_as_device_monthly():
    """18 590 Ft/hó is the tariff fee, identical across devices -> not a
    device installment. Capturing it would fabricate a per-device monthly."""
    d = _extract_telekom_hu(_StubPage(_TELEKOM_HU_600))
    assert d.get("contract_monthly") is None


def test_telekom_hu_does_not_fall_back_to_the_list_price():
    """折后锚点消失（改文案 / 改版）时，不能悄悄拿标价顶上 —— 那正是
    「直接购买」与「分期购买」对不上的根因。没有结构化数据兜底就返回 None。"""
    text = "230 780 Ft listaár helyett\n18 590 Ft/hó"
    assert _extract_telekom_hu(_StubPage(text)) is None


# --------------------------------------------------------------------------
# Yettel HU
# --------------------------------------------------------------------------
_YETTEL_HU_600 = """
Teljes ár: 53 990 Ft
Itt láthatod az összes költséget melyet egyösszegben, majd havonta fizetsz.
Készülék listaár 251 990 Ft
Kedvezményes készülék ár 53 990 Ft
Egyszeri költségek 53 990 Ft
Havonta fizetendő 26 609 Ft/hó
"""

# Bundle-only: the device is free with the subscription, but it still has a
# real list price -- that list price is what gets stored.
_YETTEL_HU_600_LITE_BUNDLE = """
Itt láthatod az összes költséget melyet egyösszegben, majd havonta fizetsz.
Készülék listaár 146 990 Ft
Kedvezményes készülék ár 0 Ft
Egyszeri költségek 0 Ft
Havonta fizetendő 26 609 Ft/hó
"""


def test_yettel_hu_stores_the_discounted_price_with_list_price_as_original():
    """与 Telekom HU 同口径：头部价 = 折后（Teljes ár 53 990），标价
    （Készülék listaár 251 990）进 original_price。"""
    d = _extract_yettel_hu(_StubPage(_YETTEL_HU_600))
    assert d["price"] == 53990.0
    assert d["original_price"] == 251990.0
    assert d["meta"]["contract_device_price"] == 53990
    assert d["meta"]["monthly_payable"] == 26609.0


def test_yettel_hu_never_stores_zero_as_the_headline_price():
    """REGRESSION: 赠机（Kedvezményes készülék ár 0 Ft）如果把 0 当头部价，
    矩阵里会出现「0 Ft」这种假最低价。此时必须退回标价 146 990，
    签约价 0 留在 meta 里供单元格标注「签约赠机」。"""
    for fixture in (_YETTEL_HU_600, _YETTEL_HU_600_LITE_BUNDLE):
        d = _extract_yettel_hu(_StubPage(fixture))
        assert d["price"] > 0
        # 头部价要么等于折后（53990）、要么退回标价（146990），绝不可能是 0。
        assert d["price"] in (53990.0, 146990.0)


def test_yettel_hu_monthly_never_enters_contract_monthly():
    """REGRESSION: 'Havonta fizetendő' is the whole monthly bill (tariff plan
    included) and reads 26 609 Ft/hó identically for a 0 Ft bundle phone and a
    710 990 Ft Z Fold8 Ultra. Writing it to ``contract_monthly`` -- the column
    that holds real device instalments (Telekom HU 9 615 Ft) and is compared
    across channels -- made Yettel look 2.7x more expensive than it is. It must
    stay in meta, where the dashboard renders it as a non-comparable annotation.
    """
    for fixture in (_YETTEL_HU_600, _YETTEL_HU_600_LITE_BUNDLE):
        d = _extract_yettel_hu(_StubPage(fixture))
        assert "contract_monthly" not in d
        assert d["meta"]["monthly_payable"] == 26609.0


def test_yettel_hu_bundle_keeps_list_price_and_zero_contract_fee():
    """Bundle device: headline stays the comparable 146 990 Ft list price, and
    the 0 Ft contract fee survives in meta so the cell can annotate
    '签约赠机 0 · 套餐 26 609 Ft/月'. 0 must not be dropped as falsy."""
    d = _extract_yettel_hu(_StubPage(_YETTEL_HU_600_LITE_BUNDLE))
    assert d["price"] == 146990.0
    assert d["meta"]["contract_device_price"] == 0
    assert d["meta"]["monthly_payable"] == 26609.0


def test_yettel_hu_monthly_is_optional():
    """A PDP without the 'Havonta fizetendő' block must still yield a price."""
    text = "Teljes ár: 53 990 Ft\nKészülék listaár 251 990 Ft"
    d = _extract_yettel_hu(_StubPage(text))
    assert d["price"] == 53990.0
    assert d["original_price"] == 251990.0
    assert "monthly_payable" not in d["meta"]


def test_yettel_hu_without_listaar_does_not_fall_back_to_the_contract_fee():
    """No listaár anchor -> structured fallback (empty html here, so None),
    NOT a silent store of the 53 990 Ft contract fee. Falling back to whatever
    number is on the page is the mixed-basis bug all over again."""
    text = "Teljes ár: 53 990 Ft\nHavonta fizetendő 26 609 Ft/hó"
    assert _extract_yettel_hu(_StubPage(text)) is None
