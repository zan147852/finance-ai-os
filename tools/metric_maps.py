# ==============================================
# 统一指标映射
# Hermes 工具层和 MCP Server 共用，避免同一映射多处漂移
# ==============================================

METRIC_VIEW_MAP = {
    "revenue": "v_monthly_overview",
    "gross_margin": "v_monthly_overview",
    "cost_ratio": "v_monthly_overview",
    "full_month": "v_monthly_overview",
}

METRIC_RULE_MAP = {
    "revenue": "销售额",
    "gross_margin": "毛利率",
    "cost_ratio": "销售成本占比",
    "full_month": "毛利率",
}
