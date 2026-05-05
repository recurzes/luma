from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone

import structlog
from supabase import Client

from app.models.member import Member
from app.models.standup import StandupResponse, StandupSession
from app.services.member_service import MemberService
from app.services.steak_service import StreakService
from app.services.xp_service import XPService

log = structlog.get_logger()


class StandupService:
    def __init__(
            self,
            db: Client,
            members: MemberService,
            xp: XPService
    ) -> None:
        self._db = db
        self._members = members
        self._xp = xp

    async def _run(self, fn):
        return await asyncio.get_event_loop().run_in_executor(None, fn)

    def _parse_session(self, data: dict) -> StandupSession:
        return StandupSession.model_validate(data)

    def _parse_response(self, data: dict) -> StandupResponse:
        return StandupResponse.model_validate(data)

    async def open_session(self) -> StandupSession:
        today = date.today().isoformat()

        def _insert():
            return (
                self._db.table("bot_standup_sessions")
                .insert({"date": today})
                .execute()
            )

        result = await self._run(_insert)
        return self._parse_session(result.data[0])

    async def get_or_create_today(self) -> StandupSession:
        today = date.today().isoformat()

        def _fetch():
            return (
                self._db.table("bot_standup_sessions")
                .select("*")
                .eq("date", today)
                .limit(1)
                .execute()
            )

        result = await self._run(_fetch)
        if result.data:
            return self._parse_session(result.data[0])
        return await self.open_session()

    async def save_response(
            self,
            session_id: str,
            member_id: str,
            yesterday: str,
            today: str,
            blockers: str
    ) -> StandupResponse:
        def _upsert():
            return (
                self._db.table("bot_standup_responses")
                .upsert(
                    {
                        "session_id": session_id,
                        "member_id": member_id,
                        "yesterday": yesterday,
                        "today": today,
                        "blockers": blockers,
                        "responded_at": datetime.now(timezone.utc).isoformat()
                    },
                    on_conflict="session_id,member_id"
                )
                .execute()
            )

        result = await self._run(_upsert)
        response = self._parse_response(result.data[0])

        await self._xp.award(member_id, "standup")

        streak = StreakService(self._db, self._members)
        await streak.record_activity(member_id, "standup")

        log.info("standup.response_saved", member_id=member_id, session_id=session_id)
        return response

    async def get_responses(self, session_id: str) -> list[StandupResponse]:
        def _fetch():
            return (
                self._db.table("bot_standup_responses")
                .select("*")
                .eq("session_id", session_id)
                .execute()
            )

        result = await self._run(_fetch)
        return [self._parse_response(r) for r in result.data]

    async def non_responders(self, session_id: str) -> list[Member]:
        all_members = await self._members.get_all_active()
        responses = await self.get_responses(session_id)
        responded_ids = {str(r.member_id) for r in responses}
        return [m for m in all_members if str(m.id) not in responded_ids]

    async def mark_posted(self, session_id: str) -> None:
        def _update():
            return (
                self._db.table("bot_standup_sessions")
                .update({"posted_at": datetime.now(timezone.utc).isoformat()})
                .eq("id", session_id)
                .execute()
            )

        await self._run(_update)
