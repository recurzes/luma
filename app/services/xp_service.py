from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from unittest import result

import structlog
from supabase import Client
from watchfiles import awatch

from app.models.member import MemberStats
from app.models.xp import LeaderboardEntry, XPLedgerEntry

log = structlog.get_logger()

_XP_MAP: dict[str, int] = {
    "close_t1": 10,
    "close_t2": 25,
    "close_t3": 50,
    "commit": 5,
    "pr_merged": 20,
    "pr_reviewed": 15,
    "helped_stuck": 15,
    "standup": 5,
    "shoutout_given": 10,
    "shoutout_recv": 10,
    "knowledge_drop": 8,
    "blitz_join": 5,
    "blitz_checkin": 10,
    "blitz_showcase": 25,
    "blitz_complete": 50,
    "blitz_first_in": 5,
    "journal_entry": 5,
    "journal_mood": 2,
    "journal_adr": 15,
    "track_checkpoint": 10,
    "track_25pct": 15,
    "track_50pct": 20,
    "track_complete": 75,
}

_LEVEL_THRESHOLDS = [0, 100, 250, 500, 900, 1400, 2000]
_LEVEL_TITLES = [
    "Junior Dev",
    "Apprentice",
    "Contributor",
    "Builder",
    "Craftsman",
    "Senior Dev",
    "Architect"
]


def compute_level(total_xp: int) -> int:
    level = 1
    for i, threshold in enumerate[int](_LEVEL_THRESHOLDS):
        if total_xp >= threshold:
            level = i + 1

    return min(level, len(_LEVEL_THRESHOLDS))


def level_title(level: int) -> str:
    return _LEVEL_TITLES[min(level - 1, len(_LEVEL_TITLES) - 1)]


@dataclass
class XPAwardResult:
    new_total: int
    new_level: int
    level_up: bool
    xp_awarded: int
    duplicate: bool = False


class XPService:
    def __init__(self, db: Client) -> None:
        self._db = db

    async def _run(self, fn):
        return await asyncio.get_event_loop().run_in_executor(None, fn)

    async def award(
            self,
            member_id: str,
            action: str,
            metadata: dict | None = None,
            xp_override: int | None = None,
            dedupe_key: str | None = None
    ) -> XPAwardResult:
        """Award XP for `action`.

        `dedupe_key` makes the award idempotent: a second call with the same member, action
        and key awards nothing. Use it wherever the caller may be retried (GitHub events).
        """
        if action not in _XP_MAP:
            log.warning("xp.unknown_action", action=action)
        # xp_override is for actions whose value is set per row, e.g. a checkpoint's xp_value.
        xp = xp_override if xp_override is not None else _XP_MAP.get(action, 0)

        def _fetch_stats():
            return (
                self._db.table("bot_member_stats")
                .select("total_xp, level")
                .eq("member_id", member_id)
                .limit(1)
                .execute()
            )

        if dedupe_key is not None:
            def _already_awarded():
                return (
                    self._db.table("bot_xp_ledger")
                    .select("id")
                    .eq("member_id", member_id)
                    .eq("action", action)
                    .eq("metadata->>dedupe_key", dedupe_key)
                    .limit(1)
                    .execute()
                )

            if (await self._run(_already_awarded)).data:
                stats = (await self._run(_fetch_stats)).data
                log.info("xp.duplicate_skipped", member_id=member_id, action=action, dedupe_key=dedupe_key)
                return XPAwardResult(
                    new_total=stats[0]["total_xp"] if stats else 0,
                    new_level=stats[0]["level"] if stats else 1,
                    level_up=False,
                    xp_awarded=0,
                    duplicate=True
                )
            metadata = {**(metadata or {}), "dedupe_key": dedupe_key}

        def _insert_ledger():
            row: dict = {
                "member_id": member_id,
                "action": action,
                "xp": xp,
                "awarded_at": datetime.now(timezone.utc).isoformat()
            }
            if metadata:
                row["metadata"] = metadata
            return self._db.table("bot_xp_ledger").insert(row).execute()

        await self._run(_insert_ledger)

        stats_result = await self._run(_fetch_stats)
        if stats_result.data:
            old_total = stats_result.data[0]["total_xp"]
            old_level = stats_result.data[0]["level"]
        else:
            old_total = 0
            old_level = 1

        new_total = old_total + xp
        new_level = compute_level(new_total)
        level_up = new_level > old_level

        def _update_stats():
            return (
                self._db.table("bot_member_stats")
                .update(
                    {
                        "total_xp": new_total,
                        "level": new_level,
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    }
                )
                .eq("member_id", member_id)
                .execute()
            )

        await self._run(_update_stats)

        log.info(
            "xp.awarded",
            member_id=member_id,
            action=action,
            xp=xp,
            new_total=new_total,
            level_up=level_up
        )
        return XPAwardResult(
            new_total=new_total,
            new_level=new_level,
            level_up=level_up,
            xp_awarded=xp
        )

    async def get_stats(self, member_id: str) -> MemberStats | None:
        def _fetch():
            return (
                self._db.table("bot_member_stats")
                .select("*")
                .eq("member_id", member_id)
                .limit(1)
                .execute()
            )

        result = await self._run(_fetch)
        if not result.data:
            return None
        return MemberStats.model_validate(result.data[0])

    async def get_recent_ledger(self, member_id: str, limit: int = 5) -> list[XPLedgerEntry]:
        def _fetch():
            return (
                self._db.table("bot_xp_ledger")
                .select("*")
                .eq("member_id", member_id)
                .order("awarded_at", desc=True)
                .limit(limit)
                .execute()
            )

        result = await self._run(_fetch)
        return [XPLedgerEntry.model_validate(r) for r in result.data]

    async def leaderboard(self, guild_id: str, limit: int = 10) -> list[LeaderboardEntry]:
        """Top members of one server by XP."""
        def _fetch():
            return (
                self._db.table("bot_member_stats")
                .select(
                    "member_id, total_xp, level, current_streak, "
                    "bot_members!inner(discord_id, discord_name, guild_id)"
                )
                .eq("bot_members.guild_id", guild_id)
                .order("total_xp", desc=True)
                .limit(limit)
                .execute()
            )

        result = await self._run(_fetch)

        entries: list[LeaderboardEntry] = []
        for rank, row in enumerate(result.data, start=1):
            m = row.get("bot_members")
            if not m:
                continue
            entries.append(
                LeaderboardEntry(
                    rank=rank,
                    member_id=row["member_id"],
                    discord_id=m["discord_id"],
                    discord_name=m["discord_name"],
                    total_xp=row["total_xp"],
                    level=row["level"],
                    current_streak=row["current_streak"]
                )
            )

        return entries
