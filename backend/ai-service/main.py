from fastapi import FastAPI

from api.assistant_routes import router as assistant_router
from api.shopping_routes import router as shopping_router

app = FastAPI(title="ai-service")
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
