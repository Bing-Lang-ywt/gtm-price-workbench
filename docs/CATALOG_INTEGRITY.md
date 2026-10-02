# 目录完整性诊断

认证接口：`GET /api/v1/models/integrity`，使用现有 Bearer 登录令牌。

响应 `data` 包含 `valid`、`counts`、`sku_findings` 和 `mapping_findings`。
SKU 问题原因：`missing_model`、`missing_channel`。竞品映射问题原因：
`missing_target_model`、`missing_competitor_model`、`self_competitor`。
同一行可以报告多个原因，但统计按问题行数计数，避免重复计数。

诊断只读取数据库，不修复关系、不抓取网页、不发送通知。空目录表示没有关系错误，
并不表示目录已具备业务价值。此接口检查关系存在性和自引用，不能判断竞品选择是否合理、
链接是否有效或业务资料是否完整。发现问题后由维护者在配置流程中确认与修复。
