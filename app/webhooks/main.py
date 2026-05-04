from __future__ import annotations

from fastapi import FastAPI

from app.webhooks.github import router as github_router

app = FastAPI(title="LumaBot Webhook Bridge", version="0.1.0")

app.include_router(github_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}