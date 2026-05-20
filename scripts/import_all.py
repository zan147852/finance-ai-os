import re
import sys
from pathlib import Path

import duckdb

from ledger_management_report import import_ledger_management_report

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = PROJECT_ROOT / "data"
DB_PATH = PROJECT_ROOT / "finance.db"

# 配置：数据类型 -> 子目录名、目标表名
DATA_TYPES = {
    "recycle": {"dir": "recycle", "table": "recycle_detail"},
    "sales": {"dir": "sales", "table": "sales_detail"},
    "inventory": {"dir": "inventory", "table": "inventory_detail"},
}

CSV_COLUMN_TYPES = {
    "recycle": {"回收单id": "VARCHAR", "业务线id": "VARCHAR"},
    "sales": {
        "销售子单号": "VARCHAR",
        "质检码": "VARCHAR",
        "来源单号": "VARCHAR",
        "销售门店ID": "VARCHAR",
        "买家UID": "VARCHAR",
        "卖家UID": "VARCHAR",
    },
    "inventory": {"回收单id": "VARCHAR", "商品id": "VARCHAR"},
}

MONTH_RE = re.compile(r"(\d{2})年(\d{1,2})月")


class ImportErrorWithContext(Exception):
    pass


def parse_month(file_path: Path) -> str:
    match = MONTH_RE.search(file_path.stem)
    if not match:
        raise ImportErrorWithContext(f"无法从文件名识别月份：{file_path.name}")
    return f"20{match.group(1)}-{int(match.group(2)):02d}"


def collect_files(folder: Path) -> list[Path]:
    patterns = ("*.xlsx", "*.xls", "*.csv")
    files: list[Path] = []
    for pattern in patterns:
        files.extend(folder.glob(pattern))
    return sorted(files)


def discover_data_type(dtype: str, folder: Path) -> list[Path]:
    if not folder.exists():
        print(f"跳过 {dtype}：目录不存在 {folder}")
        return []

    files = collect_files(folder)
    if not files:
        print(f"跳过 {dtype}：无文件")
        return []

    for file_path in files:
        try:
            parse_month(file_path)
        except ImportErrorWithContext as exc:
            raise ImportErrorWithContext(f"{dtype} 导入中止：{exc}") from exc

    return files


def source_relation_sql(dtype: str, file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        type_overrides = CSV_COLUMN_TYPES.get(dtype, {})
        if type_overrides:
            types_sql = ", ".join(f"'{name}': '{type_name}'" for name, type_name in type_overrides.items())
            return (
                "read_csv_auto(?, header=true, union_by_name=true, nullstr=['null', ''], "
                f"sample_size=-1, types={{{types_sql}}})"
            )
        return "read_csv_auto(?, header=true, union_by_name=true, nullstr=['null', ''], sample_size=-1)"
    if suffix in {".xlsx", ".xls"}:
        return "read_excel(?)"
    raise ImportErrorWithContext(f"不支持的文件类型：{file_path.name}")


def create_file_table(
    con: duckdb.DuckDBPyConnection,
    dtype: str,
    target_table: str,
    file_path: Path,
    replace: bool,
) -> int:
    month = parse_month(file_path)
    relation_sql = source_relation_sql(dtype, file_path)

    select_sql = f"""
        SELECT
            *,
            ? AS 数据月份,
            ? AS 月份
        FROM {relation_sql}
    """
    if replace:
        sql = f"CREATE OR REPLACE TABLE {target_table} AS {select_sql}"
    else:
        sql = f"INSERT INTO {target_table} BY NAME {select_sql}"
    params = [file_path.stem, month, str(file_path)]
    try:
        con.execute(sql, params)
    except Exception as exc:
        raise ImportErrorWithContext(f"读取失败：{file_path.name}，原因：{exc}") from exc

    row_count = con.execute(f"SELECT COUNT(*) FROM {target_table}").fetchone()[0]
    if row_count == 0:
        raise ImportErrorWithContext(f"文件没有数据行：{file_path.name}")
    return row_count


def replace_table(con: duckdb.DuckDBPyConnection, dtype: str, table_name: str, files: list[Path]) -> int:
    temp_table = f"tmp_import_{table_name}"
    try:
        con.execute(f"DROP TABLE IF EXISTS {temp_table}")
        for index, file_path in enumerate(files, 1):
            print(f"  [{table_name}] 导入 {index}/{len(files)}：{file_path.name}", flush=True)
            create_file_table(con, dtype, temp_table, file_path, replace=index == 1)

        total_rows = con.execute(f"SELECT COUNT(*) FROM {temp_table}").fetchone()[0]
        con.execute("BEGIN TRANSACTION")
        con.execute(f"DROP TABLE IF EXISTS {table_name}")
        con.execute(f"ALTER TABLE {temp_table} RENAME TO {table_name}")
        con.execute("COMMIT")
        return total_rows
    except Exception:
        try:
            con.execute("ROLLBACK")
        except Exception:
            pass
        con.execute(f"DROP TABLE IF EXISTS {temp_table}")
        raise


def import_all() -> int:
    print(f"数据根目录：{DATA_ROOT}")
    print(f"数据库文件：{DB_PATH}")

    con = duckdb.connect(str(DB_PATH))
    try:
        for dtype, cfg in DATA_TYPES.items():
            folder = DATA_ROOT / cfg["dir"]
            table_name = cfg["table"]

            files = discover_data_type(dtype, folder)
            if not files:
                continue

            total_rows = replace_table(con, dtype, table_name, files)
            print(f"{dtype} 导入完成：{len(files)} 个文件，{total_rows} 行 -> 表 {table_name}")

        ledger_result = import_ledger_management_report(con)
        if ledger_result:
            print(
                "ledger 管理报表导入完成："
                f"{ledger_result['sheet_count']} 个 sheet，"
                f"{ledger_result['cell_count']} 个单元格 -> "
                f"{ledger_result['html']}"
            )
    finally:
        con.close()

    print("全部数据导入完成")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(import_all())
    except ImportErrorWithContext as exc:
        print(f"导入失败：{exc}", file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        print(f"导入失败：未预期错误：{exc}", file=sys.stderr)
        raise SystemExit(1)
