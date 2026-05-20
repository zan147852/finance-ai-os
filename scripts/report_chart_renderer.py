# ==============================================
# 图表渲染器
# matplotlib 生成内联 SVG 图表
# ==============================================

import io
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

# 中文字体配置
_FONT_CANDIDATES = ["Microsoft YaHei", "SimHei", "PingFang SC", "Noto Sans CJK SC"]
for _font in _FONT_CANDIDATES:
    if any(_font.lower() in f.name.lower() for f in fm.fontManager.ttflist):
        plt.rcParams["font.sans-serif"] = [_font] + plt.rcParams["font.sans-serif"]
        break
plt.rcParams["axes.unicode_minus"] = False

# 配色方案
COLORS = {
    "primary": "#0f766e",
    "secondary": "#8a5a12",
    "danger": "#dc2626",
    "warning": "#f59e0b",
    "success": "#16a34a",
    "muted": "#667085",
    "palette": ["#0f766e", "#dc2626", "#8a5a12", "#2563eb", "#9333ea",
                "#ea580c", "#0891b2", "#65a30d", "#be123c", "#7c3aed"],
}


def _fig_to_svg(fig) -> str:
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def _find_month(records, month):
    for r in records:
        if r.get("月份") == month:
            return r
    return None


def render_revenue_cost_trend(data) -> str:
    """收入与成本趋势折线图（千元）"""
    overview = data.monthly_overview
    if not overview:
        return ""

    months = [r["月份"] for r in overview]
    revenue = [r.get("销售收入", 0) for r in overview]
    cost = [r.get("商品成本", 0) for r in overview]

    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.plot(months, revenue, "o-", color=COLORS["primary"], linewidth=2, label="销售收入", markersize=4)
    ax.plot(months, cost, "s--", color=COLORS["danger"], linewidth=2, label="商品成本", markersize=4)
    ax.fill_between(months, revenue, cost, alpha=0.1, color=COLORS["primary"])
    ax.set_ylabel("金额（千元）")
    ax.set_title("收入与成本趋势", fontsize=14, fontweight="bold", pad=12)
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.3)
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    return _fig_to_svg(fig)


def render_margin_trend(data) -> str:
    """毛利率趋势图"""
    overview = data.monthly_overview
    if not overview:
        return ""

    months = [r["月份"] for r in overview]
    margins = [r.get("毛利率", 0) for r in overview]

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(months, margins, "o-", color=COLORS["primary"], linewidth=2.5, markersize=5)
    ax.axhline(y=0, color=COLORS["danger"], linestyle="--", alpha=0.5)
    ax.fill_between(months, margins, alpha=0.15, color=COLORS["primary"])
    ax.set_ylabel("毛利率（%）")
    ax.set_title("毛利率趋势", fontsize=14, fontweight="bold", pad=12)
    ax.grid(True, alpha=0.3)
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    return _fig_to_svg(fig)


def render_category_breakdown(data, month: str) -> str:
    """品类拆解横向条形图（千元）"""
    cats = [r for r in data.category_breakdown if r.get("月份") == month]
    if not cats:
        return ""

    cats_sorted = sorted(cats, key=lambda x: x.get("回收金额", 0), reverse=True)[:10]
    names = [r["品类"] for r in cats_sorted]
    values = [r.get("回收金额", 0) for r in cats_sorted]

    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.barh(names[::-1], values[::-1], color=COLORS["palette"][:len(names)])
    ax.set_xlabel("回收金额（千元）")
    ax.set_title("品类回收金额TOP10", fontsize=14, fontweight="bold", pad=12)
    for bar, val in zip(bars, values[::-1]):
        ax.text(bar.get_width() + max(values) * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{val:,.0f}", va="center", fontsize=9)
    fig.tight_layout()
    return _fig_to_svg(fig)


def render_category_margin(data, month: str) -> str:
    """品类毛利对比：销售收入/商品成本双柱 + 毛利率折线"""
    cats = [r for r in data.category_margin if r.get("月份") == month and (r.get("销售收入", 0) or 0) > 0]
    if not cats:
        return ""

    cats_sorted = sorted(cats, key=lambda x: x.get("销售收入", 0) or 0, reverse=True)[:10]
    names = [r["品类"] for r in cats_sorted]
    revenue = [r.get("销售收入", 0) or 0 for r in cats_sorted]
    cost = [r.get("商品成本", 0) or 0 for r in cats_sorted]
    margin = [r.get("毛利率", 0) or 0 for r in cats_sorted]
    x = list(range(len(names)))
    width = 0.36

    fig, ax1 = plt.subplots(figsize=(11, 5.5))
    ax2 = ax1.twinx()
    ax1.bar([i - width / 2 for i in x], revenue, width=width, color=COLORS["primary"], label="销售收入")
    ax1.bar([i + width / 2 for i in x], cost, width=width, color=COLORS["danger"], alpha=0.75, label="商品成本")
    ax2.plot(x, margin, "o-", color=COLORS["secondary"], linewidth=2, label="毛利率")
    ax2.axhline(y=0, color=COLORS["danger"], linestyle="--", alpha=0.35)
    ax1.set_ylabel("金额（千元）")
    ax2.set_ylabel("毛利率（%）")
    ax1.set_title("品类经营分析TOP10", fontsize=14, fontweight="bold", pad=12)
    ax1.set_xticks(x)
    ax1.set_xticklabels(names, rotation=35, ha="right")
    ax1.grid(True, axis="y", alpha=0.25)
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right")
    fig.tight_layout()
    return _fig_to_svg(fig)


def render_brand_breakdown(data, month: str) -> str:
    """品牌拆解横向条形图（千元）"""
    brands = [r for r in data.brand_breakdown if r.get("月份") == month]
    if not brands:
        return ""

    brands_sorted = sorted(brands, key=lambda x: x.get("回收金额", 0), reverse=True)[:10]
    names = [r["品牌"] for r in brands_sorted]
    values = [r.get("回收金额", 0) for r in brands_sorted]

    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.barh(names[::-1], values[::-1], color=COLORS["palette"][:len(names)])
    ax.set_xlabel("回收金额（千元）")
    ax.set_title("品牌回收金额TOP10", fontsize=14, fontweight="bold", pad=12)
    for bar, val in zip(bars, values[::-1]):
        ax.text(bar.get_width() + max(values) * 0.01, bar.get_y() + bar.get_height() / 2,
                f"{val:,.0f}", va="center", fontsize=9)
    fig.tight_layout()
    return _fig_to_svg(fig)


def render_channel_pie(data, month: str) -> str:
    """销售渠道收入占比饼图"""
    channels = [r for r in data.sales_channel if r.get("月份") == month]
    if not channels:
        return ""

    channels_sorted = sorted(channels, key=lambda x: x.get("销售收入", 0) or 0, reverse=True)
    # 过滤掉0值
    channels_sorted = [r for r in channels_sorted if (r.get("销售收入", 0) or 0) > 0]
    if not channels_sorted:
        return ""

    # 合并小渠道
    top = channels_sorted[:7]
    other_val = sum(r.get("销售收入", 0) or 0 for r in channels_sorted[7:])
    if other_val > 0:
        top.append({"财务业务线": "其他", "销售收入": other_val})

    labels = [r["财务业务线"] for r in top]
    values = [(r.get("销售收入", 0) or 0) for r in top]

    # 过滤NaN/负值
    valid = [(l, v) for l, v in zip(labels, values) if v > 0]
    if not valid:
        return ""
    labels, values = zip(*valid)

    fig, ax = plt.subplots(figsize=(8, 6))
    wedges, texts, autotexts = ax.pie(
        values, labels=labels, autopct=lambda p: f"{p:.1f}%" if p > 3 else "",
        colors=COLORS["palette"][:len(labels)], startangle=90,
        textprops={"fontsize": 9},
    )
    ax.set_title("销售收入渠道占比", fontsize=14, fontweight="bold", pad=12)
    fig.tight_layout()
    return _fig_to_svg(fig)


def render_inventory_aging(data, month: str) -> str:
    """库龄分布堆叠条形图"""
    aging = [r for r in data.inventory_aging if r.get("月份") == month]
    if not aging:
        return ""

    order = ["0-7天", "8-14天", "15-30天", "31-60天", "60天以上"]
    aging_map = {r["库龄段"]: r for r in aging}
    values = [aging_map.get(seg, {}).get("库存金额", 0) for seg in order]
    colors = ["#16a34a", "#22c55e", "#f59e0b", "#ea580c", "#dc2626"]

    fig, ax = plt.subplots(figsize=(10, 4))
    left = 0
    for i, (seg, val) in enumerate(zip(order, values)):
        ax.barh("库存金额", val, left=left, color=colors[i], label=f"{seg} ({val:,.0f}千)")
        if val > max(values) * 0.08:
            ax.text(left + val / 2, 0, f"{seg}", ha="center", va="center", fontsize=8, color="white", fontweight="bold")
        left += val
    ax.set_xlabel("库存金额（千元）")
    ax.set_title("库龄分布", fontsize=14, fontweight="bold", pad=12)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.15), ncol=3, fontsize=9)
    ax.set_xlim(0, left * 1.05)
    fig.tight_layout()
    return _fig_to_svg(fig)


def render_cost_structure(data) -> str:
    """成本结构饼图（按一级分类）"""
    if not data.cost_by_level1:
        return ""

    items = sorted(data.cost_by_level1, key=lambda x: abs(x.get("total_k", 0)), reverse=True)
    items = [r for r in items if abs(r.get("total_k", 0)) > 0]
    if not items:
        return ""

    top = items[:8]
    other_val = sum(abs(r.get("total_k", 0)) for r in items[8:])
    if other_val > 0:
        top.append({"report_level1_name": "其他", "total_k": other_val})

    labels = [r["report_level1_name"] for r in top]
    values = [abs(r.get("total_k", 0)) for r in top]

    fig, ax = plt.subplots(figsize=(8, 6))
    wedges, texts, autotexts = ax.pie(
        values, labels=labels, autopct=lambda p: f"{p:.1f}%" if p > 3 else "",
        colors=COLORS["palette"][:len(labels)], startangle=90,
        textprops={"fontsize": 9},
    )
    ax.set_title("成本结构分布（千元）", fontsize=14, fontweight="bold", pad=12)
    fig.tight_layout()
    return _fig_to_svg(fig)


def render_inventory_turnover(data) -> str:
    """库存周转天数趋势"""
    turnover = data.inventory_turnover
    if not turnover:
        return ""

    months = [r["月份"] for r in turnover]
    days = [r.get("库存周转天数", 0) for r in turnover]

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(months, days, "o-", color=COLORS["secondary"], linewidth=2, markersize=5)
    ax.axhline(y=30, color=COLORS["danger"], linestyle="--", alpha=0.5, label="30天警戒线")
    ax.fill_between(months, days, alpha=0.15, color=COLORS["secondary"])
    ax.set_ylabel("周转天数")
    ax.set_title("库存周转天数趋势", fontsize=14, fontweight="bold", pad=12)
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    return _fig_to_svg(fig)


def render_cross_table(data) -> str:
    """回收-销售转化率趋势"""
    cross = data.cross_table
    if not cross:
        return ""

    months = [r["月份"] for r in cross]
    qty_rate = [r.get("回收销售转化率", 0) for r in cross]
    amt_rate = [r.get("金额转化率", 0) for r in cross]

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(months, qty_rate, "o-", color=COLORS["primary"], linewidth=2, label="数量转化率")
    ax.plot(months, amt_rate, "s--", color=COLORS["secondary"], linewidth=2, label="金额转化率")
    ax.set_ylabel("转化率（%）")
    ax.set_title("回收→销售转化率趋势", fontsize=14, fontweight="bold", pad=12)
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    return _fig_to_svg(fig)


def render_all_charts(data, month: str) -> dict[str, str]:
    """渲染所有图表，返回 {chart_name: svg_string}"""
    chart_jobs = {
        "revenue_cost_trend": lambda: render_revenue_cost_trend(data),
        "margin_trend": lambda: render_margin_trend(data),
        "category_breakdown": lambda: render_category_breakdown(data, month),
        "category_margin": lambda: render_category_margin(data, month),
        "brand_breakdown": lambda: render_brand_breakdown(data, month),
        "channel_pie": lambda: render_channel_pie(data, month),
        "inventory_aging": lambda: render_inventory_aging(data, month),
        "cost_structure": lambda: render_cost_structure(data),
        "inventory_turnover": lambda: render_inventory_turnover(data),
        "cross_table": lambda: render_cross_table(data),
    }
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {name: pool.submit(job) for name, job in chart_jobs.items()}
            return {name: future.result() for name, future in futures.items()}
    except Exception:
        return {name: job() for name, job in chart_jobs.items()}
