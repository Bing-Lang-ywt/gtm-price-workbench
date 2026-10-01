"""Per-channel device-price extraction for operator SPA product pages (Plan A).

The generic ``gigatron`` parser grabs the *first/largest* price on a page, which
on operator webshops is almost always the monthly installment or the 2-year
contract total — never the outright device price. This module renders the SKU's
PDP with headless Chromium and extracts the **device (outright) price** using a
channel-specific rule, so competitor dashboards compare like-for-like.

Two extraction modes:
- ``text``  : match a per-channel price *label* regex against the normalized
              page text (used where the device price is a labelled string).
- ``attr``  : read a stable DOM attribute (used where the device price sits in a
              marked cell, e.g. a financing-total <td data-test-total="true">).

Only channels we have empirically validated are listed. Channels blocked by a
WAF with no workaround (Euro -> Akamai 403 on the sandbox egress IP) are
deliberately absent — returning None there keeps bad data out of the DB rather
than guessing.

Reuses the browser singleton + ENABLE_SPA_CRAWL gate from ``operator_spa``.
"""
import logging
import os
import re
import unicodedata

from app.crawling.browser_pool import run_in_browser, shutdown_browser
from app.crawling.gift import extract_gift_from_text
from app.crawling.installment import extract_installment

# Kept for backward compatibility with existing scripts/tests.
close_spa_browser = shutdown_browser

log = logging.getLogger("crawl.operator_pdp")

ENABLE_SPA_CRAWL = os.getenv("ENABLE_SPA_CRAWL", "0") == "1"

# Key = Channel.name (exact, as stored in the DB). Each entry targets the
# device-price and excludes monthly/contract totals. `band` is a plausibility
# guard in the channel's native currency so a mis-parse is rejected instead of
# stored.
#
# NOTE on Hungarian pages: they render accented chars in NFD (e + combining
# acute), so the rendered text is NFC-normalized before regex matching, and
# "készülék" (device) has a 'ü' (umlaut-u), not 'é'.
#
# NOTE on Serbian pages (Yettel RS): the thousands separator is a DOT
# ("38.764" == 38764), the opposite of a decimal point. Set
# `dot_is_thousands: True` so the parser strips the dot instead of treating it
# as a decimal. (Yettel BG uses a real decimal dot in "444.99 €", so it must
# stay False there.)
OPERATOR_PDP_CONFIG = {
    # HU: "Kedvezményes készülékár: 158 680 Ft" (discounted device price).
    # NOTE "készülék" has a 'ü' (umlaut-u), not 'é'.
    "Telekom HU": {
        # The PDP has a "Kedvezménnyel vagy listaáron" toggle. The requested
        # figure is the SIM-free sticker price behind "Szolgáltatás nélkül,
        # listaáron", rendered as "230 780 Ft listaár helyett"; the contract-
        # bound price renders as "Kedvezményes készülékár: 163 630 Ft" (what the
        # old rule captured, hence the too-low dashboard number).
        #
        # We store listaár as the price and keep the contract price in meta:
        # it is LOWER than listaár, so it cannot go into original_price without
        # breaking the "original > actual" invariant and raising a false
        # actual_gt_original flag.
        #
        # NOTE the "N Ft/hó" figures on this PDP are the TARIFF plan fee
        # (identical 18 590 Ft/hó on every device), NOT a device installment,
        # so they are deliberately NOT captured as contract_monthly.
        "currency": "HUF",
        "mode": "custom",
        "custom": "telekom_hu",
        # Stored PDP URLs pin the payment tab ("...&paymentType=onetime"), which
        # hides the interest-free financing widget and silently drops the
        # "22 × 32 478 Ft" installment leg of the dual-price spec. Drop the param
        # so the default view renders BOTH the discounted total
        # ("Kedvezményes készülékár: 714 510 Ft") and the monthly × periods split.
        "drop_query": ["paymentType"],
        "band": (10000, 1500000),
    },
    # BG: "Устройство 2554.99 € 4997.13 лв" -> device CASH price in EUR.
    # Real decimal dot ("2554.99"), so dot_is_thousands stays False.
    #
    # CRITICAL (2026-08-13): Yettel BG PDP has two payment modes toggled by
    # JS buttons: "На лизинг" (lease/installment, DEFAULT) shows the device
    # MONTHLY installment as "Устройство 122.59 € ... / месец"; "В брой"
    # (cash/lump-sum) shows the device OUTRIGHT price as "Устройство 2554.99 €".
    # The default lease mode caused Fold8 prices (~100-120€) to be mis-stored
    # as subsidy_down_payment (should be ~1900-2550€). We MUST click "В брой"
    # after dismissing the cookie banner to switch to cash mode before
    # extracting. Also the PDP URL suffix changed from "-po" to "-standart"
    # (old URLs return SPA "No metadata found for this URL" and render blank).
    # Band widened to 3000 to admit 1TB foldable cash prices (2554.99€).
    "Yettel BG": {
        "currency": "EUR",
        "mode": "text",
        "device_res": [
            r"Устройство\s*([\d\s.,]{3,9}?)\s*€",
        ],
        "cookie_btn": "Приеми всички",
        "price_mode_btn": "В брой",  # click to switch from lease (monthly) to cash (outright)
        "wait_until": "domcontentloaded",
        "settle": 8000,
        "band": (80, 3000),
    },
    # BG: A1 business-device pages ("ustroystva-za-biznesa"). The generic
    # parser grabbed the monthly lease ("Цена на лизинг"); we want the
    # outright cash price labelled "Цена в брой" (e.g. "Цена в брой 383.32 €").
    # Real decimal dot, so dot_is_thousands stays False. Band is the same
    # EUR device range used for Yettel BG.
    "A1 Bulgaria": {
        "currency": "EUR",
        "mode": "text",
        "device_res": [
            r"Цена в брой[^0-9]{0,30}?([\d][\d\s.,]{2,9}?)\s*€",
        ],
        "band": (80, 2000),
    },
    # RS (Serbia): sells contract-only — there is NO outright "device price"
    # label on the page. The device cost is the device-financing TOTAL shown in
    # the installment table, exposed via the STABLE attribute
    # `data-test-total="true"` (one row per term: 24mo / 36mo). We take the
    # smallest total (least financing interest = closest to the device cash
    # value). The page is a heavy SPA where networkidle never settles, so we
    # use domcontentloaded + an 8s settle, and must dismiss the "Dozvoli sve"
    # cookie banner first.
    # DB channel name is "Yettel RS" (Serbia) — keyed as such.
    # RS (Serbia): the PDP installment calculator is unreliable (renders a
    # hardcoded/default `data-test-total` for several models, and the value
    # even shifts between scrapes), so we read the authoritative price from the
    # public BFF JSON instead. `_extract_yettel_rs` fetches
    # /bff/pages/products/{Mfr}/{model}?lang=sr&section=consumer and takes the
    # 24-month `cosmos` device-financing total — the same concept as A1 Serbia's
    # subsidy_down_payment, so the two Serbia operators compare like-for-like.
    "Yettel RS": {
        "currency": "RSD",
        "mode": "custom",
        "custom": "yettel_rs",
        "cookie_btn": "Dozvoli sve",
        "wait_until": "domcontentloaded",
        "settle": 6000,
        # 同 A1 Serbia：页面写 "1.276 RSD" = 1276 RSD，点=千分位。
        # 影响的是分期兜底扫描的数字解析（自定义抽取器自己处理价格）。
        "dot_is_thousands": True,
        "band": (10000, 400000),
    },
    # RS (Serbia): A1 Serbia webshop ("privatni/device/..."). The no-contract
    # device CASH price is the 'Cena uređaja / Bez tarifnog paketa / NNN.NNN
    # RSD' line (device price WITHOUT a tariff commitment) — the RSD cash
    # equivalent, stored as subsidy_down_payment (consistent with Yettel RS).
    # The page renders client-side, hence domcontentloaded + settle. Serbia uses
    # a real DOT as the thousands separator ("111.990" == 111990), opposite to a
    # decimal point, so dot_is_thousands is set. Band spans budget phones
    # (~30k) to foldables (~290k+). ANCHOR on 'Bez tarifnog paketa' — the bare
    # 'Cena uređaja' token also appears in the insurance boilerplate ('cena
    # uređaja bez ugovorne obaveze'), which carries no real price. See
    # _extract_a1_serbia for why there is no loose fallback.
    "A1 Serbia": {
        "currency": "RSD",
        "mode": "custom",
        "custom": "a1_serbia",
        "wait_until": "domcontentloaded",
        "settle": 9000,
        # 塞尔维亚用点做千分位（页面写 "24 x 2.825 RSD/mes" = 2825 RSD/月）。
        # 自定义抽取器内部已经这么处理，但页面文本兜底扫描（分期）读的是这个
        # 配置 —— 缺了它 2.825 会被当成 2.825，倍率护栏随即把它判为假值拒掉，
        # 结果就是全渠道抓不到分期。
        "dot_is_thousands": True,
        "band": (10000, 400000),
    },
    # BG: "Цена без абонамент 649.00€ | 1269.33лв." -> outright device price in
    # EUR (the "price without subscription" line, distinct from the per-month
    # figure shown elsewhere). Real decimal dot, so dot_is_thousands stays
    # False. Band matches the other Bulgarian operators. vivacom.bg is a heavy
    # SPA where networkidle never settles, so degrade to domcontentloaded +
    # a longer settle (same pattern as Yettel RS).
    # NOTE: premium flagships/foldables (DemoBrand Magic V6 = 2099€, Galaxy Z
    # Fold8 Ultra = 2149€) exceed a 2000 ceiling, so the upper bound is 2500 —
    # still well below any mis-parse of the monthly/contract figures.
    # BG: vivacom 改版复盘（2026-09-03）：旧的 "Цена без абонамент ... €" 锚点
    # 已不存在。新 PDP 是套餐配置器，设备价区（"ЦЕНА НА УСТРОЙСТВО"）同时给
    # 36/24 期月付和现金价，现金价的稳定锚点是 "В брой: 549.99€"（实测 DemoBrand
    # 600 Pro）。真十进制点，dot_is_thousands=False。页面还有 "24-месечни
    # вноски 32.99€/месец" 一类月付行，锚点只认 "В брой" 前缀，不会误抓。
    # band 下限 50：锚点收紧到只认 "В брой" 现金价后，低端机（A17 59.99€ /
    # H600Smart 79.99€，2026-09-03 实测）是合法裸机价，80 的旧下限会把它们
    # 全拒掉；50 与写库层 EUR subsidy plausibility band 一致（更低的会触发
    # PlausibilityError，提前拦更干净）。Redmi 15C 实测 39.99€ < 50 属已知
    # 诚实缺失，不硬塞。
    "vivacom": {
        "currency": "EUR",
        "mode": "text",
        "device_res": [
            r"В брой\s*:?\s*([\d][\d.,]{1,9}?)\s*€",
        ],
        "wait_until": "domcontentloaded",
        "settle": 8000,
        "band": (50, 2500),
    },
    # FI: Elisa verkkokauppa. "Kertamaksu 999,00 €" = 一次性全额（裸机价），
    # 同一区块还渲染 12/24/36 kk 分期（"24 kk 41,61 €/kk"）—— 分期由通用
    # installment 扫描处理（芬兰语 kk/kuukausi 已在词表里）。真十进制逗号 +
    # 空格千分位 → dot_is_thousands=False。注意页面还有 "30 päivän alin hinta
    # 799,00 €"（30 天最低价，历史信息），锚点只认 "Kertamaksu" 前缀，不会
    # 误抓。2026-09-03 之前该渠道无配置、走 gigatron 适配器，抓到的 7.46€/kk
    # 这类融资月付被 Plausibility band 拒掉（16/19 SKU 失败）—— 这正是
    # 「缺 OPERATOR_PDP_CONFIG 条目 → 运营商站走市场适配器」的已知失败模式。
    "Elisa": {
        "currency": "EUR",
        "mode": "text",
        "device_res": [
            r"Kertamaksu\s*([\d][\d\u00a0\s.,]*?)\s*€",
        ],
        "settle": 6000,
        "band": (80, 4000),
    },
    # PL: "Urządzenie w ofercie z abonamentem: 2399,00 zł" -> device price in
    # PLN (the handset total inside the bundled-offer block). The generic
    # "Urządzenie" token also appears in the monthly-installment ("rata 0% za
    # urządzenie 79,17 zł") and start-fee ("opłata na start za urządzenie
    # 499,00 zł") lines, so we anchor on the full "w ofercie z abonamentem"
    # phrase to grab the device TOTAL, not an installment. Real decimal comma,
    # so the parser treats the comma as a decimal point. Band is the PLN range.
    "Play": {
        "currency": "PLN",
        "mode": "text",
        "device_res": [
            r"Urz[aą]dzenie w ofercie z abonamentem:?\s*([\d\s.,]{3,9}?)\s*zł",
        ],
        # PL: heavy SPA — networkidle never settles (live chat / analytics
        # polling), which starved the channel for 10 days (08-14→08-24) with
        # "Page.goto: Timeout 40000ms exceeded". Device price is server-rendered
        # in the initial HTML, so domcontentloaded + settle is enough.
        "wait_until": "domcontentloaded",
        "settle": 8000,
        "band": (300, 12000),
    },
    # RO: Vodafone Romania webshop. The PDP DEFAULTS to a contract/plan view
    # ("de la 28€ lunar" with a RED Max plan) that hides the outright device
    # price. Clicking "Vrei produsul fără abonament?" (without subscription)
    # switches to the no-contract view, which shows the device OUTRIGHT price
    # as "Preț 1.015,20€" (EUR, dot=thousands, comma=decimal). We MUST click
    # that toggle before extracting — same two-mode pattern as Yettel BG. The
    # old regexes ("Prețul telefonului ... lei") never matched because that
    # label does not exist and the displayed currency is EUR, not RON.
    # Currency is EUR; real decimal comma + thousands dot -> dot_is_thousands.
    #
    # REGRESSION FIXED 2026-09-02: the loose `Pre[țt][^0-9]{0,15}?` prefix
    # matched the INSURANCE BOILERPLATE at the page footer -
    # "...smartphone-urile Apple cu pret sub 2600€" - so EVERY Vodafone RO SKU
    # was stored as a constant 2600 EUR from 08-29 onwards (14 SKUs/run, run
    # still reported "success" => silent false-positive). The "Vrei produsul
    # fără abonament?" toggle also no longer exists (click times out), so the
    # outright price is not currently reachable at all.
    # The prefix is now TIGHT (label immediately followed by the amount), which
    # kills the boilerplate match. If the real label ever renders again it still
    # matches; otherwise the channel yields "parse failure" and writes NOTHING,
    # which is the correct behaviour - no data beats fabricated data.
    "Vodafone RO": {
        "currency": "EUR",
        "mode": "text",
        # 2026-09-03 改版复盘：PDP 换成标签页「Cu abonament / Fără abonament」，
        # 旧的整句按钮 "Vrei produsul fără abonament?" 已不存在；裸机价只在点击
        # 「Fără abonament」标签后出现，且紧跟标签、无 "Preț" 前缀（实测
        # DemoBrand 600 Pro = "Fără abonament 1.015,20€"）。
        # (?!\s*lunar) 是关键护栏：若标签点击失败留在默认（合约）视图，同一位置
        # 渲染的是套餐月价（"Fără abonament 28€ lunar"），不带它就会把套餐价
        # 当裸机价 —— 这正是 2026-09-02 2600€ 事故的同族错误。band 下限 80
        # 只能拦住小额套餐价，拦不住高端机的 85€+ 月价，必须双保险。
        "device_res": [
            r"Fără abonament\s*([\d][\d\s.,]{2,}?)\s*€(?!\s*lunar)",
            r"Pre[țt]ul telefonului\s*:?\s*([\d][\d\s.,]{2,})\s*€",
            r"Pre[țt]\s*:?\s*([\d][\d\s.,]{2,})\s*€",
        ],
        "cookie_btn": "Acceptați toate",
        "price_mode_btn": "Fără abonament",
        "no_gift": True,
        "dot_is_thousands": True,
        "wait_until": "domcontentloaded",
        "settle": 8000,
        "band": (80, 3000),
    },
    # RO: Orange Romania webshop ("magazin-online/..."). The device price is the
    # 'Preț telefon' (phone price) line, RON, e.g. 'Preț întreg / Preț telefon /
    # 3479 ,03 Lei'. Romanian format = DOT thousands separator + COMMA decimal,
    # so dot_is_thousands is set (strips the dot, keeps the comma as decimal).
    # The page renders client-side (SPA), hence domcontentloaded + settle.
    # 'Preț telefon' is the device price and is STABLE across the contract /
    # no-contract (isNoSubsidy) views, so we store it as subsidy_down_payment
    # (consistent with Vodafone RO's device basis and the Serbia operators).
    # ANCHOR on 'Preț telefon': the old gigatron path (Orange RO had NO config
    # and was mis-routed to the gigatron adapter) grabbed a stray '30.0 RON'
    # tariff shard — exactly the silent false-positive class we must avoid.
    "Orange RO": {
        "currency": "RON",
        "mode": "custom",
        "custom": "orange_ro",
        "dot_is_thousands": True,
        "wait_until": "domcontentloaded",
        "settle": 10000,
        "band": (500, 15000),
    },
    # HR: Telemach Croatia AngularJS SPA. The on-plan device total is surfaced
    # as "Odmah plaćaš uređaj" (pay the device now = full price) and, on some
    # configs, "Cijena uređaja". The page renders client-side, so use
    # domcontentloaded + a longer settle. Decimal comma ("699,00 €") is handled
    # by the default parser. "Plaćaš odmah" / "Unaprijed plaćaš" are the upfront
    # fee and are ordered last as a fallback.
    "Telemach": {
        "currency": "EUR",
        "mode": "text",
        "device_res": [
            r"Odmah pla[ćc]a[šs]\s*ure[đd]aj[^0-9]{0,20}?([\d\s.,]{2,7}?)\s*€",
            r"Cijena ure[đd]aja[^0-9]{0,30}?([\d\s.,]{2,7}?)\s*€",
            r"Pla[ćc]a[šs]\s*odmah:\s*([\d\s.,]{2,7}?)\s*€",
            r"Unaprijed pla[ćc]a[šs]\s*([\d\s.,]{2,7}?)\s*€",
        ],
        "wait_until": "domcontentloaded",
        "settle": 9000,
        "band": (80, 2500),
    },
    # HU: Yettel Hungary webshop (yettel.hu). The PDP renders client-side via
    # the same Angular SPA pattern as One HU; static httpx cannot see the
    # "Teljes ár" or "Készülék listaár" lines. The Yettel page exposes both
    # pieces consistently across the device summary AND the installment
    # selector ("Teljes ár: 53 990 Ft" repeats 3 times per PDP for 22/12/6
    # month terms, all identical):
    #   "Készülék listaár"             = list price  (划线) e.g. 251 990 Ft
    #   "Hűségidő kedvezmény"          = loyalty discount (skipped, derives original)
    #   "Kedvezményes készülék ár"     = discounted device price  e.g. 103 990 Ft
    #   "Teljes ár: X Ft"              = one-time device price    <-- store this
    # The list price is captured from the detailed summary block
    # ("Készülék listaár ... Ft" appears once per PDP). The custom extractor
    # returns (actual, original).
    # NOTE on Hungarian NFD: pages ship accented chars decomposed (e + combin-
    # ing acute) — NFC normalization is applied before regex match (matches
    # One HU handling).
    "Yettel HU": {
        "currency": "HUF",
        "mode": "custom",
        "custom": "yettel_hu",
        "wait_until": "domcontentloaded",
        "settle": 5000,
        # The stored price is the SIM-free list price ("Készülék listaár"), the
        # same basis Telekom HU uses, so 0 is no longer admissible: a bundle
        # device still has a list price (600 Lite = 146 990 Ft) and its 0 Ft
        # contract fee lives in meta.contract_device_price. A 0 here now means
        # the scrape broke and must be rejected.
        "band": (10_000, 1_500_000),
    },
    # HU: One HU webshop (one.hu). The PDP defaults to a monthly-installment
    # view; the **one-time device price** ("Egy összegben") and its strikethrough
    # original + discount only render after JS hydration. Static httpx grabs the
    # JSON-LD ``price`` (81000) which is the ORIGINAL list price, not the
    # discounted lump-sum the customer pays. Render + read the hydrated block:
    #   "Készülék teljes ára" = original (划线)  e.g. 81 000 Ft
    #   "Készülékkedvezmény"  = discount          e.g. -30 000 Ft
    #   "Összesen"            = actual lump-sum   e.g. 51 000 Ft  <-- store this
    "One HU": {
        "currency": "HUF",
        "mode": "custom",
        "custom": "one_hu",
        "wait_until": "domcontentloaded",
        "settle": 4000,
        "band": (1000, 2_000_000),
    },
    # HR: Telekom Hrvatska (hrvatskitelekom.hr) AngularJS SPA. The on-plan page
    # exposes two tabs: "Mjesečno" (monthly) and "Jednokratno" (one-time). The
    # one-time device price + its original (strikethrough) live ONLY in the GA
    # dataLayer, not the DOM:
    #   productDetails.ecommerce.detail.products[0].price = original (划线) e.g. 1002.48
    #   view_item.ecommerce.items[0].price               = actual (一次性)   e.g. 978.48
    # The generic parser instead grabbed device_monthly × 24 (= 107.76) which is
    # the subsidized financed total, not the device cash price. dataLayer objects
    # contain circular refs -> never JSON.stringify the whole array.
    "Telekom HT": {
        "currency": "EUR",
        "mode": "custom",
        "custom": "telekom_ht",
        "cookie_btn": "Prihvati sve",
        "wait_until": "domcontentloaded",
        "settle": 7000,
        "band": (50, 3000),
    },
    # HR: A1 Croatia webshop ("mobiteli-na-pretplatu"). The device financing
    # price is surfaced as "X € odmah + Y € /24mj" (upfront + monthly device
    # installment) under the "UREĐAJ" heading, listed twice (standard price +
    # after the per-cart webshop discount). The "UKUPNO" line is device+tariff
    # and is excluded by the custom extractor. We compute the device financing
    # TOTAL = upfront + monthly*24 and store it as subsidy_down_payment. The
    # generic gigatron parser grabbed the mislabeled 24-month plan total
    # (~3300 EUR, constant across every device) — see _extract_a1_croatia.
    "A1 Croatia": {
        "currency": "EUR",
        "mode": "custom",
        "custom": "a1_croatia",
        "wait_until": "domcontentloaded",
        "settle": 9000,
        "band": (50, 3000),
    },
    # PL: Plus.pl SPA. Device price lives in schema.org JSON-LD
    # (Product/Offer with priceSpecification.priceComponent[]):
    # offers.price = device financing TOTAL (downpayment + installments);
    # the Downpayment component is the upfront fee, Installment the monthly.
    # Surface the total as the device price and the monthly separately so the
    # matrix shows both legs and nothing overwrites the total with monthly x 24.
    # Static HTML carries the JSON-LD, so domcontentloaded + short settle works.
    # NOTE (2026-09-02): this channel had NO config in the live deployment, so
    # every Plus SKU failed with "could not parse price" (18/19 SKUs). Ported
    # from the handoff copy where it was verified.
    "Plus": {
        "currency": "PLN",
        "mode": "custom",
        "custom": "plus",
        "wait_until": "domcontentloaded",
        "settle": 6000,
        "band": (0, 20000),
    },
}


def _parse_amount(raw: str, dot_is_thousands: bool = False):
    """Parse a localized amount.

    Handles space-thousands ('158 680') and dot-decimal ('444.99'). When
    ``dot_is_thousands`` is set (Serbian format) a dot is a thousands separator
    and is stripped, e.g. '38.764 RSD' -> 38764. Returns float or None.
    """
    if not raw:
        return None
    s = raw.strip().replace(" ", "").replace("\u00a0", "")
    if not s:
        return None
    if dot_is_thousands:
        s = s.replace(".", "")
        if "," in s:
            s = s.replace(",", ".")
    else:
        if "," in s and "." in s:
            # last separator is the decimal point
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


def _extract_text_price(txt: str, cfg: dict):
    """Mode 'text': match the device-price label regex against page text."""
    # Hungarian pages ship accented chars in NFD (e + combining acute);
    # normalize so our composite-character regexes match.
    txt = unicodedata.normalize("NFC", txt)
    txt = re.sub(r"\s+", " ", txt)
    for pat in cfg["device_res"]:
        m = re.search(pat, txt, re.I)
        if m:
            price = _parse_amount(m.group(1), cfg.get("dot_is_thousands", False))
            if price is not None:
                return price
    return None


def _extract_attr_price(page, cfg: dict):
    """Mode 'attr': read a stable DOM attribute and take the smallest
    band-plausible value (handles multiple installment-term rows)."""
    attr = cfg["attr"]
    attr_name = attr["name"]
    attr_val = attr.get("value", "")
    dot_is_thousands = cfg.get("dot_is_thousands", False)
    lo, hi = cfg["band"]
    js = (
        "() => {"
        f"  const els = Array.from(document.querySelectorAll('[{attr_name}=\"{attr_val}\"]'));"
        "  return els.map(e => (e.innerText || e.textContent || '').trim());"
        "}"
    )
    try:
        texts = page.evaluate(js)
    except Exception as exc:  # noqa: BLE001
        log.warning("operator pdp attr eval failed: %s", exc)
        return None
    valid = []
    for t in texts:
        p = _parse_amount(t, dot_is_thousands=dot_is_thousands)
        if p is not None and lo <= p <= hi:
            valid.append(p)
    if not valid:
        return None
    # smallest total == least financing interest == closest to device cash value
    return min(valid)


# -- custom extractors (return {"price":float, "original_price":float|None}) ----
_FT_RE = re.compile(r"([\d\u00a0\s]{2,12})\s*Ft")


def _ft_to_int(s: str):
    s = s.replace("\u00a0", "").replace(" ", "").strip()
    s = re.sub(r"[^\d]", "", s)
    return int(s) if s else None


def _first_ft_after(text: str, label: str):
    i = text.find(label)
    if i < 0:
        return None
    m = _FT_RE.search(text, i)
    return _ft_to_int(m.group(1)) if m else None


def _extract_one_hu(page):
    """One HU: hydrated innerText carries the lump-sum block
    'Készülék teljes ára / Készülékkedvezmény / Összesen' = original/discount/actual."""
    txt = unicodedata.normalize("NFC", page.evaluate("()=>document.body.innerText"))
    m = re.search(
        r"Készülék teljes ára[\s\S]{0,80}?Összesen[\s\S]{0,40}?"
        r"([\d\u00a0\s]{2,12})\s*Ft"
        r"[\s\S]{0,40}?-\s*([\d\u00a0\s]{2,12})\s*Ft"
        r"[\s\S]{0,40}?([\d\u00a0\s]{2,12})\s*Ft",
        txt,
    )
    if m:
        original = _ft_to_int(m.group(1))
        actual = _ft_to_int(m.group(3))
        if original and actual:
            return {"price": float(actual), "original_price": float(original)}
    # fallback: label-anchored first Ft after each label
    original = _first_ft_after(txt, "Készülék teljes ára")
    actual = _first_ft_after(txt, "Összesen")
    if original and actual:
        return {"price": float(actual), "original_price": float(original)}
    # P2-16: copy re-worded / SPA relayout -> try structured data before giving
    # up on the SKU.
    return _structured_fallback(page, "One HU")


def _extract_telekom_ht(page):
    """Telekom HT: page server-renders ALL price tiers as inline JSON in the
    HTML source: ``'OneTimePrice':<n>``, ``'SplitContractPrice':<n>``.

    There are 3 distinct price tiers per SKU (lowest "no Magenta1", middle
    "default Tarifa S 24-month", highest "Magenta1 ON"). The Cijena uređaja
    panel on the user-facing page shows the **middle** tier. We pick the
    median of deduped values so the DB matches the screenshot semantic
    ("Cijena uređaja 385,76 EUR" style position).

    No Playwright needed — fetch the page HTML once and parse. We still use
    run_in_browser as a thin wrapper to demobrand the existing cookie banner
    click + settle timing (and to be plug-compatible with the call site)."""

    html = page.content()
    ots = sorted({float(v) for v in re.findall(r"'OneTimePrice'\s*:\s*([\d.]+)", html) if float(v) > 0})
    sps = sorted({float(v) for v in re.findall(r"'SplitContractPrice'\s*:\s*([\d.]+)", html) if float(v) > 0})
    if not ots:
        return None
    actual = ots[len(ots) // 2]  # middle tier = default Tarifa S state
    # Pair the SplitContractPrice to the SAME price tier by index. Both lists
    # are sorted ascending with one entry per tier (no Magenta1 / default /
    # Magenta1 ON), so the middle index aligns. This replaces the old
    # `abs(v - (actual + 10))` magic offset, which returned a wrong or empty
    # original whenever the tier spread wasn't exactly 10 EUR.
    original = None
    if sps:
        idx = min(len(ots) // 2, len(sps) - 1)
        original = sps[idx]
    if original and original > actual:
        return {"price": float(actual), "original_price": float(original)}
    if actual:
        return {"price": float(actual), "original_price": None}
    return None


def _parse_telekom_hu_text(txt: str):
    """Pure-text parser for the Telekom HU PDP (dual-price model).

    Returns ``{"price": discounted one-time total, "original_price": list
    price, "meta": {"installment": {...}}|None}`` — or ``None`` when the
    discounted-price anchor is missing.

    Telekom HU surfaces TWO device prices on the hydrated PDP::

        849 860 Ft listaár helyett                 <- SIM-free LIST price (原价)
        Készülék kedvezményes ára / Egy összegben /
        Kamatmentes részletre  = 714 510 Ft        <- DISCOUNTED one-time /
                                                        interest-free installment
                                                        TOTAL (折后) the customer pays

    The user's spec: record the DISCOUNTED price, mark original vs discounted.
    So ``price`` = 折后 (714 510), ``original_price`` = listaár (849 860). On
    Telekom HU the one-time and the interest-free installment total are the SAME
    number (no contract subsidy, just payment method), so 折后 == one-time ==
    installment total — and ``meta.installment`` carries the monthly × periods
    split when the financing widget exposes it.

    The "N Ft/hó" figures on this PDP are the TARIFF plan fee (identical on
    every device), NOT a device installment, so they are deliberately NOT
    stored as ``contract_monthly`` (see crawl.py, which would otherwise make
    Telekom HU look 2.7x more expensive than it is).
    """
    # 原价 (list price): "X Ft listaár helyett"
    original = None
    m = re.search(r"([\d][\d\s\u00a0]{2,11}?)\s*Ft\s*lista[aá]r", txt, re.I)
    if m:
        original = _ft_to_int(m.group(1))

    # 分期 / installment split FIRST: "N × M Ft" (N months at M Ft/month).
    # Parsed up-front so the price anchors below can reject the monthly leg
    # (see the guard in the price loop — this is what stopped the default PDP
    # from reporting the 32 478 Ft/month installment as the device total).
    monthly = None
    periods = None
    m = re.search(r"(\d{1,2})\s*[x×]\s*([\d][\d\s\u00a0]{2,11}?)\s*Ft", txt)
    if m:
        periods = int(m.group(1))
        monthly = _ft_to_int(m.group(2))

    # 折后 (discounted device TOTAL). Order is load-bearing:
    # "Kedvezményes készülékár: 714 510 Ft" is the explicit, authoritative
    # discounted total and MUST win over "Egy összegben" — on the default
    # (unpinned) PDP that tab renders the financing widget inline as
    # "Egy összegben 22 × 32 478 Ft", so a naive "next number after the label"
    # match grabs the MONTHLY (32 478) and reports it as the device price
    # (~22x too low — a silent, catastrophic false low).
    # Two guards: (a) explicit total anchors are tried before the tab labels;
    # (b) any candidate equal to the installment monthly leg is rejected.
    price = None
    for label in ("Kedvezményes készülékár", "Készülék kedvezményes ára",
                  "Kamatmentes részletre", "Egy összegben"):
        for m in re.finditer(
            re.escape(label) + r"[^0-9]{0,20}?([\d][\d\s\u00a0]{2,11}?)\s*Ft",
            txt, re.I,
        ):
            cand = _ft_to_int(m.group(1))
            if not cand:
                continue
            if monthly and cand == monthly:
                continue  # the per-month installment leg, not the device total
            price = cand
            break
        if price:
            break

    if price is None:
        return None

    meta = {}
    # When the financing widget is rendered we keep the monthly × periods split
    # so the matrix can show BOTH legs (one-time vs installment). If the widget
    # is absent (e.g. a pinned one-time tab) ``installment`` is simply omitted —
    # honest: we never invent a term/monthly the page did not show.
    if monthly and periods:
            # NOTE: the per-month figure is rounded on the PDP, so
            # monthly × periods may differ by a few Ft from the displayed total
            # (e.g. 32 478 × 22 = 714 516 vs the shown 714 510). We keep the
            # AUTHORITATIVE discounted total (``price`` / "Egy összegben") as
            # ``installment.total`` and treat monthly × periods as the rounded
            # breakdown, so the matrix never shows a total that contradicts the
            # headline one-time price.
            meta["installment"] = {
                "monthly": float(monthly),
                "periods": periods,
                "total": float(price),
            }

    return {
        "price": float(price),
        "original_price": float(original) if original else None,
        "meta": meta or None,
    }


def _extract_telekom_hu(page):
    """Telekom HU: return the discounted one-time device price (折后) and the
    list price (原价) via :func:`_parse_telekom_hu_text`.

    Per the user's dual-price spec we store the DISCOUNTED price as ``price``
    (not the list price), so operator channels compare like-for-like on the
    amount the customer actually pays.
    """
    txt = unicodedata.normalize("NFC", page.evaluate("()=>document.body.innerText"))
    txt = re.sub(r"\s+", " ", txt)
    parsed = _parse_telekom_hu_text(txt)
    if parsed is None:
        # Copy re-worded / toggle relayout -> try structured data rather than
        # silently falling back to a wrong (e.g. list-only) figure.
        return _structured_fallback(page, "Telekom HU")
    return parsed


def _parse_yettel_hu_text(txt: str):
    """Pure-text parser for the Yettel HU PDP (dual-price model).

    Returns ``{"price": discounted one-time total (折后), "original_price": list
    price (原价), "meta": {...}}`` or ``None`` when the list-price anchor is
    missing.

    Yettel HU surfaces two device figures:
      * "Készülék listaár X Ft"        = SIM-free LIST price (原价)
      * "Teljes ár: Y Ft" / "Kedvezményes készülék ár Y Ft"
                                       = the one-time device price the customer
                                         actually pays (折后)

    Per the user's dual-price spec we store 折后 (``price``) and listaár
    (``original_price``), exactly like Telekom HU — so every operator channel
    compares on the amount the customer pays, and the dashboard can strike
    through the list price. The list price is still captured as the original so
    the discount depth is visible.

    Bundle-only devices ("Kedvezményes készülék ár 0 Ft" = free with a Yettel
    Prime Max subscription): there is no positive 折后, so the device's real
    value is its listaár; we store ``price = listaár`` and ``original_price =
    None`` and keep ``contract_device_price = 0`` in meta, so the cell headline
    stays comparable and the annotation reads "签约赠机 0 Ft · 套餐 X/月".
    """
    # SIM-free list price ("Készülék listaár") — only on device summary blocks,
    # NOT on tartozekok (accessory) pages where the label reads "Tartozék listaár".
    listaar = None
    m = re.search(
        r"K[eé]szül[eé]k\s*lista[aá]r[^0-9]{0,12}?([\d][\d\s\u00a0]{2,11}?)\s*Ft",
        txt,
    )
    if m:
        listaar = _ft_to_int(m.group(1))

    # 折后 (one-time device price the customer pays). case 1: "Teljes ár: Y Ft"
    # (repeated once per installment option, all identical).
    contract_dev = None
    m = re.search(
        r"Teljes\s*[aáAÁ]r[^0-9]{0,12}?([\d][\d\s\u00a0]{2,11}?)\s*Ft",
        txt,
    )
    if m:
        contract_dev = _ft_to_int(m.group(1))

    # case 2: bundle-only — "Kedvezményes készülék ár 0 Ft".
    if contract_dev is None:
        m = re.search(
            r"Kedvezm[eé]nyes\s+k[eé]szül[eé]k\s*[aá]r[^0-9]{0,12}?(0|[1-9][\d\s\u00a0]{0,11}?)\s*Ft",
            txt,
        )
        if m:
            contract_dev = _ft_to_int(m.group(1))

    if listaar is None:
        # No list price anchor -> copy re-worded / SPA relayout / not a device
        # page. Do NOT silently fall back to contract_dev.
        return None

    if contract_dev and contract_dev > 0:
        price = contract_dev          # 折后 (customer-paid one-time)
        original = listaar             # 原价 (list)
    else:
        # Bundle-only or no positive 折后: the device's real value is its listaár.
        price = listaar
        original = None

    # Monthly payable ("Havonta fizetendő X Ft/hó") — the TARIFF PLAN FEE, NOT a
    # device instalment (it reads identically for a 0 Ft bundle phone and a 710
    # 990 Ft Z Fold8 Ultra). Kept in meta as an annotation; never written to
    # contract_monthly.
    monthly = None
    m = re.search(
        r"Havonta\s*fizetend[eő]\s*([\d][\d\s\u00a0]{2,11}?)\s*Ft/h[oó]",
        txt,
    )
    if m:
        monthly = _ft_to_int(m.group(1))

    meta = {}
    if contract_dev is not None:
        meta["contract_device_price"] = contract_dev
    if monthly:
        meta["monthly_payable"] = float(monthly)
    return {
        "price": float(price),
        "original_price": float(original) if original else None,
        "meta": meta or None,
    }


def _extract_yettel_hu(page):
    """Yettel HU: return the discounted one-time device price (折后) and the list
    price (原价) via :func:`_parse_yettel_hu_text`.

    Like Telekom HU we store 折后 as ``price`` so operator channels compare
    like-for-like on the amount the customer actually pays; listaár is kept as
    ``original_price`` so the dashboard can strike it through.
    """
    txt = unicodedata.normalize("NFC", page.evaluate("()=>document.body.innerText"))
    txt = re.sub(r"\s+", " ", txt)
    parsed = _parse_yettel_hu_text(txt)
    if parsed is None:
        # No list-price anchor -> copy re-worded / SPA relayout / not a device
        # page. Do NOT silently fall back to contract_dev.
        return _structured_fallback(page, "Yettel HU")
    return parsed


# -- out-of-stock / not-sold detection (P2-14) ---------------------------------
# Operators previously hard-coded `in_stock=True`, so a delisted / sold-out
# device kept showing a price. These phrases are unambiguous "not available"
# markers across the CEE languages we crawl. They are deliberately specific
# (we never key off a bare word like "stock") so a related-products widget
# saying "sold out" next to a *different* item can't false-flag the device.
_STOCK_OUT_RE = re.compile(
    r"nem\s*[ée]rt[eé]kes[ií]t|nem\s+kaphat[oó]|elfogyott|"
    r"nincs\s+k[eé]szleten|"
    r"nema\s+na\s+stanju|rasproda[nl]|"
    r"out of stock|sold out|nenije dostupno",
    re.I,
)


def _is_out_of_stock_text(txt: str) -> bool:
    """True when ``txt`` clearly states the device is not available."""
    if not txt:
        return False
    return bool(_STOCK_OUT_RE.search(unicodedata.normalize("NFC", txt)))


def _operator_in_stock(page, url: str) -> bool:
    """Best-effort in-stock determination for an operator PDP.

    Two negative signals:
      * a mis-linked accessory / sibling page (Yettel HU device pages live
        under ``/tartozekok/`` and carry no device price) -> not a real offer;
      * clear out-of-stock / not-sold copy in the rendered text.
    Anything we can't read is assumed in-stock (fail open) so a transient
    render glitch never hides a price that is actually there.
    """
    if url and "/tartozekok/" in url.lower():
        return False
    try:
        txt = page.evaluate("() => document.body.innerText")
    except Exception:  # noqa: BLE001
        return True
    return not _is_out_of_stock_text(txt)


# -- structured-data fallback (P2-16) ----------------------------------------
# The Hungarian operators are SPAs whose device price is surfaced through
# copy-sensitive labels ("Készülék teljes ára", "Teljes ár", ...). When a page
# is re-worded (A/B test, localization) the text anchors above silently return
# None and we lose the SKU. As a resilient backstop we re-parse the rendered
# page's structured data (JSON-LD Product/Offer) and accept the device price
# only when it sits inside the channel's own plausibility band. This reuses the
# well-tested generic parser, so the fallback can never be *less* safe than the
# primary path — and it only runs when the primary anchor has already failed.
def _structured_fallback(page, channel_name: str):
    cfg = OPERATOR_PDP_CONFIG.get(channel_name)
    if not cfg:
        return None
    try:
        html = page.content()
    except Exception:  # noqa: BLE001
        return None
    try:
        from app.crawling.market_common import parse_price_page

        data = parse_price_page(html, "", expected_currency=cfg["currency"])
    except Exception:  # noqa: BLE001
        return None
    price = data.get("price")
    if price is None:
        return None
    lo, hi = cfg["band"]
    if not (lo <= price <= hi):
        return None
    return {
        "price": float(price),
        "original_price": float(data["original_price"])
        if data.get("original_price") else None,
    }


def _extract_product_name(page):
    """Best-effort page self-reported product name, consumed by the price
    audit's ``product_mismatch`` guard. Operators previously returned no name,
    so the guard never ran for them (A1 audit finding). Tries JSON-LD Product
    name, then ``<h1>``, then ``document.title``.
    """
    try:
        return page.evaluate(
            "() => {"
            "  try {"
            "    const nodes = document.querySelectorAll('script[type=\"application/ld+json\"]');"
            "    for (const n of nodes) {"
            "      try {"
            "        const j = JSON.parse(n.textContent || '{}');"
            "        const arr = Array.isArray(j) ? j : (j['@graph'] || [j]);"
            "        for (const o of arr) {"
            "          if (o && (o['@type'] === 'Product' || o['@type'] === 'product') && o.name) return o.name;"
            "        }"
            "      } catch (e) {}"
            "    }"
            "  } catch (e) {}"
            "  const h1 = document.querySelector('h1');"
            "  if (h1 && h1.innerText && h1.innerText.trim()) return h1.innerText.trim();"
            "  return (document.title || '').trim();"
            "}"
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("operator pdp product_name eval failed: %s", exc)
        return None


def _extract_yettel_rs(page):
    """Yettel RS (Serbia): the PDP's installment calculator is unreliable — for
    several models it renders a hardcoded/default `data-test-total` (e.g. three
    different budget phones all show the identical 12.856 RSD total) and the
    value even shifts between scrapes. The authoritative price lives in the
    public BFF JSON the SPA fetches:

        /bff/pages/products/{Manufacturer}/{model}?lang=sr&section=consumer

    We read `assignedTariffPackage.prices.cosmos` (the device financed over N
    months on the default-selected tariff) and take the 24-month row — this is
    the device-financing total, i.e. the same concept as A1 Serbia's
    `subsidy_down_payment` (monthly x 24), so the two Serbia operators compare
    like-for-like. `priceOld` (when present) is the struck-through original.
    """
    bff_url = page.evaluate(
        "() => {"
        "  const u = new URL(location.href);"
        "  const m = u.pathname.match(/Mobilni-telefoni\\/(.+)$/);"
        "  if (!m) return null;"
        "  return `https://${u.host}/bff/pages/products/${m[1]}?lang=sr&section=consumer`;"
        "}"
    )
    if not bff_url:
        return None

    data = page.evaluate(
        "async (url) => {"
        "  try {"
        "    const r = await fetch(url, {credentials: 'include'});"
        "    if (!r.ok) return {__err: 'http ' + r.status};"
        "    return await r.json();"
        "  } catch (e) { return {__err: String(e)}; }"
        "}",
        bff_url,
    )
    if not isinstance(data, dict) or data.get("__err"):
        log.warning("yettel_rs bff fetch failed: %s", data.get("__err") if isinstance(data, dict) else data)
        return None

    product = (data.get("data") or {}).get("product") or {}
    if not product:
        return None

    def _cosmos_rows(pkg):
        prices = (pkg or {}).get("prices") or {}
        cosmos = prices.get("cosmos") or []
        return [c for c in cosmos if isinstance(c, dict) and c.get("installments") and c.get("price") is not None]

    # Each model exposes several tariff packages, each with a 24-month `cosmos`
    # device-financing total. The assigned/default package is always the
    # CHEAPEST and for some budget models collapses to a shared placeholder
    # floor (e.g. DemoBrand 600 Lite and Redmi Note 15 both show 12.856 RSD), so it
    # is NOT a reliable per-device figure. We instead take the MEDIAN 24-month
    # `cosmos` total across all tariff packages — a robust mid-tier device
    # price that stays distinct per model and tracks peer A1 Serbia within a
    # few percent (DemoBrand 600 ~47.2k vs 45k, Redmi Note 15 ~17.2k vs 17.4k).
    candidates = []  # (price, installments, priceOld)
    for pkg in product.get("tariffPackages") or []:
        rows = _cosmos_rows(pkg)
        if not rows:
            continue
        rows.sort(key=lambda c: c["installments"])
        chosen = next((c for c in rows if c["installments"] == 24), rows[0])
        candidates.append((float(chosen["price"]), int(chosen["installments"]),
                           chosen.get("priceOld")))
    # Fallback to the assigned package if no tariff packages carried cosmos.
    if not candidates:
        rows = _cosmos_rows(product.get("assignedTariffPackage"))
        if rows:
            rows.sort(key=lambda c: c["installments"])
            chosen = next((c for c in rows if c["installments"] == 24), rows[0])
            candidates.append((float(chosen["price"]), int(chosen["installments"]),
                               chosen.get("priceOld")))
    if not candidates:
        return None

    candidates.sort(key=lambda t: t[0])
    price, inst, original = candidates[len(candidates) // 2]  # median
    original = float(original) if original not in (None, "") else None
    monthly = round(price / inst, 2) if inst else None
    # Carry the authoritative BFF product name so fetch_operator_pdp won't
    # overwrite it with an unreliable DOM name (which would otherwise trip the
    # product_mismatch guard). A genuine wrong-page still mismatches here.
    bff_name = product.get("name") or product.get("title") or product.get("displayName")
    return {
        "price": price,
        "original_price": original,
        "contract_monthly": monthly,
        "meta": {"product_name": bff_name},
    }


def _extract_a1_croatia(page):
    """A1 Croatia (HR): webshop PDP shows the device financing price as
    'X € odmah + Y € /24mj' (upfront + monthly device installment over 24
    months), listed TWICE under the 'UREĐAJ' (device) heading — once at the
    operator's standard device price and once after the per-cart webshop
    discount (the difference equals the stated 'Webshop popust od N€').
    The 'UKUPNO' (total) line is device + tariff and must be excluded.

    We take the HEADLINE (first) device variant and compute the device
    financing TOTAL = upfront + monthly*24, which is the operator's
    ``subsidy_down_payment`` basis (consistent with Telemach HR / Yettel BG
    storing the device's financed/total price rather than a promo-discounted
    one). The generic gigatron parser used to grab the mislabeled 24-month
    tariff/plan total (a constant ~3300 across every device) — never the
    real device price.
    """
    txt = unicodedata.normalize("NFC", page.evaluate("() => document.body.innerText"))
    # Only look at the device section, BEFORE the all-in 'UKUPNO' total line.
    section = txt.split("UKUPNO")[0]
    pat = re.compile(
        r"([\d][\d\s.,]{1,9}?)\s*€\s*odmah\s*\+\s*"
        r"([\d][\d\s.,]{1,9}?)\s*€\s*/\s*24\s*mj",
        re.I,
    )
    m = pat.search(section)
    if not m:
        return _structured_fallback(page, "A1 Croatia")
    upfront = _parse_amount(m.group(1))
    monthly = _parse_amount(m.group(2))
    if upfront is None or monthly is None:
        return _structured_fallback(page, "A1 Croatia")
    total = round(upfront + monthly * 24, 2)
    return {"price": total, "original_price": None}


def _extract_a1_serbia(page):
    """A1 Serbia (RS): the PDP renders client-side. The no-contract device CASH
    price is the line 'Cena uređaja / Bez tarifnog paketa / 111.990 RSD' — the
    device price WITHOUT a tariff commitment. It is the RSD cash equivalent of
    the device, stored as ``subsidy_down_payment`` (consistent with Yettel RS).

    ANCHOR on 'Bez tarifnog paketa' (without a tariff package), NOT the bare
    'Cena uređaja' token: the latter also appears in the insurance boilerplate
    ('cena uređaja bez ugovorne obaveze'), which has no real price beside it.
    'Bez tarifnog paketa NNN.NNN RSD' appears exactly once per PDP and is the
    authoritative device price. Serbia uses a real DOT as the thousands
    separator ('111.990' == 111990), so ``dot_is_thousands`` is set.

    No loose fallback: if the anchored line is absent we return None and write
    NOTHING. The generic structured fallback would otherwise grab a tariff
    monthly ('2.999 RSD/mes') or a stale figure — the class of silent
    false-positive that polluted Vodafone RO. No data beats fabricated data.
    """
    txt = unicodedata.normalize("NFC", page.evaluate("() => document.body.innerText"))
    pat = re.compile(
        r"Bez\s+tarifnog\s+paketa[\s\u00a0]+([\d][\d\s.,]{2,})\s*RSD",
        re.I,
    )
    m = pat.search(txt)
    if not m:
        return None
    price = _parse_amount(m.group(1), dot_is_thousands=True)
    if price is None:
        return None
    return {"price": float(price), "original_price": None}


def _extract_orange_ro(page):
    """Orange RO (RO): operator webshop PDP. The device price is the
    'Preț telefon' (phone price) line, RON, e.g. 'Preț întreg / Preț telefon /
    3479 ,03 Lei'. Romanian format = DOT thousands separator + COMMA decimal, so
    ``dot_is_thousands`` is set (strips the dot, converts the comma to a decimal
    point). The page renders client-side, hence domcontentloaded + settle.

    'Preț telefon' is the device price and is stable across the contract /
    no-contract (isNoSubsidy) views, so we store it as ``subsidy_down_payment``.

    ANCHOR on 'Preț telefon' (not the bare 'Preț' / 'LEI' tokens): the old
    gigatron path — Orange RO had NO config and was mis-routed to the gigatron
    adapter — grabbed a stray '30.0 RON' tariff shard from the page. The bare
    'Preț' token also appears on plan/tariff blocks, so a loose prefix would
    re-introduce that false-positive. No loose fallback: if 'Preț telefon' is
    absent we return None and write NOTHING rather than fabricate a price.
    """
    txt = unicodedata.normalize("NFC", page.evaluate("() => document.body.innerText"))
    pat = re.compile(
        r"Pre[țt]\s*telefon[\s\u00a0]*([\d][\d\s.,]{2,})\s*Lei",
        re.I,
    )
    m = pat.search(txt)
    if not m:
        return None
    price = _parse_amount(m.group(1), dot_is_thousands=True)
    if price is None:
        return None
    return {"price": float(price), "original_price": None}


def _extract_plus(page):
    """Plus.pl (Poland operator, SPA). Device price is in schema.org JSON-LD:
    ``offers.price`` is the device financing TOTAL (downpayment + installments);
    ``priceComponent[]`` carries the ``Downpayment`` (upfront fee) and the
    ``Installment`` (monthly). We surface the financing total as the device price
    and the monthly installment separately, so the matrix shows both legs and
    nothing overwrites the total with monthly x 24.

    Returns {"price": financing_total, "contract_monthly": installment,
    "original_price": None} or None when the JSON-LD price block is absent.
    """
    import json as _json

    html = page.content()
    m = re.search(
        r'<script type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S | re.I
    )
    if not m:
        return None
    try:
        blocks = _json.loads(m.group(1))
    except Exception:  # noqa: BLE001
        return None
    if isinstance(blocks, list):
        # pick the first block that actually carries an offer
        blocks = next((b for b in blocks if isinstance(b, dict) and b.get("offers")), None)
    if not isinstance(blocks, dict):
        return None

    offers = blocks.get("offers")
    if isinstance(offers, list):
        offers = next((o for o in offers if isinstance(o, dict)), None)
    if not isinstance(offers, dict):
        return None

    total = offers.get("price")
    if total is None:
        return None
    try:
        total = float(total)
    except (TypeError, ValueError):
        return None

    monthly = None
    # priceComponent[] may sit directly on offers OR nested under
    # offers.priceSpecification (Plus.pl uses the latter).
    spec = offers.get("priceSpecification")
    comps = []
    if isinstance(spec, dict):
        comps = spec.get("priceComponent") or []
    if not isinstance(comps, list):
        comps = []
    if not comps:
        raw = offers.get("priceComponent")
        comps = raw if isinstance(raw, list) else []
    for c in comps:
        if not isinstance(c, dict):
            continue
        pct = c.get("priceComponentType") or ""
        if "Installment" in pct and c.get("price") is not None:
            try:
                monthly = float(c["price"])
            except (TypeError, ValueError):
                monthly = None
            break

    return {"price": total, "contract_monthly": monthly, "original_price": None}


_CUSTOM_EXTRACTORS = {
    "one_hu": _extract_one_hu,
    "telekom_ht": _extract_telekom_ht,
    "telekom_hu": _extract_telekom_hu,
    "yettel_hu": _extract_yettel_hu,
    "yettel_rs": _extract_yettel_rs,
    "a1_croatia": _extract_a1_croatia,
    "a1_serbia": _extract_a1_serbia,
    "orange_ro": _extract_orange_ro,
    "plus": _extract_plus,
}


# Per-process tally of why PDP fetches yielded no price, keyed by the classes
# below. Read by diagnostics/tests; never used for pricing decisions.
PDP_FAILURES: dict[str, int] = {"pool": 0, "render": 0, "parse": 0}


def _classify_pdp_result(result) -> str:
    """Why a PDP fetch produced no price: 'ok' | 'pool' | 'render' | 'parse'.

    The three failure modes need different remediation and used to be collapsed
    into one indistinguishable ``None``:

    * ``pool``   - the browser pool never ran the job (SPA disabled, breaker
      open, job timeout). Nothing was rendered, so the channel's coverage says
      nothing about its selectors.
    * ``render`` - the page raised while rendering (navigation blocked, bot
      wall, page crash). Retry / proxy territory.
    * ``parse``  - the page rendered fine but no price was extracted. This is
      the only class that means "the extraction rules rotted".
    """
    if result is None:
        return "pool"
    if isinstance(result, dict) and result.get("failure"):
        return str(result["failure"])
    return "ok"


def _drop_query_params(url: str, names) -> str:
    """Return ``url`` with the named query params removed.

    Some operator PDPs pin a payment tab through the query string (Telekom HU
    stores ``...&paymentType=onetime``). That pin hides the financing widget,
    so the "N × M Ft" installment leg of the dual-price spec never renders and
    the channel silently loses half the requested data. Dropping the param lets
    the default view render every price leg in a SINGLE fetch.
    """
    try:
        from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

        parts = urlsplit(url)
        if not parts.query:
            return url
        drop = {str(n).lower() for n in names}
        keep = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                if k.lower() not in drop]
        return urlunsplit((parts.scheme, parts.netloc, parts.path,
                           urlencode(keep), parts.fragment))
    except Exception:  # noqa: BLE001 - URL cosmetics must never break a crawl
        return url


def fetch_operator_pdp(channel, sku, timeout: int = 30):
    """Render one operator PDP and return the device (outright) price.

    Returns {"price", "currency", "in_stock": True} or None when the channel is
    unsupported, the browser is unavailable, or no plausible device price was
    found. Never raises.
    """
    cfg = OPERATOR_PDP_CONFIG.get(channel.name)
    if not cfg or not ENABLE_SPA_CRAWL:
        return None
    url = sku.product_url
    if not url:
        return None
    # Un-pin a hardcoded payment tab so every price leg renders (see
    # ``_drop_query_params``); without this Telekom HU never exposes the
    # installment split and the dual-price spec is only half satisfied.
    drop = cfg.get("drop_query")
    if drop:
        url = _drop_query_params(url, drop)

    mode = cfg.get("mode", "text")
    wait_until = cfg.get("wait_until", "networkidle")
    settle = cfg.get("settle", 4000)
    cookie_btn = cfg.get("cookie_btn")
    price_mode_btn = cfg.get("price_mode_btn")  # Yettel BG: "В брой" to switch lease→cash

    def job(browser):
        page = browser.new_page()
        try:
            # networkidle gives the SPA time to hydrate the price block; on
            # chatty SPAs that never go idle (Yettel RS) we degrade to
            # domcontentloaded and rely on the extra settle.
            try:
                page.goto(url, timeout=timeout * 1000, wait_until=wait_until)
            except Exception as nav_exc:  # noqa: BLE001
                log.warning("operator pdp nav wait failed %s: %s", url, nav_exc)
            if cookie_btn:
                try:
                    page.get_by_text(cookie_btn, exact=False).first.click(timeout=5000)
                    page.wait_for_timeout(2000)
                except Exception as ck_exc:  # noqa: BLE001
                    log.debug("operator pdp cookie dismiss skipped %s: %s", url, ck_exc)
            # Yettel BG: the PDP defaults to "На лизинг" (lease) mode which
            # shows the device MONTHLY installment, not the outright price.
            # Click "В брой" (cash) to switch to the lump-sum device price
            # before extracting. Must run AFTER cookie dismiss (the banner
            # blocks the mode-toggle button) and BEFORE settle.
            if price_mode_btn:
                try:
                    page.get_by_text(price_mode_btn, exact=False).first.click(timeout=5000)
                    page.wait_for_timeout(2000)
                except Exception as pm_exc:  # noqa: BLE001
                    log.debug("operator pdp price_mode_btn click skipped %s: %s", url, pm_exc)
            page.wait_for_timeout(settle)

            product_name = _extract_product_name(page)
            if mode == "attr":
                p = _extract_attr_price(page, cfg)
                extracted = ({"price": p, "original_price": None} if p is not None else None)
            elif mode == "custom":
                extracted = _CUSTOM_EXTRACTORS[cfg["custom"]](page)
            else:
                txt = page.evaluate("() => document.body.innerText")
                p = _extract_text_price(txt, cfg)
                extracted = ({"price": p, "original_price": None} if p is not None else None)
            if extracted is None:
                # Page rendered but no price parsed - selectors may have rotted.
                return {"failure": "parse"}
            extracted["in_stock"] = _operator_in_stock(page, url)
            # 赠品（耳机/手表/充电宝…）：运营商 PDP 上通常是红色促销条幅或徽章图。
            # 规则与市场渠道共用 app/crawling/gift.py。徽章图走 alt/src，文本走
            # 渲染后的 innerText —— 两者都要过同一套护栏（配送/分期/保修话术一律拒）。
            # no_gift: 站点没有任何可靠的实物赠品信号时关闭（Vodafone RO 的
            # PDP 带一个「付费配件推荐轮播」，图片 alt 全是商品名 —— "Buds" 命中
            # 赠品名词后整轮配件被当赠品落库，2026-09-03 TRACE 实证）。页面真实
            # 权益区（Extra beneficii）只有折扣/服务类（50% off Watch 6、保险/
            # 流媒体赠送），实物赠品探测诚实返回 None。
            try:
                if not extracted.get("gift") and not cfg.get("no_gift"):
                    # src / alt / title 必须作为**三条独立线索**传进去：拼成一条
                    # 会让赠品抽取器把整串当成文件名去解析（Telekom HU 曾因此把
                    # 整个 PDP 的图片列表当成一个赠品名落库）。
                    raw_imgs = page.evaluate(
                        "() => Array.from(document.images || []).slice(0, 400)"
                        ".flatMap(i => [i.currentSrc || i.src || '',"
                        " i.alt || '', i.title || ''])"
                    ) or []
                    imgs = [x for x in raw_imgs if x and x.strip()]
                    body_txt = page.evaluate("() => document.body.innerText") or ""
                    extracted["gift"] = extract_gift_from_text(body_txt, imgs)
            except Exception as gift_exc:  # noqa: BLE001 - 赠品是增强字段
                log.debug("operator pdp gift scan skipped %s: %s", url, gift_exc)
            # 设备分期方案（「N × M Ft」/「12 rat」/「/24mj」…）：一次性付清价之外的
            # 第二条腿。自定义抽取器若已给出权威分期（Telekom HU / Yettel HU 从价格
            # 块直读），这里不再覆盖——页面文本扫描只作兜底，覆盖全部其余运营商。
            try:
                if not (extracted.get("meta") or {}).get("installment"):
                    body_txt = page.evaluate("() => document.body.innerText") or ""
                    inst = extract_installment(
                        body_txt,
                        cfg.get("currency"),
                        device_total=extracted.get("price"),
                        dot_is_thousands=cfg.get("dot_is_thousands", False),
                    )
                    if inst:
                        meta0 = dict(extracted.get("meta") or {})
                        meta0["installment"] = inst
                        extracted["meta"] = meta0
            except Exception as inst_exc:  # noqa: BLE001 - 分期是增强字段，绝不能拖垮主流程
                log.debug("operator pdp installment scan skipped %s: %s", url, inst_exc)
            # MERGE (not overwrite): a custom extractor may return extra audit
            # keys in meta (e.g. Telekom HU's contract_device_price). Overwriting
            # would silently drop them. Standard keys always win.
            meta = dict(extracted.get("meta") or {})
            # A custom extractor may already carry an authoritative product_name
            # from its own data source (e.g. Yettel RS reads it from the BFF
            # JSON). Don't let the generic DOM scrape overwrite that with an
            # unreliable name — doing so would raise false product_mismatch
            # flags for channels where the BFF (not the rendered DOM) is the
            # source of truth. Standard operators that return no name still get
            # the DOM name stamped, so their behaviour is unchanged.
            if "product_name" not in meta:
                meta["product_name"] = product_name
            meta.update({
                "source": "operator_pdp",
                "url": url,
            })
            extracted["meta"] = meta
            return extracted
        except Exception as exc:  # noqa: BLE001
            # The render itself blew up (nav blocked, bot wall, page crash).
            log.warning("operator pdp render failed %s: %s", url, exc)
            return {"failure": "render"}
        finally:
            try:
                page.close()
            except Exception:  # noqa: BLE001
                pass

    # Budget: navigation + cookie click + settle, with headroom for cold start.
    result = run_in_browser(job, timeout=timeout * 2 + settle / 1000 + 30)

    kind = _classify_pdp_result(result)
    if kind != "ok":
        PDP_FAILURES[kind] = PDP_FAILURES.get(kind, 0) + 1
        log.warning(
            "operator pdp %s failure: no device price for %s (%s)",
            kind, channel.name, url,
        )
        return None
    price = result["price"]
    lo, hi = cfg["band"]
    if not (lo <= price <= hi):
        log.warning("operator pdp: %s %s outside band %s for %s",
                    price, cfg["currency"], cfg["band"], url)
        return None
    return {
        "price": price,
        "currency": cfg["currency"],
        "in_stock": result.get("in_stock", True),
        "original_price": result.get("original_price"),
        "contract_monthly": result.get("contract_monthly"),
        "gift": result.get("gift"),
        "meta": result.get("meta"),
    }
