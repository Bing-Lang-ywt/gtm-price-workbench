import uuid

from sqlmodel import SQLModel, Field
from sqlalchemy import CheckConstraint

from app.core.time import utcnow


class Price(SQLModel, table=True):
    __tablename__ = "prices"

    # Storage-layer allow-list: never accept a non-standard price type
    # (the orphan `contract_device_total` once bypassed the service-layer
    # ALLOWED_PRICE_TYPES and broke the frontend matrix). Mirrors the
    # service-layer check so the DB itself rejects bad writes.
    __table_args__ = (
        CheckConstraint(
            "price_type IN ('unlocked','contract_monthly','subsidy_down_payment')",
            name="ck_prices_price_type",
        ),
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    sku_id: str = Field(foreign_key="skus.id", index=True)
    channel_id: str = Field(foreign_key="channels.id", index=True)
    price_type: str = Field(index=True)  # unlocked | contract_monthly | subsidy_down_payment
    price: float = Field(default=0.0)
    currency: str = Field(default="EUR")
    amount_eur: float = Field(default=0.0)  # normalised to EUR at ingest
    # 划线价（促销前原价 / strikethrough）。为 None 表示无促销或无法识别。
    # 实际到手价 = `price` 列；优惠力度 = original_price - price（前端派生展示）。
    original_price: float | None = Field(default=None, index=True)
    # 赠品文案（如「送 DemoBrand Earbuds X」）。物理赠品与「优惠」是两件独立的事：
    # 划线价→优惠 是价格层面的减免，赠品是随货实物，各自独立存储/展示。
    gift: str | None = Field(default=None)
    # 爬后一致性核对标记：actual_gt_original | missing_original_with_badge |
    # product_mismatch | out_of_band。多个以 ";" 分隔；None 表示未触发疑点。
    flag: str | None = Field(default=None, index=True)
    in_stock: bool = Field(default=True)
    captured_at: str = Field(default_factory=lambda: utcnow().isoformat(), index=True)
    # Comprehensive capture dimensions (JSON string): original_price (strikethrough
    # / pre-sale), sku_code, source, product_name (page self-reported model),
    # gift_snippet, etc. Kept as JSON for free-form provenance; the structured
    # fields above (original_price/gift/flag) are the queryable columns.
    meta: str | None = Field(default=None)


class FxRate(SQLModel, table=True):
    __tablename__ = "fx_rates"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    date: str = Field(index=True)  # YYYY-MM-DD
    currency: str = Field(index=True)
    rate_to_eur: float = Field(default=1.0)
