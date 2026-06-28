from __future__ import annotations

import os
from uuid import UUID
from datetime import datetime, timezone, date, timedelta

from supabase import Client

from app.models.journal import JournalEntry, JournalEntryCreate, ADR
from app.services.xp_service import XPService


class JournalService:
    def __init__(self, db: Client, xp_svc: XPService):
        self.db = db
        self.xp_svc = xp_svc
        self._ai_enabled = os.getenv("COMPANION_AI_ENABLED", "false").lower() == "true"


    # Entries
    async def add_entry(self, payload: JournalEntryCreate) -> JournalEntry:
        result = (
            self.db.table("companion_journal_entries")
            .insert({
                "member_id": str(payload.member_id),
                "project_id": str(payload.project_id) if payload.project_id else None,
                "entry_type": payload.entry_type,
                "content": payload.content,
                "mood": payload.mood,
                "tags": payload.tags or []
            })
            .execute()
        )
        entry = JournalEntry(**result.data[0])

        today_count = await self._entry_count_today(payload.member_id)
        if today_count == 1:
            await self.xp_svc.award(payload.member_id, "journal_entry", 5)

        if payload.mood:
            await self.xp_svc.award(payload.member_id, "journal_mood", 2)

        return entry


    async def add_adr(
            self,
            member_id: UUID,
            project_id: UUID,
            title: str,
            context: str,
            decision: str,
            alternatives: str | None = None
    ) -> tuple[JournalEntry, ADR]:
        seq_result = (
            self.db.table("companion_adrs")
            .select("sequence")
            .eq("project_id", str(project_id))
            .order("sequence.desc")
            .limit(1)
            .maybe_single()
            .execute()
        )
        next_seq = (seq_result.data["sequence"] + 1) if seq_result.data else 1

        content = (
            f"**ADR #{next_seq}: {title}**\n\n"
            f"**Context:** {context}\n\n"
            f"**Decision:** {decision}\n"
            + (f"\n**Alternatives considered:** {alternatives}" if alternatives else "")
        )

        entry = await self.add_entry(JournalEntryCreate(
            member_id=member_id,
            project_id=project_id,
            entry_type="adr",
            content=content,
            mood=None,
            tags=["#adr"]
        ))

        addr_result = (
            self.db.table("companion_adrs")
            .insert({
                "entry_id": str(entry.id),
                "project_id": str(project_id),
                "sequence": next_seq,
                "title": title,
                "context": context,
                "decision": decision,
                "alternatives": alternatives,
                "status": "proposed"
            })
            .execute()
        )
        adr = ADR(**addr_result.data[0])

        await self.xp_svc.award(member_id, "journal_adr", 15)
        return entry, adr


    # Queries

    async def get_today(self, member_id: UUID, project_id: UUID | None = None) -> list[JournalEntry]:
        today = date.today().isoformat()
        query = (
            self.db.table("companion_journal_entries")
            .select("*")
            .eq("member_id", str(member_id))
            .gte("created_at", f"{today}T00:00:00")
            .lt("created_at", f"{today}T23:59:59")
            .order("created_at")
        )
        if project_id:
            query = query.eq("project_id", str(project_id))
        result = query.execute()
        return [JournalEntry(**r) for r in result.data]


    async def get_week(self, member_id: UUID, project_id: UUID | None = None) -> list[JournalEntry]:
        start = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        query = (
            self.db.table("companion_journal_entries")
            .select("*")
            .eq("member_id", str(member_id))
            .gte("created_at", start)
            .order("created_at")
        )
        if project_id:
            query = query.eq("project_id", str(project_id))
        result = query.execute()
        return [JournalEntry(**r) for r in result.data]


    # Helpers
    async def _entry_count_today(self, member_id: UUID) -> int:
        today = date.today().isoformat()
        result = (
            self.db.table("companion_journal_entries")
            .select("id", count="exact")
            .eq("member_id", str(member_id))
            .gte("created_at", f"{today}:T00:00:00")
            .execute()
        )
        return result.count or 0