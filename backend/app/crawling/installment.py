"""Generic device-installment extraction for operator PDPs.

为什么要独立成模块
------------------
每个运营商把「设备分期」写在完全不同的位置，形态也各不相同：

    Telekom HU  ->  "22 × 8708 Ft"                       （N × 月付）
    A1 Serbia   ->  "24 x 2.825 RSD/mes"                 （N × 月付，点为千分位）
    A1 Croatia  ->  "9,00 € odmah + 11,00 € /24mj"       （月付 / 期数）
    Yettel HU   ->  "22 havi kamatmentes részlet"        （期数词在前，月付隔几行）
                    "1 317 Ft/hó"  …  "22 hónapig"
    One HU      ->  "10/20/30 havi" + "5 600 Ft helyett / 4 600 Ft/hó"
                    （只渲染当前档位，且划线月付在前、实付月付在后）
    Plus        ->  "Opłata miesięczna za sprzęt 179,15 zł dla 12 rat"

所以这里不是「一条正则打天下」，而是**多策略候选 + 统一筛选**：
  1. 每条策略产出 (periods, monthly, strength) 候选；
  2. 用「法律条款关键词」「量级校验」「期数区间」三道闸把 T&C 段落、
     屏幕分辨率（2728x1264）、套餐月费（36,28 EUR/mj）全部筛掉；
  3. 剩下的候选按 信号强度 → 期数最接近 24 期 → 总额最接近设备价 排序取第一。

写正则的红线（继承自 2026-09-02 的 Vodafone RO 事故）：
  宁可收紧到抓不到（诚实的 parse failure，不落库），也不写宽松通配造出假数据。
"""
from __future__ import annotations

import re
import unicodedata

# ---------------------------------------------------------------- 词表 / 词法

# 货币 token：紧跟金额出现才算数（用于拒绝分辨率/尺寸类数字对）
CUR = (
    r"(?:Ft|HUF|€|EUR|RSD|din|дин|RON|lei|zł|PLN|BGN|лв|lev|kn|HRK|Kč|CZK|"
    r"kr|SEK|ден|MKD)"
)

# 千分位/小数混合的本地化数字：191 570 | 2.825 | 265,76 | 1.765,20 | 2398,80 | 79,17
NUM = r"\d{1,3}(?:[\s\u00a0.']\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"

# 「月付」标记：紧跟金额 → 这个金额是每期还款额，而不是总价
MONTHLY_MARK = (
    r"(?:/\s*h[oó]\b|/\s*mj\b|/\s*mjesec|/\s*месец|/\s*lun[uă]\b|/\s*kk\b|"
    r"/\s*mes\b|/\s*month|h[oó]nap(?:ig|on|ra)?|mese[čc]n\w*|mjese[čc]n\w*|"
    r"kuukaus\w*|m[aå]nad\w*|havonta|месечн\w*|lunar|на\s+месец)"
)

# 「期数」词：紧跟数字 → 这个数字是期数（长变体必须排在短变体前）
PERIOD_WORD = (
    r"(?:ratele|ratas|instalment\w*|installment\w*|mjesec\w*|m[eě]sec\w*|"
    r"m[eě]s[ií][čc]n\w*|"
    r"m[aå]nat\w*|kuukaus\w*|h[oó]nap(?:ig|on|ra)?|вноск\w*|месец\w*|"
    r"hav[yi]|raty|rata|rate|ratas|rat(?![a-z])|spl[aá]t\w*|lun[iă]\b|luni|"
    r"month\w*|monat\w*|maand\w*|h[oó]\b|mj\b|kk\b)"
)

# 期数锚点
RE_PERIOD_ANCHOR = re.compile(r"(?<!\d)(\d{1,2})[\s\u00a0]*(?:" + PERIOD_WORD + r")", re.I)
# 带货币/月付标记的金额
RE_AMOUNT = re.compile(
    r"(?<!\d)(" + NUM + r")(?=[\s\u00a0]*(?:" + CUR + r"|" + MONTHLY_MARK + r"))", re.I
)
# 策略 1：N × AMOUNT（N 前不得有数字，否则 3840×2160 被截成 40×2160）
RE_MUL = re.compile(r"(?<!\d)(\d{1,2})\s*[×xX*·]\s*(" + NUM + r")", re.I)
# 策略 1b：AMOUNT × N（少数站点倒着写）
RE_MUL_REV = re.compile(r"(?<!\d)(" + NUM + r")\s*[×xX*·]\s*(\d{1,2})(?!\d)", re.I)
# 策略 2：AMOUNT € /24mj、AMOUNT / 24 mjeseci（期数在斜杠后）
RE_SLASH = re.compile(
    r"(?<!\d)(" + NUM + r")[\s\u00a0]*(?:" + CUR + r")?"
    r"[\s\u00a0]*/[\s\u00a0]*(\d{1,2})[\s\u00a0]*(?:" + PERIOD_WORD + r")",
    re.I,
)

# 法律条款 / 营销话术关键词：出现在「期数 ↔ 金额」之间的一段文字里就判为 T&C，丢弃。
# Vodafone RO 的「…25€ lunar, pe o perioadă minimă contractuală de 24 luni…」是典型误报源。
TC_WORDS = re.compile(
    r"perioad[ăa]|contractual|promoț|reducere|eligibil|profilul|stocur|"
    r"RRSO|oprocent|prowizj|umow\w*|regulamin|warunki|ofert[ăa]|"
    r"условия|договор|ДДС|общ|garanț|asigura",
    re.I,
)

# 期数合理区间（低于 3 期通常是一次性付清的促销文案，高于 48 期是房贷式信贷）
MIN_PERIODS, MAX_PERIODS = 3, 48

# 「期数 ↔ 金额」之间允许的最大字符跨度
WINDOW = 200

# 两者之间允许的最大换行数。运营商 PDP 的 innerText 里，一个价格块内部通常只隔
# 2~3 行（Telekom HU「22 havi / kamatmentes részlet / Kezdőrészlet: / 1 317 Ft/hó」）。
# 超过 4 行就说明这两个数字分属不同区块——典型误报：Telekom HT 的「12 mj. rata」
# 与下一段 tariff 区块里的「25,00 EUR/mj.」被硬配成一对（实际是套餐费，不是设备分期）。
MAX_GAP_NEWLINES = 3

# S4b 的「同一行」窗口：金额与期数词必须挤在同一行、且相距不超过这么多个字符
SAME_LINE_WINDOW = 40

# 分期总额 / 设备价 的允许倍率区间。
# 下界 <1：站点常只列设备裸价、不含首付与手续费；上界 >1：含利息/服务费。
# 这个区间是拒掉「套餐月费」这类含资费整单账单（通常是设备价的 3~20 倍）的主力闸。
RATIO_MIN, RATIO_MAX = 0.45, 1.8

# 「2 年期左右」的锚点：多档期数并存时取最接近它的那一档
TARGET_PERIODS = 24

# 信号强度：乘法形态 / 斜杠形态 / 带月付标记的金额 都是强信号；
# 仅靠期数词 + 裸金额配对的是弱信号，排在后面。
STRONG, WEAK = 3, 1

# 金额后面必须紧跟货币符号或月付标记，才认它是「钱」。
# 没有这道闸，机身尺寸 "Dimenzije: 161.15 x 75.0 x 8.4 mm" 会被 S1 读成
# "15 期 × 75.0"，再乘出一个看着挺像样的假总价（Telekom HT 实测坑）。
RE_MONEY_TAIL = re.compile(r"[\s\u00a0]*(?:" + CUR + r"|" + MONTHLY_MARK + r")", re.I)


def _looks_like_money(text: str, pos: int, span: int = 16) -> bool:
    """``pos`` 之后 ``span`` 个字符内是否紧跟货币 / 月付标记。"""
    if pos < 0 or pos > len(text):
        return False
    return bool(RE_MONEY_TAIL.match(text, pos, min(len(text), pos + span)))


def _parse_amount(raw: str, dot_is_thousands: bool = False) -> float | None:
    """把本地化数字转 float（与 operator_pdp._parse_amount 同口径，独立一份避免循环导入）。"""
    if not raw:
        return None
    s = raw.strip().replace(" ", "").replace("\u00a0", "").replace("'", "")
    if not s:
        return None
    if dot_is_thousands:
        s = s.replace(".", "")
        if "," in s:
            s = s.replace(",", ".")
    else:
        if "," in s and "." in s:
            s = s.replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(".", "")
        elif "," in s:
            s = s.replace(",", ".")
    s = re.sub(r"[^0-9.]", "", s)
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _candidates(text: str, dot_is_thousands: bool):
    """产出原始候选 (periods, monthly, strength)。未做业务过滤。"""
    out: list[tuple[int, float, int]] = []

    def add(periods_raw, amount_raw, strength):
        try:
            periods = int(str(periods_raw).strip())
        except (TypeError, ValueError):
            return
        monthly = _parse_amount(amount_raw, dot_is_thousands)
        if monthly is None:
            return
        out.append((periods, monthly, strength))

    # S1 / S1b：N × AMOUNT 与 AMOUNT × N
    #     「×」两边的数字必须真的是钱 —— 页面上的机身尺寸 / 屏幕分辨率同样是
    #     "A x B x C" 形态，光靠期数区间和倍率闸挡不住（见 _looks_like_money）。
    for m in RE_MUL.finditer(text):
        if _looks_like_money(text, m.end()):
            add(m.group(1), m.group(2), STRONG)
    for m in RE_MUL_REV.finditer(text):
        if _looks_like_money(text, m.start() + len(m.group(1))):
            add(m.group(2), m.group(1), STRONG)
    # S2：AMOUNT /24mj
    for m in RE_SLASH.finditer(text):
        add(m.group(2), m.group(1), STRONG)

    # S3：期数锚点 → 窗口内所有金额
    #     （One HU 的「30 havi」后面先出现划线月付 5 600 Ft、再出现实付
    #       4 600 Ft/hó，只取第一个会拿到划线价，所以必须扫全部）
    for anchor in RE_PERIOD_ANCHOR.finditer(text):
        window = text[anchor.end(): anchor.end() + WINDOW]
        if TC_WORDS.search(window):
            continue
        for am in RE_AMOUNT.finditer(window):
            if window.count("\n", 0, am.start()) > MAX_GAP_NEWLINES:
                break  # 已跨出本价格块，后续金额只会更远
            strength = STRONG if re.match(
                r"[\s\u00a0]*(?:" + CUR + r")?[\s\u00a0]*(?:" + MONTHLY_MARK + r")",
                window[am.end(): am.end() + 24],
                re.I,
            ) else WEAK
            add(anchor.group(1), am.group(1), strength)

    # S4：金额在前、期数在后。
    #   4a) 金额带月付标记 → 允许跨行（Yettel HU「1 317 Ft/hó」…「22 hónapig」）。
    #   4b) 金额只有货币符号 → 必须与期数词同一行且间距 ≤40 字符
    #       （Plus「Opłata miesięczna za sprzęt 179,15 zł dla 12 rat」）。
    #       跨行/长间距一律不采信：Telekom HT 的「96,00 EUR」与下一段的
    #       「24 mjeseca」就是这么被硬配成假分期的。
    for am in RE_AMOUNT.finditer(text):
        after = text[am.end(): am.end() + 24]
        has_monthly = re.match(
            r"[\s\u00a0]*(?:" + CUR + r")?[\s\u00a0]*(?:" + MONTHLY_MARK + r")", after, re.I
        )
        if has_monthly:
            window = text[am.end(): am.end() + WINDOW]
            if TC_WORDS.search(window):
                continue
            for anchor in RE_PERIOD_ANCHOR.finditer(window):
                if window.count("\n", 0, anchor.start()) > MAX_GAP_NEWLINES:
                    break
                add(anchor.group(1), am.group(1), STRONG)
        else:
            # 先截断到行尾，再在这一行剩下的内容里找期数词。
            # 直接对 40 字符窗口判断「有没有 \n」是错的：短行（Plus 的
            # "…179,15 zł dla 12 rat"）窗口尾部会顺带框进下一行的换行符，
            # 结果明明是同行命中却被整条丢掉。截断后语义才等于「同行 ≤40 字符」。
            same_line = text[am.end(): am.end() + SAME_LINE_WINDOW].split("\n", 1)[0]
            if TC_WORDS.search(same_line):
                continue
            anchor = RE_PERIOD_ANCHOR.search(same_line)
            if anchor:
                add(anchor.group(1), am.group(1), WEAK)

    return out


def extract_installment(
    text: str | None,
    currency: str | None = None,
    device_total: float | None = None,
    dot_is_thousands: bool = False,
) -> dict | None:
    """从渲染后的页面文本里抽取设备分期方案。

    返回 ``{"monthly", "periods", "total", "source"}``；抓不到（或全部候选被护栏
    拒绝）时返回 ``None`` —— 宁缺勿假。

    ``device_total``（一次性付清的设备折后价）是**最强的护栏**：分期总额通常与它
    同量级，而套餐月费（含资费的整单账单）会把总额顶到几倍，直接被倍率闸拒掉。
    没有设备价时倍率闸整体跳过，改为要求金额必须带月付标记（/hó、/mj、/месец…），
    否则不予采信。
    """
    if not text:
        return None
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"[ \t]+", " ", text)

    scored = []
    for periods, monthly, strength in _candidates(text, dot_is_thousands):
        if not (MIN_PERIODS <= periods <= MAX_PERIODS):
            continue
        if monthly <= 0:
            continue
        total = monthly * periods
        ratio = (total / device_total) if (device_total and device_total > 0) else None
        if ratio is not None:
            if not (RATIO_MIN <= ratio <= RATIO_MAX):
                continue
        elif strength == WEAK:
            # 没有设备价可校验时，只采信明确标了「每月」的金额
            continue
        scored.append((periods, monthly, total, strength, ratio))

    if not scored:
        return None

    def key(c):
        periods, _monthly, total, strength, ratio = c
        # 排序：信号强度 → 总额贴近设备价（分档，避免小数点抖动抢票）→ 期数贴近 24
        # dev_gap 必须排在「期数贴近 24」之前：One HU 同时给出 (20期,4600) 与
        # (30期,4600)，只有 30×4600=138 000 才等于设备总价，若先比期数会选错成 20 期。
        dev_gap = round(abs(ratio - 1.0), 1) if ratio is not None else 0.0
        return (-strength, dev_gap, abs(periods - TARGET_PERIODS), -periods)

    scored.sort(key=key)
    periods, monthly, total, _s, _r = scored[0]
    return {
        "monthly": round(monthly, 2),
        "periods": periods,
        "total": round(total, 2),
        "source": "page_text",
    }
