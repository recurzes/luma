from __future__ import annotations

from uuid import UUID

import bcrypt
from supabase import Client

from app.models.track import *
from app.services.xp_service import XPService
from app.services.badge_service import BadgeService
from app.utils.short_id import parse_short_id, parse_uuid
from app.utils.db import row_or_none, run_query

from datetime import datetime, timezone, timedelta

MILESTONE_ACTIONS = {25: "track_25pct", 50: "track_50pct", 100: "track_complete"}


class TrackService:
    def __init__(self, db: Client, xp_svc: XPService, badge_svc: BadgeService):
        self.db = db
        self.xp_svc = xp_svc
        self.badge_svc = badge_svc


    async def enroll(self, member_id: UUID, track_id: UUID) -> TrackProgress:
        existing = await self.get_progress(member_id, track_id)
        if existing:
            return existing

        result = await run_query(
            self.db.table("companion_member_track_progress")
            .insert({
                "member_id": str(member_id),
                "track_id": str(track_id)
            })
        )
        await self.badge_svc.check_and_award(str(member_id), trigger_event="track_enroll_first")
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

        already = await run_query(
            self.db.table("companion_checkpoint_completions")
            .select("id")
            .eq("member_id", str(member_id))
            .eq("checkpoint_id", str(checkpoint_id))
            .maybe_single()
        )
        if row_or_none(already):
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

        await run_query(self.db.table("companion_checkpoint_completions").insert({
            "member_id": str(member_id),
            "checkpoint_id": str(checkpoint_id)
        }))

        new_count = (progress.checkpoints_done or 0) + 1
        total = await self._total_checkpoints(checkpoint.track_id)
        pct = int((new_count / total) * 100)

        update_payload: dict = {"checkpoints_done": new_count}
        if pct == 100:
            update_payload["completed_at"] = datetime.now(timezone.utc).isoformat()

        await run_query(self.db.table("companion_member_track_progress").update(
            update_payload
        ).eq("member_id", str(member_id)).eq("track_id", str(checkpoint.track_id)))

        metadata = {"checkpoint_id": str(checkpoint_id)}
        result = await self.xp_svc.award(
            str(member_id), "track_checkpoint", metadata, xp_override=checkpoint.xp_value
        )
        xp = result.xp_awarded

        previous_pct = int(((new_count - 1) / total) * 100)
        for milestone_pct, action in MILESTONE_ACTIONS.items():
            if previous_pct < milestone_pct <= pct:
                bonus = await self.xp_svc.award(str(member_id), action, metadata)
                xp += bonus.xp_awarded

        if pct == 100:
            await self.badge_svc.check_and_award(str(member_id), trigger_event="track_complete")

        return checkpoint, xp


    # Queries
    async def list_tracks(self) -> list[Track]:
        result = await run_query(
            self.db.table("companion_tracks")
            .select("*")
            .order("is_builtin.desc, name")
        )
        return [Track(**r) for r in result.data]


    async def get_progress(self, member_id: UUID, track_id: UUID) -> TrackProgress | None:
        result = await run_query(
            self.db.table("companion_member_track_progress")
            .select("*")
            .eq("member_id", str(member_id))
            .eq("track_id", str(track_id))
            .maybe_single()
        )
        row = row_or_none(result)
        return TrackProgress(**row) if row else None


    async def get_checkpoint(self, checkpoint_id: UUID) -> Checkpoint | None:
        result = await run_query(
            self.db.table("companion_track_checkpoints")
            .select("*")
            .eq("id", str(checkpoint_id))
            .maybe_single()
        )
        row = row_or_none(result)
        return Checkpoint(**row) if row else None


    async def get_next_checkpoint(self, member_id: UUID, track_id: UUID) -> Checkpoint | None:
        done_ids = await run_query(
            self.db.table("companion_checkpoint_completions")
            .select("checkpoint_id")
            .eq("member_id", str(member_id))
        )
        done_set = {r["checkpoint_id"] for r in done_ids.data}

        checkpoints = await run_query(
            self.db.table("companion_track_checkpoints")
            .select("*")
            .eq("track_id", str(track_id))
            .order("sequence")
        )
        for cp in checkpoints.data:
            if cp["id"] not in done_set:
                return Checkpoint(**cp)
        return None


    async def find_checkpoint_by_short_id(self, member_id: UUID, value: str) -> Checkpoint | None:
        """Resolve the 8-char ID shown in DMs, searching only the member's enrolled tracks.

        The ID column is a UUID, which Postgres cannot ILIKE, so the prefix match happens here.
        """
        full_id = parse_uuid(value)
        if full_id is not None:
            return await self.get_checkpoint(full_id)

        short_id = parse_short_id(value)
        if short_id is None:
            return None

        enrolled = await run_query(
            self.db.table("companion_member_track_progress")
            .select("track_id")
            .eq("member_id", str(member_id))
        )
        track_ids = [r["track_id"] for r in enrolled.data]
        if not track_ids:
            return None

        checkpoints = await run_query(
            self.db.table("companion_track_checkpoints")
            .select("*")
            .in_("track_id", track_ids)
        )
        matches = [cp for cp in checkpoints.data if cp["id"].lower().startswith(short_id)]
        if len(matches) > 1:
            raise ValueError(f"Checkpoint ID `{short_id}` matches more than one checkpoint")
        return Checkpoint(**matches[0]) if matches else None


    async def get_stale_enrollments(self, inactive_days: int = 7) -> list[dict]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=inactive_days)).isoformat()
        result = await run_query(self.db.rpc("get_stale_track_enrollments", {"cutoff": cutoff}))
        return result.data


    async def _total_checkpoints(self, track_id: UUID) -> int:
        result = await run_query(
            self.db.table("companion_track_checkpoints")
            .select("id", count="exact")
            .eq("track_id", str(track_id))
        )
        return result.count or 1