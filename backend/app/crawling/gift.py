"""赠品（bundled gift）探测 —— 全渠道共用。

背景
----
赠品跟「优惠」是两件独立的事：划线价→优惠 是价格层面的减免，赠品是随货附送的
实物（耳机、手表、充电宝、投影仪…）。所以它在 DB 里是独立列 ``prices.gift``，
前端单独一行展示。

改造前的状态：只有 ``gigatron`` 适配器有赠品探测，其余 20+ 渠道（Alza / Datart /
Euro / Gigantti / Altex 五个 stealth 渠道 + 全部运营商）一律抓不到；而 gigatron
自己的探测还常年产出两类垃圾：
  * "Na żółtym tle znajduje się zdjęcie przedstawiają…" —— 波兰站 banner 图的
    alt 描述文案，被当成赠品名；
  * "Dwie raty gratis i 30 rat 0% *RRSO 0%" —— 免息分期话术，不是赠品。

设计
----
一个核心函数 ``extract_gift(text, images)``，两种入口共用：
  * ``extract_gift_from_text``  —— 浏览器渲染后的 innerText（运营商 PDP 走这条）
  * ``extract_gift_from_soup``  —— httpx 抓下来的 HTML（gigatron / stealth 渠道）

判定顺序：图片徽章（最可靠，文件名/alt 直接就是赠品型号）→ 文本公告。
两路都要过同一套护栏：
  1. 必须命中「实物名词」（耳机/手表/音箱/充电宝…），纯促销词不算；
  2. 命中位置周围不得出现 配送/分期/保修/保险/折扣 类词——那是话术不是赠品；
  3. 标签必须短（≤5 词 / ≤48 字符）且不能以介词/冠词开头（banner 描述的特征）。
宁可返回 None（页面上就是没有赠品），也不要编一个看起来像的值。
"""
from __future__ import annotations

import re
import unicodedata

# ------------------------------------------------------------------ 词表

# 赠品公告词：明确表示「这个东西是白送的」。
# 注意：单独的 "free" / "gratis" / "ingyenes" / "zdarma" 不进表——它们绝大多数时候
# 修饰的是 免运费 / 免息分期 / 免费保修，必须由实物名词 + 护栏共同确认才采信。
GIFT_MARKER = re.compile(
    r"(free\s+gift|gift\b|gift\s*idea|bundled\s+with|comes\s+with\s+free|"
    r"complimentary|bonus\s+gift|regalo|geschenk|gratisgeschenk|"
    r"aj[aá]nd[eé]k|aj[aá]nd[eé]kba|ingyenesen\s+j[aá]r|r[aá]ad[aá]s|"
    r"poklon(?:u|a|om|ski)?\b|na\s+poklon|darujemo|besplatan\s+poklon|"
    r"cadou|cadouri|gratis\b|"
    r"prezent(?:em|u)?\b|w\s+prezencie|gratis|dodatek\s+gratis|"
    r"d[aá]rek(?:em|u)?\b|zdarma\s+k\s+produktu|"
    r"lahja(?:na|ksi)?\b|kaupan\s+p[aä][aä]lle|"
    r"подарък|подарява|бонус|подаръчн|"
    # 注意不要收 "общ"：保加利亚站每页页脚都有 "Общи условия"（通用条款）和
    # "обобщени данни"（汇总数据），它一匹配就把整段页脚当赠品窗口，
    # Yettel BG 就是这样落库出 "DemoBrand Watch 6 Цвят" 的（2026-09-03 实测）。
    r"δώρο)",
    re.I,
)

# 实物名词：赠品可能是的东西。跨 8 种语言（我们覆盖的市场）。
GIFT_NOUN = re.compile(
    r"("
    # 音频 / 穿戴
    r"earbuds?|earpods?|airpods?|\bbuds\b|headset|headphones?|"
    r"smartwatch|smart\s+watch|\bwatch\b(?!\s*list)|watch\s+gt|band\s+\d|"
    r"fülhallgató|fejhallgató|okosóra|okos\s+óra|"
    r"c[aă][sș]ti|c[ăa][sș][tț]i|ceas|br[ațț]ar[aă]|"
    r"slu[sš]al\w*|pametni\s+sat|sat\b|zvu[čc]nik|"
    r"s[uł][uł]chawk\w*|zegarek|g[łl]o[sś]nik|opaska|"
    r"kuulokkeet|kello|kaiutin|"
    r"sluch[aá]tk\w*|hodinky|reproduktor|n[aá]ramkov|"
    r"слушалк\w*|наушник\w*|часовник|гарнитур\w*|"
    # 配件 / 充电
    r"power\s?bank|powerbank|charger|charging\s+case|"
    r"töltő|power\s+bank|hordozható\s+töltő|"
    r"[îi]nc[aă]rc[aă]tor|hus[aă]|cablu|"
    r"punja[čc]|futrola|kabl\w*|maska|"
    r"[łl]adowark\w*|etui|kabel|"
    r"laturi|kotelo|kaapeli|"
    r"nab[ií]je[čc]k\w*|pouzdro|"
    r"зарядно|кал[ъь]ф|кабел|"
    # 家电 / 大件（这些站点真的送过）
    r"air\s?fryer|airfryer|fritez[aă]|projector|proiector|projektor|"
    r"robot\s?vacuum|robotporszívó|aspirator|"
    r"speaker|hangszóró|diff?user|"
    r"tablet(?!\s*case)|tablet[aă]|tabletti|"
    r"television|tv\b|telev[ií]z[ií]|televizor|"
    r"kettle|v\u00edv\u00e1rn\u00e1|canifer|"
    r"microwave|cuptor|mikrohull[aá]|"
    r"blender|mixer|turbo\s+hand|"
    # 包 / 其他
    r"backpack|rucksack|t[aá]ska|torb[ăa]|bag\b|rygs[æa]k|batoh|"
    r"mouse|keyboard|eg[eé]r|billenty[uű]zet|"
    r"scooter|trotinet[aă]|roller|"
    r"box\s+set|box\s?suit"
    r")",
    re.I,
)

# 反向护栏：命中这些词 → 这段讲的是配送/分期/保修/保险/折扣，不是赠品。
NEG_CONTEXT = re.compile(
    r"("
    r"доставк|куриер|courier|shipping|shipment|freight|пратк|isporuk|"
    r"free\s+delivery|doru[eč]en|sz[aá]ll[ií]t|livrare|expedi|运输|"
    r"\brata|raty|\brate\b|\brat[aă]|taksit|installment\w*|instalment\w*|"
    r"reszlet|r[eé]szletfizet|RRSO|RRSO\s*0|0\s*%|oprocent|prowizj|"
    r"l[eá]zing|leasing|hitel|kredit|"
    r"garanc|garanț|gwaranc|z[aá]ruka|garancija|j[oó]t[aá]ll|"
    r"za[sš]tit|osiguranj|assigur|ubezpiecz|insurance|poji[sš]t|biztos[ií]t|"
    r"popust|reducere|rabatt|kedvezm[eé]ny|zni[zż]k|slev|\bale\b|\bsale\b|"
    r"promoți|akci[oó]s|campaign|kampanie|akce|"
    # 「不含 X」：欧盟统一充电口法规落地后，几乎每个运营商 PDP 都挂一个充电器
    # 图标，配文「包装盒内不含充电器」。各国写法不同，而实物名词（charger /
    # încărcător / punjač / ładowarka）就贴在负向词旁边，不拦就会被当成赠品。
    # 2026-09-03 实测三个渠道整渠道同一个值，全是这一个来源：
    #   Play(PL) 19 行 "Zestaw Bez Ładowarki"（alt，图是 charger_excluded.svg）
    #   Telekom HT 18 行 "Bez Punjača"（图是 icons/charger-without.svg）
    #   Orange RO  17 行 "Charger"（图是 charger.svg，正文 "nu are inclus"）
    r"excluded|not\s+included|nincs\s+benne|nem\s+tartalmaz|nie\s+zawiera|"
    r"nu\s+este\s+inclus|nu\s+are\s+inclus|brak\s+w\s+zestawie|"
    r"without|\bbez\b|\bbrez\b|\bбез\b|f[aă]r[aă]\b|\bilman\b|"
    r"n[eé]lk[uü]l|zonder|\bsans\b|ohne|f[aä]r[ae]r"
    r")",
    re.I,
)

# 图片型赠品文件名里出现的噪音（尺寸/颜色/占位符）
#
# ``cross_sell`` / ``upsell`` 是站内 CMS 的**版位名**（Plus 的
# ``watch_cross_sell.webp`` 挂在「看了又看」位上），不是赠品徽章 —— 卡片上写着
# 什么无从判断，宁可整条跳过也不要把交叉销售位当成赠品落库。
IMG_NOISE = re.compile(
    r"(banner|slider|hero|placeholder|logo|icon|spinner|loading|blank|"
    r"\d{2,4}x\d{2,4}|@\dx|sprite|favicon|pixel|"
    r"cross[_\-]?sell|up[_\-]?sell)",
    re.I,
)
COLOR = re.compile(
    r"\b(white|black|blue|red|green|gold|silver|grey|gray|pink|purple|"
    r"b[ií]lá|[cč]ern|modr|[cč]erven|zelen|zlat|st[řr][ií]br|"
    r"feh[eé]r|fekete|k[eé]k|piros|z[oö]ld|arany|ez[uü]st|"
    r"alb|negru|albastru|ro[sș]u|verde|auriu|argintiu|"
    r"feher|narancs|lila|bk|blk|wh|blk)\b",
    re.I,
)
# 图片文件名里被拆出来的扩展名 token（"demobrand-earbuds-a-pro png"）—— 不是型号
EXT_TOKEN = {"png", "jpg", "jpeg", "webp", "gif", "avif", "svg"}

# 标签开头的介词/冠词/动词 —— banner 描述文案的典型开头，必须剔除
LEAD_STOP = re.compile(
    r"^(na|na\s+|w\s+|z\s+|do\s+|za\s+|a\s+|the\s+|a\s+free|in\s+|pe\s+|"
    r"cu\s+|s\s+|i\s+|e\s+|o\s+|u\s+|v\s+|k\s+|mit\s+|bei\s+|"
    r"zdj[eę]cie|zdj[eę]ciu|obraz|fotografia|tło|tle|"
    r"this|that|our|your|get|buy|shop"  # 营销口号
    r")\b",
    re.I,
)

# 品牌词：紧挨实物名词左边出现时一定要带上（"DemoBrand Earbuds X" 少了品牌就不完整）
BRAND = re.compile(
    r"^(DemoBrand|SAMSUNG|SAMS|XIAOMI|REDMI|POCO|APPLE|HUAWEI|SONY|JBL|ANKER|"
    r"BASEUS|CHOICE|REALME|MOTOROLA|NOKIA|PHILIPS|LOGITECH|TP-?LINK|SANDISK|"
    r"GARMIN|AMAZFIT|ORAL-?B|ROWENTA|TEFAL|DE'LONGHI)$",
    re.I,
)
# 实物名词右侧会出现的虚词（冠词/介词），不能进标签
TAIL_STOP = {
    "a", "az", "egy", "és", "s", "de", "la", "le", "les", "du", "de",
    "și", "si", "i", "in", "w", "z", "do", "na", "za", "cu", "pe", "cu",
    "the", "of", "for", "and", "with", "to", "mellé", "hozzá", "gratis",
    # 被卖的那个「手机本体」——出现在赠品名词旁边时是噪音，不是赠品名的一部分
    "telefon", "telefonu", "telefonem", "telefona", "telefonie", "telefonhoz",
    "telefonului", "phone", "smartphone", "handset", "készülék", "készülékhez",
    "készülékkel", "uređaj", "uređaja", "uređaju", "aparat", "aparatul",
    "aparatului", "dispozitiv", "dispozitivul", "device", "terminal",
    "mobil", "mobile", "teléfono", "telefono", "handy", "smartphonu",
    # 「购买 / 下单」类词——活动条件说明，不是赠品名
    "achizitie", "achiziție", "achizitiei", "achiziției", "achizitionare",
    "cumparare", "cumpărare", "comandă", "comanda", "vásárlás", "vasarlas",
    "rendelés", "rendeles", "megrendelés", "koupě", "koupi", "kupno",
    "zakup", "kupnja", "kupovina", "kupovine", "narudžba", "narudzba",
    "porudzbina", "purchase", "purchases", "buy", "order", "bestellung",
    "kaufen", "compra",
    # 荷兰语活动话术（bij aankoop van deze telefoon）
    "bij", "aankoop", "van", "deze", "een", "met", "op", "aan", "voor",
    "naar", "je", "uw", "telefoon", "telefoons", "toestel", "mobiel",
}
# 营销修饰词：既不是型号的一部分，也说明右边不再是型号词 → 直接停
MOD_STOP = {"true", "stereo", "bluetooth"}

# 界面文案词（颜色选择器一类的标签）：撞上就停，不进标签，也不算「型号后缀」。
# 保加利亚站的产品名后面紧跟颜色选择器（"… DemoBrand Watch 6 / Цвят / Red"），
# 不在 MOD_STOP 里、单独成表是有原因的：下面的数字守卫要看「数字右边那个词是不是
# 像型号」，如果颜色词也算不像型号，"Watch 6" 的 "6" 就会被当成
# 参数表开头（"power bank 10000 mAh" 那类）整条丢掉，只剩 "DemoBrand Watch"。
UI_STOP = {
    "цвят", "цвет", "цвята",
    "боја", "boja", "barva", "farba", "szín", "szin", "culoare", "renk",
    "color", "colour", "colour:", "värvi", "farve",
}
# 库存 / 图库状态词：运营商与电商 PDP 的赠品图下方几乎必带一行
# 「Raktáron Galéria」「Nincs készleten」，截进标签就成了噪音。
# 出现即停 —— 这些词后面绝不会是型号后缀。
STATUS_STOP = {
    # 匈牙利语
    "nincs", "készleten", "keszleten", "raktáron", "rakhtaron", "raktár",
    "galéria", "galeria", "készlet", "előrendelhető", "rendelhető",
    "megrendelhető", "elérhető",
    # 波兰语
    "dostępny", "dostepny", "niedostępny", "brak", "dostępne", "wyprzedany",
    # 塞尔维亚 / 克罗地亚
    "nema", "dostupno", "nedostupno", "galerija", "lageru", "zalihi",
    # 罗马尼亚
    "indisponibil", "disponibil", "stoc", "galerie", "limitat",
    # 保加利亚
    "наличност", "наличен", "налични",
    # 捷克
    "skladem", "není", "nedostupné", "vyprodáno",
    # 芬兰（Power）
    "varastossa", "loppuunmyyty", "saatavilla", "ei",
    # 英语 / 通用
    "stock", "outofstock", "unavailable", "preorder", "pre-order",
    "soldout", "lead",
}


def _fold(s: str) -> str:
    """小写 + 去音标。图片文件名几乎都是 ASCII 化的（``raktaron`` 而不是
    ``raktáron``），所以状态词表必须按去音标后的形式比对才拦得住。"""
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


STATUS_STOP_FOLDED = {_fold(w) for w in STATUS_STOP}

# 素材命名里的填充词：运营商赠品图的文件名 / alt 常把活动名、版位名、
# 图片类型词、乃至语法变格一起拼进去。这些词本身不是赠品的一部分，
# **只跳过该词、保留左右的品牌与实物名词**，不要整条丢掉。
#   A1 Croatia ``demobrand-nacionalna_projektor``  —— "Nacionalna" 是活动名
#     （页面写的是 "Projektor na poklon"，赠品确实是投影仪）
#   Plus alt "Packshot zegarka Galaxy Watch Ultra" —— "Packshot" 是「产品图」，
#     "zegarka" 是 zegarek（手表）的波兰语属格，真赠品是 Galaxy Watch Ultra
FILLER_STOP_FOLDED = {
    _fold(w)
    for w in (
        # 活动 / 版位名
        "nacionalna", "nacionalni", "nacionalno", "nacionalne", "nacional",
        "kampanja", "kampany", "kampagne", "kampania", "kampan",
        "akcija", "akcije", "akcijsko", "promocija", "promocije",
        "bundleonly", "paket",
        # 图片类型词（"产品图" 这类，说明这是张图而不是赠品名）
        "packshot", "packshots", "pack", "shot", "shots",
        "zdjecie", "zdjęcie", "zdjecia", "zdjęcia", "foto", "fotografia",
        "obraz", "render", "wizualizacja",
        # 波兰语属格 / 工具格：纯语法变格，不是产品名的一部分
        "zegarka", "zegarkiem", "zegarki", "zegarkow", "zegarków",
        "sluchawek", "słuchawek", "sluchawkami", "słuchawkami",
        "ladowarki", "ładowarki", "ladowarka", "ładowarka",
    )
}
# 图片扩展名：alt/title 直接就是文件名时（"charger.svg"）也要能剥掉，
# 否则泛类判定比的是 "charger.svg" 而不是 "charger"，拦不住。
IMG_EXT_RE = re.compile(r"\.(png|jpe?g|webp|gif|avif|svg)$", re.I)
# 规格单位：出现即说明后面是参数表，不是赠品型号 → 停止向右收词
SPEC_STOP = {
    "mah", "wh", "kwh", "gb", "tb", "mb", "w", "kw", "hz", "mhz",
    "inch", "inč", "mm", "cm", "m", "kg", "g", "mp", "gbps",
}
# 会跟在实物名词右边的「赠品动作词」，同样不能进标签
TAIL_MARKER = re.compile(r"^(gratis|ingyenes|free|bonus|gift)$", re.I)

# 图片文件名里的纯规格单位：出现即断（"mah" / "hz" / "inch"…）。
# 刻意不含 w / gb —— "25w" "256gb" 常是产品名的一部分，断了反而丢信息。
UNIT_STOP_IMG = {
    "mah", "kwh", "hz", "mhz", "ghz", "inch", "inč", "mm", "cm", "m",
    "kg", "g", "mp", "mah)", "ml", "lumen", "lm",
}
# 光秃秃一个泛类名词 = 不是赠品。
#
# 欧盟统一充电口法规落地后，几乎每个运营商 PDP 都在显眼位置挂一个充电器图标，
# 配文「包装盒内不含充电器」。图标文件名就是 ``charger.svg``，清洗后只剩
# "Charger" —— 既没有品牌也没有型号，落到表上既无法识别成赠品，实际也确实
# 不是赠品（Orange RO 17 行全是它，正文写的是
# "Acest model nu are inclus în cutie încărcătorul."）。
#
# 只收充电器 / 线材这类「法规说明高发」的泛类词。绝不能扩到 earbuds / watch：
# Telekom HU 的赠品图 ``gift/earbuds-*.png`` 清洗后就是光秃秃的 "Earbuds"。
BARE_NOT_GIFT_FOLDED = {
    _fold(w)
    for w in (
        "charger", "chargers", "charging", "chargerpower",
        "incarcator", "încărcător", "incarcatoare",
        "ladowarka", "ladowarki", "ladowark", "ladowarka",
        "punjac", "punjač", "punjača", "punjačem", "punjacem",
        "nabijecka", "nabíječka",
        "laddare", "laturi",
        "kabel", "kabla", "cable", "cablu",
        "зарядно",
    )
}

MAX_LABEL_CHARS = 48
MAX_LABEL_WORDS = 5
# 公告词前后各取多少字符做上下文窗口
WIN_BEFORE, WIN_AFTER = 60, 90


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFC", s or "")
    return re.sub(r"\s+", " ", s)


# 允许出现在标签最左侧、但本身无意义的引导词（会被剥掉）
LEAD_MARKER = {
    "free", "gratis", "ingyenes", "ingyenesen", "gift", "gifts", "poklon",
    "poklonom", "cadou", "prezent", "dárek", "darek", "ajándék", "ajandek",
    "bonus", "lahja", "подарък", "geschenk", "regalo",
}


def _clean_label(s: str, max_words: int = MAX_LABEL_WORDS,
                 max_chars: int = MAX_LABEL_CHARS) -> str | None:
    """清洗并校验一条候选赠品文案；不合格返回 None。

    图片徽章走的是文件名（"samsung-ep-t2510nbegeu-fast-charger-25w-bk.png"），
    词数天然比公告文案多，所以调用方可以放宽上限。
    """
    s = _norm(s).strip(" \u00a0-–—+*·|,;:()[]\"'")
    if not s:
        return None
    # 剥掉左侧残留的公告词 / 连接符（"free gift: DemoBrand Earbuds X" → "DemoBrand Earbuds X"）
    toks = s.split()
    while toks:
        t = toks[0].strip(".,;:+-–—*()[]\"'")
        if not t or t.lower() in LEAD_MARKER or GIFT_MARKER.fullmatch(t) or t in {"+", "&", "-"}:
            toks.pop(0)
            continue
        break
    s = " ".join(toks)
    if not s:
        return None
    # banner 描述 / 长句：直接丢弃
    if len(s) > max_chars or len(s.split()) > max_words:
        return None
    if LEAD_STOP.match(s):
        return None
    # 纯数字 / 无字母
    if not re.search(r"[^\W\d_]", s, re.UNICODE):
        return None
    if NEG_CONTEXT.search(s):
        return None
    if not GIFT_NOUN.search(s):
        return None
    # 库存 / 图库状态词混进标签（"Earbuds Raktáron Galéria"）→ 就地截断，
    # 截断后若只剩空壳则整条丢弃。
    words = s.split()
    kept: list[str] = []
    for w in words:
        if _fold(w.strip(".,;:()[]")) in STATUS_STOP_FOLDED:
            break
        kept.append(w)
    if not kept:
        return None
    s = " ".join(kept)
    if not GIFT_NOUN.search(s):
        return None
    # 截断后（或本来）只剩一个泛类名词 → 是配件说明图标，不是赠品。
    if all(
        _fold(IMG_EXT_RE.sub("", w.strip(".,;:()[]"))) in BARE_NOT_GIFT_FOLDED
        for w in s.split()
    ):
        return None
    return s


# ------------------------------------------------------------------ 图片徽章


def _label_from_src(src: str) -> str | None:
    """'.../demobrand-earbuds-a-pro-white.png' -> 'DemoBrand Earbuds A Pro'."""
    if not src or IMG_NOISE.search(src):
        return None
    # 只取 URL 的最后一段（路径 + 文件名），丢掉 query / 域名
    fn = src.split("?")[0].rsplit("/", 1)[-1]
    fn = IMG_EXT_RE.sub("", fn)
    fn = re.sub(r"[-_+.]+", " ", fn).strip()
    if not fn:
        return None
    toks: list[str] = []
    for t in fn.split():
        if not t or COLOR.fullmatch(t) or t.lower() in EXT_TOKEN or t.isdigit():
            continue
        low = t.lower().strip("(),")
        # 规格单位一出现，后面就是参数表而不是型号（"ttec-recharger-mah-(2)…"
        # 里的 mAh 曾经一路拼进标签）。注意不能断在 "25w" / "256gb" —— 那两个
        # 常常是产品名的一部分，只有纯单位词才断。
        if low in UNIT_STOP_IMG or re.fullmatch(r"\d+(mah|wh|kwh|hz)", low):
            break
        # 库存 / 图库状态词同样要断：文件名是连字符拼的
        # （".../earbuds-raktaron-galeria.png"），不走 _clean_label 的按空格
        # 截断那条路，这里不断就会落库成 "Earbuds Raktaron"。
        if _fold(low) in STATUS_STOP_FOLDED:
            break
        # 活动名 / 版位名 / 图片类型词 / 语法变格：跳过即可，
        # 左右的品牌与实物名词要留下。
        if _fold(low) in FILLER_STOP_FOLDED:
            continue
        toks.append(t)
    if not toks:
        return None
    label = " ".join(t.capitalize() for t in toks)
    # 文件名比公告文案长（"samsung-ep-t2510nbegeu-fast-charger-25w"），但再长
    # 就说明这个 src 不是赠品徽章，而是整个页面的拼接串 → 必须拒掉。
    return _clean_label(label, 6, 56) or None


def _gift_from_images(images) -> str | None:
    """最可靠的一路：赠品徽章图的文件名 / alt 往往直接就是赠品型号。"""
    for img in images or []:
        if not img or IMG_NOISE.search(img):
            continue
        # 1) 文件名（含路径）——最具体
        label = _label_from_src(img)
        if label and GIFT_NOUN.search(label) and not NEG_CONTEXT.search(label):
            return label
        # 2) alt 文案本身
        if GIFT_NOUN.search(img) and not NEG_CONTEXT.search(img):
            cleaned = _clean_label(img)
            if cleaned:
                return cleaned
    return None


# ------------------------------------------------------------------ 文本公告


_PUNCT = ".,;:+-–—*()[]\"'!?"


def _collect_tail(after: str) -> list[str]:
    """从实物名词右侧收集至多 2 个「像型号后缀」的词。

    规则（踩过坑总结的）：
      * 虚词/本体词（telefon / la / gratis / bij aankoop…）跳过；
      * 撞上规格单位（mAh / GB / inch…）直接停 —— 后面是参数表不是型号；
      * 纯数字只有在前面已经有字母词时才收（"GS 3" 收，"10000 mAh" 不收）。
    """
    toks = [t.strip(_PUNCT) for t in after.split()]
    toks = [t for t in toks if t]
    tail: list[str] = []
    i, n = 0, len(toks)
    while i < n and len(tail) < 2:
        t = toks[i]
        low = t.lower()
        if low in TAIL_STOP or TAIL_MARKER.match(t):
            i += 1
            continue
        if low in SPEC_STOP or low in MOD_STOP or low in STATUS_STOP or low in UI_STOP:
            break
        if t.isdigit():
            # 数字打头（"… power bank 10000 mAh"）→ 后面是参数表，停；
            # 数字跟在型号词后面（"GS 3" / "Epic 2" / "2 Lite"）→ 是型号的一部分，收。
            nxt = toks[i + 1].lower() if i + 1 < n else ""
            if not tail and not (
                nxt
                and re.search(r"[^\W\d_]", nxt, re.UNICODE)
                and nxt not in TAIL_STOP
                and nxt not in SPEC_STOP
                and nxt not in MOD_STOP
                and nxt not in STATUS_STOP
            ):
                break
        tail.append(t)
        i += 1
    return tail


def _pick_brand(head_all: list[str]) -> str:
    """在实物名词左侧找品牌词。

    允许跳过**一个**「像型号」的词（含数字或 ≤4 字符），这样
    "Xiaomi S40c Robotporszívó" 才能带上 Xiaomi；但不允许一路往左扫，
    否则 "DemoBrand 600 Pro … Watch" 会把手机的品牌硬安到赠品头上。
    """
    skipped = 0
    for tok in reversed(head_all[-3:]):
        t = tok.strip(_PUNCT)
        if not t or GIFT_MARKER.fullmatch(t):
            continue
        if BRAND.match(t):
            return t
        if skipped == 0 and (re.search(r"\d", t) or len(t) <= 4):
            skipped += 1
            continue
        break
    return ""


def _build_candidate(window: str, noun) -> tuple[str, bool] | None:
    """以实物名词为核心拼一条候选标签。返回 (标签, 是否带品牌)。"""
    before = window[: noun.start()].strip()
    after = window[noun.end():].strip()
    head_all = before.split()
    # 去掉左侧的赠品公告词（"poklon Watch Epic 2" → 不要 "poklon"）
    while head_all and GIFT_MARKER.fullmatch(head_all[-1].strip(_PUNCT)):
        head_all.pop()
    name = window[noun.start(): noun.end()]
    tail = _collect_tail(after)
    brand = _pick_brand(head_all)
    has_brand = bool(brand)

    # 由宽到窄地试：优先带上品牌 + 型号后缀，宁可短一点也绝不把
    # "Kup telefon i odbierz …" 这类动词 / 本体词吞进来（宁缺勿假）。
    tries: list[str] = []
    if has_brand and len(tail) >= 2:
        tries.append(" ".join([brand, name, *tail[:2]]))
    if has_brand:
        tries.append(" ".join([brand, name, *tail[:1]]))
    if len(tail) >= 2:
        tries.append(" ".join([name, *tail[:2]]))
    tries.append(" ".join([name, *tail[:1]]))
    tries.append(name)
    for t in tries:
        cleaned = _clean_label(t)
        if cleaned:
            return cleaned, has_brand
    return None


def _gift_from_text(text: str) -> str | None:
    if not text:
        return None
    for m in GIFT_MARKER.finditer(text):
        lo = max(0, m.start() - WIN_BEFORE)
        hi = min(len(text), m.end() + WIN_AFTER)
        window = text[lo:hi]
        if NEG_CONTEXT.search(window):
            continue
        # 同一窗口里可能有多个实物名词（"Prezent smartwatch DemoBrand Watch GS 3"
        # 里 smartwatch 在前、Watch 在后）。带品牌的那条才完整，所以先扫一轮
        # 找带品牌的候选，找不到才退而求其次用第一条能用的。
        fallback: str | None = None
        for noun in GIFT_NOUN.finditer(window):
            cand = _build_candidate(window, noun)
            if not cand:
                continue
            label, has_brand = cand
            if has_brand:
                return label
            if fallback is None:
                fallback = label
        if fallback:
            return fallback
    return None


# ------------------------------------------------------------------ 对外入口


def extract_gift(text: str | None = None, images=None) -> str | None:
    """从渲染文本 + 图片线索里探测赠品，返回简短标签或 None。"""
    return _gift_from_images(images) or _gift_from_text(_norm(text or ""))


def extract_gift_from_soup(soup) -> str | None:
    """HTML 入口（httpx 抓下来的页面）。先扫图片徽章，再扫正文。"""
    images: list[str] = []
    try:
        for img in soup.find_all("img"):
            for attr in ("src", "data-src", "data-original", "alt", "title"):
                v = (img.get(attr) or "").strip()
                if v:
                    images.append(v)
    except Exception:  # noqa: BLE001 - 赠品是增强字段，绝不能拖垮抓取主流程
        images = []
    try:
        text = soup.get_text(" ")
    except Exception:  # noqa: BLE001
        text = ""
    return extract_gift(text, images)


def extract_gift_from_text(text: str | None, images=None) -> str | None:
    """纯文本入口（浏览器渲染后的 innerText / 已 normalize 的正文）。"""
    return extract_gift(text, images)
