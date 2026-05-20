# ==============================================
# 正式财务报告生成器 — 主入口
# 用法: python scripts/generate_formal_report.py --month 2026-04 --format both
# ==============================================

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from report_data_collector import collect_report_data
from report_deep_analyzer import run_deep_analysis
from report_chart_renderer import render_all_charts
from report_html_builder import build_report_html, load_report_profile, save_html

try:
    from report_pdf_exporter import export_pdf
except Exception:
    export_pdf = None


def run_report(month: str, fmt: str = "both", output_dir: str = None, profile: str = "full") -> dict:
    """生成正式报告，返回输出文件路径"""
    if output_dir is None:
        output_dir = Path(__file__).resolve().parents[1] / "outputs" / "formal_report"
    else:
        output_dir = Path(output_dir)
    profile_info = load_report_profile(profile)
    sections = profile_info.get("sections", [])

    # 1. 采集数据
    print(f"[1/5] 采集 {month} 数据...", file=sys.stderr)
    data = collect_report_data(month)

    # 2-3. 深度分析 + 图表渲染
    print("[2/5] 运行深度分析与图表渲染...", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=2) as pool:
        analysis_future = pool.submit(run_deep_analysis, data)
        charts_future = pool.submit(render_all_charts, data, month)
        analysis = analysis_future.result()
        charts = charts_future.result()

    # 4. 构建 HTML
    print("[4/5] 构建 HTML...", file=sys.stderr)
    html_content = build_report_html(data, charts, analysis, sections=sections, profile_info=profile_info)
    html_path = save_html(html_content, month, output_dir, profile=profile_info["id"])
    print(f"  HTML: {html_path}", file=sys.stderr)

    result = {"html": str(html_path), "month": month, "profile": profile_info["id"]}

    # 5. 导出 PDF（如需要）
    if fmt in ("pdf", "both"):
        print("[5/5] 导出 PDF...", file=sys.stderr)
        try:
            pdf_path = export_pdf(html_path, output_dir)
            result["pdf"] = str(pdf_path)
            print(f"  PDF: {pdf_path}", file=sys.stderr)
        except Exception as e:
            result["pdf_error"] = str(e)
            print(f"  PDF 导出失败: {e}", file=sys.stderr)
    else:
        print("[5/5] 跳过 PDF 导出", file=sys.stderr)

    print("完成！", file=sys.stderr)
    return result


def main():
    parser = argparse.ArgumentParser(description="生成正式财务分析月报")
    parser.add_argument("--month", required=True, help="报告期月份，如 2026-04")
    parser.add_argument("--format", default="both", choices=["html", "pdf", "both"],
                        help="输出格式 (default: both)")
    parser.add_argument("--output-dir", default=None, help="输出目录")
    parser.add_argument("--profile", default="full", help="报告版本: full/ceo/category_manager/channel_manager")
    args = parser.parse_args()

    result = run_report(args.month, args.format, args.output_dir, args.profile)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
