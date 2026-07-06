# Windows psycopg async 需要 SelectorEventLoop（不兼容默认的 ProactorEventLoop）。
# 必须在 import asyncio 之前设置策略，让所有下游子系统都拿到正确的 loop。
import sys
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from contextlib import asynccontextmanager

from fastapi import FastAPI

from agents.runtime import init_runtime, close_runtime
from api.assistant_routes import router as assistant_router
from api.shopping_routes import router as shopping_router


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
app.include_router(assistant_router)
app.include_router(shopping_router)

# RAG 路由依赖 pymilvus；缺依赖时降级跳过，保证 assistant 主图始终可用。
try:
    from api.rag_routes import router as rag_router
    app.include_router(rag_router)
except Exception as _rag_import_error:  # pragma: no cover
    import logging
    logging.getLogger("ai-service").warning("RAG routes disabled: %s", _rag_import_error)


@app.get("/health")
async def health():
    return {"status": "healthy"}


import uvicorn
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
