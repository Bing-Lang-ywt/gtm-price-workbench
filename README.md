# GTM Price Workbench

价格监控与 GTM 分析工作台：整理渠道与产品目录，采集和校验价格，查看竞品矩阵与历史趋势，配置异动预警，并辅助参数对比和导出。

这是作者提供的已有项目源码的**脱敏公开导入**，不是从零开始的逐小时开发记录。原始开发历史未包含在输入压缩包中，不补造历史提交。公开整理、测试隔离及安全修复由 Codex 辅助完成。后续提交只记录实际完成的改进。

## 六个功能模块

| 模块 | 主要路径 | 现有能力 | 公开版边界 |
|---|---|---|---|
| 目录与渠道 | `backend/app/{models,repositories,services}/`、`frontend/app/config/` | 产品、SKU、渠道、竞品映射 | 配置为虚构样例，删除私有链接映射 |
| 采集与价格校验 | `backend/app/crawling/`、`backend/app/services/prices.py` | 价格提取、币种、分期、赠品、异常检测 | 真实站点适配器代码保留，默认不抓取，未作线上兼容承诺 |
| 竞品矩阵与趋势 | `frontend/app/{monitor,trend}/`、`frontend/components/dashboard/` | 价格矩阵、差价、日历、历史回放 | 演示价格不是实际市场报价 |
| 预警与新鲜度 | `backend/app/alerting/`、`backend/app/services/staleness.py` | 规则、价格异动、库存、覆盖率 | 不配置 Slack/SMTP；验证过程不发送通知 |
| 参数与导出 | `backend/app/routes/{params,export,energy_labels}.py`、`frontend/app/{compare,chips}/` | 参数对比、芯片排名、Excel、标签接口 | 私有 Excel、截图、品牌 PDF 不分发；缺失附件会返回空数据或 404 |
| 权限、部署与验证 | `backend/app/core/`、`deploy/`、`.github/workflows/` | 登录、分层 API、容器模板、测试 | 本地演示账号需自行设置；不是完成生产安全认证的部署 |

## 本地启动

需要 Python 3.12、Node.js 22。完整后端依赖见 `backend/requirements.lock.txt`。

```sh
cd backend
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements.lock.txt
export DEV_EMAIL=analyst@example.com
# 在本地设置自选密码；不要把密码提交到仓库。
export DEV_PASSWORD='choose-a-local-password'
export SECRET_KEY=$(python -c 'import secrets; print(secrets.token_hex(32))')
export ENABLE_SCHEDULER=0
python seed_demo.py
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

另开终端：

```sh
cd frontend
npm ci --ignore-scripts
npm run dev
```

打开 `http://localhost:3000`，使用自行设置的账号登录。API 文档：`http://127.0.0.1:8000/docs`。`seed_demo.py` 仅接受空数据库，生成 2 个虚构机型、2 个禁用渠道、4 个 SKU、28 条虚构历史价格，拒绝覆盖已有业务数据。

参数表只读取显式 `PARAMS_XLSX_PATH`，或可选本地 `backend/data/demo_parameters.xlsx`；不再搜索个人桌面。价格链接工作簿通过 `PRICE_LINKS_XLSX_PATH` 配置。调度器与浏览器抓取默认关闭；真实采集须由使用者自行配置合法可用渠道。

## 验证

```sh
cd backend
PYTHONPATH=. python -m pytest tests -q
cd ../frontend
npm run build
npm audit --audit-level=high
cd ..
python scripts/scan_public.py
```

测试使用临时数据库、离线样例与模拟浏览器，禁用调度与外部通知。结构扫描只是选定模式检查，不能证明没有任何秘密或软件缺陷。CI 的实际结果以 GitHub Actions 为准。

## 目录完整性诊断

登录后可调用 `GET /api/v1/models/integrity` 检查孤立 SKU、缺失关联及无效竞品映射。
接口只读，详情见 [使用说明](docs/CATALOG_INTEGRITY.md)。

## 价格输入预检

`POST /api/v1/prices/preflight` 在鉴权后检查金额、价格类型和币种，返回明确问题，
不写库或触发通知。详情见 [使用说明](docs/PRICE_PREFLIGHT.md)。

## 审查材料

- [功能与任务边界](docs/MODULES.md)
- [脱敏处理和限制](docs/SANITIZATION.md)
- [首次导入验证记录](docs/VALIDATION.md)
- [后续六个实际改进任务](docs/ROADMAP.md)
- [真实更新说明](CHANGELOG.md)

平台准入与评分标准尚未提供，本仓库不宣称已通过任何平台预审。仓库可见不等于获得开源许可，代码使用条件见 `LICENSE`。
