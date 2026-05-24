from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone

import structlog
from rich import _timer
from sqlalchemy.ext.asyncio import result
from supabase import Client
from watchfiles import awatch

from app.models.badge import Badge
from app.models.ticket import Ticket, TicketCreate, TierViolationError
from app.services.badge_service import BadgeService
from app.services.member_service import MemberService
from app.services.xp_service import XPService
from app.utils.badge_broadcast import get_current_streak

log = structlog.get_logger()

_VALID_STATUSES = {"todo", "in_progress", "in_review", "done"}
_VALID_TIERS = {"T1", "T2", "T3"}
_TIER_ORDER = {"T1": 1, "T2": 2, "T3": 3}


@dataclass
class CloseResult:
    ticket: Ticket
    xp_awarded: int = 0
    new_level: int = 1
    level_up: bool = False
    badges: list[Badge] = field(default_factory=list)


@dataclass
class AssignResult:
    ticket: Ticket
    first_t2: bool


class TicketService:
    def __init__(
            self,
            db: Client,
            members: MemberService,
            xp_service=None,
            streak_service=None
    ) -> None:
        self._db = db
        self._members = members
        self._xp = xp_service
        self._streak = streak_service

    # Helpers

    def _parse(self, data: dict) -> Ticket:
        return Ticket.model_validate(data)

    async def _run(self, fn):
        return await asyncio.get_event_loop().run_in_executor(None, fn)

    async def _get_by_id(self, ticket_id: str) -> Ticket | None:
        def _suffix():
            return (
                self._db.table("bot_tickets")
                .select("*")
                .ilike("id_text", f"%{ticket_id}")
                .limit(1)
                .execute()
            )

        if len(ticket_id) < 36:
            result = await self._run(_suffix)
            return self._parse(result.data[0]) if result.data else None

        def _exact():
            return (
                self._db.table("bot_tickets")
                .select("*")
                .eq("id", ticket_id)
                .limit(1)
                .execute()
            )

        result = await self._run(_exact)
        if result.data:
            return self._parse(result.data[0])

        result = await self._run(_suffix)
        if not result.data:
            return None
        return self._parse(result.data[0])


    # Public API

    async def create(
            self,
            payload: TicketCreate,
            created_by_discord_id: str
    ) -> Ticket:
        creator = await self._members.get_by_discord_id(created_by_discord_id)
        created_by_id = str(creator.id) if creator else None

        row: dict = {
            "title": payload.title,
            "tier": payload.tier,
            "status": "todo",
            "priority": payload.priority
        }
        if payload.description:
            row["description"] = payload.description
        if payload.phase:
            row["phase"] = payload.phase
        if payload.deadline:
            row["deadline"] = payload.deadline.isoformat()
        if created_by_id:
            row["created_by"] = created_by_id

        def _insert():
            return self._db.table("bot_tickets").insert(row).execute()

        result = await self._run(_insert)
        ticket = self._parse(result.data[0])
        log.info("ticket.created", ticket_id = str(ticket.id), tier=ticket.tier, title=ticket.title)
        return ticket

    async def get(self, ticket_id: str) -> Ticket | None:
        return await self._get_by_id(ticket_id)

    async def get_all(
            self,
            status: str | None = None,
            phase: str | None = None
    ) -> list[Ticket]:
        def _fetch():
            q = self._db.table("bot_tickets").select("*").neq("status", "done")
            if status:
                q = q.eq("status", status)
            if phase:
                q = q.eq("phase", phase)
            return q.order("created_at", desc=False).execute()

        result = await self._run(_fetch)
        return [self._parse(r) for r in result.data]

    async def get_by_assignee(self, discord_id: str) -> list[Ticket]:
        member = await self._members.get_by_discord_id(discord_id)
        if member is None:
            return []

        member_id = str(member.id)

        def _fetch():
            return (
                self._db.table("bot_tickets")
                .select("*")
                .eq("assignee_id", member_id)
                .neq("status", "done")
                .order("created_at", desc=False)
                .execute()
            )

        result = await self._run(_fetch)
        return [self._parse(r) for r in result.data]

    async def validate_tier_eligibility(
            self,
            assignee_discord_id: str,
            tier: str
    ) -> bool:
        member = await self._members.get_by_discord_id(assignee_discord_id)
        if member is None:
            raise ValueError(f"No member found with discord_id {assignee_discord_id!r}")

        if member.role in ("lead", "professor"):
            return True

        if tier == "T3":
            raise TierViolationError(
                assignee_name=member.discord_name,
                requested_tier="T3",
                max_tier=member.tier_max
            )

        if tier == "T2" and _TIER_ORDER[member.tier_max] < _TIER_ORDER["T2"]:
            raise TierViolationError(
                assignee_name=member.discord_name,
                requested_tier="T2",
                max_tier=member.tier_max
            )

        return True

    async def _is_first_t2(self, assignee_discord_id: str) -> bool:
        member = await self._members.get_by_discord_id(assignee_discord_id)
        if member is None or member.role in ("lead", "professor"):
            return False

        member_id = str(member.id)

        def _count():
            return (
                self._db.table("bot_tickets")
                .select("id", count="exact")
                .eq("assignee_id", member_id)
                .eq("tier", "T2")
                .execute()
            )

        result = await self._run(_count)
        return (result.count or 0) == 0

    async def assign(
            self,
            ticket_id: str,
            assignee_discord_id: str
    ) -> AssignResult:
        ticket = await self._get_by_id(ticket_id)
        if ticket is None:
            raise ValueError(f"Ticket {ticket_id!r} not found")

        await self.validate_tier_eligibility(assignee_discord_id, ticket.tier)

        first_t2 = False
        if ticket.tier == "T2":
            first_t2 = await self._is_first_t2(assignee_discord_id)

        assignee = await self._members.get_by_discord_id(assignee_discord_id)
        assert assignee is not None
        assignee_id = str(assignee.id)

        def _update():
            return (
                self._db.table("bot_tickets")
                .update({"assignee_id": assignee_id, "status": "in_progress"})
                .eq("id", str(ticket.id))
                .execute()
            )

        result = await self._run(_update)
        updated = self._parse(result.data[0])
        log.info(
            "ticket.assigned",
            ticket_id=str(ticket.id),
            assignee=assignee_discord_id,
            first_t2=first_t2
        )
        return AssignResult(ticket=updated, first_t2=first_t2)

    async def update_status(
            self,
            ticket_id: str,
            new_status: str,
            updated_by_discord_id: str
    ) -> Ticket:
        if new_status not in _VALID_STATUSES:
            raise ValueError(f"Invalid status: {new_status!r}")

        ticket = await self._get_by_id(ticket_id)
        if ticket is None:
            raise ValueError(f"Ticket {ticket_id!r} not found")

        if new_status == "done":
            close_result = await self.close(ticket_id, updated_by_discord_id)
            return close_result.ticket

        def _update():
            return (
                self._db.table("bot_tickets")
                .update({"status": new_status, "updated_at": datetime.now(timezone.utc).isoformat()})
                .eq("id", str(ticket.id))
                .execute()
            )

        result = await self._run(_update)
        updated = self._parse(result.data[0])
        log.info("ticket.status_updated", ticket_id=str(ticket.id), new_status=new_status)
        return updated

    async def close(self, ticket_id: str, closed_by_discord_id: str) -> CloseResult:
        ticket = await self._get_by_id(ticket_id)
        if ticket is None:
            raise ValueError(f"Ticket {ticket_id!r} not found")

        now = datetime.now(timezone.utc).isoformat()

        def _close():
            return (
                self._db.table("bot_tickets")
                .update({"status": "done", "closed_at": now, "updated_at": now})
                .eq("id", str(ticket.id))
                .execute()
            )

        result = await self._run(_close)
        closed = self._parse(result.data[0])

        closer = await self._members.get_by_discord_id(closed_by_discord_id)
        if closer:
            await self._increment_tickets_closed(str(closer.id))

        badges: list[Badge] = []
        xp_svc = self._xp
        badge_xp = xp_svc or XPService(self._db)
        badge_svc = BadgeService(self._db, badge_xp)

        xp_result = None
        if self._xp and closer:
            action = f"close_{closed.tier.lower()}"
            xp_result = await xp_svc.award(str(closer.id), action, metadata={"ticket_id": str(closed.id)})
            clutch_ctx = closed.model_dump(mode="json")
            badges.extend(
                await badge_svc.check_and_award(str(closer.id), action, {"ticket": clutch_ctx})
            )

        if self._streak and closer:
            await self._streak.record_activity(str(closer.id), "ticket_closed")
            streak_n = await get_current_streak(self._db, str(closer.id))
            badges.extend(
                await badge_svc.check_and_award(
                    str(closer.id), "streak_check", {"current_streak": streak_n}
                )
            )

        log.info("ticket.closed", ticket_id=str(closed.id), closed_by=closed_by_discord_id)

        if xp_result:
            return CloseResult(
                ticket=closed,
                xp_awarded=xp_result.xp_awarded,
                new_level=xp_result.new_level,
                level_up=xp_result.level_up,
                badges=badges
            )
        return CloseResult(ticket=closed)

    async def _increment_tickets_closed(self, member_id: str) -> None:
        def _fetch_stats():
            return (
                self._db.table("bot_member_stats")
                .select("tickets_closed")
                .eq("member_id", member_id)
                .limit(1)
                .execute()
            )

        stats_result = await self._run(_fetch_stats)
        current = stats_result.data[0]["tickets_closed"] if stats_result.data else 0

        def _update_stats():
            return (
                self._db.table("bot_member_stats")
                .update({"tickets_closed": current + 1, "updated_at": datetime.now(timezone.utc).isoformat()})
                .eq("member_id", member_id)
                .execute()
            )

        await self._run(_update_stats)

    async def update_discord_msg_id(self, ticket_id: str, msg_id: str) -> None:
        def _update():
            return (
                self._db.table("bot_tickets")
                .update({"discord_msg_id": msg_id})
                .eq("id", ticket_id)
                .execute()
            )

        await self._run(_update)

