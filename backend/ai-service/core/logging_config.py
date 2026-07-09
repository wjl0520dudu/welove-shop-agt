"""结构化日志配置：控制台带 traceId + 时间 + 级别，供 lifespan 早期调用。

放在 core/ 而非 api/ 是因为它不依赖 FastAPI；lifespan 之外的模块也能用。
"""
from __future__ import annotations

import logging
import sys

from api.middleware import TraceIdLogFilter


def setup_logging(level: str = "INFO") -> None:
    """配置 root logger：单一 StreamHandler，带 traceId 的 Formatter。

    幂等：多次调用只会保留最新配置，避免重复 handler 造成日志翻倍。
    """
    root = logging.getLogger()
    root.setLevel(level.upper())

    # 清掉已有 handler（uvicorn / pytest 可能已经装过）
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(TraceIdLogFilter())
    handler.setFormatter(logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(trace_id)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root.addHandler(handler)

    # uvicorn 自己也有 logger，跟着走同样的格式
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
