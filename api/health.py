"""GET /api/health — liveness check for the Vercel function."""

from fastapi import FastAPI

app = FastAPI()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "version": "0.1.0"}
