from __future__ import annotations

from datetime import datetime, timezone, timedelta

import discord
import structlog
from discord import app_commands
from discord.ext import commands

from app import database
from app.models.journal import JournalEntryCreate
from app.services.journal_service import JournalService
from app.services.project_service import ProjectService
from app.services.xp_service import XPService
from app.embeds.journal_embed import *
from app.utils.guards import require_member

log = structlog.get_logger()

_MOOD_CHOICES = [
    app_commands.Choice(name="😩 1 — Struggling", value=1),
    app_commands.Choice(name="😕 2 — A bit lost", value=2),
    app_commands.Choice(name="😐 3 — Getting there", value=3),
    app_commands.Choice(name="😊 4 — Feeling good", value=4),
    app_commands.Choice(name="🔥 5 — In flow!", value=5),
]


class JournalCog(commands.Cog):
    journal = app_commands.Group(name="journal", description="Dev Journal commands")
    journal_adr = app_commands.Group(
        name="adr",
        description="Architectural Decision Records",
        parent=journal
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _journal_svc(self) -> JournalService:
        db = database.get_db()
        return JournalService(db, xp_svc=XPService(db))

    def _project_svc(self) -> ProjectService:
        svc = getattr(self.bot, "services", {}).get("project")
        if svc is not None:
            return svc
        return ProjectService(database.get_db())


    @journal.command(name="entry", description="Log what you build or learned today")
    @app_commands.describe(
        text="Your journal entry - what did you do, build or learn?",
        mood="Your energy level right now",
        tags="Space-separated tags e.g. #bug #backend #godot"
    )
    @app_commands.choices(mood=_MOOD_CHOICES)
    async def journal_entry(
            self,
            interaction: discord.Interaction,
            text: str,
            mood: app_commands.Choice[int] | None = None,
            tags: str = ""
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            member = await require_member(interaction)
        except RuntimeError:
            return

        project = await self._project_svc().resolve_active_or_abort(member.id, interaction)
        if not project:
            return

        tag_list = [t.strip() for t in tags.split() if t.strip()] if tags else []

        svc = self._journal_svc()
        try:
            entry = await svc.add_entry(JournalEntryCreate(
                member_id=member.id,
                project_id=project.id,
                entry_type="freeform",
                content=text,
                mood=mood.value if mood else None,
                tags=tag_list
            ))
        except Exception as e:
            log.error("journal_entry_error", error=str(e))
            await interaction.followup.send("Something went wrong saving your entry", ephemeral=True)
            return

        embed = build_entry_embed(entry, project_name=project.name)
        await interaction.followup.send(embed=embed, ephemeral=True)


    @journal.command(name="decision", description="Record an architectural decision (ADR)")
    @app_commands.describe(
        title="Short title for this decision",
        context="What problem or situation led to this decision?",
        decision="What did you decide to do?",
        alternatives="What other options did you consider? (optional)",
    )
    async def journal_decision(
            self,
            interaction: discord.Interaction,
            title: str,
            context: str,
            decision: str,
            alternatives: str | None = None
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            member = await require_member(interaction)
        except RuntimeError:
            return

        project = await self._project_svc().resolve_active_or_abort(member.id, interaction)
        if not project:
            return

        svc = self._journal_svc()
        try:
            _, adr = await svc.add_adr(
                member_id=member.id,
                project_id=project.id,
                title=title,
                context=context,
                decision=decision,
                alternatives=alternatives
            )
        except Exception as e:
            log.error("journal_decision_error", error=str(e))
            await interaction.followup.send("Something went wrong saving your decision", ephemeral=True)
            return

        embed = build_adr_embed(adr, project_name=project.name)
        await interaction.followup.send(embed=embed, ephemeral=True)


    @journal.command(name="today", description="See all your journal entries for today")
    async def journal_today(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            member = await require_member(interaction)
        except RuntimeError:
            return

        project = await self._project_svc().resolve_active_or_abort(member.id, interaction)
        if not project:
            return

        svc = self._journal_svc()
        entries = await svc.get_today(member.id, project.id)
        embed = build_today_embed(entries, project_name=project.name)
        await interaction.followup.send(embed=embed, ephemeral=True)


    @journal.command(name="week", description="See this week's entries with a mood trend")
    async def journal_week(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            member = await require_member(interaction)
        except RuntimeError:
            return

        project = await self._project_svc().resolve_active_or_abort(member.id, interaction)
        if not project:
            return

        svc = self._journal_svc()
        entries = await svc.get_week(member.id, project.id)
        embed = build_week_embed(entries, project_name=project.name)
        await interaction.followup.send(embed=embed, ephemeral=True)


    @journal.command(name="search", description="Full-text search across your journal entries")
    @app_commands.describe(query="Keyword or phrase to search for")
    async def journal_search(
            self,
            interaction: discord.Interaction,
            query: str
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            member = await require_member(interaction)
        except RuntimeError:
            return

        project = await self._project_svc().get_active_project(member.id)

        svc = self._journal_svc()
        try:
            entries = await svc.searc
