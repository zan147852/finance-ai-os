# ==============================================
# 报告数据采集层
# 从 DuckDB 查询所有报告所需数据
# 财务口径：GMV = 非买家服务费+佣金+实际到账+换货补贴
#          销售收入 = GMV / 1.02
#          毛利 = (销售收入 - 商品成本) / 销售收入
# ==============================================

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.db import get_conn


@dataclass
class ReportData:
    current_month: str
    previous_month: str
    # 月度总览（使用修正口径）
    monthly_overview: list[dict] = field(default_factory=list)
    # 按品类
    category_breakdown: list[dict] = field(default_factory=list)
    # 品类级毛利（回收+销售+库存）
    category_margin: list[dict] = field(default_factory=list)
    # 按品牌
    brand_breakdown: list[dict] = field(default_factory=list)
    # 按渠道（销售）
    sales_channel: list[dict] = field(default_factory=list)
    # 按履约方式（回收）
    fulfillment: list[dict] = field(default_factory=list)
    # 按终端（回收）
    terminal: list[dict] = field(default_factory=list)
    # 库龄分布
    inventory_aging: list[dict] = field(default_factory=list)
    # 库存周转
    inventory_turnover: list[dict] = field(default_factory=list)
    # 回收-销售转化
    cross_table: list[dict] = field(default_factory=list)
    # 明细账P&L（管理报表）
    pnl_items: list[dict] = field(default_factory=list)
    # 管报P&L实际数据的period_serial
    pnl_period_serial: int | None = None
    # 管报P&L数据对应的月份标签
    pnl_period_label: str | None = None
    # 明细账下钻 — 按report_level1
    cost_by_level1: list[dict] = field(default_factory=list)
    # 明细账下钻 — 按report_level2
    cost_by_level2: list[dict] = field(default_factory=list)
    # 明细账下钻 — 按业务线
    cost_by_business: list[dict] = field(default_factory=list)
    # 明细账下钻 — 按法人实体
    cost_by_entity: list[dict] = field(default_factory=list)
    # 当月KPI汇总
    current_kpis: dict = field(default_factory=dict)
    # 上月KPI汇总
    previous_kpis: dict = field(default_factory=dict)


def _query(sql: str, params: list | tuple | None = None) -> list[dict]:
    con = get_conn(read_only=True)
    df = con.execute(sql, params or []).fetchdf()
    result = df.to_dict(orient="records")
    for row in result:
        for key, value in row.items():
            if hasattr(value, "item"):
                row[key] = value.item()
    return result


def _month_offset(month: str, delta: int) -> str:
    """月份偏移，如 2026-04 + (-1) = 2026-03"""
    y, m = int(month[:4]), int(month[5:7])
    m += delta
    while m > 12:
        m -= 12
        y += 1
    while m < 1:
        m += 12
        y -= 1
    return f"{y:04d}-{m:02d}"


def _month_to_period_serial(month: str) -> int:
    """月份字符串转 Excel 日期序列号，如 2026-01 -> 46023"""
    from datetime import date as _date
    y, m = int(month[:4]), int(month[5:7])
    d = _date(y, m, 1)
    epoch = _date(1899, 12, 30)
    return (d - epoch).days


def _period_serial_to_month(serial: int) -> str:
    """Excel 日期序列号转月份字符串，如 46023 -> 2026-01"""
    from datetime import date as _date, timedelta as _td
    epoch = _date(1899, 12, 30)
    d = epoch + _td(days=int(serial))
    return f"{d.year:04d}-{d.month:02d}"


def _get_ledger_period(month: str) -> str:
    """月份转明细账period（季度），取最近可用period"""
    rows = _query("SELECT MAX(period) AS period FROM ledger_raw_detail")
    return rows[0]["period"] if rows and rows[0].get("period") else "1"


def _find_month(records: list[dict], month: str) -> Optional[dict]:
    for row in records:
        if row.get("月份") == month:
            return row
    return None


def _split_ledger_costs(rows: list[dict], data: ReportData) -> None:
    data.cost_by_level1 = [
        {"report_level1_name": row.get("report_level1_name"), "total_k": row.get("total_k")}
        for row in rows
        if row.get("bucket") == "level1"
    ]
    data.cost_by_level2 = [
        {
            "report_level1_name": row.get("report_level1_name"),
            "report_level2_name": row.get("report_level2_name"),
            "total_k": row.get("total_k"),
        }
        for row in rows
        if row.get("bucket") == "level2"
    ]
    data.cost_by_business = [
        {"business": row.get("business"), "report_subject": row.get("report_subject"), "total_k": row.get("total_k")}
        for row in rows
        if row.get("bucket") == "business"
    ]
    data.cost_by_entity = [
        {"ledger_name": row.get("ledger_name"), "report_subject": row.get("report_subject"), "total_k": row.get("total_k")}
        for row in rows
        if row.get("bucket") == "entity"
    ]


def _build_category_breakdown(category_margin: list[dict]) -> list[dict]:
    return [
        {
            "月份": row.get("月份"),
            "品类": row.get("品类"),
            "回收量": row.get("回收量", 0),
            "回收金额": row.get("回收金额", 0),
            "库存金额": row.get("库存金额", 0),
            "库存数量": row.get("库存数量", 0),
        }
        for row in category_margin
    ]


SQL_MONTHLY_OVERVIEW = """
WITH s AS (
    SELECT 月份,
           SUM(COALESCE(非买家服务费金额,0) + COALESCE(佣金金额,0) + COALESCE(实际到账,0) + COALESCE(换货补贴金额,0)) / 1000 AS gmv,
           SUM(COALESCE(非买家服务费金额,0) + COALESCE(佣金金额,0) + COALESCE(实际到账,0) + COALESCE(换货补贴金额,0)) / 1.02 / 1000 AS 销售收入,
           SUM(COALESCE(商品成本,0)) / 1000 AS 商品成本,
           (SUM(COALESCE(非买家服务费金额,0) + COALESCE(佣金金额,0) + COALESCE(实际到账,0) + COALESCE(换货补贴金额,0)) / 1.02 - SUM(COALESCE(商品成本,0)))
               / NULLIF(SUM(COALESCE(非买家服务费金额,0) + COALESCE(佣金金额,0) + COALESCE(实际到账,0) + COALESCE(换货补贴金额,0)) / 1.02, 0) AS 毛利率
    FROM sales_detail
    GROUP BY 月份
),
r AS (
    SELECT 月份,
           COUNT(DISTINCT 回收单id) AS 回收量,
           ROUND(SUM(c1) / 1000, 2) AS 回收金额
    FROM recycle_detail
    GROUP BY 月份
),
inv AS (
    SELECT 月份,
           ROUND(SUM(库存价值) / 1000, 2) AS 库存金额,
           ROUND(AVG(库龄), 1) AS 平均库龄,
           COUNT(*) AS 库存数量
    FROM inventory_detail
    GROUP BY 月份
)
SELECT
    COALESCE(r.月份, s.月份, inv.月份) AS 月份,
    COALESCE(r.回收量, 0) AS 回收量,
    COALESCE(r.回收金额, 0) AS 回收金额,
    ROUND(COALESCE(s.gmv, 0), 2) AS 销售GMV,
    ROUND(COALESCE(s.销售收入, 0), 2) AS 销售收入,
    ROUND(COALESCE(s.商品成本, 0), 2) AS 商品成本,
    ROUND(COALESCE(s.毛利率, 0) * 100, 2) AS 毛利率,
    COALESCE(inv.库存金额, 0) AS 库存金额,
    COALESCE(inv.平均库龄, 0) AS 平均库龄,
    COALESCE(inv.库存数量, 0) AS 库存数量
FROM r
FULL OUTER JOIN s ON r.月份 = s.月份
FULL OUTER JOIN inv ON COALESCE(r.月份, s.月份) = inv.月份
ORDER BY 月份
"""

SQL_CATEGORY_MARGIN = """
WITH recycle_cat AS (
    SELECT 月份, 品类,
           COUNT(DISTINCT 回收单id) AS 回收量,
           ROUND(SUM(c1) / 1000, 2) AS 回收金额
    FROM recycle_detail
    GROUP BY 月份, 品类
),
sales_cat AS (
    SELECT 月份, 类目 AS 品类,
           ROUND(SUM(COALESCE(非买家服务费金额,0) + COALESCE(佣金金额,0) + COALESCE(实际到账,0) + COALESCE(换货补贴金额,0)) / 1.02 / 1000, 2) AS 销售收入,
           ROUND(SUM(COALESCE(商品成本,0)) / 1000, 2) AS 商品成本
    FROM sales_detail
    GROUP BY 月份, 类目
),
inv_cat AS (
    SELECT 月份, 品类,
           ROUND(SUM(库存价值) / 1000, 2) AS 库存金额,
           COUNT(*) AS 库存数量
    FROM inventory_detail
    GROUP BY 月份, 品类
)
SELECT
    COALESCE(r.月份, s.月份, i.月份) AS 月份,
    COALESCE(r.品类, s.品类, i.品类) AS 品类,
    COALESCE(r.回收量, 0) AS 回收量,
    COALESCE(r.回收金额, 0) AS 回收金额,
    COALESCE(s.销售收入, 0) AS 销售收入,
    COALESCE(s.商品成本, 0) AS 商品成本,
    ROUND(COALESCE(s.销售收入, 0) - COALESCE(s.商品成本, 0), 2) AS 毛利额,
    ROUND((COALESCE(s.销售收入, 0) - COALESCE(s.商品成本, 0)) / NULLIF(COALESCE(s.销售收入, 0), 0) * 100, 2) AS 毛利率,
    COALESCE(i.库存金额, 0) AS 库存金额,
    COALESCE(i.库存数量, 0) AS 库存数量
FROM recycle_cat r
FULL OUTER JOIN sales_cat s ON r.月份 = s.月份 AND r.品类 = s.品类
FULL OUTER JOIN inv_cat i ON COALESCE(r.月份, s.月份) = i.月份
    AND COALESCE(r.品类, s.品类) = i.品类
ORDER BY 月份, 回收金额 DESC
"""

SQL_BRAND_BREAKDOWN = """
WITH recycle_brand AS (
    SELECT 月份, 品牌,
           COUNT(DISTINCT 回收单id) AS 回收量,
           ROUND(SUM(c1) / 1000, 2) AS 回收金额
    FROM recycle_detail
    GROUP BY 月份, 品牌
),
sales_brand AS (
    SELECT 月份, 品牌,
           SUM(COALESCE(非买家服务费金额,0) + COALESCE(佣金金额,0) + COALESCE(实际到账,0) + COALESCE(换货补贴金额,0)) / 1.02 / 1000 AS 销售收入,
           SUM(COALESCE(商品成本,0)) / 1000 AS 商品成本
    FROM sales_detail
    GROUP BY 月份, 品牌
),
inv_brand AS (
    SELECT 月份, 品牌,
           ROUND(SUM(库存价值) / 1000, 2) AS 库存金额
    FROM inventory_detail
    GROUP BY 月份, 品牌
)
SELECT
    COALESCE(r.月份, s.月份, i.月份) AS 月份,
    COALESCE(r.品牌, s.品牌, i.品牌) AS 品牌,
    COALESCE(r.回收量, 0) AS 回收量,
    COALESCE(r.回收金额, 0) AS 回收金额,
    ROUND(COALESCE(s.销售收入, 0), 2) AS 销售收入,
    ROUND(COALESCE(s.商品成本, 0), 2) AS 商品成本,
    ROUND(COALESCE(i.库存金额, 0), 2) AS 库存金额
FROM recycle_brand r
FULL OUTER JOIN sales_brand s ON r.月份 = s.月份 AND r.品牌 = s.品牌
FULL OUTER JOIN inv_brand i ON COALESCE(r.月份, s.月份) = i.月份
    AND COALESCE(r.品牌, s.品牌) = i.品牌
ORDER BY 月份, 回收金额 DESC
"""

SQL_SALES_CHANNEL = """
SELECT
    月份,
    财务业务线,
    COUNT(*) AS 销售单量,
    ROUND(SUM(COALESCE(非买家服务费金额,0) + COALESCE(佣金金额,0) + COALESCE(实际到账,0) + COALESCE(换货补贴金额,0)) / 1.02 / 1000, 2) AS 销售收入,
    ROUND(SUM(COALESCE(商品成本,0)) / 1000, 2) AS 商品成本,
    ROUND(
        (SUM(COALESCE(非买家服务费金额,0) + COALESCE(佣金金额,0) + COALESCE(实际到账,0) + COALESCE(换货补贴金额,0)) / 1.02 - SUM(COALESCE(商品成本,0)))
        / NULLIF(SUM(COALESCE(非买家服务费金额,0) + COALESCE(佣金金额,0) + COALESCE(实际到账,0) + COALESCE(换货补贴金额,0)) / 1.02, 0) * 100,
        2
    ) AS 毛利率
FROM sales_detail
GROUP BY 月份, 财务业务线
ORDER BY 月份, 销售收入 DESC
"""

SQL_FULFILLMENT = """
SELECT 月份, 履约方式,
       COUNT(DISTINCT 回收单id) AS 回收量,
       ROUND(SUM(c1) / 1000, 2) AS 回收金额,
       ROUND(SUM(c1) / 1000 / NULLIF(COUNT(DISTINCT 回收单id), 0), 2) AS 单均回收金额
FROM recycle_detail
GROUP BY 月份, 履约方式
ORDER BY 月份, 回收金额 DESC
"""

SQL_TERMINAL = """
SELECT 月份, 终端,
       COUNT(DISTINCT 回收单id) AS 回收量,
       ROUND(SUM(c1) / 1000, 2) AS 回收金额,
       ROUND(SUM(c1) / 1000 / NULLIF(COUNT(DISTINCT 回收单id), 0), 2) AS 单均回收金额
FROM recycle_detail
GROUP BY 月份, 终端
ORDER BY 月份, 回收金额 DESC
"""

SQL_INVENTORY_AGING = """
SELECT 月份,
       CASE
           WHEN 库龄 <= 7 THEN '0-7天'
           WHEN 库龄 <= 14 THEN '8-14天'
           WHEN 库龄 <= 30 THEN '15-30天'
           WHEN 库龄 <= 60 THEN '31-60天'
           ELSE '60天以上'
       END AS 库龄段,
       COUNT(*) AS 库存数量,
       ROUND(SUM(库存价值) / 1000, 2) AS 库存金额
FROM inventory_detail
GROUP BY 月份,
    CASE
        WHEN 库龄 <= 7 THEN '0-7天'
        WHEN 库龄 <= 14 THEN '8-14天'
        WHEN 库龄 <= 30 THEN '15-30天'
        WHEN 库龄 <= 60 THEN '31-60天'
        ELSE '60天以上'
    END
ORDER BY 月份, 库龄段
"""

SQL_INVENTORY_TURNOVER = """
WITH inv AS (
    SELECT 月份,
           ROUND(SUM(库存价值) / 1000, 2) AS 月库存金额,
           COUNT(*) AS 月库存数量
    FROM inventory_detail
    GROUP BY 月份
),
sales AS (
    SELECT 月份,
           ROUND(SUM(商品成本) / 1000, 2) AS 月销售成本
    FROM sales_detail
    GROUP BY 月份
),
md AS (
    SELECT 月份,
           CAST(
               CASE
                   WHEN SUBSTR(月份, 6, 2) IN ('04','06','09','11') THEN 30
                   WHEN SUBSTR(月份, 6, 2) = '02' THEN 28
                   ELSE 31
               END AS DOUBLE
           ) AS 月天数
    FROM (SELECT DISTINCT 月份 FROM inventory_detail) t
)
SELECT i.月份, i.月库存金额, i.月库存数量,
       COALESCE(s.月销售成本, 0) AS 月销售成本,
       md.月天数,
       ROUND(i.月库存金额 / NULLIF(s.月销售成本 / md.月天数, 0), 1) AS 库存周转天数
FROM inv i
LEFT JOIN sales s ON i.月份 = s.月份
LEFT JOIN md ON i.月份 = md.月份
ORDER BY i.月份
"""

SQL_CROSS_TABLE = """
WITH r AS (
    SELECT 月份, COUNT(DISTINCT 回收单id) AS 回收量, ROUND(SUM(c1) / 1000, 2) AS 回收金额
    FROM recycle_detail GROUP BY 月份
),
s AS (
    SELECT 月份, COUNT(*) AS 销售量,
           SUM(COALESCE(非买家服务费金额,0) + COALESCE(佣金金额,0) + COALESCE(实际到账,0) + COALESCE(换货补贴金额,0)) / 1.02 / 1000 AS 销售收入
    FROM sales_detail GROUP BY 月份
),
i AS (
    SELECT 月份, ROUND(SUM(库存价值) / 1000, 2) AS 库存金额
    FROM inventory_detail GROUP BY 月份
)
SELECT COALESCE(r.月份, s.月份) AS 月份,
       COALESCE(r.回收量, 0) AS 回收量,
       COALESCE(s.销售量, 0) AS 销售量,
       ROUND(COALESCE(s.销售量, 0) / NULLIF(r.回收量, 0) * 100, 2) AS 回收销售转化率,
       COALESCE(r.回收金额, 0) AS 回收金额,
       ROUND(COALESCE(s.销售收入, 0), 2) AS 销售收入,
       COALESCE(i.库存金额, 0) AS 库存金额,
       ROUND(COALESCE(s.销售收入, 0) / NULLIF(r.回收金额, 0) * 100, 2) AS 金额转化率
FROM r FULL OUTER JOIN s ON r.月份 = s.月份
FULL OUTER JOIN i ON COALESCE(r.月份, s.月份) = i.月份
ORDER BY 月份
"""

SQL_PNL_ITEMS = """
SELECT item_group, item_name, metric_type, period_serial,
       ROUND(SUM(value), 2) AS total_value
FROM management_report_output
WHERE metric_type = 'Act.'
GROUP BY item_group, item_name, metric_type, period_serial
ORDER BY period_serial, item_name, metric_type
"""

SQL_LEDGER_COSTS = """
SELECT 'level1' AS bucket,
       report_level1_name,
       NULL AS report_level2_name,
       NULL AS business,
       NULL AS ledger_name,
       NULL AS report_subject,
       ROUND(SUM(ABS(amount_k)), 2) AS total_k
FROM ledger_raw_detail
WHERE period = ?
GROUP BY report_level1_name
UNION ALL
SELECT 'level2' AS bucket,
       report_level1_name,
       report_level2_name,
       NULL AS business,
       NULL AS ledger_name,
       NULL AS report_subject,
       ROUND(SUM(ABS(amount_k)), 2) AS total_k
FROM ledger_raw_detail
WHERE period = ?
GROUP BY report_level1_name, report_level2_name
UNION ALL
SELECT 'business' AS bucket,
       NULL AS report_level1_name,
       NULL AS report_level2_name,
       business,
       NULL AS ledger_name,
       report_subject,
       ROUND(SUM(ABS(amount_k)), 2) AS total_k
FROM ledger_raw_detail
WHERE period = ?
GROUP BY business, report_subject
UNION ALL
SELECT 'entity' AS bucket,
       NULL AS report_level1_name,
       NULL AS report_level2_name,
       NULL AS business,
       ledger_name,
       report_subject,
       ROUND(SUM(ABS(amount_k)), 2) AS total_k
FROM ledger_raw_detail
WHERE period = ?
GROUP BY ledger_name, report_subject
ORDER BY bucket, total_k DESC
"""


def collect_report_data(month: str) -> ReportData:
    """采集指定月份的完整报告数据"""
    previous_month = _month_offset(month, -1)
    period = _get_ledger_period(month)
    data = ReportData(current_month=month, previous_month=previous_month)

    parallel_queries = {
        "monthly_overview": (SQL_MONTHLY_OVERVIEW, None),
        "brand_breakdown": (SQL_BRAND_BREAKDOWN, None),
        "category_margin": (SQL_CATEGORY_MARGIN, None),
        "sales_channel": (SQL_SALES_CHANNEL, None),
        "fulfillment": (SQL_FULFILLMENT, None),
        "terminal": (SQL_TERMINAL, None),
        "inventory_aging": (SQL_INVENTORY_AGING, None),
        "inventory_turnover": (SQL_INVENTORY_TURNOVER, None),
        "cross_table": (SQL_CROSS_TABLE, None),
    }
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            name: pool.submit(_query, sql, params)
            for name, (sql, params) in parallel_queries.items()
        }
        for name, future in futures.items():
            setattr(data, name, future.result())
    data.category_breakdown = _build_category_breakdown(data.category_margin)

    # 管报P&L：只取 Act. 数据，优先请求月份，否则用最近可用 period
    all_pnl = _query(SQL_PNL_ITEMS)
    data.pnl_items = []
    data.pnl_period_serial = None
    data.pnl_period_label = None
    if all_pnl:
        available_periods = sorted(set(r["period_serial"] for r in all_pnl))
        requested_serial = _month_to_period_serial(month)
        if requested_serial in available_periods:
            target = requested_serial
        else:
            target = available_periods[-1]
        data.pnl_items = [r for r in all_pnl if r["period_serial"] == target]
        data.pnl_period_serial = target
        data.pnl_period_label = _period_serial_to_month(target)
    ledger_rows = _query(SQL_LEDGER_COSTS, [period, period, period, period])
    _split_ledger_costs(ledger_rows, data)

    data.current_kpis = _find_month(data.monthly_overview, month) or {}
    data.previous_kpis = _find_month(data.monthly_overview, previous_month) or {}

    return data


if __name__ == "__main__":
    data = collect_report_data("2026-04")
    print(f"Current: {data.current_month}, Previous: {data.previous_month}")
    print(f"Monthly overview rows: {len(data.monthly_overview)}")
    print(f"Category rows: {len(data.category_breakdown)}")
    print(f"Category margin rows: {len(data.category_margin)}")
    print(f"Brand rows: {len(data.brand_breakdown)}")
    print(f"Sales channel rows: {len(data.sales_channel)}")
    print(f"Inventory aging rows: {len(data.inventory_aging)}")
    print(f"Cost by level1 rows: {len(data.cost_by_level1)}")
    print(f"Cost by level2 rows: {len(data.cost_by_level2)}")
    print(f"PnL items rows: {len(data.pnl_items)}")
    print(f"Current KPIs: {data.current_kpis}")
