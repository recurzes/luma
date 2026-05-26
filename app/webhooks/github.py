from __future__ import annotations

import asyncio
import json

import structlog
from fastapi import APIRouter, Header, Request

from app import database
from app.webhooks.validators import require_valid_github_signature

log = structlog.get_logger()

router = APIRouter()

def _extract_actor(event_type: str, payload: dict) -> str:
    match event_type:
        case "push":
            return payload.get("pusher", {}).get("name", "unknown")
        case "pull_request" | "pull_request_review":
            return payload.get("sender", {}).get("login", "unknown")
        case "check_run":
            return payload.get("sender", {}).get("login", "unknown")
        case _:
            return payload.get("sender", {}).get("login", "unknown")


@router.post("/webhooks/github")
async def receive_github_webhook(
        request: Request,
        x_github_event: str | None = Header(default=None),
        x_hub_signature_256: str | None = Header(default=None)
) -> dict:
    body = await request.body()
    require_valid_github_signature(body, x_hub_signature_256)

    if not x_github_event:
        return {"received": True, "processed": False}

    payload: dict = await request.json() if not body else json.loads(body)

    known_events = {"push", "pull_request", "pull_request_review", "check_run"}

    if x_github_event not in known_events:
        log.debug("github.event.unknown", event_type=x_github_event)
        return {"received": True, "processed": False}

    actor = _extract_actor(x_github_event, payload)

    db = database.get_db()

    def _insert():
        return (
            db.table("bot_github_events")
            .insert(
                {
                    "event_type": x_github_event,
                    "actor": actor,
                    "member_id": None,
                    "payload": payload,
                }
            )
            .execute()
        )

    await asyncio.get_event_loop().run_in_executor(None, _insert)

    log.info("github.event.stored", event_type=x_github_event, actor=actor)
    return {"received": True}