"""``add_price`` 的去重语义：什么算「一次变更」。

price 表被当成**变更日志**用（一次真实变更一行），所以去重必须既不能太松
（每次抓取都插一行 → 表退化成快照流水），也不能太紧（只比价格 → 分期/赠品
这类挂在 meta 上的语义变了却落不了新行，脏数据会一直赖在「最新行」上）。

2026-09-03 实测的血案：Telekom HT 把机身尺寸 ``161.15 x 75.0 x 8.4 mm``
读成「15 期 × 75.0」，抽取器修好后重抓，价格没变 → 去重命中旧行 → 假分期
``75.0×15`` 反复重抓也清不掉。meta 里只有 ``installment`` 需要参与比较：
``url`` / ``fetched_at`` / ``product_name`` 每次抓取都可能微变，不能比。
"""
import json

import pytest
from sqlmodel import Session as Sess, SQLModel, create_engine
from sqlalchemy.pool import StaticPool

from app.repositories import prices as prepo

CH = "ch-dedup"
SKU = "sku-dedup"


@pytest.fixture()
def sess():
    e = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(e)
    with Sess(e) as s:
        s.add_all(_seed())
        s.commit()
        yield s


def _seed():
    # add_price 只碰 prices 表，但 Sku/Channel 得先存在才能满足外键与
    # plausibility band 的查询前提。Model 不需要（与定价无关）。
    from app.models.catalog import Sku
    from app.models.channel import Channel

    return [
        Channel(id=CH, name="Telekom HT", country="HR", type="operator",
                crawl_mode="static", enabled=True, base_url="https://x"),
        Sku(id=SKU, model_id="m-dedup", channel_id=CH, product_url="https://x/1",
            in_stock=True),
    ]


def _add(sess, **kw):
    from app.models.price import Price
    kw.setdefault("in_stock", True)
    p = prepo.add_price(sess, SKU, CH, "subsidy_down_payment",
                        kw.pop("price", 100.0), kw.pop("currency", "EUR"),
                        kw.pop("amount_eur", 100.0), **kw)
    sess.commit()
    return p


def _count(sess):
    from sqlmodel import select
    from app.models.price import Price
    return len(sess.exec(select(Price)).all())


def test_identical_row_is_not_duplicated(sess):
    """价格 / 赠品 / 分期全没变 → 不插新行（每次抓取不刷表）。"""
    meta = json.dumps({"source": "operator_pdp", "url": "https://x/a?ts=1",
                       "installment": {"monthly": 75.0, "periods": 15,
                                       "total": 1125.0}})
    p1 = _add(sess, price=889.76, meta=meta, gift="Bez Punjača")
    # url 里的 query 变了（每次抓取都会变），但语义没变
    meta2 = meta.replace("ts=1", "ts=2")
    p2 = _add(sess, price=889.76, meta=meta2, gift="Bez Punjača")
    assert p1.id == p2.id
    assert _count(sess) == 1


def test_installment_change_writes_a_new_row(sess):
    """REGRESSION: 分期方案变了必须落新行，否则修好抽取器也清不掉假分期。"""
    bad = json.dumps({"source": "operator_pdp",
                      "installment": {"monthly": 75.0, "periods": 15,
                                      "total": 1125.0}})
    p1 = _add(sess, price=889.76, meta=bad, gift="Bez Punjača")
    # 抽取器修好后：不再给出分期（诚实 parse failure）
    p2 = _add(sess, price=889.76,
              meta=json.dumps({"source": "operator_pdp"}), gift="Bez Punjača")
    assert p1.id != p2.id
    assert _count(sess) == 2


def test_installment_periods_change_writes_a_new_row(sess):
    """期数从 15 改成官网真实的 22 期 → 也算变更。"""
    p1 = _add(sess, price=889.76,
              meta=json.dumps({"installment": {"monthly": 75.0, "periods": 15}}))
    p2 = _add(sess, price=889.76,
              meta=json.dumps({"installment": {"monthly": 40.4, "periods": 22}}))
    assert p1.id != p2.id


def test_gift_change_still_writes_a_new_row(sess):
    """赠品变了照旧落新行（这条原本就覆盖，守住不回退）。"""
    p1 = _add(sess, price=889.76, gift="Bez Punjača")
    p2 = _add(sess, price=889.76, gift="DemoBrand Earbuds")
    assert p1.id != p2.id


def test_price_change_writes_a_new_row(sess):
    p1 = _add(sess, price=889.76)
    p2 = _add(sess, price=879.76)
    assert p1.id != p2.id
