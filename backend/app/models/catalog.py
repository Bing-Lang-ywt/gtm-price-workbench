import uuid

from sqlmodel import SQLModel, Field

from app.core.time import utcnow


class Model(SQLModel, table=True):
    __tablename__ = "models"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    marketing_code: str = Field(index=True)  # H600 | H600P | H600L | MagicV6 | ...
    display_name: str
    brand: str = Field(default="")
    price_band_anchor: float = Field(default=0.0)  # EUR anchor for segment bucketing
    is_target: bool = Field(default=False)  # DemoBrand 600 series & Magic V6
    official_url: str = Field(default="")  # 厂商官方产品详情页（看板顶部「官网」按钮用）
    created_at: str = Field(default_factory=lambda: utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: utcnow().isoformat())


class ModelAlias(SQLModel, table=True):
    __tablename__ = "model_alias"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    model_id: str = Field(foreign_key="models.id", index=True)
    alias: str = Field(index=True)


class ModelCompetitorMap(SQLModel, table=True):
    """Generic DemoBrand target model -> competitor mapping (one row per rival).

    A DemoBrand model may map to multiple competitors (e.g. Magic V6 -> Z Fold8
    Ultra + Z Fold8, both Samsung). `position` orders rivals and marks the
    primary rival (0) used for the competitiveness column.
    """

    __tablename__ = "model_competitor_map"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    model_id: str = Field(foreign_key="models.id", index=True)
    competitor_id: str = Field(foreign_key="models.id", index=True)
    position: int = Field(default=0)
    created_at: str = Field(default_factory=lambda: utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: utcnow().isoformat())


class Sku(SQLModel, table=True):
    __tablename__ = "skus"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    model_id: str = Field(foreign_key="models.id", index=True)
    channel_id: str = Field(foreign_key="channels.id", index=True)
    slug: str = Field(default="")
    product_url: str = Field(default="")
    in_stock: bool = Field(default=True)
    note: str = Field(default="")
    created_at: str = Field(default_factory=lambda: utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: utcnow().isoformat())
