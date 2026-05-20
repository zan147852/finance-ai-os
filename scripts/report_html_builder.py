# ==============================================
# HTML 报告构建器
# 加载 Jinja2 模板，注入数据+图表
# ==============================================

import sys
import json
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jinja2 import Environment, FileSystemLoader

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = PROJECT_ROOT / "rules" / "report_profiles.json"
DEFAULT_SECTIONS = ["summary", "revenue", "category_margin", "cost", "pnl", "inventory", "channels", "risk", "actions"]
TEMPLATE_SECTION_ORDER = ["summary", "revenue", "category_margin", "cost", "pnl", "inventory", "channels", "risk", "actions"]
CN_NUMBERS = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]


def load_report_profile(profile: str = "full") -> dict:
    config = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    default_profile = config.get("default_profile", "full")
    profile_id = profile or default_profile
    profiles = config.get("profiles", {})
    if profile_id not in profiles:
        raise ValueError(f"Unknown report profile: {profile_id}")
    profile_info = dict(profiles[profile_id])
    profile_info["id"] = profile_id
    return profile_info


def _section_numbers(sections: list[str]) -> dict[str, str]:
    rendered_sections = [section for section in TEMPLATE_SECTION_ORDER if section in sections]
    return {
        section: CN_NUMBERS[idx] if idx < len(CN_NUMBERS) else str(idx + 1)
        for idx, section in enumerate(rendered_sections)
    }


def build_report_html(data, charts, analysis, sections=None, profile_info=None) -> str:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("formal_report.html.j2")

    # 读取 CSS
    css_path = TEMPLATES_DIR / "report_style.css"
    css_content = css_path.read_text(encoding="utf-8")

    # 月份标签
    y, m = data.current_month.split("-")
    month_label = f"{y}年{int(m)}月"
    sections = list(sections or DEFAULT_SECTIONS)
    section_numbers = _section_numbers(sections)

    # KPI 变化
    cur = data.current_kpis
    pre = data.previous_kpis
    kpi_changes = {"revenue_pct": None, "margin_change": None, "recycle_pct": None}

    if cur and pre:
        rev_cur = cur.get("销售收入", 0)
        rev_pre = pre.get("销售收入", 0)
        if rev_pre:
            kpi_changes["revenue_pct"] = round((rev_cur - rev_pre) / abs(rev_pre) * 100, 1)

        m_cur = cur.get("毛利率", 0)
        m_pre = pre.get("毛利率", 0)
        kpi_changes["margin_change"] = round(m_cur - m_pre, 2)

        r_cur = cur.get("回收量", 0)
        r_pre = pre.get("回收量", 0)
        if r_pre:
            kpi_changes["recycle_pct"] = round((r_cur - r_pre) / abs(r_pre) * 100, 1)

    html = template.render(
        month=data.current_month,
        month_label=month_label,
        gen_date=date.today().isoformat(),
        css_content=css_content,
        kpis=cur,
        kpi_changes=kpi_changes,
        charts=charts,
        analysis=analysis,
        sections=sections,
        section_numbers=section_numbers,
        profile_info=profile_info or {},
        pnl_items=data.pnl_items,
        pnl_period_serial=data.pnl_period_serial,
        pnl_period_label=data.pnl_period_label,
    )
    return html


def save_html(html_content: str, month: str, output_dir: Path, profile: str = "full") -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = "" if profile == "full" else f"_{profile}"
    out_path = output_dir / f"{month}{suffix}_formal_report.html"
    out_path.write_text(html_content, encoding="utf-8")
    return out_path
