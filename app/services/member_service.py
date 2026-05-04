from __future__ import annotations

import asyncio
from functools import partial

import structlog
from supabase import Client

from app.models.member import Member, MemberCreate, MemberStats

log = structlog.get_logger()

_VALID_ROLES = {"lead", "professor", "beginner"}
_VALID_TIERS = {"T1", "T2", "T3"}


class MemberService:
    def __init__(self, db: Client) -> None:
        self._db = db

    # Helpers
    def _run(self, fn, *args, **kwargs):
        return asyncio.get_event_loop().run_in_executor(None, partial[Any](fn, *args, **kwargs))

    def _parse(self, data: dict) -> Member:
        return Member.model_validate(data)


    # Public API

    async def register(
            self,
            discord_id: str,
            discord_name: str,
            role: str,
            tier_max: str
    ) -> Member:
        if role not in _VALID_ROLES:
            raise ValueError(f"Invalid role: {role!r}. Must be one of {_VALID_ROLES}")
        if tier_max not in _VALID_TIERS:
            raise ValueError(f"Invalid tier_max: {tier_max!r}. Must be one of {_VALID_TIERS}")

        existing = await self.get_by_discord_id(discord_id)
        if existing is not None:
            raise ValueError(f"Member with discord_id {discord_id!r} is already registered")

        def _insert():
            return (
                self._db.table("bot_members")
                .insert(
                    {
                        "discord_id": discord_id,
                        "discord_name": discord_name,
                        "role": role,
                        "tier_max": tier_max
                    }
                )
                .execute()
            )

        result = await asyncio.get_event_loop().run_in_executor(None, _insert)
        member = self._parse(result.data[0])

        def _stats():
            return (
                self._db.table("bot_member_stats")
                .insert({"member_id": str(member.id)})
                .execute()
            )

        await asyncio.get_event_loop().run_in_executor(None, _stats)

        log.info("member.registered", discord_id=discord_id, role=role, tier_max=tier_max)
        return member

    async def get_by_discord_id(self, discord_id: str) -> Member | None:
        def _fetch():
            return (
                self._db.table("bot_members")
                .select("*")
                .eq("discord_id", discord_id)
                .limit(1)
                .execute()
            )

        result = await asyncio.get_event_loop().run_in_executor(None, _fetch)
        if not result.data:
            return None
        return self._parse(result.data[0])

    async def get_all_active(self) -> list[Member]:
        def _fetch():
            return self._db.table("bot_members").select("*").execute()

        result = await asyncio.get_event_loop().run_in_executor(None, _fetch)
        return [self._parse(row) for row in result.data]

    async def update_github_username(self, discord_id: str, github_username: str) -> Member:
        def _update():
            return (
                self._db.table("bot_members")
                .update({"github_username": github_username})
                .eq("discord_id", discord_id)
                .execute()
            )

        result = await asyncio.get_event_loop().run_in_executor(None, _update)
        if not result.data:
            raise ValueError(f"No member found with discord_id {discord_id!r}")

        log.info("member.github_linked", discord_id=discord_id, github_username=github_username)
        return self._parse(result.data[0])

    async def get_tier_max(self, discord_id: str) -> str:
        member = await self.get_by_discord_id(discord_id)
        if member is None:
            raise ValueError(f"No member found with discord_id {discord_id!r}")
        return member.tier_max

    async def exists(self, discord_id: str) -> bool:
        return await self.get_by_discord_id(discord_id) is not None