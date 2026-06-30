from __future__ import annotations

import os
from uuid import UUID
from datetime import datetime, timezone, date, timedelta

from supabase import Client

from app.models.journal import JournalEntry, JournalEntryCreate, ADR
from app.services.xp_service import XPService
import anthropic


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


    async def search(self, member_id: UUID, query_text: str, project_id: UUID | None = None) -> list[JournalEntry]:
        result = self.db.rpc("journal_fts_search", {
            "p_member_id": str(member_id),
            "p_project_id": str(project_id) if project_id else None,
            "p_query": query_text
        }).execute()
        return [JournalEntry(**r) for r in result.data]


    async def list_adrs(self, project_id: UUID) -> list[ADR]:
        result = (
            self.db.table("companion_adrs")
            .select("*")
            .eq("project_id", str(project_id))
            .order("sequence")
            .execute()
        )
        return [ADR(**r) for r in result.data]


    #Synthesis
    async def synthesize_sprint(
            self,
            member_id: UUID,
            project_id: UUID,
            sprint_start: datetime,
            sprint_end: datetime
    ) -> str:
        entries = (
            self.db.table("companion_journal_entries")
            .select("*")
            .eq("member_id", str(member_id))
            .eq("project_id", str(project_id))
            .gte("created_at", sprint_start.isoformat())
            .lte("created_at", sprint_start.isoformat())
            .order("created_at")
            .execute()
        )


    async def _ai_synthesis(self, entries: list[JournalEntry], adrs: list[ADR]) -> str:
        client = anthropic.Anthropic()
        entries_text = "\n\n".join(
            f"[{e.created_at.strftime('%b %d')}] ({e.entry_type}) {e.content}"
            for e in entries
        )
        adr_text = "\n".join(
            f"ADR #{a.sequence}: {a.title} - {a.decision}"
            for a in adrs
        ) or "None"

        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=600,
            messages=[{
                "role": "user",
                "content": (
                    f"Here are a developer's journal entries from this sprint:\n\n{entries_text}\n\n"
                    f"Key decisions made:\n{adr_text}\n\n"
                    "Write a concise sprint journal summary (3-5 sentences) for a team retro. "
                    "Cover: what was built, any notable challenges, mood trend, and key decisions. "
                    "Be factual and direct. No fluff"
                ),
            }]
        )
        return message.content[0].text


    def _rule_based_synthesis(self, entries: list[JournalEntry], adrs: list[ADR]) -> str:
        if not entries:
            return "No journal entries this sprint"

        moods = [e.mood for e in entries if e.mood]
        avg_mood = sum(moods) / len(moods) if moods else None

        tags: dict[str, int] = {}
        for e in entries:
            for tag in (e.tags or []):
                tags[tag] = tags.get(tag, 0) + 1
        top_tags = sorted(tags.items(), key=lambda x: -x[1])[:3]

        adr_lines = "\n".join(f" • {a.title} [ADR #{a.sequence}]" for a in adrs) or "  None"
        tag_str = ", ".join(f"{t} ({c})" for t, c in top_tags) or "none"
        mood_str = f"{avg_mood:.1f}/5" if avg_mood else "not logged"

        return (
            f"**Sprint Journal Summary**\n"
            f"{len(entries)} entries · Mood avg: {mood_str}\n\n"
            f"**Key decisions:**\n{adr_lines}\n\n"
            f"**Recurring themes:** {tag_str}"
        )


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