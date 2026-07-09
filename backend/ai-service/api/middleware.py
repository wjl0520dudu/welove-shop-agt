"""FastAPI 中间件：traceId 透传 & 请求日志。

Java 侧通过 `X-Trace-Id` header 传递全局链路 ID；ai-service 读到就用，
读不到就自己生成。日志和响应 header 都会带上，方便在两个系统之间对齐日志。

用法（main.py）：
    from api.middleware import TraceIdMiddleware, RequestLogMiddleware
    app.add_middleware(TraceIdMiddleware)
    app.add_middleware(RequestLogMiddleware)
"""
from __future__ import annotations

import contextvars
import logging
import time
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("ai-service.access")

# 用 contextvars 让日志格式化时随时能拿到当前请求的 traceId，
# 而不用手工在每条 log 里传参数。子协程会继承同一个 var。
trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="-")

TRACE_HEADER = "X-Trace-Id"


class TraceIdMiddleware(BaseHTTPMiddleware):
    """读/生成 traceId，塞进 contextvars 和 response header。

    这个中间件必须放在最外层（先执行、后返回），才能覆盖后续所有处理链。
    """

    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get(TRACE_HEADER)
        trace_id = incoming or uuid4().hex
        token = trace_id_var.set(trace_id)
        # 让路由函数也能从 request.state 拿到
        request.state.trace_id = trace_id
        try:
            response: Response = await call_next(request)
        finally:
            trace_id_var.reset(token)
        response.headers[TRACE_HEADER] = trace_id
        return response


class RequestLogMiddleware(BaseHTTPMiddleware):
    """结构化请求日志：方法 / 路径 / 状态码 / 耗时。

    与 TraceIdMiddleware 配合，日志前缀会自动带上 traceId
    （前提是日志格式里配置了 %(trace_id)s，见 logging_config.py）。
    """

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        except Exception:
            status = 500
            raise
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            # 健康探针刷屏，降级到 DEBUG
            path = request.url.path
            level = logging.DEBUG if path.startswith("/health") else logging.INFO
            logger.log(
                level,
                "%s %s -> %d %.1fms",
                request.method,
                path,
                status,
                elapsed_ms,
            )


class TraceIdLogFilter(logging.Filter):
    """把当前 contextvar 的 trace_id 塞进每条 LogRecord。

    用法：
        handler.addFilter(TraceIdLogFilter())
        # formatter 里就能引用 %(trace_id)s
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = trace_id_var.get()
        return True
