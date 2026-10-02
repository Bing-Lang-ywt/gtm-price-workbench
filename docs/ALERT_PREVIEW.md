# 规则离线预览

认证接口：`POST /api/v1/alert-rules/preview`，不读取已保存规则或历史价格。
提交 1–50 条 `rules` 和 1–100 条 `samples`，使用现有 Bearer 令牌。

```json
{
  "rules": [{"condition_type": "below", "threshold": 350, "model_id": "demo-target"}],
  "samples": [{"sku_id": "demo-sku", "model_id": "demo-target", "channel_id": "demo-shop",
               "price_type": "unlocked", "amount_eur": 300}]
}
```

返回 `data.matched_count` 及 `results`。每个结果按 `sample_index` 标识输入样例，
`evaluations` 按 `rule_index` 标识规则，提供 `matched` 和明确原因码。
索引均从 0 开始。完全相同的业务样例只评估一次，后续返回 `duplicate_of`
与 `duplicate_sample`，避免重复计数；不以输入顺序模拟历史变更。

规则条件：`below`/`above` 使用严格小于/大于 EUR 阈值；`delta_pct` 比较相对
`previous_amount_eur` 的涨跌幅绝对值，大于等于百分比阈值触发。
缺少前价或前价为零返回 `no_positive_previous_price`，不猜测涨跌幅。
`new_entry` 必须由样例显式给出 `is_new_entry: true`，不能同时提交前价；该规则阈值必须为 null。
金额与阈值要求有限非负数，拒绝布尔值和数字字符串；零元样例可用于预览补贴规则。

复合 `sku_id`/`model_id`/`channel_id` 绑定优先于旧 `scope_type`/`scope_id`。
支持旧 all、sku、model、channel 和无名称 segment；具名 segment 需要目录数据，离线预览拒绝处理。
支持 `price_type` 过滤与 `is_active` 开关。样例必须含 SKU、机型、渠道 ID 和有效价格类型。
标识字符串最多 200 字符。无效输入返回 422，未认证返回 401。

其他原因码包括 `inactive_rule`、`price_type_mismatch`、`scope_mismatch`、
`condition_matched`、`condition_not_met`。阈值运算使用 Decimal，避免极端有限金额计算溢出。
预览不申请数据库会话、不创建告警、不抓取、不发邮件或 Slack。
输入中的通知目标不会使用。正式引擎的历史查询、待处理告警去重和通知投递不在此预览范围内；
预览匹配不保证正式运行会新增或发送告警。原有规则 CRUD 和入库评估流程保持不变。
