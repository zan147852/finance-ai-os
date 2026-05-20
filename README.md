# Finance AI OS — 财务BP AI工作台

基于 **Python + DuckDB + Hermes Agent + MCP** 构建的智能财务分析系统。自动完成数据采集、指标计算、经营分析、风险预警、报告生成，并通过多 Agent 协作输出管理层可读的分析报告。

## 系统架构

```
┌──────────────────────────────────────────────────────┐
│                    飞书 / 用户入口                      │
└────────────────────────┬─────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────┐
│              Hermes Orchestrator Agent                 │
│         接收请求 → 判断类型 → 调度子 Agent              │
└──────┬──────────────────┬──────────────────┬─────────┘
       │ delegate_task    │ delegate_task    │ delegate_task
┌──────▼──────┐  ┌───────▼───────┐  ┌──────▼──────┐
│   Analyst   │  │   Reporter    │  │  直接调用     │
│  数据分析    │  │  报告输出     │  │  MCP Tools   │
└──────┬──────┘  └───────┬───────┘  └──────┬──────┘
       │                 │                  │
┌──────▼─────────────────▼──────────────────▼─────────┐
│              MCP Server (finance-tools)               │
│   query_metric | check_finance_rule | log_event ...   │
└────────────────────────┬────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────┐
│              DuckDB (finance.db, 3.3GB)               │
│   3 核心业务表 + 12 明细账表 + 13 分析视图              │
└──────────────────────────────────────────────────────┘
```

## 项目结构

```
finance-ai-os/
├── agents/                     # Agent 人格定义
│   ├── orchestrator.SOUL.md    # 主编排 Agent
│   ├── analyst.SOUL.md         # 数据分析 Agent
│   └── reporter.SOUL.md        # 管理层汇报 Agent
├── scripts/                    # 核心脚本
│   ├── generate_formal_report.py   # 正式报告生成入口
│   ├── report_data_collector.py    # 数据采集层（DuckDB查询）
│   ├── report_deep_analyzer.py     # 深度归因分析引擎
│   ├── report_chart_renderer.py    # matplotlib → SVG 图表
│   ├── report_html_builder.py      # Jinja2 模板渲染
│   ├── report_pdf_exporter.py      # Playwright → PDF 导出
│   ├── import_all.py               # ETL 数据导入
│   ├── ledger_management_report.py # 明细账导入处理
│   ├── create_metrics.py           # 指标创建脚本
│   ├── run_daily.py                # 日常任务调度
│   └── ...
├── tools/                      # MCP 工具层
│   ├── finance_mcp_server.py       # MCP Server 主入口
│   ├── query_metric.py             # 指标查询引擎
│   ├── db.py                       # DuckDB连接复用与超时控制
│   ├── metric_maps.py              # 指标视图/规则映射
│   ├── rule_engine.py              # 规则引擎
│   ├── hermes_tools.py             # Hermes 工具集成
│   └── logger.py                   # 日志记录器
├── templates/                  # 报告模板
│   ├── formal_report.html.j2       # 正式报告 HTML 模板
│   └── report_style.css            # 报告样式（A4打印友好）
├── rules/
│   ├── finance_rules.json          # 经营预警规则
│   └── report_profiles.json        # 报告版本配置
├── outputs/                    # 报告输出目录
│   └── formal_report/              # 正式报告 HTML/PDF
├── data/                       # 原始数据文件
├── logs/                       # Agent 日志
├── snapshots/                  # 数据快照
├── finance.db                  # DuckDB 数据库（3.3GB）
├── config.yaml                 # Hermes 配置
├── .env                        # 环境变量
└── CLAUDE.md                   # Claude Code 项目指令
```

## 数据库设计

### 核心业务表（3张，4200万+行）

| 表名 | 说明 | 主要字段 |
|------|------|----------|
| `recycle_detail` | 回收明细 | 月份, 品类, 品牌, 履约方式, 终端, c1(回收金额), 回收单id |
| `sales_detail` | 销售明细 | 月份, 品类, 品牌, 财务业务线, 非买家服务费金额, 佣金金额, 实际到账, 换货补贴金额, 商品成本 |
| `inventory_detail` | 库存明细 | 月份, 品类, 品牌, 库龄, 库存价值 |

### 明细账表（12张）

| 表名 | 说明 |
|------|------|
| `ledger_raw_detail` | 明细账原始数据（72个会计科目、37个一级分类、51个二级分类） |
| `management_report_output` | 管理报表输出（70个P&L项目，Act/Bgt/Fsct） |
| `management_report_template` | 管理报表模板 |
| `management_report_rules` | 管理报表计算规则 |
| `ledger_sheets` | 明细账工作表 |
| `ledger_sheet_cells` | 明细账单元格数据 |
| `ledger_workbook_imports` | 明细账导入记录 |
| `ledger_subject_mapping` | 科目映射 |
| `ledger_cost_center_mapping` | 成本中心映射 |
| `ledger_settlement_allocation` | 结算分摊 |
| `ledger_formula_dependencies` | 公式依赖 |
| `ledger_sheet_merges` / `ledger_sheet_tables` | 辅助表 |

### 分析视图（13个）

| 视图 | 用途 |
|------|------|
| `v_monthly_overview` | 月度经营总览 |
| `v_monthly_by_category` | 按品类拆解 |
| `v_monthly_by_brand` | 按品牌拆解 |
| `v_monthly_by_sales_channel` | 按销售渠道拆解 |
| `v_monthly_by_fulfillment` | 按履约方式拆解 |
| `v_monthly_by_terminal` | 按终端拆解 |
| `v_monthly_by_business_line` | 按业务线拆解 |
| `v_monthly_by_financial_category` | 按财务分类拆解 |
| `v_inventory_aging` | 库龄分布 |
| `v_inventory_turnover` | 库存周转 |
| `v_cross_table_monthly` | 回收-销售转化 |
| `v_management_report_latest` | 最新管理报表 |
| `v_management_report_output_latest` | 最新P&L数据 |

### 财务口径定义

| 指标 | 计算公式 |
|------|----------|
| **销售GMV** | `非买家服务费金额 + 佣金金额 + 实际到账 + 换货补贴金额` |
| **销售收入** | `销售GMV ÷ 1.02` |
| **毛利** | `(销售收入 - 商品成本) ÷ 销售收入` |

> 所有核心业务表单位为**元**，报告输出统一转换为**千元**。明细账表本身单位为千元。

## MCP 工具

系统通过 MCP (Model Context Protocol) 对外暴露 7 个工具，供 Agent 调用：

| 工具 | 说明 | 关键参数 |
|------|------|----------|
| `query_metric` | 参数化指标查询 | `metric_id`: revenue/gross_margin/cost_ratio/full_month, `month` |
| `check_finance_rule` | 规则阈值校验 | `metric`, `value` |
| `log_agent_event` | Agent 事件日志 | `trace_id`, `agent`, `event_type`, `detail` |
| `get_monthly_overview` | 月度KPI总览 | `month` |
| `get_category_breakdown` | 品类维度数据 | `month` |
| `get_brand_trend` | 品牌维度趋势 | `month` |
| `generate_formal_report` | 生成正式HTML/PDF报告 | `month`, `format`(html/pdf/both), `profile` |

MCP Server 信息：`finance-tools v2.0.0`，协议 `2024-11-05`，stdio 传输。

### 运行稳定性

- DuckDB 连接由 `tools/db.py` 统一管理，按线程复用，并区分只读/写入连接。
- 每个连接最多执行200次查询后自动重建，避免长期持有连接导致状态污染。
- 查询默认超时10秒；超时或 DuckDB 异常后会中断查询并重建连接。
- `query_metric` 只允许白名单视图和白名单列，SQL 使用显式列清单，禁止 `SELECT *`。
- 默认返回100行，最大1000行；超长 JSON 结果会截断并附带 `_truncated=true`。
- `METRIC_VIEW_MAP` / `METRIC_RULE_MAP` 统一维护在 `tools/metric_maps.py`。
- 下一阶段预留方向：建设 `analyzers/`、`metric_catalog.yaml` 和 KPI 标准答案集，把经营归因进一步代码化。

## Agent 系统

### Orchestrator（主编排）

- 接收飞书消息，生成 `trace_id`（格式 `YYYYMMDD-序号`）
- 判断任务类型，通过 `delegate_task` 调度子 Agent
- 汇总结果，输出管理层可读内容
- 不直接分析数据
- 单次最终回复不超过800字，不直接转发子 Agent 原始长输出

### Analyst（数据分析）

- 专注：收入、毛利、成本、费用、ROI、同比环比、经营异常
- 通过 `query_metric` 获取数据，禁止自行编造
- 固定输出结论、归因、风险、建议，总长度不超过600字
- 禁止查询明细表和输出详细数据表格

### Reporter（管理层汇报）

- 输出渠道：飞书消息、邮件草稿、PPT大纲、正式HTML/PDF报告
- 语言风格：先结论 → 原因 → 建议，拒绝流水账
- 调用 `generate_formal_report` 生成包含图表的正式报告

## 正式报告生成

### 5步流水线

```
数据采集 → 深度分析 → 图表渲染 → HTML构建 → PDF导出
```

### 报告结构（8个板块）

1. **封面** — 标题、期间、生成日期、保密声明
2. **管理层摘要** — 6个KPI卡片 + 环比变化 + 核心发现
3. **收入分析** — 趋势折线图 + 品类/品牌/渠道拆解 + 深度下钻
4. **品类经营分析** — 回收×销售×库存打通后的品类毛利分析
5. **成本分析** — 成本结构饼图 + P&L对比 + 明细账科目下钻
6. **库存分析** — 库龄分布堆叠图 + 周转天数趋势 + 滞销预警
7. **渠道效率** — 回收→销售转化率 + 渠道毛利对比
8. **风险预警** — 规则引擎自动触发的告警
9. **行动建议** — 3-5条优先级标注的可执行建议

### 图表清单

| 图表 | 类型 | 数据来源 |
|------|------|----------|
| 收入与成本趋势 | 折线图 | `monthly_overview` |
| 毛利率趋势 | 折线图 | `monthly_overview` |
| 品类回收金额TOP10 | 横向条形图 | `category_breakdown` |
| 品类经营分析TOP10 | 双柱+折线 | `category_margin` |
| 品牌回收金额TOP10 | 横向条形图 | `brand_breakdown` |
| 销售收入渠道占比 | 饼图 | `sales_channel` |
| 库龄分布 | 堆叠条形图 | `inventory_aging` |
| 成本结构分布 | 饼图 | `cost_by_level1` |
| 库存周转天数趋势 | 折线图 | `inventory_turnover` |
| 回收→销售转化率趋势 | 双折线图 | `cross_table` |

### 深度分析能力

`report_deep_analyzer.py` 实现自动归因分析：

- **收入变化归因**：品类 → 品牌 → 渠道 → 业务线，找出贡献最大的变化因子
- **成本变化归因**：P&L项目 → 明细科目 → 业务线 → 法人实体，定位超支科目
- **库存风险分析**：库龄 → 品类 → 品牌，识别滞销品
- **渠道盈利性**：各渠道收入/成本/毛利，找出亏损渠道

## 安装与运行

### 环境要求

- Python 3.12+
- DuckDB 1.5.2+
- Playwright + Chromium（PDF导出）

### 安装依赖

```bash
pip install duckdb jinja2 matplotlib playwright
python -m playwright install chromium
```

### 生成正式报告

```bash
# 生成 HTML + PDF
python scripts/generate_formal_report.py --month 2026-03 --format both

# 仅生成 HTML
python scripts/generate_formal_report.py --month 2026-03 --format html

# 指定输出目录
python scripts/generate_formal_report.py --month 2026-03 --format both --output-dir ./my_reports

# 指定报告版本
python scripts/generate_formal_report.py --month 2026-03 --format html --profile ceo
python scripts/generate_formal_report.py --month 2026-03 --format html --profile category_manager
```

输出文件位于 `outputs/formal_report/` 目录：
- `2026-03_formal_report.html`
- `2026-03_formal_report.pdf`
- 非 `full` 版本会增加后缀，例如 `2026-03_ceo_formal_report.html`

可用报告版本：
- `full`：完整版，包含所有板块
- `ceo`：CEO全局版，聚焦全局KPI和核心风险
- `category_manager`：品类经理版，聚焦品类毛利和库存
- `channel_manager`：渠道经理版，聚焦渠道效率和转化

### 数据导入

```bash
# 导入所有数据（回收/销售/库存）
python scripts/import_all.py

# 导入明细账
python scripts/ledger_management_report.py
```

## 预警规则

规则统一由 `rules/finance_rules.json` 管理：

| 规则 | 条件 | 阈值 | 级别 |
|------|------|------|------|
| 毛利率过低 | `<` | 5.0% | warning |
| 亏损预警 | `<` | 0 | critical |
| 库龄过高 | `>` | 45天 | warning |
| 周转过慢 | `>` | 30天 | warning |
| 成本占比异常 | `>` | 95.0% | warning |
| 回收量过低 | `<` | 100单 | info |

## 当前状态

- [x] ETL 数据导入（回收/销售/库存/明细账）
- [x] DuckDB 数据库（29张表/视图，4200万+行）
- [x] MCP Server（7个工具）
- [x] 3个 Agent（Orchestrator/Analyst/Reporter）
- [x] 正式报告生成（HTML + PDF，10个图表 + 深度分析 + profile版本）
- [x] 飞书集成
- [ ] 告警推送自动化
- [ ] 定时报告调度
- [ ] 多月对比分析
