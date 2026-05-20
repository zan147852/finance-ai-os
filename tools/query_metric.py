# ==============================================
# 参数化指标查询工具
# 所有 Agent 通过此工具查询数据，禁止直接写 SQL
# 安全机制：视图/列白名单 + 参数绑定 + 默认限流
# ==============================================

import json
from typing import Optional

from tools.db import QueryTimeoutError, execute_query

MAX_LIMIT = 1000
DEFAULT_LIMIT = 100
MAX_JSON_CHARS = 4000

# 白名单：允许查询的视图
VIEW_COLUMNS = {
    "v_monthly_overview": (
        "月份", "回收量", "回收金额", "销售额", "销售成本", "毛利", "毛利率",
        "库存金额", "平均库龄", "库存数量",
    ),
    "v_monthly_by_category": (
        "月份", "品类", "回收量", "回收金额", "库存金额", "库存数量",
    ),
    "v_monthly_by_brand": (
        "月份", "品牌", "回收量", "回收金额", "销售额", "销售成本", "毛利", "库存金额",
    ),
    "v_monthly_by_terminal": (
        "月份", "终端", "回收量", "回收金额", "单均回收金额",
    ),
    "v_monthly_by_fulfillment": (
        "月份", "履约方式", "回收量", "回收金额", "单均回收金额",
    ),
    "v_monthly_by_sales_channel": (
        "月份", "财务业务线", "销售单量", "销售额", "销售成本", "毛利", "毛利率",
    ),
    "v_monthly_by_business_line": (
        "月份", "业务线名称", "回收量", "回收金额", "平均回收单价",
    ),
    "v_inventory_aging": (
        "月份", "库龄段", "库存数量", "库存金额", "占比",
    ),
    "v_monthly_by_financial_category": (
        "月份", "财务类目", "销售单量", "销售额", "销售成本", "毛利", "毛利率",
    ),
    "v_cross_table_monthly": (
        "月份", "回收量", "销售量", "回收销售转化率", "回收金额", "销售额",
        "库存金额", "金额转化率",
    ),
    "v_inventory_turnover": (
        "月份", "月库存金额", "月库存数量", "月销售成本", "月天数", "库存周转天数",
    ),
}
ALLOWED_VIEWS = set(VIEW_COLUMNS)

# 白名单：允许作为筛选条件的列
ALLOWED_FILTER_COLUMNS = {
    "月份", "品类", "品牌", "终端", "履约方式", "业务线名称",
    "财务业务线", "财务类目", "业务模式", "库龄段",
}


def _validate_column(view_name: str, column: str, usage: str) -> Optional[str]:
    allowed = VIEW_COLUMNS[view_name]
    if column not in allowed:
        return f"{usage}列 '{column}' 不属于视图 '{view_name}'，允许: {sorted(allowed)}"
    return None


def _parse_order_by(view_name: str, order_by: str) -> tuple[Optional[str], Optional[str]]:
    parts = order_by.strip().split()
    if len(parts) not in (1, 2):
        return None, "order_by 只允许格式: 列名、列名 ASC、列名 DESC"

    column = parts[0]
    err = _validate_column(view_name, column, "排序")
    if err:
        return None, err

    if len(parts) == 1:
        return column, None

    direction = parts[1].upper()
    if direction not in {"ASC", "DESC"}:
        return None, "order_by 排序方向只允许 ASC 或 DESC"
    return f"{column} {direction}", None


def _parse_limit(limit: int) -> tuple[Optional[int], Optional[str]]:
    try:
        parsed = int(limit)
    except (TypeError, ValueError):
        return None, "limit 必须是正整数"

    if parsed <= 0:
        return None, "limit 必须是正整数"
    if parsed > MAX_LIMIT:
        return None, f"limit 不能超过 {MAX_LIMIT}"
    return parsed, None


def _quote_identifier(column: str) -> str:
    return '"' + column.replace('"', '""') + '"'


def _truncate_output(records: list[dict], max_chars: int = MAX_JSON_CHARS) -> list[dict]:
    encoded = json.dumps(records, ensure_ascii=False, default=str)
    if len(encoded) <= max_chars:
        return records

    shown: list[dict] = []
    total_rows = len(records)
    for row in records:
        candidate = shown + [row, {"_truncated": True, "total_rows": total_rows, "shown_rows": len(shown) + 1}]
        candidate_json = json.dumps(candidate, ensure_ascii=False, default=str)
        if len(candidate_json) > max_chars:
            break
        shown.append(row)

    shown.append({"_truncated": True, "total_rows": total_rows, "shown_rows": len(shown)})
    return shown


def query_metric(
    view_name: str,
    start_month: Optional[str] = None,
    end_month: Optional[str] = None,
    filters: Optional[dict] = None,
    order_by: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[dict]:
    if view_name not in ALLOWED_VIEWS:
        return [{"error": f"未知视图 '{view_name}'，允许: {sorted(ALLOWED_VIEWS)}"}]

    columns = ", ".join(_quote_identifier(column) for column in VIEW_COLUMNS[view_name])
    sql = f"SELECT {columns} FROM {view_name}"
    params = []
    conditions = []

    if start_month:
        err = _validate_column(view_name, "月份", "筛选")
        if err:
            return [{"error": err}]
        conditions.append(f"{_quote_identifier('月份')} >= ?")
        params.append(start_month)
    if end_month:
        err = _validate_column(view_name, "月份", "筛选")
        if err:
            return [{"error": err}]
        conditions.append(f"{_quote_identifier('月份')} <= ?")
        params.append(end_month)
    if filters:
        for col, val in filters.items():
            if col not in ALLOWED_FILTER_COLUMNS:
                return [{"error": f"不允许的筛选列 '{col}'，允许: {sorted(ALLOWED_FILTER_COLUMNS)}"}]
            err = _validate_column(view_name, col, "筛选")
            if err:
                return [{"error": err}]
            conditions.append(f"{_quote_identifier(col)} = ?")
            params.append(val)

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    if order_by:
        safe_order_by, err = _parse_order_by(view_name, order_by)
        if err:
            return [{"error": err}]
        order_column, *order_rest = safe_order_by.split()
        safe_order_sql = _quote_identifier(order_column)
        if order_rest:
            safe_order_sql += f" {order_rest[0]}"
        sql += f" ORDER BY {safe_order_sql}"

    effective_limit = DEFAULT_LIMIT if limit is None else limit
    parsed_limit, err = _parse_limit(effective_limit)
    if err:
        return [{"error": err}]
    sql += f" LIMIT {parsed_limit}"

    try:
        df = execute_query(sql, params).fetchdf()
        return _truncate_output(df.to_dict(orient="records"))
    except QueryTimeoutError:
        return [{"error": "query timeout"}]
    except Exception as e:
        return [{"error": f"查询错误: {str(e)}"}]


def get_monthly_overview(start_month: Optional[str] = None, end_month: Optional[str] = None) -> list[dict]:
    return query_metric("v_monthly_overview", start_month=start_month, end_month=end_month)


def get_category_breakdown(month: str) -> list[dict]:
    return query_metric("v_monthly_by_category", filters={"月份": month})


def get_brand_trend(start_month: Optional[str] = None, end_month: Optional[str] = None) -> list[dict]:
    return query_metric("v_monthly_by_brand", start_month=start_month, end_month=end_month)
