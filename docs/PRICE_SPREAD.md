# 最新价格差汇总

认证接口：`GET /api/v1/comparison/spread?price_type=unlocked&model_id=...`。
`model_id` 可省略；类型默认 `unlocked`，也允许 `contract_monthly`、
`subsidy_down_payment`。无效类型返回 422，未认证返回 401。

返回 `data.items`，每个机型包含 `channels`、`channel_count`、`min_eur`、
`max_eur` 和 `spread_eur`。同一 SKU 在所选类型中按实际采集时间选最新价格，
解析 ISO 时间偏移，未注明时区的旧时间按 UTC；相同时间以价格记录 ID 降序决胜。
本汇总不使用旧看板的人工价格优先规则，旧人工价不能盖过后来的采集价。

每渠道用该机型各 SKU 的最新有效 EUR 价格的最低值作为代表报价，并记录
`sku_samples`。至少两个渠道才计算价差；空目录/无价格金额为 null，单渠道价差为 null，
不把缺价当作零。最新值为非有限数或非正数时排除该 SKU，不回退到旧报价。
不能解析时间的行被忽略并累计在 `skipped_invalid_timestamps`。

此接口只读，不写库、转换汇率、抓取或发送通知。使用已存储的 `amount_eur`，
没有新鲜度上限，也不评判报价是否合理；零元补贴不纳入正价汇总。
不同 SKU 配置或渠道合约条件可能不同，价差不是完整商业可比性结论。
实现会扫描所选类型的历史记录，适合演示和小型目录，大型部署需进一步优化查询。
