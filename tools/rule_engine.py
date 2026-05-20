# ==============================================
# 规则引擎
# 从 rules/finance_rules.json 加载预警规则
# 检查指标值是否触发阈值，返回告警列表
# ==============================================

import json
from pathlib import Path
from typing import Optional

from tools.logger import StructuredLogger, generate_trace_id

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = PROJECT_ROOT / "rules" / "finance_rules.json"


class RuleEngine:
    def __init__(self, rules_path: Path = RULES_PATH):
        self.rules = self._load_rules(rules_path)
        self.logger = StructuredLogger("rule_engine")

    def _load_rules(self, path: Path) -> list[dict]:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("rules", [])

    def check(
        self,
        metric_name: str,
        value: float,
        dimension: Optional[str] = None,
        dim_value: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> list[dict]:
        trace_id = trace_id or generate_trace_id()
        alerts = []
        for rule in self.rules:
            if rule["metric"] != metric_name:
                continue
            if self._evaluate(rule, value):
                alert = {
                    "rule_name": rule["name"],
                    "severity": rule["severity"],
                    "message": rule["message"].format(
                        value=value,
                        threshold=rule["threshold"],
                        dimension=dimension or "",
                        dim_value=dim_value or "",
                    ),
                    "trace_id": trace_id,
                }
                alerts.append(alert)
                self.logger.warning(trace_id, alert["message"], rule=rule["name"])
        return alerts

    def _evaluate(self, rule: dict, value: float) -> bool:
        op = rule["condition"]
        threshold = rule["threshold"]
        if op == "gt":
            return value > threshold
        if op == "lt":
            return value < threshold
        if op == "gte":
            return value >= threshold
        if op == "lte":
            return value <= threshold
        if op == "eq":
            return value == threshold
        return False

    def check_monthly_overview(self, overview_row: dict, trace_id: Optional[str] = None) -> list[dict]:
        trace_id = trace_id or generate_trace_id()
        all_alerts = []
        checkable = ["毛利率", "毛利", "库存周转天数", "平均库龄", "销售额", "回收量"]
        for metric in checkable:
            val = overview_row.get(metric)
            if val is not None and val != 0:
                alerts = self.check(metric, float(val), trace_id=trace_id)
                all_alerts.extend(alerts)
        return all_alerts
