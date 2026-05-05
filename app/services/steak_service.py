from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone

import structlog
from dateutil.utils import today
from supabase import Client

from app.models.member import Member
from app.services.member_service import MemberService

log = structlog.get_logger()


class StreakService:
    def __init__(self, db: Client, members: MemberService):
        self._db = db
        self._members = members

    async def _run(self, fn):
        return await asyncio.get_event_loop().run_in_executor(None, fn)

    async def record_activity(self, member_id: str, activity: str) -> None:
        today = date.today().isoformat()

        def _check():
            return (
                self._db.table("bot_streak_log")
                .select("id")
                .eq("member_id", member_id)
                .eq("streak_date", today)
                .limit(1)
                .execute()
            )

        existing = await self._run(_check)
        if existing.data:
            return

        def _insert():
            return (
                self._db.table("bot_streak_log")
                .insert({"member_id": member_id, "streak_date": today, "activity": activity})
                .execute()
            )

        await self._run(_insert)

        def _fetch_stats():
            return (
                self._db.table("bot_member_stats")
                .select("current_streak, longest_streak")
                .eq("member_id", member_id)
                .limit(1)
                .execute()
            )

        stats = await self._run(_fetch_stats)
        if not stats.data:
            return

        current = stats.data[0]["current_streak"]
        longest = stats.data[0]["longest_streak"]
        new_current = current + 1
        new_longest = max(longest, new_current)

        def _update_stats():
            return (
                self._db.table("bot_member_stats")
                .update(
                    {
                        "current_streak": new_current,
                        "longest_streak": new_longest,
                        "last_activity": datetime.now(timezone.utc).isoformat(),
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    }
                )
                .eq("member_id", member_id)
                .execute()
            )

        await self._run(_update_stats)
        log.info("streak.recorded", member_id=member_id, new_streak=new_current)

    async def check_all_streaks(self) -> list[str]:
        today = date.today().isoformat()
        broken: list[str] = []

        all_members = await self._members.get_all_active()

        def _had_activity(member_id: str):
            return (
                self._db.table("bot_streak_log")
                .select("id")
                .eq("member_id", member_id)
                .eq("streak_date", today)
                .limit(1)
                .execute()
            )

        for member in all_members:
            member_id = str(member.id)
            result = await self._run(lambda mid=member_id: _had_activity(mid))
            if not result.data:
                def _fetch_streak(mid=member_id):
                    return (
                        self._db.table("bot_member_stats")
                        .select("current_streak")
                        .eq("member_id", mid)
                        .limit(1)
                        .execute()
                    )

                stats = await self._run(_fetch_streak)
                if stats.data and stats.data[0]["current_streak"] > 0:
                    def _reset(mid=member_id):
                        return (
                            self._db.table("bot_members_stats")
                            .update({"current_streak": 0})
                            .eq("member_id", mid)
                            .execute()
                        )
                    await self._run(_reset)
                    broken.append(member_id)
                    log.info("streak.broken", member_id=member_id)

        return broken

    async def at_risk_members(self) -> list[Member]:
        today = date.today().isoformat()
        all_members = await self._members.get_all_active()
        at_risk: list[Member] = []

        for member in all_members:
            member_id = str(member.id)

            def _check(mid=member_id):
                return (
                    self._db.table("bot_streak_log")
                    .select("id")
                    .eq("member_id", mid)
                    .eq("streak_date", today)
                    .limit(1)
                    .execute()
                )

            result = await self._run(_check)
            if not result.data:
                at_risk.append(member)

        return at_risk