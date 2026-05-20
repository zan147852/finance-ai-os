# ==============================================
# PDF 导出器
# 使用 Playwright + Chromium 渲染 HTML → PDF
# ==============================================

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def export_pdf(html_path: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = output_dir / html_path.name.replace(".html", ".pdf")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "Playwright 未安装。请运行:\n"
            "  pip install playwright\n"
            "  python -m playwright install chromium"
        )

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"file:///{html_path.resolve()}", wait_until="networkidle")
        page.pdf(
            path=str(pdf_path),
            format="A4",
            margin={"top": "20mm", "bottom": "20mm", "left": "22mm", "right": "22mm"},
            print_background=True,
        )
        browser.close()

    return pdf_path
