# ==============================================
# Hermes 工具注册入口
# 将 query_metric、rule_engine、logger 封装为 Hermes 可调用的函数
# 适配 SOUL 文件中定义的工具签名
# ==============================================

import json
import traceback
from tools.query_metric import query_metric, get_monthly_overview, get_category_breakdown, get_brand_trend
from tools.rule_engine import RuleEngine
from tools.logger import StructuredLogger
from tools.metric_maps import METRIC_RULE_MAP, METRIC_VIEW_MAP

engine = RuleEngine()
logger = StructuredLogger("hermes_tools")

def hermes_query_metric(
    metric_id: str,
    month: str = None,
    start_month: str = None,
    end_month: str = None,
    view_name: str = None,
    filters: dict = None,
    order_by: str = None,
    limit: int = None,
    **_: object,
) -> str:
    try:
        resolved_view_name = view_name or METRIC_VIEW_MAP.get(metric_id, metric_id)
        query_filters = dict(filters or {})
        if month:
            query_filters["月份"] = month
        result = query_metric(
            view_name=resolved_view_name,
            start_month=start_month,
            end_month=end_month,
            filters=query_filters if query_filters else None,
            order_by=order_by,
            limit=limit,
        )
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": f"query_metric_error: {str(e)}"}, ensure_ascii=False)


def hermes_check_rule(metric_id: str, current_value: float, compare_value: float = None) -> str:
    try:
        metric_name = METRIC_RULE_MAP.get(metric_id, metric_id)
        result = engine.check(metric_name=metric_name, value=current_value)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def hermes_log_event(agent_name: str, event_type: str, payload: str = "{}", trace_id: str = "unknown") -> str:
    try:
        log_logger = StructuredLogger(agent_name)
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {"raw_payload": payload}
        log_logger.info(trace_id=trace_id, message=event_type, **payload)
        return "ok"
    except Exception as e:
        return f"log_error: {str(e)}"


def hermes_log_error(agent_name: str, error: str, trace_id: str = "unknown") -> str:
    try:
        log_logger = StructuredLogger(agent_name)
        log_logger.error(
            trace_id=trace_id,
            message="error",
            error=error,
            traceback=traceback.format_exc(),
        )
        return "ok"
    except Exception as e:
        return f"log_error: {str(e)}"


# ==============================================
# 工具注册表 — 供 Hermes 框架加载
# ==============================================

TOOL_SCHEMAS = [
    {
        "name": "query_metric",
        "description": "参数化查询财务指标，支持 metric_id + month 或底层 view_name 查询",
        "parameters": {
            "type": "object",
            "properties": {
                "metric_id": {"type": "string", "description": "指标ID: revenue/gross_margin/cost_ratio/full_month"},
                "month": {"type": "string", "description": "月份，如 2025-05，仅查询单月时使用"},
                "view_name": {"type": "string", "description": "底层视图名，直接查询时使用"},
                "start_month": {"type": "string", "description": "起始月份"},
                "end_month": {"type": "string", "description": "结束月份"},
                "filters": {"type": "object", "description": "过滤条件 {列名: 值}"},
                "order_by": {"type": "string", "description": "排序字段"},
                "limit": {"type": "integer", "description": "返回行数限制"},
            },
        },
    },
    {
        "name": "check_finance_rule",
        "description": "检查指标值是否触发预警规则，返回告警列表",
        "parameters": {
            "type": "object",
            "properties": {
                "metric_id": {"type": "string", "description": "指标ID: revenue/gross_margin/cost_ratio"},
                "current_value": {"type": "number", "description": "当前指标值"},
                "compare_value": {"type": "number", "description": "对比值（可选）"},
            },
            "required": ["metric_id", "current_value"],
        },
    },
    {
        "name": "log_agent_event",
        "description": "记录 Agent 操作日志，所有关键动作必须调用",
        "parameters": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string", "description": "Agent 名称"},
                "event_type": {"type": "string", "description": "事件类型"},
                "payload": {"type": "string", "description": "事件载荷 JSON 字符串"},
                "trace_id": {"type": "string", "description": "链路追踪ID"},
            },
            "required": ["agent_name", "event_type", "trace_id"],
        },
    },
    {
        "name": "get_monthly_overview",
        "description": "获取月度总览：回收量、回收金额、销售额、销售成本、毛利、毛利率、库存金额、平均库龄",
        "parameters": {
            "type": "object",
            "properties": {
                "start_month": {"type": "string"},
                "end_month": {"type": "string"},
            },
        },
    },
    {
        "name": "get_category_breakdown",
        "description": "获取指定月份的品类拆解数据",
        "parameters": {
            "type": "object",
            "properties": {
                "month": {"type": "string", "description": "月份，如 2025-01"},
            },
            "required": ["month"],
        },
    },
    {
        "name": "get_brand_trend",
        "description": "获取按品牌拆解的趋势数据",
        "parameters": {
            "type": "object",
            "properties": {
                "start_month": {"type": "string"},
                "end_month": {"type": "string"},
            },
        },
    },
]


def execute_tool(tool_name: str, arguments: dict, trace_id: str = None) -> str:
    trace_id = trace_id or "unknown"
    logger.info(trace_id, f"Executing tool: {tool_name}", args=arguments)

    try:
        if tool_name == "query_metric":
            # 支持两种调用方式：metric_id 模式 和 view_name 模式
            if "metric_id" in arguments:
                result = hermes_query_metric(**arguments)
            else:
                result = query_metric(**arguments)
                result = json.dumps(result, ensure_ascii=False, default=str)
        elif tool_name == "check_finance_rule":
            result = hermes_check_rule(**arguments)
        elif tool_name == "check_rules":
            result = engine.check(**arguments, trace_id=trace_id)
            result = json.dumps(result, ensure_ascii=False, default=str)
        elif tool_name == "log_agent_event":
            result = hermes_log_event(**arguments)
        elif tool_name == "get_monthly_overview":
            result = get_monthly_overview(**arguments)
            result = json.dumps(result, ensure_ascii=False, default=str)
        elif tool_name == "get_category_breakdown":
            result = get_category_breakdown(**arguments)
            result = json.dumps(result, ensure_ascii=False, default=str)
        elif tool_name == "get_brand_trend":
            result = get_brand_trend(**arguments)
            result = json.dumps(result, ensure_ascii=False, default=str)
        else:
            result = json.dumps({"error": f"Unknown tool: {tool_name}"}, ensure_ascii=False)
    except Exception as e:
        logger.error(trace_id, f"Tool {tool_name} failed", error=str(e))
        result = json.dumps({"error": f"{tool_name}_error: {str(e)}"}, ensure_ascii=False)

    logger.info(trace_id, f"Tool {tool_name} completed")
    return result
