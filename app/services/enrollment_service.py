from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from functools import partial
from typing import Any
from uuid import UUID

import structlog
from supabase import Client

from app.models.enrollment import EnrollmentCreate, MemberEnrollment
from app.models.member import Member

log = structlog.get_logger()


class EnrollmentService:
    def __init__(self, db: Client) -> None:
        self._db = db

    def _run(self, fn, *args, **kwargs):
        return asyncio.get_event_loop().run_in_executor(None, partial[Any](fn, *args, **kwargs))

    def _parse(self, data: dict) -> MemberEnrollment:
        return MemberEnrollment.model_validate(data)

    def _parse_member(self, data: dict) -> Member:
        return Member.model_validate(data)

    async def get_enrollment(self, member_id: UUID, guild_id: str) -> MemberEnrollment | None:
        def _fetch():
            return (
                self._db.table("bot_member_enrollments")
                .select("*")
                .eq("member_id", str(member_id))
                .eq("guild_id", guild_id)
                .limit(1)
                .execute()
            )

        result = await self._run(_fetch)
        if not result.data:
            return None
        return self._parse(result.data[0])

    async def enroll(self, member_id: UUID, guild_id: str, guild_name: str) -> MemberEnrollment:
        existing = await self.get_enrollment(member_id, guild_id)
        if existing is not None:
            if existing.signed_out_at is None:
                return existing

            def _reactivate():
                return (
                    self._db.table("bot_member_enrollments")
                    .update({"signed_out_at": None, "guild_name": guild_name})
                    .eq("id", str(existing.id))
                    .execute()
                )

            result = await self._run(_reactivate)
            log.info("enrollment.reactivated", member_id=str(member_id), guild_id=guild_id)
            return self._parse(result.data[0])

        payload = EnrollmentCreate(
            member_id=member_id,
            guild_id=guild_id,
            guild_name=guild_name,
        )

        def _insert():
            return (
                self._db.table("bot_member_enrollments")
                .insert(payload.model_dump(mode="json"))
                .execute()
            )

        result = await self._run(_insert)
        log.info("enrollment.created", member_id=str(member_id), guild_id=guild_id)
        return self._parse(result.data[0])

    async def sign_out(self, member_id: UUID, guild_id: str) -> MemberEnrollment:
        enrollment = await self.get_enrollment(member_id, guild_id)
        if enrollment is None:
            raise ValueError(f"No enrollment for member {member_id} in guild {guild_id}")

        now = datetime.now(tz=timezone.utc).isoformat()

        def _update():
            return (
                self._db.table("bot_member_enrollments")
                .update({"signed_out_at": now})
                .eq("id", str(enrollment.id))
                .execute()
            )

        result = await self._run(_update)
        log.info("enrollment.signed_out", member_id=str(member_id), guild_id=guild_id)
        return self._parse(result.data[0])

    async def is_active(self, member_id: UUID, guild_id: str) -> bool:
        enrollment = await self.get_enrollment(member_id, guild_id)
        return enrollment is not None and enrollment.signed_out_at is None

    async def get_active_enrollments_for_member(self, member_id: UUID) -> list[MemberEnrollment]:
        def _fetch():
            return (
                self._db.table("bot_member_enrollments")
                .select("*")
                .eq("member_id", str(member_id))
                .is_("signed_out_at", "null")
                .execute()
            )

        result = await self._run(_fetch)
        return [self._parse(row) for row in result.data]

    async def get_dm_targets(self, guild_id: str) -> list[Member]:
        def _fetch():
            return (
                self._db.table("bot_member_enrollments")
                .select("bot_members(*)")
                .eq("guild_id", guild_id)
                .is_("signed_out_at", "null")
                .execute()
            )

        result = await self._run(_fetch)
        members: list[Member] = []
        for row in result.data:
            member_data = row.get("bot_members")
            if member_data:
                members.append(self._parse_member(member_data))
        return members

    async def backfill_guild(self, guild_id: str, guild_name: str) -> int:
        """Create enrollments for members missing one in this guild (startup backfill)."""

        def _fetch_members():
            return self._db.table("bot_members").select("id").execute()

        def _fetch_enrolled():
            return (
                self._db.table("bot_member_enrollments")
                .select("member_id")
                .eq("guild_id", guild_id)
                .execute()
            )

        members_result = await self._run(_fetch_members)
        enrolled_result = await self._run(_fetch_enrolled)
        enrolled_ids = {row["member_id"] for row in enrolled_result.data}

        created = 0
        for row in members_result.data:
            if row["id"] in enrolled_ids:
                continue
            await self.enroll(UUID(row["id"]), guild_id, guild_name)
            created += 1

        if created:
            log.info("enrollment.backfill", guild_id=guild_id, created=created)
        return created
