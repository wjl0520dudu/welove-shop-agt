from fastapi import FastAPI
app = FastAPI(title="ai-service")

@app.get("/health")
async def health():
    return {"status": "healthy"}