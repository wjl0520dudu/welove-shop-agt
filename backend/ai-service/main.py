from fastapi import FastAPI

from api.rag_routes import router as rag_router

app = FastAPI(title="ai-service")
app.include_router(rag_router)


@app.get("/health")
async def health():
    return {"status": "healthy"}
