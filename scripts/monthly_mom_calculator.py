#!/usr/bin/env python3
"""
每月环比计算脚本
Finance AI OS - trace_id: 20260514-006

用法：
    python monthly_mom_calculator.py --source csv --input data.csv
    python monthly_mom_calculator.py --source csv --input data.csv --metrics 回收量,回收金额,销售额
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime


def load_from_csv(filepath: str) -> list:
    """从CSV文件加载数据"""
    import csv
    data = []
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            data.append(row)
    return data


def load_from_json(filepath: str) -> list:
    """从JSON文件加载数据"""
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def normalize_data(raw_data: list) -> list:
    """标准化数据格式"""
    
    field_mapping = {
        "月份": ["月份", "month", "sale_date", "日期"],
        "品类": ["品类", "category", "product_category", "产品类别"],
        "回收量": ["回收量", "recycling_qty", "recycle_quantity"],
        "回收金额": ["回收金额", "recycling_amount", "recycle_amount"],
        "销售额": ["销售额", "sales_amount", "sale_amount", "revenue"],
        "销售成本": ["销售成本", "cost_amount", "cost", "cogs"],
        "毛利": ["毛利", "profit", "gross_profit"],
        "毛利率": ["毛利率", "margin", "gross_margin"],
    }
    
    def find_field(row, candidates):
        for candidate in candidates:
            if candidate in row:
                return candidate
        return None
    
    normalized = []
    for row in raw_data:
        month_field = find_field(row, field_mapping["月份"])
        category_field = find_field(row, field_mapping["品类"])
        
        if not month_field:
            continue
        
        month = row[month_field]
        category = row[category_field] if category_field else "合计"
        
        def safe_float(field_name):
            if field_name and row.get(field_name):
                try:
                    return float(row[field_name])
                except (ValueError, TypeError):
                    return 0
            return 0
        
        recycling_qty = safe_float(find_field(row, field_mapping["回收量"]))
        recycling_amount = safe_float(find_field(row, field_mapping["回收金额"]))
        sales_amount = safe_float(find_field(row, field_mapping["销售额"]))
        cost_amount = safe_float(find_field(row, field_mapping["销售成本"]))
        profit_field = find_field(row, field_mapping["毛利"])
        margin_field = find_field(row, field_mapping["毛利率"])
        profit = safe_float(profit_field) or (sales_amount - cost_amount)
        margin = safe_float(margin_field) or ((profit / sales_amount * 100) if sales_amount > 0 else 0)
        
        normalized.append({
            "月份": month,
            "品类": category,
            "回收量": recycling_qty,
            "回收金额": recycling_amount,
            "销售额": sales_amount,
            "销售成本": cost_amount,
            "毛利": profit,
            "毛利率": round(margin, 2),
        })
    
    return normalized


def calculate_mom(data: list, metrics: list = None) -> dict:
    """计算每月环比"""
    
    if metrics is None:
        metrics = ["回收量", "回收金额", "销售额", "销售成本", "毛利", "毛利率"]
    
    # 按月份汇总
    monthly_summary = defaultdict(lambda: defaultdict(float))
    for item in data:
        month = item["月份"]
        for metric in metrics:
            monthly_summary[month][metric] += item[metric]
    
    sorted_months = sorted(monthly_summary.keys())
    
    # 计算整体环比
    mom_growth = {}
    for i, month in enumerate(sorted_months):
        if i == 0:
            mom_growth[month] = {metric: None for metric in metrics}
        else:
            prev_month = sorted_months[i - 1]
            mom_growth[month] = {}
            for metric in metrics:
                current = monthly_summary[month][metric]
                previous = monthly_summary[prev_month][metric]
                if previous > 0:
                    growth = (current - previous) / previous * 100
                    mom_growth[month][metric] = round(growth, 2)
                else:
                    mom_growth[month][metric] = None
    
    # 按品类计算环比
    category_data = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    for item in data:
        category = item["品类"]
        month = item["月份"]
        for metric in metrics:
            category_data[category][month][metric] += item[metric]
    
    category_mom = {}
    for category, months_data in category_data.items():
        sorted_cat_months = sorted(months_data.keys())
        category_mom[category] = {}
        
        for i, month in enumerate(sorted_cat_months):
            if i == 0:
                category_mom[category][month] = {metric: None for metric in metrics}
            else:
                prev_month = sorted_cat_months[i - 1]
                category_mom[category][month] = {}
                for metric in metrics:
                    current = months_data[month][metric]
                    previous = months_data[prev_month][metric]
                    if previous > 0:
                        growth = (current - previous) / previous * 100
                        category_mom[category][month][metric] = round(growth, 2)
                    else:
                        category_mom[category][month][metric] = None
    
    return {
        "monthly_summary": dict(monthly_summary),
        "mom_growth": mom_growth,
        "category_mom": category_mom,
        "sorted_months": sorted_months,
        "metrics": metrics,
    }


def print_overall_mom_report(results: dict):
    """打印整体环比报表"""
    
    monthly_summary = results["monthly_summary"]
    mom_growth = results["mom_growth"]
    sorted_months = results["sorted_months"]
    metrics = results["metrics"]
    
    print("=" * 120)
    print("每月环比分析报表（整体）")
    print(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 120)
    
    # 数据概览
    print(f"\n{'月份':<10}", end="")
    for metric in metrics:
        print(f" {metric:>15}", end="")
    print()
    print("-" * (10 + 16 * len(metrics)))
    
    for month in sorted_months:
        print(f"{month:<10}", end="")
        for metric in metrics:
            value = monthly_summary[month][metric]
            if metric == "毛利率":
                print(f" {value:>14.2f}%", end="")
            else:
                print(f" {value:>15,.0f}", end="")
        print()
    
    # 环比增长率
    print("\n" + "=" * 120)
    print("环比增长率（MoM%）")
    print("=" * 120)
    
    print(f"\n{'月份':<10}", end="")
    for metric in metrics:
        print(f" {metric:>15}", end="")
    print()
    print("-" * (10 + 16 * len(metrics)))
    
    for month in sorted_months:
        print(f"{month:<10}", end="")
        for metric in metrics:
            value = mom_growth[month][metric]
            if value is None:
                print(f" {'--':>15}", end="")
            else:
                sign = "+" if value > 0 else ""
                print(f" {sign}{value:>14.2f}%", end="")
        print()
    
    print("\n" + "=" * 120)


def print_category_mom_report(results: dict, top_n: int = 10):
    """打印品类环比报表"""
    
    category_mom = results["category_mom"]
    sorted_months = results["sorted_months"]
    metrics = results["metrics"]
    
    print("\n" + "=" * 120)
    print("品类环比分析报表")
    print("=" * 120)
    
    main_metric = "销售额"
    top_categories = list(category_mom.keys())[:top_n]
    
    print(f"\nTOP {top_n} 品类 {main_metric} 环比增长率：")
    print("-" * 120)
    
    print(f"{'品类':<15}", end="")
    for month in sorted_months:
        print(f" {month:>12}", end="")
    print()
    print("-" * (15 + 13 * len(sorted_months)))
    
    for category in top_categories:
        print(f"{category:<15}", end="")
        for month in sorted_months:
            value = category_mom[category][month].get(main_metric)
            if value is None:
                print(f" {'--':>12}", end="")
            else:
                sign = "+" if value > 0 else ""
                print(f" {sign}{value:>11.2f}%", end="")
        print()
    
    print("-" * 120)
    
    # 各品类详细环比
    print(f"\n各品类详细环比：")
    print("=" * 120)
    
    for category in top_categories:
        print(f"\n【{category}】")
        print("-" * 100)
        
        print(f"{'月份':<10}", end="")
        for metric in metrics:
            print(f" {metric:>15}", end="")
        print()
        print("-" * (10 + 16 * len(metrics)))
        
        for month in sorted_months:
            print(f"{month:<10}", end="")
            for metric in metrics:
                value = category_mom[category][month].get(metric)
                if value is None:
                    print(f" {'--':>15}", end="")
                else:
                    sign = "+" if value > 0 else ""
                    print(f" {sign}{value:>14.2f}%", end="")
            print()
    
    print("\n" + "=" * 120)


def print_mom_summary(results: dict):
    """打印环比摘要"""
    
    mom_growth = results["mom_growth"]
    sorted_months = results["sorted_months"]
    category_mom = results["category_mom"]
    
    print("\n" + "=" * 80)
    print("环比摘要")
    print("=" * 80)
    
    latest_month = sorted_months[-1]
    prev_month = sorted_months[-2] if len(sorted_months) > 1 else None
    
    if prev_month:
        print(f"\n最新月份: {latest_month} vs {prev_month}")
        print("-" * 80)
        
        for metric, value in mom_growth[latest_month].items():
            if value is not None:
                sign = "↑" if value > 0 else "↓" if value < 0 else "→"
                print(f"  {metric:<10} {sign} {abs(value):.2f}%")
            else:
                print(f"  {metric:<10} --")
    
    # 品类环比排名
    latest_growth = []
    for category, months_data in category_mom.items():
        if latest_month in months_data:
            growth = months_data[latest_month].get("销售额")
            if growth is not None:
                latest_growth.append((category, growth))
    
    if latest_growth:
        latest_growth.sort(key=lambda x: x[1], reverse=True)
        
        print(f"\n{latest_month} 销售额环比增长最快 TOP 3:")
        for i, (cat, growth) in enumerate(latest_growth[:3], 1):
            sign = "+" if growth > 0 else ""
            print(f"  {i}. {cat}: {sign}{growth:.2f}%")
        
        print(f"\n{latest_month} 销售额环比下降最多 TOP 3:")
        for i, (cat, growth) in enumerate(latest_growth[-3:], 1):
            sign = "+" if growth > 0 else ""
            print(f"  {i}. {cat}: {sign}{growth:.2f}%")
    
    print("\n" + "=" * 80)


def main():
    parser = argparse.ArgumentParser(description="每月环比计算工具")
    parser.add_argument("--source", choices=["csv", "json"], default="csv",
                        help="数据源类型 (default: csv)")
    parser.add_argument("--input", type=str, required=True, help="输入文件路径")
    parser.add_argument("--metrics", type=str, default="回收量,回收金额,销售额,毛利",
                        help="要计算环比的指标，逗号分隔")
    parser.add_argument("--output", type=str, help="输出文件路径 (json)")
    parser.add_argument("--top", type=int, default=10, help="显示TOP N品类 (default: 10)")
    
    args = parser.parse_args()
    
    metrics = [m.strip() for m in args.metrics.split(",")]
    
    print(f"正在从 {args.source} 加载数据...")
    
    try:
        if args.source == "csv":
            raw_data = load_from_csv(args.input)
        elif args.source == "json":
            raw_data = load_from_json(args.input)
    except Exception as e:
        print(f"错误：加载数据失败 - {e}")
        sys.exit(1)
    
    print(f"成功加载 {len(raw_data)} 条记录")
    
    print("正在标准化数据...")
    normalized_data = normalize_data(raw_data)
    print(f"标准化后 {len(normalized_data)} 条记录")
    
    print("正在计算环比...")
    results = calculate_mom(normalized_data, metrics)
    
    print_overall_mom_report(results)
    print_category_mom_report(results, args.top)
    print_mom_summary(results)
    
    if args.output:
        print(f"\n正在导出到 {args.output}...")
        export_data = {
            "generated_at": datetime.now().isoformat(),
            "monthly_summary": results["monthly_summary"],
            "mom_growth": results["mom_growth"],
            "category_mom": results["category_mom"],
            "sorted_months": results["sorted_months"],
            "metrics": results["metrics"],
        }
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)
        print(f"已导出到 {args.output}")
    
    print("\n完成！")


if __name__ == "__main__":
    main()
