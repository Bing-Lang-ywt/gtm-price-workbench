# 价格输入预检

认证接口：`POST /api/v1/prices/preflight`，使用现有 Bearer 令牌。

```json
{"price": 399.5, "price_type": "unlocked", "currency": "EUR"}
```

返回 `data.valid` 和 `data.issues`，每个问题包含 `field`、`code`、`message`。
业务无效输入也返回 HTTP 200，调用者必须检查 `valid`；缺少必填字段/错误的字段结构
返回 422，未认证返回 401。价格值不被回显，避免非有限数导致响应序列化失败。

- 金额必须是有限正数，拒绝布尔值、数字字符串、负数、零、NaN 和 Infinity。
- 类型允许 `unlocked`、`contract_monthly`、`subsidy_down_payment`。
- 币种允许 `EUR`、`RSD`、`HUF`、`RON`、`BGN`、`PLN`、`CZK`，区分大小写。
- 错误码：`not_numeric`、`not_finite`、`not_positive`、`unsupported_price_type`、`unsupported_currency`。

这是独立预览：不申请数据库会话、不写库、不查询汇率、不抓取、不发通知。
预检通过不代表 SKU/渠道存在、汇率可用、价格合理或正式写入必然成功。
现有人工录价流程保持不变；其合法零元补贴情形与本预览的正数要求不同，
不能用本预检代替正式入库流程的全部校验。JSON 请求应使用标准有限数值。
