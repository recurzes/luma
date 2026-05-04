from __future__ import annotations

import structlog
from supabase import Client, create_client

from app.config import settings

log = structlog.get_logger()

_client: Client | None = None


def get_db() -> Client:
    global _client
    if _client is None:
        _client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
        log.info("supabase.client_initialized", url=settings.SUPABASE_URL)
    return _client

async def ping() -> bool:
    try:
        db = get_db()
        db.table("bot_phases").select("id").limit(1).execute()
        return True
    except Exception as exc:
        log.warning("supabase.ping_failed", error=str(exc))
        return False