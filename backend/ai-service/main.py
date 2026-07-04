from fastapi import FastAPI

from api.rag_routes import router as rag_router
from api.shopping_routes import router as shopping_router

app = FastAPI(title="ai-service")
app.include_router(rag_router)
app.include_router(shopping_router)


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