from __future__ import annotations

from uuid import UUID

import bcrypt
from supabase import Client

from app.models.track import *
from app.services.xp_service import XPService
from app.services.badge_service import BadgeService

from datetime import datetime, timezone, timedelta

MILESTONE_XP = {25: 15, 50: 20, 100: 75}


class TrackService:
    def __init__(self, db: Client, xp_svc: XPService, badge_svc: BadgeService):
        self.db = db
        self.xp_svc = xp_svc
        self.badge_svc = badge_svc


    async def enroll(self, member_id: UUID, track_id: UUID) -> TrackProgress:
        existing = await self.get_progress(member_id, track_id)
        if existing:
            return existing

        result = (
            self.db.table("companion_member_track_progress")
            .insert({
                "member_id": str(member_id),
                "track_id": str(track_id)
            })
            .execute()
        )
        await self.badge_svc.check_and_award(member_id, trigger_event="track_enroll_first")
        return TrackProgress(**result.data[0])


    async def complete_checkpoint(
            self,
            member_id: UUID,
            checkpoint_id: UUID,
            answer: str | None = None
    ) -> tuple[Checkpoint, int]:
        checkpoint = await self.get_checkpoint(checkpoint_id)
        if not checkpoint:
            raise ValueError("Checkpoint not found")

        progress = await self.get_progress(member_id, checkpoint.track_id)
        if not progress:
            raise ValueError("You are not enrolled in this track")

        already = (
            self.db.table("companion_checkpoint_completions")
            .select("id")
            .eq("member_id", str(member_id))
            .eq("checkpoint_id", str(checkpoint_id))
            .maybe_single()
            .execute()
        )
        if already.data:
            raise ValueError("Checkpoint already completed")

        if checkpoint.answer_hash and answer:
            if not bcrypt.checkpw(
                answer.lower().strip().encode(), checkpoint.answer_hash.encode()
            ):
                raise ValueError("Incorrect answer. Try again")
        elif checkpoint.answer_hash and not answer:
            raise ValueError(
                "This checkpoint requires an answer. "
                "Use `/track checkpoint done [id] answer:[your answer]`"
            )

        self.db.table("companion_checkpoint_completions").insert({
            "member_id": str(member_id),
            "checkpoint_id": str(checkpoint_id)
        }).execute()

        new_count = (progress.checkpoints_done or 0) + 1
        total = await self._total_checkpoints(checkpoint.track_id)
        pct = int((new_count / total) * 100)

        update_payload: dict = {"checkpoints_done": new_count}
        if pct == 100:
            update_payload["completed_at"] = datetime.now(timezone.utc).isoformat()

        self.db.table("companion_member_track_progress").update(
            update_payload
        ).eq("member_id", str(member_id)).eq("track_id", str(checkpoint.track_id)).execute()

        xp = checkpoint.xp_value
        await self.xp_svc.award(str(member_id), "track_checkpoint", {"xp": xp})

        for milestone_pct, bonus_xp in MILESTONE_XP.items():
            if pct >= milestone_pct > (pct - (100 // total)):
                await self.xp_svc.award(str(member_id), f"track_{milestone_pct}pct", {"bonus_xp": bonus_xp})
                xp += bonus_xp

        if pct == 100:
            await self.badge_svc.check_and_award(str(member_id), trigger_event="track_complete")

        return checkpoint, xp


    # Queries
    async def list_tracks(self) -> list[Track]:
        result = (
            self.db.table("companion_tracks")
            .select("*")
            .order("is_builtin.desc, name")
            .execute()
        )
        return [Track(**r) for r in result.data]


    async def get_progress(self, member_id: UUID, track_id: UUID) -> TrackProgress | None:
        result = (
            self.db.table("companion_member_track_progress")
            .select("*")
            .eq("member_id", str(member_id))
            .eq("track_id", str(track_id))
            .maybe_single()
            .execute()
        )
        return TrackProgress(**result.data) if result.data else None


    async def get_checkpoint(self, checkpoint_id: UUID) -> Checkpoint | None:
        result = (
            self.db.table("companion_track_checkpoints")
            .select("*")
            .eq("id", str(checkpoint_id))
            .maybe_single()
            .execute()
        )
        return Checkpoint(**result.data) if result.data else None


    async def get_next_checkpoint(self, member_id: UUID, track_id: UUID) -> Checkpoint | None:
        done_ids = (
            self.db.table("companion_checkpoint_completions")
            .select("checkpoint_id")
            .eq("member_id", str(member_id))
            .execute()
        )
        done_set = {r["checkpoint_id"] for r in done_ids.data}

        checkpoints = (
            self.db.table("companion_track_checkpoints")
            .select("*")
            .order("sequence")
            .execute()
        )
        for cp in checkpoints.data:
            if cp["id"] not in done_set:
                return Checkpoint(**cp)
        return None


    async def get_stale_enrollments(self, inactive_days: int = 7) -> list[dict]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=inactive_days)).isoformat()
        result = self.db.rpc("get_stale_track_enrollments", {"cutoff": cutoff}).execute()
        return result.data


    async def _total_checkpoints(self, track_id: UUID) -> int:
        result = (
            self.db.table("companion_track_checkpoints")
            .select("id", count="exact")
            .eq("track_id", str(track_id))
            .execute()
        )
        return result.count or 1