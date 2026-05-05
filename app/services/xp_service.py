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
    "knowledge_drop": 8
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


class XPService:
    def __init__(self, db: Client) -> None:
        self._db = db

    async def _run(self, fn):
        return await asyncio.get_event_loop().run_in_executor(None, fn)

    async def award(
            self,
            member_id: str,
            action: str,
            metadata: dict | None = None
    ) -> XPAwardResult:
        xp = _XP_MAP.get(action, 0)
        if xp == 0:
            log.warning("xp.unknown_action", action=action)

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

        def _fetch_stats():
            return (
                self._db.table("bot_member_stats")
                .select("total_xp, level")
                .eq("member_id", member_id)
                .limit(1)
                .execute()
            )

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

    async def leaderboard(self, limit: int = 10) -> list[LeaderboardEntry]:
        def _fetch_stats():
            return (
                self._db.table("bot_member_stats")
                .select("member_id, total_xp, level, current_streak")
                .order("total_xp", desc=True)
                .limit(limit)
                .execute()
            )

        stats_result = await self._run(_fetch_stats)
        if not stats_result.data:
            return []

        member_ids = [r["member_id"] for r in stats_result.data]

        def _fetch_members():
            return (
                self._db.table("bot_members")
                .select("id, discord_id, discord_name")
                .in_("id", member_ids)
                .execute()
            )

        members_result = await self._run(_fetch_members)
        members_by_id = {r["id"]: r for r in members_result.data}

        entries: list[LeaderboardEntry] = []
        for rank, row in enumerate(stats_result.data, start=1):
            m = members_by_id.get(row["member_id"])
            if m is None:
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