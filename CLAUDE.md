# 项目：财务BP AI 工作台
- Python + DuckDB + Hermes + 飞书
- 所有脚本必须可复用，不硬编码
- 指标查询必须通过 query_metric 工具，参数化调用
- 所有 Agent 操作必须记录 trace_id 日志
- 规则统一由 rules/finance_rules.json 管理
- 当前目标：跑通 ETL→指标→双Agent→飞书闭环

## 稳定性约束
- 所有 DuckDB 查询统一通过 `tools/db.py` 连接管理，线程级复用连接，单连接最多执行200次查询后自动重建。
- 查询默认超时10秒；超时或 DuckDB 异常后必须 interrupt 并重建当前线程连接。
- `query_metric` 默认返回100行，最大1000行，禁止生成 `SELECT *`，必须使用视图列白名单。
- Agent 输出限制：Analyst 不超过600字，Orchestrator 最终回复不超过800字。
- 下一阶段再推进 `analyzers/`、`metric_catalog.yaml` 和 KPI 标准答案集，本轮不要混入大重构。
