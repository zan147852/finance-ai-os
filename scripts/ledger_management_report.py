import csv
import html
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import duckdb
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = PROJECT_ROOT / "data"
LEDGER_DIR = DATA_ROOT / "ledger"
DB_PATH = PROJECT_ROOT / "finance.db"
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "management_report"

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKGREL = "http://schemas.openxmlformats.org/package/2006/relationships"

OUTPUT_SHEET_NAME = "管理报表"
DETAIL_SHEET_NAME = "明细账"
SUBJECT_SHEET_NAME = "科目"
COST_CENTER_SHEET_NAME = "成本中心"
SETTLEMENT_SHEET_NAME = "结算及分摊数据"
MARKET_BEFORE_SHEET_NAME = "市场化前"

REPORT_RULE_SHEETS = {
    OUTPUT_SHEET_NAME,
    MARKET_BEFORE_SHEET_NAME,
    DETAIL_SHEET_NAME,
    SUBJECT_SHEET_NAME,
}

LEDGER_COLUMN_MAP = {
    "A": "subject_code",
    "B": "subject_name",
    "C": "period",
    "D": "cost_center_code",
    "E": "cost_center_name",
    "F": "app",
    "G": "city",
    "H": "business_line_1",
    "I": "business_line_2",
    "J": "personnel_type",
    "K": "expense_type",
    "L": "ledger_name",
    "M": "date_text",
    "N": "voucher_word",
    "O": "voucher_no",
    "P": "creator",
    "Q": "modifier",
    "R": "summary",
    "S": "amount",
    "T": "report_level1_code",
    "U": "report_level1_name",
    "V": "report_level2_code",
    "W": "report_level2_name",
    "X": "time_serial",
    "Y": "business",
    "Z": "attribute",
    "AA": "report_subject",
    "AB": "amount_k",
    "AC": "helper_col",
    "AD": "is_counted",
}


class LedgerImportError(Exception):
    pass


@dataclass(frozen=True)
class CellRecord:
    sheet_index: int
    sheet_name: str
    row_no: int
    col_no: int
    cell_ref: str
    value_text: str | None
    value_number: float | None
    formula: str | None
    style_id: str | None


@dataclass(frozen=True)
class SheetRecord:
    sheet_index: int
    sheet_name: str
    state: str
    dimension: str | None
    tab_color: str | None
    cells: list[CellRecord]
    merges: list[str]


@dataclass(frozen=True)
class WorkbookData:
    path: Path
    sheets: list[SheetRecord]
    external_links: list[str]


def q(tag: str) -> str:
    return f"{{{NS_MAIN}}}{tag}"


def col_to_num(col: str) -> int:
    num = 0
    for ch in col:
        num = num * 26 + ord(ch.upper()) - 64
    return num


def num_to_col(num: int) -> str:
    col = ""
    while num:
        num, rem = divmod(num - 1, 26)
        col = chr(65 + rem) + col
    return col


def cell_to_pos(cell_ref: str) -> tuple[int, int]:
    match = re.match(r"([A-Z]+)(\d+)", cell_ref or "")
    if not match:
        raise LedgerImportError(f"无法解析单元格地址：{cell_ref}")
    return int(match.group(2)), col_to_num(match.group(1))


def parse_dimension(dimension: str | None) -> tuple[int | None, int | None]:
    if not dimension:
        return None, None
    end_ref = dimension.split(":")[-1]
    try:
        return cell_to_pos(end_ref)
    except LedgerImportError:
        return None, None


def safe_number(value: str | None) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def target_to_path(target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    if not target.startswith("xl/"):
        return "xl/" + target
    return target


def load_xml(zip_file: zipfile.ZipFile, name: str) -> ET.Element:
    return ET.fromstring(zip_file.read(name))


def read_shared_strings(zip_file: zipfile.ZipFile) -> list[str]:
    try:
        root = load_xml(zip_file, "xl/sharedStrings.xml")
    except KeyError:
        return []
    strings: list[str] = []
    for item in root.findall(q("si")):
        strings.append("".join(node.text or "" for node in item.iter(q("t"))))
    return strings


def read_cell_value(cell_node: ET.Element, shared_strings: list[str]) -> str | None:
    cell_type = cell_node.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell_node.iter(q("t")))

    value_node = cell_node.find(q("v"))
    if value_node is None:
        return None

    value = value_node.text
    if value is None:
        return None
    if cell_type == "s":
        try:
            return shared_strings[int(value)]
        except (ValueError, IndexError):
            return value
    if cell_type == "b":
        return "TRUE" if value == "1" else "FALSE"
    return value


def discover_ledger_workbook(ledger_dir: Path = LEDGER_DIR) -> Path | None:
    if not ledger_dir.exists():
        return None

    workbooks = sorted(
        path
        for path in ledger_dir.glob("*.xlsx")
        if path.is_file() and not path.name.startswith("~$")
    )
    if not workbooks:
        return None
    if len(workbooks) > 1:
        names = ", ".join(path.name for path in workbooks)
        raise LedgerImportError(f"ledger 目录只能保留一个正式 xlsx 文件，当前发现：{names}")
    return workbooks[0]


def parse_xlsx_workbook(path: Path) -> WorkbookData:
    if not path.exists():
        raise LedgerImportError(f"文件不存在：{path}")

    sheets: list[SheetRecord] = []
    external_links: list[str] = []

    with zipfile.ZipFile(path) as zip_file:
        shared_strings = read_shared_strings(zip_file)
        workbook_root = load_xml(zip_file, "xl/workbook.xml")
        rels_root = load_xml(zip_file, "xl/_rels/workbook.xml.rels")
        rel_map = {
            rel.attrib["Id"]: target_to_path(rel.attrib["Target"])
            for rel in rels_root.findall(f"{{{NS_PKGREL}}}Relationship")
        }

        sheet_nodes = workbook_root.find(q("sheets"))
        if sheet_nodes is None:
            raise LedgerImportError(f"未找到工作表列表：{path.name}")

        for sheet_index, sheet_node in enumerate(sheet_nodes.findall(f"{q('sheet')}"), 1):
            sheet_name = sheet_node.attrib["name"]
            state = sheet_node.attrib.get("state", "visible")
            rel_id = sheet_node.attrib[f"{{{NS_REL}}}id"]
            sheet_path = rel_map[rel_id]
            sheet_root = load_xml(zip_file, sheet_path)

            dimension_node = sheet_root.find(q("dimension"))
            dimension = dimension_node.attrib.get("ref") if dimension_node is not None else None

            tab_color = None
            sheet_pr = sheet_root.find(q("sheetPr"))
            if sheet_pr is not None:
                tab_color_node = sheet_pr.find(q("tabColor"))
                if tab_color_node is not None:
                    tab_color = (
                        tab_color_node.attrib.get("rgb")
                        or tab_color_node.attrib.get("indexed")
                        or tab_color_node.attrib.get("theme")
                    )

            merges: list[str] = []
            merge_cells = sheet_root.find(q("mergeCells"))
            if merge_cells is not None:
                merges = [
                    merge_node.attrib["ref"]
                    for merge_node in merge_cells.findall(q("mergeCell"))
                    if merge_node.attrib.get("ref")
                ]

            cells: list[CellRecord] = []
            sheet_data = sheet_root.find(q("sheetData"))
            if sheet_data is not None:
                for row_node in sheet_data.findall(q("row")):
                    for cell_node in row_node.findall(q("c")):
                        cell_ref = cell_node.attrib.get("r")
                        if not cell_ref:
                            continue
                        row_no, col_no = cell_to_pos(cell_ref)
                        formula_node = cell_node.find(q("f"))
                        formula = None
                        if formula_node is not None:
                            formula = "=" + (formula_node.text or "")
                        value_text = read_cell_value(cell_node, shared_strings)
                        cells.append(
                            CellRecord(
                                sheet_index=sheet_index,
                                sheet_name=sheet_name,
                                row_no=row_no,
                                col_no=col_no,
                                cell_ref=cell_ref,
                                value_text=value_text,
                                value_number=safe_number(value_text),
                                formula=formula,
                                style_id=cell_node.attrib.get("s"),
                            )
                        )

            sheets.append(
                SheetRecord(
                    sheet_index=sheet_index,
                    sheet_name=sheet_name,
                    state=state,
                    dimension=dimension,
                    tab_color=tab_color,
                    cells=cells,
                    merges=merges,
                )
            )

        for part_name in zip_file.namelist():
            if part_name.startswith("xl/externalLinks/") or part_name.startswith("xl/connections"):
                external_links.append(part_name)

    required_sheets = {
        OUTPUT_SHEET_NAME,
        SETTLEMENT_SHEET_NAME,
        MARKET_BEFORE_SHEET_NAME,
        DETAIL_SHEET_NAME,
        SUBJECT_SHEET_NAME,
        COST_CENTER_SHEET_NAME,
    }
    actual_sheets = {sheet.sheet_name for sheet in sheets}
    missing = sorted(required_sheets - actual_sheets)
    if missing:
        raise LedgerImportError(f"明细账模板缺少必要 sheet：{', '.join(missing)}")

    return WorkbookData(path=path, sheets=sheets, external_links=external_links)


def cell_dict(sheet: SheetRecord) -> dict[tuple[int, int], CellRecord]:
    return {(cell.row_no, cell.col_no): cell for cell in sheet.cells}


def cell_text(cells: dict[tuple[int, int], CellRecord], row_no: int, col_no: int) -> str | None:
    cell = cells.get((row_no, col_no))
    return cell.value_text if cell else None


def cell_number(cells: dict[tuple[int, int], CellRecord], row_no: int, col_no: int) -> float | None:
    cell = cells.get((row_no, col_no))
    return cell.value_number if cell else None


def max_row(sheet: SheetRecord) -> int:
    dimension_row, _ = parse_dimension(sheet.dimension)
    actual_row = max((cell.row_no for cell in sheet.cells), default=0)
    if sheet.sheet_name == DETAIL_SHEET_NAME:
        return actual_row
    return max(dimension_row or 0, actual_row)


def max_col(sheet: SheetRecord) -> int:
    _, dimension_col = parse_dimension(sheet.dimension)
    actual_col = max((cell.col_no for cell in sheet.cells), default=0)
    return max(dimension_col or 0, actual_col)


def sheet_role(sheet: SheetRecord) -> str:
    if sheet.sheet_name == OUTPUT_SHEET_NAME:
        return "output"
    if sheet.tab_color and sheet.tab_color.upper() == "FFFF0000":
        return "output"
    if sheet.tab_color and sheet.tab_color.upper() == "FF00B050":
        return "dependency"
    return "dependency"


def formula_dependencies(formula: str | None, current_sheet: str) -> list[str]:
    if not formula:
        return []
    deps: set[str] = set()
    for match in re.finditer(r"(?:'([^']+)'|([^\s'!(),:+\-*/&=<>]+))!", formula):
        dep = (match.group(1) or match.group(2) or "").strip()
        if dep and dep != current_sheet:
            deps.add(dep)
    return sorted(deps)


def classify_formula(formula: str | None) -> str:
    if not formula:
        return "value"
    stripped = formula.strip()
    upper = stripped.upper()
    if stripped == "=":
        return "cached_fallback"
    if "XLOOKUP(" in upper:
        return "xlookup_join"
    if "VLOOKUP(" in upper:
        return "external_lookup_cached" if "[" in stripped else "lookup"
    if "[1]" in stripped or "#REF!" in upper:
        return "cached_fallback"
    if "FILTER(" in upper and "SUM(" in upper:
        return "filter_sum"
    if re.match(r"^=\+?SUM\(", stripped, re.IGNORECASE):
        return "sum_range"
    if re.match(r"^='?[^']+'?!\$?[A-Z]+\$?\d+$", stripped) or re.match(
        r"^=[^!]+!\$?[A-Z]+\$?\d+$", stripped
    ):
        return "direct_reference"
    if re.search(r"[\+\-\*/]", stripped[1:]):
        return "arithmetic"
    return "cached_fallback"


def formula_sql_template(formula: str | None) -> str | None:
    if not formula:
        return None
    rule_type = classify_formula(formula)
    if rule_type == "xlookup_join":
        if "成本中心!" in formula:
            return "通过 cost_center_code 关联 ledger_cost_center_mapping 补业务/属性"
        if "科目!" in formula:
            return "通过 report_level2_code 关联 ledger_subject_mapping 补管报科目"
    if rule_type == "filter_sum":
        sign = "-SUM" if "-SUM" in formula.upper() else "SUM"
        conditions = []
        for col, field_name in LEDGER_COLUMN_MAP.items():
            if f"明细账!${col}$" in formula:
                conditions.append(field_name)
        condition_sql = " AND ".join(f"{name} = :{name}" for name in dict.fromkeys(conditions) if name != "amount_k")
        if not condition_sql:
            condition_sql = "按公式条件筛选"
        prefix = "-SUM" if sign == "-SUM" else "SUM"
        return f"SELECT {prefix}(amount_k) FROM ledger_raw_detail WHERE {condition_sql}"
    if rule_type == "sum_range":
        return "按同一输出区域的行/列范围求和"
    if rule_type == "direct_reference":
        return "读取被引用 sheet 的同位置缓存值"
    if rule_type == "arithmetic":
        return "按公式引用的输出单元格做算术计算"
    return None


def create_tables(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS ledger_workbook_imports (
            import_id VARCHAR PRIMARY KEY,
            file_name VARCHAR,
            file_path VARCHAR,
            file_size BIGINT,
            file_mtime TIMESTAMP,
            imported_at TIMESTAMP,
            status VARCHAR,
            sheet_count INTEGER,
            external_links_json VARCHAR,
            output_dir VARCHAR,
            message VARCHAR
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS ledger_sheets (
            import_id VARCHAR,
            sheet_index INTEGER,
            sheet_name VARCHAR,
            sheet_role VARCHAR,
            state VARCHAR,
            dimension VARCHAR,
            tab_color VARCHAR,
            max_row INTEGER,
            max_col INTEGER,
            nonblank_cell_count INTEGER,
            formula_count INTEGER,
            merge_count INTEGER
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS ledger_sheet_cells (
            import_id VARCHAR,
            sheet_index INTEGER,
            sheet_name VARCHAR,
            row_no INTEGER,
            col_no INTEGER,
            cell_ref VARCHAR,
            value_text VARCHAR,
            value_number DOUBLE,
            formula VARCHAR,
            cached_text VARCHAR,
            cached_number DOUBLE,
            is_formula BOOLEAN,
            style_id VARCHAR
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS ledger_sheet_merges (
            import_id VARCHAR,
            sheet_name VARCHAR,
            merged_range VARCHAR
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS ledger_formula_dependencies (
            import_id VARCHAR,
            source_sheet VARCHAR,
            source_cell VARCHAR,
            target_sheet VARCHAR,
            formula VARCHAR
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS ledger_sheet_tables (
            import_id VARCHAR,
            sheet_name VARCHAR,
            source_row INTEGER,
            source_col INTEGER,
            column_name VARCHAR,
            value_text VARCHAR,
            value_number DOUBLE
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS ledger_raw_detail (
            import_id VARCHAR,
            source_row INTEGER,
            subject_code VARCHAR,
            subject_name VARCHAR,
            period VARCHAR,
            cost_center_code VARCHAR,
            cost_center_name VARCHAR,
            app VARCHAR,
            city VARCHAR,
            business_line_1 VARCHAR,
            business_line_2 VARCHAR,
            personnel_type VARCHAR,
            expense_type VARCHAR,
            ledger_name VARCHAR,
            date_text VARCHAR,
            voucher_word VARCHAR,
            voucher_no VARCHAR,
            creator VARCHAR,
            modifier VARCHAR,
            summary VARCHAR,
            amount DOUBLE,
            report_level1_code VARCHAR,
            report_level1_name VARCHAR,
            report_level2_code VARCHAR,
            report_level2_name VARCHAR,
            time_serial VARCHAR,
            business VARCHAR,
            attribute VARCHAR,
            report_subject VARCHAR,
            amount_k DOUBLE,
            helper_col VARCHAR,
            is_counted VARCHAR
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS ledger_subject_mapping (
            import_id VARCHAR,
            source_row INTEGER,
            report_level1_code VARCHAR,
            report_level1_name VARCHAR,
            report_level2_code VARCHAR,
            report_level2_name VARCHAR,
            report_subject VARCHAR,
            online_subject VARCHAR
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS ledger_cost_center_mapping (
            import_id VARCHAR,
            source_row INTEGER,
            cost_center_code VARCHAR,
            cost_center_name VARCHAR,
            expense_type VARCHAR,
            business VARCHAR,
            report_attribute VARCHAR,
            business_alias VARCHAR
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS ledger_settlement_allocation (
            import_id VARCHAR,
            source_row INTEGER,
            item_name VARCHAR,
            period_serial VARCHAR,
            value DOUBLE,
            value_text VARCHAR
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS management_report_template (
            import_id VARCHAR,
            row_no INTEGER,
            col_no INTEGER,
            cell_ref VARCHAR,
            row_group VARCHAR,
            row_label VARCHAR,
            metric_type VARCHAR,
            period_serial VARCHAR,
            value_text VARCHAR,
            value_number DOUBLE,
            formula VARCHAR
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS management_report_rules (
            import_id VARCHAR,
            sheet_name VARCHAR,
            cell_ref VARCHAR,
            rule_type VARCHAR,
            formula VARCHAR,
            cached_text VARCHAR,
            cached_number DOUBLE,
            dependencies_json VARCHAR,
            rule_sql VARCHAR
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS management_report_output (
            import_id VARCHAR,
            row_no INTEGER,
            item_group VARCHAR,
            item_name VARCHAR,
            metric_type VARCHAR,
            period_serial VARCHAR,
            value DOUBLE,
            value_text VARCHAR,
            source_rule VARCHAR,
            formula VARCHAR
        )
        """
    )


def bulk_insert_rows(
    con: duckdb.DuckDBPyConnection,
    table_name: str,
    columns: list[str],
    rows: list[list[Any]],
) -> None:
    if not rows:
        return
    view_name = f"_tmp_{table_name}"
    frame = pd.DataFrame(rows, columns=columns)
    con.register(view_name, frame)
    try:
        quoted_columns = ", ".join(f'"{column}"' for column in columns)
        con.execute(f"INSERT INTO {table_name} ({quoted_columns}) SELECT {quoted_columns} FROM {view_name}")
    finally:
        con.unregister(view_name)


def insert_base_workbook(
    con: duckdb.DuckDBPyConnection,
    import_id: str,
    workbook: WorkbookData,
    output_dir: Path,
) -> None:
    stat = workbook.path.stat()
    con.execute(
        """
        INSERT INTO ledger_workbook_imports
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            import_id,
            workbook.path.name,
            str(workbook.path),
            stat.st_size,
            datetime.fromtimestamp(stat.st_mtime),
            datetime.now(),
            "success",
            len(workbook.sheets),
            json.dumps(workbook.external_links, ensure_ascii=False),
            str(output_dir),
            "导入完成",
        ],
    )

    sheet_rows = []
    cell_rows = []
    merge_rows = []
    dependency_rows = []
    rule_rows = []

    for sheet in workbook.sheets:
        sheet_rows.append(
            [
                import_id,
                sheet.sheet_index,
                sheet.sheet_name,
                sheet_role(sheet),
                sheet.state,
                sheet.dimension,
                sheet.tab_color,
                max_row(sheet),
                max_col(sheet),
                len(sheet.cells),
                sum(1 for cell in sheet.cells if cell.formula),
                len(sheet.merges),
            ]
        )
        for merge_range in sheet.merges:
            merge_rows.append([import_id, sheet.sheet_name, merge_range])
        for cell in sheet.cells:
            is_formula = cell.formula is not None
            cell_rows.append(
                [
                    import_id,
                    cell.sheet_index,
                    cell.sheet_name,
                    cell.row_no,
                    cell.col_no,
                    cell.cell_ref,
                    cell.value_text,
                    cell.value_number,
                    cell.formula,
                    cell.value_text if is_formula else None,
                    cell.value_number if is_formula else None,
                    is_formula,
                    cell.style_id,
                ]
            )
            if cell.formula:
                deps = formula_dependencies(cell.formula, cell.sheet_name)
                for dep in deps:
                    dependency_rows.append(
                        [import_id, cell.sheet_name, cell.cell_ref, dep, cell.formula]
                    )
                if cell.sheet_name in REPORT_RULE_SHEETS:
                    rule_rows.append(
                        [
                            import_id,
                            cell.sheet_name,
                            cell.cell_ref,
                            classify_formula(cell.formula),
                            cell.formula,
                            cell.value_text,
                            cell.value_number,
                            json.dumps(deps, ensure_ascii=False),
                            formula_sql_template(cell.formula),
                        ]
                    )

    bulk_insert_rows(
        con,
        "ledger_sheets",
        [
            "import_id",
            "sheet_index",
            "sheet_name",
            "sheet_role",
            "state",
            "dimension",
            "tab_color",
            "max_row",
            "max_col",
            "nonblank_cell_count",
            "formula_count",
            "merge_count",
        ],
        sheet_rows,
    )
    bulk_insert_rows(
        con,
        "ledger_sheet_cells",
        [
            "import_id",
            "sheet_index",
            "sheet_name",
            "row_no",
            "col_no",
            "cell_ref",
            "value_text",
            "value_number",
            "formula",
            "cached_text",
            "cached_number",
            "is_formula",
            "style_id",
        ],
        cell_rows,
    )
    bulk_insert_rows(
        con,
        "ledger_sheet_merges",
        ["import_id", "sheet_name", "merged_range"],
        merge_rows,
    )
    bulk_insert_rows(
        con,
        "ledger_formula_dependencies",
        ["import_id", "source_sheet", "source_cell", "target_sheet", "formula"],
        dependency_rows,
    )
    bulk_insert_rows(
        con,
        "management_report_rules",
        [
            "import_id",
            "sheet_name",
            "cell_ref",
            "rule_type",
            "formula",
            "cached_text",
            "cached_number",
            "dependencies_json",
            "rule_sql",
        ],
        rule_rows,
    )


def insert_sheet_tables(
    con: duckdb.DuckDBPyConnection,
    import_id: str,
    workbook: WorkbookData,
) -> None:
    rows = []
    for sheet in workbook.sheets:
        if sheet.sheet_name == DETAIL_SHEET_NAME:
            header_row = 2
        else:
            header_row = 1
        cells = cell_dict(sheet)
        headers = {
            col_no: cell_text(cells, header_row, col_no)
            for col_no in range(1, max_col(sheet) + 1)
        }
        for cell in sheet.cells:
            if cell.row_no <= header_row:
                continue
            header = headers.get(cell.col_no) or f"列{num_to_col(cell.col_no)}"
            rows.append(
                [
                    import_id,
                    sheet.sheet_name,
                    cell.row_no,
                    cell.col_no,
                    header,
                    cell.value_text,
                    cell.value_number,
                ]
            )
    bulk_insert_rows(
        con,
        "ledger_sheet_tables",
        [
            "import_id",
            "sheet_name",
            "source_row",
            "source_col",
            "column_name",
            "value_text",
            "value_number",
        ],
        rows,
    )


def insert_normalized_tables(
    con: duckdb.DuckDBPyConnection,
    import_id: str,
    workbook: WorkbookData,
) -> None:
    sheet_map = {sheet.sheet_name: sheet for sheet in workbook.sheets}

    detail_sheet = sheet_map[DETAIL_SHEET_NAME]
    detail_cells = cell_dict(detail_sheet)
    detail_rows = []
    for row_no in range(3, max_row(detail_sheet) + 1):
        if not any(cell_text(detail_cells, row_no, col_no) for col_no in range(1, 31)):
            continue
        detail_rows.append(
            [
                import_id,
                row_no,
                cell_text(detail_cells, row_no, 1),
                cell_text(detail_cells, row_no, 2),
                cell_text(detail_cells, row_no, 3),
                cell_text(detail_cells, row_no, 4),
                cell_text(detail_cells, row_no, 5),
                cell_text(detail_cells, row_no, 6),
                cell_text(detail_cells, row_no, 7),
                cell_text(detail_cells, row_no, 8),
                cell_text(detail_cells, row_no, 9),
                cell_text(detail_cells, row_no, 10),
                cell_text(detail_cells, row_no, 11),
                cell_text(detail_cells, row_no, 12),
                cell_text(detail_cells, row_no, 13),
                cell_text(detail_cells, row_no, 14),
                cell_text(detail_cells, row_no, 15),
                cell_text(detail_cells, row_no, 16),
                cell_text(detail_cells, row_no, 17),
                cell_text(detail_cells, row_no, 18),
                cell_number(detail_cells, row_no, 19),
                cell_text(detail_cells, row_no, 20),
                cell_text(detail_cells, row_no, 21),
                cell_text(detail_cells, row_no, 22),
                cell_text(detail_cells, row_no, 23),
                cell_text(detail_cells, row_no, 24),
                cell_text(detail_cells, row_no, 25),
                cell_text(detail_cells, row_no, 26),
                cell_text(detail_cells, row_no, 27),
                cell_number(detail_cells, row_no, 28),
                cell_text(detail_cells, row_no, 29),
                cell_text(detail_cells, row_no, 30),
            ]
        )
    bulk_insert_rows(
        con,
        "ledger_raw_detail",
        [
            "import_id",
            "source_row",
            "subject_code",
            "subject_name",
            "period",
            "cost_center_code",
            "cost_center_name",
            "app",
            "city",
            "business_line_1",
            "business_line_2",
            "personnel_type",
            "expense_type",
            "ledger_name",
            "date_text",
            "voucher_word",
            "voucher_no",
            "creator",
            "modifier",
            "summary",
            "amount",
            "report_level1_code",
            "report_level1_name",
            "report_level2_code",
            "report_level2_name",
            "time_serial",
            "business",
            "attribute",
            "report_subject",
            "amount_k",
            "helper_col",
            "is_counted",
        ],
        detail_rows,
    )

    subject_sheet = sheet_map[SUBJECT_SHEET_NAME]
    subject_cells = cell_dict(subject_sheet)
    subject_rows = []
    for row_no in range(2, max_row(subject_sheet) + 1):
        if not cell_text(subject_cells, row_no, 3):
            continue
        subject_rows.append(
            [
                import_id,
                row_no,
                cell_text(subject_cells, row_no, 1),
                cell_text(subject_cells, row_no, 2),
                cell_text(subject_cells, row_no, 3),
                cell_text(subject_cells, row_no, 4),
                cell_text(subject_cells, row_no, 5),
                cell_text(subject_cells, row_no, 6),
            ]
        )
    bulk_insert_rows(
        con,
        "ledger_subject_mapping",
        [
            "import_id",
            "source_row",
            "report_level1_code",
            "report_level1_name",
            "report_level2_code",
            "report_level2_name",
            "report_subject",
            "online_subject",
        ],
        subject_rows,
    )

    cost_center_sheet = sheet_map[COST_CENTER_SHEET_NAME]
    cost_center_cells = cell_dict(cost_center_sheet)
    cost_center_rows = []
    for row_no in range(2, max_row(cost_center_sheet) + 1):
        if not cell_text(cost_center_cells, row_no, 1):
            continue
        cost_center_rows.append(
            [
                import_id,
                row_no,
                cell_text(cost_center_cells, row_no, 1),
                cell_text(cost_center_cells, row_no, 2),
                cell_text(cost_center_cells, row_no, 3),
                cell_text(cost_center_cells, row_no, 4),
                cell_text(cost_center_cells, row_no, 5),
                cell_text(cost_center_cells, row_no, 7),
            ]
        )
    bulk_insert_rows(
        con,
        "ledger_cost_center_mapping",
        [
            "import_id",
            "source_row",
            "cost_center_code",
            "cost_center_name",
            "expense_type",
            "business",
            "report_attribute",
            "business_alias",
        ],
        cost_center_rows,
    )

    settlement_sheet = sheet_map[SETTLEMENT_SHEET_NAME]
    settlement_cells = cell_dict(settlement_sheet)
    settlement_rows = []
    for row_no in range(2, max_row(settlement_sheet) + 1):
        item_name = cell_text(settlement_cells, row_no, 1)
        if not item_name:
            continue
        for col_no in range(2, max_col(settlement_sheet) + 1):
            period_serial = cell_text(settlement_cells, 1, col_no)
            if not period_serial:
                continue
            settlement_rows.append(
                [
                    import_id,
                    row_no,
                    item_name,
                    period_serial,
                    cell_number(settlement_cells, row_no, col_no),
                    cell_text(settlement_cells, row_no, col_no),
                ]
            )
    bulk_insert_rows(
        con,
        "ledger_settlement_allocation",
        ["import_id", "source_row", "item_name", "period_serial", "value", "value_text"],
        settlement_rows,
    )


def _looks_like_period_serial(value: str | None) -> bool:
    """判断值是否像 Excel 日期序列号（如 46023），而非 metric_type 标签（如 Act.）"""
    if not value:
        return False
    try:
        v = float(value)
        return 40000 < v < 50000
    except (ValueError, TypeError):
        return False


def insert_management_report(
    con: duckdb.DuckDBPyConnection,
    import_id: str,
    workbook: WorkbookData,
) -> list[list[Any]]:
    report_sheet = next(sheet for sheet in workbook.sheets if sheet.sheet_name == OUTPUT_SHEET_NAME)
    report_cells = cell_dict(report_sheet)
    template_rows = []
    output_rows = []
    table_values: list[list[Any]] = []
    rule_by_cell = {}
    for cell_ref, rule_type, formula in con.execute(
        """
        SELECT cell_ref, rule_type, formula
        FROM management_report_rules
        WHERE import_id = ? AND sheet_name = ?
        """,
        [import_id, OUTPUT_SHEET_NAME],
    ).fetchall():
        rule_by_cell[cell_ref] = (rule_type, formula)

    rows = max_row(report_sheet)
    cols = max_col(report_sheet)

    # 检测模板布局：新模板 Row 1 直接是 period_serial，无 metric_type 行
    row1_c = cell_text(report_cells, 1, 3)
    new_layout = row1_c is not None and _looks_like_period_serial(row1_c)
    # 旧布局: Row1=metric_type, Row2=period_serial, data>=Row3
    # 新布局: Row1=period_serial, data>=Row2
    data_start_row = 2 if new_layout else 3

    for row_no in range(1, rows + 1):
        table_row = []
        row_group = cell_text(report_cells, row_no, 1)
        row_label = cell_text(report_cells, row_no, 2)
        for col_no in range(1, cols + 1):
            cell = report_cells.get((row_no, col_no))
            value_text = cell.value_text if cell else None
            value_number = cell.value_number if cell else None
            formula = cell.formula if cell else None
            if new_layout:
                metric_type = "Act."
                period_serial = cell_text(report_cells, 1, col_no)
            else:
                metric_type = cell_text(report_cells, 1, col_no)
                period_serial = cell_text(report_cells, 2, col_no)
            template_rows.append(
                [
                    import_id,
                    row_no,
                    col_no,
                    f"{num_to_col(col_no)}{row_no}",
                    row_group,
                    row_label,
                    metric_type,
                    period_serial,
                    value_text,
                    value_number,
                    formula,
                ]
            )
            table_row.append(value_number if value_number is not None else value_text)

            if row_no >= data_start_row and col_no >= 3:
                rule_type, output_formula = rule_by_cell.get(
                    f"{num_to_col(col_no)}{row_no}", ("value", formula)
                )
                output_rows.append(
                    [
                        import_id,
                        row_no,
                        row_group,
                        row_label,
                        metric_type,
                        period_serial,
                        value_number,
                        value_text,
                        rule_type,
                        output_formula,
                    ]
                )
        table_values.append(table_row)

    bulk_insert_rows(
        con,
        "management_report_template",
        [
            "import_id",
            "row_no",
            "col_no",
            "cell_ref",
            "row_group",
            "row_label",
            "metric_type",
            "period_serial",
            "value_text",
            "value_number",
            "formula",
        ],
        template_rows,
    )
    bulk_insert_rows(
        con,
        "management_report_output",
        [
            "import_id",
            "row_no",
            "item_group",
            "item_name",
            "metric_type",
            "period_serial",
            "value",
            "value_text",
            "source_rule",
            "formula",
        ],
        output_rows,
    )
    return table_values


def create_latest_views(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE OR REPLACE VIEW v_management_report_latest AS
        SELECT t.*
        FROM management_report_template t
        WHERE t.import_id = (
            SELECT import_id
            FROM ledger_workbook_imports
            WHERE status = 'success'
            ORDER BY imported_at DESC
            LIMIT 1
        )
        """
    )
    con.execute(
        """
        CREATE OR REPLACE VIEW v_management_report_output_latest AS
        SELECT o.*
        FROM management_report_output o
        WHERE o.import_id = (
            SELECT import_id
            FROM ledger_workbook_imports
            WHERE status = 'success'
            ORDER BY imported_at DESC
            LIMIT 1
        )
        """
    )


def format_html_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if abs(value) >= 1000:
            return f"{value:,.2f}"
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def export_csv(output_dir: Path, table_values: list[list[Any]]) -> Path:
    csv_path = output_dir / "management_report.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerows(table_values)
    return csv_path


def export_xlsx(output_dir: Path, table_values: list[list[Any]]) -> Path | None:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
    except Exception:
        return None

    xlsx_path = output_dir / "management_report.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = OUTPUT_SHEET_NAME
    for row in table_values:
        sheet.append(row)

    header_fill = PatternFill("solid", fgColor="D9EAD3")
    title_fill = PatternFill("solid", fgColor="FCE4D6")
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.fill = title_fill
    for cell in sheet[2]:
        cell.font = Font(bold=True)
        cell.fill = header_fill
    for column_cells in sheet.columns:
        max_len = max(len(str(cell.value or "")) for cell in column_cells)
        sheet.column_dimensions[column_cells[0].column_letter].width = min(max(max_len + 2, 10), 28)
    workbook.save(xlsx_path)
    return xlsx_path


def export_html(
    output_dir: Path,
    import_id: str,
    workbook_path: Path,
    table_values: list[list[Any]],
    csv_path: Path,
    xlsx_path: Path | None,
) -> Path:
    html_path = output_dir / "management_report.html"
    header_periods = table_values[1] if len(table_values) > 1 else []
    column_controls = []
    for col_index in range(2, len(header_periods)):
        period = format_html_value(header_periods[col_index])
        metric = format_html_value(table_values[0][col_index] if table_values else "")
        label = f"{metric} {period}".strip()
        column_controls.append(
            f"""
            <label class="chip">
              <input type="checkbox" data-col="{col_index}" checked>
              <span>{html.escape(label)}</span>
            </label>
            """
        )

    table_rows = []
    for row_index, row in enumerate(table_values):
        tag = "th" if row_index < 2 else "td"
        cells_html = []
        for col_index, value in enumerate(row):
            classes = [f"col-{col_index}"]
            if row_index < 2:
                classes.append("header-cell")
            if col_index >= 2 and row_index >= 2:
                classes.append("number")
            class_text = " ".join(classes)
            cells_html.append(
                f"<{tag} class=\"{class_text}\">{html.escape(format_html_value(value))}</{tag}>"
            )
        table_rows.append(f"<tr>{''.join(cells_html)}</tr>")

    xlsx_link = (
        f'<a class="button" href="{html.escape(xlsx_path.name)}" download>下载 XLSX</a>'
        if xlsx_path
        else '<span class="button disabled">XLSX 未生成</span>'
    )
    html_doc = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>管理报表</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f8;
      --panel: #ffffff;
      --text: #1f2933;
      --muted: #667085;
      --line: #d9dee7;
      --accent: #0f766e;
      --accent-2: #8a5a12;
      --header: #eef6f4;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
      font-size: 14px;
    }}
    .topbar {{
      position: sticky;
      top: 0;
      z-index: 2;
      background: var(--panel);
      border-bottom: 1px solid var(--line);
      padding: 14px 20px;
    }}
    .title-row {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
    }}
    h1 {{
      margin: 0;
      font-size: 20px;
      letter-spacing: 0;
    }}
    .meta {{
      margin-top: 6px;
      color: var(--muted);
      font-size: 12px;
    }}
    .actions {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .button {{
      display: inline-flex;
      align-items: center;
      min-height: 32px;
      padding: 6px 10px;
      border: 1px solid var(--accent);
      color: var(--accent);
      background: #fff;
      text-decoration: none;
      border-radius: 6px;
      font-size: 13px;
    }}
    .button.disabled {{
      border-color: var(--line);
      color: var(--muted);
    }}
    .filters {{
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      padding: 12px 20px;
      background: #fbfcfd;
      border-bottom: 1px solid var(--line);
    }}
    .chip {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 5px 8px;
      border: 1px solid var(--line);
      background: #fff;
      border-radius: 6px;
      white-space: nowrap;
    }}
    .table-wrap {{
      padding: 16px 20px 28px;
      overflow: auto;
    }}
    table {{
      border-collapse: collapse;
      min-width: 760px;
      width: 100%;
      background: var(--panel);
      border: 1px solid var(--line);
    }}
    th, td {{
      border: 1px solid var(--line);
      padding: 7px 9px;
      min-width: 96px;
      max-width: 260px;
      vertical-align: middle;
      overflow-wrap: anywhere;
    }}
    th {{
      background: var(--header);
      font-weight: 700;
      text-align: left;
    }}
    tr:nth-child(1) th,
    tr:nth-child(2) th {{
      position: sticky;
      top: 0;
    }}
    .col-0, .col-1 {{
      min-width: 150px;
      text-align: left;
    }}
    .number {{
      text-align: right;
      font-variant-numeric: tabular-nums;
    }}
    .hidden-col {{
      display: none;
    }}
  </style>
</head>
<body>
  <header class="topbar">
    <div class="title-row">
      <h1>管理报表</h1>
      <div class="actions">
        <a class="button" href="{html.escape(csv_path.name)}" download>下载 CSV</a>
        {xlsx_link}
      </div>
    </div>
    <div class="meta">导入批次：{html.escape(import_id)} ｜ 来源：{html.escape(workbook_path.name)}</div>
  </header>
  <section class="filters" aria-label="列筛选">
    <strong>列口径</strong>
    {''.join(column_controls)}
  </section>
  <main class="table-wrap">
    <table>
      <tbody>
        {''.join(table_rows)}
      </tbody>
    </table>
  </main>
  <script>
    document.querySelectorAll('[data-col]').forEach((input) => {{
      input.addEventListener('change', () => {{
        const col = input.dataset.col;
        document.querySelectorAll('.col-' + col).forEach((cell) => {{
          cell.classList.toggle('hidden-col', !input.checked);
        }});
      }});
    }});
  </script>
</body>
</html>
"""
    html_path.write_text(html_doc, encoding="utf-8")
    return html_path


def export_report_files(
    import_id: str,
    workbook_path: Path,
    table_values: list[list[Any]],
    output_dir: Path = OUTPUT_DIR,
) -> dict[str, Path | None]:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = export_csv(output_dir, table_values)
    xlsx_path = export_xlsx(output_dir, table_values)
    html_path = export_html(output_dir, import_id, workbook_path, table_values, csv_path, xlsx_path)
    return {"html": html_path, "csv": csv_path, "xlsx": xlsx_path}


def import_ledger_management_report(
    con: duckdb.DuckDBPyConnection,
    ledger_dir: Path = LEDGER_DIR,
    output_dir: Path = OUTPUT_DIR,
) -> dict[str, Any] | None:
    workbook_path = discover_ledger_workbook(ledger_dir)
    if workbook_path is None:
        print(f"跳过 ledger 管理报表：目录无正式 xlsx 文件 {ledger_dir}")
        return None

    import_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    workbook = parse_xlsx_workbook(workbook_path)
    create_tables(con)

    con.execute("BEGIN TRANSACTION")
    try:
        insert_base_workbook(con, import_id, workbook, output_dir)
        insert_sheet_tables(con, import_id, workbook)
        insert_normalized_tables(con, import_id, workbook)
        table_values = insert_management_report(con, import_id, workbook)
        create_latest_views(con)
        con.execute("COMMIT")
    except Exception:
        try:
            con.execute("ROLLBACK")
        except Exception:
            pass
        raise

    exports = export_report_files(import_id, workbook_path, table_values, output_dir)
    con.execute(
        """
        UPDATE ledger_workbook_imports
        SET output_dir = ?
        WHERE import_id = ?
        """,
        [str(output_dir), import_id],
    )
    return {
        "import_id": import_id,
        "workbook": workbook_path,
        "sheet_count": len(workbook.sheets),
        "cell_count": sum(len(sheet.cells) for sheet in workbook.sheets),
        "html": exports["html"],
        "csv": exports["csv"],
        "xlsx": exports["xlsx"],
    }


def main() -> int:
    with duckdb.connect(str(DB_PATH)) as con:
        result = import_ledger_management_report(con)
    if result is None:
        return 0
    print(
        "ledger 管理报表导入完成："
        f"{result['sheet_count']} 个 sheet，{result['cell_count']} 个单元格，批次 {result['import_id']}"
    )
    print(f"HTML 输出：{result['html']}")
    print(f"CSV 输出：{result['csv']}")
    print(f"XLSX 输出：{result['xlsx']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except LedgerImportError as exc:
        print(f"ledger 管理报表导入失败：{exc}")
        raise SystemExit(1)
