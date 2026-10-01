import json
import logging
import time

from sqlmodel import select

from app.core.config import OUTLIER_MIN_SAMPLES

log = logging.getLogger("services.prices")

# LOW: 同一次进程内，同一 (model, price_type) 的跨渠道中位数只算一次。
# record_price 批量写入同一机型的多个 SKU 时会反复重算 median（O(N*M)），
# 而缓存首次 baseline 既省 CPU，又避免后写的 SKU 被自己刚写入的行污染
# （cross_channel_outlier 本就应与"其他价格"对比）。60s TTL 防止常驻进程过时。
_median_cache: dict = {}
_MEDIAN_TTL = 60.0


def _cached_model_median(session, model_id, price_type):
    key = (model_id, price_type)
    now = time.monotonic()
    hit = _median_cache.get(key)
    if hit and (now - hit[1]) < _MEDIAN_TTL:
        return hit[0]
    from app.services.price_audit import model_median_latest

    val = model_median_latest(session, model_id, price_type)
    _median_cache[key] = (val, now)
    return val


def clear_price_median_cache() -> None:
    """清空中位数缓存；在每次抓取开始前调用可避免跨抓取 stale baseline。"""
    _median_cache.clear()

from app.models.catalog import Sku
from app.models.price import Price
from app.repositories import prices as prepo, fx_rates as fxrepo
from app.repositories.base import page_meta
from app.services.common import load_maps
from app.services.link_routing import resolve_link

# 国家名（Channel.country 存的是名）→ ISO 代码，用于对齐前端 COUNTRIES 维度
COUNTRY_CODE_BY_NAME = {
    "Serbia": "RS",
    "Croatia": "HR",
    "Hungary": "HU",
    "Romania": "RO",
    "Bulgaria": "BG",
    "Poland": "PL",
    "Finland": "FI",
    "Czech Republic": "CZ",
}


def to_eur(price, currency, session, as_of=None):
    if currency == "EUR":
        return float(price)
    rate = fxrepo.get_latest_rate(session, currency, as_of)
    # A missing FX rate must fail loudly, not silently store the raw local
    # number as if it were EUR (that corrupts every downstream comparison).
    if rate is None:
        raise RuntimeError(
            f"no FX rate available for currency {currency!r}; cannot convert "
            f"price {price} to EUR. Add the rate to fx_rates first."
        )
    return float(price) * float(rate)


def _eur_of_original(p, session):
    """把 Price.original_price（本地货币）按汇率折算成 EUR，用于 EUR 模式划线价/折扣展示。
    缺汇率/异常时返回 None（让前端不展示划线价——比展示"省 25 万 €"这类荒谬数字更安全）。
    """
    if p.original_price is None or not p.currency:
        return None
    try:
        return round(float(to_eur(p.original_price, p.currency, session, p.captured_at)), 2)
    except Exception:
        return None


def record_price(
    session,
    sku_id,
    channel_id,
    price_type,
    price,
    currency,
    in_stock=True,
    captured_at=None,
    evaluate=True,
    meta=None,
    original_price=None,
    gift=None,
    flag=None,
    model_id=None,
):
    amount_eur = to_eur(price, currency, session, captured_at)
    # meta is a dict from the crawler (original_price, sku, source, ...); the
    # column is TEXT, so serialise it. Pass-through if already a string.
    meta_payload = meta
    if isinstance(meta, dict):
        import json as _json
        meta_payload = _json.dumps(meta, ensure_ascii=False)
    # 爬后一致性核对：除非调用方显式给了 flag（如人工标 product_mismatch），
    # 否则自动计算（actual_gt_original / missing_original_with_badge /
    # product_mismatch / out_of_band / cross_channel_outlier）。非致命，失败不影响落库。
    computed_flag = flag
    if computed_flag is None:
        try:
            from app.services.price_audit import compute_price_flag
            from app.models.catalog import Model

            # Prefer a caller-supplied model_id (cheaper, avoids a SKU reload);
            # otherwise resolve it from the SKU in this session.
            _model_id = model_id
            if _model_id is None:
                _sku = session.get(Sku, sku_id)
                _model_id = _sku.model_id if _sku else None
            _model_name = None
            _model_median = None
            if _model_id:
                _m = session.get(Model, _model_id)
                _model_name = _m.display_name if _m else None
                from app.repositories import prices as _prepo

                # Only feed the cross-channel median when the model has enough
                # peers at this price type, else the guard would flag cold-start
                # channels on a single lopsided comparison. (OUTLIER_MIN_SAMPLES)
                if _prepo.count_samples(session, _model_id, price_type) >= OUTLIER_MIN_SAMPLES:
                    _model_median = _cached_model_median(session, _model_id, price_type)
            computed_flag = compute_price_flag(
                price=price,
                original_price=original_price,
                gift=gift,
                meta=meta if isinstance(meta, dict) else None,
                currency=currency,
                amount_eur=amount_eur,
                model_display_name=_model_name,
                model_median_eur=_model_median,
                price_type=price_type,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("price audit failed (non-fatal): %s", exc)
    p = prepo.add_price(
        session,
        sku_id,
        channel_id,
        price_type,
        float(price),
        currency,
        amount_eur,
        in_stock,
        captured_at,
        meta=meta_payload,
        original_price=original_price,
        gift=gift,
        flag=computed_flag,
    )
    if evaluate:
        from app.alerting.evaluator import evaluate_price_change

        evaluate_price_change(
            session, sku_id, price_type, amount_eur, currency, exclude_id=p.id
        )

    # Rule-based reasonableness alerts (below / above / new_entry). Best-effort:
    # a failure here must never block the price write.
    try:
        from app.models.channel import Channel as _Channel
        from app.alerting.rule_engine import evaluate_rules_for_price

        _ch = session.get(_Channel, channel_id)
        _sku = session.get(Sku, sku_id)
        if _ch and _sku:
            evaluate_rules_for_price(
                session, _sku, _ch, price_type, amount_eur, currency
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("alert rule evaluation failed (non-fatal): %s", exc)

    return p


def create_manual_price(
    session,
    sku_id,
    channel_id,
    price_type,
    price,
    currency,
    in_stock=True,
):
    """人工在看板补录一条价格（meta.source='manual'），复用爬虫同款落库+归一化+告警评估。"""
    sku = session.get(Sku, sku_id)
    if not sku:
        raise ValueError(f"sku_id {sku_id!r} 不存在，无法补录价格")
    price = float(price)
    if price < 0:
        raise ValueError("价格不能为负")
    if currency not in ("EUR", "RSD", "HUF", "RON", "BGN", "PLN", "CZK"):
        raise ValueError(f"不支持的币种 {currency!r}")
    if price_type not in ("unlocked", "contract_monthly", "subsidy_down_payment"):
        raise ValueError(f"不支持的价格类型 {price_type!r}")
    from app.core.time import utcnow
    from sqlmodel import select

    # 同一 (sku, channel, price_type) 只保留一条人工价：写入前删除旧的 manual 行，
    # 避免每次「修改价格」都堆积一条新记录（否则 latest_snapshot 会保留多条，且历史越攒越长）。
    existing = session.exec(
        select(Price).where(
            Price.sku_id == sku_id,
            Price.channel_id == channel_id,
            Price.price_type == price_type,
        )
    ).all()
    for e in existing:
        is_manual = False
        if getattr(e, "meta", None):
            try:
                m = json.loads(e.meta) if isinstance(e.meta, str) else e.meta
                is_manual = (m or {}).get("source") == "manual"
            except Exception:
                is_manual = False
        if is_manual:
            session.delete(e)
    session.commit()

    meta = {
        "source": "manual",
        "entered_at": utcnow().isoformat(),
    }
    p = record_price(
        session,
        sku_id,
        channel_id,
        price_type,
        price,
        currency,
        in_stock=in_stock,
        meta=meta,
    )
    return {
        "id": p.id,
        "sku_id": p.sku_id,
        "channel_id": p.channel_id,
        "price_type": p.price_type,
        "price": p.price,
        "currency": p.currency,
        "amount_eur": p.amount_eur,
        "in_stock": p.in_stock,
        "captured_at": p.captured_at,
    }


def latest_snapshot_service(
    session, channel_id, model_id, country, price_type, page, limit,
    as_of_date=None, window_days=14,
):
    """价格快照。as_of_date=None → 取全局最新（看板主源）；
    as_of_date='YYYY-MM-DD' → 锚定到该日窗口内最新价（日历「看当日价格」用）。"""
    skus = prepo.get_skus_for_filter(
        session, country=country, channel_id=channel_id, model_id=model_id
    )
    sku_ids = [s.id for s in skus]
    if as_of_date:
        latest = prepo.latest_snapshot_as_of(session, sku_ids, as_of_date, window_days)
    else:
        latest = prepo.latest_snapshot(session, sku_ids)
    model_map, channel_map = load_maps(session)
    rows = []
    for (sku_id, pt), p in latest.items():
        if price_type and pt != price_type:
            continue
        sku = next((s for s in skus if s.id == sku_id), None)
        if not sku:
            continue
        m = model_map.get(sku.model_id, {})
        c = channel_map.get(sku.channel_id, {})
        country_name = c.get("country") or ""
        # 跳转链接：优先用爬虫自动发现的精确商品页(PDP)（sku.product_url，经四闸门校验，
        # 是最权威的验证链接），回退到硬编码路由字典 resolve_link（运营商等尚未自动发现的渠道）。
        product_url, listing_url = resolve_link(
            c.get("name", ""),
            m.get("marketing_code", ""),
            m.get("display_name", ""),
            m.get("brand", ""),
        )
        if sku.product_url:
            product_url = sku.product_url
        # 维度透传：把 prices.meta 里的校验/来源信息回传给前端，便于人工核对价格正确性
        # （original_price=划线价、product_name=页面自报机型、sku=渠道商品编码、source_url=抓取页）。
        verification = {}
        # 套餐月费（如 Yettel HU「Havonta fizetendő 26 609 Ft/hó」）：**不是**设备分期，
        # 全机型同值（0 Ft 的机器和 710 990 Ft 的 Z Fold8 Ultra 都是 26 609），
        # 绝不能进 contract_monthly 参与跨渠道比较；只作单元格注解展示。
        monthly_payable = None
        # 合约设备实付价（Telekom HU「Kedvezményes készülékár」/ Yettel HU「Teljes ár」）。
        # 主价格列统一存裸机标价 listaár 以保证跨渠道可比，补贴力度靠这个注解字段体现。
        contract_device_price = None
        if getattr(p, "meta", None):
            try:
                _m = json.loads(p.meta) if isinstance(p.meta, str) else p.meta
                verification = {
                    "product_name": _m.get("product_name"),
                    "original_price": _m.get("original_price"),
                    "sku": _m.get("sku"),
                    "source_url": _m.get("url"),
                    "in_stock_detail": _m.get("in_stock"),
                    "method": _m.get("method"),
                    "source": _m.get("source"),
                }
                monthly_payable = _m.get("monthly_payable")
                contract_device_price = _m.get("contract_device_price")
                # 设备分期明细（Telekom HU「N × M Ft」免息分期控件）：月付 × 期数 = 总价。
                # 仅作单元格注解，不参与跨渠道比较/排名；EUR 模式下用折算值渲染。
                installment = _m.get("installment")
            except Exception:
                verification = {}

        # 硬规则：本地货币字段要在 EUR 模式展示，必须配套 EUR 折算字段，
        # 否则 26 609 HUF 会被当成 26 609 € 渲染。
        def _eur(v):
            if v is None:
                return None
            try:
                return round(float(to_eur(v, p.currency, session, p.captured_at)), 2)
            except Exception:  # noqa: BLE001
                return None

        monthly_payable_eur = _eur(monthly_payable) if monthly_payable else None
        # 注意用 `is not None`：合约设备价 0（签约赠机）是有效值，不能被 falsy 判断吃掉。
        contract_device_price_eur = (
            _eur(contract_device_price) if contract_device_price is not None else None
        )
        # 设备分期明细：本地货币 + EUR 折算。total 直接用折后总价（与 amount_eur 同源），
        # 避免 monthly×periods 四舍五入后与权威总额差几欧分。
        installment_eur = None
        if isinstance(installment, dict) and installment.get("total") is not None:
            installment_eur = {
                "monthly": _eur(installment.get("monthly")),
                "periods": installment.get("periods"),
                "total": _eur(installment.get("total")),
            }
        rows.append(
            {
                "sku_id": sku_id,
                "model_id": m.get("id"),
                "model": m.get("display_name"),
                "model_marketing_code": m.get("marketing_code"),
                "brand": m.get("brand"),
                "is_target": m.get("is_target"),
                "channel_id": c.get("id"),
                "channel": c.get("name"),
                "channel_type": c.get("type"),
                "country": country_name,
                "country_code": COUNTRY_CODE_BY_NAME.get(country_name, country_name),
                "price_type": pt,
                "amount": p.price,
                "currency": p.currency,
                "amount_eur": p.amount_eur,
                "original_price": p.original_price,
                # EUR 模式划线价/折扣需要 EUR 折算值（原始 original_price 是本地货币，直接当 EUR
                # 渲染会让非欧元渠道出现"省 25 万 €"这类荒谬数字，如 Yettel HU 251 990 Ft 被显示为 251 990 €）
                "original_price_eur": _eur_of_original(p, session),
                "gift": p.gift,
                "flag": p.flag,
                # 套餐月费 + 合约设备实付价（本地货币 + EUR 折算）；
                # 仅作单元格注解展示，不参与比较/排名/最低价计算
                "monthly_payable": monthly_payable,
                "monthly_payable_eur": monthly_payable_eur,
                "contract_device_price": contract_device_price,
                "contract_device_price_eur": contract_device_price_eur,
                # 设备分期明细（月付 × 期数 = 总价）；仅注解展示，不参与比较/排名
                "installment": installment,
                "installment_eur": installment_eur,
                "delta_pct": None,
                "in_stock": p.in_stock,
                "captured_at": p.captured_at,
                # 精确商品页（可能为空）；列表页回退（可能为空）；渠道官网兜底
                "product_url": product_url,
                "listing_url": listing_url,
                "channel_base_url": c.get("base_url") or "",
                # 价格正确性校验维度（爬虫 meta 透传）：人工/看板可据此核对
                "verification": verification,
            }
        )
    rows.sort(
        key=lambda r: (
            r["country_code"],
            r["model"] or "",
            r["channel"] or "",
            r["price_type"],
        )
    )
    total = len(rows)
    start = (page - 1) * limit
    return {"items": rows[start : start + limit], "meta": page_meta(total, page, limit)}


def price_history_service(session, sku_id, channel_id, price_type, from_, to, page, limit):
    rows, total = prepo.price_history(
        session, sku_id, channel_id, price_type, from_, to, page, limit
    )
    return {"items": rows, "meta": page_meta(total, page, limit)}


def date_counts_service(session):
    """日历用：返回所有有价格记录的日期及其条数，升序。"""
    from sqlmodel import func, select

    stmt = (
        select(
            func.substr(Price.captured_at, 1, 10).label("d"),
            func.count().label("n"),
        )
        .group_by(func.substr(Price.captured_at, 1, 10))
        .order_by("d")
    )
    return [{"date": r[0], "count": int(r[1])} for r in session.exec(stmt).all()]


def promotions_service(session, from_, to, threshold, channel_id, model_id, country, max_drop=0.6):
    """促销起点检测：对每个 (sku, price_type) 按时间升序，以首条价格为基准，
    找到第一个显著低于基准 (= threshold) 的价格点 → 视为「开始做活动」的起点。
    单次降幅超过 max_drop（默认 60%）视为数据纠错/异常（价格审计已标），非真促销，跳过。
    返回事件列表（按发生时间倒序），每条含机型/渠道/国家/降幅/前后价/链接。"""
    skus = prepo.get_skus_for_filter(
        session, country=country, channel_id=channel_id, model_id=model_id
    )
    sku_ids = [s.id for s in skus]
    if not sku_ids:
        return []
    stmt = (
        select(Price)
        .where(Price.sku_id.in_(sku_ids))
        .order_by(Price.captured_at.asc())
    )
    if from_:
        from datetime import datetime

        try:
            stmt = stmt.where(Price.captured_at >= datetime.fromisoformat(from_))
        except ValueError:
            pass
    if to:
        from datetime import datetime

        try:
            stmt = stmt.where(Price.captured_at <= datetime.fromisoformat(to))
        except ValueError:
            pass
    groups: dict = {}
    for p in session.exec(stmt).all():
        groups.setdefault((p.sku_id, p.price_type), []).append(p)

    model_map, channel_map = load_maps(session)
    thr = float(threshold if threshold is not None else 0.03)
    events = []
    for (sku_id, pt), prices in groups.items():
        prices.sort(key=lambda x: x.captured_at)
        ref = prices[0]
        ref_eur = ref.amount_eur
        if ref_eur is None or ref_eur <= 0:
            continue
        started = None
        for p in prices[1:]:
            if p.amount_eur is None:
                continue
            drop = 1 - p.amount_eur / ref_eur
            if drop < thr:
                continue
            # 单次降幅过大 → 数据纠错/异常而非促销，跳过（避免把价格审计已标的
            # 离群/错价当成"打 9 折"误导用户）
            if drop > max_drop:
                break
            started = p
            break
        if not started:
            continue
        sku = next((s for s in skus if s.id == sku_id), None)
        if not sku:
            continue
        m = model_map.get(sku.model_id, {})
        c = channel_map.get(sku.channel_id, {})
        events.append(
            {
                "sku_id": sku_id,
                "model_id": m.get("id"),
                "model": m.get("display_name"),
                "model_marketing_code": m.get("marketing_code"),
                "brand": m.get("brand"),
                "channel": c.get("name"),
                "channel_id": c.get("id"),
                "country_code": COUNTRY_CODE_BY_NAME.get(
                    c.get("country", ""), c.get("country", "")
                ),
                "price_type": pt,
                "date": started.captured_at[:10],
                "captured_at": started.captured_at,
                "prev_amount_eur": round(ref_eur, 2),
                "new_amount_eur": round(started.amount_eur, 2),
                "drop_pct": round((1 - started.amount_eur / ref_eur) * 100, 1),
                "currency": started.currency,
                "amount": started.price,
                "product_url": sku.product_url or None,
            }
        )
    events.sort(key=lambda e: e["captured_at"], reverse=True)
    return events


def model_trend_service(session, model_id, price_type=None, country=None):
    """单品生命周期走势：取某机型下所有 sku 的价格历史，按渠道分组，
    返回每条渠道的时间序列（date + amount_eur），供前端折线图绘制。"""
    from sqlmodel import select as _select

    skus = prepo.get_skus_for_filter(
        session, country=country, model_id=model_id
    )
    if not skus:
        return {"model_id": model_id, "model": None, "channels": []}
    model_map, channel_map = load_maps(session)
    m = model_map.get(skus[0].model_id, {})
    sku_ids = [s.id for s in skus]
    stmt = _select(Price).where(Price.sku_id.in_(sku_ids))
    if price_type:
        stmt = stmt.where(Price.price_type == price_type)
    stmt = stmt.order_by(Price.captured_at.asc())
    # 以 channel_id 为键聚合时间序列，最后再解析渠道名/国家，避免反复反查
    by_ch: dict = {}
    for p in session.exec(stmt).all():
        sku = next((s for s in skus if s.id == p.sku_id), None)
        if not sku:
            continue
        by_ch.setdefault(sku.channel_id, []).append(
            {
                "date": p.captured_at[:10],
                "ts": p.captured_at,
                "amount_eur": p.amount_eur,
                "amount": p.price,
                "currency": p.currency,
            }
        )
    channels = []
    for ch_id, pts in by_ch.items():
        pts.sort(key=lambda x: x["ts"])
        c = channel_map.get(ch_id, {})
        country_name = c.get("country", "")
        channels.append(
            {
                "channel": c.get("name") or ch_id,
                "country_code": COUNTRY_CODE_BY_NAME.get(country_name, country_name),
                "points": pts,
            }
        )
    channels.sort(key=lambda x: x["channel"])
    return {
        "model_id": model_id,
        "model": m.get("display_name"),
        "model_marketing_code": m.get("marketing_code"),
        "channels": channels,
    }
