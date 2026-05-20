# ==============================================
# 财务数据每日自动更新流水线脚本
# 功能：按顺序自动执行数据导入 → 指标生成，出错自动停止
# 使用方法：每天早上双击运行这个文件即可
# ==============================================

# 导入Python标准库（无需额外安装）
import subprocess  # 用于调用并执行外部的Python脚本
import sys         # 用于在出错时强制终止整个程序
import time        # 用于统计整个脚本的执行总耗时
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# --------------------------
# 配置：每日更新的执行步骤
# 严格按照从上到下的顺序执行，上一步成功才会执行下一步
# --------------------------
steps = [
    [sys.executable, str(PROJECT_ROOT / "scripts" / "import_all.py")],
    [sys.executable, str(PROJECT_ROOT / "scripts" / "create_metrics.py")],
]

# 记录脚本开始执行的时间（精确到秒）
start_time = time.time()

print("=" * 50)
print("开始执行每日财务数据更新...")
print("=" * 50)

# --------------------------
# 循环执行每一个配置好的步骤
# --------------------------
for step_index, command in enumerate(steps, 1):
    display_command = " ".join(command)
    print(f"\n【第 {step_index}/{len(steps)} 步】正在执行：{display_command}")
    print("-" * 50)

    # 执行命令，等待它完全运行完成
    # 会把脚本的所有输出（打印信息、报错信息）直接显示在当前终端
    result = subprocess.run(command, cwd=PROJECT_ROOT)

    # --------------------------
    # 错误检查：上一步执行失败则立即终止整个程序
    # 所有程序的通用约定：运行成功返回0，运行失败返回非0数字
    # --------------------------
    if result.returncode != 0:
        print("\n❌ 执行失败！")
        print(f"失败的步骤：{display_command}")
        print("请修复错误后重新运行脚本")
        # 退出程序，返回码1表示执行失败
        sys.exit(1)

    print(f"✅ 第 {step_index} 步执行完成")

# --------------------------
# 所有步骤全部执行成功
# --------------------------
print("\n" + "=" * 50)
print("🎉 全部数据更新完成！")

# 计算并打印总耗时
total_seconds = time.time() - start_time
total_minutes = round(total_seconds / 60, 1)
print(f"⏱️  总耗时：{total_seconds:.1f} 秒（约 {total_minutes} 分钟）")
print("=" * 50)
