from __future__ import annotations

from fastapi import FastAPI

from app.config import settings
from app.logging_config import configure_logging
from app.webhooks.github import router as github_router

configure_logging()
settings.require("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "GITHUB_WEBHOOK_SECRET")

app = FastAPI(title="LumaBot Webhook Bridge", version="0.1.0")

app.include_router(github_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}