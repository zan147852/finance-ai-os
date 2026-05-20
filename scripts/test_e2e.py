# ==============================================
# 端到端测试脚本
# 模拟完整 Agent 工作流：查询 → 分析 → 规则校验 → 日志记录
# 验证所有工具链路正常工作
# ==============================================

import json
import sys
import os

# 确保项目根目录在路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.hermes_tools import execute_tool
from tools.logger import generate_trace_id


def test_e2e():
    trace_id = generate_trace_id()
    print(f"Trace ID: {trace_id}")
    print("=" * 60)

    # Step 1: 查询毛利率
    print("\n[Step 1] 查询毛利率 (query_metric metric_id=gross_margin)")
    result = execute_tool("query_metric", {"metric_id": "gross_margin", "month": "2026-04"}, trace_id)
    data = json.loads(result)
    if isinstance(data, list) and len(data) > 0:
        print(f"  OK: 获取到 {len(data)} 条记录")
        print(f"  毛利率: {data[0].get('毛利率', 'N/A')}%")
    else:
        print(f"  FAIL: {data}")

    # Step 2: 查询销售额
    print("\n[Step 2] 查询销售额 (query_metric metric_id=revenue)")
    result = execute_tool("query_metric", {"metric_id": "revenue", "month": "2026-04"}, trace_id)
    data = json.loads(result)
    if isinstance(data, list) and len(data) > 0:
        print(f"  OK: 销售额 = {data[0].get('销售额', 'N/A')}")
    else:
        print(f"  FAIL: {data}")

    # Step 3: 查询月度总览
    print("\n[Step 3] 查询月度总览 (get_monthly_overview)")
    result = execute_tool("get_monthly_overview", {"start_month": "2026-01", "end_month": "2026-04"}, trace_id)
    data = json.loads(result)
    if isinstance(data, list) and len(data) > 0:
        print(f"  OK: 获取到 {len(data)} 个月的数据")
        for row in data:
            print(f"  {row['月份']}: 毛利率={row.get('毛利率', 'N/A')}%, 销售额={row.get('销售额', 'N/A')}")
    else:
        print(f"  FAIL: {data}")

    # Step 4: 检查规则
    print("\n[Step 4] 检查规则 (check_finance_rule metric_id=gross_margin)")
    result = execute_tool("check_finance_rule", {"metric_id": "gross_margin", "current_value": 16.18}, trace_id)
    data = json.loads(result)
    if isinstance(data, list):
        if len(data) > 0:
            print(f"  OK: 触发 {len(data)} 条规则")
            for alert in data:
                print(f"  - [{alert['severity']}] {alert['message']}")
        else:
            print("  OK: 未触发规则")
    else:
        print(f"  FAIL: {data}")

    # Step 5: 记录日志
    print("\n[Step 5] 记录日志 (log_agent_event)")
    result = execute_tool("log_agent_event", {
        "agent_name": "analyst",
        "event_type": "e2e_test",
        "payload": json.dumps({"metric": "gross_margin", "value": 16.18}),
        "trace_id": trace_id,
    }, trace_id)
    print(f"  Result: {result}")

    # Step 6: 查询品类拆解
    print("\n[Step 6] 查询品类拆解 (get_category_breakdown)")
    result = execute_tool("get_category_breakdown", {"month": "2026-04"}, trace_id)
    data = json.loads(result)
    if isinstance(data, list) and len(data) > 0:
        print(f"  OK: 获取到 {len(data)} 个品类")
    else:
        print(f"  FAIL: {data}")

    # Step 7: 查询品牌趋势
    print("\n[Step 7] 查询品牌趋势 (get_brand_trend)")
    result = execute_tool("get_brand_trend", {"start_month": "2026-01", "end_month": "2026-04"}, trace_id)
    data = json.loads(result)
    if isinstance(data, list) and len(data) > 0:
        print(f"  OK: 获取到 {len(data)} 条品牌记录")
    else:
        print(f"  FAIL: {data}")

    # Step 8: 验证日志文件
    print("\n[Step 8] 验证日志文件")
    from datetime import datetime
    today = datetime.now().strftime("%Y%m%d")
    log_file = f"logs/hermes_tools_{today}.jsonl"
    if os.path.exists(log_file):
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            trace_lines = [l for l in lines if trace_id in l]
            print(f"  OK: 日志文件存在, 共 {len(lines)} 行, 本 trace_id 相关 {len(trace_lines)} 行")
    else:
        print(f"  WARN: 日志文件不存在 {log_file}")

    print("\n" + "=" * 60)
    print("端到端测试完成")


if __name__ == "__main__":
    test_e2e()
