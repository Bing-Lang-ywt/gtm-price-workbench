from enum import Enum


class PriceType(str, Enum):
    unlocked = "unlocked"
    contract_monthly = "contract_monthly"
    subsidy_down_payment = "subsidy_down_payment"


class ChannelType(str, Enum):
    market = "market"
    operator = "operator"


class CrawlMode(str, Enum):
    static = "static"
    list = "list"


class RunStatus(str, Enum):
    running = "running"
    success = "success"
    partial = "partial"
    failed = "failed"


class AlertType(str, Enum):
    price_drop = "price_drop"
    price_up = "price_up"
    new_sku = "new_sku"
    stock_out = "stock_out"


class AlertStatus(str, Enum):
    pending = "pending"
    sent = "sent"
    failed = "failed"
