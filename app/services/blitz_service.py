from __future__ import annotations

from uuid import UUID
from datetime import datetime, timezone, timedelta

from supabase import Client

from app.models.blitz import *
from app.services.xp_service import XPService
from app.services.badge_service import BadgeService

MILESTONES = {
    "75pct_done": 0.75,
    "50pct_done": 0.50,
    "25pct_left": 0.75
}
ONE_HOUR_MILESTONE = "1h_left"


def _rows(result) -> list:
    if result is None:
        return []
    data = getattr(result, "data", None)
    return data if isinstance(data, list) else []


def _first_row(result) -> dict | None:
    rows = _rows(result)
    return rows[0] if rows else None


class BlitzService:
    def __init__(self, db: Client, xp_svc: XPService, badge_svc: BadgeService):
        self.db = db
        self.xp_svc = xp_svc
        self.badge_svc = badge_svc

    async def create(self, payload: BlitzCreate) -> BlitzSession:
        existing = await self.get_active(payload.guild_id)
        if existing:
            raise ValueError(
                f"A blitz is already running: **{existing.technology}**. "
                f"End it first with `/blitz end`"
            )

        now = datetime.now(timezone.utc)
        ends_at = now + timedelta(hours=payload.duration_hours)

        result = (
            self.db.table("companion_blitz_sessions")
            .insert({
                "guild_id": payload.guild_id,
                "created_by": str(payload.created_by),
                "technology": payload.technology,
                "tech_category": payload.tech_category,
                "goal": payload.goal,
                "deliverable_type": payload.deliverable_type,
                "duration_hours": payload.duration_hours,
                "started_at": now.isoformat(),
                "ends_at": ends_at.isoformat(),
                "guild_channel_id": payload.guild_channel_id,
                "status": "active"
            })
            .execute()
        )
        row = _first_row(result)
        if row is None:
            raise ValueError("Failed to create blitz session")
        session = BlitzSession(**row)

        await self.join(session.id, payload.created_by)
        return session

    async def set_announce_msg(self, blitz_id: UUID, msg_id: str) -> None:
        self.db.table("companion_blitz_sessions").update(
            {"announce_msg_id": msg_id}
        ).eq("id", str(blitz_id)).execute()

    async def extend(self, blitz_id: UUID, extra_hours: int) -> BlitzSession:
        session = await self.get_by_id(blitz_id)
        if not session:
            raise ValueError("Blitz not found")
        if session.status != "active":
            raise ValueError("Can only extend an active blitz")

        new_ends_at = session.ends_at + timedelta(hours=extra_hours)
        new_extended = session.extended_hours + extra_hours

        result = (
            self.db.table("companion_blitz_sessions")
            .update({
                "ends_at": new_ends_at.isoformat(),
                "extended_hours": new_extended
            })
            .eq("id", str(blitz_id))
            .execute()
        )
        row = _first_row(result)
        if row is None:
            raise ValueError("Failed to update blitz session")
        return BlitzSession(**row)

    async def transition_to_showcase(self, blitz_id: UUID) -> BlitzSession:
        result = (
            self.db.table("companion_blitz_sessions")
            .update({"status": "showcase"})
            .eq("id", str(blitz_id))
            .execute()
        )
        row = _first_row(result)
        if row is None:
            raise ValueError("Failed to transition blitz to showcase")
        return BlitzSession(**row)

    async def complete(self, blitz_id: UUID) -> BlitzSession:
        now = datetime.now(timezone.utc)

        participants = await self.get_participants(blitz_id)
        showcases = await self.get_showcases(blitz_id)
        showcase_member_ids = {str(s.member_id) for s in showcases}

        for p in participants:
            mid = p.member_id
            if str(mid) in showcase_member_ids:
                await self.xp_svc.award(str(mid), "blitz_complete", {"xp": 50})

        result = (
            self.db.table("companion_blitz_sessions")
            .update({
                "status": "completed",
                "completed_at": now.isoformat()
            })
            .eq("id", str(blitz_id))
            .execute()
        )
        row = _first_row(result)
        if row is None:
            raise ValueError("Failed to complete blitz session")
        return BlitzSession(**row)
        now = datetime.now(timezone.utc)
        result = (
            self.db.table("companion_blitz_sessions")
            .update({
                "status": "cancelled",
                "cancelled_at": now.isoformat()
            })
            .eq("id", str(blitz_id))
            .execute()
        )
        row = _first_row(result)
        if row is None:
            raise ValueError("Failed to cancel blitz session")
        return BlitzSession(**row)
    async def join(self, blitz_id: UUID, member_id: UUID) -> BlitzParticipant:
        existing = await self.is_participant(blitz_id, member_id)
        if existing:
            raise ValueError("You're already in this blitz")

        result = (
            self.db.table("companion_blitz_participants")
            .insert({
                "blitz_id": str(blitz_id),
                "member_id": str(member_id)
            })
            .execute()
        )

        row = _first_row(result)
        if row is None:
            raise ValueError("Failed to join blitz")

        await self.xp_svc.award(str(member_id), "blitz_join")
        await self.badge_svc.check_and_award(str(member_id), trigger_event="blitz_join_first")
        return BlitzParticipant(**row)

    async def is_participant(self, blitz_id: UUID, member_id: UUID) -> bool:
        result = (
            self.db.table("companion_blitz_participants")
            .select("id")
            .eq("blitz_id", str(blitz_id))
            .eq("member_id", str(member_id))
            .limit(1)
            .execute()
        )
        return _first_row(result) is not None

    # Check-ins
    async def checkin(
            self,
            blitz_id: UUID,
            member_id: UUID,
            content: str,
            media_url: str | None = None,
            mood: int | None = None
    ) -> BlitzCheckin:
        session = await self.get_by_id(blitz_id)
        if not session or session.status != "active":
            raise ValueError("No active blitz to check in to")

        if not await self.is_participant(blitz_id, member_id):
            await self.join(blitz_id, member_id)

        result = (
            self.db.table("companion_blitz_checkins")
            .insert({
                "blitz_id": str(blitz_id),
                "member_id": str(member_id),
                "content": content,
                "media_url": media_url,
                "mood": mood,
                "posted_at": datetime.now(timezone.utc).isoformat()
            })
            .execute()
        )
        row = _first_row(result)
        if row is None:
            raise ValueError("Failed to save check-in")
        checkin = BlitzCheckin(**row)

        await self.xp_svc.award(str(member_id), "blitz_checkin")

        all_checkins = await self.get_checkins(blitz_id)
        if len(all_checkins) == 1:
            await self.xp_svc.award(str(member_id), "blitz_first_in")

        return checkin

    # Showcases
    async def submit_showcase(
            self,
            blitz_id: UUID,
            member_id: UUID,
            title: str,
            description: str,
            repo_url: str | None = None,
            demo_url: str | None = None,
            media_url: str | None = None
    ) -> BlitzShowcase:
        session = await self.get_by_id(blitz_id)
        if not session or session.status not in ("active", "showcase"):
            raise ValueError("Showcase submissions are closed")

        result = (
            self.db.table("companion_blitz_showcases")
            .upsert({
                "blitz_id": str(blitz_id),
                "member_id": str(member_id),
                "title": title,
                "description": description,
                "repo_url": repo_url,
                "demo_url": demo_url,
                "media_url": media_url,
                "submitted_at": datetime.now(timezone.utc).isoformat()
            },
                on_conflict="blitz_id,member_id"
            )
            .execute()
        )

        row = _first_row(result)
        if row is None:
            raise ValueError("Failed to submit showcase")

        await self.xp_svc.award(str(member_id), "blitz_showcase")
        await self.badge_svc.check_and_award(str(member_id), trigger_event="blitz_showcase_first")

        if session.started_at and session.ends_at:
            total = (session.ends_at - session.started_at).total_seconds()
            elapsed = (datetime.now(timezone.utc) - session.started_at).total_seconds()
            if elapsed / total <= 0.25:
                await self.badge_svc.check_and_award(str(member_id), trigger_event="blitz_speed_learner")

        return BlitzShowcase(**row)


    async def vote_showcase(self, showcase_id: UUID) -> int:
        current = (
            self.db.table("companion_blitz_showcases")
            .select("vote_count")
            .eq("id", str(showcase_id))
            .limit(1)
            .execute()
        )
        row = _first_row(current)
        if not row:
            raise ValueError("Showcase not found")

        new_count = (row["vote_count"] or 0) + 1
        self.db.table("companion_blitz_showcases").update(
            {"vote_count": new_count}
        ).eq("id", str(showcase_id)).execute()
        return new_count


    # Milestones
    async def mark_milestone(self, blitz_id: UUID, milestone: str) -> bool:
        existing = (
            self.db.table("companion_blitz_milestones")
            .select("id")
            .eq("blitz_id", str(blitz_id))
            .eq("milestone", milestone)
            .limit(1)
            .execute()
        )
        if _first_row(existing):
            return False

        self.db.table("companion_blitz_milestones").insert({
            "blitz_id": str(blitz_id),
            "milestone": milestone
        }).execute()
        return True


    async def calculate_pending_milestones(self, session: BlitzSession) -> list[str]:
        now = datetime.now(timezone.utc)
        if not session.started_at or not session.ends_at:
            return []

        total = (session.ends_at - session.started_at).total_seconds()
        elapsed = (now - session.started_at).total_seconds()
        remaining = (session.ends_at - now).total_seconds()

        pct_done = elapsed / total if total > 0 else 0
        pending = []

        if pct_done >= 0.50:
            pending.append("50pct_done")
        if pct_done >= 0.75:
            pending.append("75pct_done")
        if 0 < remaining <= 3600:
            pending.append(ONE_HOUR_MILESTONE)

        return pending


    # Queries
    async def get_by_id(self, blitz_id: UUID) -> BlitzSession | None:
        result = (
            self.db.table("companion_blitz_sessions")
            .select("*")
            .eq("id", str(blitz_id))
            .limit(1)
            .execute()
        )
        row = _first_row(result)
        return BlitzSession(**row) if row else None

    async def get_active(self, guild_id: str) -> BlitzSession | None:
        result = (
            self.db.table("companion_blitz_sessions")
            .select("*")
            .eq("guild_id", guild_id)
            .in_("status", ["active", "showcase"])
            .limit(1)
            .execute()
        )
        row = _first_row(result)
        return BlitzSession(**row) if row else None

    async def get_all_active(self) -> list[BlitzSession]:
        result = (
            self.db.table("companion_blitz_sessions")
            .select("*")
            .in_("status", ["active", "showcase"])
            .execute()
        )
        return [BlitzSession(**r) for r in _rows(result)]

    async def get_participants(self, blitz_id: UUID) -> list[BlitzParticipant]:
        result = (
            self.db.table("companion_blitz_participants")
            .select("*")
            .eq("blitz_id", str(blitz_id))
            .execute()
        )
        return [BlitzParticipant(**r) for r in _rows(result)]

    async def get_checkins(self, blitz_id: UUID) -> list[BlitzCheckin]:
        result = (
            self.db.table("companion_blitz_checkins")
            .select("*")
            .eq("blitz_id", str(blitz_id))
            .order("posted_at")
            .execute()
        )
        return [BlitzCheckin(**r) for r in _rows(result)]

    async def get_showcases(self, blitz_id: UUID) -> list[BlitzShowcase]:
        result = (
            self.db.table("companion_blitz_showcases")
            .select("*")
            .eq("blitz_id", str(blitz_id))
            .order("vote_count.desc")
            .execute()
        )
        return [BlitzShowcase(**r) for r in _rows(result)]

    async def get_history(self, guild_id: str, limit: int = 10) -> list[BlitzSession]:
        result = (
            self.db.table("companion_blitz_sessions")
            .select("*")
            .eq("guild_id", guild_id)
            .in_("status", ["completed", "cancelled"])
            .order("completed_at.desc")
            .limit(limit)
            .execute()
        )
        return [BlitzSession(**r) for r in _rows(result)]

    async def member_blitz_count(self, member_id: UUID) -> int:
        result = (
            self.db.table("companion_blitz_participants")
            .select("companion_blitz_sessions!inner(status)")
            .eq("member_id", str(member_id))
            .eq("companion_blitz_sessions.status", "completed")
            .execute()
        )
        return len(_rows(result))
