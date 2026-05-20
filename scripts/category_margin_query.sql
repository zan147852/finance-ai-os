-- ============================================================
-- 每月品类毛利率计算 SQL
-- Finance AI OS - trace_id: 20260514-004
-- ============================================================

-- 方案1：如果有销售明细表（sales_detail）
-- 假设表结构：order_id, category, sale_amount, cost_amount, sale_date

SELECT 
    DATE_FORMAT(sale_date, '%Y-%m') AS 月份,
    category AS 品类,
    COUNT(DISTINCT order_id) AS 订单数,
    SUM(sale_amount) AS 销售额,
    SUM(cost_amount) AS 销售成本,
    SUM(sale_amount) - SUM(cost_amount) AS 毛利,
    ROUND((SUM(sale_amount) - SUM(cost_amount)) / SUM(sale_amount) * 100, 2) AS 毛利率
FROM sales_detail
WHERE sale_date >= '2026-01-01' 
  AND sale_date < '2026-04-01'
GROUP BY DATE_FORMAT(sale_date, '%Y-%m'), category
ORDER BY 月份, 销售额 DESC;


-- ============================================================
-- 方案2：如果有回收-销售关联表（recycling_sales）
-- 假设表结构：recycling_id, category, recycling_amount, sale_amount, cost_amount, sale_date

SELECT 
    DATE_FORMAT(sale_date, '%Y-%m') AS 月份,
    category AS 品类,
    SUM(recycling_amount) AS 回收金额,
    SUM(sale_amount) AS 销售额,
    SUM(cost_amount) AS 销售成本,
    SUM(sale_amount) - SUM(cost_amount) AS 毛利,
    ROUND((SUM(sale_amount) - SUM(cost_amount)) / SUM(sale_amount) * 100, 2) AS 毛利率
FROM recycling_sales
WHERE sale_date >= '2026-01-01' 
  AND sale_date < '2026-04-01'
GROUP BY DATE_FORMAT(sale_date, '%Y-%m'), category
ORDER BY 月份, 销售额 DESC;


-- ============================================================
-- 方案3：如果数据在月度汇总表（monthly_category_summary）
-- 直接查询

SELECT 
    月份,
    品类,
    回收量,
    回收金额,
    销售额,
    销售成本,
    毛利,
    毛利率
FROM monthly_category_summary
WHERE 月份 BETWEEN '2026-01' AND '2026-03'
ORDER BY 月份, 回收金额 DESC;


-- ============================================================
-- 方案4：DuckDB 语法（如果用 DuckDB）

SELECT 
    strftime(sale_date, '%Y-%m') AS 月份,
    category AS 品类,
    SUM(sale_amount) AS 销售额,
    SUM(cost_amount) AS 销售成本,
    SUM(sale_amount) - SUM(cost_amount) AS 毛利,
    ROUND((SUM(sale_amount) - SUM(cost_amount)) / SUM(sale_amount) * 100, 2) AS 毛利率
FROM sales_detail
WHERE sale_date >= '2026-01-01' 
  AND sale_date < '2026-04-01'
GROUP BY strftime(sale_date, '%Y-%m'), category
ORDER BY 月份, 销售额 DESC;
