from __future__ import annotations

from fastapi import FastAPI

from app.logging_config import configure_logging
from app.webhooks.github import router as github_router

configure_logging()

app = FastAPI(title="LumaBot Webhook Bridge", version="0.1.0")

app.include_router(github_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}