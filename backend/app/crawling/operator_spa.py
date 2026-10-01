"""Playwright headless adapter for operator SPA webshops (P1).

Renders operator device-listing pages with headless Chromium and extracts device
prices, replacing the MVP `operator_list` no-op fallback for channels with a real
webshop. Off by default; activates only when ENABLE_SPA_CRAWL=1 and playwright +
Chromium are present. Otherwise `operator_list` degrades to the static fallback
and the MVP crawl keeps running.

To add a channel: append an entry to SPA_CONFIG keyed by Channel.name, with
device_url, currency, base_domain, nav_wait and a keywords map (marketing_code ->
name substrings). The shared render+price engine does the rest. Operator installment
totals are recorded as `unlocked` (comparable to GIGATRON's outright price) and the
monthly installment as `contract_monthly`.
"""
import logging
import os
import re

from app.crawling.browser_pool import (
    browser_available,
    run_in_browser,
    shutdown_browser,
)

log = logging.getLogger("crawl.spa")

ENABLE_SPA_CRAWL = os.getenv("ENABLE_SPA_CRAWL", "0") == "1"

# Per-channel SPA configuration. Key = Channel.name (exact match, as seeded).
SPA_CONFIG = {
    "Yettel RS": {
        "country": "Serbia",
        "device_url": (
            "https://www.yettel.rs/webshop/sr/Privatni-korisnici/Mobilni-telefoni"
        ),
        "base_domain": "https://www.yettel.rs",
        "currency": "RSD",
        "nav_wait": "a[href*='Mobilni-telefoni/']",
        "price_type_default": "unlocked",
        # Longest/most-specific keyword wins when a card name matches several.
        "keywords": {
            "H600P": ["demobrand 600 pro", "600 pro"],
            "H600L": ["demobrand 600 lite", "600 lite"],
            "H600": ["demobrand 600"],
            "MagicV6": ["magic v6"],
            "GalaxyS26U": ["galaxy s26 ultra"],
            "GalaxyS26": ["galaxy s26"],
            "GalaxyA57": ["galaxy a57"],
            "GalaxyZFold8": ["galaxy z fold8"],
            "RedmiNote15": ["redmi note 15"],
            "Xiaomi17T": ["17t"],
        },
    },
    # Configured best-effort; selectors reuse the generic engine but were not
    # empirically validated in this sandbox. Tune after a real run.
    "Telekom HU": {
        "country": "Hungary",
        "device_url": "https://www.telekom.hu/webshop/lakossagi/keszulekek/mobiltelefonok",
        "base_domain": "https://www.telekom.hu",
        "currency": "HUF",
        "nav_wait": "a[href*='mobil'], a[href*='telefon']",
        "price_type_default": "unlocked",
        "keywords": {
            "H600P": ["demobrand 600 pro"],
            "H600": ["demobrand 600"],
            "MagicV6": ["magic v6"],
            "GalaxyS26U": ["galaxy s26 ultra"],
            "GalaxyS26": ["galaxy s26"],
            "GalaxyA57": ["galaxy a57"],
            "RedmiNote15": ["redmi note 15"],
            "Xiaomi17T": ["17t"],
        },
    },
    # MTS (Serbia) — operator, sells on monthly installments only
    # ("Rata za uređaj"); no one-time device total is published, so we capture
    # the device monthly rate and let derive_operator_device_totals() build the
    # subsidy_down_payment (monthly x 24). Reuses the Serbian RSD extraction in
    # _extract_price.
    #
    # 2026-09-03 站点重构复盘（全渠道 items=0 的根因）：
    # 1. 旧列表 URL /Privatni/Pojedinacni-uredjaji 已 404，设备列表迁到
    #    /Privatni/Uredjaji/Tip-uredjaja/telefoni（商品 PDP 链接仍是老路径）。
    # 2. 新列表的卡片不再是 <li> 结构（closest('li') 会抓到包含整个网格的
    #    大容器，21 张卡全被分给一个机型），整卡是一个 <a>，改用
    #    card_scope="link" 直接取链接自身文本。
    # 3. nav_wait 不再锚 URL（隐藏导航里的产品链接会让 visible 等待超时），
    #    改锚卡片价格标签 "Mesečna rata"。
    # 4. PDP 上的 "Ukupno N RSD" 是 设备月付+套餐月费 的合并账单
    #    （实测 demobrand 600: 2375+2899=5274），不是设备总价 —— no_total 屏蔽
    #    total，只留 monthly 由 derive ×24 生成设备基准价。
    "MTS": {
        "country": "Serbia",
        "device_url": "https://mts.rs/Privatni/Uredjaji/Tip-uredjaja/telefoni",
        "base_domain": "https://www.mts.rs",
        "currency": "RSD",
        "nav_wait": "text=Mesečna rata",
        "card_scope": "link",
        "no_total": True,
        "scroll": True,
        "price_type_default": "subsidy_down_payment",
        "keywords": {
            "GalaxyA17": ["galaxy a17 5g", "galaxy a17"],
            "GalaxyA27": ["galaxy a27 5g", "galaxy a27", "samsung a27 5g", "samsung a27"],
            "GalaxyA37": ["galaxy a37 5g", "galaxy a37", "samsung a37 5g", "samsung a37"],
            "GalaxyA57": ["galaxy a57 5g", "galaxy a57", "samsung a57 5g", "samsung a57"],
            "GalaxyA17": ["galaxy a17 5g", "galaxy a17", "samsung a17 5g", "samsung a17"],
            "GalaxyS26": ["galaxy s26", "samsung s26"],
            "GalaxyS26U": ["galaxy s26 ultra", "samsung s26 ultra", "s26 ultra"],
            "GalaxyZFold8": ["galaxy z fold8", "samsung z fold8", "z fold8"],
            "GalaxyZFold8Ultra": ["galaxy z fold8 ultra", "samsung z fold8 ultra", "z fold8 ultra"],
            "H600": ["demobrand 600"],
            "H600L": ["demobrand 600 lite", "600 lite"],
            "H600P": ["demobrand 600 pro", "600 pro"],
            "H600Smart": ["demobrand 600 smart", "600 smart"],
            "Magic8Lite": ["magic8 lite"],
            "Magic8Pro": ["magic8 pro"],
            "MagicV6": ["magic v6"],
            "Redmi15C": ["redmi 15c"],
            "RedmiNote15": ["redmi note 15"],
            "Xiaomi15T": ["xiaomi 15t"],
            "Xiaomi17": ["xiaomi 17"],
            "Xiaomi17T": ["xiaomi 17t", "17t"],
        },
    },
}

_RENDER_CACHE: dict[str, list[dict]] = {}

# Browser lifecycle now lives in browser_pool (dedicated thread + recoverable
# breaker). These aliases keep the old import surface working.
is_spa_available = browser_available
close_spa_browser = shutdown_browser


def fetch_operator_spa(channel, sku, timeout: int = 30):
    """Crawl one operator SPA for a single SKU.

    Returns a list of (price_type, price, currency) tuples, or [] when the
    channel is unsupported, the browser is unavailable, or no price matched.
    """
    cfg = SPA_CONFIG.get(channel.name)
    if not cfg:
        return []

    code = (sku.slug or "").upper()
    # Config keys are mixed-case marketing codes; normalize for lookup.
    kw_map = {k.upper(): v for k, v in cfg["keywords"].items()}
    if code not in kw_map:
        return []

    def job(browser):
        cards = _render_cards(channel, cfg, browser, timeout)
        # Bind each card to the most specific matching model so that, e.g.,
        # "galaxy s26" does not steal the "galaxy s26 ultra" card (which maps
        # to GalaxyS26U). Then resolve this SKU to the card(s) for its code.
        assigned = _assign_cards(cards, kw_map)
        targets = assigned.get(code)
        if not targets:
            return None
        return _extract_price(targets[0]["href"], cfg, browser, timeout)

    # Listing render + PDP render happen back to back inside one browser job.
    result = run_in_browser(job, timeout=timeout * 4 + 30)
    if not result:
        return []

    total, monthly = result
    out = []
    # no_total: 有些运营商（MTS）PDP 上的 "Ukupno/合计" 是 设备月付+套餐
    # 月费 的合并账单，不是设备总价 —— 抓到也是假值。这种渠道只出 monthly，
    # 设备基准价由 derive_operator_device_totals() 以 monthly×24 生成。
    if total is not None and not cfg.get("no_total"):
        out.append((cfg["price_type_default"], total, cfg["currency"]))
    if monthly is not None:
        out.append(("contract_monthly", monthly, cfg["currency"]))
    return out


def _assign_cards(cards, kw_map):
    """Map each card to the model code whose keyword matches most specifically.

    A card can match several codes (e.g. "galaxy s26" matches both GalaxyS26
    and GalaxyS26U); it is bound to the code with the longest matched keyword,
    which is the most specific one. Returns {code: [card, ...]}.

    Space-insensitive: MTS renders model names WITH spaces ("Galaxy Z Fold 8
    Ultra") while the configured keywords are written without them ("galaxy z
    fold8 ultra"). We normalize BOTH the card name and each keyword by stripping
    whitespace before comparing, and rank by the normalized keyword length. This
    fixes the 8-SKU MTS mismatch in one place instead of maintaining a parallel
    set of space-variant keywords.
    """
    assigned: dict[str, list[dict]] = {}
    for card in cards:
        norm_name = re.sub(r"\s+", "", (card.get("name") or "").lower())
        best_code = None
        best_len = -1
        for code, kws in kw_map.items():
            for kw in kws:
                norm_kw = re.sub(r"\s+", "", kw.lower())
                if norm_kw in norm_name and len(norm_kw) > best_len:
                    best_len = len(norm_kw)
                    best_code = code
        if best_code:
            assigned.setdefault(best_code, []).append(card)
    return assigned


def _render_cards(channel, cfg, browser, timeout) -> list[dict]:
    """Render the listing page once per process and cache device cards.

    The render is retried once on failure. Critically, an empty/failed render
    is NOT cached, so a transient cold-start error cannot poison the cache and
    silently zero out every subsequent SKU in the same crawl run.
    """
    if channel.id in _RENDER_CACHE:
        return _RENDER_CACHE[channel.id]

    cards: list[dict] = []
    last_err: Exception | None = None
    # card_scope="link": 新版 MTS 列表的整卡是一个 <a>（无 <li> 包裹），
    # closest('li') 会抓到包含整个网格的大容器 —— 此时直接用链接自身文本
    # 当卡片名。默认仍是旧的 li 向上查找，其他渠道行为不变。
    use_link_text = cfg.get("card_scope") == "link"
    # scroll: 列表页懒加载时（MTS 新列表只渲染首屏 ~9 张卡），逐屏滚到底
    # 触发加载，能把覆盖从 9 卡提到全量。默认不滚，其他渠道行为不变。
    do_scroll = bool(cfg.get("scroll"))
    for attempt in range(2):
        page = browser.new_page()
        try:
            page.goto(cfg["device_url"], timeout=timeout * 1000,
                      wait_until="domcontentloaded")
            page.wait_for_timeout(3500)  # let the SPA hydrate
            if do_scroll:
                for _ in range(8):
                    page.mouse.wheel(0, 4000)
                    page.wait_for_timeout(900)
                page.mouse.wheel(0, -4000)
                page.wait_for_timeout(500)
            page.wait_for_selector(cfg["nav_wait"], timeout=timeout * 1000)
            raw = page.evaluate(
                """() => {
                    const out = [];
                    const as = Array.from(document.querySelectorAll("a[href]"));
                    for (const a of as) {
                        const h = a.getAttribute('href') || '';
                        if (!/Mobilni-telefoni\\/[^?]+\\//.test(h)
                            && !/mobiltelefonok/.test(h)
                            && !/telefon/.test(h)
                            && !/uredjaj/.test(h)) continue;
                        let card;
                        if (__CARD_SCOPE_LINK__) {
                            card = a;
                        } else {
                            card = a.closest('li');
                            if (!card) card = a.parentElement?.parentElement || a.parentElement || a;
                        }
                        const name = (card.innerText || '').replace(/\\s+/g, ' ').trim();
                        if (!name) continue;
                        out.push({ name, href: h });
                    }
                    return out;
                }""".replace("__CARD_SCOPE_LINK__",
                              "true" if use_link_text else "false")
            )
            seen = set()
            for r in raw:
                base = r["href"].split("?")[0]
                if base in seen:
                    continue
                seen.add(base)
                cards.append(r)
            break
        except Exception as exc:
            last_err = exc
            log.warning("SPA render attempt %d failed for %s: %s",
                        attempt + 1, channel.name, exc)
        finally:
            page.close()

    if not cards:
        if last_err:
            log.warning("SPA render gave no cards for %s: %s", channel.name, last_err)
        return []
    _RENDER_CACHE[channel.id] = cards
    return cards


def _parse_spa_prices(txt: str, cfg: dict):
    """Pure, browser-free parse of an operator SPA PDP's visible text into
    ``(total, monthly)`` device prices.

    Extracted from ``_extract_price`` so the extraction rules can be unit-tested
    against real captured page text. Keep this free of any Playwright/browser
    dependency.

    MTS (Serbia) publishes only a device monthly rate ("Rata za uređaj ...
    RSD/mes"); there is no one-time device total, so ``monthly`` is what we keep
    and ``derive_operator_device_totals()`` turns it into ``subsidy_down_payment``
    (monthly x 24). On MTS the "RSD/mes" string appears THREE times — the device
    installment, the trade-in (reklaža), and a flat plan fee (4.199) — so the
    anchor EXPLICITLY excludes "reciklažu" between the label and the number, and
    there is NO "smallest RSD/mes" fallback: that fallback was proven wrong on
    8/8 recrawled SKUs (it grabbed the trade-in or the plan fee) and produced
    plausible-looking but incorrect x24 totals. We return ``monthly=None`` rather
    than guess — a wrong price is worse than no price.
    """
    txt = re.sub(r"\s+", " ", txt)
    total = monthly = None
    # Yettel 36-month installment row: "36 1.326 RSD 47.764 RSD"
    m = re.search(r"36\s+([\d\.]+)\s*RSD\s+([\d\.]+)\s*RSD", txt)
    if m:
        monthly = _to_float(m.group(1))
        total = _to_float(m.group(2))
    else:
        m_dev = re.search(r"Rata za uređaj\s*\([^)]*\)\s*([\d\.]+)\s*RSD", txt)
        if m_dev:
            monthly = _to_float(m_dev.group(1))
        m_up = re.search(r"Ukupno.*?([\d\.]+)\s*RSD", txt)
        if m_up:
            total = _to_float(m_up.group(1))
    # Generic fallback: largest RSD amount near a total/cena keyword.
    if total is None:
        cand = re.findall(
            r"(?:ukupno|cena|total|ára|preis)[^\d]{0,30}([\d\.\s]+)\s*RSD",
            txt,
            re.I,
        )
        if cand:
            total = _to_float(max(cand, key=lambda x: _to_float(x) or 0))
    # MTS device monthly rate. The negative lookahead (?!reciklaž) forbids the
    # trade-in line ("uz reciklažu ...") from sitting between the label and the
    # captured number, so we always take the device installment, never reklaža.
    if monthly is None:
        m_dev = re.search(
            r"Rata za ure[đd]aj(?:(?!reciklaž).){0,80}?([\d\.]+)\s*RSD/mes",
            txt, re.S | re.I,
        )
        if m_dev:
            monthly = _to_float(m_dev.group(1))
    # Intentionally NO "smallest RSD/mes" fallback — see docstring.
    return total, monthly


def _extract_price(href: str, cfg: dict, browser, timeout):
    """Open a product detail page and return (total, monthly) device price."""
    url = href if href.startswith("http") else cfg["base_domain"] + href
    page = browser.new_page()
    total = monthly = None
    try:
        page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
        page.wait_for_timeout(3500)
        txt = page.evaluate("() => document.body.innerText")
        total, monthly = _parse_spa_prices(txt, cfg)
    except Exception as exc:
        log.warning("SPA price extract failed for %s: %s", url, exc)
    finally:
        page.close()
    return total, monthly


def _to_float(value):
    """Parse a localized price string to float.

    Handles Serbian / Balkan conventions where "." is the thousands separator
    and "," is the decimal (e.g. "47.764" -> 47764, "1.326,50" -> 1326.50).
    A lone "." followed by exactly three digits is treated as a thousands group,
    not a decimal, to avoid reading 47.764 RSD as ~0.41 EUR.
    """
    if value is None:
        return None
    s = str(value).strip().replace(" ", "").replace("\xa0", "")
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") \
            else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", "") if re.fullmatch(r"\d{1,3}(,\d{3})+", s) \
            else s.replace(",", ".")
    elif "." in s:
        if re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
            s = s.replace(".", "")
        # otherwise keep as a genuine decimal (e.g. "0.41")
    try:
        return float(s)
    except ValueError:
        m = re.search(r"[\d\.]+", s)
        return float(m.group()) if m else None
