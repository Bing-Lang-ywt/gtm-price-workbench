import uuid

from sqlmodel import SQLModel, Field

from app.core.time import utcnow


class CrawlRun(SQLModel, table=True):
    __tablename__ = "crawl_runs"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    channel_id: str = Field(foreign_key="channels.id", index=True)
    started_at: str = Field(default_factory=lambda: utcnow().isoformat())
    finished_at: str = Field(default="")
    status: str = Field(default="running")  # running | success | partial | failed
    items: int = Field(default=0)
    error: str = Field(default="")  # 截断摘要（向后兼容，旧字段保留）
    # LOW: 完整失败明细 JSON（每条失败 = [sku_id, error_type]），不再截断到 8 条。
    # 旧代码只把前 8 条拼进 `error`，排查"某渠道为何大面积失败"时信息不足。
    error_detail: str = Field(default="")


class Alert(SQLModel, table=True):
    __tablename__ = "alerts"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    sku_id: str = Field(foreign_key="skus.id", index=True)
    type: str = Field(index=True)  # price_drop | price_up | new_sku | stock_out
    before: float = Field(default=0.0)
    after: float = Field(default=0.0)
    currency: str = Field(default="")
    threshold_pct: float = Field(default=0.0)
    triggered_at: str = Field(default_factory=lambda: utcnow().isoformat())
    status: str = Field(default="pending")  # pending | sent | failed
    notify_target: str = Field(default="")
    message: str = Field(default="")


class AlertRule(SQLModel, table=True):
    __tablename__ = "alert_rules"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)

    # 复合作用域（精确绑定）：渠道 / 机型 / SKU 三维度，任一字段为空代表「该维度不限」。
    # 三者均设置 = 锁定到具体渠道的具体产品具体 SKU；只设置部分 = 该维度下全部匹配。
    channel_id: str | None = Field(default=None, index=True)
    model_id: str | None = Field(default=None, index=True)
    sku_id: str | None = Field(default=None, index=True)

    # 兼容旧规则：单一作用域（all/model/sku/channel/segment）+ 原始 scope_id。
    # 新规则统一走复合维度，scope_type 默认 "all" 仅作占位。
    scope_type: str = Field(default="all", index=True)
    scope_id: str = Field(default="")
    price_type: str | None = Field(default=None)  # unlocked | contract_monthly | subsidy_down_payment | null
    condition_type: str  # below | above | delta_pct | new_entry
    threshold: float | None = Field(default=None)
    notify_target: str | None = Field(default=None)
    is_active: bool = Field(default=True)
    created_at: str = Field(default_factory=lambda: utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: utcnow().isoformat())


class Feedback(SQLModel, table=True):
    __tablename__ = "feedbacks"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    author: str = Field(default="")  # 留言人（取自登录用户 sub/email，匿名时留空）
    email: str = Field(default="")
    content: str = Field(default="")
    created_at: str = Field(default_factory=lambda: utcnow().isoformat())
    status: str = Field(default="open")  # open | resolved
