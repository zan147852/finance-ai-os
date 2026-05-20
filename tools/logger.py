# ==============================================
# 结构化日志模块
# 所有 Agent/工具操作通过此类记录，支持 trace_id 链路追踪
# 输出格式：JSONL（每行一个 JSON 对象）
# ==============================================

import json
import uuid
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def generate_trace_id() -> str:
    return f"trace_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def _sanitize_text(value):
    if isinstance(value, str):
        return value.encode("utf-8", "replace").decode("utf-8")
    if isinstance(value, dict):
        return {_sanitize_text(key): _sanitize_text(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_text(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_text(item) for item in value)
    return value


class StructuredLogger:
    def __init__(self, component_name: str, log_dir: str = "logs"):
        self.component = _sanitize_text(component_name)
        self.log_dir = Path(log_dir)
        if not self.log_dir.is_absolute():
            self.log_dir = PROJECT_ROOT / self.log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _write(self, level: str, trace_id: str, message: str, extra: dict):
        today = datetime.now().strftime("%Y%m%d")
        log_file = self.log_dir / f"{self.component}_{today}.jsonl"
        entry = {
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "component": self.component,
            "trace_id": _sanitize_text(trace_id),
            "message": _sanitize_text(message),
        }
        if extra:
            entry["data"] = _sanitize_text(extra)
        with open(log_file, "a", encoding="utf-8", errors="replace") as f:
            f.write(json.dumps(_sanitize_text(entry), ensure_ascii=False, default=str) + "\n")

    def info(self, trace_id: str, message: str, **extra):
        self._write("INFO", trace_id, message, extra)

    def warning(self, trace_id: str, message: str, **extra):
        self._write("WARNING", trace_id, message, extra)

    def error(self, trace_id: str, message: str, **extra):
        self._write("ERROR", trace_id, message, extra)
