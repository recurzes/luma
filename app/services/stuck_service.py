from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import structlog
from supabase import Client

from app.models.help_thread import HelpThread
from app.services.xp_service import XPService

log = structlog.get_logger()

_bumped_15: set[str] = set()


class StuckService:
    def __init__(self, db: Client, xp: XPService) -> None:
        self._db = db
        self._xp = xp

    async def _run(self, fn):
        return await asyncio.get_event_loop().run_in_executor(None, fn)

    def _parse(self, data: dict) -> HelpThread:
        return HelpThread.model_validate(data)

    async def open_thread(self, requester_id: str, problem: str, discord_thread_id: str) -> HelpThread:
        def _insert():
            return (
                self._db.table("bot_help_threads")
                .insert({
                    "requester_id": requester_id,
                    "problem": problem,
                    "discord_thread_id": discord_thread_id,
                    "status": "open"
                })
                .execute()
            )

        result = await self._run(_insert)
        thread = self._parse(result.data[0])
        log.info("stuck.thread.opened", thread_id=str(thread.id), requester=requester_id)
        return thread

    async def resolve(self, thread_id: str, helper_id: str, notes: str = "") -> HelpThread:
        now = datetime.now(timezone.utc).isoformat()

        def _update():
            return (
                self._db.table("bot_help_threads")
                .update({"status": "resolved", "resolved_at": now, "helper_id": helper_id, "resolution_notes": notes or None})
                .eq("id", thread_id)
                .execute()
            )

        result = await self._run(_update)
        if not result.data:
            raise ValueError(f"Thread {thread_id!r} not found")

        thread = self._parse(result.data[0])
        await self._xp.award(helper_id, "helped_stuck", metadata={"thread_id": thread_id})
        _bumped_15.discard(thread_id)
        log.info("stuck.thread.resolved", thread_id=thread_id, helper=helper_id)
        return thread

    async def escalate(self, thread_id: str) -> HelpThread:
        now = datetime.now(timezone.utc).isoformat()

        def _update():
            return (
                self._db.table("bot_help_threads")
                .update({"status": "escalated", "escalated_at": now})
                .eq("id", thread_id)
                .execute()
            )

        result = await self._run(_update)
        if not result.data:
            raise ValueError(f"Thread {thread_id!r} not found")

        return self._parse(result.data[0])

    async def get_open_threads(self) -> list[HelpThread]:
        def _fetch():
            return (
                self._db.table("bot_help_threads")
                .select("*")
                .eq("status", "open")
                .order("opened_at", desc=False)
                .execute()
            )

        result = await self._run(_fetch)
        return [self._parse(r) for r in result.data]

    async def get_overdue_threads(self, minutes: int) -> list[HelpThread]:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()

        def _fetch():
            return (
                self._db.table("bot_help_threads")
                .select("*")
                .eq("status", "open")
                .is_("escalated_at", "null")
                .lt("opened_at", cutoff)
                .execute()
            )

        result = await self._run(_fetch)
        return [self._parse(r) for r in result.data]