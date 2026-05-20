# ==============================================
# Finance MCP Server
# 将财务工具暴露为 MCP 协议，供 Hermes 调用
# 工具签名与 SOUL 文件 / hermes_tools.py 保持一致
# ==============================================

import json
import sys
import os
import io
import traceback

# 强制 stdout/stderr 使用 UTF-8 编码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 确保项目根目录在 Python 路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.query_metric import query_metric, get_monthly_overview, get_category_breakdown, get_brand_trend
from tools.rule_engine import RuleEngine
from tools.logger import StructuredLogger, generate_trace_id
from tools.metric_maps import METRIC_RULE_MAP, METRIC_VIEW_MAP

logger = StructuredLogger("mcp_server")
engine = RuleEngine()


def _sanitize_text(value):
    if isinstance(value, str):
        return value.encode("utf-8", "replace").decode("utf-8")
    if isinstance(value, dict):
        return {_sanitize_text(key): _sanitize_text(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_text(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_text(item) for item in value)
    return value

# MCP 工具定义 — 与 SOUL 文件中定义的调用签名对齐
TOOLS = [
    {
        "name": "query_metric",
        "description": "参数化查询财务指标，支持 metric_id+month 模式或 view_name 直接查询模式",
        "inputSchema": {
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
        "inputSchema": {
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
        "inputSchema": {
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
        "inputSchema": {
            "type": "object",
            "properties": {
                "start_month": {"type": "string"},
                "end_month": {"type": "string"},
            },
        },
    },
    {
        "name": "get_category_breakdown",
        "description": "获取指定月份的品类拆解数据。仅支持 month 参数，不要传 format 或其他参数。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "month": {"type": "string", "description": "月份，如 2025-01。仅接受此参数。"},
            },
            "required": ["month"],
        },
    },
    {
        "name": "get_brand_trend",
        "description": "获取按品牌拆解的趋势数据",
        "inputSchema": {
            "type": "object",
            "properties": {
                "start_month": {"type": "string"},
                "end_month": {"type": "string"},
            },
        },
    },
    {
        "name": "generate_formal_report",
        "description": "生成正式的PDF/HTML财务分析月报，包含图表、KPI表格、风险预警和行动建议",
        "inputSchema": {
            "type": "object",
            "properties": {
                "month": {"type": "string", "description": "报告期月份，如 2026-04"},
                "format": {"type": "string", "enum": ["html", "pdf", "both"], "default": "both",
                           "description": "输出格式"},
                "profile": {"type": "string", "description": "报告版本: full/ceo/category_manager/channel_manager"},
            },
            "required": ["month"],
        },
    },
]


def handle_request(request: dict) -> dict:
    """处理 MCP JSON-RPC 请求"""
    method = request.get("method")
    req_id = request.get("id")
    params = request.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "finance-tools", "version": "2.0.0"},
            },
        }

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        trace_id = generate_trace_id()

        try:
            result = _dispatch_tool(tool_name, arguments, trace_id)
            logger.info(trace_id, f"MCP tool call: {tool_name}", args=_sanitize_text(arguments))
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {"type": "text", "text": json.dumps(_sanitize_text(result), ensure_ascii=False, default=str)}
                    ]
                },
            }
        except Exception as e:
            logger.error(trace_id, f"MCP tool error: {tool_name}", error=str(e))
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": str(e)},
            }

    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "Method not found"}}


def _dispatch_tool(tool_name: str, arguments: dict, trace_id: str):
    """统一分发工具调用，支持新旧两种签名"""
    if tool_name == "query_metric":
        # 支持 metric_id 模式（SOUL 文件调用方式）
        if "metric_id" in arguments:
            metric_id = arguments["metric_id"]
            month = arguments.get("month")
            view_name = METRIC_VIEW_MAP.get(metric_id, metric_id)
            filters = dict(arguments.get("filters") or {})
            if month:
                filters["月份"] = month
            return query_metric(
                view_name=view_name,
                start_month=arguments.get("start_month"),
                end_month=arguments.get("end_month"),
                filters=filters if filters else None,
                order_by=arguments.get("order_by"),
                limit=arguments.get("limit"),
            )
        # view_name 直接查询模式（兼容旧调用）
        return query_metric(**arguments)

    elif tool_name == "check_finance_rule":
        metric_id = arguments["metric_id"]
        current_value = arguments["current_value"]
        metric_name = METRIC_RULE_MAP.get(metric_id, metric_id)
        return engine.check(metric_name=metric_name, value=current_value, trace_id=trace_id)

    elif tool_name == "check_rules":
        # 兼容旧调用
        return engine.check(**arguments, trace_id=trace_id)

    elif tool_name == "log_agent_event":
        agent_name = arguments["agent_name"]
        event_type = arguments["event_type"]
        payload_str = arguments.get("payload", "{}")
        log_trace_id = arguments.get("trace_id", trace_id)
        try:
            payload = json.loads(payload_str) if isinstance(payload_str, str) else payload_str
        except Exception:
            payload = {"raw_payload": payload_str}
        payload = _sanitize_text(payload)
        log_logger = StructuredLogger(agent_name)
        try:
            log_logger.info(trace_id=log_trace_id, message=event_type, **payload)
        except Exception:
            fallback = {"raw_payload": payload_str, "log_error": "payload_sanitization_failed"}
            log_logger.info(trace_id=log_trace_id, message=event_type, **fallback)
        return "ok"

    elif tool_name == "get_monthly_overview":
        return get_monthly_overview(**arguments)

    elif tool_name == "get_category_breakdown":
        return get_category_breakdown(**arguments)

    elif tool_name == "get_brand_trend":
        return get_brand_trend(**arguments)

    elif tool_name == "generate_formal_report":
        from scripts.generate_formal_report import run_report
        return run_report(
            month=arguments["month"],
            fmt=arguments.get("format", "both"),
            output_dir=arguments.get("output_dir"),
            profile=arguments.get("profile", "full"),
        )

    else:
        raise ValueError(f"Unknown tool: {tool_name}")


def main():
    """MCP stdio 主循环"""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = handle_request(request)
            if response is not None:
                print(json.dumps(_sanitize_text(response), ensure_ascii=False, default=str), flush=True)
        except json.JSONDecodeError:
            logger.warning(generate_trace_id(), "Invalid JSON request", raw_line=line)
            continue


if __name__ == "__main__":
    main()
