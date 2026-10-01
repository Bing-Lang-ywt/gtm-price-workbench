import uuid

from sqlmodel import SQLModel, Field

from app.core.time import utcnow


class Channel(SQLModel, table=True):
    __tablename__ = "channels"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    country: str = Field(index=True)  # Serbia | Croatia | Hungary | Romania
    name: str = Field(index=True)
    type: str = Field(default="market")  # market | operator
    base_url: str = Field(default="")
    crawl_mode: str = Field(default="static")  # static | list
    health: str = Field(default="healthy")  # healthy | degraded | down
    enabled: bool = Field(default=True)
    # Operator contract term (months) used to derive device-financing TOTALS
    # from monthly installments. Per-channel override; defaults to 24 when
    # unset. Nullable + default so existing rows are unaffected (P2-12).
    contract_term_months: int | None = Field(default=24)
    created_at: str = Field(default_factory=lambda: utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: utcnow().isoformat())
