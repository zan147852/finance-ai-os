# ==============================================
# 财务指标视图生成脚本
# 基于 3 张原始表（recycle_detail, sales_detail, inventory_detail）
# 创建 11 个分析视图，供 query_metric 工具查询
# ==============================================

import duckdb

DB_PATH = "finance.db"

# 所有视图定义：{视图名: SQL}
VIEWS = {}

# ---------- 1. 月度总览 ----------
VIEWS["v_monthly_overview"] = """
CREATE OR REPLACE VIEW v_monthly_overview AS
WITH
recycle AS (
    SELECT 月份,
           COUNT(DISTINCT 回收单id) AS 回收量,
           ROUND(SUM(c1), 2) AS 回收金额
    FROM recycle_detail
    GROUP BY 月份
),
sales AS (
    SELECT 月份,
           ROUND(SUM(实际到账), 2) AS 销售额,
           ROUND(SUM(商品成本), 2) AS 销售成本,
           ROUND(SUM(实际到账) - SUM(商品成本), 2) AS 毛利,
           ROUND((SUM(实际到账) - SUM(商品成本)) / NULLIF(SUM(实际到账), 0) * 100, 2) AS 毛利率
    FROM sales_detail
    GROUP BY 月份
),
inventory AS (
    SELECT 月份,
           ROUND(SUM(库存价值), 2) AS 库存金额,
           ROUND(AVG(库龄), 1) AS 平均库龄,
           COUNT(*) AS 库存数量
    FROM inventory_detail
    GROUP BY 月份
)
SELECT
    COALESCE(r.月份, s.月份, i.月份) AS 月份,
    COALESCE(r.回收量, 0) AS 回收量,
    COALESCE(r.回收金额, 0) AS 回收金额,
    COALESCE(s.销售额, 0) AS 销售额,
    COALESCE(s.销售成本, 0) AS 销售成本,
    COALESCE(s.毛利, 0) AS 毛利,
    COALESCE(s.毛利率, 0) AS 毛利率,
    COALESCE(i.库存金额, 0) AS 库存金额,
    COALESCE(i.平均库龄, 0) AS 平均库龄,
    COALESCE(i.库存数量, 0) AS 库存数量
FROM recycle r
FULL OUTER JOIN sales s ON r.月份 = s.月份
FULL OUTER JOIN inventory i ON COALESCE(r.月份, s.月份) = i.月份
ORDER BY 月份;
"""

# ---------- 2. 按品类拆解 ----------
VIEWS["v_monthly_by_category"] = """
CREATE OR REPLACE VIEW v_monthly_by_category AS
WITH
recycle_cat AS (
    SELECT 月份, 品类,
           COUNT(DISTINCT 回收单id) AS 回收量,
           ROUND(SUM(c1), 2) AS 回收金额
    FROM recycle_detail
    GROUP BY 月份, 品类
),
inventory_cat AS (
    SELECT 月份, 品类,
           ROUND(SUM(库存价值), 2) AS 库存金额,
           COUNT(*) AS 库存数量
    FROM inventory_detail
    GROUP BY 月份, 品类
)
SELECT
    COALESCE(r.月份, i.月份) AS 月份,
    COALESCE(r.品类, i.品类) AS 品类,
    COALESCE(r.回收量, 0) AS 回收量,
    COALESCE(r.回收金额, 0) AS 回收金额,
    COALESCE(i.库存金额, 0) AS 库存金额,
    COALESCE(i.库存数量, 0) AS 库存数量
FROM recycle_cat r
FULL OUTER JOIN inventory_cat i ON r.月份 = i.月份 AND r.品类 = i.品类
ORDER BY 月份, 品类;
"""

# ---------- 3. 按品牌拆解 ----------
VIEWS["v_monthly_by_brand"] = """
CREATE OR REPLACE VIEW v_monthly_by_brand AS
WITH
recycle_brand AS (
    SELECT 月份, 品牌,
           COUNT(DISTINCT 回收单id) AS 回收量,
           ROUND(SUM(c1), 2) AS 回收金额
    FROM recycle_detail
    GROUP BY 月份, 品牌
),
sales_brand AS (
    SELECT 月份, 品牌,
           ROUND(SUM(实际到账), 2) AS 销售额,
           ROUND(SUM(商品成本), 2) AS 销售成本,
           ROUND(SUM(实际到账) - SUM(商品成本), 2) AS 毛利
    FROM sales_detail
    GROUP BY 月份, 品牌
),
inventory_brand AS (
    SELECT 月份, 品牌,
           ROUND(SUM(库存价值), 2) AS 库存金额
    FROM inventory_detail
    GROUP BY 月份, 品牌
)
SELECT
    COALESCE(r.月份, s.月份, i.月份) AS 月份,
    COALESCE(r.品牌, s.品牌, i.品牌) AS 品牌,
    COALESCE(r.回收量, 0) AS 回收量,
    COALESCE(r.回收金额, 0) AS 回收金额,
    COALESCE(s.销售额, 0) AS 销售额,
    COALESCE(s.销售成本, 0) AS 销售成本,
    COALESCE(s.毛利, 0) AS 毛利,
    COALESCE(i.库存金额, 0) AS 库存金额
FROM recycle_brand r
FULL OUTER JOIN sales_brand s ON r.月份 = s.月份 AND r.品牌 = s.品牌
FULL OUTER JOIN inventory_brand i ON COALESCE(r.月份, s.月份) = i.月份
    AND COALESCE(r.品牌, s.品牌) = i.品牌
ORDER BY 月份, 品牌;
"""

# ---------- 4. 按终端渠道拆解（仅回收） ----------
VIEWS["v_monthly_by_terminal"] = """
CREATE OR REPLACE VIEW v_monthly_by_terminal AS
SELECT
    月份,
    终端,
    COUNT(DISTINCT 回收单id) AS 回收量,
    ROUND(SUM(c1), 2) AS 回收金额,
    ROUND(SUM(c1) / NULLIF(COUNT(DISTINCT 回收单id), 0), 2) AS 单均回收金额
FROM recycle_detail
GROUP BY 月份, 终端
ORDER BY 月份, 回收金额 DESC;
"""

# ---------- 5. 按履约方式拆解（仅回收） ----------
VIEWS["v_monthly_by_fulfillment"] = """
CREATE OR REPLACE VIEW v_monthly_by_fulfillment AS
SELECT
    月份,
    履约方式,
    COUNT(DISTINCT 回收单id) AS 回收量,
    ROUND(SUM(c1), 2) AS 回收金额,
    ROUND(SUM(c1) / NULLIF(COUNT(DISTINCT 回收单id), 0), 2) AS 单均回收金额
FROM recycle_detail
GROUP BY 月份, 履约方式
ORDER BY 月份, 回收金额 DESC;
"""

# ---------- 6. 按财务业务线拆解（仅销售） ----------
VIEWS["v_monthly_by_sales_channel"] = """
CREATE OR REPLACE VIEW v_monthly_by_sales_channel AS
SELECT
    月份,
    财务业务线,
    COUNT(*) AS 销售单量,
    ROUND(SUM(实际到账), 2) AS 销售额,
    ROUND(SUM(商品成本), 2) AS 销售成本,
    ROUND(SUM(实际到账) - SUM(商品成本), 2) AS 毛利,
    ROUND((SUM(实际到账) - SUM(商品成本)) / NULLIF(SUM(实际到账), 0) * 100, 2) AS 毛利率
FROM sales_detail
GROUP BY 月份, 财务业务线
ORDER BY 月份, 销售额 DESC;
"""

# ---------- 7. 按业务线名称拆解（仅回收） ----------
VIEWS["v_monthly_by_business_line"] = """
CREATE OR REPLACE VIEW v_monthly_by_business_line AS
SELECT
    月份,
    业务线名称,
    COUNT(DISTINCT 回收单id) AS 回收量,
    ROUND(SUM(c1), 2) AS 回收金额,
    ROUND(AVG(c1), 2) AS 平均回收单价
FROM recycle_detail
GROUP BY 月份, 业务线名称
ORDER BY 月份, 回收金额 DESC;
"""

# ---------- 8. 库龄分布 ----------
VIEWS["v_inventory_aging"] = """
CREATE OR REPLACE VIEW v_inventory_aging AS
SELECT
    月份,
    CASE
        WHEN 库龄 <= 7 THEN '0-7天'
        WHEN 库龄 <= 14 THEN '8-14天'
        WHEN 库龄 <= 30 THEN '15-30天'
        WHEN 库龄 <= 60 THEN '31-60天'
        ELSE '60天以上'
    END AS 库龄段,
    COUNT(*) AS 库存数量,
    ROUND(SUM(库存价值), 2) AS 库存金额,
    ROUND(SUM(库存价值) / NULLIF(SUM(SUM(库存价值)) OVER (PARTITION BY 月份), 0) * 100, 2) AS 占比
FROM inventory_detail
GROUP BY 月份,
    CASE
        WHEN 库龄 <= 7 THEN '0-7天'
        WHEN 库龄 <= 14 THEN '8-14天'
        WHEN 库龄 <= 30 THEN '15-30天'
        WHEN 库龄 <= 60 THEN '31-60天'
        ELSE '60天以上'
    END
ORDER BY 月份, 库龄段;
"""

# ---------- 9. 按财务类目拆解（仅销售） ----------
VIEWS["v_monthly_by_financial_category"] = """
CREATE OR REPLACE VIEW v_monthly_by_financial_category AS
SELECT
    月份,
    财务类目,
    COUNT(*) AS 销售单量,
    ROUND(SUM(实际到账), 2) AS 销售额,
    ROUND(SUM(商品成本), 2) AS 销售成本,
    ROUND(SUM(实际到账) - SUM(商品成本), 2) AS 毛利,
    ROUND((SUM(实际到账) - SUM(商品成本)) / NULLIF(SUM(实际到账), 0) * 100, 2) AS 毛利率
FROM sales_detail
GROUP BY 月份, 财务类目
ORDER BY 月份, 销售额 DESC;
"""

# ---------- 10. 回收-销售月度对比 ----------
VIEWS["v_cross_table_monthly"] = """
CREATE OR REPLACE VIEW v_cross_table_monthly AS
WITH
recycle_month AS (
    SELECT 月份,
           COUNT(DISTINCT 回收单id) AS 回收量,
           ROUND(SUM(c1), 2) AS 回收金额
    FROM recycle_detail
    GROUP BY 月份
),
sales_month AS (
    SELECT 月份,
           COUNT(*) AS 销售量,
           ROUND(SUM(实际到账), 2) AS 销售额
    FROM sales_detail
    GROUP BY 月份
),
inventory_month AS (
    SELECT 月份,
           ROUND(SUM(库存价值), 2) AS 库存金额
    FROM inventory_detail
    GROUP BY 月份
)
SELECT
    COALESCE(r.月份, s.月份) AS 月份,
    COALESCE(r.回收量, 0) AS 回收量,
    COALESCE(s.销售量, 0) AS 销售量,
    ROUND(COALESCE(s.销售量, 0) / NULLIF(r.回收量, 0) * 100, 2) AS 回收销售转化率,
    COALESCE(r.回收金额, 0) AS 回收金额,
    COALESCE(s.销售额, 0) AS 销售额,
    COALESCE(i.库存金额, 0) AS 库存金额,
    ROUND(COALESCE(s.销售额, 0) / NULLIF(r.回收金额, 0) * 100, 2) AS 金额转化率
FROM recycle_month r
FULL OUTER JOIN sales_month s ON r.月份 = s.月份
FULL OUTER JOIN inventory_month i ON COALESCE(r.月份, s.月份) = i.月份
ORDER BY 月份;
"""

# ---------- 11. 库存周转天数 ----------
VIEWS["v_inventory_turnover"] = """
CREATE OR REPLACE VIEW v_inventory_turnover AS
WITH
inventory_month AS (
    SELECT 月份,
           ROUND(SUM(库存价值), 2) AS 月库存金额,
           COUNT(*) AS 月库存数量
    FROM inventory_detail
    GROUP BY 月份
),
sales_month AS (
    SELECT 月份,
           ROUND(SUM(商品成本), 2) AS 月销售成本
    FROM sales_detail
    GROUP BY 月份
),
month_days AS (
    SELECT 月份,
           CAST(
               CASE
                   WHEN SUBSTR(月份, 1, 4) IN ('2024','2028') AND SUBSTR(月份, 6, 2) = '02' THEN 29
                   WHEN SUBSTR(月份, 6, 2) = '02' THEN 28
                   WHEN SUBSTR(月份, 6, 2) IN ('04','06','09','11') THEN 30
                   ELSE 31
               END AS DOUBLE
           ) AS 月天数
    FROM (SELECT DISTINCT 月份 FROM inventory_detail) t
)
SELECT
    i.月份,
    i.月库存金额,
    i.月库存数量,
    COALESCE(s.月销售成本, 0) AS 月销售成本,
    md.月天数,
    ROUND(i.月库存金额 / NULLIF(s.月销售成本 / md.月天数, 0), 1) AS 库存周转天数
FROM inventory_month i
LEFT JOIN sales_month s ON i.月份 = s.月份
LEFT JOIN month_days md ON i.月份 = md.月份
ORDER BY i.月份;
"""


def create_all_views():
    con = duckdb.connect(DB_PATH)
    try:
        for name, sql in VIEWS.items():
            con.execute(sql)
            count = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            print(f"  {name}: 创建成功 ({count} 行)")
        print(f"\n共创建 {len(VIEWS)} 个视图")
    finally:
        con.close()


if __name__ == "__main__":
    print("开始创建财务指标视图...")
    create_all_views()
    print("全部视图创建完成")
