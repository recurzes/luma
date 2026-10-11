from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone

import structlog
from supabase import Client

from app.models.phase import Phase, PhaseCriteria

log = structlog.get_logger()

_MOTIVATIONAL = [
    "The best code is yet to come — let's build it",
    "Phase complete. Time to level up the whole team",
    "One step closed to shipping something great",
    "Progress is a habit. Keep the momentum",
    "Every phase makes the next one easier",
    "The foundation is solid. Build higher",
    "Done is better than perfect — until the next phase"
]


class PhaseService:
    """Phases of one server: every query is filtered by the guild given here."""

    def __init__(self, db: Client, guild_id: str) -> None:
        self._db = db
        self._guild_id = guild_id

    async def _run(self, fn):
        return await asyncio.get_event_loop().run_in_executor(None, fn)

    async def get_current(self) -> Phase | None:
        def _fetch():
            return (
                self._db.table("bot_phases")
                .select("*")
                .eq("guild_id", self._guild_id)
                .eq("status", "active")
                .limit(1)
                .execute()
            )

        result = await self._run(_fetch)
        if not result.data:
            return None
        return Phase.model_validate(result.data[0])

    async def get_all(self) -> list[Phase]:
        def _fetch():
            return (
                self._db.table("bot_phases")
                .select("*")
                .eq("guild_id", self._guild_id)
                .order("key")
                .execute()
            )

        result = await self._run(_fetch)
        return [Phase.model_validate(r) for r in result.data]

    async def create(self, key: str, name: str, description: str | None = None) -> Phase:
        """Add a phase. The first phase of a server starts active; later ones wait as pending."""
        existing = await self.get_all()
        if any(p.key == key for p in existing):
            raise ValueError(f"A phase with key `{key}` already exists in this server")

        row = {
            "guild_id": self._guild_id,
            "key": key,
            "name": name,
            "description": description,
            "status": "pending" if existing else "active",
        }
        if not existing:
            row["started_at"] = datetime.now(timezone.utc).isoformat()

        result = await self._run(lambda: self._db.table("bot_phases").insert(row).execute())
        log.info("phase.created", guild_id=self._guild_id, phase_key=key, status=row["status"])
        return Phase.model_validate(result.data[0])

    async def get_by_key(self, key: str) -> Phase | None:
        result = await self._run(
            lambda: (
                self._db.table("bot_phases")
                .select("*")
                .eq("guild_id", self._guild_id)
                .eq("key", key)
                .limit(1)
                .execute()
            )
        )
        return Phase.model_validate(result.data[0]) if result.data else None

    async def add_criterion(self, phase_id: str, description: str) -> PhaseCriteria:
        result = await self._run(
            lambda: (
                self._db.table("bot_phase_criteria")
                .insert({"phase_id": phase_id, "description": description})
                .execute()
            )
        )
        return PhaseCriteria.model_validate(result.data[0])

    async def ticket_counts(self, phase_key: str) -> tuple[int, int]:
        """(open, closed) tickets tagged with this phase in this server."""
        def _count(done: bool):
            q = (
                self._db.table("bot_tickets")
                .select("id", count="exact")
                .eq("guild_id", self._guild_id)
                .eq("phase", phase_key)
            )
            return (q.eq("status", "done") if done else q.neq("status", "done")).execute()

        open_res = await self._run(lambda: _count(False))
        closed_res = await self._run(lambda: _count(True))
        return open_res.count or 0, closed_res.count or 0

    async def get_criteria(self, phase_id: str) -> list[PhaseCriteria]:
        def _fetch():
            return (
                self._db.table("bot_phase_criteria")
                .select("*")
                .eq("phase_id", phase_id)
                .order("id")
                .execute()
            )

        result = await self._run(_fetch)
        return [PhaseCriteria.model_validate(r) for r in result.data]

    async def check_criterion(
            self,
            phase_id: str,
            criterion_index: int,
            checked_by_id: str
    ) -> PhaseCriteria | None:
        criteria = await self.get_criteria(phase_id)
        if criterion_index < 1 or criterion_index > len(criteria):
            return None
        target = criteria[criterion_index - 1]

        def _update():
            return (
                self._db.table("bot_phase_criteria")
                .update({
                    "checked": True,
                    "checked_by": checked_by_id,
                    "checked_at": datetime.now(timezone.utc).isoformat()
                })
                .eq("id", str(target.id))
                .execute()
            )

        result = await self._run(_update)
        if not result.data:
            return None
        return PhaseCriteria.model_validate(result.data[0])

    async def complete_phase(self, phase_key: str, lead_id: str) -> Phase | None:
        now = datetime.now(timezone.utc).isoformat()

        def _complete():
            return (
                self._db.table("bot_phases")
                .update({"status": "complete", "completed_at": now})
                .eq("guild_id", self._guild_id)
                .eq("key", phase_key)
                .execute()
            )

        result = await self._run(_complete)
        if not result.data:
            return None

        def _fetch_pending():
            return (
                self._db.table("bot_phases")
                .select("*")
                .eq("guild_id", self._guild_id)
                .eq("status", "pending")
                .order("key")
                .limit(1)
                .execute()
            )

        pending = await self._run(_fetch_pending)
        if pending.data:
            next_key = pending.data[0]["key"]

            def _activate():
                return (
                    self._db.table("bot_phases")
                    .update({"status": "active", "started_at": now})
                    .eq("guild_id", self._guild_id)
                    .eq("key", next_key)
                    .execute()
                )

            await self._run(_activate)
            log.info("phase.activated", phase_key=next_key)

        log.info("phase.completed", phase_key=phase_key, completed_by=lead_id)
        return Phase.model_validate(result.data[0])

    async def phase_summary(self, phase_key: str) -> dict:
        phase_result = await self._run(
            lambda : (
                self._db.table("bot_phases")
                .select("id")
                .eq("guild_id", self._guild_id)
                .eq("key", phase_key)
                .limit(1)
                .execute()
            )
        )

        if not phase_result.data:
            return {}
        phase_id = phase_result.data[0]["id"]

        tickets_result = await self._run(
            lambda : (
                self._db.table("bot_tickets")
                .select("assignee_id, tier")
                .eq("guild_id", self._guild_id)
                .eq("status", "done")
                .eq("phase", phase_key)
                .execute()
            )
        )

        stats_result = await self._run(
            lambda: (
                self._db.table("bot_member_stats")
                .select(
                    "member_id, total_xp, level, current_streak, longest_streak, tickets_closed, "
                    "bot_members!inner(discord_name, guild_id)"
                )
                .eq("bot_members.guild_id", self._guild_id)
                .order("total_xp", desc=True)
                .limit(20)
                .execute()
            )
        )
        names_by_id = {
            r["member_id"]: (r.get("bot_members") or {}).get("discord_name", "Unknown")
            for r in stats_result.data
        }

        tickets_by_member: dict[str, int] = {}
        for t in tickets_result.data:
            aid = t.get("assignee_id")
            if aid:
                tickets_by_member[aid] = tickets_by_member.get(aid, 0) + 1

        per_dev = []
        for row in stats_result.data:
            mid = row["member_id"]
            per_dev.append({
                "member_id": mid,
                "name": names_by_id.get(mid, "Unknown"),
                "total_xp": row["total_xp"],
                "level": row["level"],
                "current_streak": row["current_streak"],
                "tickets_closed": tickets_by_member.get(mid, 0)
            })

        return {
            "phase_key": phase_key,
            "per_dev": per_dev,
            "motivational": random.choice(_MOTIVATIONAL)
        }