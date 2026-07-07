# Windows psycopg async 需要 SelectorEventLoop（不兼容默认的 ProactorEventLoop）。
# 必须在 import asyncio 之前设置策略，让所有下游子系统都拿到正确的 loop。
import sys
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# LangSmith 追踪初始化。必须在 import LangChain / langgraph 之前，让它们
# 加载时能读到 LANGCHAIN_* 环境变量并自动挂钩。
# 我们把 config 里的 LANGSMITH_* 映射到 LangChain 期望的 LANGCHAIN_* 前缀名。
import os
from core.config import config as _cfg
if _cfg.LANGSMITH_TRACING and _cfg.LANGSMITH_API_KEY:
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGCHAIN_ENDPOINT", _cfg.LANGSMITH_ENDPOINT)
    os.environ.setdefault("LANGCHAIN_API_KEY", _cfg.LANGSMITH_API_KEY)
    os.environ.setdefault("LANGCHAIN_PROJECT", _cfg.LANGSMITH_PROJECT)
    # 新版环境变量名也一起设，前后兼容
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGSMITH_ENDPOINT", _cfg.LANGSMITH_ENDPOINT)
    os.environ.setdefault("LANGSMITH_API_KEY", _cfg.LANGSMITH_API_KEY)
    os.environ.setdefault("LANGSMITH_PROJECT", _cfg.LANGSMITH_PROJECT)

# 结构化日志必须尽早配置，让 lifespan 和后续 import 阶段的日志都用统一格式
from core.logging_config import setup_logging
setup_logging(level=os.getenv("LOG_LEVEL", "INFO"))

import logging
if _cfg.LANGSMITH_TRACING and _cfg.LANGSMITH_API_KEY:
    logging.getLogger("ai-service").info("LangSmith tracing enabled, project=%s", _cfg.LANGSMITH_PROJECT)

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agents.runtime import init_runtime, close_runtime
from api.assistant_routes import router as assistant_router
from api.health_routes import router as health_router
from api.middleware import RequestLogMiddleware, TraceIdMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 生命周期：启动时初始化 Postgres 连接池，关闭时释放。

    init_runtime 内部若 Postgres 连不上会自动降级 InMemory，服务照常起。
    """
    await init_runtime()
    try:
        yield
    finally:
        await close_runtime()


app = FastAPI(title="ai-service", lifespan=lifespan)

# ── 中间件（自内向外注册，实际执行顺序倒过来）──
# TraceId 必须最外层：response 阶段要给所有响应都带上 X-Trace-Id header，
# 且 request 阶段要在最早就把 traceId 塞进 contextvar，供后续所有日志用。
app.add_middleware(RequestLogMiddleware)
app.add_middleware(TraceIdMiddleware)

# CORS：允许来源从 config 读，逗号分隔可配置。SSE 长连接必须允许 GET/POST。
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cfg.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Trace-Id"],
)

app.include_router(assistant_router)
app.include_router(health_router)

# RAG 路由依赖 pymilvus；缺依赖时降级跳过，保证 assistant 主图始终可用。
try:
    from api.rag_routes import router as rag_router
    app.include_router(rag_router)
except Exception as _rag_import_error:  # pragma: no cover
    logging.getLogger("ai-service").warning("RAG routes disabled: %s", _rag_import_error)


import uvicorn
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
