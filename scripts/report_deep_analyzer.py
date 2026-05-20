# ==============================================
# 深度归因分析引擎
# 自动发现异常并下钻到明细科目
# ==============================================

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dataclasses import dataclass, field
from typing import Optional
from report_data_collector import ReportData


@dataclass
class AnalysisFinding:
    category: str  # 收入/成本/库存/渠道
    title: str  # 发现标题
    detail: str  # 详细说明
    severity: str  # info/warning/critical
    data: list[dict] = field(default_factory=list)  # 支撑数据


@dataclass
class DeepAnalysis:
    revenue_findings: list[AnalysisFinding] = field(default_factory=list)
    category_findings: list[AnalysisFinding] = field(default_factory=list)
    cost_findings: list[AnalysisFinding] = field(default_factory=list)
    inventory_findings: list[AnalysisFinding] = field(default_factory=list)
    channel_findings: list[AnalysisFinding] = field(default_factory=list)
    key_findings: list[str] = field(default_factory=list)  # 核心发现摘要
    recommendations: list[dict] = field(default_factory=list)  # 行动建议


class DeepAnalyzer:

    def __init__(self, data: ReportData):
        self.data = data

    def analyze(self) -> DeepAnalysis:
        result = DeepAnalysis()
        self._analyze_revenue(result)
        self._analyze_category_margin(result)
        self._analyze_cost(result)
        self._analyze_inventory(result)
        self._analyze_channels(result)
        self._generate_key_findings(result)
        self._generate_recommendations(result)
        return result

    def _get_month_data(self, records: list[dict], month: str) -> list[dict]:
        return [r for r in records if r.get("月份") == month]

    def _pct_change(self, current: float, previous: float) -> Optional[float]:
        if previous and previous != 0:
            return round((current - previous) / abs(previous) * 100, 2)
        return None

    # === 收入分析 ===

    def _analyze_revenue(self, result: DeepAnalysis):
        month = self.data.current_month
        prev = self.data.previous_month

        cur = next((r for r in self.data.monthly_overview if r.get("月份") == month), None)
        pre = next((r for r in self.data.monthly_overview if r.get("月份") == prev), None)

        if not cur:
            return

        # 品类维度下钻
        cur_cat = self._get_month_data(self.data.category_breakdown, month)
        pre_cat = self._get_month_data(self.data.category_breakdown, prev)

        if cur_cat and pre_cat:
            pre_cat_map = {r["品类"]: r for r in pre_cat}
            changes = []
            for c in cur_cat:
                p = pre_cat_map.get(c["品类"])
                if p and p.get("回收金额", 0) != 0:
                    chg = self._pct_change(c.get("回收金额", 0), p.get("回收金额", 0))
                    if chg is not None:
                        changes.append({
                            "品类": c["品类"],
                            "当月回收金额": c.get("回收金额", 0),
                            "上月回收金额": p.get("回收金额", 0),
                            "环比变化%": chg,
                        })
            changes.sort(key=lambda x: abs(x["环比变化%"]), reverse=True)
            if changes:
                top = changes[0]
                result.revenue_findings.append(AnalysisFinding(
                    category="收入",
                    title=f"品类变化最大：{top['品类']}，环比{top['环比变化%']:+.1f}%",
                    detail=f"回收金额从{top['上月回收金额']:,.0f}变为{top['当月回收金额']:,.0f}",
                    severity="info",
                    data=changes[:5],
                ))

        # 渠道维度下钻
        cur_ch = self._get_month_data(self.data.sales_channel, month)
        pre_ch = self._get_month_data(self.data.sales_channel, prev)

        if cur_ch and pre_ch:
            pre_ch_map = {r["财务业务线"]: r for r in pre_ch}
            ch_changes = []
            for c in cur_ch:
                p = pre_ch_map.get(c["财务业务线"])
                if p and p.get("销售收入", 0) != 0:
                    chg = self._pct_change(c.get("销售收入", 0), p.get("销售收入", 0))
                    if chg is not None:
                        ch_changes.append({
                            "渠道": c["财务业务线"],
                            "当月收入": c.get("销售收入", 0),
                            "上月收入": p.get("销售收入", 0),
                            "环比变化%": chg,
                            "当月毛利率%": c.get("毛利率", 0),
                        })
            ch_changes.sort(key=lambda x: abs(x["环比变化%"]), reverse=True)
            if ch_changes:
                top = ch_changes[0]
                result.revenue_findings.append(AnalysisFinding(
                    category="收入",
                    title=f"渠道变化最大：{top['渠道']}，收入环比{top['环比变化%']:+.1f}%",
                    detail=f"收入从{top['上月收入']:,.0f}变为{top['当月收入']:,.0f}，毛利率{top['当月毛利率%']:.1f}%",
                    severity="info",
                    data=ch_changes[:5],
                ))

    # === 品类经营分析 ===

    def _analyze_category_margin(self, result: DeepAnalysis):
        month = self.data.current_month
        prev = self.data.previous_month

        cur_cat = self._get_month_data(self.data.category_margin, month)
        pre_cat = self._get_month_data(self.data.category_margin, prev)
        if not cur_cat:
            return

        margin_rows = [r for r in cur_cat if r.get("销售收入", 0)]
        loss_categories = sorted(
            [r for r in margin_rows if (r.get("毛利率") or 0) < 0],
            key=lambda x: x.get("毛利率") or 0,
        )
        if loss_categories:
            worst = loss_categories[0]
            result.category_findings.append(AnalysisFinding(
                category="品类",
                title=f"负毛利品类：{len(loss_categories)}个",
                detail=f"毛利率最低为{worst.get('品类')}，毛利率{worst.get('毛利率', 0):.1f}%，毛利额{worst.get('毛利额', 0):,.0f}千元",
                severity="warning",
                data=[
                    {
                        "品类": r.get("品类"),
                        "销售收入": r.get("销售收入", 0),
                        "商品成本": r.get("商品成本", 0),
                        "毛利额": r.get("毛利额", 0),
                        "毛利率%": r.get("毛利率", 0),
                    }
                    for r in loss_categories[:5]
                ],
            ))

        if pre_cat:
            pre_map = {r.get("品类"): r for r in pre_cat}
            margin_changes = []
            for current in margin_rows:
                previous = pre_map.get(current.get("品类"))
                if not previous or previous.get("销售收入", 0) == 0:
                    continue
                current_margin = current.get("毛利率") or 0
                previous_margin = previous.get("毛利率") or 0
                margin_changes.append({
                    "品类": current.get("品类"),
                    "当月毛利率%": current_margin,
                    "上月毛利率%": previous_margin,
                    "变化pp": round(current_margin - previous_margin, 2),
                    "当月销售收入": current.get("销售收入", 0),
                })
            declines = sorted(margin_changes, key=lambda x: x["变化pp"])
            declines = [r for r in declines if r["变化pp"] < 0]
            if declines:
                top = declines[0]
                result.category_findings.append(AnalysisFinding(
                    category="品类",
                    title=f"毛利率下滑最大：{top['品类']}，环比{top['变化pp']:.2f}pp",
                    detail=f"毛利率从{top['上月毛利率%']:.1f}%变为{top['当月毛利率%']:.1f}%",
                    severity="warning" if top["变化pp"] <= -5 else "info",
                    data=declines[:5],
                ))

        high_recycle_low_margin = [
            r for r in cur_cat
            if (r.get("回收金额", 0) or 0) > 0 and (r.get("销售收入", 0) or 0) > 0 and (r.get("毛利率") or 0) < 5
        ]
        high_recycle_low_margin = sorted(
            high_recycle_low_margin,
            key=lambda x: x.get("回收金额", 0) or 0,
            reverse=True,
        )
        if high_recycle_low_margin:
            top = high_recycle_low_margin[0]
            result.category_findings.append(AnalysisFinding(
                category="品类",
                title=f"高回收低毛利：{top.get('品类')}",
                detail=f"回收金额{top.get('回收金额', 0):,.0f}千元，但毛利率仅{top.get('毛利率', 0):.1f}%",
                severity="warning",
                data=[
                    {
                        "品类": r.get("品类"),
                        "回收金额": r.get("回收金额", 0),
                        "销售收入": r.get("销售收入", 0),
                        "毛利率%": r.get("毛利率", 0),
                        "库存金额": r.get("库存金额", 0),
                    }
                    for r in high_recycle_low_margin[:5]
                ],
            ))

    # === 成本分析（核心下钻） ===

    def _analyze_cost(self, result: DeepAnalysis):
        # 按一级分类看成本结构
        if not self.data.cost_by_level1:
            return

        # 找出最大的成本项
        sorted_l1 = sorted(self.data.cost_by_level1, key=lambda x: abs(x.get("total_k", 0)), reverse=True)
        if sorted_l1:
            top_l1 = sorted_l1[:5]
            result.cost_findings.append(AnalysisFinding(
                category="成本",
                title=f"成本TOP5一级分类（本期）",
                detail=f"最大的成本项为{top_l1[0]['report_level1_name']}，金额{top_l1[0]['total_k']:,.0f}千元",
                severity="info",
                data=top_l1,
            ))

        # 下钻到二级分类（人力成本等）
        if not self.data.cost_by_level2:
            return

        # 按一级分组，展示每个一级下的二级明细
        level1_groups = {}
        for r in self.data.cost_by_level2:
            l1 = r.get("report_level1_name", "")
            if l1 not in level1_groups:
                level1_groups[l1] = []
            level1_groups[l1].append(r)

        # 找出人力成本等关键科目的明细
        key_l1_items = ["人员薪酬及福利", "履约费用", "市场费", "四费", "外包服务费"]
        for key_item in key_l1_items:
            if key_item in level1_groups:
                items = sorted(level1_groups[key_item], key=lambda x: abs(x.get("total_k", 0)), reverse=True)
                total = sum(abs(x.get("total_k", 0)) for x in items)
                if items:
                    result.cost_findings.append(AnalysisFinding(
                        category="成本",
                        title=f"{key_item}构成明细",
                        detail=f"{key_item}合计{total:,.0f}千元，最大子项为{items[0]['report_level2_name']}({items[0]['total_k']:,.0f}千元)",
                        severity="info",
                        data=items,
                    ))

        # 按业务线看成本
        if self.data.cost_by_business:
            biz_groups = {}
            for r in self.data.cost_by_business:
                biz = r.get("business", "")
                if biz not in biz_groups:
                    biz_groups[biz] = 0
                biz_groups[biz] += abs(r.get("total_k", 0))

            sorted_biz = sorted(biz_groups.items(), key=lambda x: x[1], reverse=True)
            if sorted_biz:
                result.cost_findings.append(AnalysisFinding(
                    category="成本",
                    title="业务线成本分布",
                    detail=f"成本最高的业务线为{sorted_biz[0][0]}，金额{sorted_biz[0][1]:,.0f}千元",
                    severity="info",
                    data=[{"业务线": b, "金额千元": v} for b, v in sorted_biz[:8]],
                ))

    # === 库存分析 ===

    def _analyze_inventory(self, result: DeepAnalysis):
        month = self.data.current_month
        prev = self.data.previous_month

        cur_aging = self._get_month_data(self.data.inventory_aging, month)
        pre_aging = self._get_month_data(self.data.inventory_aging, prev)

        if not cur_aging:
            return

        # 库龄结构
        total_value = sum(r.get("库存金额", 0) for r in cur_aging)
        aging_summary = []
        for r in cur_aging:
            pct = r.get("库存金额", 0) / total_value * 100 if total_value else 0
            aging_summary.append({
                "库龄段": r.get("库龄段", ""),
                "库存金额": r.get("库存金额", 0),
                "占比%": round(pct, 1),
            })

        # 60天以上库存预警
        old_stock = [r for r in cur_aging if r.get("库龄段") == "60天以上"]
        if old_stock and old_stock[0].get("库存金额", 0) > 0:
            old_pct = old_stock[0].get("库存金额", 0) / total_value * 100 if total_value else 0
            result.inventory_findings.append(AnalysisFinding(
                category="库存",
                title=f"60天以上滞销库存占比{old_pct:.1f}%",
                detail=f"滞销库存金额{old_stock[0].get('库存金额', 0):,.0f}元",
                severity="warning" if old_pct > 20 else "info",
                data=aging_summary,
            ))

        # 库存周转
        cur_turnover = self._get_month_data(self.data.inventory_turnover, month)
        if cur_turnover:
            days = cur_turnover[0].get("库存周转天数", 0)
            result.inventory_findings.append(AnalysisFinding(
                category="库存",
                title=f"库存周转天数：{days}天",
                detail=f"库存金额{cur_turnover[0].get('月库存金额', 0):,.0f}元，月销售成本{cur_turnover[0].get('月销售成本', 0):,.0f}元",
                severity="warning" if days and days > 30 else "info",
                data=cur_turnover,
            ))

    # === 渠道分析 ===

    def _analyze_channels(self, result: DeepAnalysis):
        month = self.data.current_month
        cur = self._get_month_data(self.data.sales_channel, month)

        if not cur:
            return

        # 按毛利率排序，找亏损渠道
        sorted_ch = sorted(cur, key=lambda x: x.get("毛利率", 0))
        loss_channels = [c for c in sorted_ch if c.get("毛利率", 0) < 0]
        if loss_channels:
            result.channel_findings.append(AnalysisFinding(
                category="渠道",
                title=f"亏损渠道：{len(loss_channels)}个",
                detail=f"毛利率最低的渠道为{loss_channels[0]['财务业务线']}，毛利率{loss_channels[0]['毛利率']:.1f}%",
                severity="warning",
                data=[{
                    "渠道": c["财务业务线"],
                    "毛利率%": c.get("毛利率", 0),
                    "销售收入": c.get("销售收入", 0),
                } for c in loss_channels[:5]],
            ))

        # 按收入排序，TOP5渠道
        top_channels = sorted(cur, key=lambda x: x.get("销售收入", 0), reverse=True)[:5]
        if top_channels:
            result.channel_findings.append(AnalysisFinding(
                category="渠道",
                title="TOP5销售渠道",
                detail=f"收入最高的渠道为{top_channels[0]['财务业务线']}，收入{top_channels[0]['销售收入']:,.0f}元",
                severity="info",
                data=top_channels,
            ))

        # 履约方式分析
        cur_fulfill = self._get_month_data(self.data.fulfillment, month)
        if cur_fulfill:
            result.channel_findings.append(AnalysisFinding(
                category="渠道",
                title="履约方式分布",
                detail="各履约方式的回收量和单均金额",
                severity="info",
                data=cur_fulfill,
            ))

    # === 核心发现生成 ===

    def _generate_key_findings(self, result: DeepAnalysis):
        findings = []

        # 从收入分析提取
        for f in result.revenue_findings:
            findings.append(f.title)

        # 从品类经营分析提取
        for f in result.category_findings:
            if f.severity in ("warning", "critical"):
                findings.append(f.title)

        # 从成本分析提取
        for f in result.cost_findings:
            if f.severity in ("warning", "critical"):
                findings.append(f.title)

        # 从库存分析提取
        for f in result.inventory_findings:
            if f.severity in ("warning", "critical"):
                findings.append(f.title)

        # 从渠道分析提取
        for f in result.channel_findings:
            if f.severity in ("warning", "critical"):
                findings.append(f.title)

        # 补充KPI变化
        cur = self.data.current_kpis
        pre = self.data.previous_kpis
        if cur and pre:
            rev_cur = cur.get("销售收入", 0)
            rev_pre = pre.get("销售收入", 0)
            if rev_pre:
                chg = self._pct_change(rev_cur, rev_pre)
                if chg is not None:
                    findings.append(f"销售收入环比{'增长' if chg > 0 else '下降'}{abs(chg):.1f}%")

            margin_cur = cur.get("毛利率", 0)
            margin_pre = pre.get("毛利率", 0)
            if margin_pre:
                m_chg = margin_cur - margin_pre
                if abs(m_chg) > 1:
                    findings.append(f"毛利率环比{'提升' if m_chg > 0 else '下降'}{abs(m_chg):.2f}个百分点")

        result.key_findings = findings[:8]

    # === 行动建议生成 ===

    def _generate_recommendations(self, result: DeepAnalysis):
        recs = []

        # 基于库存预警
        for f in result.inventory_findings:
            if f.severity == "warning":
                recs.append({
                    "priority": "高",
                    "area": "库存",
                    "action": f"关注{f.title}，建议加速滞销品清理或调整采购策略",
                })

        # 基于渠道亏损
        for f in result.channel_findings:
            if f.severity == "warning":
                recs.append({
                    "priority": "中",
                    "area": "渠道",
                    "action": f"{f.title}，建议评估亏损渠道的投入产出比",
                })

        # 基于品类毛利异常
        for f in result.category_findings:
            if f.severity == "warning":
                recs.append({
                    "priority": "高",
                    "area": "品类",
                    "action": f"{f.title}，建议复盘定价、补贴和回收结构，优先压降低毛利资源投入",
                })

        # 基于成本分析
        for f in result.cost_findings:
            if "人力成本" in f.title or "人员薪酬" in f.title:
                recs.append({
                    "priority": "中",
                    "area": "成本",
                    "action": f"关注{f.title}，建议review人力投入与业务增长的匹配度",
                })

        # 通用建议
        if not recs:
            recs.append({
                "priority": "低",
                "area": "经营",
                "action": "本月各项指标正常，建议持续关注库存周转和渠道盈利性",
            })

        result.recommendations = recs[:6]


def run_deep_analysis(data: ReportData) -> DeepAnalysis:
    analyzer = DeepAnalyzer(data)
    return analyzer.analyze()


if __name__ == "__main__":
    from report_data_collector import collect_report_data
    data = collect_report_data("2026-04")
    analysis = run_deep_analysis(data)
    print("=== 核心发现 ===")
    for f in analysis.key_findings:
        print(f"  - {f}")
    print("\n=== 行动建议 ===")
    for r in analysis.recommendations:
        print(f"  [{r['priority']}] {r['area']}: {r['action']}")
    print(f"\n收入发现: {len(analysis.revenue_findings)}")
    print(f"品类发现: {len(analysis.category_findings)}")
    print(f"成本发现: {len(analysis.cost_findings)}")
    print(f"库存发现: {len(analysis.inventory_findings)}")
    print(f"渠道发现: {len(analysis.channel_findings)}")
