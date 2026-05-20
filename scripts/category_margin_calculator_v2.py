#!/usr/bin/env python3
"""
每月品类毛利率计算脚本
Finance AI OS - trace_id: 20260514-005

用法：
    python category_margin_calculator.py --source csv --input data.csv
    python category_margin_calculator.py --source api --endpoint /api/category_sales
    python category_margin_calculator.py --source db --query "SELECT ..."
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime


# ============================================================
# 数据加载器
# ============================================================

def load_from_csv(filepath: str) -> list[dict]:
    """从CSV文件加载数据"""
    import csv
    data = []
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            data.append(row)
    return data


def load_from_json(filepath: str) -> list[dict]:
    """从JSON文件加载数据"""
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_from_api(endpoint: str) -> list[dict]:
    """从API加载数据（示例）"""
    # TODO: 实现实际的API调用
    # import requests
    # response = requests.get(endpoint)
    # return response.json()
    raise NotImplementedError("API数据源尚未实现")


def load_from_db(query: str) -> list[dict]:
    """从数据库加载数据（示例）"""
    # TODO: 实现实际的数据库查询
    # import duckdb
    # conn = duckdb.connect()
    # return conn.execute(query).fetchdf().to_dict('records')
    raise NotImplementedError("数据库数据源尚未实现")


# ============================================================
# 数据标准化
# ============================================================

def normalize_data(raw_data: list[dict]) -> list[dict]:
    """
    标准化数据格式
    
    输入格式（自动识别）：
    - 格式A: 月份, 品类, 回收量, 回收金额, 销售额, 销售成本
    - 格式B: month, category, recycling_qty, recycling_amount, sales_amount, cost_amount
    
    输出格式：
    - 月份, 品类, 回收量, 回收金额, 销售额, 销售成本, 毛利, 毛利率
    """
    
    # 字段映射
    field_mapping = {
        '月份': ['月份', 'month', 'sale_date', '日期'],
        '品类': ['品类', 'category', 'product_category', '产品类别'],
        '回收量': ['回收量', 'recycling_qty', 'recycle_quantity'],
        '回收金额': ['回收金额', 'recycling_amount', 'recycle_amount'],
        '销售额': ['销售额', 'sales_amount', 'sale_amount', 'revenue'],
        '销售成本': ['销售成本', 'cost_amount', 'cost', 'cogs'],
    }
    
    # 自动检测字段名
    def find_field(row, candidates):
        for candidate in candidates:
            if candidate in row:
                return candidate
        return None
    
    normalized = []
    for row in raw_data:
        # 查找实际字段名
        month_field = find_field(row, field_mapping['月份'])
        category_field = find_field(row, field_mapping['品类'])
        recycling_qty_field = find_field(row, field_mapping['回收量'])
        recycling_amount_field = find_field(row, field_mapping['回收金额'])
        sales_amount_field = find_field(row, field_mapping['销售额'])
        cost_amount_field = find_field(row, field_mapping['销售成本'])
        
        # 检查必需字段
        if not all([month_field, category_field, sales_amount_field, cost_amount_field]):
            print(f"警告：跳过不完整的行: {row}")
            continue
        
        # 提取数据
        month = row[month_field]
        category = row[category_field]
        sales_amount = float(row[sales_amount_field])
        cost_amount = float(row[cost_amount_field])
        
        # 可选字段
        recycling_qty = float(row[recycling_qty_field]) if recycling_qty_field and row.get(recycling_qty_field) else 0
        recycling_amount = float(row[recycling_amount_field]) if recycling_amount_field and row.get(recycling_amount_field) else 0
        
        # 计算毛利和毛利率
        profit = sales_amount - cost_amount
        margin = (profit / sales_amount * 100) if sales_amount > 0 else 0
        
        normalized.append({
            '月份': month,
            '品类': category,
            '回收量': recycling_qty,
            '回收金额': recycling_amount,
            '销售额': sales_amount,
            '销售成本': cost_amount,
            '毛利': profit,
            '毛利率': round(margin, 2),
        })
    
    return normalized


# ============================================================
# 毛利率计算
# ============================================================

def calculate_monthly_category_margin(data: list[dict]) -> dict:
    """
    计算每月品类毛利率
    
    返回：
    {
        'monthly': {月份: [品类数据]},
        'category_summary': {品类: 汇总数据},
        'month_summary': {月份: 汇总数据}
    }
    """
    
    # 按月份分组
    monthly = defaultdict(list)
    for item in data:
        monthly[item['月份']].append(item)
    
    # 按品类汇总
    category_summary = defaultdict(lambda: {
        '回收量': 0, '回收金额': 0, '销售额': 0, '销售成本': 0, '毛利': 0
    })
    for item in data:
        cat = item['品类']
        category_summary[cat]['回收量'] += item['回收量']
        category_summary[cat]['回收金额'] += item['回收金额']
        category_summary[cat]['销售额'] += item['销售额']
        category_summary[cat]['销售成本'] += item['销售成本']
        category_summary[cat]['毛利'] += item['毛利']
    
    # 计算品类汇总毛利率
    for cat, summary in category_summary.items():
        summary['毛利率'] = round(
            (summary['毛利'] / summary['销售额'] * 100) if summary['销售额'] > 0 else 0, 2
        )
    
    # 按月份汇总
    month_summary = defaultdict(lambda: {
        '回收量': 0, '回收金额': 0, '销售额': 0, '销售成本': 0, '毛利': 0
    })
    for item in data:
        month = item['月份']
        month_summary[month]['回收量'] += item['回收量']
        month_summary[month]['回收金额'] += item['回收金额']
        month_summary[month]['销售额'] += item['销售额']
        month_summary[month]['销售成本'] += item['销售成本']
        month_summary[month]['毛利'] += item['毛利']
    
    # 计算月份汇总毛利率
    for month, summary in month_summary.items():
        summary['毛利率'] = round(
            (summary['毛利'] / summary['销售额'] * 100) if summary['销售额'] > 0 else 0, 2
        )
    
    return {
        'monthly': dict(monthly),
        'category_summary': dict(category_summary),
        'month_summary': dict(month_summary)
    }


# ============================================================
# 报表输出
# ============================================================

def print_monthly_report(results: dict):
    """打印每月品类毛利率报表"""
    
    monthly = results['monthly']
    month_summary = results['month_summary']
    
    print("=" * 100)
    print("每月品类毛利率报表")
    print(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 100)
    
    # 按月份排序
    sorted_months = sorted(monthly.keys())
    
    for month in sorted_months:
        items = monthly[month]
        summary = month_summary[month]
        
        # 按销售额排序
        items.sort(key=lambda x: x['销售额'], reverse=True)
        
        print(f"\n【{month}】整体毛利率: {summary['毛利率']}%")
        print("-" * 100)
        print(f"{'品类':<15} {'回收量':>10} {'回收金额':>15} {'销售额':>15} {'销售成本':>15} {'毛利':>15} {'毛利率':>8}")
        print("-" * 100)
        
        for item in items:
            print(f"{item['品类']:<15} {item['回收量']:>10,.0f} {item['回收金额']:>15,.0f} "
                  f"{item['销售额']:>15,.0f} {item['销售成本']:>15,.0f} {item['毛利']:>15,.0f} {item['毛利率']:>7.2f}%")
        
        print("-" * 100)
        print(f"{'合计':<15} {'':>10} {'':>15} {summary['销售额']:>15,.0f} {summary['销售成本']:>15,.0f} "
              f"{summary['毛利']:>15,.0f} {summary['毛利率']:>7.2f}%")
    
    print("\n" + "=" * 100)


def print_category_summary(results: dict):
    """打印品类汇总报表"""
    
    category_summary = results['category_summary']
    
    print("\n" + "=" * 100)
    print("品类汇总报表（Q1）")
    print("=" * 100)
    
    # 转换为列表并排序
    summary_list = [
        {'品类': cat, **data}
        for cat, data in category_summary.items()
    ]
    summary_list.sort(key=lambda x: x['销售额'], reverse=True)
    
    # 计算总计
    total_sales = sum(item['销售额'] for item in summary_list)
    total_cost = sum(item['销售成本'] for item in summary_list)
    total_profit = sum(item['毛利'] for item in summary_list)
    total_margin = (total_profit / total_sales * 100) if total_sales > 0 else 0
    
    print(f"\n{'品类':<15} {'回收量':>12} {'回收金额':>18} {'销售额':>18} {'销售成本':>18} {'毛利':>18} {'毛利率':>8} {'销售占比':>8}")
    print("-" * 120)
    
    for item in summary_list:
        sales_ratio = (item['销售额'] / total_sales * 100) if total_sales > 0 else 0
        print(f"{item['品类']:<15} {item['回收量']:>12,.0f} {item['回收金额']:>18,.0f} "
              f"{item['销售额']:>18,.0f} {item['销售成本']:>18,.0f} {item['毛利']:>18,.0f} "
              f"{item['毛利率']:>7.2f}% {sales_ratio:>7.2f}%")
    
    print("-" * 120)
    print(f"{'合计':<15} {'':>12} {'':>18} {total_sales:>18,.0f} {total_cost:>18,.0f} "
          f"{total_profit:>18,.0f} {total_margin:>7.2f}% {'100.00%':>8}")
    
    print("=" * 120)


def print_top_bottom(results: dict, top_n: int = 5):
    """打印毛利率最高/最低的品类"""
    
    category_summary = results['category_summary']
    
    # 转换为列表
    summary_list = [
        {'品类': cat, **data}
        for cat, data in category_summary.items()
    ]
    
    # 按毛利率排序
    sorted_by_margin = sorted(summary_list, key=lambda x: x['毛利率'], reverse=True)
    
    print("\n" + "=" * 60)
    print(f"毛利率 TOP {top_n} 品类")
    print("=" * 60)
    
    for i, item in enumerate(sorted_by_margin[:top_n], 1):
        print(f"{i}. {item['品类']:<15} 毛利率: {item['毛利率']:>7.2f}%  销售额: {item['销售额']:>15,.0f}")
    
    print("\n" + "=" * 60)
    print(f"毛利率 BOTTOM {top_n} 品类")
    print("=" * 60)
    
    for i, item in enumerate(sorted_by_margin[-top_n:], 1):
        print(f"{i}. {item['品类']:<15} 毛利率: {item['毛利率']:>7.2f}%  销售额: {item['销售额']:>15,.0f}")
    
    print("=" * 60)


# ============================================================
# 主程序
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='每月品类毛利率计算工具')
    parser.add_argument('--source', choices=['csv', 'json', 'api', 'db'], default='csv',
                        help='数据源类型 (default: csv)')
    parser.add_argument('--input', type=str, help='输入文件路径 (csv/json)')
    parser.add_argument('--endpoint', type=str, help='API端点')
    parser.add_argument('--query', type=str, help='数据库查询语句')
    parser.add_argument('--output', type=str, help='输出文件路径 (json)')
    parser.add_argument('--top', type=int, default=5, help='显示TOP N品类 (default: 5)')
    
    args = parser.parse_args()
    
    # 加载数据
    print(f"正在从 {args.source} 加载数据...")
    
    try:
        if args.source == 'csv':
            if not args.input:
                print("错误：CSV数据源需要指定 --input 参数")
                sys.exit(1)
            raw_data = load_from_csv(args.input)
        elif args.source == 'json':
            if not args.input:
                print("错误：JSON数据源需要指定 --input 参数")
                sys.exit(1)
            raw_data = load_from_json(args.input)
        elif args.source == 'api':
            if not args.endpoint:
                print("错误：API数据源需要指定 --endpoint 参数")
                sys.exit(1)
            raw_data = load_from_api(args.endpoint)
        elif args.source == 'db':
            if not args.query:
                print("错误：数据库数据源需要指定 --query 参数")
                sys.exit(1)
            raw_data = load_from_db(args.query)
    except Exception as e:
        print(f"错误：加载数据失败 - {e}")
        sys.exit(1)
    
    print(f"成功加载 {len(raw_data)} 条记录")
    
    # 标准化数据
    print("正在标准化数据...")
    normalized_data = normalize_data(raw_data)
    print(f"标准化后 {len(normalized_data)} 条记录")
    
    # 计算毛利率
    print("正在计算毛利率...")
    results = calculate_monthly_category_margin(normalized_data)
    
    # 输出报表
    print_monthly_report(results)
    print_category_summary(results)
    print_top_bottom(results, args.top)
    
    # 导出JSON（可选）
    if args.output:
        print(f"\n正在导出到 {args.output}...")
        export_data = {
            'generated_at': datetime.now().isoformat(),
            'monthly': results['monthly'],
            'category_summary': results['category_summary'],
            'month_summary': results['month_summary'],
        }
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)
        print(f"已导出到 {args.output}")
    
    print("\n完成！")


if __name__ == '__main__':
    main()
