"""app.crawling.installment 的回归单测。

用例全部来自真实运营商 PDP 的渲染文本，期望值是人工在官网上核对过的期数。
抓不到返回 None 是**正确行为** —— 前端会退化为「按 24 期折算」并明确标注，
比写一个假的官网期数强。
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.crawling.installment import extract_installment  # noqa: E402


# ---------------------------------------------------------------- 真实页面

def test_telekom_hu_22_periods():
    """"22 × 8708 Ft" + "Kedvezményes készülékár: 191 570 Ft"。"""
    text = (
        "Készülék kedvezményes ára\nEgy összegben\n22 × 8708 Ft\n"
        "Online kedvezménnyel\n236 720 Ft listaár helyett\n"
        "Kedvezményes készülékár: 191 570 Ft\n"
    )
    got = extract_installment(text, "HUF", device_total=191570)
    assert got is not None
    assert got["periods"] == 22
    assert got["monthly"] == 8708


def test_one_hu_30_periods():
    """30 期与 20 期同页，月付相同 —— 只有 30×4600 等于设备总价。

    这条是排序规则的守门用例：若把「期数最接近 24」排在「总额贴合度」前面，
    会选中 20 期（20×4600=92000 ≠ 138000）。
    """
    text = (
        "30 havi kamatmentes részlet\n5 600 Ft/hó helyett 4 600 Ft/hó\n"
        "20 havi kamatmentes részlet\n4 600 Ft/hó\n"
        "Készülék ára: 138 000 Ft\n"
    )
    got = extract_installment(text, "HUF", device_total=138000)
    assert got is not None
    assert got["periods"] == 30


def test_a1_serbia_dot_thousands():
    """塞尔维亚用点做千分位："24 x 2.825 RSD/mes" = 2825 RSD/月。"""
    text = "Bez tarifnog paketa 73.990 RSD\n24 x 2.825 RSD/mes\n"
    got = extract_installment(text, "RSD", device_total=73990, dot_is_thousands=True)
    assert got is not None
    assert got["periods"] == 24
    assert got["monthly"] == 2825


def test_plus_12_rat():
    """"Opłata miesięczna za sprzęt 179,15 zł dla 12 rat"（金额在前、期数在后、同行）。"""
    text = (
        "Opłata miesięczna za sprzęt 179,15 zł dla 12 rat\n"
        "Cena urządzenia 2398,80 zł\n"
    )
    got = extract_installment(text, "PLN", device_total=2398.80)
    assert got is not None
    assert got["periods"] == 12


def test_yettel_hu_22_havi():
    """期数词与月付跨行："22 havi … 1 317 Ft/hó"。"""
    text = (
        "22 havi kamatmentes részlet\nKezdőrészlet: 0 Ft\n1 317 Ft/hó\n"
        "Kedvezményes készülék ár 28 990 Ft\n"
    )
    got = extract_installment(text, "HUF", device_total=28990)
    assert got is not None
    assert got["periods"] == 22


# ---------------------------------------------------------------- 误报护栏

def test_device_dimensions_are_not_an_installment():
    """机身尺寸 "161.15 x 75.0 x 8.4 mm" 必须被拒。

    真实事故（Telekom HT magic8pro）：S1 的 `N × AMOUNT` 正则把 "161.15 x 75.0"
    读成 "15 期 × 75.0"，乘出 1125 —— 与设备价 889.76 只差 1.26 倍，倍率闸
    完全挡不住，落库后就是一条以假乱真的「官网分期方案」。
    """
    text = (
        "DemoBrand Magic8 Pro 5G\nDimenzije: 161.15 x 75.0 x 8.4 mm\n"
        "Zaslon: 6.71 inča\nCijena uređaja 889,76 €\n"
    )
    assert extract_installment(text, "EUR", device_total=889.76) is None


def test_screen_resolution_is_not_an_installment():
    """屏幕分辨率 "1264 × 2728" 必须被拒。"""
    text = "Zaslon\n1264 × 2728 PX\nCijena 361,76 €\n"
    assert extract_installment(text, "EUR", device_total=361.76) is None


def test_vodafone_ro_tc_wording_is_rejected():
    """T&C 长句里的 "25€ lunar, pe o perioadă minimă contractuală de 24 luni"。"""
    text = (
        "Preț telefon 251,99 €\n"
        "Oferta este valabilă pentru o perioadă minimă contractuală de 24 luni, "
        "25€ lunar, RRSO 0%.\n"
    )
    assert extract_installment(text, "EUR", device_total=251.99) is None


def test_tariff_monthly_far_from_device_price_is_rejected():
    """套餐月费（设备价的十几倍）必须被倍率闸拒掉。"""
    text = "Mjesečna naknada 36,28 EUR/mj\n24 mjeseca\nCijena uređaja 361,76 €\n"
    assert extract_installment(text, "EUR", device_total=361.76) is None


def test_no_device_total_weak_candidate_alone_is_not_trusted():
    """没有设备总价做校验时，弱信号（裸金额 + 期数词）不该单独成交。"""
    text = "Cijena 96,00 EUR\n12 mjeseca\n"
    assert extract_installment(text, "EUR", device_total=None) is None
